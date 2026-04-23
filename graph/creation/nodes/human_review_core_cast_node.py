"""
human_review_core_cast_node：确认全书核心班底（仅 interrupt，无 LLM）

interrupt 与耗时生成须分属不同节点，否则 LangGraph resume 会从节点头重跑，
导致班底被重复生成、确认看似被跳过。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.db import update_project_core_cast


async def human_review_core_cast_node(state: CreationState) -> Command:
    result = state.get("core_cast_draft") or {}
    if not isinstance(result, dict) or not (result.get("ultimate_villain") or {}).get("name"):
        return Command(goto="core_cast_gen")

    user_input = interrupt({
        "type": "core_cast_review",
        "content": result,
        "prompt": "请确认全书核心角色班底",
    })
    action = user_input.get("action", "approve")
    if action == "regenerate":
        return Command(
            update={"core_cast_draft": {}},
            goto="core_cast_gen",
        )

    edits = user_input.get("edits") or {}
    if isinstance(edits, dict):
        result = {**result, **edits}

    project_id = state.get("project_id", "")
    if project_id:
        await update_project_core_cast(project_id, result)

    return Command(
        update={"core_cast": result, "core_cast_draft": {}},
        goto="story_arc_plan",
    )
