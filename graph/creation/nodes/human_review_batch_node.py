"""
human_review_batch_node：批次完成后的人工审核节点
整批节点全部写完后触发，用户可以：
  1. 继续规划下一批路径
  2. 开始揭露核心谜题（从持续引力中选择）
  3. 结束创作

框架导入模式：展示当前卷进度，批次完成后必要时更新卷状态。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.db import get_story_status, get_volumes, load_chapters_count, update_volume_progress
import logging

logger = logging.getLogger(__name__)


def _volume_target_events(vol: dict) -> int:
    if not isinstance(vol, dict):
        return 30
    try:
        te = int(vol.get("target_events", 0) or 0)
    except (TypeError, ValueError):
        te = 0
    if te > 0:
        return max(1, te)
    return 30


async def human_review_batch_node(state: CreationState) -> Command:
    story_path = state.get("story_path", [])
    project_id = state.get("project_id", "")
    batch_index = state.get("batch_index", 0)
    gsec = int(state.get("global_settled_event_count", 0) or 0)
    vsec = int(state.get("volume_start_event_count", 0) or 0)
    vol_events = max(0, gsec - vsec)

    batch_preview = "\n".join(
        f"  {i + 1}. {node.get('node_name', f'节点{i + 1}')}"
        for i, node in enumerate(story_path)
    )

    status = await get_story_status(project_id) if project_id else {"permanent": [], "backbone": [], "pending": []}

    volumes = await get_volumes(project_id) if project_id else []
    current_vol_index = state.get("current_volume_index", 0)
    if volumes and current_vol_index < len(volumes):
        current_vol = volumes[current_vol_index]
        from rich.console import Console
        con = Console()
        con.print(
            f"\n[dim]当前进度：第{current_vol_index + 1}卷 / 共{len(volumes)}卷 "
            f"「{current_vol.get('volume_name', '')}」 本卷已结算事件 {vol_events}[/dim]"
        )
        completed_count = await load_chapters_count(project_id)
        te = _volume_target_events(current_vol)
        if te and vol_events >= te:
            await update_volume_progress(
                project_id,
                current_vol_index,
                completed_count,
                is_completed=True,
            )
            con.print(
                f"[green]✓[/green]  第{current_vol_index + 1}卷"
                f"「{current_vol.get('volume_name', '')}」已达到本卷目标事件数"
            )

    user_input = interrupt({
        "type": "batch_review",
        "content": {
            "story_path":         story_path,
            "global_settled_event_count": gsec,
            "volume_event_count": vol_events,
            "batch_preview":      batch_preview,
            "project_id":         project_id,
            "story_status":       status,
        },
        "prompt": (
            f"本批次已完成 {len(story_path)} 个节点：\n"
            f"{batch_preview}"
        ),
    })

    action = user_input.get("action", "continue")

    if action == "continue":
        volumes = state.get("volumes") or []
        if project_id and not volumes:
            volumes = await get_volumes(project_id)
        chain = list(state.get("current_event_chain") or [])
        pos = int(state.get("current_event_chain_pos", 0) or 0)
        vol_idx = int(state.get("current_volume_index", 0) or 0)

        base_update = {
            "story_path":         [],
            "path_approved":      False,
            "current_node_index": 0,
            "creation_complete":  False,
            "batch_index":        batch_index + 1,
        }

        if chain and pos >= len(chain) and vol_idx + 1 < len(volumes):
            base_update["current_volume_index"] = vol_idx + 1
            base_update["current_event_chain"] = []
            base_update["current_event_chain_pos"] = 0
            base_update["last_event_batch_size"] = 0
            base_update["volume_start_event_count"] = int(
                state.get("global_settled_event_count", 0) or 0
            )
            return Command(update=base_update, goto="event_chain_gen")

        return Command(update=base_update, goto="path_gen")
    else:  # done
        return Command(
            update={"creation_complete": True},
            goto="__end__",
        )
