"""
human_review_brainwave_node：脑洞引擎产出后的人审

在 idea_forge 写入 user_anchors / brainwave_engine / narrative_era 等之后中断，
用户确认后再进入 world_build；若要求调整则带着意见回到 idea_forge 重炼。
"""
from __future__ import annotations

from langgraph.types import Command, interrupt

from schemas.state import CreationState


async def human_review_brainwave_node(state: CreationState) -> Command:
    user_input = interrupt(
        {
            "type": "brainwave_review",
            "content": {
                "narrative_era": state.get("narrative_era") or "",
                "user_anchors": state.get("user_anchors") or {},
                "brainwave_engine": state.get("brainwave_engine") or {},
                "genesis_variables": state.get("genesis_variables") or {},
            },
        }
    )

    action = user_input.get("action", "approve")
    if action == "approve":
        return Command(
            update={"brainwave_approved": True},
            goto="world_build",
        )

    feedback = str(user_input.get("feedback", "") or "").strip()
    return Command(
        update={
            "brainwave_approved": False,
            "brainwave_regen_feedback": feedback,
        },
        goto="idea_forge",
    )
