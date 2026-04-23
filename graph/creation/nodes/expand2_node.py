"""
expand2_node：场景设计节点
根据 3W1H 分析结果设计具体场景序列，并规划伏笔的植入和回收。

伏笔管理逻辑：
  - 从故事圣经（bible）中读取已植入但未回收的伏笔，判断当前节点是否适合回收
  - 根据骨骼伏笔地图（layer3.foreshadow_map）判断当前节点是否需要植入新伏笔
"""
from __future__ import annotations
import json
from langgraph.types import StreamWriter
from schemas.state import CreationState
from prompts.creation.expand2 import EXPAND2_SYSTEM, EXPAND2_USER_TEMPLATE
from prompts.creation.platform_styles import (
    RULE_PRECEDENCE_NOTICE,
    POV_AND_CUTAWAY_RULES,
    DEEPNOVEL_LITERARY_CONSTITUTION,
    ADVANCED_LITERARY_RULES,
)
from utils.llm import call_llm_json
from utils.json_cot import flatten_cot_output
from config import get_weight_description
from memory.db import get_framework_foreshadow_seeds


def _build_foreshadow_tasks(state: CreationState) -> tuple[str, str]:
    """
    分析当前节点的伏笔任务，返回 (要植入的伏笔描述, 要回收的伏笔描述)

    植入逻辑：对照骨骼伏笔地图（layer3.foreshadow_map），
              找到 planted_at_node == current_node_index 的条目
    回收逻辑：从故事圣经中找出已植入但未回收的伏笔，
              检查 collected_at_node 是否 == current_node_index
    """
    current_idx = state.get("current_node_index", 0)
    blueprint = state.get("blueprint", {})
    bible = state.get("bible", {})

    # ── 植入任务：从骨骼伏笔地图查找当前节点需要植入的伏笔 ──
    foreshadow_map = blueprint.get("layer3", {}).get("foreshadow_map", [])
    to_plant = [
        f for f in foreshadow_map
        if f.get("planted_at_node") == current_idx
    ]

    if to_plant:
        plant_lines = []
        for f in to_plant:
            plant_lines.append(
                f"• [{f.get('foreshadow_id', '?')}] "
                f"表面含义：{f.get('surface_meaning', '')} / "
                f"真实含义：{f.get('true_meaning', '')} / "
                f"误导方向：{f.get('misdirect_direction', '')}"
            )
        foreshadows_to_plant = "\n".join(plant_lines)
    else:
        foreshadows_to_plant = "本节点无需植入伏笔"

    # ── 回收任务：从骨骼伏笔地图查找当前节点需要回收的伏笔 ──
    to_collect_from_map = [
        f for f in foreshadow_map
        if f.get("collected_at_node") == current_idx
    ]

    # 同时从故事圣经中找已植入但未标记回收的伏笔
    bible_planted = bible.get("planted_foreshadows", [])
    bible_collected_ids = set(bible.get("collected_foreshadows", []))
    overdue = [
        f for f in bible_planted
        if f.get("foreshadow_id") not in bible_collected_ids
        and f.get("planned_collection_node", 999) <= current_idx
    ]

    to_collect = to_collect_from_map + overdue
    # 去重
    seen_ids: set[str] = set()
    to_collect_unique = []
    for f in to_collect:
        fid = f.get("foreshadow_id", "")
        if fid not in seen_ids:
            seen_ids.add(fid)
            to_collect_unique.append(f)

    if to_collect_unique:
        collect_lines = []
        for f in to_collect_unique:
            collect_lines.append(
                f"• [{f.get('foreshadow_id', '?')}] "
                f"原植入表达：{f.get('surface_expression', f.get('surface_meaning', ''))} / "
                f"真实含义：{f.get('true_meaning', '')} / "
                f"计划回收节点：{f.get('planned_collection_node', f.get('collected_at_node', ''))}"
            )
        foreshadows_to_collect = "\n".join(collect_lines)
    else:
        foreshadows_to_collect = "本节点无需回收伏笔"

    return foreshadows_to_plant, foreshadows_to_collect


