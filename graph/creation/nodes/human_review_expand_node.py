"""
human_review_expand_node：expand1 后的方向确认节点

在 expand1（3W1H 分析）完成后、expand2（场景设计）开始前介入。
用户此时看到的是 expand1 生成的草稿事件路径链，代价仅为 expand1 的 token。

[1] 路径正确 → expand2（expand1_approved=True）
[2] 修改路径 → expand1（注入 chapter_feedback，代价极小）

职责：方向性确认，防止方向错了再花大量 token 写正文。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState


async def human_review_expand_node(state: CreationState) -> Command:
    draft_chain = state.get("expand1_event_draft", [])
    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    expand1     = state.get("current_expand1", {})

    node_name = (
        story_path[current_idx].get("node_name", f"第{current_idx + 1}章")
        if current_idx < len(story_path)
        else f"第{current_idx + 1}章"
    )

    # v4.3 路径落地确认输出字段（chapter_tone / chapter_driver / function_confirmed 等）
    is_v43 = bool(expand1.get("chapter_tone") or expand1.get("chapter_driver") or expand1.get("function_confirmed"))
    if is_v43:
        # v4.3 分支：直接展示落地确认结果
        content = {
            "node_name":              node_name,
            "node_index":             current_idx,
            "is_v43":                 True,
            "path_id":                expand1.get("path_id", ""),
            "chapter_tone":           expand1.get("chapter_tone", ""),
            "function_confirmed":     expand1.get("function_confirmed", ""),
            "chapter_driver":         expand1.get("chapter_driver", ""),
            "key_state_factors":      expand1.get("key_state_factors", []),
            "causal_input":           expand1.get("causal_input", ""),
            "causal_output_direction": expand1.get("causal_output_direction", ""),
            "hidden_seed":            expand1.get("hidden_seed", ""),
            "state_audit_note":       expand1.get("state_audit_note", ""),
            "event_path_draft":       draft_chain,
        }
    else:
        # 旧版分支：施压机制 + 破局方式 + 草稿路径链
        how = expand1.get("how", {})
        what = expand1.get("what", {})
        content = {
            "node_name":              node_name,
            "node_index":             current_idx,
            "is_v43":                 False,
            "core_event":             what.get("core_event", ""),
            "pressure_mechanism":     how.get("pressure_mechanism", ""),
            "resolution_trigger":     how.get("resolution_trigger", ""),
            "event_path_draft":       draft_chain,
        }

    user_input = interrupt({"type": "expand_review", "content": content})

    action   = user_input.get("action", "approve")
    feedback = user_input.get("feedback", "").strip()

    if action == "approve":
        return Command(
            update={"expand1_approved": True},
            goto="expand2",
        )

    # 修改路径：注入反馈到当前 story_path 节点，重新跑 expand1
    updated_path = list(story_path)
    if current_idx < len(updated_path):
        updated_path[current_idx] = {
            **updated_path[current_idx],
            "chapter_feedback": feedback,
        }

    # 清除 bible 中来自 human_review_write 的解析结果，避免混用
    bible_clear = {**state.get("bible", {}), "rewrite_feedback": "", "rewrite_feedback_parsed": {}}

    return Command(
        update={
            "expand1_approved":   False,
            "expand1_event_draft": [],
            "story_path":         updated_path,
            "bible":              bible_clear,
        },
        goto="expand1",
    )
