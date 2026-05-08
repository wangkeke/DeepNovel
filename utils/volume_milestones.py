"""
卷级里程碑（沙盒引力场）：仅从 milestone_conditions 解析，
供 event_chain_gen / auto_arc_transition / bible 收卷等消费。
"""
from __future__ import annotations

from typing import Any


def _str_mid(prefix: str, idx: int) -> str:
    return f"{prefix}{idx:02d}"


_DEFAULT_FORBIDDEN_MICRO = (
    "禁止在 trigger_state 中写入微观 NPC 具体姓名、台词、连续动作走位、死因现场与唯一剧情链；"
    "禁止规定具体刑侦/笔迹/纸张化验类破局手法（比对墨迹透印度等）；"
    "具体谁来、如何翻盘，全部由 event_chain_gen / write 涌现。"
)


def get_volume_milestones(volume: dict | None) -> list[dict]:
    """
    返回本卷里程碑列表（每项含 milestone_id, milestone_kind, name, trigger_state,
    forbidden_micro_actions, is_volume_closer）。
    仅读取 milestone_conditions；若无或非列表则返回 []。
    """
    if not isinstance(volume, dict):
        return []
    mc = volume.get("milestone_conditions")
    if isinstance(mc, list) and mc:
        out: list[dict] = []
        for i, m in enumerate(mc):
            if not isinstance(m, dict):
                continue
            mid = str(m.get("milestone_id") or "").strip() or _str_mid("m", i + 1)
            ts = str(m.get("trigger_state") or "").strip() or "（待模型补全）"
            fb = str(m.get("forbidden_micro_actions") or "").strip() or _DEFAULT_FORBIDDEN_MICRO
            mk = str(m.get("milestone_kind") or "").strip() or "crisis_collision"
            out.append(
                {
                    "milestone_id": mid,
                    "milestone_kind": mk,
                    "name": str(m.get("name") or "").strip() or mid,
                    "trigger_state": ts,
                    "forbidden_micro_actions": fb,
                    "is_volume_closer": bool(m.get("is_volume_closer")),
                }
            )
        if out and not any(x.get("is_volume_closer") for x in out):
            out[-1]["is_volume_closer"] = True
        return out
    return []


def default_milestone_conditions_placeholder() -> list[dict]:
    """LLM 未输出里程碑时的最小占位（纯状态断言，非动作剧本）。"""
    return [
        {
            "milestone_id": "m_01",
            "milestone_kind": "crisis_collision",
            "name": "卷入核心矛盾",
            "trigger_state": "主角在制度/资源层面已被卷入本卷主矛盾，与结构性对立面发生首次不可回避的碰撞。",
            "forbidden_micro_actions": _DEFAULT_FORBIDDEN_MICRO,
            "is_volume_closer": False,
        },
        {
            "milestone_id": "m_02",
            "milestone_kind": "world_expansion",
            "name": "世界版图扩大（画卷调度）",
            "trigger_state": "主角经若干独立事件后已进入新的可写圈层或地理/社会舞台，人际与信息网显著扩张（可客观叙述、禁止微观分镜）。",
            "forbidden_micro_actions": _DEFAULT_FORBIDDEN_MICRO,
            "is_volume_closer": False,
        },
        {
            "milestone_id": "m_99",
            "milestone_kind": "crisis_collision",
            "name": "收卷跃迁",
            "trigger_state": "本卷明面条线矛盾得到阶段性收束，压力骨架升级并自然暴露下一层威胁或下一卷伏笔。",
            "forbidden_micro_actions": _DEFAULT_FORBIDDEN_MICRO,
            "is_volume_closer": True,
        },
    ]


def ensure_milestone_closer_flag(milestones: list[dict]) -> list[dict]:
    """保证恰好一条 is_volume_closer（若无则最后一条为 True；多条则只保留最后一条）。"""
    if not milestones:
        return [dict(x) for x in default_milestone_conditions_placeholder()]
    out = []
    for m in milestones:
        if not isinstance(m, dict):
            continue
        out.append(dict(m))
    if not out:
        return [dict(x) for x in default_milestone_conditions_placeholder()]
    closers = [i for i, m in enumerate(out) if m.get("is_volume_closer")]
    if not closers:
        out[-1]["is_volume_closer"] = True
    elif len(closers) > 1:
        for i, m in enumerate(out):
            m["is_volume_closer"] = i == closers[-1]
    return out


def normalize_volume_milestones_keys(vol: dict) -> dict:
    """确保卷 dict 带规范化的 milestone_conditions。"""
    if not isinstance(vol, dict):
        return vol
    milestones = get_volume_milestones(vol)
    if not milestones:
        milestones = default_milestone_conditions_placeholder()
    vol = dict(vol)
    vol["milestone_conditions"] = [
        {
            "milestone_id": m["milestone_id"],
            "milestone_kind": m.get("milestone_kind", "crisis_collision"),
            "name": m["name"],
            "trigger_state": m["trigger_state"],
            "forbidden_micro_actions": m["forbidden_micro_actions"],
            "is_volume_closer": m["is_volume_closer"],
        }
        for m in milestones
    ]
    return vol


def _progress_ids_compatible(progress: dict, all_ids: list[str]) -> bool:
    if not all_ids:
        return True
    ids_set = set(all_ids)
    p = [str(x) for x in (progress.get("pending") or []) if x is not None]
    c = [str(x) for x in (progress.get("completed") or []) if x is not None]
    if not p and not c:
        return False
    for x in p + c:
        if x not in ids_set:
            return False
    if set(p) & set(c):
        return False
    return True


def initialize_milestone_progress(
    milestones: list[dict],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    """pending / completed 使用 milestone_id 字符串。若与当前卷 id 不兼容则重置。"""
    all_ids: list[str] = []
    for m in milestones:
        if isinstance(m, dict) and m.get("milestone_id"):
            all_ids.append(str(m.get("milestone_id")))

    if existing and isinstance(existing, dict):
        ex = dict(existing)
        for key in ("pending", "completed"):
            raw = ex.get(key) or []
            if not isinstance(raw, list):
                ex[key] = []
            else:
                ex[key] = [str(x) for x in raw if x is not None]
        if _progress_ids_compatible(ex, all_ids):
            return ex
    return {"completed": [], "pending": all_ids}