def _format_world_setting_section(world_setting: dict) -> str:
    """将世界设定卡格式化为 prompt 前缀段落（静态背景宪法）。"""
    if not world_setting:
        return ""
    lines = ["## 世界设定（全书宪法，场景设计必须遵守）\n"]
    if br := world_setting.get("basic_rules"):
        lines.append(f"基础规则：{br}")
    for label, key in [("权力结构", "power_structure"), ("地理框架", "geography"),
                        ("世界禁忌", "world_taboos"), ("独特设定", "unique_settings")]:
        items = world_setting.get(key, [])
        if items:
            lines.append(f"{label}：" + "；".join(items))
    return "\n".join(lines) + "\n\n"


def _get_foreshadow_embedded_from_current_path(state: CreationState) -> str:
    """
    从 current_event_paths 中读取当前路径的 foreshadow_embedded，
    供 expand2 注入场景设计中。
    """
    event_paths = state.get("current_event_paths") or {}
    if not isinstance(event_paths, dict):
        return ""

    path_progress = state.get("path_progress") or {}
    remaining = path_progress.get("remaining_paths") or []

    if not remaining:
        return ""

    current_path_id = remaining[0]
    paths = event_paths.get("paths") or []

    current_path = None
    for path in paths:
        if isinstance(path, dict) and path.get("path_id") == current_path_id:
            current_path = path
            break

    if not current_path:
        return ""

    foreshadow = current_path.get("foreshadow_embedded") or {}
    if not isinstance(foreshadow, dict):
        return ""

    is_embedded = foreshadow.get("is_embedded", False)
    if not is_embedded:
        return ""

    ftype = foreshadow.get("foreshadow_type", "无")
    content = foreshadow.get("foreshadow_content", "")
    trigger = foreshadow.get("trigger_condition", "")
    is_new = foreshadow.get("is_new_foreshadow", False)

    if not content:
        return ""

    return (
        f"\n## 路径伏笔嵌入指令（path_gen 规划；场景设计须自然植入）\n"
        f"类型：{ftype}{'（新伏笔）' if is_new else ''}\n"
        f"伏笔内容：{content}\n"
        + (f"引爆条件：{trigger}\n" if trigger else "")
        + "注意：伏笔须以场景细节或人物行为自然呈现，禁止生硬点题。\n"
    )


def _build_v43_expand1_section(expand1: dict) -> str:
    """
    将 v4.3 格式的 expand1 输出格式化为 expand2 可读的章节规划摘要。
    兼容旧格式（3W1H CoT）和新格式（chapter_tone, chapter_driver 等）。
    """
    # 新格式：存在 chapter_tone 或 function_confirmed 字段
    chapter_tone = expand1.get("chapter_tone", "")
    function_confirmed = expand1.get("function_confirmed", "")
    chapter_driver = expand1.get("chapter_driver", "")
    key_state_factors = expand1.get("key_state_factors") or []
    causal_input = expand1.get("causal_input", "")
    causal_output_dir = expand1.get("causal_output_direction", "")
    hidden_seed = expand1.get("hidden_seed", "")

    if chapter_tone or function_confirmed or chapter_driver:
        lines = ["## 章节规划（expand1 v4.3 落地确认结果）\n"]
        if chapter_tone:
            lines.append(f"章节基调：{chapter_tone}")
        if function_confirmed:
            lines.append(f"叙事功能落地：{function_confirmed}")
        if chapter_driver:
            lines.append(f"章节驱动力：{chapter_driver}")
        if isinstance(key_state_factors, list) and key_state_factors:
            lines.append("关键档案状态：" + "；".join(str(x) for x in key_state_factors[:5]))
        if causal_input:
            lines.append(f"承接因果：{causal_input}")
        if causal_output_dir:
            lines.append(f"因果方向：{causal_output_dir}")
        if hidden_seed and hidden_seed != "无":
            lines.append(f"隐性种子：{hidden_seed}")
        return "\n".join(lines) + "\n\n"

    # 旧格式：3W1H CoT，直接序列化
    return ""


