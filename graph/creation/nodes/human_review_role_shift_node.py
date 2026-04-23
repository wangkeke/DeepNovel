"""
human_review_role_shift_node：核心角色立场变化确认节点

当 bible_update_node 检测到核心配角触发立场变化特征时，
将变化信息存入 pending_role_shifts，本节点触发中断让用户确认。

三种决策：
  confirm      → 更新为对立，可填写 true_motive（伏笔来源）
  misunderstanding → 这是误会/隐情，保持当前立场不变
  gray_area    → 灰色地带（表面盟友/实为对立），写正文按表面立场，内部知晓真实立场

若 pending_role_shifts 为空，节点直接透传（无 interrupt）。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.entity_db import update_character_role
from config import DB_PATH
import aiosqlite
import json
import logging

logger = logging.getLogger(__name__)


async def _add_true_motive_foreshadow(
    project_id: str,
    char_name: str,
    true_motive: str,
    seq: int,
) -> None:
    """将 true_motive 注册为一条待回收伏笔（自动推送到伏笔地图）。"""
    if not true_motive or not project_id:
        return
    foreshadow_id = f"FM_{char_name[:4]}_{seq}"
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            # event_timeline 里插一条特殊的伏笔事件
            await conn.execute(
                """INSERT INTO event_timeline
                   (event_id, project_id, seq, description, characters,
                    locations, items, is_foreshadow, foreshadow_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    foreshadow_id,
                    project_id,
                    seq,
                    f"【隐藏伏笔】{char_name}的真实动机：{true_motive}",
                    json.dumps([char_name], ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    foreshadow_id,
                ),
            )
            await conn.commit()
    except Exception as e:
        logger.warning(f"注册 true_motive 伏笔失败 ({char_name}): {e}")


async def human_review_role_shift_node(state: CreationState) -> Command:
    pending = state.get("pending_role_shifts", [])

    if not pending:
        return Command(
            update={"pending_role_shifts": []},
            goto="update_weight",
        )

    project_id  = state.get("project_id", "")
    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    global_seq  = (
        story_path[current_idx - 1].get("_seq", current_idx)
        if 0 < current_idx <= len(story_path)
        else current_idx
    )

    user_input = interrupt({
        "type": "role_shift_review",
        "content": {
            "shifts": pending,
            "seq":    global_seq,
        },
    })

    responses: list[dict] = user_input.get("responses", [])

    for shift in pending:
        char_name = shift.get("character_name", "")
        seq       = shift.get("current_seq", global_seq)
        trigger   = shift.get("trigger_description", "")

        # 找到用户对该角色的回应
        resp = next(
            (r for r in responses if r.get("character_name") == char_name),
            {"decision": "misunderstanding"},  # 默认保持不变
        )
        decision    = resp.get("decision", "misunderstanding")
        true_motive = resp.get("true_motive", "").strip()
        surface_role= resp.get("surface_role", shift.get("current_role", "盟友"))

        if decision == "confirm":
            try:
                await update_character_role(
                    project_id         = project_id,
                    name               = char_name,
                    new_role           = "对立",
                    seq                = seq,
                    trigger_description= trigger,
                    true_motive        = true_motive,
                )
            except Exception as e:
                logger.warning(f"update_character_role 失败 ({char_name}): {e}")
            if true_motive:
                await _add_true_motive_foreshadow(project_id, char_name, true_motive, seq)

        elif decision == "gray_area":
            try:
                await update_character_role(
                    project_id         = project_id,
                    name               = char_name,
                    new_role           = "灰色地带",
                    seq                = seq,
                    trigger_description= trigger,
                    true_motive        = true_motive,
                    surface_role       = surface_role,
                )
            except Exception as e:
                logger.warning(f"update_character_role 灰色地带失败 ({char_name}): {e}")
            if true_motive:
                await _add_true_motive_foreshadow(project_id, char_name, true_motive, seq)

        # decision == "misunderstanding" → 不做任何更新

    return Command(
        update={"pending_role_shifts": []},
        goto="update_weight",
    )
