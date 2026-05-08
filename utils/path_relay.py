"""
补丁 H：路径五维接力（path_state_extract → 下一路径 write 注入）。
补丁 G：paths_status 初始化、当前路径定义解析、章节展示名。
"""
from __future__ import annotations

from typing import Any, Mapping


def init_paths_status_from_paths(paths: list) -> list[dict[str, Any]]:
    """path_gen_v43 产出 paths 时，初始化 paths_status（与 remaining_paths 顺序一致）。"""
    out: list[dict[str, Any]] = []
    for p in paths:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("path_id") or "").strip()
        if not pid:
            continue
        pnm = str(p.get("path_name") or p.get("moment_description") or "").strip()
        out.append(
            {
                "path_id": pid,
                "path_name": pnm,
                "status": "pending",
                "path_state": None,
                "last_sentence": None,
            }
        )
    return out


def build_path_relay_context(path_state: Mapping[str, Any] | None) -> str:
    """将五维状态转化为下一条路径 write 的上下文注入（补丁 H §四）。"""
    if not isinstance(path_state, dict) or not path_state:
        return ""

    physical = path_state.get("1_physical_state") or {}
    if not isinstance(physical, dict):
        physical = {}
    inventory = path_state.get("2_inventory_delta") or {}
    if not isinstance(inventory, dict):
        inventory = {}
    entities = path_state.get("3_emergent_entities") or {}
    if not isinstance(entities, dict):
        entities = {}
    decision = path_state.get("4_character_decision") or {}
    if not isinstance(decision, dict):
        decision = {}
    tension = path_state.get("5_immediate_tension") or {}
    if not isinstance(tension, dict):
        tension = {}

    entity_lines: list[str] = []
    for e in entities.get("entities") or []:
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "").strip()
        if not name:
            continue
        et = str(e.get("type") or "").strip()
        fact = str(e.get("established_fact") or "").strip()
        entity_lines.append(f"  · {name}（{et}）：{fact}")

    inv_changes = inventory.get("changes") or []
    if isinstance(inv_changes, str):
        inv_changes = [inv_changes] if inv_changes.strip() else []
    if not isinstance(inv_changes, list):
        inv_changes = []
    inventory_lines = [f"  · {c}" for c in inv_changes if str(c).strip()]
    threats = tension.get("active_threats") or []
    if isinstance(threats, str):
        threats = [threats] if threats.strip() else []
    if not isinstance(threats, list):
        threats = []
    threat_str = ", ".join(str(t) for t in threats if str(t).strip()) or "无"

    relay = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
【前文已确立的核心事实——必须完整继承，不得修改或遗忘】
━━━━━━━━━━━━━━━━━━━━━━━━━━━

【写作起点（物理接缝）】
主角当前位置：{physical.get("end_location", "未知")}
姿态与状态：{physical.get("end_posture_and_status", "未知")}
接缝句（从这句话的下一秒开始写，不要重复）：
"{physical.get("last_sentence", "")}"

【已确立的关键实体（严禁改名或替换）】
{chr(10).join(entity_lines) if entity_lines else "  · 无新增实体"}

【道具/资源变动（严格遵守，不得矛盾）】
{chr(10).join(inventory_lines) if inventory_lines else "  · 无变动"}

【主角的核心决策（驱动本段剧情的方向）】
{decision.get("final_decision", "无")}
⚠️ {decision.get("this_decision_drives_next_path", "")}

【当前紧张氛围（情绪气口）】
紧迫压力：{tension.get("urgency", "无")}
活跃威胁：{threat_str}
整体氛围：{tension.get("atmosphere", "无")}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return relay.strip()


