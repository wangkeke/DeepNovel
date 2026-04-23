"""
event_chain_gen_node v4.3 — 单事件生成

每次调用生成一个事件（通过三步命运编织引擎），输出写入 state.current_event；
同时追加 completed_events_summary，更新 anchor_progress。

路由：→ human_review_event（人工模式）或 → path_gen（自动模式）。
"""
from __future__ import annotations
import json
import logging
from langgraph.types import Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from memory.db import get_volumes, get_available_character_names_for_volume, get_active_lexicon_entries
from memory.entity_db import get_character_cards_with_tendencies
from prompts.creation.platform_styles import platform_planning_bundle
from prompts.creation.event_chain_gen import (
    EVENT_CHAIN_GEN_SYSTEM,
    EVENT_CHAIN_GEN_USER_TEMPLATE,
    format_completed_events_summary,
    format_arc_anchors_for_event_gen,
)
from utils.v42_flow import protagonist_archive_prompt_block

logger = logging.getLogger("deepnovel.event_chain_gen")


# ─── 保留的辅助函数 ────────────────────────────────────────────────────────────

def _karmic_ledger_prompt_block(state: CreationState) -> str:
    """将 state 顶层或 bible 中的因果种子注入事件链 prompt。"""
    raw = state.get("karmic_ledger")
    if not isinstance(raw, list) or not raw:
        bb = state.get("bible")
        if isinstance(bb, dict):
            inv = bb.get("karmic_seeds_inventory") or []
            if isinstance(inv, list) and inv:
                raw = list(inv)[-40:]
            else:
                return ""
        else:
            return ""
    else:
        raw = list(raw)[-40:]
    try:
        blob = json.dumps(raw, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        blob = str(raw)
    lim = 12000
    if len(blob) > lim:
        blob = blob[: lim - 20] + "\n…（截断）"
    return blob


def _get_arc_anchors(volume: dict) -> list[dict]:
    """从卷中提取 arc_anchors；旧卷不含时生成最小占位。"""
    anchors = volume.get("arc_anchors")
    if isinstance(anchors, list) and anchors:
        out = []
        for idx, a in enumerate(anchors):
            if not isinstance(a, dict):
                continue
            if not a.get("anchor_id"):
                a = dict(a)
                a["anchor_id"] = idx + 1
            out.append(a)
        return out
    return [
        {
            "anchor_id": 1,
            "position": "early",
            "milestone_type": "开篇碰撞",
            "arrival_condition": "主角被卷入本卷核心冲突",
            "completion_signal": "主角与核心冲突完成首次正面碰撞",
        },
        {
            "anchor_id": 2,
            "position": "mid",
            "milestone_type": "规则反转",
            "arrival_condition": "主角发现表面规则背后的真实博弈",
            "completion_signal": "某关键信息被揭露或某势力关系发生实质性转变",
        },
        {
            "anchor_id": 3,
            "position": "late",
            "milestone_type": "圈层跃迁",
            "arrival_condition": "主角完成本卷核心目标，进入更高圈层",
            "completion_signal": "主角获得新身份/资源/权柄或打破核心幻想",
        },
    ]


def _get_last_causal_output(state: CreationState) -> str:
    """从 state 中提取上一事件的因果输出，供下一事件生成时注入。"""
    # 优先从 current_event 中提取 causal_chain
    current_event = state.get("current_event") or {}
    if isinstance(current_event, dict) and current_event:
        causal_chain = current_event.get("causal_chain") or {}
        if isinstance(causal_chain, dict):
            to_next = causal_chain.get("to_next_event", "")
            writeback = causal_chain.get("archive_writeback", {})
            if to_next or writeback:
                parts = []
                if to_next:
                    parts.append(f"因果土壤：{to_next}")
                if writeback:
                    try:
                        wb_text = json.dumps(writeback, ensure_ascii=False)
                        if len(wb_text) > 2000:
                            wb_text = wb_text[:2000] + "…（截断）"
                        parts.append(f"上一事件 archive_writeback：{wb_text}")
                    except (TypeError, ValueError):
                        pass
                return "\n".join(parts)
        event_name = current_event.get("event_name", "")
        if event_name:
            return f"上一事件：{event_name}（{current_event.get('event_summary', '')}）"

    # 从 bible 或事件链中查找最后一个事件的 causal 信息
    bible = state.get("bible") or {}
    if isinstance(bible, dict):
        last_causal = bible.get("last_event_causal_output", "")
        if last_causal:
            return str(last_causal)

    completed = state.get("completed_events_summary") or []
    if isinstance(completed, list) and completed:
        last = completed[-1]
        if isinstance(last, dict):
            return f"上一事件：{last.get('event_name', '?')}（冲突类型：{last.get('conflict_type', '?')}）"

    return "（全书开篇，这是第一个事件）"


def _get_world_archive_text(state: CreationState) -> str:
    """格式化 world_archive 供 prompt 注入。"""
    wa = state.get("world_archive") or state.get("world_setting") or {}
    if not isinstance(wa, dict) or not wa:
        synopsis = state.get("synopsis") or {}
        return f"世界观摘要：{synopsis.get('world', '（未提供）')}"
    try:
        blob = json.dumps(wa, ensure_ascii=False, indent=2)
        if len(blob) > 6000:
            blob = blob[:6000] + "\n…（截断）"
        return blob
    except (TypeError, ValueError):
        return str(wa)[:3000]


def _get_protagonist_archive_text(state: CreationState) -> str:
    """格式化 protagonist_archive 供 prompt 注入（active_quest_stack 已嵌入档案）。"""
    pa = state.get("protagonist_archive") or state.get("protagonist_card") or {}
    if not isinstance(pa, dict) or not pa:
        return f"主角名：{state.get('protagonist_name', '（未知）')}"
    # 确保 active_quest_stack 已同步到 protagonist_archive（bible_update 会写入）
    qs = state.get("active_quest_stack") or []
    if qs and not pa.get("active_quest_stack"):
        pa = dict(pa)
        pa["active_quest_stack"] = qs
    return protagonist_archive_prompt_block(pa)


def _build_quest_stack_for_protagonist_tick(state: CreationState) -> str:
    """
    提取 active_quest_stack 中 critical/high 的活跃任务，
    格式化为 Protagonist Tick 专用注入块（补丁 D）。
    """
    qs = state.get("active_quest_stack") or []
    if not isinstance(qs, list):
        return ""
    active = [
        q for q in qs
        if isinstance(q, dict)
        and q.get("status") == "active"
        and q.get("urgency_level") in ("critical", "high")
        and q.get("layer") in ("immediate", "short_term")
    ]
    if not active:
        return ""

    lines = [
        "## 【Protagonist Tick — 任务栈驱动（补丁D，优先于 core_desire 推导）】",
        "以下任务的 current_sub_goal 直接构成主角此刻最深的需求，",
        "无需重新从 core_desire 推导——任务栈已经是推导的结果。",
        "",
    ]
    for q in active:
        urg = q.get("urgency_level", "")
        icon = "⚠️" if urg == "critical" else "→"
        lines.append(f"{icon} quest_id={q.get('quest_id', '?')}  [{q.get('layer', '')}|{urg}]")
        lines.append(f"   quest_name: {q.get('quest_name', '')}")
        sg = (q.get("current_sub_goal") or "").strip()
        if sg:
            lines.append(f"   current_sub_goal（= deepest_need）: {sg[:150]}")
        ew = (q.get("emotional_weight") or "").strip()
        if ew:
            lines.append(f"   emotional_weight: {ew[:120]}")
        dn = (q.get("deadline_note") or "").strip()
        if dn:
            lines.append(f"   deadline_note: {dn[:80]}")
        lines.append("")

    lines.append(
        "Protagonist Tick 输出须包含：quest_driven=true, driving_quest_id=（上方 quest_id），\n"
        "deepest_need 直接引用 current_sub_goal，emotional_weight 引用任务的 emotional_weight。"
    )
    return "\n".join(lines) + "\n"


def _should_include_character_for_relationship_tick(
    targeting: int,
    ebd: int,
    ebd_bond: str,
    innate: list,
    remaining_capacity: int,
) -> bool:
    """
    补丁文档：A/B 类主阈值建议 60；40～59 仅在其精神阈值接近透支或具备 C 类性格/利益联盟标签时纳入，避免弱关系噪音。
    """
    ae = abs(ebd)
    if targeting >= 60 or ae >= 60:
        return True
    if ebd_bond == "benefactor_debt":
        return True
    in_weak_band = (40 <= targeting < 60) or (40 <= ae < 60)
    if not in_weak_band:
        return False
    if remaining_capacity <= 30:
        return True
    betrayal_traits = {"薄情寡恩", "见风使舵", "极度功利", "功利", "自私"}
    innate_set = {str(t) for t in innate}
    if innate_set & betrayal_traits:
        return True
    if ebd_bond == "alliance_interest":
        return True
    return False


def _capabilities_snippet_for_tick(card: dict) -> str:
    """从配角卡 capabilities 摘一行供关系层与暗流对齐（无则省略）。"""
    caps = card.get("capabilities")
    if not isinstance(caps, dict) or not caps:
        return ""
    gf = caps.get("golden_finger")
    lines: list[str] = []
    if isinstance(gf, dict) and gf.get("has_golden_finger"):
        t = str(gf.get("gf_type") or "").strip()
        core = str(gf.get("core_ability") or "").strip()[:80]
        if t or core:
            lines.append(f"金手指: {t or '（类型未标）'} — {core or '（能力简述）'}")
    ut = caps.get("unique_traits") or []
    if isinstance(ut, list) and ut:
        names = []
        for u in ut[:2]:
            if isinstance(u, dict) and (u.get("trait_name") or "").strip():
                names.append(str(u["trait_name"]).strip())
        if names:
            lines.append(f"特质: {' / '.join(names)}")
    if not lines:
        return ""
    return "  capabilities摘要: " + "；".join(lines)


async def _get_entity_cards_text(project_id: str, vol_index: int) -> str:
    """
    从 entity_db 读取与主角存在强关系的角色卡，
    按 A类仇敌/B类恩情/C类潜在背叛 分类格式化为文本，供 World Tick 扫描维度二使用。
    纳入规则与补丁文档一致：主阈值 60；40～59 仅在阈值透支/C 类性格/利益联盟等条件下纳入。
    """
    if not project_id:
        return "（无项目ID，跳过角色关系卡注入）"
    try:
        char_names = await get_available_character_names_for_volume(project_id, vol_index)
        if not char_names:
            return "（当前卷暂无已登记角色卡）"
        cards = await get_character_cards_with_tendencies(project_id, list(char_names))
    except Exception as exc:
        logger.warning("读取角色关系卡失败：%s", exc)
        return "（读取角色关系卡时出错，跳过）"

    # 按 A/B/C 分类
    a_class: list[str] = []  # 仇敌阻路者
    b_class: list[str] = []  # 恩情持有者
    c_class: list[str] = []  # 潜在背叛者

    for card in cards:
        name = card.get("name", "?")
        targeting = int(card.get("targeting_degree") or 0)
        ebd = int(card.get("ebd_to_protagonist") or 0)
        ebd_bond = (card.get("ebd_bond_kind") or "").strip()
        innate = card.get("innate_traits") or []
        mental_capacity_drain = int(card.get("current_emotional_drain") or 0)
        # emotional_capacity 从 mental_core 读取（0~100）
        mc = card.get("mental_core") or {}
        emotional_capacity = int(mc.get("emotional_capacity") or 60)
        remaining_capacity = max(0, emotional_capacity - mental_capacity_drain)

        if not _should_include_character_for_relationship_tick(
            targeting, ebd, ebd_bond, innate, remaining_capacity
        ):
            continue

        innate_str = ", ".join(str(t) for t in innate[:6]) if innate else "未知"
        current_state = (card.get("current_mental_state") or card.get("current_status") or "").strip()
        mental_growth = (card.get("mental_growth_path") or "").strip()
        cap_line = _capabilities_snippet_for_tick(card)

        base_info = (
            f"  姓名: {name}\n"
            f"  先天底色: {innate_str}\n"
            f"  targeting_degree: {targeting}  ebd_to_protagonist: {ebd}  ebd_bond_kind: {ebd_bond}\n"
            f"  remaining_emotional_capacity: {remaining_capacity}\n"
            f"  当前状态: {current_state or '（未记录）'}\n"
            f"  心智成长路径: {mental_growth or '（未记录）'}"
            + (f"\n{cap_line}" if cap_line else "")
        )

        betrayal_traits = {"薄情寡恩", "见风使舵", "极度功利", "功利", "自私"}
        innate_set = set(str(t) for t in innate)
        is_c = (
            bool(innate_set & betrayal_traits)
            or ebd_bond == "alliance_interest"
            or remaining_capacity <= 30
        )

        # A类：高 targeting、或强负向情感轴（仇敌/压迫）
        if targeting >= 60 or ebd <= -60:
            a_class.append(base_info)
        # B类：高正向 ebd 或恩情债主
        elif ebd >= 60 or ebd_bond == "benefactor_debt":
            b_class.append(base_info)
        # C类：潜在背叛者（性格底色 + 低剩余阈值 或 利益联盟关系）
        elif is_c and targeting < 60:
            c_class.append(base_info)
        elif 40 <= targeting < 60:
            # 弱带内阻路者（已满足纳入条件且未归入 B/C）
            a_class.append(base_info)

    if not a_class and not b_class and not c_class:
        return "（当前卷无满足阈值的强关系角色，World Tick 扫描维度二无输入）"

    lines = []
    if a_class:
        lines.append("【A类：仇敌与阻路者（高 targeting_degree）】")
        lines.extend(a_class)
    if b_class:
        lines.append("\n【B类：恩情持有者（benefactor_debt / 高正向 ebd）】")
        lines.extend(b_class)
    if c_class:
        lines.append("\n【C类：潜在背叛者（性格底色 + 压力临界）】")
        lines.extend(c_class)
    return "\n".join(lines)


def _build_archive_writeback_snapshot(state: CreationState) -> str:
    """
    收集 completed_events_summary 中最近几个事件的 archive_writeback，
    作为累积状态快照注入本次生成，模拟「回写后再推导」。
    """
    current_event = state.get("current_event") or {}
    if not isinstance(current_event, dict) or not current_event:
        return "（无历史 archive_writeback，这是第一个事件）"

    causal_chain = current_event.get("causal_chain") or {}
    if not isinstance(causal_chain, dict):
        return "（无历史 archive_writeback）"

    writeback = causal_chain.get("archive_writeback") or {}
    if not writeback:
        return "（无历史 archive_writeback）"

    try:
        blob = json.dumps(writeback, ensure_ascii=False, indent=2)
        if len(blob) > 3000:
            blob = blob[:3000] + "\n…（截断）"
        return f"（来自上一事件 `{current_event.get('event_id', '?')}`）\n{blob}"
    except (TypeError, ValueError):
        return "（archive_writeback 格式异常）"


async def _get_world_lexicon_active_text(project_id: str, state: CreationState) -> str:
    """
    读取 world_lexicon 中 active 词条，按优先级注入 World Tick：
    优先级1：C类（携带未完整线索）
    优先级2：B类（可持有，被多方关联的）
    优先级3：当前进行中的 A类
    """
    # 优先从 state 读（最新）
    lexicon_state = state.get("world_lexicon") or []
    entries: list[dict] = []

    if lexicon_state:
        for entry in lexicon_state:
            if not isinstance(entry, dict):
                continue
            ttype = entry.get("term_type", "A")
            dyn = entry.get("dynamic_associations") or []
            has_active = any(isinstance(d, dict) and d.get("is_active", False) for d in dyn)
            clue = entry.get("incomplete_clue") or {}
            if ttype == "C" or has_active:
                entries.append(entry)
    elif project_id:
        try:
            entries = await get_active_lexicon_entries(project_id, limit=20)
        except Exception as exc:
            logger.warning("读取 world_lexicon 失败：%s", exc)
            return "（词条库读取失败）"

    if not entries:
        return "（当前无 active 词条）"

    # 按优先级排序：C类 > B类 > A类
    type_order = {"C": 0, "B": 1, "A": 2}
    entries.sort(key=lambda e: type_order.get(e.get("term_type", "A"), 3))

    lines = []
    for e in entries[:15]:
        term   = e.get("term", "?")
        ttype  = e.get("term_type", "A")
        cat    = e.get("category", "")
        sp     = e.get("static_profile") or {}
        defn   = sp.get("definition", "")[:80]
        clue   = e.get("incomplete_clue") or {}
        has_clue = clue.get("has_incomplete_clue", False)

        # 最新动态关联
        dyn = e.get("dynamic_associations") or []
        active_assoc = next(
            (d for d in reversed(dyn) if isinstance(d, dict) and d.get("is_active", False)),
            None,
        )
        holder_note = ""
        if active_assoc:
            holder  = active_assoc.get("holder") or ""
            ctx     = active_assoc.get("context_note", "")[:60]
            assoc_t = active_assoc.get("association_type", "")
            holder_note = f"（{assoc_t}：{holder or '未知持有者'}，{ctx}）"

        line = f"  【{ttype}类/{cat}】{term}：{defn}{holder_note}"
        if has_clue:
            frag = clue.get("clue_fragment", "")
            trig = clue.get("trigger_condition", "")
            line += f"\n    ⚡不完整线索：{frag}  触发条件：{trig}"
        lines.append(line)

    priority_note = (
        "【注意】C类词条（携带未完整线索）在 World Tick 中应被优先考虑为潜在事件触发点。\n"
        "B类词条（可持有/可竞争）可直接成为资源争夺的焦点。\n"
    )
    return priority_note + "\n".join(lines)


def _determine_next_event_seq(state: CreationState, vol_index: int) -> int:
    """根据 completed_events_summary 确定本事件的序号。"""
    completed = state.get("completed_events_summary") or []
    if not isinstance(completed, list):
        return 1
    # 统计当前卷的事件数
    vol_prefix = f"ev_{vol_index + 1}_"
    count = sum(
        1 for e in completed
        if isinstance(e, dict) and str(e.get("event_id", "")).startswith(vol_prefix)
    )
    return count + 1


def _check_anchor_touched(event_result: dict, arc_anchors: list, anchor_progress: dict) -> tuple[str | None, dict]:
    """
    检查本事件是否触达某个锚点，返回 (touched_anchor_id, updated_anchor_progress)。
    """
    if not isinstance(event_result, dict):
        return None, anchor_progress

    anchor_check = event_result.get("anchor_check") or {}
    if not isinstance(anchor_check, dict):
        return None, anchor_progress

    arrival_met = anchor_check.get("arrival_condition_met", False)
    completion_verified = anchor_check.get("completion_signal_verified", False)
    nearest_id = anchor_check.get("nearest_pending_anchor_id")

    if not arrival_met or not completion_verified:
        return None, anchor_progress

    # 更新 anchor_progress
    updated = dict(anchor_progress) if isinstance(anchor_progress, dict) else {}
    completed_list = list(updated.get("completed", []))
    pending_list = list(updated.get("pending", []))

    if nearest_id is not None and nearest_id not in completed_list:
        completed_list.append(nearest_id)
        if nearest_id in pending_list:
            pending_list.remove(nearest_id)

    updated["completed"] = completed_list
    updated["pending"] = pending_list
    return nearest_id, updated


def _initialize_anchor_progress(arc_anchors: list, existing: dict | None) -> dict:
    """如果 anchor_progress 尚未初始化，根据 arc_anchors 建立初始状态。"""
    if existing and isinstance(existing, dict) and (existing.get("pending") or existing.get("completed")):
        return existing
    all_ids = [a.get("anchor_id") for a in arc_anchors if isinstance(a, dict)]
    return {"completed": [], "pending": all_ids}


# ─── 主节点 ────────────────────────────────────────────────────────────────────

async def event_chain_gen_node(state: CreationState) -> Command:
    """
    v4.3 单事件生成节点：
    1. 从 state 读取 anchor_progress（确定下一个待完成锚点）
    2. 从 state 读取 completed_events_summary（全局防重复）
    3. 从 state 读取上一个事件的 causal_output
    4. 调用新提示词，输出单事件 JSON
    5. 将新事件追加到 completed_events_summary
    6. 更新 anchor_progress（若本事件触达锚点）
    7. 返回 Command(update={...}, goto="human_review_event")
    """
    project_id = state.get("project_id", "")
    vol_index = int(state.get("current_volume_index", 0) or 0)

    # 加载卷信息
    volumes = list(state.get("volumes") or [])
    if not volumes and project_id:
        volumes = await get_volumes(project_id)

    if vol_index >= len(volumes):
        logger.warning("卷索引越界：%s，共 %s 卷", vol_index, len(volumes))
        return Command(goto="human_review_batch")

    current_vol = volumes[vol_index]
    arc_anchors = _get_arc_anchors(current_vol)

    # 初始化 anchor_progress
    anchor_progress = _initialize_anchor_progress(
        arc_anchors, state.get("anchor_progress")
    )

    # 确定待完成锚点列表和下一个锚点
    pending_anchor_ids = anchor_progress.get("pending", [])
    completed_anchor_ids = anchor_progress.get("completed", [])

    event_seq = _determine_next_event_seq(state, vol_index)
    event_id = f"ev_{vol_index + 1}_{event_seq:03d}"

    node_step(
        f"事件链：单事件生成 — {event_id}（卷 {vol_index + 1}，序号 {event_seq}）"
    )

    # 准备 prompt 输入块
    world_archive_text = _get_world_archive_text(state)
    entity_cards_block = await _get_entity_cards_text(project_id, vol_index)
    protagonist_archive_text = _get_protagonist_archive_text(state)
    world_lexicon_active_text = await _get_world_lexicon_active_text(project_id, state)
    karmic_ledger_text = _karmic_ledger_prompt_block(state)
    arc_anchors_text = format_arc_anchors_for_event_gen(arc_anchors, anchor_progress)
    last_causal_output = _get_last_causal_output(state)
    completed_events_text = format_completed_events_summary(
        state.get("completed_events_summary") or []
    )
    archive_writeback_snapshot = _build_archive_writeback_snapshot(state)
    platform_style_block = platform_planning_bundle(state, skin_max_chars=0)
    # 补丁 D：任务栈驱动 Protagonist Tick
    quest_stack_section = _build_quest_stack_for_protagonist_tick(state)

    user_prompt = EVENT_CHAIN_GEN_USER_TEMPLATE.format(
        quest_stack_section=quest_stack_section,
        world_archive=world_archive_text,
        entity_cards_block=entity_cards_block,
        protagonist_archive=protagonist_archive_text,
        world_lexicon_active=world_lexicon_active_text,
        karmic_ledger=karmic_ledger_text or "（无）",
        arc_anchors=arc_anchors_text,
        completed_anchors=json.dumps(completed_anchor_ids, ensure_ascii=False),
        pending_anchors=json.dumps(pending_anchor_ids, ensure_ascii=False),
        last_causal_output=last_causal_output,
        completed_events_summary=completed_events_text,
        archive_writeback_snapshot=archive_writeback_snapshot,
        platform_style_block=platform_style_block,
        volume_index=vol_index + 1,
        event_seq=f"{event_seq:03d}",
        event_id=event_id,
    )

    raw = await call_llm_json(EVENT_CHAIN_GEN_SYSTEM, user_prompt, max_tokens=6000)

    # 处理 LLM 输出
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        raw = raw[0]
    if not isinstance(raw, dict):
        logger.warning("event_chain_gen 单事件生成返回非 dict，使用占位")
        raw = {}

    # 注入/修正关键字段
    raw["event_id"] = raw.get("event_id") or event_id
    raw["event_seq"] = event_seq
    raw["volume_index"] = vol_index

    # 检查是否触达锚点并更新 anchor_progress
    touched_anchor_id, updated_anchor_progress = _check_anchor_touched(
        raw, arc_anchors, anchor_progress
    )

    if touched_anchor_id is not None:
        node_step(f"事件链：锚点 {touched_anchor_id} 已触达，更新 anchor_progress")

    # 构建追加到 completed_events_summary 的摘要条目
    new_summary_entry = {
        "event_id": raw.get("event_id", event_id),
        "event_name": raw.get("event_name", "（未命名）"),
        "conflict_type": (raw.get("event_core") or {}).get("conflict_type", ""),
        "primary_resource_used": (raw.get("event_core") or {}).get("primary_resource_used", ""),
        "anchor_touched": touched_anchor_id,
    }

    # 追加 completed_events_summary
    existing_summary = list(state.get("completed_events_summary") or [])
    updated_summary = existing_summary + [new_summary_entry]

    post_pending = updated_anchor_progress.get("pending", [])
    node_done(
        f"单事件生成完成：{raw.get('event_name', event_id)}"
        + (f"（触达锚点 {touched_anchor_id}）" if touched_anchor_id else "")
        + f"  待完成锚点→{post_pending}"
    )

    # 根据是否为自动模式决定路由目标
    # v4.3 自动模式应直接进入 path_gen_v43，而不是旧的 path_gen
    auto_mode = state.get("auto_mode", False)
    goto_target = "path_gen_v43" if auto_mode else "human_review_event"

    return Command(
        update={
            "current_event": raw,
            "completed_events_summary": updated_summary,
            "anchor_progress": updated_anchor_progress,
        },
        goto=goto_target,
    )
