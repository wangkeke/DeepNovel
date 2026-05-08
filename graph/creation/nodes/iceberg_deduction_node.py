"""
iceberg_deduction_node：仅执行 LLM（阶段1 并发 world+cast → 阶段2 synopsis），
结果写入 iceberg_review_payload；审核在 human_review_iceberg_node，避免 resume 时整段重跑。
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid as _uuid
from langgraph.types import StreamWriter, Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from knowledge.story_variables import map_genre_bucket, describe_targeting, describe_emotional, sample_variables
from prompts.creation.genesis_iceberg import (
    ICEBERG_PROMPT4_SYSTEM,
    ICEBERG_PROMPT4_USER,
    ICEBERG_STAGE1_WORLD_SYSTEM,
    ICEBERG_STAGE1_WORLD_USER,
    ICEBERG_STAGE1_CAST_SYSTEM,
    ICEBERG_STAGE1_CAST_USER,
    ICEBERG_STAGE2_SYNOPSIS_SYSTEM,
    ICEBERG_STAGE2_SYNOPSIS_USER,
    platform_hint_for,
)
from graph.creation.genesis_merge import (
    world_setting_from_iceberg,
    synopsis_merge,
    protagonist_card_from_iceberg,
    protagonist_name_from_cast_local,
)
from graph.creation.iceberg_anchor import format_iceberg_anchor_block
from utils.brainwave_engine import (
    brainwave_engine_from_state,
    brainwave_prompt_block,
    quest_dict_from_brainwave,
    strip_brainwave_and_collision_immediate,
)
from utils.v42_flow import (
    protagonist_archive_prompt_block,
    shallow_world_archive,
    synthetic_opening_anchor_for_iceberg,
)
from prompts.creation.platform_styles import (
    ANTI_CLICHE_AND_TEXTURE_RULES,
    DEMOGRAPHIC_NARRATIVE_RULES,
)

logger = logging.getLogger("deepnovel.iceberg_deduction")


def _extract_initial_quests_from_prompt4(
    prompt4_raw: dict,
    existing_stack: list,
) -> list:
    """
    从 PROMPT4 开篇碰撞输出提取 immediate 层初始任务，推入任务栈。
    来源字段：protagonist_tick_at_opening.deepest_need + opening_collision
    """
    if not isinstance(prompt4_raw, dict) or not prompt4_raw:
        return existing_stack

    pt = prompt4_raw.get("protagonist_tick_at_opening")
    if not isinstance(pt, dict):
        pt = {}
    deepest_need = str(pt.get("deepest_need") or "").strip()
    if not deepest_need:
        return existing_stack

    col = prompt4_raw.get("opening_collision")
    if not isinstance(col, dict):
        col = {}
    collision_cause = str(
        col.get("collision_trigger") or col.get("why_inevitable") or ""
    ).strip()
    collision_outcome = str(col.get("collision_outcome") or "").strip()

    # 推导 immediate 层任务的属性
    quest_id = f"AQ_INIT_{_uuid.uuid4().hex[:6].upper()}"
    deadline_note = str(pt.get("time_pressure") or col.get("time_limit") or "").strip() or None
    emotional_weight = str(
        pt.get("emotional_stakes") or col.get("emotional_cost") or ""
    ).strip()
    completion_cond = str(
        col.get("resolution_hint") or collision_outcome or ""
    ).strip()[:200] or "主角成功渡过开篇危机，脱离当前困境"

    new_quest: dict = {
        "quest_id": quest_id,
        "quest_name": deepest_need[:60],
        "quest_origin": (
            f"opening_collision（{collision_cause[:100]}）"
            if collision_cause else "opening_collision（开篇碰撞）"
        ),
        "urgency_level": "critical",
        "deadline_note": deadline_note,
        "current_sub_goal": deepest_need[:150],
        "layer": "immediate",
        "completion_condition": completion_cond,
        "failure_condition": str(col.get("failure_condition") or "").strip()[:150] or None,
        "evolution_on_completion": None,
        "evolution_on_failure": None,
        "status": "active",
        "planted_chapter": "opening_collision",
        "emotional_weight": emotional_weight[:200] if emotional_weight else "",
    }

    # 过滤掉旧的 immediate 层同名任务，避免重复
    updated = [
        q for q in existing_stack
        if not (isinstance(q, dict) and q.get("layer") == "immediate"
                and q.get("planted_chapter") == "opening_collision")
    ]
    updated.append(new_quest)
    return updated


def _iceberg_demographic_block(platform_style: str) -> str:
    ps = (platform_style or "").strip() or "通用网文"
    return f"\n\n当前平台：{ps}\n{DEMOGRAPHIC_NARRATIVE_RULES}"


def _iceberg_user_anchor_injections(state: CreationState) -> tuple[str, str, str]:
    """(world_user_suffix, cast_user_suffix, synopsis_user_suffix)，解耦滴灌。"""
    ua = state.get("user_anchors") or {}
    if not isinstance(ua, dict):
        return "", "", ""
    rules = ua.get("world_rules")
    if not isinstance(rules, list):
        rules = []
    rules_str = (
        f"\n【用户指定世界法则】须作为世界观承重墙落实：{json.dumps(rules, ensure_ascii=False)}\n"
        if rules
        else ""
    )
    cast_bits: list[str] = []
    prot = ua.get("protagonist")
    if isinstance(prot, dict) and (prot.get("name") or prot.get("setting")):
        cast_bits.append(f"主角锚点：{json.dumps(prot, ensure_ascii=False)}")
    chars = ua.get("characters")
    if isinstance(chars, list) and chars:
        cast_bits.append(f"须编入班底：{json.dumps(chars, ensure_ascii=False)}")
    chars_str = (
        "\n【用户指定配角/核心人物】须无缝编织进核心班底（人名与身份勿篡改）：\n"
        + "\n".join(cast_bits)
        + "\n"
        if cast_bits
        else ""
    )
    emo = ua.get("emotional_lines")
    if not isinstance(emo, list):
        emo = []
    emo_str = (
        f"\n【用户情感与爽点诉求】宏观构思须深度融合：{json.dumps(emo, ensure_ascii=False)}\n"
        if emo
        else ""
    )
    return rules_str, chars_str, emo_str


def _vblock(genre_request: str, v: dict) -> str:
    td = int(v.get("targeting_degree") or 0)
    ed = int(v.get("emotional_degree") or 0)
    return (
        f"题材桶：{v.get('genre_bucket') or map_genre_bucket(genre_request)}\n"
        f"针对度 {td}：{describe_targeting(td)}\n"
        f"情感度 {ed}：{describe_emotional(ed)}\n"
        f"人性逻辑：{v.get('human_logic', '')}\n"
        f"故事模式：{v.get('story_mode', '')}\n"
        f"金手指：{v.get('fictional_hook', '')}\n"
    )


def _existing_protagonist_for_iceberg(state: CreationState) -> dict | None:
    """已确认的主角卡优先于冰山预填 genesis_protagonist_card。"""
    pc = dict(state.get("protagonist_card") or {})
    if (pc.get("standard_name") or "").strip():
        return pc
    g = dict(state.get("genesis_protagonist_card") or {})
    if (g.get("standard_name") or "").strip():
        return g
    return None


def _enrich_pc_from_local_cast(pc: dict, cast_raw: dict) -> dict:
    """把 local_cast 主角行上的心智/逆鳞补进 protagonist_card 草稿（避免模型只写一侧）。"""
    out = dict(pc or {})
    prot_name = (out.get("standard_name") or "").strip()
    for c in (cast_raw or {}).get("local_cast") or []:
        if not isinstance(c, dict):
            continue
        if str(c.get("role", "")).strip() != "protagonist_side":
            continue
        cn = (c.get("name") or "").strip()
        if prot_name and cn and cn != prot_name:
            continue
        for key in ("current_mental_state", "mental_growth_path", "reverse_scale"):
            v = str(c.get(key) or "").strip()
            if v and not str(out.get(key) or "").strip():
                out[key] = v
        break
    return out


async def iceberg_deduction_node(state: CreationState, writer: StreamWriter) -> Command:
    writer({"node_status": "started", "node": "iceberg_deduction"})
    genre_request = state.get("genre_request", "")
    platform_style = (state.get("platform_style") or "").strip() or "通用网文"
    variables = state.get("genesis_variables") or {}
    genesis_var_update: dict = {}
    if not variables:
        variables = sample_variables(genre_request)
        genesis_var_update["genesis_variables"] = variables

    opening = (state.get("genesis_opening_text") or "").strip()
    if not opening:
        opening = synthetic_opening_anchor_for_iceberg(state)
    extra = (state.get("iceberg_deduction_feedback") or "").strip()

    synopsis_only_flag = bool(state.get("iceberg_synopsis_only"))
    cached_w = state.get("iceberg_stage1_world_raw") or {}
    cached_c = state.get("iceberg_stage1_cast_raw") or {}
    can_synopsis_only = (
        synopsis_only_flag
        and isinstance(cached_w, dict)
        and isinstance(cached_c, dict)
        and bool(cached_w)
        and bool(cached_c)
    )

    vb = _vblock(genre_request, variables)
    anchor_block = format_iceberg_anchor_block(opening)
    demo_block = _iceberg_demographic_block(platform_style)
    texture_block = f"\n\n{ANTI_CLICHE_AND_TEXTURE_RULES}"
    rules_anchor_str, chars_anchor_str, emo_anchor_str = _iceberg_user_anchor_injections(state)

    ws_confirmed = state.get("world_setting") if isinstance(state.get("world_setting"), dict) else {}
    pc_confirmed = state.get("protagonist_card") if isinstance(state.get("protagonist_card"), dict) else {}
    wa = state.get("world_archive")
    if not isinstance(wa, dict) or not (
        (str(wa.get("basic_rules") or "").strip())
        or (wa.get("power_structure") or [])
    ):
        wa = shallow_world_archive(ws_confirmed)

    syn_stored = state.get("synopsis") if isinstance(state.get("synopsis"), dict) else {}
    cached_p4 = syn_stored.get("iceberg_prompt4")

    prompt4_raw: dict = {}
    if can_synopsis_only and isinstance(cached_p4, dict) and cached_p4:
        prompt4_raw = cached_p4
    else:
        node_step("冰山·PROMPT4：开篇碰撞与暗流（结构化 JSON）")
        p4_user = ICEBERG_PROMPT4_USER.format(
            world_archive_json=json.dumps(wa, ensure_ascii=False, indent=2),
            protagonist_archive_text=protagonist_archive_prompt_block(pc_confirmed, max_chars=10000),
            variables_block=vb,
            genre_request=genre_request,
            extra_feedback=extra or "（无）",
        ) + brainwave_prompt_block(state)
        raw_p4 = await call_llm_json(
            ICEBERG_PROMPT4_SYSTEM + demo_block + texture_block,
            p4_user,
            max_tokens=4096,
        )
        prompt4_raw = raw_p4 if isinstance(raw_p4, dict) else {}
        if not prompt4_raw:
            logger.warning("iceberg PROMPT4 返回空 JSON，阶段1/2 将仅依赖档案锚点")

    p4_json_str = json.dumps(prompt4_raw, ensure_ascii=False, indent=2) if prompt4_raw else ""
    prompt4_chain_block = ""
    if p4_json_str.strip() and p4_json_str not in ("{}", "null"):
        prompt4_chain_block = (
            "\n## 【PROMPT4 开篇推导（阶段1/2 须与此自洽；主角必须与 protagonist_archive 一致）】\n"
            + p4_json_str
            + "\n"
        )

    pn_lock = (pc_confirmed.get("standard_name") or "").strip()
    protagonist_name_lock = ""
    if pn_lock:
        protagonist_name_lock = (
            f"\n【主角姓名铁律】local_cast 中 protagonist_side 的 name、protagonist_card.standard_name 必须为「{pn_lock}」，"
            "禁止改名、禁止套娃别名顶替、禁止性转。\n"
        )

    if can_synopsis_only:
        world_raw, cast_raw = cached_w, cached_c
        node_step("冰山·阶段2：宏观构思统合（沿用已定世界与班底快照）")
    else:
        node_step("冰山·阶段1：世界与班底（并发）")
        w_user = ICEBERG_STAGE1_WORLD_USER.format(
            anchor_block=anchor_block,
            variables_block=vb,
            opening_text=opening,
        ) + rules_anchor_str + prompt4_chain_block + brainwave_prompt_block(state)
        c_user = ICEBERG_STAGE1_CAST_USER.format(
            anchor_block=anchor_block,
            variables_block=vb,
            opening_text=opening,
        ) + chars_anchor_str + protagonist_name_lock + prompt4_chain_block + brainwave_prompt_block(state)
        world_raw, cast_raw = await asyncio.gather(
            call_llm_json(ICEBERG_STAGE1_WORLD_SYSTEM + demo_block + texture_block, w_user),
            call_llm_json(ICEBERG_STAGE1_CAST_SYSTEM + demo_block + texture_block, c_user),
        )
        if not isinstance(world_raw, dict):
            world_raw = {}
        if not isinstance(cast_raw, dict):
            cast_raw = {}

    if not can_synopsis_only:
        node_step("冰山·阶段2：宏观构思统合")
    sys2 = ICEBERG_STAGE2_SYNOPSIS_SYSTEM.format(
        platform_hint_block=platform_hint_for(platform_style),
    ) + demo_block + texture_block
    user2 = ICEBERG_STAGE2_SYNOPSIS_USER.format(
        prompt4_block=prompt4_chain_block or "\n",
        anchor_block=anchor_block,
        genre_request=genre_request,
        variables_block=vb,
        opening_text=opening,
        world_json=json.dumps(world_raw, ensure_ascii=False, indent=2),
        cast_json=json.dumps(cast_raw, ensure_ascii=False, indent=2),
        extra_feedback=extra or "（无）",
    ) + emo_anchor_str + brainwave_prompt_block(state)
    stage2 = await call_llm_json(sys2, user2)
    if not isinstance(stage2, dict):
        stage2 = {}

    merged_synopsis = synopsis_merge(
        stage2, opening, variables, genre_request, iceberg_prompt4=prompt4_raw
    )

    if can_synopsis_only:
        merged_world = dict(state.get("world_setting") or {})
        if not merged_world:
            merged_world = world_setting_from_iceberg(
                world_raw, genre_request, state.get("world_setting") or {}
            )
        ex0 = _existing_protagonist_for_iceberg(state)
        protagonist_card = dict(ex0) if ex0 else dict(state.get("genesis_protagonist_card") or {})
        if not protagonist_card.get("standard_name"):
            pc_ice = (
                cast_raw.get("protagonist_card")
                if isinstance(cast_raw.get("protagonist_card"), dict)
                else {}
            )
            if not pc_ice.get("standard_name"):
                _pn = protagonist_name_from_cast_local(cast_raw)
                pc_ice = {
                    "standard_name": _pn or "主角",
                    "appearance": "见开篇呈现",
                    "current_mental_state": "",
                    "mental_growth_path": "",
                    "reverse_scale": "",
                    "background_summary": merged_synopsis.get("protagonist", "")[:400],
                    "traits_display": ["遇险反应见开篇", "执念见开篇不可逆推动力"],
                    "dominant_logics": [str(variables.get("human_logic") or "忍辱逻辑")],
                    "immediate_motive": (merged_synopsis.get("volume_1_goal") or "")[:200],
                    "destiny_seed": (merged_synopsis.get("ultimate_goal") or "")[:200],
                }
            pc_ice = _enrich_pc_from_local_cast(pc_ice, cast_raw)
            _existing = _existing_protagonist_for_iceberg(state)
            protagonist_card = protagonist_card_from_iceberg(
                pc_ice, existing_card=_existing or (protagonist_card if protagonist_card.get("standard_name") else None)
            )
    else:
        merged_world = world_setting_from_iceberg(
            world_raw, genre_request, state.get("world_setting") or {}
        )
        pc_ice = (
            cast_raw.get("protagonist_card")
            if isinstance(cast_raw.get("protagonist_card"), dict)
            else {}
        )
        if not pc_ice.get("standard_name"):
            _pn = protagonist_name_from_cast_local(cast_raw)
            pc_ice = {
                "standard_name": _pn or "主角",
                "appearance": "见开篇呈现",
                "current_mental_state": "",
                "mental_growth_path": "",
                "reverse_scale": "",
                "background_summary": merged_synopsis.get("protagonist", "")[:400],
                "traits_display": ["遇险反应见开篇", "执念见开篇不可逆推动力"],
                "dominant_logics": [str(variables.get("human_logic") or "忍辱逻辑")],
                "immediate_motive": (merged_synopsis.get("volume_1_goal") or "")[:200],
                "destiny_seed": (merged_synopsis.get("ultimate_goal") or "")[:200],
            }
        pc_ice = _enrich_pc_from_local_cast(pc_ice, cast_raw)
        _existing_full = _existing_protagonist_for_iceberg(state)
        protagonist_card = protagonist_card_from_iceberg(pc_ice, existing_card=_existing_full)

    review_payload = {
        "opening_text": opening,
        "synopsis": merged_synopsis,
        "world_setting": merged_world,
        "protagonist_card": protagonist_card,
    }
    if can_synopsis_only:
        node_done("宏观构思已按意见重算（世界与班底与已确认稿一致）")
    else:
        node_done("冰山反推草案已就绪")
    # 从 PROMPT4 开篇碰撞提取初始任务；若无则回退脑洞引擎 first_quest（补丁 E）
    existing_stack = strip_brainwave_and_collision_immediate(
        list(state.get("active_quest_stack") or [])
    )
    updated_stack = _extract_initial_quests_from_prompt4(prompt4_raw, existing_stack)
    if not any(
        isinstance(q, dict)
        and q.get("layer") == "immediate"
        and q.get("planted_chapter") == "opening_collision"
        for q in updated_stack
    ):
        bq = quest_dict_from_brainwave(brainwave_engine_from_state(state))
        if bq:
            updated_stack = list(updated_stack) + [bq]

    payload_update = {
        "iceberg_review_payload": review_payload,
        "iceberg_stage1_world_raw": world_raw,
        "iceberg_stage1_cast_raw": cast_raw,
        "iceberg_synopsis_only": False,
        "iceberg_deduction_feedback": "",
        "active_quest_stack": updated_stack,
    }
    payload_update.update(genesis_var_update)
    return Command(
        update=payload_update,
        goto="human_review_iceberg",
    )
