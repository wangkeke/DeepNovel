"""
human_review_event_node（v4.3）：单事件人工审核节点

interrupt 展示 event_chain_gen 生成的单个事件，等待用户决策：
  - approve    → path_gen_v43（拆解为叙事路径）
  - edit       → 接受用户编辑后的事件内容，同样进入 path_gen_v43
  - regenerate → event_chain_gen（重新生成本事件）
"""
from __future__ import annotations
import logging
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.v42_flow import collision_display_v43

logger = logging.getLogger("deepnovel.human_review_event")


def _summarize_event(event: dict) -> dict:
    """从 current_event 提取展示摘要，避免把大量原始字段全部暴露给前端。"""
    col = event.get("collision", {}) or {}
    ec = event.get("event_core", {}) or {}
    cs, tw = collision_display_v43(
        col if isinstance(col, dict) else {},
        ec if isinstance(ec, dict) else {},
    )
    return {
        "event_id":      event.get("event_id", ""),
        "event_name":    event.get("event_name", ""),
        "event_summary": event.get("event_summary", ""),
        "collision": {
            "conflict_surface": cs,
            "twist":            tw,
        },
        "event_core": {
            "narrative_purpose": event.get("event_core", {}).get("narrative_purpose", ""),
            "character_impact":  event.get("event_core", {}).get("character_impact", ""),
        },
        "milestone_check": event.get("milestone_check", {}),
        "global_context_check": event.get("global_context_check", {}),
    }


async def human_review_event_node(state: CreationState) -> Command:
    current_event: dict = state.get("current_event") or {}

    # 若状态中没有当前事件，直接回到生成节点
    if not current_event:
        logger.warning("human_review_event：current_event 为空，重新生成")
        return Command(goto="event_chain_gen")

    interrupt_payload = {
        "type":    "event_review",
        "content": _summarize_event(current_event),
        "full_event": current_event,
        "prompt":  (
            "请确认此事件（approve / edit / regenerate）\n"
            "• approve    ：接受，进入路径拆解\n"
            "• edit       ：提交编辑后的 full_event，进入路径拆解\n"
            "• regenerate ：驳回，重新生成此事件"
        ),
    }

    user_input = interrupt(interrupt_payload)

    # 防空
    if not isinstance(user_input, dict):
        logger.warning("human_review_event：user_input 非 dict，重新生成")
        return Command(
            update={"current_event": {}},
            goto="event_chain_gen",
        )

    action = user_input.get("action", "approve")

    if action == "regenerate":
        return Command(
            update={"current_event": {}},
            goto="event_chain_gen",
        )

    # approve 或 edit
    if action == "edit" and user_input.get("edited_event"):
        approved_event = dict(user_input["edited_event"])
    else:
        approved_event = current_event

    # 二次防空
    if not approved_event:
        logger.warning("human_review_event：审核后事件为空，重新生成")
        return Command(
            update={"current_event": {}},
            goto="event_chain_gen",
        )

    return Command(
        update={
            "current_event":  approved_event,
            "path_approved":  True,          # 供下游 human_review_event 条件边使用
        },
        goto="path_gen_v43",
    )
