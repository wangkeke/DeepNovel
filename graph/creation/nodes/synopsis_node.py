"""
synopsis_node：宏观构思生成节点
生成宏观构思后，由图中紧接的 human_review_synopsis 节点通过 interrupt 等待用户确认。
synopsis_approved 初始设为 False，由 human_review_synopsis 的 Command 决定最终值。
"""
from __future__ import annotations
import json
from langgraph.types import StreamWriter
from schemas.state import CreationState
from prompts.creation.synopsis import (
    SYNOPSIS_SYSTEM,
    SYNOPSIS_USER_TEMPLATE,
    PLATFORM_MACRO_HINTS,
)
from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING
from utils.llm import call_llm_json
from config import get_weight_description


async def synopsis_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "synopsis"})
    genre_request = state.get("genre_request", "")
    blueprint     = state.get("blueprint", {})
    weight        = state.get("blueprint_weight", 0.5)
    free_creation = state.get("free_creation", False)

    weight_description = (
        "自由创作，不参考骨骼，完全根据题材自行发挥"
        if free_creation else get_weight_description(weight)
    )

    # 用户修改意见（由 human_review 回传后注入）
    prev_synopsis = state.get("synopsis", {})
    feedback = prev_synopsis.get("user_feedback", "")
    if feedback:
        feedback_section = USER_FEEDBACK_HANDLING.format(user_feedback=feedback) + "\n\n"
    else:
        feedback_section = ""

    platform_style = (state.get("platform_style") or "").strip() or "通用网文"
    platform_macro_hint = PLATFORM_MACRO_HINTS.get(
        platform_style, PLATFORM_MACRO_HINTS["通用网文"]
    )

    user_prompt = SYNOPSIS_USER_TEMPLATE.format(
        genre_request=genre_request,
        platform_macro_hint=platform_macro_hint,
        weight_description=weight_description,
        world_rule_type  = "" if free_creation else blueprint.get("world_rule_type", ""),
        conflict_scale   = "" if free_creation else blueprint.get("conflict_scale", ""),
        protagonist_power= "" if free_creation else blueprint.get("protagonist_power", ""),
        macro_pacing     = "" if free_creation else blueprint.get("layer1", {}).get("macro_pacing", ""),
        emotional_curve  = "" if free_creation else blueprint.get("layer2", {}).get("emotional_curve", ""),
        payoff_rhythm    = "" if free_creation else blueprint.get("layer2", {}).get("payoff_rhythm", ""),
        feedback_section=feedback_section,
    )

    result = await call_llm_json(SYNOPSIS_SYSTEM, user_prompt)

    # synopsis_approved 仅由 human_review_synopsis 的 Command 控制，此处不写
    return {"synopsis": result}
