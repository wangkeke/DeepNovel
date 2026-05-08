"""
bible_update_node：更新实体知识库 + 持久化章节正文
1. 调用 LLM 从正文提取结构化实体变化和事件
2. 用 entity_db 更新 entity_cards / event_timeline 表
3. 生成轻量 entity_summary 写回 novel_projects
4. 若为本批最后一个节点，生成 last_batch_ending 写回 novel_projects
5. 将本节点正文写入 chapters 表
"""
from __future__ import annotations
import json
import aiosqlite
from langgraph.types import StreamWriter
from schemas.state import CreationState
from prompts.creation.bible_update import (
    BIBLE_UPDATE_SYSTEM, BIBLE_UPDATE_USER_TEMPLATE,
    LAST_BATCH_ENDING_SYSTEM, LAST_BATCH_ENDING_USER_TEMPLATE,
)
from prompts.creation.ebd_settlement import (
    EBD_SETTLEMENT_SYSTEM,
    EBD_SETTLEMENT_USER_TEMPLATE,
)
from prompts.common.emotional_bond_doctrine import core_cast_ebd_seed_for_name
from utils.llm import call_llm, call_llm_json
from utils.chapter_excerpt import excerpt_head_tail
from memory.entity_db import (
    upsert_entity_card, append_event,
    build_entity_summary, save_confirmed_char_cards,
    increment_key_event_count, get_newly_promoted_chars,
    is_core_character, upsert_character_ability,
    get_character_cards_with_tendencies, apply_ebd_delta,
    get_all_entity_names,
)
from memory.db import (
    save_foreshadow, collect_foreshadow, foreshadow_exists_by_surface,
    update_foreshadow_mention, get_noun_foreshadows,
    upsert_lexicon_entry,
)
from config import DB_PATH
from utils.mental_core import normalize_mental_core_dict
from utils.protagonist_card_normalize import normalize_protagonist_card_for_state
from prompts.creation.world_build import CHAR_CARD_DRAFT_SYSTEM, CHAR_CARD_DRAFT_USER_TEMPLATE
from prompts.creation.narrative_memory import CONSOLIDATION_SYSTEM, CONSOLIDATION_USER
from utils.narrative_memory import ensure_memory_streams
from utils.text_metrics import prose_char_count
from utils.path_relay import effective_chapter_draft
import logging
import uuid as _uuid

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 任务生命周期管理（补丁 D）
# ──────────────────────────────────────────────────────────────────────────────

_QUEST_LIFECYCLE_SYSTEM = """你是一位故事逻辑分析师。
你的任务是：根据刚完成的章节正文，对主角的活跃任务栈进行生命周期检查。
只输出 JSON，不加任何前言。"""

_QUEST_LIFECYCLE_USER_TEMPLATE = """## 本章正文摘要
{draft_excerpt}

## 当前活跃任务列表
{active_quests_json}

## 任务

对每个活跃任务执行四项检查，输出任务栈更新指令。

返回 JSON：
{{
  "completed_quests": ["本章满足 completion_condition 的 quest_id 列表"],
  "failed_quests": ["本章满足 failure_condition 的 quest_id 列表"],
  "sub_goal_updates": [
    {{
      "quest_id": "更新子目标的任务ID",
      "new_sub_goal": "本章推进后的新子目标（具体可执行的下一步）"
    }}
  ],
  "new_quests": [
    {{
      "quest_name": "新任务名称",
      "quest_origin": "触发原因（结合本章内容）",
      "urgency_level": "critical|high|medium|low",
      "current_sub_goal": "当前子目标",
      "layer": "immediate|short_term",
      "completion_condition": "完成条件",
      "failure_condition": "失败条件或null",
      "emotional_weight": "对主角的情感意义"
    }}
  ]
}}

判断规则：
- completion_condition 是否在本章正文中已经发生 → 标记为 completed
- failure_condition 是否在本章正文中已经发生 → 标记为 failed
- 任务仍在进行中但本章推进了子目标 → 更新 current_sub_goal
- 本章出现新的角色危机/承诺债务/处境改变/词条关键变化 → 推入新任务
- core_drive 层任务永远不完成，不列入检查范围
- arc_level 层任务除非有极其明显的事件，否则不轻易完成"""


async def _check_quest_lifecycle(
    draft: str,
    active_quest_stack: list,
    global_seq: int,
    chapter_id: str,
) -> tuple[list, dict]:
    """
    对活跃任务执行生命周期检查，返回 (updated_stack, quest_stack_updates)。
    """
    if not isinstance(active_quest_stack, list):
        return active_quest_stack, {}

    active = [
        q for q in active_quest_stack
        if isinstance(q, dict) and q.get("status") == "active"
        and q.get("layer") not in ("core_drive",)
    ]
    if not active:
        return active_quest_stack, {}

    try:
        excerpt = excerpt_head_tail(draft, head_chars=2000, tail_chars=2000)
        active_json = json.dumps(active, ensure_ascii=False, indent=2)
        raw = await call_llm_json(
            _QUEST_LIFECYCLE_SYSTEM,
            _QUEST_LIFECYCLE_USER_TEMPLATE.format(
                draft_excerpt=excerpt,
                active_quests_json=active_json,
            ),
            max_tokens=2000,
        )
    except Exception as exc:
        logger.warning("任务生命周期检查 LLM 失败: %s", exc)
        return active_quest_stack, {}

    if not isinstance(raw, dict):
        return active_quest_stack, {}

    completed_ids = set(raw.get("completed_quests") or [])
    failed_ids = set(raw.get("failed_quests") or [])
    sub_updates = {
        u.get("quest_id"): u.get("new_sub_goal")
        for u in (raw.get("sub_goal_updates") or [])
        if isinstance(u, dict) and u.get("quest_id")
    }

    updated_stack = []
    for q in active_quest_stack:
        if not isinstance(q, dict):
            updated_stack.append(q)
            continue
        qid = q.get("quest_id", "")
        q = dict(q)
        if qid in completed_ids and q.get("layer") != "core_drive":
            q["status"] = "completed"
            q["completed_chapter"] = chapter_id
            # 处理演化任务
            evo = q.get("evolution_on_completion")
            if isinstance(evo, dict) and evo.get("new_quest_name"):
                new_qid = f"AQ_EVO_{_uuid.uuid4().hex[:6].upper()}"
                updated_stack.append({
                    "quest_id": new_qid,
                    "quest_name": evo["new_quest_name"],
                    "quest_origin": f"演化自 {qid}（完成触发）",
                    "urgency_level": evo.get("new_urgency", "high"),
                    "deadline_note": None,
                    "current_sub_goal": evo.get("trigger_note", "")[:150],
                    "layer": evo.get("new_layer", "short_term"),
                    "completion_condition": "",
                    "failure_condition": None,
                    "evolution_on_completion": None,
                    "evolution_on_failure": None,
                    "status": "active",
                    "planted_chapter": chapter_id,
                    "emotional_weight": f"由「{q.get('quest_name', '')}完成」演化而来。",
                })
        elif qid in failed_ids and q.get("layer") != "core_drive":
            q["status"] = "failed"
            q["failed_chapter"] = chapter_id
            evo = q.get("evolution_on_failure")
            if isinstance(evo, dict) and evo.get("new_quest_name"):
                new_qid = f"AQ_EVO_{_uuid.uuid4().hex[:6].upper()}"
                updated_stack.append({
                    "quest_id": new_qid,
                    "quest_name": evo["new_quest_name"],
                    "quest_origin": f"演化自 {qid}（失败触发）",
                    "urgency_level": evo.get("new_urgency", "critical"),
                    "deadline_note": None,
                    "current_sub_goal": evo.get("trigger_note", "")[:150],
                    "layer": evo.get("new_layer", "immediate"),
                    "completion_condition": "",
                    "failure_condition": None,
                    "evolution_on_completion": None,
                    "evolution_on_failure": None,
                    "status": "active",
                    "planted_chapter": chapter_id,
                    "emotional_weight": f"由「{q.get('quest_name', '')}失败」演化而来。",
                })
        elif qid in sub_updates:
            new_sg = sub_updates[qid]
            if new_sg and str(new_sg).strip():
                q["current_sub_goal"] = str(new_sg).strip()[:150]
        updated_stack.append(q)

    # 推入新任务
    new_quests_raw = raw.get("new_quests") or []
    for nq in new_quests_raw:
        if not isinstance(nq, dict) or not (nq.get("quest_name") or "").strip():
            continue
        new_qid = f"AQ_NEW_{_uuid.uuid4().hex[:6].upper()}"
        updated_stack.append({
            "quest_id": new_qid,
            "quest_name": str(nq.get("quest_name") or "")[:60],
            "quest_origin": str(nq.get("quest_origin") or "bible_update 新涌现")[:150],
            "urgency_level": nq.get("urgency_level", "high"),
            "deadline_note": None,
            "current_sub_goal": str(nq.get("current_sub_goal") or "")[:150],
            "layer": nq.get("layer", "short_term"),
            "completion_condition": str(nq.get("completion_condition") or "")[:200],
            "failure_condition": str(nq.get("failure_condition") or "")[:150] or None,
            "evolution_on_completion": None,
            "evolution_on_failure": None,
            "status": "active",
            "planted_chapter": chapter_id,
            "emotional_weight": str(nq.get("emotional_weight") or "")[:200],
        })

    quest_stack_updates = {
        "completed_quests": list(completed_ids),
        "failed_quests": list(failed_ids),
        "new_quests_added": [q.get("quest_id") for q in new_quests_raw if isinstance(q, dict)],
        "sub_goal_updates": raw.get("sub_goal_updates") or [],
    }
    return updated_stack, quest_stack_updates

