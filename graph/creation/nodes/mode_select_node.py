"""
mode_select_node：创作模式选择节点

在所有全局设定确认完成后、第一次 event_chain_gen / path_gen 之前统一询问一次。
普通流程和已有故事方向流程都会经过此节点。
续传时跳过（resume_from_db 时已从 DB 加载模式）。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.db import update_project_mode


async def mode_select_node(state: CreationState) -> Command:
    """
    在所有全局设定确认完成后，询问创作模式。
    人工模式 / 自动模式。
    只执行一次，续传时跳过。
    """
    if state.get("resume_from_db"):
        return Command(goto="path_gen")

    user_input = interrupt({
        "type": "mode_select",
        "prompt": (
            "请选择创作模式：\n"
            "[1] 人工模式（每个节点都需要确认）\n"
            "[2] 自动模式（全自动推进，方向问题时自动修正）"
        ),
    })

    auto_mode = user_input.get("auto_mode", False)
    max_chapters = user_input.get("max_chapters", 0)

    await update_project_mode(
        state["project_id"],
        auto_mode=auto_mode,
        max_chapters=max_chapters,
    )

    return Command(
        update={
            "auto_mode": auto_mode,
            "max_chapters": max_chapters,
        },
        goto="event_chain_gen",
    )
