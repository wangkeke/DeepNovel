"""
auto_review_node：自动模式下替代所有人工确认节点。

替代范围：
  human_review_path   → review_type='path'
  human_review_expand → review_type='expand'
  human_review_write  → review_type='write'
  human_review_batch  → review_type='batch'

判断分级：
  直接通过（不调用 LLM）：
  - batch 类型且未达 max_auto_events（已结算事件）→ 直接继续下一批
  - batch 类型且达到 max_auto_events → 直接结束

  LLM 判断（方向性决策）：
    - path：路径是否符合 synopsis 的核心冲突和走向
    - write：先验骨再品味（逻辑完整性 + 题材质感/人味/余韵；见 prompts.creation.auto_review）

异常处理：
  LLM 判断不通过 → 自动生成修改意见继续推进
  连续2次不通过 → 通知用户介入，临时切回人工确认
"""
from __future__ import annotations
import json
import re
from langgraph.types import Command
from langgraph.graph import END
from schemas.state import CreationState
from utils.llm import call_llm_json
from prompts.creation.auto_review import (
    AUTO_REVIEW_WRITE_SYSTEM,
    AUTO_REVIEW_WRITE_USER_TEMPLATE,
)
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from memory.db import (
    get_entity_cards_by_names,
    load_chapters_count,
    get_project_max_auto_events,
    get_volumes,
)
from graph.creation.nodes.human_review_node import (
    _insert_story_nodes,
    _get_done_node_count,
    _save_volume_to_db,
)
import logging

logger = logging.getLogger("deepnovel.auto_review")

MAX_AUTO_RETRY = 2
MAX_TOTAL_RETRY = 5


def _expand1_retry_goto(state: CreationState) -> str:
    """v4.3 须回到 expand1_v43；旧流程回到 expand1。"""
    return "expand1_v43" if state.get("current_event_paths") else "expand1"


def _map_goto_expand1_for_v43(goto: str, state: CreationState) -> str:
    """_write_review_goto 等仍返回 'expand1' 时，映射为 expand1_v43。"""
    if goto == "expand1" and state.get("current_event_paths"):
        return "expand1_v43"
    return goto


