"""
consistency_node：正文一致性检查节点（补丁 F）

write 之后、tension_check 之前执行。
两套检验：物理/路径/悬念 + 叙事质量；输出 verdict 与 routing_decision。
超过最大重写次数时强制通过，防止死循环。
"""
from __future__ import annotations
import json
import logging

from langgraph.types import Command

from schemas.state import CreationState
from prompts.common.era_lexicon_filter import era_lexicon_system_suffix
from prompts.creation.consistency import CONSISTENCY_SYSTEM, CONSISTENCY_USER_TEMPLATE
from utils.llm import call_llm_json
from utils.display import node_warn

# 与 tension_check 对齐的 logger 名，便于终端里一眼区分「一致性」与「张力」两步质检
logger = logging.getLogger("deepnovel.consistency")

MAX_REWRITES = 3


def _json_block(obj: object, limit: int = 8000) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        s = str(obj)
    if len(s) > limit:
        return s[: limit - 20] + "\n…（截断）"
    return s


def _scene_snapshot_block(state: CreationState) -> str:
    snap = state.get("scene_snapshot") or {}
    if not isinstance(snap, dict) or not snap:
        return "（无 scene_snapshot — 非 v4.3 落盘流程或首章前。）\n第一套检验中空间/资产/悬念相关项请标为 na。"
    return _json_block(snap, 6000)


def _event_paths_block(state: CreationState) -> str:
    """
    v4.3 多路径事件按 path_progress.remaining_paths 逐条写正文；单章/单段只覆盖
    current_path_id。若仍把整表 events paths 喂给 LLM，检验四会误把「只写了 p01」
    判为缺 p02–p04。故在存在 remaining[0] 时，只把 current_path_only 作为完整性依据。
    """
    ep = state.get("current_event_paths") or {}
    paths = ep.get("paths") if isinstance(ep, dict) else None
    if not isinstance(ep, dict) or not isinstance(paths, list) or not paths:
        return "（无 current_event_paths — 不做路径完整性检验，path_completeness_check 标 na。）"

    pp = state.get("path_progress")
    if not isinstance(pp, dict):
        pp = {}
    remaining = [str(x).strip() for x in (pp.get("remaining_paths") or []) if str(x).strip()]
    current_id = remaining[0] if remaining else ""

    if not current_id:
        return _json_block(ep, 8000)

    current_def: dict | None = None
    other_ids: list[str] = []
    for p in paths:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("path_id") or "").strip()
        if not pid:
            continue
        if pid == current_id:
            current_def = p
        else:
            other_ids.append(pid)

    if current_def is None:
        return _json_block(ep, 8000)

    header = (
        "【本章仅检验单条路径·v4.3 分段写作】\n"
        f"当前写作 path_id = `{current_id}`。路径完整性（检验四）**只对照**下面 "
        "`current_path_only`；同事件内其它 path 将后续轮次完成，未写不属缺失。\n"
        f"本事件路径数：{len(paths)}；与当前并行的其它 path_id：{other_ids}\n\n"
    )
    payload = {
        "event_name": ep.get("event_name"),
        "event_id": ep.get("event_id"),
        "current_path_id": current_id,
        "current_path_only": current_def,
    }
    return header + _json_block(payload, 8000)


def _lexicon_constraints_block(state: CreationState) -> str:
    lx = state.get("world_lexicon") or []
    if not isinstance(lx, list) or not lx:
        bible = state.get("bible") or {}
        lx = bible.get("world_lexicon") or []
    if not isinstance(lx, list) or not lx:
        return "（无 world_lexicon。）"
    lines: list[str] = []
    for e in lx[:25]:
        if not isinstance(e, dict):
            continue
        lid = e.get("lexicon_id", "?")
        term = e.get("term", "?")
        sp = e.get("static_profile") or {}
        hc = sp.get("hard_constraints") or []
        if isinstance(hc, str):
            hc = [hc]
        if not hc:
            continue
        lines.append(f"- [{lid}] {term}：hard_constraints = {hc[:5]}")
    if not lines:
        return "（词条无 hard_constraints 摘要。）"
    return "\n".join(lines)


