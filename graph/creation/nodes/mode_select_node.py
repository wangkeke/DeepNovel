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
            "[2] 自动模式（全自动推进，方向问题时自动修正）\n\n"
            "自动模式下可选 auto_target（JSON 字段）：\n"
            "  arc — 单卷写完后自动卷过渡，停在 human_review_batch 待人开下一卷；\n"
            "  book — 跨卷自动继续（默认）。"
        ),
    })

    auto_mode = user_input.get("auto_mode", False)
    max_auto_events = int(user_input.get("max_auto_events", 0) or 0)
    auto_target = (user_input.get("auto_target") or "book").strip().lower()
    if auto_target not in ("arc", "book"):
        auto_target = "book"

    await update_project_mode(
        state["project_id"],
        auto_mode=auto_mode,
        max_auto_events=max_auto_events,
    )

    return Command(
        update={
            "auto_mode": auto_mode,
            "max_auto_events": max_auto_events,
            "auto_target": auto_target,
            "volume_start_event_count": int(state.get("global_settled_event_count", 0) or 0),
        },
        goto="event_chain_gen",
    )