def get_current_v43_path_def(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """从 current_event_paths.paths 中取 path_progress.remaining_paths[0] 对应的路径定义。"""
    pp = state.get("path_progress") or {}
    if not isinstance(pp, dict):
        return None
    remaining = list(pp.get("remaining_paths") or [])
    if not remaining:
        return None
    pid = str(remaining[0] or "").strip()
    if not pid:
        return None
    ep = state.get("current_event_paths") or {}
    if not isinstance(ep, dict):
        return None
    for p in ep.get("paths") or []:
        if isinstance(p, dict) and str(p.get("path_id") or "").strip() == pid:
            return p
    return None


def _default_pass_next_node(state: Mapping[str, Any]) -> str:
    return "auto_review" if state.get("auto_mode") else "human_review_write"


def effective_chapter_draft(state: Mapping[str, Any]) -> str:
    """
    入库与圣经抽取用的「整章正文」。
    优先 current_draft；若为空则回退 path_progress.all_paths_text（v4.3 多路径已合并片段）。
    与 narrative_extract 的回退逻辑一致，避免「提取用了合并稿、入库仍读空串」的断层。
    """
    raw = state.get("current_draft")
    d = (raw or "").strip() if isinstance(raw, str) else ""
    if d:
        return str(raw).strip()
    pp = state.get("path_progress")
    if isinstance(pp, dict):
        ap = str(pp.get("all_paths_text") or "").strip()
        if ap:
            return ap
    return ""


def v43_tension_pass_update(state: Mapping[str, Any], draft: str) -> tuple[dict[str, Any], str]:
    """
    补丁 G：单路径张力通过后，将本段并入 all_paths_text、推进 remaining_paths；
    若仍有路径 → 下一跳 write；否则合并正文进入人工/自动审阅。
    非 v4.3 或未配置路径时返回空 update，由调用方使用默认下一跳。
    """
    if not state.get("current_event_paths"):
        return {}, _default_pass_next_node(state)
    pp = dict(state.get("path_progress") or {}) if isinstance(state.get("path_progress"), dict) else {}
    remaining = list(pp.get("remaining_paths") or [])
    if not remaining:
        return {}, _default_pass_next_node(state)

    pid = str(remaining[0] or "").strip()
    if not pid:
        return {}, _default_pass_next_node(state)

    completed = list(pp.get("completed_paths") or [])
    ap = str(pp.get("all_paths_text") or "").strip()
    seg = (draft or "").strip()
    ap = f"{ap}\n\n{seg}".strip() if ap else seg

    remaining_new = remaining[1:]
    completed_new = completed + [pid]

    paths_status_in = list(pp.get("paths_status") or [])
    paths_status_out: list[dict[str, Any]] = []
    last_st = pp.get("last_path_state_extract")
    for row in paths_status_in:
        if not isinstance(row, dict):
            continue
        r = dict(row)
        if str(r.get("path_id") or "").strip() == pid:
            r["status"] = "completed"
            if isinstance(last_st, dict):
                r["path_state"] = last_st
                phys = last_st.get("1_physical_state")
                if isinstance(phys, dict):
                    ls = str(phys.get("last_sentence") or "").strip()
                    if ls:
                        r["last_sentence"] = ls
        paths_status_out.append(r)

    pp["all_paths_text"] = ap
    pp["remaining_paths"] = remaining_new
    pp["completed_paths"] = completed_new
    if remaining_new:
        nxt_id = str(remaining_new[0] or "").strip()
        for row in paths_status_out:
            if str(row.get("path_id") or "").strip() == nxt_id:
                row["status"] = "in_progress"
                break

    pp["paths_status"] = paths_status_out

    if remaining_new:
        return {
            "path_progress": pp,
            "current_draft": "",
            "tension_retry_count": 0,
            "consistency_result": {},
        }, "write"
    return {
        "path_progress": pp,
        "current_draft": ap,
        "tension_retry_count": 0,
    }, _default_pass_next_node(state)


def v43_chapter_display_name(state: Mapping[str, Any]) -> str:
    """补丁 G Fix2：优先用当前路径 path_name，回退 story_path 节点名。"""
    pd = get_current_v43_path_def(state)
    if isinstance(pd, dict):
        nm = (pd.get("path_name") or pd.get("moment_description") or "").strip()
        if nm:
            return nm
    idx = int(state.get("current_node_index", 0) or 0)
    sp = state.get("story_path") or []
    if isinstance(sp, list) and idx < len(sp):
        row = sp[idx]
        if isinstance(row, dict):
            n = (row.get("node_name") or "").strip()
            if n:
                return n
    return f"第{idx + 1}章"
