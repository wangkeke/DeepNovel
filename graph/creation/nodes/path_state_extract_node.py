"""
path_state_extract_node：补丁 H — 单路径正文 → 五维 path_state，生成下一路径 write 接力块。
在 write 之后、consistency 之前运行（与 graph 边一致）。
"""
from __future__ import annotations

import logging

from langgraph.types import StreamWriter

from schemas.state import CreationState
from prompts.creation.path_state_extract import (
    PATH_STATE_EXTRACT_SYSTEM,
    PATH_STATE_EXTRACT_USER_TEMPLATE,
)
from utils.text_metrics import prose_char_count
from utils.path_relay import build_path_relay_context, get_current_v43_path_def, init_paths_status_from_paths
from utils.display import node_step, node_done
from utils.llm import call_llm_json
from utils.narrative_memory import parse_inner_stream_batch
from prompts.creation.narrative_memory import INNER_STREAM_BATCH_SYSTEM, INNER_STREAM_BATCH_USER

logger = logging.getLogger(__name__)


def _event_planning_context_for_inner_stream(state: CreationState) -> str:
    """从 current_event 取出补丁 J 的 event_result_type / tick 类型，供内心切片语气对齐。"""
    ev = state.get("current_event") or {}
    if not isinstance(ev, dict) or not ev:
        return "（尚无 current_event：按正文纯事实提取即可）"
    cc = ev.get("causal_chain") if isinstance(ev.get("causal_chain"), dict) else {}
    er = str(cc.get("event_result_type") or "").strip()
    pt = ev.get("protagonist_tick") if isinstance(ev.get("protagonist_tick"), dict) else {}
    ptt = str(pt.get("protagonist_tick_type") or "").strip()
    return (
        f"event_result_type: {er or '（未生成，仅从正文推断语气）'}\n"
        f"protagonist_tick_type: {ptt or '（未生成）'}\n"
        "切片语气：A_closed 偏阅历人情；B_fragment 须有主线碎片相关的疑虑/追查欲（仅当正文已出现线索）；"
        "C_open 偏压力与议程被打断。"
    )


def _merge_path_state_into_paths_status(
    paths_status: list,
    path_id: str,
    path_state: dict,
    last_sentence: str,
) -> list:
    out: list = []
    for row in paths_status:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        if str(r.get("path_id") or "").strip() == path_id:
            r["path_state"] = path_state
            r["last_sentence"] = last_sentence or None
            r["status"] = "written_pending_tension"
        out.append(r)
    return out


async def path_state_extract_node(
    state: CreationState,
    writer: StreamWriter,
) -> dict:
    writer({"node_status": "started", "node": "path_state_extract"})

    draft = (state.get("current_draft") or "").strip()
    pp = dict(state.get("path_progress") or {}) if isinstance(state.get("path_progress"), dict) else {}
    remaining = list(pp.get("remaining_paths") or [])
    event_paths = state.get("current_event_paths") or {}

    # 非 v4.3 多路径：跳过（不调用 LLM）
    if not isinstance(event_paths, dict) or not event_paths.get("paths") or len(remaining) < 1:
        writer({"node_status": "done", "node": "path_state_extract"})
        return {}

    path_id = str(remaining[0] or "").strip()
    if not path_id or not draft:
        writer({"node_status": "done", "node": "path_state_extract"})
        return {}

    node_step(f"path_state_extract：路径 {path_id}（{prose_char_count(draft)} 字）")

    user_prompt = PATH_STATE_EXTRACT_USER_TEMPLATE.format(
        path_id=path_id,
        draft=draft[:6000],
    )

    raw: dict = {}
    try:
        raw = await call_llm_json(PATH_STATE_EXTRACT_SYSTEM, user_prompt, max_tokens=3000)
    except Exception as e:
        logger.warning("path_state_extract LLM 失败: %s", e)

    if not isinstance(raw, dict):
        raw = {}

    raw["path_id"] = path_id
    phys = raw.get("1_physical_state") if isinstance(raw.get("1_physical_state"), dict) else {}
    last_sentence = str(phys.get("last_sentence") or "").strip()

    relay = build_path_relay_context(raw)
    paths_status = list(pp.get("paths_status") or [])
    if not paths_status:
        ep = state.get("current_event_paths") or {}
        paths = ep.get("paths") if isinstance(ep, dict) else []
        if isinstance(paths, list):
            paths_status = init_paths_status_from_paths(paths)
    if paths_status:
        paths_status = _merge_path_state_into_paths_status(
            paths_status, path_id, raw, last_sentence
        )

    pp["last_path_state_extract"] = raw
    pp["write_relay_context"] = relay
    if paths_status:
        pp["paths_status"] = paths_status

    # ── 补丁 I：在场内心切片（每路径写完后追加，章末 bible_update 固化入 long_term）──
    cand: list[str] = []
    pd = get_current_v43_path_def(state)
    if isinstance(pd, dict):
        pov = str(pd.get("pov_character") or "").strip()
        if pov:
            cand.append(pov)
        kc = pd.get("key_characters", [])
        if isinstance(kc, str):
            kc = [x.strip() for x in kc.replace("，", ",").split(",") if x.strip()]
        if isinstance(kc, list):
            for x in kc:
                s = str(x).strip() if x is not None else ""
                if s and s not in cand:
                    cand.append(s)
    prot = str(state.get("protagonist_name") or "").strip()
    if prot and prot not in cand:
        cand.insert(0, prot)
    seen_c: set[str] = set()
    cand_unique: list[str] = []
    for n in cand:
        if n not in seen_c:
            seen_c.add(n)
            cand_unique.append(n)
    cand_unique = cand_unique[:8]
    names_text = "\n".join(f"- {n}" for n in cand_unique) if cand_unique else ""
    if names_text:
        try:
            inner_raw = await call_llm_json(
                INNER_STREAM_BATCH_SYSTEM,
                INNER_STREAM_BATCH_USER.format(
                    path_id=path_id,
                    event_planning_context=_event_planning_context_for_inner_stream(state),
                    character_names=names_text,
                    draft=draft[:7000],
                ),
                max_tokens=1500,
            )
        except Exception as e:
            logger.warning("inner narrative stream batch 失败: %s", e)
            inner_raw = {}
        slices = parse_inner_stream_batch(inner_raw if isinstance(inner_raw, dict) else {})
        pend = list(pp.get("pending_inner_stream_chunks") or [])
        for s in slices:
            pend.append(
                {"character_name": s["character_name"], "inner_slice": s["inner_slice"], "path_id": path_id}
            )
        pp["pending_inner_stream_chunks"] = pend[-120:]

    node_done("path_state_extract：五维状态已写入 path_progress")
    writer({"node_status": "done", "node": "path_state_extract"})
    return {"path_progress": pp}
