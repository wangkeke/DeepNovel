"""
human_review_chapter_node：章节事件链审核节点

在 expand2 之后、write 之前触发 interrupt，
展示本章的事件路径链，让用户确认叙事方向：

  approve → write_node（按确认的事件链写作）
  revise  → expand1（重新分析，将修改意见注入当前路径节点）
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState


async def human_review_chapter_node(state: CreationState) -> Command:
    chain        = state.get("pending_event_path_chain", [])
    current_idx  = state.get("current_node_index", 0)
    story_path   = state.get("story_path", [])
    node_name    = (
        story_path[current_idx].get("node_name", f"第{current_idx + 1}章")
        if current_idx < len(story_path)
        else f"第{current_idx + 1}章"
    )

    # 格式化事件链供展示
    chain_text = "\n".join(
        f"  {i + 1}. {step}" for i, step in enumerate(chain)
    ) if chain else "  （暂无事件链）"

    user_input = interrupt({
        "type":    "chapter_review",
        "content": {
            "node_name":        node_name,
            "node_index":       current_idx,
            "event_path_chain": chain,
        },
        "prompt": (
            f"第 {current_idx + 1} 章：{node_name}\n\n"
            f"事件路径链：\n{chain_text}\n\n"
            "[1] 满意，开始写作\n"
            "[2] 修改 - 请附上修改意见（将回到分析阶段重新规划）"
        ),
    })

    if user_input.get("action") == "approve":
        return Command(
            update={"chapter_approved": True},
            goto="write",
        )
    else:
        feedback = user_input.get("feedback", "")
        # 将修改意见注入当前路径节点，expand1 可读取
        updated_path = list(story_path)
        if current_idx < len(updated_path):
            updated_path[current_idx] = {
                **updated_path[current_idx],
                "chapter_feedback": feedback,
            }
        return Command(
            update={
                "chapter_approved":         False,
                "story_path":               updated_path,
                "pending_event_path_chain": [],
            },
            goto="expand1",
        )
