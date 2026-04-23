"""
update_weight_node：骨骼权重动态更新节点
每个节点写完后调整 blueprint_weight，同时判断是否需要长篇续写。

权重调整规则：
  - 扭转（post_pivot=True）：每次扭转后权重衰减 0.1（最低降到 0.1）
    表示故事逐渐脱离原骨骼轨道，以故事圣经为主
  - 一致性违规后重写成功：保持当前权重不变
  - 正常通过：维持权重，不变化

长篇续写判断：
  - 当前批次节点全部写完（current_node_index >= len(story_path)）
  - 故事未标记完成（creation_complete=False）→ 触发下一批 path_gen
  - 如果 story_path 为空或 completed_chapters 数量达到阈值 → 标记完成
"""
from __future__ import annotations
from langgraph.types import StreamWriter
from schemas.state import CreationState
from memory.db import update_event_chain_pos


async def update_weight_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "update_weight"})
    weight     = state.get("blueprint_weight", 0.5)
    post_pivot = state.get("post_pivot", False)
    current_idx = state.get("current_node_index", 0)
    story_path = state.get("story_path", [])

    # 权重衰减（扭转后）
    if post_pivot:
        weight = max(0.1, round(weight - 0.1, 2))

    out: dict = {
        "blueprint_weight": weight,
    }
    # 本批节点全部写完时，按本批消费的事件数推进事件链游标（path 驳回重跑不会走到此处）
    if story_path and current_idx >= len(story_path):
        delta = int(state.get("last_event_batch_size", 0) or 0)
        chain = state.get("current_event_chain") or []
        pos = int(state.get("current_event_chain_pos", 0) or 0)
        if delta > 0 and chain:
            new_pos = pos + delta
            out["current_event_chain_pos"] = new_pos
            out["last_event_batch_size"] = 0
            pid = state.get("project_id", "")
            if pid:
                await update_event_chain_pos(pid, new_pos)

    if state.get("auto_mode") and current_idx >= len(story_path):
        out["pending_review_type"] = "batch"
    return out