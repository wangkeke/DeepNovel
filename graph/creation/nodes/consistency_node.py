"""
consistency_node：正文一致性检查节点

检查当前章节草稿是否符合故事圣经和骨骼结构，
超过最大重写次数时强制通过，防止死循环。
"""
from __future__ import annotations
import json
from schemas.state import CreationState
from prompts.creation.consistency import CONSISTENCY_SYSTEM, CONSISTENCY_USER_TEMPLATE
from utils.llm import call_llm_json
from utils.display import node_warn

MAX_REWRITES = 2


async def consistency_node(state: CreationState) -> dict:
    draft = state.get("current_draft", "")
    bible = state.get("bible", {})

    current_idx = state.get("current_node_index", 0)
    story_path = state.get("story_path", [])
    current_node = story_path[current_idx] if current_idx < len(story_path) else {}

    blueprint_weight = state.get("blueprint_weight", 0.5)

    pivot_str = ""
    if state.get("post_pivot", False):
        pivot_str = json.dumps(state.get("pivot_records", []), ensure_ascii=False)

    free_creation = state.get("free_creation", False)

    user_prompt = CONSISTENCY_USER_TEMPLATE.format(
        current_draft=draft,
        bible_summary=json.dumps(bible, ensure_ascii=False, indent=2),
        # 自由创作时不检查骨骼链类型，传空字符串让 LLM 只校验故事圣经一致性
        expected_pressure_type   = "" if free_creation else current_node.get("pressure_chain_type", ""),
        expected_resolution_type = "" if free_creation else current_node.get("resolution_chain_type", ""),
        blueprint_weight = "0.0" if free_creation else str(blueprint_weight),
        weight_description = "自由创作模式，只需检查与故事圣经的一致性，不检查骨骼结构" if free_creation else "权重越高说明越需要严格遵循",
        pivot_records_if_any=pivot_str,
    )

    result = await call_llm_json(CONSISTENCY_SYSTEM, user_prompt)

    passed = result.get("passed", True)
    is_pivot = result.get("is_pivot", False)
    violations = result.get("violations", [])

    rewrite_count = state.get("rewrite_count", 0)

    # 超过最大重写次数时强制通过，防止死循环
    if not passed and not is_pivot:
        if rewrite_count >= MAX_REWRITES:
            node_warn(
                f"一致性检查连续失败 {rewrite_count + 1} 次，强制通过。"
                f"违规：{'; '.join(violations)}"
            )
            passed = True

    output: dict = {
        "consistency_result": result,
        "has_violation": not passed and not is_pivot,
        "post_pivot": is_pivot or state.get("post_pivot", False),
        "rewrite_count": rewrite_count + 1 if (not passed and not is_pivot) else 0,
    }

    if is_pivot:
        output["pivot_records"] = [
            {"node": current_idx, "reason": result.get("pivot_reason")}
        ]

    return output