# v4.3 补丁：配角 entity_card 与主角卡同构；占位/初建时写入空 capabilities，便于增量合并与 event_chain 读取
_DEFAULT_CAPABILITIES_STUB: dict = {
    "combat_skills": [],
    "dao_foundation": None,
    "signature_items": [],
    "golden_finger": {
        "has_golden_finger": False,
        "gf_type": None,
        "core_ability": None,
        "activation_condition": None,
        "cost_and_limit": None,
        "exposure_risk": None,
        "current_state": None,
    },
    "unique_traits": [],
}


def _ensure_capabilities_on_character_patch(data_patch: dict) -> dict:
    """若 LLM 未输出 capabilities，补默认结构，避免库内缺键。"""
    if not isinstance(data_patch.get("capabilities"), dict):
        out = dict(data_patch)
        out["capabilities"] = dict(_DEFAULT_CAPABILITIES_STUB)
        return out
    return data_patch


async def _merge_capabilities_delta_into_character_patch(
    project_id: str,
    name: str,
    upd: dict,
    data_patch: dict,
) -> None:
    """将 entity_updates.capabilities_delta 合并进 data_patch.capabilities（不写裸 delta 键入 DB）。"""
    cap_delta = upd.get("capabilities_delta")
    if not isinstance(cap_delta, dict):
        return
    if not project_id or not name:
        return
    if not any(
        cap_delta.get(k)
        for k in (
            "golden_finger_state_change",
            "items_status_change",
            "trait_triggered",
            "capability_undercurrent_progress",
        )
    ):
        return
    existing = await _load_character_data_json(project_id, name)
    base = existing.get("capabilities") if isinstance(existing.get("capabilities"), dict) else {}
    caps = {**_DEFAULT_CAPABILITIES_STUB, **base}
    gf = {**_DEFAULT_CAPABILITIES_STUB["golden_finger"], **(caps.get("golden_finger") or {})}
    gch = cap_delta.get("golden_finger_state_change")
    if gch:
        gf["current_state"] = str(gch).strip()[:500]
    caps["golden_finger"] = gf
    items_change = cap_delta.get("items_status_change")
    if isinstance(items_change, list) and items_change:
        caps["last_signature_items_change_log"] = [str(x) for x in items_change[:8]]
    tr = cap_delta.get("trait_triggered")
    if tr:
        caps["last_trait_double_edge_triggered"] = str(tr).strip()[:300]
    uc = cap_delta.get("capability_undercurrent_progress")
    if uc:
        caps["last_undercurrent_progress_note"] = str(uc).strip()[:400]
    data_patch["capabilities"] = caps


def _state_karmic_ledger_from_merged_bible(merged_bible: dict) -> list:
    """同步顶层 state.karmic_ledger，供 event_chain_gen 等只读 state 的节点使用。"""
    if not isinstance(merged_bible, dict):
        return []
    inv = merged_bible.get("karmic_seeds_inventory")
    if isinstance(inv, list) and inv:
        return list(inv)[-200:]
    out: list[dict] = []
    for f in merged_bible.get("planted_foreshadows") or []:
        if not isinstance(f, dict):
            continue
        fid = (f.get("foreshadow_id") or "").strip()
        surf = (f.get("surface_meaning") or f.get("surface_expression") or "").strip()
        if not fid and not surf:
            continue
        out.append(
            {
                "seed_id": fid or surf[:48],
                "surface_meaning": surf,
                "mentioned_by": f.get("mentioned_by", ""),
                "status": "harvested" if f.get("collected_at_node") else "planted",
                "planted_at_seq": int(f.get("planted_at_node") or 0),
                "collected_at_seq": int(f.get("collected_at_node") or 0),
                "urgency": f.get("urgency", "latent"),
                "story_potential": f.get("story_potential", ""),
            }
        )
    return out[-200:]


async def _load_character_data_json(project_id: str, name: str) -> dict:
    """读取已有人物卡 data_json（用于 mental_core 增量合并）。"""
    if not project_id or not name:
        return {}
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cur = await conn.execute(
                "SELECT data_json FROM entity_cards "
                "WHERE project_id=? AND card_type='character' AND name=?",
                (project_id, name),
            )
            row = await cur.fetchone()
            if not row or not row[0]:
                return {}
            return json.loads(row[0])
    except Exception:
        return {}


def _normalize_targeting_degree_in_patch(data_patch: dict) -> None:
    """LLM 可能写 threat_level；统一为 targeting_degree 0～100。"""
    if not isinstance(data_patch, dict):
        return
    if "threat_level" in data_patch and "targeting_degree" not in data_patch:
        data_patch["targeting_degree"] = data_patch.pop("threat_level")
    if "targeting_degree" not in data_patch:
        return
    try:
        data_patch["targeting_degree"] = max(
            0, min(100, int(round(float(data_patch["targeting_degree"]))))
        )
    except (TypeError, ValueError):
        data_patch.pop("targeting_degree", None)