def _quest_stack_block(state: CreationState) -> str:
    qs = state.get("active_quest_stack") or []
    if not isinstance(qs, list) or not qs:
        return "（无 active_quest_stack。）"
    lines: list[str] = []
    for q in qs[:20]:
        if not isinstance(q, dict):
            continue
        if q.get("status") != "active":
            continue
        lines.append(
            f"- {q.get('quest_id', '?')} [{q.get('urgency_level', '')}/{q.get('layer', '')}] "
            f"{q.get('quest_name', '')} | sub_goal: {(q.get('current_sub_goal') or '')[:120]}"
        )
    return "\n".join(lines) if lines else "（无活跃任务。）"


def _entity_cards_block(state: CreationState) -> str:
    bible = state.get("bible") or {}
    cards = bible.get("entity_cards") or bible.get("characters") or []
    if isinstance(cards, dict):
        cards = list(cards.values())
    if not isinstance(cards, list) or not cards:
        return "（圣经中无 entity_cards 列表。）"
    lines: list[str] = []
    for c in cards[:18]:
        if not isinstance(c, dict):
            continue
        nm = c.get("name") or c.get("character_name", "?")
        innate = c.get("innate_traits") or []
        if isinstance(innate, str):
            innate = [innate]
        lines.append(f"- {nm}：innate_traits = {innate[:8]}")
    return "\n".join(lines) if lines else "（无可用人物卡摘要。）"


def _merge_bible_rewrite_feedback(state: CreationState, tag: str, detail: str) -> dict:
    bible = dict(state.get("bible") or {})
    prev = (bible.get("rewrite_feedback") or "").strip()
    chunk = f"{tag}\n{detail}".strip()
    bible["rewrite_feedback"] = f"{prev}\n\n{chunk}".strip() if prev else chunk
    return bible


def _map_routing_decision(decision: str, state: CreationState) -> str:
    """将 LLM routing_decision 映射为图中真实节点名。"""
    d = (decision or "write").strip().lower()
    if d == "bible_update":
        # 避免在章节未入库时误入 bible_update；交给 expand2 收敛设计/执行
        return "expand2"
    if d == "event_chain_gen":
        if not state.get("current_event_paths"):
            return "write"
        return "event_chain_gen"
    if d == "expand1":
        return "expand1_v43" if state.get("current_event_paths") else "expand1"
    if d in ("expand2", "write"):
        return d
    return "write"


def _node_label_for_consistency_log(state: CreationState) -> str:
    """与 tension_check 一致：旧 story_path 节点名优先，v4.3 回落到路径名 / 事件名。"""
    current_idx = int(state.get("current_node_index", 0) or 0)
    story_path = state.get("story_path") or []
    if isinstance(story_path, list) and current_idx < len(story_path):
        row = story_path[current_idx]
        if isinstance(row, dict):
            nm = (row.get("node_name") or "").strip()
            if nm:
                return nm
    expand1 = state.get("current_expand1") or {}
    current_event = state.get("current_event") or {}
    event_paths = state.get("current_event_paths") or {}
    path_progress = state.get("path_progress") or {}
    remaining = path_progress.get("remaining_paths") or []
    current_path_id = remaining[0] if remaining else ""
    path_name = ""
    if isinstance(event_paths, dict):
        for p in (event_paths.get("paths") or []):
            if isinstance(p, dict) and p.get("path_id") == current_path_id:
                path_name = (p.get("path_name") or p.get("path_id") or "").strip()
                break
    if isinstance(expand1, dict):
        e1_pid = (expand1.get("path_id") or "").strip()
    else:
        e1_pid = ""
    ev_name = (current_event.get("event_name") or "").strip() if isinstance(current_event, dict) else ""
    return path_name or ev_name or e1_pid or "（未命名）"


