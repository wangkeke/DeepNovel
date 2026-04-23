"""protagonist_collision_node：三步命运编织引擎第二步（引力交汇）。"""
from __future__ import annotations

import json
import logging
from langgraph.types import Command, StreamWriter
from schemas.state import CreationState
from utils.llm import call_llm_json
from prompts.creation.protagonist_collision import (
    PROTAGONIST_COLLISION_SYSTEM,
    PROTAGONIST_COLLISION_USER_TEMPLATE,
    PROTAGONIST_COLLISION_RETRY_PREFIX,
)

logger = logging.getLogger("deepnovel.protagonist_collision")
MAX_RETRIES = 2


def _validate_collision(result: dict) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return False, "返回非 JSON 对象"
    if not result.get("gravity_check_passed", False):
        return False, "gravity_check_passed=false"
    if not result.get("protagonist_driven_by_need", False):
        return False, "protagonist_driven_by_need=false"
    if not (result.get("resource_focal_point") or "").strip():
        return False, "resource_focal_point 为空"
    if not (result.get("instinct_or_principle_violated") or "").strip():
        return False, "instinct_or_principle_violated 为空"
    return True, ""


async def protagonist_collision_node(state: CreationState, writer: StreamWriter) -> Command:
    writer({"node_status": "started", "node": "protagonist_collision"})

    current_idx = state.get("current_node_index", 0)
    story_path = state.get("story_path", [])

    existing = state.get("current_protagonist_collision") or {}
    if isinstance(existing, dict) and existing.get("node_index") == current_idx:
        return Command(goto="expand1")

    world_tick = state.get("current_world_tick") or {}
    if not isinstance(world_tick, dict) or world_tick.get("_fallback"):
        return Command(
            update={
                "current_protagonist_collision": {
                    "node_index": current_idx,
                    "_fallback": True,
                }
            },
            goto="expand1",
        )

    current_node = story_path[current_idx] if current_idx < len(story_path) else {}
    node_name = current_node.get("node_name") or f"第{current_idx + 1}章"
    tension_design = current_node.get("tension_design") or current_node.get("tension_type") or "（未提供）"

    retry_prefix = ""
    collision: dict = {}
    for attempt in range(MAX_RETRIES + 1):
        user_prompt = PROTAGONIST_COLLISION_USER_TEMPLATE.format(
            node_name=node_name,
            tension_design=tension_design,
            world_tick_json=json.dumps(world_tick, ensure_ascii=False, indent=2),
            node_index=current_idx,
        )
        if retry_prefix:
            user_prompt = retry_prefix + "\n\n" + user_prompt

        try:
            result = await call_llm_json(PROTAGONIST_COLLISION_SYSTEM, user_prompt)
            collision = result if isinstance(result, dict) else {}
        except Exception as exc:
            logger.warning(f"[protagonist_collision] 调用失败 attempt={attempt}: {exc}")
            if attempt >= MAX_RETRIES:
                collision = {"node_index": current_idx, "_fallback": True}
                break
            continue

        passed, reason = _validate_collision(collision)
        if passed:
            break
        if attempt < MAX_RETRIES:
            retry_prefix = PROTAGONIST_COLLISION_RETRY_PREFIX.format(failure_reason=reason)
        else:
            collision["_fallback"] = True

    collision["node_index"] = current_idx
    return Command(update={"current_protagonist_collision": collision}, goto="expand1")
