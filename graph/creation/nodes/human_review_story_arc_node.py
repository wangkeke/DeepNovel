"""
human_review_story_arc_node：确认全书分卷规划（仅 interrupt，无 LLM）

与 story_arc_plan_node 拆分，避免 resume 时重复跑逐卷生成。
"""
from __future__ import annotations
import uuid as _uuid
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.db import save_framework_to_project


def _build_arc_level_quests(volumes: list, existing_stack: list) -> list:
    """
    从分卷规划的 milestone_conditions 生成 arc_level 层任务，推入任务栈。
    每个里程碑对应主角在该卷需趋近的状态目标（无序，非流水账顺序）。
    """
    if not isinstance(volumes, list):
        return existing_stack

    # 清除旧的 arc_level 任务（重新规划时覆盖）
    updated = [q for q in existing_stack if not (isinstance(q, dict) and q.get("layer") == "arc_level")]

    for vol_idx, vol in enumerate(volumes):
        if not isinstance(vol, dict):
            continue
        vol_name = str(vol.get("volume_name") or f"第{vol_idx + 1}卷").strip()
        mlist = vol.get("milestone_conditions")
        if not isinstance(mlist, list):
            mlist = []
        for m in mlist:
            if not isinstance(m, dict):
                continue
            mid = str(m.get("milestone_id") or "?").strip()
            label = str(m.get("name") or "").strip()
            trig = str(m.get("trigger_state") or "").strip()
            if not (label or trig):
                continue
            quest_id = f"AQ_ARC_{vol_idx + 1}_{mid}_{_uuid.uuid4().hex[:4].upper()}"
            updated.append({
                "quest_id": quest_id,
                "quest_name": f"{vol_name}·{label}" if label else f"{vol_name}·{mid}",
                "quest_origin": f"story_arc_plan·milestone（{vol_name}，{mid}）",
                "urgency_level": "medium",
                "deadline_note": None,
                "current_sub_goal": trig[:200],
                "layer": "arc_level",
                "completion_condition": trig[:220] if trig else label[:200],
                "failure_condition": None,
                "evolution_on_completion": None,
                "evolution_on_failure": None,
                "status": "active",
                "planted_chapter": f"story_arc_vol{vol_idx + 1}",
                "emotional_weight": f"{vol_name}的里程碑条件（沙盒引力场，非固定顺序）。",
                "_volume_index": vol_idx,
                "_milestone_id": mid,
            })

    return updated


async def human_review_story_arc_node(state: CreationState) -> Command:
    volumes = list(state.get("story_arc_volumes_draft") or [])
    if not volumes:
        return Command(goto="story_arc_plan")

    project_id = state.get("project_id", "")
    synopsis = state.get("synopsis", {}) or {}

    user_input = interrupt({
        "type": "story_arc_review",
        "content": volumes,
        "prompt": "请确认全书分卷规划（可调整每卷章节数）",
    })
    action = user_input.get("action", "approve")
    if action == "regenerate":
        fb = user_input.get("feedback", "")
        if not isinstance(fb, str):
            fb = ""
        return Command(
            update={
                "story_arc_volumes_draft": [],
                "story_arc_regen_feedback": fb.strip(),
            },
            goto="story_arc_plan",
        )

    edits = user_input.get("edits") or {}
    if isinstance(edits, dict) and "chapter_adjustments" in edits:
        for vol_idx, new_te in edits["chapter_adjustments"].items():
            try:
                idx = int(vol_idx)
                if 0 <= idx < len(volumes):
                    volumes[idx]["target_events"] = max(
                        20, min(int(new_te), 120)
                    )
            except (TypeError, ValueError):
                pass

    if project_id:
        await save_framework_to_project(
            project_id=project_id,
            synopsis=synopsis,
            world_setting=state.get("world_setting", {}) or {},
            volumes=volumes,
            write_rules=state.get("user_write_rules", "") or "",
            blueprint_id=state.get("blueprint_id", "") or "",
            genre_request=state.get("genre_request", "") or "",
            platform_style=state.get("platform_style", "通用网文") or "通用网文",
            protagonist_name=state.get("protagonist_name", "") or "",
        )

    existing_stack = list(state.get("active_quest_stack") or [])
    updated_stack = _build_arc_level_quests(volumes, existing_stack)

    return Command(
        update={
            "volumes": volumes,
            "story_arc_volumes_draft": [],
            "story_arc_regen_feedback": "",
            "current_volume_index": state.get("current_volume_index", 0) or 0,
            "active_quest_stack": updated_stack,
        },
        goto="mode_select",
    )
