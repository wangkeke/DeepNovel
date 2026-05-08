"""
auto_arc_transition_node：v4.3 卷末自动过渡（单卷全自动 / 全书自动）

在 bible_update 判定 trigger_arc_end 且 auto_mode + auto_target 为 arc/book 时进入。
职责：推进 current_volume_index、重建 milestone_progress、重置路径相关状态、对齐下一跳与 auto_review batch。
"""
from __future__ import annotations

import logging

from langgraph.graph import END
from langgraph.types import Command

from schemas.state import CreationState
from utils.volume_milestones import (
    default_milestone_conditions_placeholder,
    get_volume_milestones,
    initialize_milestone_progress,
)

logger = logging.getLogger(__name__)


def _milestones_for_volume(vol: dict) -> list:
    m = get_volume_milestones(vol)
    if m:
        return m
    return [dict(x) for x in default_milestone_conditions_placeholder()]


def _settle_arc_level_quests(stack: list) -> list:
    """将本卷 arc_level 活跃任务标为 completed（卷过渡结账）。"""
    out: list = []
    for q in stack or []:
        if not isinstance(q, dict):
            out.append(q)
            continue
        if q.get("layer") == "arc_level" and q.get("status") == "active":
            q = dict(q)
            q["status"] = "completed"
            q.setdefault("completion_note", "volume_transition")
        out.append(q)
    return out


async def auto_arc_transition_node(state: CreationState) -> Command:
    was_v43 = bool(state.get("current_event_paths"))
    auto_target = (state.get("auto_target") or "book").strip().lower()
    vol_idx = int(state.get("current_volume_index", 0) or 0)
    volumes = list(state.get("volumes") or [])
    next_vol_idx = vol_idx + 1
    new_baseline = int(state.get("global_settled_event_count", 0) or 0)

    # ── 全书已写完（最后一卷之后）────────────────────────────────────────────
    if next_vol_idx >= len(volumes):
        logger.info(
            "auto_arc_transition：全书完结 vol_idx=%s volumes=%s",
            vol_idx,
            len(volumes),
        )
        return Command(
            update={
                "creation_complete": True,
                "loop_control": {
                    "inner_loop_complete": True,
                    "outer_loop_action": "continue_event_loop",
                },
                "pending_review_type": "",
            },
            goto=END,
        )

    next_vol = volumes[next_vol_idx] if isinstance(volumes[next_vol_idx], dict) else {}
    milestones = _milestones_for_volume(next_vol)
    mp = initialize_milestone_progress(milestones, None)

    settled_quests = _settle_arc_level_quests(list(state.get("active_quest_stack") or []))

    base_update: dict = {
        "current_volume_index": next_vol_idx,
        "volume_start_event_count": new_baseline,
        "milestone_progress": mp,
        "active_quest_stack": settled_quests,
        "current_event": {},
        "current_event_paths": {},
        "path_progress": {
            "current_event_id": "",
            "completed_paths": [],
            "remaining_paths": [],
        },
        "loop_control": {
            "inner_loop_complete": True,
            "outer_loop_action": "continue_event_loop",
            "pending_milestones_count": len(mp.get("pending", [])),
            "volume_event_count": new_baseline,
        },
        "story_path": [],
        "path_approved": False,
        "current_node_index": 0,
        "batch_index": int(state.get("batch_index", 0) or 0) + 1,
        "auto_total_retry_count": 0,
        "pending_review_type": "",
    }

    # auto_target == arc：卷末待人开下一卷（与人工 batch 对齐）
    if auto_target == "arc":
        logger.info("auto_arc_transition：单卷自动结束，进入 human_review_batch（arc）")
        return Command(update=base_update, goto="human_review_batch")

    # auto_target == book：与 auto_review._review_batch 对齐下一跳
    chain = list(state.get("current_event_chain") or [])
    pos = int(state.get("current_event_chain_pos", 0) or 0)

    if was_v43:
        logger.info("auto_arc_transition：跨卷继续（v4.3）→ event_chain_gen")
        base_update["current_event_chain"] = []
        base_update["current_event_chain_pos"] = 0
        base_update["last_event_batch_size"] = 0
        return Command(update=base_update, goto="event_chain_gen")

    if chain and pos >= len(chain) and next_vol_idx < len(volumes):
        base_update["current_event_chain"] = []
        base_update["current_event_chain_pos"] = 0
        base_update["last_event_batch_size"] = 0
        logger.info("auto_arc_transition：旧事件链耗尽 → event_chain_gen")
        return Command(update=base_update, goto="event_chain_gen")

    logger.info("auto_arc_transition：默认 → path_gen")
    return Command(update=base_update, goto="path_gen")