def _collect_character_names_from_bible_result(result: dict) -> list[str]:
    """合并 LLM 明示名单与 entity_updates / 事件人物，去重保序。"""
    out: list[str] = []
    seen: set[str] = set()
    for x in result.get("named_characters_in_scene") or []:
        s = (x or "").strip() if isinstance(x, str) else str(x or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    for upd in result.get("entity_updates") or []:
        if (upd.get("card_type") or "character") != "character":
            continue
        s = (upd.get("name") or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    for ev in result.get("new_events") or []:
        for x in ev.get("characters") or []:
            if isinstance(x, str):
                s = x.strip()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


async def _generate_full_char_cards_for_new(
    project_id: str,
    new_names: list[str],
    protagonist_name: str,
    draft: str,
    global_seq: int,
    entity_updates: list[dict],
) -> None:
    """
    对首次出场且戏份达标的新配角（非路人）生成完整 PROMPT 3 同构角色卡并入库。
    戏份判断：在 entity_updates 里有实质内容（chapter_behavior_note / stance / role 非 unknown）。
    """
    if not project_id or not new_names:
        return
    prot = (protagonist_name or "").strip()
    # 戏份判断：entity_updates 中有实质信息
    significant: list[str] = []
    eu_map: dict[str, dict] = {
        str(u.get("name") or "").strip(): u
        for u in (entity_updates or [])
        if isinstance(u, dict) and (u.get("card_type") or "character") == "character"
    }
    for nm in new_names:
        if not nm or nm == prot:
            continue
        eu = eu_map.get(nm, {})
        note = str(eu.get("chapter_behavior_note") or "").strip()
        role = str(eu.get("current_role") or "unknown").strip()
        stance = str(eu.get("stance_to_protagonist") or "").strip()
        # 有行为注记 or 有明确角色 or 有立场描述 → 视为重要配角
        if note or role not in ("unknown", "") or (stance and stance != "待观察（bible_update 逐章修订）"):
            significant.append(nm)

    if not significant:
        return

    char_list = "\n".join(f"- {n}" for n in significant)
    draft_excerpt = excerpt_head_tail(draft, head_chars=3000, tail_chars=3000)
    try:
        result = await call_llm_json(
            CHAR_CARD_DRAFT_SYSTEM,
            CHAR_CARD_DRAFT_USER_TEMPLATE.format(
                draft_excerpt=draft_excerpt,
                character_names=char_list,
            ),
        )
    except Exception as e:
        logger.warning("新配角全卡生成失败: %s", e)
        return

    cards: list[dict] = []
    if isinstance(result, dict):
        cards = result.get("character_cards", [])
    elif isinstance(result, list):
        cards = result

    for card in cards:
        if not isinstance(card, dict):
            continue
        nm = (card.get("standard_name") or "").strip()
        if not nm:
            continue
        normalize_protagonist_card_for_state(card)
        aliases = card.pop("aliases", []) or []
        data_patch: dict = _ensure_capabilities_on_character_patch(
            {**card, "first_seen_context": f"第{global_seq}节（全卡初建）"}
        )
        try:
            await upsert_entity_card(
                project_id=project_id,
                card_type="character",
                name=nm,
                data_patch=data_patch,
                seq=global_seq,
                aliases=aliases,
            )
        except Exception as e:
            logger.warning("新配角全卡入库失败 (%s): %s", nm, e)

    # 对 significant 中未被 LLM 返回的名字，建最小占位卡兜底
    card_names = {(c.get("standard_name") or "").strip() for c in cards if isinstance(c, dict)}
    for nm in significant:
        if nm not in card_names:
            try:
                await upsert_entity_card(
                    project_id=project_id,
                    card_type="character",
                    name=nm,
                    data_patch={
                        **_DEFAULT_CAPABILITIES_STUB,
                        "background_summary": f"第{global_seq}节首次出场，详情随章节补全",
                        "current_role": "unknown",
                        "first_seen_context": f"第{global_seq}节",
                    },
                    seq=global_seq,
                )
            except Exception:
                pass


async def _ensure_scene_character_stubs(
    project_id: str,
    names: list[str],
    protagonist_name: str,
    global_seq: int,
    draft: str = "",
    entity_updates: list[dict] | None = None,
) -> None:
    """
    entity_cards 中尚不存在的人物：
    - 重要配角（戏份达标）→ 调 LLM 生成完整 PROMPT 3 同构角色卡
    - 其余 → 最小占位卡，随后由 entity_updates 深度合并
    """
    if not project_id or not names:
        return
    known = set(await get_all_entity_names(project_id))
    prot = (protagonist_name or "").strip()
    new_names: list[str] = []
    for nm in names:
        if nm and nm != prot and nm not in known:
            known.add(nm)
            new_names.append(nm)
    if not new_names:
        return

    # Step A：重要配角 → 全卡生成
    await _generate_full_char_cards_for_new(
        project_id, new_names, prot, draft, global_seq, entity_updates or []
    )

    # Step B：已建全卡的不再重复建占位；其余（全卡生成漏掉的）补最小占位
    known_after = set(await get_all_entity_names(project_id))
    for nm in new_names:
        if nm in known_after:
            continue
        try:
            await upsert_entity_card(
                project_id=project_id,
                card_type="character",
                name=nm,
                data_patch={
                    **_DEFAULT_CAPABILITIES_STUB,
                    "background_summary": f"第{global_seq}节于正文首次建档，详情随章节补全",
                    "current_role": "unknown",
                    "stance_to_protagonist": "待观察（bible_update 逐章修订）",
                    "first_seen_context": f"第{global_seq}节",
                },
                seq=global_seq,
            )
        except Exception as e:
            logger.warning("首次建档占位失败 (%s): %s", nm, e)


# ──────────────────────────────────────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _save_chapter_to_db(
    project_id: str,
    seq: int,
    node_name: str,
    content: str,
    event_path_chain: list[str],
) -> None:
    """
    章节写完后：
    1. 查找对应的 story_nodes 行（按全局 seq）
    2. 更新 story_nodes：写入 event_path_chain，status → done
    3. INSERT chapters：关联 node_id

    seq 由调用方从 story_path[current_idx]["_seq"] 取得，是跨批次全局序号。
    """
    try:
        from ulid import ULID
        chapter_id = str(ULID())
    except ImportError:
        import uuid
        chapter_id = str(uuid.uuid4())

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cursor = await conn.execute(
            "SELECT node_id FROM story_nodes WHERE project_id = ? AND seq = ?",
            (project_id, seq),
        )
        row = await cursor.fetchone()
        node_id = row[0] if row else None

        if node_id:
            await conn.execute(
                """UPDATE story_nodes
                   SET event_path_chain = ?, status = 'done'
                   WHERE node_id = ?""",
                (json.dumps(event_path_chain, ensure_ascii=False), node_id),
            )

        await conn.execute(
            """INSERT OR REPLACE INTO chapters
               (chapter_id, project_id, node_id, seq, node_name, content, word_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (chapter_id, project_id, node_id, seq, node_name, content, prose_char_count(content)),
        )
        await conn.commit()


async def _update_project_summary(
    project_id: str,
    entity_summary: str,
    last_batch_ending: dict | None = None,
    last_action_intent: str | None = None,
) -> None:
    """更新 novel_projects 的 entity_summary、last_batch_ending、last_action_intent。"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        # 构建更新：entity_summary 必更新，last_batch_ending 和 last_action_intent 可选
        updates = ["entity_summary = ?", "updated_at = datetime('now')"]
        params: list = [entity_summary]
        if last_batch_ending is not None:
            updates.append("last_batch_ending = ?")
            params.append(json.dumps(last_batch_ending, ensure_ascii=False))
        if last_action_intent is not None:
            updates.append("last_action_intent = ?")
            params.append(last_action_intent)
        params.append(project_id)
        await conn.execute(
            f"UPDATE novel_projects SET {', '.join(updates)} WHERE project_id = ?",
            params,
        )
        await conn.commit()


def _resolve_bible_character_key(raw_name: str, bible_characters: dict) -> str:
    """
    将 path_state_extract 提供的 character_name 对齐到 bible.characters 的真实 dict 键。
    优先键精确匹配，再比 standard_name / name / aliases（全相等，避免跨名误绑）。
    若无匹配则退回原串（新角可由上游后续补卡）。
    """
    raw = (raw_name or "").strip()
    if not raw:
        return ""
    if not isinstance(bible_characters, dict):
        return raw
    if raw in bible_characters:
        return raw
    for k, v in bible_characters.items():
        if not isinstance(v, dict):
            continue
        sk = str(k).strip()
        if not sk:
            continue
        sn = str(v.get("standard_name") or "").strip()
        vn = str(v.get("name") or "").strip()
        if raw == sk:
            return sk
        if sn and raw == sn:
            return sk
        if vn and raw == vn:
            return sk
        for al in v.get("aliases") or []:
            if raw == str(al).strip():
                return sk
    return raw


def _character_name_hits_draft(card: dict, dict_key: str, draft: str) -> bool:
    """事件结算时判断该 bible 角色是否在正文中出场（弱匹配：任一常用名字段为子串）。"""
    if not (draft or "").strip():
        return True
    cand: set[str] = set()
    for fld in ("standard_name", "name"):
        v = card.get(fld)
        if v is not None and str(v).strip():
            cand.add(str(v).strip())
    if dict_key.strip():
        cand.add(dict_key.strip())
    if not cand:
        return False
    d = draft
    return any(n in d for n in cand if len(n) >= 1)


async def _apply_patch_i_chapter_narrative_memory(
    state: CreationState,
    project_id: str,
    global_seq: int,
    *,
    event_boundary_flush: bool = False,
    chapter_draft: str = "",
) -> dict[str, dict]:
    """
    补丁 I §四：pending_inner_stream_chunks → short_term；（仅事件末拍）short_term + 近期 long
    → LLM 合并 → long_term，并强制清空 short_term。
    多路径下同事件只在本事件最后一条路径收尾时做固化，避免短栈被提前清空。
    """
    pp = dict(state.get("path_progress") or {}) if isinstance(state.get("path_progress"), dict) else {}
    chunks = list(pp.get("pending_inner_stream_chunks") or [])
    bible = state.get("bible") or {}
    chars_map = bible.get("characters") or {}
    if not isinstance(chars_map, dict):
        chars_map = {}
    base: dict[str, dict] = {
        str(k): ensure_memory_streams(dict(v))
        for k, v in chars_map.items()
        if isinstance(v, dict) and str(k).strip()
    }
    if not chunks and not base:
        return {}

    for ch in chunks:
        if not isinstance(ch, dict):
            continue
        raw_nm = str(ch.get("character_name") or "").strip()
        sl = str(ch.get("inner_slice") or "").strip()
        if not raw_nm or not sl:
            continue
        nm = _resolve_bible_character_key(raw_nm, chars_map)
        if not nm:
            continue
        if nm not in base:
            base[nm] = ensure_memory_streams({"standard_name": raw_nm, "name": raw_nm})
        card = base[nm]
        st = list(card.get("short_term_stream") or [])
        st.append(sl)
        card["short_term_stream"] = st[-40:]

    if event_boundary_flush and chapter_draft.strip():
        seen: set[str] = set(base.keys())
        for k, v in (bible.get("characters") or {}).items():
            if not isinstance(v, dict):
                continue
            key = str(k).strip()
            if not key:
                continue
            card0 = ensure_memory_streams(dict(v))
            if _character_name_hits_draft(card0, key, chapter_draft) and key not in seen:
                base[key] = card0
                seen.add(key)

    if not event_boundary_flush:
        return base

    for nm, card in list(base.items()):
        st = list(card.get("short_term_stream") or [])
        if not st:
            continue
        # 事件边界上不再依赖正文命中：Stub/极短梗概会导致名字匹配失败、long_term 永不合。
        # 凡本事件已累计的 short_term_stream，一律做固化合并（若有正文且明确未出场可再收紧，见上「扩展出场」逻辑）。
        lt_full = list(card.get("long_term_stream") or [])
        recent = lt_full[-3:] if lt_full else []
        long_term_recent = (
            "\n".join(f"- {s}" for s in recent)
            if recent
            else "（尚无既往长篇自传条目。）"
        )
        slices_text = "\n".join(f"- {i + 1}. {s}" for i, s in enumerate(st))
        memoir = ""
        try:
            raw = await call_llm_json(
                CONSOLIDATION_SYSTEM,
                CONSOLIDATION_USER.format(
                    character_name=nm,
                    long_term_recent=long_term_recent,
                    slices_text=slices_text,
                ),
                max_tokens=700,
            )
            if isinstance(raw, dict):
                memoir = str(raw.get("event_memoir") or "").strip()
        except Exception as e:
            logger.warning("事件记忆固化失败 (%s): %s", nm, e)
        card["short_term_stream"] = []
        if memoir and memoir != "无":
            lt = list(card.get("long_term_stream") or [])
            lt.append(memoir)
            card["long_term_stream"] = lt[-200:]
            if project_id:
                try:
                    ent_nm = (
                        str(card.get("standard_name") or card.get("name") or nm).strip() or nm
                    )
                    await upsert_entity_card(
                        project_id,
                        "character",
                        ent_nm,
                        {"long_term_stream": [memoir]},
                        seq=global_seq,
                    )
                except Exception as e:
                    logger.warning("long_term_stream 入库失败 (%s): %s", nm, e)
        base[nm] = card

    return base


# ──────────────────────────────────────────────────────────────────────────────
# Main node
# ──────────────────────────────────────────────────────────────────────────────

async def bible_update_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "bible_update"})

    # 与 narrative_extract 对齐：v4.3 多路径下 current_draft 可能被清空，合并稿在 all_paths_text
    draft       = effective_chapter_draft(state)
    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    project_id  = state.get("project_id", "")

    current_node = story_path[current_idx] if current_idx < len(story_path) else {}
    node_name    = current_node.get("node_name", f"节点{current_idx + 1}")
    global_seq   = current_node.get("_seq", current_idx + 1)

    # 当前实体摘要（用于 LLM 上下文）
    entity_summary = await build_entity_summary(project_id) if project_id else ""

    # ── Step 1: LLM 提取实体变化 ──
    user_prompt = BIBLE_UPDATE_USER_TEMPLATE.format(
        seq=global_seq,
        node_name=node_name,
        current_draft=draft,
        entity_summary=entity_summary or "（暂无实体记录）",
    )
    result = await call_llm_json(BIBLE_UPDATE_SYSTEM, user_prompt)
    if not isinstance(result, dict):
        result = {}

    if project_id:
        ch_names = _collect_character_names_from_bible_result(result)
        await _ensure_scene_character_stubs(
            project_id,
            ch_names,
            (state.get("protagonist_name") or "").strip(),
            global_seq,
            draft=draft,
            entity_updates=result.get("entity_updates") or [],
        )

    pending_role_shifts: list[dict] = []
    pending_trait_interaction_update: list[dict] = []

    # ── Step 2: 写入实体卡片 ──
    if project_id:
        core_cast = state.get("core_cast") or {}
        for upd in result.get("entity_updates", []):
            card_type = upd.get("card_type", "character")
            name = upd.get("name", "").strip()
            if not name:
                continue
            em_delta = upd.get("emotional_capacity_delta")
            data_patch = {
                k: v
                for k, v in upd.items()
                if k not in ("name", "card_type", "aliases")
                and k != "emotional_capacity_delta"
                and k != "capabilities_delta"
                and v is not None
                and v != ""
            }
            if card_type == "character":
                await _merge_capabilities_delta_into_character_patch(
                    project_id, name, upd, data_patch
                )
                _normalize_targeting_degree_in_patch(data_patch)
                llm_mc_in_patch = isinstance(data_patch.get("mental_core"), dict)
                if project_id and em_delta is not None:
                    try:
                        d_int = int(em_delta)
                    except (TypeError, ValueError):
                        d_int = 0
                    if d_int != 0:
                        existing_d = await _load_character_data_json(project_id, name)
                        llm_mc = data_patch.pop("mental_core", None)
                        mc = normalize_mental_core_dict(existing_d.get("mental_core"))
                        if isinstance(llm_mc, dict):
                            mc = normalize_mental_core_dict({**mc, **llm_mc})
                        ec = int(mc.get("emotional_capacity", 100))
                        mc["emotional_capacity"] = max(0, min(100, ec + d_int))
                        data_patch["mental_core"] = mc
                    elif llm_mc_in_patch:
                        data_patch["mental_core"] = normalize_mental_core_dict(
                            data_patch["mental_core"]
                        )
                elif llm_mc_in_patch:
                    data_patch["mental_core"] = normalize_mental_core_dict(
                        data_patch["mental_core"]
                    )
                seed = core_cast_ebd_seed_for_name(
                    core_cast if isinstance(core_cast, dict) else {}, name,
                )
                if seed:
                    for sk, sv in seed.items():
                        if sv in (None, ""):
                            continue
                        if sk == "ebd_crack" and not sv:
                            continue
                        if sk not in data_patch:
                            data_patch[sk] = sv
            aliases = upd.get("aliases") or []
            try:
                await upsert_entity_card(
                    project_id=project_id,
                    card_type=card_type,
                    name=name,
                    data_patch=data_patch,
                    seq=global_seq,
                    aliases=aliases,
                )
            except Exception as e:
                logger.warning(f"upsert_entity_card 失败 ({name}): {e}")

        # EBD 章节结算（正文驱动，增量写回人物卡）
        involved_ebd: set[str] = set()
        for upd in result.get("entity_updates", []):
            if (upd.get("card_type") or "character") == "character":
                n = (upd.get("name") or "").strip()
                if n:
                    involved_ebd.add(n)
        for ev in result.get("new_events", []):
            for n in ev.get("characters") or []:
                if isinstance(n, str) and n.strip():
                    involved_ebd.add(n.strip())
        prot_n = (state.get("protagonist_name") or "").strip()
        if prot_n:
            involved_ebd.discard(prot_n)
        if involved_ebd and draft.strip() and len(draft) > 80:
            try:
                cards_e = await get_character_cards_with_tendencies(
                    project_id, list(involved_ebd),
                )
                lines_e: list[str] = []
                got_names = {c.get("name") for c in cards_e}
                for c in cards_e:
                    td = c.get("targeting_degree")
                    td_s = f" TD={td}" if td is not None and str(td).strip() != "" else ""
                    lines_e.append(
                        f"- {c.get('name')}: EBD={c.get('ebd_to_protagonist', 0)} "
                        f"bond={c.get('ebd_bond_kind', '')} type={c.get('ebd_type', '')}{td_s}"
                    )
                for nm in involved_ebd:
                    if nm in got_names:
                        continue
                    sd = core_cast_ebd_seed_for_name(
                        core_cast if isinstance(core_cast, dict) else {}, nm,
                    )
                    lines_e.append(
                        f"- {nm}: EBD={sd.get('ebd_to_protagonist', 0)} "
                        f"bond={sd.get('ebd_bond_kind', '')} type={sd.get('ebd_type', '')}"
                        f"（尚未建卡，仅供参考）"
                    )
                st_user = EBD_SETTLEMENT_USER_TEMPLATE.format(
                    seq=global_seq,
                    chapter_excerpt=excerpt_head_tail(
                        draft,
                        head_chars=4500,
                        tail_chars=5500,
                    ),
                    protagonist_name=prot_n or "（未知）",
                    char_lines="\n".join(lines_e) if lines_e else "（无）",
                )
                settled_raw = await call_llm_json(EBD_SETTLEMENT_SYSTEM, st_user)
                settled_list = settled_raw
                if isinstance(settled_raw, dict):
                    settled_list = settled_raw.get("changes") or settled_raw.get("ebd_changes") or []
                if not isinstance(settled_list, list):
                    settled_list = []
                for item in settled_list:
                    if not isinstance(item, dict):
                        continue
                    cn = (item.get("character_name") or item.get("name") or "").strip()
                    if not cn or cn == prot_n:
                        continue
                    try:
                        dlt = int(item.get("delta", 0) or 0)
                    except (TypeError, ValueError):
                        dlt = 0
                    reason = (item.get("reason") or "").strip()
                    et_after = (item.get("ebd_type_after") or "").strip() or None
                    if dlt == 0 and not et_after:
                        continue
                    try:
                        await apply_ebd_delta(
                            project_id, cn, dlt, reason, global_seq,
                            ebd_type_after=et_after,
                        )
                    except Exception as e:
                        logger.warning(f"apply_ebd_delta 失败 ({cn}): {e}")
            except Exception as e:
                logger.warning(f"EBD 章节结算跳过: {e}")

        # ── Step 2b: 更新角色能力 ──
        for ab_upd in result.get("ability_updates", []):
            char_name = ab_upd.get("character_name", "").strip()
            ability   = ab_upd.get("ability", {})
            operation = ab_upd.get("operation", "add")
            if not char_name or not ability.get("name"):
                continue
            try:
                await upsert_character_ability(project_id, char_name, operation, ability)
            except Exception as e:
                logger.warning(f"upsert_character_ability 失败 ({char_name}): {e}")

        # ── Step 3: 写入事件时间线 + 关键事件计数 ──
        all_key_participants: list[str] = []
        for ev in result.get("new_events", []):
            desc = ev.get("description", "").strip()
            if not desc:
                continue
            try:
                await append_event(
                    project_id=project_id,
                    seq=global_seq,
                    description=desc,
                    characters=ev.get("characters", []),
                    locations=ev.get("locations", []),
                    items=ev.get("items", []),
                    is_foreshadow=bool(ev.get("is_foreshadow")),
                    foreshadow_id=ev.get("foreshadow_id"),
                )
            except Exception as e:
                logger.warning(f"append_event 失败 ({desc[:20]}): {e}")

            # 收集关键事件参与者
            if ev.get("is_key_event"):
                participants = ev.get("key_event_participants", [])
                all_key_participants.extend(participants)

        # 对关键事件参与者按事件类型增量计数，检测刚到达阈值的角色
        newly_promoted: list[dict] = []
        if all_key_participants:
            unique_participants = list(dict.fromkeys(all_key_participants))  # 去重保序
            # 按事件逐个 increment，传递 key_event_type
            for ev in result.get("new_events", []):
                if not ev.get("is_key_event"):
                    continue
                participants = ev.get("key_event_participants", [])
                event_type = ev.get("key_event_type", "neutral")
                if event_type not in ("positive", "negative", "neutral"):
                    event_type = "neutral"
                for name in participants:
                    if name in unique_participants:
                        try:
                            await increment_key_event_count(
                                project_id, name, event_type=event_type
                            )
                        except Exception as e:
                            logger.warning(f"increment_key_event_count 失败 ({name}): {e}")
            try:
                newly_promoted = await get_newly_promoted_chars(
                    project_id, unique_participants, threshold=2
                )
            except Exception as e:
                logger.warning(f"get_newly_promoted_chars 失败: {e}")

        # ── Step 4: 生成新的 entity_summary ──
        new_summary = await build_entity_summary(project_id)

        # ── Step 5: 若为批次末尾，生成 last_batch_ending ──
        is_last_in_batch = (current_idx == len(story_path) - 1)
        last_batch_ending: dict | None = None

        if is_last_in_batch:
            ending_prompt = LAST_BATCH_ENDING_USER_TEMPLATE.format(
                seq=global_seq,
                node_name=node_name,
                draft_excerpt=draft[:800],   # 截取前800字避免 token 浪费
                entity_summary=new_summary,
            )
            try:
                last_batch_ending = await call_llm_json(
                    LAST_BATCH_ENDING_SYSTEM, ending_prompt
                )
            except Exception as e:
                logger.warning(f"生成 last_batch_ending 失败: {e}")

        # ── Step 5b: 提取本章结尾的行动意图（供下一章 expand1 硬约束承接）──
        last_action_intent_val: str = ""
        if draft.strip():
            tail = draft[-200:] if len(draft) >= 200 else draft
            try:
                intent_prompt = (
                    f"以下是章节结尾：\n{tail}\n\n"
                    "用一句话描述：结尾暗示主角下一步打算做什么？只输出这一句话，不加任何解释。"
                )
                raw = await call_llm(
                    "你是一个故事连贯性分析助手。", intent_prompt, max_tokens=80
                )
                last_action_intent_val = (raw or "").strip()
            except Exception as e:
                logger.warning(f"提取 last_action_intent 失败: {e}")

        # ── Step 6: 更新 novel_projects ──
        try:
            await _update_project_summary(
                project_id, new_summary, last_batch_ending,
                last_action_intent=last_action_intent_val or None,
            )
        except Exception as e:
            logger.critical(f"_update_project_summary 失败 (project={project_id}): {e}")

        # ── Step 7: 写入 chapters + story_nodes ──
        if (draft or "").strip():
            try:
                await _save_chapter_to_db(
                    project_id=project_id,
                    seq=global_seq,
                    node_name=node_name,
                    content=draft,
                    event_path_chain=state.get("pending_event_path_chain", []),
                )
            except Exception as e:
                logger.critical(f"_save_chapter_to_db 失败 (project={project_id}, seq={global_seq}): {e}")
        else:
            logger.critical(
                "bible_update：current_draft 为空，已跳过 chapters 持久化 "
                "(project=%s seq=%s node=%s)，避免写入空 content；请上游排查 write/路由。",
                project_id,
                global_seq,
                node_name,
            )

        # ── Step 8: 保存用户确认的人物卡草稿 ──
        confirmed_char_cards = state.get("confirmed_char_cards", [])
        if confirmed_char_cards:
            try:
                await save_confirmed_char_cards(project_id, confirmed_char_cards, seq=global_seq)
            except Exception as e:
                logger.warning(f"save_confirmed_char_cards 失败: {e}")

        # ── Step 9: 保存用户确认的新能力（decision=add）──
        ability_decisions: list[dict] = state.get("ability_decisions", [])
        for ad in ability_decisions:
            if ad.get("decision") != "add":
                continue
            char_name = ad.get("char_name", "")
            if not char_name or char_name == "未知":
                continue
            ability = {
                "name":             ad.get("ability_name", ""),
                "type":             ad.get("ability_type", "特异能力"),
                "description":      ad.get("ability_desc", ""),
                "level":            "初步掌握",
                "source":           f"第{global_seq}节，用户确认首次出场",
                "limitation":       ad.get("ability_limit", ""),
                "growth_potential": True,
                "active":           True,
            }
            try:
                await upsert_character_ability(project_id, char_name, "add", ability)
            except Exception as e:
                logger.warning(f"用户确认能力写入失败 ({char_name}/{ability['name']}): {e}")

        # 角色升级通知（通过 StreamWriter 发出，主循环按类型展示）
        for item in newly_promoted:
            writer({
                "node_status":     "core_char_promoted",
                "character_name":  item.get("name", ""),
                "key_event_count": 2,
                "upgrade_role":    item.get("upgrade_role", "neutral"),
                "pos_count":       item.get("pos_count", 0),
                "neg_count":       item.get("neg_count", 0),
            })

        # ── 核心角色立场变化检测 ──
        for rs in result.get("role_shift_events", []):
            char_name = rs.get("character_name", "").strip()
            if not char_name:
                continue
            # 只对已是核心配角的角色触发确认
            try:
                is_core = await is_core_character(project_id, char_name, threshold=2)
            except Exception:
                is_core = False
            if not is_core:
                continue

            # 读取当前立场和建立时机
            current_role   = "中立"
            established_seq = 0
            try:
                cards = await get_character_cards_with_tendencies(project_id, [char_name])
                if cards:
                    data = cards[0]
                    # current_role 存在 data_json 里，cards 目前没有直接返回，需要单独查
                    import aiosqlite as _aio
                    async with _aio.connect(str(DB_PATH)) as _conn:
                        _conn.row_factory = _aio.Row
                        _cur = await _conn.execute(
                            "SELECT data_json FROM entity_cards "
                            "WHERE project_id=? AND card_type='character' AND name=?",
                            (project_id, char_name),
                        )
                        _row = await _cur.fetchone()
                        if _row:
                            import json as _j
                            _d = _j.loads(_row["data_json"] or "{}")
                            current_role    = _d.get("current_role", "中立")
                            # 从 role_history 取最近一次建立时机
                            _hist = _d.get("role_history", [])
                            if _hist:
                                established_seq = _hist[-1].get("seq", 0)
            except Exception:
                pass

            pending_role_shifts.append({
                "character_name":      char_name,
                "trigger_type":        rs.get("trigger_type", ""),
                "trigger_description": rs.get("trigger_description", ""),
                "evidence":            rs.get("evidence", ""),
                "current_role":        current_role,
                "established_at_seq":  established_seq,
                "current_seq":         global_seq,
            })

        # ── 特质叠加变化检测（learned）──
        trait_changes = result.get("trait_interaction_changes", [])
        for tc in trait_changes:
            char_name = tc.get("character_name", "").strip()
            suggested = tc.get("suggested_interaction", {})
            if not char_name or not suggested:
                continue
            pending_trait_interaction_update.append({
                "character_name":      char_name,
                "trigger_event":       tc.get("trigger_event", ""),
                "seq":                 tc.get("seq", global_seq),
                "suggested_interaction": suggested,
            })

    # 维持向下兼容：bible state 字段改为存 entity_summary 字符串形式的轻量摘要
    new_bible = {"entity_summary": new_summary if project_id else ""}

    # 伏笔追加：mention_count 自增、urgency 升级、应用用户 story_potential 编辑
    def _calc_urgency(mention_count: int) -> str:
        if mention_count >= 5:
            return "ready"
        if mention_count >= 3:
            return "building"
        return "latent"

    existing_planted = []
    for f in state.get("bible", {}).get("planted_foreshadows", []):
        f = dict(f)
        if f.get("foreshadow_type") == "noun":
            noun_name = f.get("surface_meaning") or f.get("surface_expression", "")
            if noun_name and noun_name in draft:
                f["mention_count"] = f.get("mention_count", 1) + 1
                f["urgency"] = _calc_urgency(f["mention_count"])
        existing_planted.append(f)

    new_planted = result.get("planted_foreshadows", [])
    story_potential_edits = state.get("noun_foreshadow_story_potential_edits") or {}
    existing_ids = {f.get("foreshadow_id") for f in existing_planted}
    for f in new_planted:
        if f.get("foreshadow_id") in existing_ids:
            continue
        surf = f.get("surface_meaning") or f.get("surface_expression", "")
        if surf and surf in story_potential_edits:
            f["story_potential"] = story_potential_edits[surf]
        if not f.get("surface_meaning") and f.get("surface_expression"):
            f["surface_meaning"] = f["surface_expression"]
        existing_planted.append(f)

    collected_ids = set(result.get("collected_foreshadows", []))
    for f in existing_planted:
        if f.get("foreshadow_id") in collected_ids:
            f["collected_at_node"] = global_seq

    new_bible["planted_foreshadows"] = existing_planted

    # ── narrative_extract 伏笔回写（v4.3 补丁 B：分析者视角因果判断伏笔）──────────
    narrative_result = state.get("narrative_extract_result") or {}
    ne_foreshadows = narrative_result.get("foreshadows") or []
    if ne_foreshadows:
        # 更新 karmic_seeds_inventory（已在 bible 合并阶段处理 karmic_ledger_updates）
        # 这里仅将 new 类型伏笔追加到 planted_foreshadows，update 类型追加 building_notes
        ne_existing_ids = {f.get("foreshadow_id") for f in existing_planted}
        for f in ne_foreshadows:
            fid      = f.get("foreshadow_id", "")
            action   = f.get("karmic_ledger_action", "new")
            surface  = f.get("surface_appearance", "")[:120]
            payoff   = f.get("estimated_payoff_type", "")
            why      = f.get("why_not_obvious", "")

            if action == "new" and fid not in ne_existing_ids:
                new_entry = {
                    "foreshadow_id":    fid,
                    "foreshadow_type":  "event",
                    "surface_meaning":  surface,
                    "true_meaning":     payoff,
                    "story_potential":  payoff,
                    "mentioned_by":     why,
                    "planted_at_node":  global_seq,
                    "collected_at_node": 0,
                    "urgency":          "latent",
                    "mention_count":    1,
                    "ready_threshold":  3,
                    "is_backbone":      0,
                    "mystery_type":     "normal",
                    "is_inferred":      0,
                    "_source":          "narrative_extract",
                }
                existing_planted.append(new_entry)
                ne_existing_ids.add(fid)
            elif action == "update":
                target_id = f.get("update_target_id")
                if target_id:
                    for ep in existing_planted:
                        if ep.get("foreshadow_id") == target_id or ep.get("seed_id") == target_id:
                            notes = list(ep.get("building_notes") or [])
                            notes.append({"seq": global_seq, "detail": surface})
                            ep["building_notes"] = notes
                            mc = ep.get("mention_count", 1) + 1
                            ep["mention_count"] = mc
                            ep["urgency"] = _calc_urgency(mc)
                            break

        new_bible["planted_foreshadows"] = existing_planted

        # 同步写入独立伏笔表
        if project_id:
            try:
                for f in ne_foreshadows:
                    if f.get("karmic_ledger_action") != "new":
                        continue
                    fid   = f.get("foreshadow_id", "")
                    surf  = f.get("surface_appearance", "")[:120]
                    payoff = f.get("estimated_payoff_type", "")
                    if not fid or not surf:
                        continue
                    if await foreshadow_exists_by_surface(project_id, surf):
                        continue
                    await save_foreshadow(project_id, {
                        "foreshadow_id":       fid,
                        "foreshadow_type":     "event",
                        "surface_meaning":     surf,
                        "true_meaning":        payoff,
                        "planted_at_node":     global_seq,
                        "collected_at_node":   0,
                        "mentioned_by":        f.get("why_not_obvious", "")[:200],
                        "story_potential":     payoff,
                        "mystery_type":        "normal",
                        "is_backbone":         0,
                        "urgency":             "latent",
                        "mention_count":       1,
                        "ready_threshold":     3,
                        "is_inferred":         0,
                    })
            except Exception as e:
                logger.warning(f"narrative_extract 伏笔写入独立表失败: {e}")

    # ── narrative_extract world_lexicon 词条回写 ──────────────────────────────────
    ne_lexicon_updates = narrative_result.get("lexicon_updates") or []
    lexicon_updates_applied: list[dict] = []
    if ne_lexicon_updates and project_id:
        # 同步到 state.world_lexicon
        current_world_lexicon = list(state.get("world_lexicon") or [])
        lexicon_by_term = {e.get("term", ""): e for e in current_world_lexicon if isinstance(e, dict)}
        for lu in ne_lexicon_updates:
            if not isinstance(lu, dict):
                continue
            term   = (lu.get("term") or "").strip()
            action = (lu.get("action") or "new").strip()
            if not term:
                continue
            conflict_detected = False
            conflict_note = ""
            try:
                await upsert_lexicon_entry(project_id, lu)
            except Exception as exc:
                logger.warning(f"world_lexicon DB 写入失败 ({term}): {exc}")

            if action == "new" and term not in lexicon_by_term:
                new_entry: dict = {
                    "lexicon_id":    lu.get("lexicon_id") or f"LEX_{term[:8]}",
                    "term":          term,
                    "term_type":     lu.get("term_type", "A"),
                    "category":      lu.get("category", "其他"),
                    "static_profile":   lu.get("static_profile") or {},
                    "dynamic_associations": ([lu["dynamic_association"]] if lu.get("dynamic_association") else []),
                    "incomplete_clue": lu.get("incomplete_clue") or {},
                    "first_appearance": {
                        "chapter_id": str(global_seq),
                        "appearance_mode": "static" if lu.get("term_type") == "A" else "dynamic",
                        "was_noticed_by_protagonist": True,
                    },
                }
                lexicon_by_term[term] = new_entry
                current_world_lexicon.append(new_entry)

            elif action == "update_static" and term in lexicon_by_term:
                existing = lexicon_by_term[term]
                existing_sp = existing.get("static_profile") or {}
                new_sp = lu.get("static_profile") or {}
                for list_key in ("inherent_attributes", "hard_constraints"):
                    existing_list = list(existing_sp.get(list_key) or [])
                    for item in (new_sp.get(list_key) or []):
                        if item and item not in existing_list:
                            existing_list.append(item)
                    existing_sp[list_key] = existing_list
                # 矛盾检测（简单实现：hard_constraints 中包含 "不能" 的条目与新属性对比）
                # 此处仅记录，不自动路由（人工 review 时可查看 anchor_integrity_check）
                existing["static_profile"] = existing_sp

            elif action == "update_dynamic" and term in lexicon_by_term:
                existing = lexicon_by_term[term]
                dyn_list = list(existing.get("dynamic_associations") or [])
                for d in dyn_list:
                    if isinstance(d, dict):
                        d["is_active"] = False
                if lu.get("dynamic_association"):
                    dyn_list.append({**lu["dynamic_association"], "is_active": True})
                existing["dynamic_associations"] = dyn_list

            lexicon_updates_applied.append({
                "lexicon_id":       lu.get("lexicon_id", ""),
                "term":             term,
                "action_taken":     action,
                "conflict_detected": conflict_detected,
                "conflict_note":    conflict_note,
            })

        new_bible["world_lexicon_updates_applied"] = lexicon_updates_applied
        # 更新 state.world_lexicon
        # 用 merged_bible 的占位字段传递（实际通过 base_update 中单独输出）
        current_world_lexicon = list(lexicon_by_term.values())
    else:
        current_world_lexicon = list(state.get("world_lexicon") or [])

    # ── 伏笔同步写入独立表 ──
    if project_id:
        try:
            # 扫描正文，更新已有词条的 mention_count
            nouns = await get_noun_foreshadows(project_id)
            for row in nouns:
                surf = row.get("surface_meaning", "")
                if surf and surf in draft:
                    await update_foreshadow_mention(project_id, surf)

            known_names = {f.get("surface_meaning") or f.get("surface_expression", "") for f in existing_planted}
            for i, f in enumerate(new_planted):
                # foreshadow_id 为主键全局唯一，加 project 前缀避免跨项目冲突
                fid = f.get("foreshadow_id") or f"{project_id}_{global_seq:03d}_{i:02d}"
                surf = f.get("surface_meaning") or f.get("surface_expression", "")
                if fid in existing_ids or (surf and surf in known_names):
                    continue
                if surf and await foreshadow_exists_by_surface(project_id, surf):
                    continue
                known_names.add(surf)
                await save_foreshadow(project_id, {
                    "foreshadow_id":       fid,
                    "foreshadow_type":     f.get("foreshadow_type", "event"),
                    "surface_meaning":     surf,
                    "true_meaning":        f.get("true_meaning", ""),
                    "planted_at_node":     global_seq,
                    "collected_at_node":   0,
                    "misdirect_direction": f.get("misdirect_direction", ""),
                    "mentioned_by":        f.get("mentioned_by", ""),
                    "story_potential":     story_potential_edits.get(surf, f.get("story_potential", "")),
                    "mystery_type":        "normal",
                    "is_backbone":         1 if f.get("is_backbone") else 0,
                    "urgency":             "latent",
                    "mention_count":       1,
                    "ready_threshold":     3,
                    "is_inferred":         0,
                })
            for f in existing_planted:
                fid = f.get("foreshadow_id", "")
                if not fid:
                    continue
                await save_foreshadow(project_id, {
                    "foreshadow_id":       fid,
                    "foreshadow_type":     f.get("foreshadow_type", "event"),
                    "surface_meaning":     f.get("surface_meaning") or f.get("surface_expression", ""),
                    "true_meaning":        f.get("true_meaning", ""),
                    "planted_at_node":     f.get("planted_at_node", 0),
                    "collected_at_node":   f.get("collected_at_node", 0),
                    "mentioned_by":        f.get("mentioned_by", ""),
                    "story_potential":     f.get("story_potential", ""),
                    "mystery_type":        f.get("mystery_type", "normal"),
                    "is_backbone":         f.get("is_backbone", 0),
                    "urgency":             f.get("urgency", "latent"),
                    "mention_count":       f.get("mention_count", 1),
                    "ready_threshold":     f.get("ready_threshold", 3),
                    "is_inferred":         0,
                })
            for fid in collected_ids:
                await collect_foreshadow(fid, global_seq)
        except Exception as e:
            logger.warning(f"伏笔同步独立表失败: {e}")

    existing_collected = state.get("bible", {}).get("collected_foreshadows", [])
    new_bible["collected_foreshadows"] = list(
        set(existing_collected + result.get("collected_foreshadows", []))
    )

    _pp_mem = state.get("path_progress") or {}
    _rem = list(_pp_mem.get("remaining_paths") or []) if isinstance(_pp_mem, dict) else []
    _event_boundary_flush = len(_rem) == 0
    memory_chars_patch = await _apply_patch_i_chapter_narrative_memory(
        state,
        project_id or "",
        global_seq,
        event_boundary_flush=_event_boundary_flush,
        chapter_draft=draft or "",
    )

    # 合并 bible 并清除本章修改反馈，防止跨章污染
    merged_bible = {
        **state.get("bible", {}),
        **new_bible,
        "rewrite_feedback":        "",
        "rewrite_feedback_parsed": {},
    }
    if memory_chars_patch:
        mch = dict(merged_bible.get("characters") or {})
        for k, v in memory_chars_patch.items():
            prev_c = dict(mch[k]) if isinstance(mch.get(k), dict) else {}
            inc_c = dict(v) if isinstance(v, dict) else {}
            mch[k] = {**prev_c, **inc_c}
        merged_bible["characters"] = mch

    ledger = result.get("karmic_ledger_updates")
    if isinstance(ledger, dict):
        merged_bible["last_karmic_ledger_updates"] = ledger
        prev_inv = list(state.get("bible", {}).get("karmic_seeds_inventory") or [])
        for s in ledger.get("seeds_planted") or []:
            if isinstance(s, dict):
                sid = (s.get("seed_id") or "").strip() or f"K{global_seq}_{len(prev_inv)}"
                prev_inv.append({**s, "seed_id": sid, "planted_at_seq": global_seq})
        merged_bible["karmic_seeds_inventory"] = prev_inv[-300:]
        prev_h = list(state.get("bible", {}).get("karmic_seeds_harvested_log") or [])
        for h in ledger.get("seeds_harvested") or []:
            if isinstance(h, dict):
                prev_h.append({**h, "at_seq": global_seq})
        merged_bible["karmic_seeds_harvested_log"] = prev_h[-300:]

    aic = result.get("anchor_integrity_check")
    if isinstance(aic, dict):
        merged_bible["anchor_integrity_check"] = aic
        if (aic.get("status") or "").strip().upper() == "WARNING":
            logger.warning(
                "anchor_integrity_check WARNING seq=%s: %s",
                global_seq,
                aic.get("conflicts"),
            )

    fn = result.get("faction_shift_notes")
    if isinstance(fn, list) and fn:
        merged_bible["faction_shift_notes_last"] = [str(x).strip() for x in fn if str(x).strip()][
            :20
        ]

    # ── v4.3 双循环控制：先推进路径再判定内外循环（末条路径不得误判为「内循环未完成」）
    _pp_merged = dict(state.get("path_progress") or {}) if isinstance(state.get("path_progress"), dict) else {}
    _pp_merged["pending_inner_stream_chunks"] = []
    _adv_pp = _advance_path_progress(state)
    _sim_pp = dict(_pp_merged)
    if _adv_pp:
        _sim_pp.update(_adv_pp)
    state_for_loop: dict = dict(state)
    state_for_loop["path_progress"] = _sim_pp
    loop_control = _compute_v43_loop_control(state_for_loop, merged_bible, draft_for_count=draft)
    if _adv_pp:
        _pp_merged.update(_adv_pp)
    _all_txt = (state.get("all_paths_text") or draft or "").strip()
    if _all_txt:
        _pp_merged["cumulative_prose_tail"] = _all_txt[-400:]
    updated_path_progress = _pp_merged

    settle_extras: dict = {}
    if loop_control.get("inner_loop_complete"):
        gsec = int(state.get("global_settled_event_count", 0) or 0)
        settle_extras["global_settled_event_count"] = gsec + 1
        ce = state.get("current_event") if isinstance(state.get("current_event"), dict) else {}
        ent = ce.get("_settlement_summary_entry") if isinstance(ce, dict) else None
        if isinstance(ent, dict) and str(ent.get("event_id") or "").strip():
            settle_extras["completed_events_summary"] = [dict(ent)]
        elif isinstance(ce, dict) and str(ce.get("event_id") or "").strip():
            _cc = ce.get("causal_chain") if isinstance(ce.get("causal_chain"), dict) else {}
            _pt = ce.get("protagonist_tick") if isinstance(ce.get("protagonist_tick"), dict) else {}
            _ecore = ce.get("event_core") if isinstance(ce.get("event_core"), dict) else {}
            settle_extras["completed_events_summary"] = [
                {
                    "event_id": str(ce.get("event_id") or "").strip(),
                    "event_name": ce.get("event_name", "（未命名）"),
                    "conflict_type": _ecore.get("conflict_type", ""),
                    "primary_resource_used": _ecore.get("primary_resource_used", ""),
                    "event_result_type": str(_cc.get("event_result_type") or "").strip(),
                    "protagonist_tick_type": str(_pt.get("protagonist_tick_type") or "").strip(),
                    "milestone_touched": None,
                }
            ]
    # 将 narrative_extract 的 actual_chain 追加到 path_progress 供后续参考
    ne_result = state.get("narrative_extract_result") or {}
    ne_snap = ne_result.get("scene_snapshot") or {}
    if not isinstance(ne_snap, dict):
        ne_snap = {}
    ne_path_chain = ne_result.get("chapter_path_chain") or {}
    if ne_path_chain and isinstance(updated_path_progress, dict):
        history = list(updated_path_progress.get("actual_chain_history") or [])
        history.append({
            "seq":            ne_result.get("global_seq", global_seq),
            "actual_chain":   ne_path_chain.get("actual_chain", ""),
            "planned_chain":  ne_path_chain.get("planned_chain", ""),
            "deviation_exists": ne_path_chain.get("deviation_exists", False),
            "deviation_note": ne_path_chain.get("deviation_note", ""),
        })
        updated_path_progress["actual_chain_history"] = history[-20:]  # 保留最近20章

    # 里程碑 / 锚点进度（event_chain_gen 更新；此处透传，双写兼容旧 checkpoint）
    _prog = dict(state.get("milestone_progress") or {})

    # ── 主角精神层面动态回写 ──────────────────────────────────────────────────────
    # 若 entity_updates 中包含主角，将 current_mental_state / mental_status_note 同步到
    # protagonist_archive，使后续 expand1/event_chain_gen 能感知主角的精神演变
    updated_protagonist_archive = _merge_protagonist_mental_update(
        state, result.get("entity_updates") or []
    )

    # ── 任务生命周期检查（补丁 D：active_quest_stack）────────────────────────────
    current_active_quest_stack = list(state.get("active_quest_stack") or [])
    quest_stack_updates: dict = {}
    if current_active_quest_stack and draft.strip():
        try:
            current_active_quest_stack, quest_stack_updates = await _check_quest_lifecycle(
                draft=draft,
                active_quest_stack=current_active_quest_stack,
                global_seq=global_seq,
                chapter_id=str(global_seq),
            )
        except Exception as _qe:
            logger.warning("任务生命周期检查失败（不阻断主流程）: %s", _qe)

    # 将任务栈同步到 protagonist_archive（以便 expand1 / event_chain_gen 感知）
    if updated_protagonist_archive is not None and current_active_quest_stack:
        updated_protagonist_archive = dict(updated_protagonist_archive)
        updated_protagonist_archive["active_quest_stack"] = current_active_quest_stack
    elif current_active_quest_stack:
        pa = dict(state.get("protagonist_archive") or state.get("protagonist_card") or {})
        if pa:
            pa["active_quest_stack"] = current_active_quest_stack
            updated_protagonist_archive = pa

    base_update = {
        "bible":                          merged_bible,
        "karmic_ledger":                  _state_karmic_ledger_from_merged_bible(merged_bible),
        "current_node_index":             current_idx + 1,
        "confirmed_char_cards":           [],
        "pending_char_cards":             [],
        "pending_role_shifts":            pending_role_shifts if project_id else [],
        "pending_ability_checks":         [],
        "ability_decisions":              [],
        "pending_trait_interaction_update": pending_trait_interaction_update if project_id else [],
        "pending_noun_foreshadows":        [],
        "noun_foreshadow_story_potential_edits": {},
        "narrative_extract_result":        {},
        "scene_snapshot":                  ne_snap if ne_snap else state.get("scene_snapshot") or {},
        "world_lexicon":                   current_world_lexicon,
        "active_quest_stack":              current_active_quest_stack,
        "last_action_intent":             last_action_intent_val if project_id else "",
        "auto_total_retry_count":         0,
        "tension_retry_count":           0,
        "tension_minor_issues":          [],
        # v4.3 新增
        "loop_control":                   loop_control,
        "path_progress":                  updated_path_progress,
        "milestone_progress":             _prog,
        # 主角精神层面动态回写
        **({"protagonist_archive": updated_protagonist_archive} if updated_protagonist_archive else {}),
        **settle_extras,
    }

    # 若有卷收束摘要（trigger_arc_end），附加到 state
    if loop_control.get("outer_loop_action") == "trigger_arc_end":
        base_update["arc_completion_summary"] = loop_control.get("arc_completion_summary")

    return base_update