async def consistency_node(state: CreationState) -> Command:
    draft = state.get("current_draft", "")
    bible = state.get("bible", {})

    current_idx = state.get("current_node_index", 0)
    story_path = state.get("story_path", [])
    current_node = story_path[current_idx] if current_idx < len(story_path) else {}

    blueprint_weight = state.get("blueprint_weight", 0.5)
    free_creation = state.get("free_creation", False)

    pivot_str = ""
    if state.get("post_pivot", False):
        pivot_str = json.dumps(state.get("pivot_records", []), ensure_ascii=False)

    user_prompt = CONSISTENCY_USER_TEMPLATE.format(
        current_draft=draft[:12000] if draft else "",
        scene_snapshot_block=_scene_snapshot_block(state),
        event_paths_block=_event_paths_block(state),
        bible_summary=_json_block(bible, 10000),
        expected_pressure_type="" if free_creation else current_node.get("pressure_chain_type", ""),
        expected_resolution_type="" if free_creation else current_node.get("resolution_chain_type", ""),
        blueprint_weight="0.0" if free_creation else str(blueprint_weight),
        weight_description=(
            "自由创作模式，只需检查与故事圣经的一致性，不检查骨骼结构"
            if free_creation
            else "权重越高说明越需要严格遵循"
        ),
        pivot_records_if_any=pivot_str,
        lexicon_constraints_block=_lexicon_constraints_block(state),
        quest_stack_block=_quest_stack_block(state),
        entity_cards_block=_entity_cards_block(state),
    )

    consistency_system = CONSISTENCY_SYSTEM + "\n\n" + era_lexicon_system_suffix(state)
    result = await call_llm_json(consistency_system, user_prompt)
    if not isinstance(result, dict):
        result = {}

    verdict = (result.get("verdict") or "").strip().lower()
    passed = result.get("passed", True)
    is_pivot = result.get("is_pivot", False)
    routing = _map_routing_decision(str(result.get("routing_decision", "")), state)
    revision_focus = (result.get("revision_focus") or "").strip()

    if verdict == "approve":
        passed = True
    elif verdict == "revise":
        passed = False

    # 合理扭转：不记为违规、不阻塞去张力质检（与旧版 is_pivot 语义一致）
    effective_pass = bool(passed or is_pivot)

    rewrite_count = int(state.get("rewrite_count", 0) or 0)
    force_pass = False
    if not effective_pass and rewrite_count >= MAX_REWRITES:
        node_warn(
            f"一致性检查已连续失败 {rewrite_count + 1} 次，强制通过。"
            f" revision_focus={revision_focus!r}"
        )
        effective_pass = True
        force_pass = True

    base_update: dict = {
        "consistency_result": result,
        "has_violation": not effective_pass,
        "post_pivot": is_pivot or state.get("post_pivot", False),
        "rewrite_count": rewrite_count + 1 if (not effective_pass and not force_pass) else 0,
    }

    if is_pivot:
        base_update["pivot_records"] = [
            {"node": current_idx, "reason": result.get("pivot_reason")}
        ]

    node_label = _node_label_for_consistency_log(state)

    # 通过 → 张力质检
    if effective_pass:
        if force_pass:
            logger.info(
                "[质检·一致性] 「%s」强制通过（已连续未通过达上限，进入张力质检）",
                node_label,
            )
        elif is_pivot:
            logger.info(
                "[质检·一致性] 「%s」通过（合理扭转，进入张力质检）",
                node_label,
            )
        else:
            logger.info("[质检·一致性] 「%s」通过", node_label)
        return Command(
            update={
                **base_update,
                "_consistency_goto": "tension_check",
            },
            goto="tension_check",
        )

    # 修订 → 按路由回跳；写入 rewrite 提示
    tag = f"【一致性 revise → {routing}】"
    detail = revision_focus or "；".join(result.get("violations") or []) or "请按 routing 回流修正"
    base_update["bible"] = _merge_bible_rewrite_feedback(state, tag, detail)
    tail = detail if len(detail) <= 120 else detail[:117] + "…"
    logger.info("[质检·一致性] 「%s」未通过 → %s（%s）", node_label, routing, tail)

    return Command(
        update={
            **base_update,
            "_consistency_goto": routing,
        },
        goto=routing,
    )
