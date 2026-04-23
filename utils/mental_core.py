"""精神面板五维：0～100 规范化（与 schemas.entity.MentalCore 一致）。"""
from __future__ import annotations

_MENTAL_KEYS = ("intelligence", "eq", "meticulousness", "emotional_capacity", "forbearance")


def normalize_mental_core_dict(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        raw = {}
    out: dict[str, int] = {}
    for k in _MENTAL_KEYS:
        default = 60 if k == "emotional_capacity" else 50
        try:
            v = int(raw.get(k, default))
        except (TypeError, ValueError):
            v = default
        out[k] = max(0, min(100, v))
    return out