# ════════════════════════════════════════════════════════════════════════════════
# v4.3 双循环控制函数
# ════════════════════════════════════════════════════════════════════════════════

def _advance_path_progress(state: CreationState) -> dict:
    """
    内循环：将当前 path_progress.remaining_paths[0] 移入 completed_paths。
    """
    path_progress = state.get("path_progress") or {}
    if not isinstance(path_progress, dict):
        return {}

    remaining = list(path_progress.get("remaining_paths") or [])
    completed = list(path_progress.get("completed_paths") or [])
    current_event_id = path_progress.get("current_event_id", "")

    if remaining:
        finished_path_id = remaining.pop(0)
        completed.append(finished_path_id)
    
    return {
        "current_event_id": current_event_id,
        "completed_paths": completed,
        "remaining_paths": remaining,
    }


def _volume_target_events(vol: dict) -> int:
    """本卷目标事件数（规划字段 target_events；缺省 30）。"""
    if not isinstance(vol, dict):
        return 30
    try:
        te = int(vol.get("target_events", 0) or 0)
    except (TypeError, ValueError):
        te = 0
    if te > 0:
        return max(1, te)
    return 30


# 沙盒压测：与 volumes[].target_events 取 min，压低后仍满足「事件计数」语义（非章节表）
_SANDBOX_ARC_TARGET_EVENTS_CAP = 12


