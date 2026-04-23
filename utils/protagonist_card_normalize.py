"""
主角人物卡：与 docs/DeepNovel_重构文档_完整版.md PROMPT 3 对齐后的规范化。
LLM 可输出文档型 mental_core（文字）+ mental_core_panel（引擎五维整数）；
入库前统一为 mental_core 五维整数 + 保留 literary/detail 副本。
"""
from __future__ import annotations

from typing import Any

from utils.mental_core import normalize_mental_core_dict


def _is_literary_mental_core(mc: dict) -> bool:
    if not isinstance(mc, dict):
        return False
    return any(
        isinstance(mc.get(k), str) and len(str(mc.get(k) or "").strip()) > 0
        for k in ("intellect", "emotional_intelligence", "strategic_thinking", "endurance")
    )


def normalize_protagonist_card_for_state(card: dict[str, Any]) -> None:
    """就地规范化主角卡：name/standard_name、先天、成熟度、精神面板。"""
    if not isinstance(card, dict):
        return

    name = (card.get("name") or card.get("standard_name") or "").strip()
    if name:
        card["name"] = name
        if not (card.get("standard_name") or "").strip():
            card["standard_name"] = name

    # ── mental_core：文档型 → mental_core_literary；引擎用五维整数 ──
    mc = card.get("mental_core")
    panel = card.get("mental_core_panel") if isinstance(card.get("mental_core_panel"), dict) else {}
    if isinstance(mc, dict) and _is_literary_mental_core(mc):
        card["mental_core_literary"] = dict(mc)
        p = dict(panel)
        if not p and isinstance(mc.get("emotional_capacity"), (int, float)):
            try:
                ec = int(round(float(mc["emotional_capacity"])))
                p["emotional_capacity"] = max(0, min(100, ec))
            except (TypeError, ValueError):
                pass
        card["mental_core"] = normalize_mental_core_dict(p)
    elif isinstance(panel, dict) and panel:
        card["mental_core"] = normalize_mental_core_dict(panel)
    elif isinstance(mc, dict):
        card["mental_core"] = normalize_mental_core_dict(mc)
    else:
        card["mental_core"] = normalize_mental_core_dict({})
    card.pop("mental_core_panel", None)

    # ── innate_traits：文档为对象时拆成列表供扩写/旧逻辑 ──
    inn = card.get("innate_traits")
    if isinstance(inn, dict):
        card["innate_traits_detail"] = inn
        parts: list[str] = []
        for k in ("personality", "talent_physical"):
            for x in inn.get(k) or []:
                s = str(x).strip()
                if s:
                    parts.append(s)
        card["innate_traits"] = parts[:12]
    elif isinstance(inn, list):
        card["innate_traits"] = [str(x).strip() for x in inn if str(x).strip()][:12]
    else:
        card["innate_traits"] = []

    # ── maturity_level：文档为对象 ──
    ml = card.get("maturity_level")
    if isinstance(ml, dict):
        card["maturity_level_detail"] = ml
        score = str(ml.get("current_score") or "").strip()
        ill = ml.get("illusions_held") or []
        ill_s = "；".join(str(x) for x in ill[:8] if str(x).strip())
        gt = str(ml.get("growth_trajectory") or "").strip()
        parts2: list[str] = []
        if score:
            parts2.append(f"档位：{score}")
        if ill_s:
            parts2.append(f"当前保有幻想/成长靶点：{ill_s}")
        if gt:
            parts2.append(f"跃迁：{gt}")
        summary = "。".join(parts2) if parts2 else score
        card["current_maturity"] = summary[:600]
        card["maturity_level"] = summary[:600]
    else:
        card.setdefault("current_maturity", "")
        card.setdefault("maturity_level", "")
        if isinstance(ml, str) and ml.strip():
            card["current_maturity"] = ml.strip()[:600]
            card["maturity_level"] = ml.strip()[:600]

    try:
        card["current_emotional_drain"] = max(
            0, min(100, int(card.get("current_emotional_drain", 0) or 0))
        )
    except (TypeError, ValueError):
        card["current_emotional_drain"] = 0

    # core_motif：文档未单列时从 innate 欲求/恐惧归纳一句叙事锚
    if not (card.get("core_motif") or "").strip():
        inn_d = card.get("innate_traits_detail") if isinstance(
            card.get("innate_traits_detail"), dict
        ) else {}
        cd = str(inn_d.get("core_desire") or "").strip()
        cf = str(inn_d.get("core_fear") or "").strip()
        if cd or cf:
            card["core_motif"] = (f"欲求：{cd}" + (f"；恐惧：{cf}" if cf else ""))[:500]

    card.setdefault("reverse_scale", "")
    card.setdefault("world_position", "")
    card.setdefault("independent_agenda", "")
    card.setdefault("faction_relationship", {})
    card.setdefault("character_id", "")
    card.setdefault("aliases", [])