def _v43_expand_review_user_prompt(
    state: CreationState,
    expand1: dict,
    synopsis: dict,
) -> str:
    """
    自动模式 expand 审核：对齐 expand1_v43 的 JSON 与 path_gen 当前路径，而非旧版 event_path_draft 列表。
    """
    event_paths = state.get("current_event_paths") or {}
    if not isinstance(event_paths, dict):
        event_paths = {}
    path_progress = state.get("path_progress") or {}
    remaining = path_progress.get("remaining_paths") or []
    eid = str(expand1.get("path_id") or "").strip()
    if not eid and remaining:
        eid = str(remaining[0] or "").strip()

    path_def_snippet = "（无 paths 或 path_id 未匹配）"
    for p in event_paths.get("paths") or []:
        if isinstance(p, dict) and p.get("path_id") == eid:
            try:
                path_def_snippet = json.dumps(p, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                path_def_snippet = str(p)
            if len(path_def_snippet) > 5000:
                path_def_snippet = path_def_snippet[: 5000 - 20] + "\n…（截断）"
            break

    event_name = str(event_paths.get("event_name", "") or "")
    node_label = eid or event_name or "（当前路径）"

    summary_keys = (
        "path_id", "chapter_tone", "function_confirmed", "chapter_driver",
        "key_state_factors", "causal_input", "causal_output_direction",
        "state_audit_note", "function_alignment_note", "hidden_seed", "quest_context",
    )
    ex_sum: dict = {}
    for k in summary_keys:
        if k in expand1 and expand1.get(k) not in (None, ""):
            ex_sum[k] = expand1.get(k)
    try:
        ex_blob = json.dumps(ex_sum, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        ex_blob = str(ex_sum)[:4000]
    if len(ex_blob) > 10000:
        ex_blob = ex_blob[: 10000 - 20] + "…（截断）"

    return f"""
## 整体故事方向
标题：{synopsis.get("title", "")}
核心冲突：{synopsis.get("core_conflict", "")}
走向：{synopsis.get("direction", "")}

## 当前事件与路径（v4.3）
事件名：{event_name}
待审落地对象：{node_label}

### 本路径在 path_gen 中的定义
{path_def_snippet}

### expand1_v43 落地确认单（待审核）
{ex_blob}

## 审核任务
1. 「落地确认单」与「路径定义」的叙事功能/场景核是否一致？有无与事件意图明显偏离？
2. causal_input / causal_output_direction 与大纲走向、上一章线头是否矛盾？
3. 若有 quest_context：规划层动机语境是否自洽（不要求在正文出现系统语）？

返回 JSON：
{{
  "decision": "approve" 或 "revise",
  "reason": "判断依据（一句话）",
  "revision_suggestion": "若 revise：具体修改建议（可指出应强化的设计维度）"
}}
"""


def _check_total_retry(state: CreationState, review_type: str, reason: str) -> Command | None:
    """全局安全阀：总重试次数超限则退回人工"""
    total = state.get("auto_total_retry_count", 0)
    if total >= MAX_TOTAL_RETRY:
        logger.warning(f"[自动] 章节总重试已达 {total} 次，退回人工确认")
        return _fallback_to_human(state, review_type, f"章节反复修改未通过（{reason}），需要人工介入")
    return None


async def auto_review_node(state: CreationState) -> Command:
    review_type = state.get("pending_review_type", "")
    retry_path = state.get("auto_retry_count_path", 0) or state.get("auto_retry_count", 0)
    retry_expand = state.get("auto_retry_count_expand", 0)
    retry_write = state.get("auto_retry_count_write", 0)

    if review_type == "path":
        return await _review_path(state, retry_path)
    elif review_type == "expand":
        return await _review_expand(state, retry_expand)
    elif review_type == "write":
        return await _review_write(state, retry_write)
    elif review_type == "batch":
        return await _review_batch(state)
    else:
        logger.warning(f"未知的 review_type: {review_type}，直接通过")
        return _direct_pass(state, review_type)


# ── 路径确认 ────────────────────────────────────────────────────────────────

async def _review_path(state: CreationState, retry_count: int) -> Command:
    """
    判断这批路径是否符合整体故事方向。
    数据来源：State（synopsis + story_path）
    """
    # v4.3：路径在 current_event_paths，不由 story_path 承载；与人工点「满意」一致直接通过。
    # 若仍走旧版 _format_path(story_path) 会得到 0 条，误判或浪费一次 LLM。
    if state.get("current_event_paths"):
        logger.info("[自动] v4.3 叙事路径已拆解，跳过旧版 story_path LLM 审核，进入路径落地")
        next_expand = _expand1_retry_goto(state)
        return Command(
            update={
                "path_approved": True,
                "pending_review_type": "",
                "auto_retry_count": 0,
                "auto_retry_count_path": 0,
                "auto_total_retry_count": 0,
                "_auto_review_goto": next_expand,
            },
            goto=next_expand,
        )

    synopsis = state.get("synopsis", {})
    story_path = state.get("story_path", [])

    result = await call_llm_json(
        system=DEEPNOVEL_CONSTITUTION + "\n\n" + """
你是一个有经验的网文编辑，正在审核一批故事节点路径。
判断这批路径是否符合整体故事方向，给出明确的决策。
只返回 JSON，不加任何前言。
""",
        user=f"""
## 整体故事方向
标题：{synopsis.get('title', '')}
核心冲突：{synopsis.get('core_conflict', '')}
走向：{synopsis.get('direction', '')}

## 待确认的路径（共 {len(story_path)} 个节点）
{_format_path(story_path)}

判断：
1. 这批节点的整体方向是否符合核心冲突和故事走向？
2. 节点之间是否有明显的逻辑断层？

返回 JSON：
{{
  "decision": "approve" 或 "revise",
  "reason": "判断依据（一句话）",
  "revision_suggestion": "如果 revise，具体修改建议"
}}
""",
    )

    if result.get("decision") == "approve":
        logger.info(f"[自动] 路径确认通过：{result.get('reason', '')}")
        # 与 human_review_path 一致：必须 INSERT story_nodes 并注入 _seq
        project_id = state.get("project_id", "")
        updated_path = story_path
        try:
            seq_offset = await _get_done_node_count(project_id)
            updated_path = await _insert_story_nodes(project_id, story_path, seq_offset)
            batch_index = state.get("batch_index", 0)
            volume_name = state.get("volume_name", "")
            volume_tagline = state.get("volume_tagline", "")
            await _save_volume_to_db(
                project_id=project_id,
                volume_index=batch_index + 1,
                volume_name=volume_name,
                volume_tagline=volume_tagline,
                start_seq=seq_offset + 1,
                end_seq=seq_offset + len(story_path),
            )
        except Exception:
            seq_offset = 0
        next_expand = _expand1_retry_goto(state)
        return Command(
            update={
                "path_approved": True,
                "current_node_index": 0,
                "story_path": updated_path,
                "auto_retry_count": 0,
                "auto_retry_count_path": 0,
                "auto_total_retry_count": 0,
                "pending_review_type": "",
                "_auto_review_goto": next_expand,
            },
            goto=next_expand,
        )
    else:
        logger.info(f"[自动] 路径需修改：{result.get('reason', '')}")
        reason = result.get("reason", "")

        if fallback := _check_total_retry(state, "path", reason):
            return fallback
        if retry_count >= MAX_AUTO_RETRY:
            logger.warning("[自动] 路径连续修改失败，切回人工确认")
            return _fallback_to_human(state, "path", reason)

        total = state.get("auto_total_retry_count", 0)
        return Command(
            update={
                "path_approved": False,
                "auto_retry_count": retry_count + 1,
                "auto_retry_count_path": retry_count + 1,
                "auto_total_retry_count": total + 1,
                "synopsis": {
                    **state.get("synopsis", {}),
                    "path_feedback": result.get("revision_suggestion", ""),
                },
                "_auto_review_goto": "path_gen",
            },
            goto="path_gen",
        )


# ── 事件路径方向确认 ────────────────────────────────────────────────────────

async def _review_expand(state: CreationState, retry_count: int) -> Command:
    """
    判断本章方向：旧版读 expand1_event_draft + how/what；v4.3 读 expand1_v43 与 current_event_paths。
    """
    synopsis = state.get("synopsis", {}) or {}
    story_path = state.get("story_path", [])
    current_idx = state.get("current_node_index", 0)
    expand1 = state.get("current_expand1", {})
    if not isinstance(expand1, dict):
        expand1 = {}

    is_v43 = bool(state.get("current_event_paths"))

    if is_v43:
        system_expand = DEEPNOVEL_CONSTITUTION + "\n\n" + """
你是一个有经验的网文编辑，正在审核 v4.3「路径落地确认单」（expand1_v43）。
对照 path_gen 给出的当前路径定义，判断落地规划是否与事件意图、因果线一致。
只返回 JSON，不加任何前言。
"""
        user_expand = _v43_expand_review_user_prompt(state, expand1, synopsis)
        node_name = str(expand1.get("path_id") or "（路径）")
    else:
        draft_chain = state.get("expand1_event_draft", [])
        node_name = (
            story_path[current_idx].get("node_name", f"第{current_idx + 1}章")
            if current_idx < len(story_path)
            else f"第{current_idx + 1}章"
        )
        one_liner = (
            story_path[current_idx].get("one_liner", "")
            if current_idx < len(story_path)
            else ""
        )
        how = expand1.get("how", {})
        what = expand1.get("what", {})
        system_expand = DEEPNOVEL_CONSTITUTION + "\n\n" + """
你是一个有经验的网文编辑，正在审核单章的事件路径草稿。
判断草稿事件链是否符合节点意图和故事走向，给出明确的决策。
只返回 JSON，不加任何前言。
"""
        user_expand = f"""
## 整体故事方向
标题：{synopsis.get('title', '')}
核心冲突：{synopsis.get('core_conflict', '')}
走向：{synopsis.get('direction', '')}

## 本节点（{node_name}）
一句话概括：{one_liner}
核心事件：{what.get('core_event', '')}
施压机制：{how.get('pressure_mechanism', '')}
破局触发：{how.get('resolution_trigger', '')}

## 待确认的事件路径草稿
{chr(10).join(f"{i+1}. {e}" for i, e in enumerate(draft_chain))}

判断：
1. 事件路径链是否与节点一句话概括和核心事件相符？
2. 施压→破局的逻辑是否合理？

返回 JSON：
{{
  "decision": "approve" 或 "revise",
  "reason": "判断依据（一句话）",
  "revision_suggestion": "如果 revise，具体修改建议"
}}
"""

    result = await call_llm_json(
        system=system_expand,
        user=user_expand,
    )

    if result.get("decision") == "approve":
        logger.info(f"[自动] 本章「{node_name}」方向确认通过")
        return Command(
            update={
                "expand1_approved": True,
                "auto_retry_count_expand": 0,
                "pending_review_type": "",
                "_auto_review_goto": "expand2",
            },
            goto="expand2",
        )
    else:
        logger.info(f"[自动] 本章「{node_name}」方向需修改：{result.get('reason', '')}")
        reason = result.get("reason", "")

        if fallback := _check_total_retry(state, "expand", reason):
            return fallback
        if retry_count >= MAX_AUTO_RETRY:
            logger.warning(f"[自动] 本章「{node_name}」连续修改失败，切回人工确认")
            return _fallback_to_human(state, "expand", reason)

        # 注入修改意见到 story_path 当前节点，回到 expand1
        updated_path = list(story_path)
        if current_idx < len(updated_path):
            updated_path[current_idx] = {
                **updated_path[current_idx],
                "chapter_feedback": result.get("revision_suggestion", ""),
            }
        bible_clear = {**state.get("bible", {}), "rewrite_feedback": "", "rewrite_feedback_parsed": {}}
        total = state.get("auto_total_retry_count", 0)
        next_expand = _expand1_retry_goto(state)

        return Command(
            update={
                "expand1_approved": False,
                "expand1_event_draft": [],
                "story_path": updated_path,
                "bible": bible_clear,
                "auto_retry_count_expand": retry_count + 1,
                "auto_total_retry_count": total + 1,
                "_auto_review_goto": next_expand,
            },
            goto=next_expand,
        )


# ── 章节确认 ────────────────────────────────────────────────────────────────

def _check_dialogue_ratio(draft: str) -> tuple[bool, str]:
    """
    检查对话占比是否达标。
    对话段落 = 包含引号「」""''的段落。
    返回 (是否达标, 提示信息)
    """
    paragraphs = [p.strip() for p in draft.split("\n") if p.strip()]
    if not paragraphs:
        return True, ""

    dialogue_markers = [
        "「", "」",
        "\u201c", "\u201d",
        "\u2018", "\u2019",
        '"', "'",
    ]
    dialogue_count = sum(
        1 for p in paragraphs
        if any(m in p for m in dialogue_markers)
    )

    ratio = dialogue_count / len(paragraphs)
    if ratio < 0.30:
        return False, f"对话占比仅 {ratio:.0%}，低于平台标准35%，建议补充对话"
    return True, ""


def _format_user_anchors_block(user_anchors: dict | None) -> str:
    if not user_anchors:
        return "无"
    try:
        return json.dumps(user_anchors, ensure_ascii=False, indent=2)
    except TypeError:
        return str(user_anchors)


def _draft_head_tail_for_review(
    draft: str, *, head: int = 800, tail: int = 400, threshold: int = 1200
) -> str:
    """供自动审读：长章给首尾，短章给全文。"""
    if not draft:
        return ""
    if len(draft) <= threshold:
        return draft
    return f"{draft[:head]}\n\n...（中间略）...\n\n{draft[-tail:]}"


def _write_review_goto(revision_focus: str, bone_issues: list[str]) -> str:
    """与历史逻辑一致：对话/呈现与味道→write；情节骨架类→expand1；其余→expand2。"""
    text = f"{revision_focus or ''} {' '.join(bone_issues or [])}"
    if "对话" in text:
        return "write"
    if any(
        k in text
        for k in (
            "人味",
            "质感",
            "腔调",
            "跑调",
            "偏机械",
            "说教",
            "内心",
            "旁白",
            "余韵",
            "震撼",
            "适应",
        )
    ):
        return "write"
    if any(
        k in text
        for k in ("情节", "人物", "行为", "锚点", "因果", "降神", "降智", "事件链", "铺垫", "伏笔")
    ):
        return "expand1"
    return "expand2"


async def _review_write(state: CreationState, retry_count: int) -> Command:
    """
    判断正文质量（自动模式）：先验骨、再品味（见 AUTO_REVIEW_WRITE_*）。
    数据来源：State（含 user_anchors）+ 数据库（entity_cards）
    """
    project_id = state.get("project_id", "")
    draft = state.get("current_draft", "")
    expand1 = state.get("current_expand1", {})
    synopsis = state.get("synopsis", {}) or {}
    node_index = state.get("current_node_index", 0)
    story_path = state.get("story_path", [])
    node_name = (
        story_path[node_index].get("node_name", "")
        if node_index < len(story_path)
        else ""
    )
    if not node_name.strip() and state.get("current_event_paths"):
        from utils.path_relay import v43_chapter_display_name

        node_name = v43_chapter_display_name(state)

    event_path_chain = expand1.get("event_path_chain", [])
    chain_lines = "\n".join(
        f"{i + 1}. {json.dumps(e, ensure_ascii=False) if isinstance(e, dict) else e}"
        for i, e in enumerate(event_path_chain)
    )
    draft_preview = _draft_head_tail_for_review(draft)

    # 前置规则检查：对话占比（对话不足只回退到 write，不重跑 expand1/expand2）
    dialogue_ok, dialogue_msg = _check_dialogue_ratio(draft)
    if not dialogue_ok:
        logger.info(f"[自动] 章节「{node_name}」对话占比不足：{dialogue_msg}")
        if fallback := _check_total_retry(state, "write", dialogue_msg):
            return fallback
        if retry_count >= MAX_AUTO_RETRY:
            logger.warning(f"[自动] 章节「{node_name}」连续修改失败，切回人工确认")
            return _fallback_to_human(state, "write", dialogue_msg)
        total = state.get("auto_total_retry_count", 0)
        return Command(
            update={
                "auto_retry_count_write": retry_count + 1,
                "auto_total_retry_count": total + 1,
                "bible": {
                    **state.get("bible", {}),
                    "rewrite_feedback": dialogue_msg,
                },
                "_auto_review_goto": "write",
            },
            goto="write",
        )

    involved_chars = _extract_character_names(draft, state)
    char_cards = await get_entity_cards_by_names(project_id, involved_chars)
    user_anchors_block = _format_user_anchors_block(state.get("user_anchors"))

    user_prompt = AUTO_REVIEW_WRITE_USER_TEMPLATE.format(
        direction=synopsis.get("direction", "") or "（未给出）",
        chain_lines=chain_lines or "（无单独事件链，请结合节点意图判断）",
        user_anchors_block=user_anchors_block,
        char_cards_block=_format_char_cards(char_cards),
        draft_preview=draft_preview or "（空稿）",
    )

    result = await call_llm_json(AUTO_REVIEW_WRITE_SYSTEM, user_prompt)
    if not isinstance(result, dict):
        logger.warning(
            "[自动] write 审核返回非 JSON 对象（%s），按不通过处理",
            type(result).__name__,
        )
        result = {}

    bone_check = result.get("bone_check") if isinstance(result.get("bone_check"), dict) else {}
    issues = bone_check.get("issues") if isinstance(bone_check.get("issues"), list) else []
    issues = [str(x) for x in issues if x]
    bone_passed = bone_check.get("passed", True)
    if issues:
        bone_passed = False

    verdict = (result.get("verdict") or "").strip().lower()
    if verdict not in ("approve", "revise"):
        verdict = "revise" if not bone_passed else "approve"

    if not bone_passed:
        verdict = "revise"

    revision_focus = (result.get("revision_focus") or "").strip()
    if verdict == "revise" and not revision_focus:
        if issues:
            revision_focus = f"骨架：{'；'.join(issues)}"
        else:
            vc = result.get("vibe_check") if isinstance(result.get("vibe_check"), dict) else {}
            revision_focus = (
                f"品味需收紧：{vc.get('genre_tone', '')}；{vc.get('human_warmth', '')}"
            ).strip("；")

    if verdict == "approve":
        vc = result.get("vibe_check") if isinstance(result.get("vibe_check"), dict) else {}
        reason_log = f"{vc.get('genre_tone', '')} / {vc.get('human_warmth', '')} / {vc.get('ending_resonance', '')}"
        logger.info(f"[自动] 章节「{node_name}」确认通过：{reason_log}")
        return Command(
            update={
                "auto_retry_count_write": 0,
                "auto_total_retry_count": 0,
                "pending_review_type": "",
                "_auto_review_goto": "narrative_extract",
            },
            goto="narrative_extract",
        )

    logger.info(f"[自动] 章节「{node_name}」需修改：{revision_focus}")

    reason = revision_focus or "审稿未通过"
    if fallback := _check_total_retry(state, "write", reason):
        return fallback
    if retry_count >= MAX_AUTO_RETRY:
        logger.warning(f"[自动] 章节「{node_name}」连续修改失败，切回人工确认")
        return _fallback_to_human(state, "write", reason)

    raw_goto = _write_review_goto(revision_focus, issues)
    goto = _map_goto_expand1_for_v43(raw_goto, state)
    total = state.get("auto_total_retry_count", 0)
    update_payload = {
        "auto_retry_count_write": retry_count + 1,
        "auto_total_retry_count": total + 1,
        "bible": {
            **state.get("bible", {}),
            "rewrite_feedback": revision_focus,
        },
    }
    if raw_goto == "expand1":
        updated_path = list(story_path)
        if node_index < len(updated_path):
            updated_path[node_index] = {
                **updated_path[node_index],
                "chapter_feedback": revision_focus,
            }
        update_payload["story_path"] = updated_path
        update_payload["expand1_approved"] = False
        update_payload["expand1_event_draft"] = []
    elif goto == "expand2":
        updated_path = list(story_path)
        if node_index < len(updated_path):
            updated_path[node_index] = {
                **updated_path[node_index],
                "prose_feedback": revision_focus,
            }
        update_payload["story_path"] = updated_path
        update_payload["bible"] = {**update_payload["bible"], "rewrite_feedback": revision_focus}

    update_payload["_auto_review_goto"] = goto
    return Command(update=update_payload, goto=goto)


# ── 批次确认 ────────────────────────────────────────────────────────────────

async def _review_batch(state: CreationState) -> Command:
    """
    批次完成后的自动决策。
    直接通过，不调用 LLM。
    停笔条件：已结算事件数 ≥ max_auto_events（state 或 DB novel_projects.max_chapters 列）。
    """
    project_id = state.get("project_id", "")
    cap = int(state.get("max_auto_events", 0) or 0) or await get_project_max_auto_events(
        project_id
    )
    gsec = int(state.get("global_settled_event_count", 0) or 0)

    if cap > 0 and gsec >= cap:
        logger.info(
            f"[自动] 已结算事件 {gsec} 个，达到上限 {cap}，结束创作"
        )
        return Command(
            update={"creation_complete": True, "pending_review_type": "", "_auto_review_goto": "__end__"},
            goto=END,
        )

    db_chapters = await load_chapters_count(project_id)
    logger.info(f"[自动] DB 正文片段 {db_chapters} 条，继续下一批")
    batch_index = state.get("batch_index", 0)
    volumes = state.get("volumes") or []
    if not volumes and project_id:
        volumes = await get_volumes(project_id)
    chain = list(state.get("current_event_chain") or [])
    pos = int(state.get("current_event_chain_pos", 0) or 0)
    vol_idx = int(state.get("current_volume_index", 0) or 0)

    base_update = {
        "story_path": [],
        "path_approved": False,
        "current_node_index": 0,
        "creation_complete": False,
        "pending_review_type": "",
        "auto_total_retry_count": 0,
        "batch_index": batch_index + 1,
    }

    if chain and pos >= len(chain) and vol_idx + 1 < len(volumes):
        base_update["current_volume_index"] = vol_idx + 1
        base_update["current_event_chain"] = []
        base_update["current_event_chain_pos"] = 0
        base_update["last_event_batch_size"] = 0
        base_update["volume_start_event_count"] = int(
            state.get("global_settled_event_count", 0) or 0
        )
        base_update["_auto_review_goto"] = "event_chain_gen"
        return Command(update=base_update, goto="event_chain_gen")

    base_update["_auto_review_goto"] = "path_gen"
    return Command(update=base_update, goto="path_gen")


# ── 降级回人工 ──────────────────────────────────────────────────────────────

def _fallback_to_human(
    state: CreationState,
    review_type: str,
    reason: str,
) -> Command:
    """连续自动修改失败，通知用户介入。临时切回对应的人工确认节点。"""
    from rich.console import Console

    console = Console()
    console.print(
        f"\n[yellow]⚠[/yellow]  自动模式无法解决当前问题，需要您介入\n"
        f"  问题：{reason}\n"
        f"  请手动处理后继续。"
    )

    goto_map = {
        "path":   "human_review_path",
        "expand": "human_review_expand",
        "write":  "human_review_write",
        "batch":  "human_review_batch",
    }

    goto = goto_map.get(review_type, "human_review_path")
    return Command(
        update={
            "auto_retry_count": 0,
            "auto_retry_count_path": 0,
            "auto_retry_count_expand": 0,
            "auto_retry_count_write": 0,
            "auto_total_retry_count": 0,
            "pending_review_type": review_type,
            "_auto_review_goto": goto,
        },
        goto=goto,
    )


def _direct_pass(state: CreationState, review_type: str) -> Command:
    """未知 review_type 时默认通过到 expand2（expand 流程的下游）"""
    return Command(
        update={"pending_review_type": "", "expand1_approved": True, "_auto_review_goto": "expand2"},
        goto="expand2",
    )


# ── 辅助函数 ────────────────────────────────────────────────────────────────

def _format_path(story_path: list) -> str:
    return "\n".join(
        f"{i+1}. {n.get('node_name', '')}：{n.get('one_liner', '')}"
        for i, n in enumerate(story_path)
    )


def _format_char_cards(cards: list) -> str:
    if not cards:
        return "无"
    lines = []
    for c in cards:
        traits = c.get("traits_display", [])
        trait_part = "\n".join(f"  • {t}" for t in traits[:3])
        ms = (c.get("current_mental_state") or "").strip()
        gp = (c.get("mental_growth_path") or "").strip()
        rs = (c.get("reverse_scale") or "").strip()
        mental_part = ""
        if ms or gp or rs:
            mental_part = (
                "\n"
                f"  心智成熟度：{ms or '未知'}\n"
                f"  心智成长轨迹：{gp or '未知'}\n"
                f"  绝对逆鳞：{rs or '无'}"
            )
        lines.append(f"{c.get('standard_name', '')}：\n{trait_part}{mental_part}")
    return "\n".join(lines)


def _extract_character_names(draft: str, state: dict) -> list[str]:
    """从正文中提取出现的人物名（从 current_expand1/story_path 的 key_characters 匹配）"""
    key_chars = (state.get("current_expand1") or {}).get("key_characters", [])
    if isinstance(key_chars, str):
        key_chars = [x.strip() for x in key_chars.replace("、", ",").split(",") if x.strip()]
    if not key_chars:
        story_path = state.get("story_path", [])
        node_index = state.get("current_node_index", 0)
        if node_index < len(story_path):
            key_chars = (story_path[node_index] or {}).get("key_characters", [])
        if isinstance(key_chars, str):
            key_chars = [x.strip() for x in key_chars.replace("、", ",").split(",") if x.strip()]
    protagonist = state.get("protagonist_name", "")
    if protagonist and protagonist not in key_chars:
        key_chars = [protagonist] + list(key_chars)
    return [n for n in key_chars if n and n in draft]