def _compute_v43_loop_control(
    state: CreationState,
    merged_bible: dict,
    *,
    draft_for_count: str = "",
) -> dict:
    """
    计算 v4.3 双循环控制决策（path_progress 须为已 advance 后的快照）：
    1. 内循环：path_progress.remaining_paths 是否非空
    2. 外循环（内循环完成后）：本卷已完结事件数 vs volumes[].target_events；
       里程碑全清且事件数≥80% 目标 → trigger_arc_end；≥120% → 强制收卷。

    计数器说明（与章节表无关）：「本卷事件数」= global_settled_event_count + 1
    （本笔结算）− volume_start_event_count（卷起点基准）；见 volume_events_after。
    沙盒可设 state["_sandbox_arc_relaxed"]，将参与阈值的 target_events 上限压到
    `_SANDBOX_ARC_TARGET_EVENTS_CAP`，便于在少量事件内走通 auto_arc_transition。
    """
    path_progress = state.get("path_progress") or {}
    remaining_paths = list(path_progress.get("remaining_paths") or [])

    sandbox_arc_relaxed = bool(state.get("_sandbox_arc_relaxed"))
    gsec = int(state.get("global_settled_event_count", 0) or 0)
    vsec = int(state.get("volume_start_event_count", 0) or 0)
    volume_events_after = max(0, gsec + 1 - vsec)
    vol_index = int(state.get("current_volume_index", 0) or 0)
    volumes = state.get("volumes") or []

    if len(remaining_paths) > 0:
        next_path_id = str(remaining_paths[0] or "").strip()
        out = {
            "inner_loop_complete": False,
            "inner_loop_action": "continue_inner_loop",
            "next_path_id": next_path_id,
        }
        logger.debug(
            "bible_update v4.3 loop_control_diag %s",
            json.dumps(
                {
                    "branch": "inner_incomplete",
                    "sandbox_arc_relaxed": sandbox_arc_relaxed,
                    "loop_control": out,
                    "remaining_paths_head": remaining_paths[:5],
                    "remaining_paths_count": len(remaining_paths),
                    "global_settled_event_count": gsec,
                    "volume_start_event_count": vsec,
                    "volume_events_after_this_settlement": volume_events_after,
                    "current_volume_index": vol_index,
                },
                ensure_ascii=False,
            ),
        )
        return out

    mp = state.get("milestone_progress") or {}
    pending = list(mp.get("pending") or [])
    completed = list(mp.get("completed") or [])
    milestone_all_complete = len(pending) == 0 and len(completed) > 0

    if volumes and vol_index < len(volumes):
        target_events_raw = _volume_target_events(
            volumes[vol_index] if isinstance(volumes[vol_index], dict) else {}
        )
    else:
        target_events_raw = 30
    target_events = max(1, int(target_events_raw))
    if sandbox_arc_relaxed:
        target_events = max(5, min(target_events, _SANDBOX_ARC_TARGET_EVENTS_CAP))

    th_normal = target_events * 0.8
    th_forced = target_events * 1.2
    normal_ready = milestone_all_complete and volume_events_after >= th_normal
    forced_ready = volume_events_after >= th_forced

    trigger_arc = False
    if normal_ready:
        trigger_arc = True
        logger.info(
            "bible_update v4.3：卷收束触发(正常) 里程碑全清且本卷事件数≥80%% 阈值 "
            "vol=%s milestones=%s 本卷事件=%s/%s",
            vol_index,
            len(completed),
            volume_events_after,
            target_events,
        )
    elif forced_ready:
        trigger_arc = True
        logger.warning(
            "bible_update v4.3：卷收束触发(强制) 事件数≥120%% 阈值（里程碑状态不阻塞） "
            "vol=%s pending_milestones=%s 本卷事件=%s/%s",
            vol_index,
            len(pending),
            volume_events_after,
            target_events,
        )

    diag_common = {
        "branch": "outer_eval",
        "sandbox_arc_relaxed": sandbox_arc_relaxed,
        "counter_note": "volume_events_after = global_settled_event_count + 1 - volume_start_event_count（章节行数不参与）",
        "global_settled_event_count": gsec,
        "volume_start_event_count": vsec,
        "volume_events_after_this_settlement": volume_events_after,
        "current_volume_index": vol_index,
        "target_events_raw": int(target_events_raw),
        "target_events_effective": target_events,
        "threshold_normal_80pct": th_normal,
        "threshold_forced_120pct": th_forced,
        "milestone_pending": pending,
        "milestone_completed": completed,
        "milestone_all_complete": milestone_all_complete,
        "normal_path_ready": normal_ready,
        "forced_path_ready": forced_ready,
    }

    if trigger_arc:
        protagonist_archive = state.get("protagonist_archive") or state.get("protagonist_card") or {}
        current_vol = volumes[vol_index] if volumes and vol_index < len(volumes) else {}

        karmic_inventory = merged_bible.get("karmic_seeds_inventory") or []
        harvested_log = merged_bible.get("karmic_seeds_harvested_log") or []
        harvested_ids = {h.get("seed_id") for h in harvested_log if isinstance(h, dict)}
        open_seeds = [
            {"seed_id": s.get("seed_id"), "description": s.get("description", s.get("surface_meaning", ""))}
            for s in karmic_inventory
            if isinstance(s, dict) and s.get("seed_id") not in harvested_ids
        ][-10:]

        arc_completion_summary = {
            "volume_index": vol_index,
            "volume_name": current_vol.get("volume_name", ""),
            "milestones_completed": completed,
            "total_events_in_volume": volume_events_after,
            "open_seeds": open_seeds,
            "protagonist_state_at_end": {
                "name": protagonist_archive.get("standard_name", "") or state.get("protagonist_name", ""),
                "maturity": (protagonist_archive.get("psychological_profile") or {}).get("maturity_level", ""),
                "current_status": protagonist_archive.get("current_status", ""),
            },
            "volume_direction_achieved": current_vol.get("volume_direction", ""),
        }

        out_trigger = {
            "inner_loop_complete": True,
            "outer_loop_action": "trigger_arc_end",
            "arc_completion_summary": arc_completion_summary,
        }
        logger.info(
            "bible_update v4.3 loop_control_diag %s",
            json.dumps({**diag_common, "loop_control": out_trigger}, ensure_ascii=False),
        )
        return out_trigger

    out_continue = {
        "inner_loop_complete": True,
        "outer_loop_action": "continue_event_loop",
        "pending_milestones_count": len(pending),
        "volume_event_count": gsec,
        "current_volume_event_count": volume_events_after,
    }
    logger.info(
        "bible_update v4.3 loop_control_diag %s",
        json.dumps({**diag_common, "loop_control": out_continue}, ensure_ascii=False),
    )
    return out_continue

