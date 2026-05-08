"""
补丁 E：脑洞引擎 state 衔接与下游 prompt 块生成。
"""
from __future__ import annotations

import json
import uuid as _uuid
from typing import Any

from schemas.state import CreationState

from knowledge.story_variables import build_genre_constraints_prompt_for_brainwave


def brainwave_engine_from_state(state: CreationState) -> dict[str, Any]:
    raw = state.get("brainwave_engine")
    return dict(raw) if isinstance(raw, dict) else {}


def brainwave_prompt_block(state: CreationState, *, max_chars: int = 14000) -> str:
    """供 iceberg / world_build / protagonist_card / story_arc 注入的配方摘要。"""
    be = brainwave_engine_from_state(state)
    if not be:
        return ""
    try:
        blob = json.dumps(be, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        blob = str(be)
    if len(blob) > max_chars:
        blob = blob[: max_chars - 20] + "\n…（截断）"
    return (
        "\n\n## 【脑洞引擎配方（DeepNovel v4.3 补丁 E）】\n"
        "下列 JSON 须与当前步骤输出自洽；开篇碰撞须呼应 opening_crisis；"
        "针对度/感情度可参考 downstream_instructions.for_iceberg_deduction。\n"
        f"{blob}\n"
    )


def world_build_brainwave_suffix(state: CreationState) -> str:
    be = brainwave_engine_from_state(state)
    genre_req = (state.get("genre_request") or "").strip() or "通用网文"
    genre_iron = build_genre_constraints_prompt_for_brainwave(genre_req)
    if not be:
        if not genre_iron.strip():
            return ""
        return (
            "\n\n## 【脑洞引擎 → 世界设定侧重（补丁 E）】\n"
            "【以下题材铁律高于 inferred_world_seeds 与下行说明；冲突时以铁律为准】\n"
            f"{genre_iron}"
        )
    ds = be.get("downstream_instructions") if isinstance(be.get("downstream_instructions"), dict) else {}
    fw = str(ds.get("for_world_build") or "").strip()
    seeds = be.get("inferred_world_seeds")
    if not fw and not (isinstance(seeds, list) and seeds):
        blob = brainwave_prompt_block(state, max_chars=6000)
        if not blob and not genre_iron.strip():
            return ""
        head = (
            "\n\n## 【脑洞引擎 → 世界设定侧重（补丁 E）】\n"
            "【以下题材铁律高于配方 JSON；冲突时以铁律为准】\n"
            f"{genre_iron}"
        )
        return head + blob if blob else head
    parts = [
        "\n\n## 【脑洞引擎 → 世界设定侧重（补丁 E）】\n",
        "【以下题材铁律高于 inferred_world_seeds 与下行说明；冲突时以铁律为准】\n",
        genre_iron,
    ]
    if fw:
        parts.append(f"{fw}\n")
    if isinstance(seeds, list) and seeds:
        parts.append("inferred_world_seeds：\n")
        parts.append(json.dumps(seeds, ensure_ascii=False) + "\n")
    bf = be.get("brainwave_formula") if isinstance(be.get("brainwave_formula"), dict) else {}
    sv = bf.get("survival_logic") if isinstance(bf.get("survival_logic"), dict) else {}
    if sv:
        parts.append("\n【补丁 J · survival_logic】谋生逻辑影响灰市/委托/职场案源等可写空间，请在势力与规则设计中留出口：\n")
        parts.append(json.dumps(sv, ensure_ascii=False, indent=2) + "\n")
    return "".join(parts)


def protagonist_card_brainwave_suffix(state: CreationState) -> str:
    be = brainwave_engine_from_state(state)
    if not be:
        return ""
    ds = be.get("downstream_instructions") if isinstance(be.get("downstream_instructions"), dict) else {}
    fp = str(ds.get("for_protagonist_card") or "").strip()
    bf = be.get("brainwave_formula") if isinstance(be.get("brainwave_formula"), dict) else {}
    aa = bf.get("asymmetric_advantage") if isinstance(bf.get("asymmetric_advantage"), dict) else {}
    sl = bf.get("survival_logic") if isinstance(bf.get("survival_logic"), dict) else {}
    if not fp and not aa and not sl:
        return brainwave_prompt_block(state, max_chars=8000)
    chunk: dict[str, Any] = {}
    if fp:
        chunk["for_protagonist_card"] = fp
    if aa:
        chunk["asymmetric_advantage"] = aa
    pm = bf.get("pain_mapping") if isinstance(bf.get("pain_mapping"), dict) else {}
    if pm:
        chunk["pain_mapping"] = pm
    if sl:
        chunk["survival_logic"] = sl
    return (
        "\n\n## 【脑洞引擎 → 主角人物卡侧重（补丁 E / J）】\n"
        "survival_logic 须落实到 independent_agenda 的日常主动行动与谋生方式。\n"
        + json.dumps(chunk, ensure_ascii=False, indent=2)
        + "\n"
    )


def story_arc_brainwave_suffix(state: CreationState) -> str:
    be = brainwave_engine_from_state(state)
    if not be:
        return ""
    bf = be.get("brainwave_formula") if isinstance(be.get("brainwave_formula"), dict) else {}
    ep = bf.get("escalation_path")
    ds = be.get("downstream_instructions") if isinstance(be.get("downstream_instructions"), dict) else {}
    fap = str(ds.get("for_arc_planning") or "").strip()
    fbc = str(bf.get("final_boss_concept") or "").strip()
    sv = bf.get("survival_logic") if isinstance(bf.get("survival_logic"), dict) else {}
    if not isinstance(ep, list) and not fap and not fbc and not sv:
        return brainwave_prompt_block(state, max_chars=8000)
    out: dict[str, Any] = {}
    if isinstance(ep, list):
        out["escalation_path"] = ep
    if fap:
        out["for_arc_planning"] = fap
    if fbc:
        out["final_boss_concept"] = fbc
    if sv:
        out["survival_logic"] = sv
    return (
        "\n\n## 【脑洞引擎 → 分卷规划格局参考（补丁 E）】\n"
        + json.dumps(out, ensure_ascii=False, indent=2)
        + "\n"
    )


def _first_quest_text_from_brainwave(be: dict[str, Any]) -> str:
    bf = be.get("brainwave_formula") if isinstance(be.get("brainwave_formula"), dict) else {}
    oc = bf.get("opening_crisis") if isinstance(bf.get("opening_crisis"), dict) else {}
    t1 = str(oc.get("first_quest") or "").strip()
    if t1:
        return t1
    ds = be.get("downstream_instructions") if isinstance(be.get("downstream_instructions"), dict) else {}
    return str(ds.get("for_quest_stack") or "").strip()


def quest_dict_from_brainwave(be: dict[str, Any]) -> dict[str, Any] | None:
    text = _first_quest_text_from_brainwave(be)
    if not text:
        return None
    bf = be.get("brainwave_formula") if isinstance(be.get("brainwave_formula"), dict) else {}
    oc = bf.get("opening_crisis") if isinstance(bf.get("opening_crisis"), dict) else {}
    scene = str(oc.get("scene") or "").strip()[:200]
    qid = f"AQ_BW_{_uuid.uuid4().hex[:6].upper()}"
    origin = "brainwave_formula（补丁E·opening_crisis / downstream_instructions）"
    if scene:
        origin = f"brainwave_engine·opening_crisis（{scene}）"
    return {
        "quest_id": qid,
        "quest_name": text[:60],
        "quest_origin": origin[:200],
        "urgency_level": "critical",
        "deadline_note": None,
        "current_sub_goal": text[:200],
        "layer": "immediate",
        "completion_condition": text[:220] if len(text) > 60 else "完成开局 immediate 任务（见脑洞引擎 first_quest）",
        "failure_condition": None,
        "evolution_on_completion": None,
        "evolution_on_failure": None,
        "status": "active",
        "planted_chapter": "brainwave_engine",
        "emotional_weight": str(oc.get("discomfort_type") or "")[:120],
    }


def strip_brainwave_and_collision_immediate(stack: list) -> list:
    """去掉将由 PROMPT4 或脑洞引擎重新写入的 immediate 开局任务，避免重复。"""
    out: list = []
    for q in stack:
        if not isinstance(q, dict):
            out.append(q)
            continue
        if q.get("layer") == "immediate" and q.get("planted_chapter") in (
            "opening_collision",
            "brainwave_engine",
        ):
            continue
        out.append(q)
    return out
