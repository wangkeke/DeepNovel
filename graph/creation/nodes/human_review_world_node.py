"""
human_review_world_node：世界设定确认节点

用户确认或修改模型生成的世界设定草稿。
确认后将设定卡存入 novel_projects 表，全书锁定不再变动。
"""
from __future__ import annotations
import json
import aiosqlite
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from config import DB_PATH
from utils.v42_flow import shallow_world_archive
import logging

logger = logging.getLogger(__name__)



async def _save_world_setting_to_db(project_id: str, world_setting: dict) -> None:
    """将确认后的世界设定卡写入 novel_projects 表。"""
    if not project_id:
        return
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            await conn.execute(
                """UPDATE novel_projects
                   SET world_setting_json = ?, updated_at = datetime('now')
                   WHERE project_id = ?""",
                (json.dumps(world_setting, ensure_ascii=False), project_id),
            )
            await conn.commit()
    except Exception as e:
        logger.warning(f"保存世界设定卡失败: {e}")


async def human_review_world_node(state: CreationState) -> Command:
    world_setting = state.get("world_setting", {})
    project_id    = state.get("project_id", "")

    user_input = interrupt({
        "type": "world_review",
        "content": {
            "world_setting": world_setting,
        },
    })

    action   = user_input.get("action", "approve")
    feedback = user_input.get("feedback", "").strip()

    if action == "approve":
        # 写入 DB
        await _save_world_setting_to_db(project_id, world_setting)
        ws = world_setting if isinstance(world_setting, dict) else {}
        ne = str(ws.get("narrative_era") or "").strip()
        return Command(
            update={
                "world_setting_confirmed": True,
                "world_archive": shallow_world_archive(ws),
                "narrative_era": ne or (state.get("narrative_era") or ""),
            },
            goto="protagonist_card",
        )
    else:
        # 大改时代/脑洞根：回到脑洞引擎重炼（意见写入 brainwave_regen_feedback）
        return Command(
            update={
                "world_setting_confirmed": False,
                "world_setting_feedback": "",
                "world_setting": {},
                "brainwave_regen_feedback": feedback,
                "brainwave_approved": False,
            },
            goto="idea_forge",
        )
