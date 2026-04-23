"""路径节点上的因果演化字段：果/种、兑现时机（与白皮书·演化层一致）。"""
from __future__ import annotations

_PAYOFF = frozenset({"immediate", "delayed"})


def default_fruit_and_seed() -> dict[str, str]:
    return {
        "immediate_fruit": "",
        "hidden_seed": "",
        "payoff_timing": "immediate",
    }


def normalize_fruit_and_seed(raw: object) -> dict[str, str]:
    """immediate_fruit / hidden_seed 为短句；payoff_timing ∈ {immediate, delayed}。"""
    base = default_fruit_and_seed()
    if not isinstance(raw, dict):
        return base
    for k in ("immediate_fruit", "hidden_seed"):
        v = raw.get(k)
        if isinstance(v, str):
            base[k] = v.strip()[:800]
    pt = raw.get("payoff_timing")
    if isinstance(pt, str):
        s = pt.strip().lower()
        if s in _PAYOFF:
            base["payoff_timing"] = s
        elif "delay" in s or "远期" in s or "伏脉" in s:
            base["payoff_timing"] = "delayed"
    return base


def format_fruit_and_seed_for_prompt(fs: dict[str, str] | None) -> str:
    d = fs if isinstance(fs, dict) else default_fruit_and_seed()
    imm = (d.get("immediate_fruit") or "").strip()
    hid = (d.get("hidden_seed") or "").strip()
    pt = (d.get("payoff_timing") or "immediate").strip()
    if not imm and not hid:
        return "（未单列：请结合 node_result 与 tension 自行落实表面结果与暗线种子）"
    timing_zh = "下一拍/近线" if pt == "immediate" else "远期/伏脉"
    parts = []
    if imm:
        parts.append(f"表面结果：{imm}")
    if hid:
        parts.append(f"暗中埋种：{hid}")
    parts.append(f"兑现预期：{timing_zh}")
    return "；".join(parts)