async def expand2_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "expand2"})
    expand1       = state.get("current_expand1", {})
    project_id    = state.get("project_id", "")
    blueprint     = state.get("blueprint", {})
    weight        = state.get("blueprint_weight", 0.5)
    free_creation = state.get("free_creation", False)
    world_setting = state.get("world_setting", {})

    # 读取用户对上一版正文文笔的修改意见（human_review_write 回传）
    current_idx  = state.get("current_node_index", 0)
    story_path   = state.get("story_path", [])
    prose_feedback = (
        story_path[current_idx].get("prose_feedback", "")
        if current_idx < len(story_path) else ""
    )
    prose_feedback_section = (
        f"## 用户对上一版正文文笔的修改意见\n\n{prose_feedback}\n\n"
        if prose_feedback else ""
    )

    # v4.3 路径伏笔嵌入（从 current_event_paths 当前路径定义读取）
    path_foreshadow_section = _get_foreshadow_embedded_from_current_path(state)

    # v4.3 新格式 expand1 摘要（若存在 chapter_tone 等新字段）
    v43_expand1_section = _build_v43_expand1_section(expand1)

    # 人物本节行为预测（expand1 旧格式输出），场景设计应围绕这些预测
    reaction_analysis = expand1.get("character_reaction_analysis", [])
    if reaction_analysis:
        lines = ["## 人物本节行为预测（场景设计必须围绕以下预测，选择能呈现这些反应的场景）\n"]
        for r in reaction_analysis:
            name = r.get("character_name", "?")
            ext = r.get("external_appearance", "")
            inner = r.get("internal_reality", "")
            detail = r.get("key_detail", "")
            lines.append(
                f"- {name}：外部表现={ext}，内部实际={inner}，关键细节={detail}"
            )
        character_reaction_section = "\n".join(lines) + "\n\n"
    else:
        character_reaction_section = v43_expand1_section

    weight_description = (
        "自由创作，不参考骨骼，完全根据故事圣经和场景逻辑设计场景"
        if free_creation else get_weight_description(weight)
    )

    if free_creation:
        foreshadows_to_plant   = "自由创作模式，无骨骼伏笔任务"
        foreshadows_to_collect = "自由创作模式，无骨骼伏笔任务"
    else:
        foreshadows_to_plant, foreshadows_to_collect = _build_foreshadow_tasks(state)

    # 框架种子伏笔（planted_at_node=0）：不进入 bible.planted_foreshadows，需单独注入
    framework_seeds_section = ""
    if project_id:
        seeds = await get_framework_foreshadow_seeds(project_id)
        if seeds:
            lines = [
                f"  • {s.get('surface_meaning', '')} — {s.get('story_potential', '')}"
                for s in seeds
            ]
            framework_seeds_section = (
                "\n\n框架预设伏笔（可考虑在本节自然提及，若场景合适则植入）：\n"
                + "\n".join(lines) + "\n"
            )

    user_prompt = EXPAND2_USER_TEMPLATE.format(
        world_setting_section=_format_world_setting_section(world_setting),
        expand1_result=json.dumps(expand1, ensure_ascii=False, indent=2),
        prose_feedback_section=prose_feedback_section,
        character_reaction_section=character_reaction_section,
        weight_description=weight_description,
        conflict_escalation = "" if free_creation else blueprint.get("layer2", {}).get("conflict_escalation", ""),
        turning_point_style = "" if free_creation else blueprint.get("layer2", {}).get("turning_point_style", ""),
        foreshadows_to_plant=foreshadows_to_plant,
        foreshadows_to_collect=foreshadows_to_collect,
        framework_seeds_section=framework_seeds_section,
    ) + path_foreshadow_section

    raw = await call_llm_json(
        RULE_PRECEDENCE_NOTICE.strip()
        + "\n\n"
        + EXPAND2_SYSTEM
        + f"\n\n{POV_AND_CUTAWAY_RULES}"
        + f"\n\n{DEEPNOVEL_LITERARY_CONSTITUTION}"
        + f"\n\n{ADVANCED_LITERARY_RULES}",
        user_prompt,
    )
    result = flatten_cot_output(raw if isinstance(raw, dict) else {})

    return {
        "current_expand2":           result,
        "pending_event_path_chain": result.get("event_path_chain", []),
        "chapter_approved":         False,
    }