def _bible_update_v43_routing(state: CreationState) -> str:
    """
    图路由函数：根据 loop_control 决定 bible_update 的下一跳。
    用于 graph.py 中 bible_update 节点的 conditional_edge。
    """
    loop_control = state.get("loop_control") or {}

    # 内循环未完成 → 回到 expand1（下一路径）
    if not loop_control.get("inner_loop_complete", True):
        return "expand1_v43"

    # 外循环：继续事件循环
    outer_action = loop_control.get("outer_loop_action", "continue_event_loop")
    if outer_action == "trigger_arc_end":
        auto_mode = state.get("auto_mode", False)
        auto_target = (state.get("auto_target") or "book").strip().lower()
        if auto_mode and auto_target in ("arc", "book"):
            return "auto_arc_transition"
        return "human_review_batch"

    # 默认：继续事件循环（生成下一个事件）
    return "event_chain_gen"


def _merge_protagonist_mental_update(
    state: CreationState,
    entity_updates: list[dict],
) -> dict | None:
    """
    将本章 entity_updates 中主角相关的精神层面信息合并回 protagonist_archive。

    更新逻辑：
    - mental_status_note → protagonist_archive["current_mental_state_note"]（本章精神状态摘要）
    - mental_core（若 LLM 提供）→ 合并进 protagonist_archive["mental_core"]
    - status_change（如有）→ protagonist_archive["current_status"]

    返回更新后的 protagonist_archive dict，若主角未出现在 entity_updates 中则返回 None。
    """
    protagonist_name = (state.get("protagonist_name") or "").strip()
    if not protagonist_name:
        return None

    protagonist_archive = dict(state.get("protagonist_archive") or state.get("protagonist_card") or {})
    if not protagonist_archive:
        return None

    # 在 entity_updates 中查找主角（匹配标准名或别名前缀）
    prot_update: dict | None = None
    for upd in entity_updates:
        if not isinstance(upd, dict):
            continue
        if (upd.get("card_type") or "character") != "character":
            continue
        upd_name = (upd.get("name") or "").strip()
        if upd_name == protagonist_name or protagonist_name in (upd.get("aliases") or []):
            prot_update = upd
            break

    if not prot_update:
        return None

    updated = dict(protagonist_archive)

    # 精神状态摘要（提示性记录，供下一轮 expand1 感知主角当下精神状态）
    mental_note = (prot_update.get("mental_status_note") or "").strip()
    if mental_note:
        updated["current_mental_state_note"] = mental_note

    # 若 LLM 直接提供了 current_mental_state（拓展字段）则覆盖
    cms = (prot_update.get("current_mental_state") or "").strip()
    if cms:
        updated["current_mental_state"] = cms

    # 若 LLM 提供了 mental_growth_path 更新（一般不会每章更新，但允许更新）
    mgp = (prot_update.get("mental_growth_path") or "").strip()
    if mgp:
        updated["mental_growth_path"] = mgp

    # 物理/社会地位变化
    sc = (prot_update.get("status_change") or "").strip()
    if sc:
        updated["current_status"] = sc

    # 位置变化
    lc = (prot_update.get("location_change") or "").strip()
    if lc:
        updated["current_location"] = lc

    # mental_core 增量合并（emotional_capacity 由 upsert_entity_card 写 DB；此处同步 state）
    if isinstance(prot_update.get("mental_core"), dict):
        existing_mc = dict(updated.get("mental_core") or {})
        for k, v in prot_update["mental_core"].items():
            if v is not None and v != "":
                existing_mc[k] = v
        updated["mental_core"] = existing_mc

    return updated
