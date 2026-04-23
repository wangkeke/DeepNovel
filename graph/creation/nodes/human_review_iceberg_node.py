"""
human_review_iceberg_node：仅 interrupt，确认 iceberg_review_payload 并入主 state。

v4.2：冰山在世界设定与主角卡之后运行；通过后进入 genesis_ignition 点燃开篇，
不再回到 world_build（世界设定已在 human_review_world 锁定）。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from graph.creation.nodes.human_review_node import _upsert_project
from utils.v42_flow import shallow_world_archive


async def human_review_iceberg_node(state: CreationState) -> Command:
    payload = state.get("iceberg_review_payload") or {}
    synopsis = payload.get("synopsis") if isinstance(payload, dict) else {}
    if not isinstance(synopsis, dict) or not (synopsis.get("title") or synopsis.get("core_conflict")):
        return Command(goto="iceberg_deduction")

    user_input = interrupt({
        "type": "iceberg_review",
        "content": payload,
        "prompt": "确认冰山反推结果，或要求重新反推",
    })
    action = user_input.get("action", "approve")
    if action == "regenerate":
        fb = (user_input.get("feedback") or "").strip()
        return Command(
            update={
                "iceberg_review_payload": {},
                "iceberg_deduction_feedback": fb or "结构再紧缩、格局再抬高",
                "iceberg_synopsis_only": False,
                "iceberg_world_snapshot": {},
            },
            goto="iceberg_deduction",
        )

    opening_final = (user_input.get("opening_text") or "").strip()
    if not opening_final:
        opening_final = (payload.get("opening_text") or "").strip()
    syn = dict(payload.get("synopsis") or {})
    # 种子正文由后续 genesis_ignition 生成；此处仅同步占位或用户粘贴
    syn["opening_seed_text"] = opening_final
    ws_ice = payload.get("world_setting") if isinstance(payload.get("world_setting"), dict) else {}
    base_ws = state.get("world_setting") if isinstance(state.get("world_setting"), dict) else {}
    merged_ws = {**base_ws, **ws_ice} if ws_ice else dict(base_ws)

    try:
        await _upsert_project(
            project_id=state.get("project_id", ""),
            blueprint_id=state.get("blueprint_id", ""),
            genre_request=state.get("genre_request", ""),
            synopsis=syn,
            platform_style=state.get("platform_style", "通用网文"),
        )
    except Exception:
        pass

    return Command(
        update={
            "synopsis": syn,
            "synopsis_approved": True,
            "world_setting": merged_ws,
            "world_setting_confirmed": True,
            "world_setting_feedback": "",
            "skip_world_build_regen": False,
            "iceberg_world_snapshot": merged_ws,
            "world_archive": shallow_world_archive(merged_ws),
            "genesis_protagonist_card": payload.get("protagonist_card") or {},
            "protagonist_user_input": {},
            "iceberg_review_payload": {},
            "iceberg_deduction_feedback": "",
        },
        goto="genesis_ignition",
    )
