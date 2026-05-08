"""
world_build_node：世界设定生成节点

触发时机：synopsis 确认后、第一次 path_gen 之前。
职责：根据已确认的 synopsis 自动生成世界设定卡草稿，
      交由 human_review_world_node 让用户确认。

世界设定卡是全书"宪法"——一旦确认，全书不再变动。
"""
from __future__ import annotations
import json
from langgraph.types import StreamWriter
from schemas.state import CreationState
from prompts.creation.world_build import (
    WORLD_BUILD_SYSTEM,
    WORLD_BUILD_USER_TEMPLATE,
    WORLD_BUILD_REVISE_USER_TEMPLATE,
)
from prompts.creation.synopsis import PLATFORM_MACRO_HINTS
from prompts.common.era_lexicon_filter import (
    era_lexicon_system_suffix,
    resolve_narrative_era_for_filter,
)
from utils.llm import call_llm_json
from utils.v42_flow import stub_synopsis_for_world_build, shallow_world_archive
from utils.brainwave_engine import world_build_brainwave_suffix


def _narrative_era_section_for_prompt(state: CreationState) -> str:
    hint = resolve_narrative_era_for_filter(state)
    if hint:
        return (
            "## 叙事时代与语体锚点（全书须遵守；须写入返回 JSON 的 narrative_era 字段，可与 basic_rules 呼应但不得矛盾）\n"
            f"{hint}\n"
        )
    return (
        "## 叙事时代与语体锚点（用户未预填：请依据题材与宏观构思显式给出 narrative_era）\n"
        "须写清：时代类别 + 科技/行政/学术/文化认知边界（抽象即可）；须与 System 文末「时代语料隔离法则」可互证。\n"
    )


async def world_build_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "world_build"})

    if state.get("skip_world_build_regen"):
        ws = state.get("world_setting") or {}
        if isinstance(ws, dict) and (
            (ws.get("basic_rules") or "").strip()
            or (ws.get("power_structure") or [])
        ):
            ne_skip = str(ws.get("narrative_era") or "").strip() or (state.get("narrative_era") or "")
            return {
                "world_setting": ws,
                "world_archive": shallow_world_archive(ws),
                "world_setting_confirmed": False,
                "world_setting_feedback": "",
                "skip_world_build_regen": False,
                "narrative_era": ne_skip,
            }

    synopsis = stub_synopsis_for_world_build(state)
    feedback = state.get("world_setting_feedback", "")
    current_world_setting = state.get("world_setting", {})

    synopsis_text = json.dumps(synopsis, ensure_ascii=False, indent=2)
    genre_request = (state.get("genre_request") or "").strip() or "通用网文"
    platform_style = (state.get("platform_style") or "").strip() or "通用网文"
    platform_macro_hint = PLATFORM_MACRO_HINTS.get(
        platform_style, PLATFORM_MACRO_HINTS["通用网文"]
    )

    snap = state.get("iceberg_world_snapshot") or {}
    if not isinstance(snap, dict):
        snap = {}
    if snap.get("basic_rules") or snap.get("power_structure") or snap.get("unique_settings"):
        iceberg_world_baseline = json.dumps(snap, ensure_ascii=False, indent=2)
    else:
        iceberg_world_baseline = "（无冰山阶段快照；请仅从宏观构思推导。）"

    narrative_era_section = _narrative_era_section_for_prompt(state)

    if feedback and current_world_setting:
        # 有修改意见：基于现有草稿修改
        user_prompt = WORLD_BUILD_REVISE_USER_TEMPLATE.format(
            genre_request=genre_request,
            platform_macro_hint=platform_macro_hint,
            narrative_era_section=narrative_era_section,
            synopsis_text=synopsis_text,
            iceberg_world_baseline=iceberg_world_baseline,
            current_world_setting=json.dumps(
                current_world_setting, ensure_ascii=False, indent=2
            ),
            feedback=feedback,
        )
    else:
        # 首次生成
        user_prompt = WORLD_BUILD_USER_TEMPLATE.format(
            genre_request=genre_request,
            platform_macro_hint=platform_macro_hint,
            synopsis_text=synopsis_text,
            iceberg_world_baseline=iceberg_world_baseline,
            narrative_era_section=narrative_era_section,
        )

    user_prompt = user_prompt + world_build_brainwave_suffix(state)

    world_build_system = WORLD_BUILD_SYSTEM + "\n\n" + era_lexicon_system_suffix(state)
    result = await call_llm_json(world_build_system, user_prompt)
    if not isinstance(result, dict):
        result = {}

    hint_ne = resolve_narrative_era_for_filter(state)
    ne_llm = str(result.get("narrative_era") or "").strip()
    narrative_era_state = ne_llm or hint_ne
    if narrative_era_state and not ne_llm:
        result = dict(result)
        result["narrative_era"] = narrative_era_state

    return {
        "synopsis":                synopsis,
        "world_setting":           result,
        "world_archive":           shallow_world_archive(result),
        "world_setting_confirmed": False,
        "world_setting_feedback":  "",   # 清除修改意见，防止下次循环重复使用
        "narrative_era":           narrative_era_state,
    }
