"""
tension_check_node：逻辑与张力综合质检（宽松标准）

原则：
  - 拦截明显逻辑/题材硬伤，不挑剔文笔
  - 人物关系数值不得否决合理情节；有胁迫/利益解释的高信任背叛算优秀张力
  - 最多重试 2 次（失败两次后第三次强制通过）

位置：write → tension_check → human_review_write / auto_review / write（返工）
"""
from __future__ import annotations
import json
import logging
from langgraph.types import Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.chapter_excerpt import excerpt_head_tail
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

logger = logging.getLogger("deepnovel.tension_check")

MAX_TENSION_RETRY = 16  # 失败累计达到此次数后强制通过


def _expand1_design_for_qc(expand1: dict) -> str:
    """
    旧版 expand1：tension_analysis 对象 JSON。
    v4.3 expand1_v43：用 path_id、叙事功能、因果、动机语境等拼成可质检文本块。
    """
    if not isinstance(expand1, dict) or not expand1:
        return "（本节无 expand1 设计快照。）"
    ta = expand1.get("tension_analysis")
    if isinstance(ta, dict) and ta:
        try:
            return json.dumps(ta, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return str(ta)
    if any(expand1.get(k) for k in ("function_confirmed", "chapter_driver", "path_id")):
        parts: list[str] = []
        for k, lab in (
            ("path_id", "path_id"),
            ("chapter_tone", "情绪基调"),
            ("function_confirmed", "叙事功能落地"),
            ("chapter_driver", "本章叙事驱动力"),
            ("causal_input", "因果承接（输入）"),
            ("causal_output_direction", "因果传递（输出）"),
        ):
            v = expand1.get(k)
            if v:
                parts.append(f"【{lab}】{v}")
        ksf = expand1.get("key_state_factors")
        if isinstance(ksf, list) and ksf:
            parts.append("【关键状态】 " + "；".join(str(x) for x in ksf[:10]))
        for k, lab in (("state_audit_note", "状态确认"), ("function_alignment_note", "功能对齐")):
            v = expand1.get(k)
            if v:
                parts.append(f"【{lab}】{v}")
        qc = expand1.get("quest_context")
        if isinstance(qc, dict):
            pd = (qc.get("primary_driver") or "").strip()
            eu = (qc.get("emotional_undercurrent") or "").strip()
            if pd or eu:
                parts.append(f"【动机语境】primary_driver: {pd}\nemotional_undercurrent: {eu}")
        if parts:
            return "\n".join(parts)
    return "（本节无旧版 tension_analysis，亦无 v4.3 落地字段；请依大纲与正文做逻辑与题材质检。）"


async def tension_check_node(state: CreationState) -> Command:
    draft = state.get("current_draft", "")
    expand1_full = state.get("current_expand1", {})
    if not isinstance(expand1_full, dict):
        expand1_full = {}
    expand1_design = _expand1_design_for_qc(expand1_full)
    tension_retry = state.get("tension_retry_count", 0)
    node_index = state.get("current_node_index", 0)
    story_path = state.get("story_path", [])
    synopsis = state.get("synopsis") or {}
    node_name = (
        story_path[node_index].get("node_name", "")
        if node_index < len(story_path)
        else ""
    )
    # v43 flow 回落：story_path 为空或 node_name 未填时，从多处取名
    if not node_name:
        expand1 = state.get("current_expand1") or {}
        current_event = state.get("current_event") or {}
        event_paths = state.get("current_event_paths") or {}
        path_progress = state.get("path_progress") or {}
        remaining = path_progress.get("remaining_paths") or []
        current_path_id = remaining[0] if remaining else ""
        # 从 current_event_paths.paths 找当前路径名
        path_name = ""
        for p in (event_paths.get("paths") or []):
            if isinstance(p, dict) and p.get("path_id") == current_path_id:
                path_name = p.get("path_name") or p.get("path_id", "")
                break
        node_name = (
            path_name
            or current_event.get("event_name")
            or expand1.get("path_id")
            or ""
        )

    if tension_retry >= MAX_TENSION_RETRY:
        next_node = _get_next_node(state)
        logger.info(f"[质检] 「{node_name}」已重试{tension_retry}次，强制通过")
        return Command(
            update={"tension_retry_count": 0, "tension_minor_issues": [], "_tension_goto": next_node},
            goto=next_node,
        )

    if not (draft or "").strip():
        next_node = _get_next_node(state)
        return Command(
            update={"tension_retry_count": 0, "tension_minor_issues": [], "_tension_goto": next_node},
            goto=next_node,
        )

    result = await _check_tension_and_logic(draft, expand1_design, node_name, synopsis)

    if result.get("passed", True):
        minor_issues = result.get("issues", []) if result.get("severity") == "minor" else []
        next_node = _get_next_node(state)
        logger.info(f"[质检] 「{node_name}」通过")
        return Command(
            update={
                "tension_retry_count": 0,
                "tension_minor_issues": minor_issues,
                "_tension_goto": next_node,
            },
            goto=next_node,
        )

    issues = result.get("issues", [])
    issue_text = "；".join(str(x) for x in issues) if isinstance(issues, list) else str(issues)
    logger.info(f"[质检] 「{node_name}」不通过：{issue_text}")

    return Command(
        update={
            "tension_retry_count": tension_retry + 1,
            "bible": {
                **state.get("bible", {}),
                "rewrite_feedback": _build_rewrite_instruction(issues, expand1_full, synopsis),
            },
            "_tension_goto": "write",
        },
        goto="write",
    )


def _get_next_node(state: CreationState) -> str:
    if state.get("auto_mode"):
        return "auto_review"
    return "human_review_write"


async def _check_tension_and_logic(
    draft: str,
    expand1_design: str,
    node_name: str,
    synopsis: dict,
) -> dict:
    """轻量 LLM：题材/大纲、基础逻辑、变量自洽（宽松）、核心张力载体。"""
    ta_block = (expand1_design or "").strip() or (
        "（本节无 expand1 设计快照；请依据大纲与正文做逻辑与题材校验。）"
    )

    core_conflict = ""
    direction = ""
    if isinstance(synopsis, dict):
        core_conflict = str(synopsis.get("core_conflict", "") or "")
        direction = str(synopsis.get("direction", "") or "")

    draft_for_qc = excerpt_head_tail(
        draft,
        head_chars=3000,
        tail_chars=3500,
    )

    result = await call_llm_json(
        system=DEEPNOVEL_CONSTITUTION + "\n\n" + """
你是一个宽容的网文内容质检编辑。你的任务是拦截“明显的逻辑硬伤”，而不是挑剔文笔细节。
只要正文在逻辑上能够自圆其说（即使有些牵强），就给 passed=true。
只有出现以下【严重违规】时，才返回 passed=false：

【严重违规清单】：
1. 题材/大纲偏离：正文出现了完全不符合该题材与世界观设定的东西（如宫斗背景里无铺垫地出现违背时代的超自然打击作为实写等——须有上下文铺垫或明确另类设定）。
2. 基础逻辑崩坏：死人复活无解释、明显的时间/空间悖论、前后硬性事实矛盾且无叙事意图（如刻意误导）等。
3. 变量崩坏（无动机的精分）：人物行为与他们当前的【情感度/针对度】极度不符，且【没有任何外部压力、利益诱惑、胁迫、信息差或路径要求】来解释这种反常。
   （注：高情感度角色在常态下应表现出支持、信任与亲密距离；若遭遇极端外部压力——如重大利益冲突、生死威胁、亲人被要挟等，角色基于自身人性逻辑，无论是选择拼死坚守忠诚与牺牲，还是选择被迫背叛与妥协，只要因果与动机铺垫在正文可感知，均属逻辑自洽，必须 passed=true。切勿死板要求人物做道德完人，也勿将「背叛」或「忠诚」任一方向预设为更优结局。）
4. 核心张力缺失：本章路径或张力设计中有明确的推波助澜者/代价/反转轴，但正文**完全没有**对应的具体动作、对话或细节载体（仅有抽象概括不算）。

只返回 JSON，不加任何前言。
""",
        user=f"""
## 宏观大纲约束
核心冲突：{core_conflict}
走向：{direction}

## 本节节点
{node_name or "（未命名）"}

## 本节张力与情节设计（expand1）
{ta_block}

## 正文草稿（用于质检；短章全文，长章含开篇铺垫 + 章末收束段，禁止只读半截就判定「张力未落地」）
{draft_for_qc}

## 检查任务
请根据上述【宽松标准】和【严重违规清单】对正文进行校验。

返回 JSON：
{{
  "passed": true,
  "issues": [],
  "severity": "minor"
}}

说明：issues 在 passed=false 时列出简短原因（对应哪一条违规）；severity 取 minor | major。
再次强调：仅有 severity=major 时才允许 passed=false。
""",
    )

    if not isinstance(result, dict):
        result = {"passed": True, "issues": [], "severity": "minor"}

    if result.get("severity") != "major":
        result["passed"] = True

    return result


def _build_rewrite_instruction(
    issues: list,
    expand1: dict,
    synopsis: dict,
) -> str:
    lines = ["【逻辑与张力质检：请针对性修改以下内容后重写本章】\n"]

    if isinstance(issues, list):
        for issue in issues:
            lines.append(f"• {issue}")
    elif issues:
        lines.append(f"• {issues}")

    cc = ""
    if isinstance(synopsis, dict):
        cc = str(synopsis.get("core_conflict", "") or "").strip()
    if cc:
        lines.append(f"\n大纲核心冲突（勿偏题）：{cc[:400]}")

    expand2_design = ""
    if isinstance(expand1, dict):
        ta = expand1.get("tension_analysis")
        if isinstance(ta, dict):
            expand2_design = str(ta.get("tension_execution", "") or "").strip()
        if not expand2_design:
            expand2_design = str(expand1.get("function_alignment_note") or "").strip() or str(
                expand1.get("function_confirmed", "") or ""
            ).strip()
    if expand2_design:
        lines.append(f"\n参考本章设计意图（勿偏题）：\n{expand2_design[:800]}")

    lines.append(
        "\n注意：优先修正质检指出的硬伤；人物走向须与其人性逻辑及事件链压力相称，"
        "缺动机、缺铺垫的突然倒戈或突然无脑效忠才需重写；勿用初始关系数值代替因果判断。"
    )
    return "\n".join(lines)
