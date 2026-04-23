"""
human_review_event_chain_node：确认本卷事件链（仅 interrupt，无 LLM）

与 event_chain_gen_node 拆分，避免 LangGraph resume 从节点头重跑导致事件链生成两遍。
支持识别 Phase 2 漂移报告，向用户暴露漂移决策选项：
  - accept_drift：接受当前走向，调整锚点内容继续
  - skip_anchor：接受当前走向，跳过偏离的锚点继续
  - rollback：回滚到上一锚点重新推导（重新生成整个事件链）
  - regenerate：完全重新生成（等同旧 regenerate）
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.db import save_event_chain, get_volumes
import logging

logger = logging.getLogger("deepnovel.event_chain_review")


def _has_drift_flag(draft: list) -> bool:
    """检测事件链中是否含 Phase 2 严重漂移哨兵事件。"""
    return any(
        isinstance(e, dict) and e.get("_drift_flag") is True
        for e in draft
    )


def _strip_drift_sentinel(events: list) -> list:
    """移除漂移哨兵，返回真实事件列表。"""
    return [e for e in events if not (isinstance(e, dict) and e.get("_drift_flag"))]


async def human_review_event_chain_node(state: CreationState) -> Command:
    draft = list(state.get("event_chain_draft") or [])
    if not draft:
        return Command(goto="event_chain_gen")

    project_id = state.get("project_id", "")
    vol_index = int(state.get("current_volume_index", 0) or 0)
    volumes = list(state.get("volumes") or [])
    if not volumes and project_id:
        volumes = await get_volumes(project_id)
    current_vol = volumes[vol_index] if vol_index < len(volumes) else {}

    # 检测 Phase 2 漂移报告
    drift_detected = _has_drift_flag(draft)
    clean_draft = _strip_drift_sentinel(draft)
    drift_detail = ""
    if drift_detected:
        sentinel = next((e for e in draft if isinstance(e, dict) and e.get("_drift_flag")), {})
        drift_detail = sentinel.get("drift_detail", "")
        logger.warning("human_review_event_chain：检测到 Phase 2 严重漂移哨兵，共 %s 个事件", len(clean_draft))

    interrupt_payload: dict = {
        "type": "event_chain_review",
        "content": {
            "volume_name": current_vol.get("volume_name", ""),
            "volume_index": vol_index,
            "total_events": len(clean_draft),
            "events": clean_draft,
        },
        "prompt": "请确认本卷事件链（可重新生成）",
    }
    if drift_detected:
        interrupt_payload["drift_warning"] = {
            "message": "Phase 2 循环推导检测到严重漂移，事件链与锚点到达条件偏离较大",
            "detail": drift_detail,
            "options": [
                {"action": "accept_drift", "label": "接受当前走向（继续，锚点内容由人工调整）"},
                {"action": "skip_anchor", "label": "接受走向并跳过偏离锚点"},
                {"action": "rollback", "label": "回滚到上一锚点重新推导（重新生成）"},
                {"action": "regenerate", "label": "完全重新生成本卷事件链"},
            ],
        }

    user_input = interrupt(interrupt_payload)

    # ── 防空双保险 ──────────────────────────────────────────────────────────
    if not isinstance(user_input, dict):
        logger.warning("human_review_event_chain：user_input 非 dict，强制重新生成")
        return Command(
            update={"event_chain_draft": []},
            goto="event_chain_gen",
        )

    action = user_input.get("action", "approve")

    if action in ("regenerate", "rollback"):
        return Command(
            update={"event_chain_draft": []},
            goto="event_chain_gen",
        )

    if action == "skip_anchor":
        # 跳过偏离锚点：使用当前已生成的事件（不含哨兵），继续下一步
        events = clean_draft
    elif action == "accept_drift":
        # 接受漂移：使用当前事件，锚点调整由人工在后续 review 处理
        events = clean_draft
    else:
        # approve / edit
        events = list(clean_draft)
        if action == "edit" and user_input.get("edited_events"):
            events = list(user_input["edited_events"])

    # 二次防空：events 为空时回退重生成
    if not events:
        logger.warning("human_review_event_chain：确认后 events 为空，强制重新生成")
        return Command(
            update={"event_chain_draft": []},
            goto="event_chain_gen",
        )

    if project_id:
        await save_event_chain(project_id, vol_index, events, chain_pos=0)

    return Command(
        update={
            "current_event_chain": events,
            "current_event_chain_pos": 0,
            "event_chain_draft": [],
        },
        goto="path_gen",
    )
