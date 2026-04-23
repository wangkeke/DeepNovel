"""
CLI 逐字段编辑主角卡：字段名与 docs/DeepNovel_重构文档_完整版.md PROMPT 3 及 prompts/creation/world_build.py 模板一致。
编辑结束后调用 normalize_protagonist_card_for_state，保证与引擎层对齐。
"""
from __future__ import annotations

import copy
import json
from typing import Any

from utils.protagonist_card_normalize import normalize_protagonist_card_for_state


def _pv(v: Any, n: int = 120) -> str:
    s = "" if v is None else str(v)
    s = " ".join(s.split())
    return (s[:n] + "…") if len(s) > n else s


def _inp(label: str, cur: Any) -> str:
    return input(f"  {label} [原值: {_pv(cur)}]：").strip()


def _parse_json_object(line: str) -> dict[str, Any] | None:
    line = line.strip()
    if not line:
        return None
    try:
        raw = json.loads(line)
        return raw if isinstance(raw, dict) else None
    except json.JSONDecodeError:
        return None


def _comma_list(s: str) -> list[str]:
    return [x.strip() for x in s.replace("，", ",").split(",") if x.strip()]


def edit_protagonist_card_interactive(card: dict[str, Any], *, console: Any) -> dict[str, Any]:
    c = copy.deepcopy(card)
    console.print("\n[dim]──────── PROMPT 3 · 标识与称谓（回车保留）────────[/dim]")

    v = _inp("character_id", c.get("character_id"))
    if v:
        c["character_id"] = v

    v = _inp("name（同步 standard_name）", c.get("name") or c.get("standard_name"))
    if v:
        c["name"] = v
        c["standard_name"] = v

    al = c.get("aliases")
    al_str = "，".join(str(x) for x in al) if isinstance(al, list) else str(al or "")
    v = _inp("aliases（英文逗号或中文逗号分隔）", al_str)
    if v:
        c["aliases"] = _comma_list(v)

    console.print("\n[dim]──────── 外在叙事（模板必填）────────[/dim]")
    for key, lab in [
        ("appearance", "appearance（客观外貌）"),
        ("persona", "persona（外在假面/保护色）"),
        ("reverse_scale", "reverse_scale（绝对逆鳞）"),
        ("core_motif", "core_motif（叙事核心底色，可空则归一化时从欲求/恐惧推导）"),
        ("background_summary", "background_summary（出身与关键经历）"),
    ]:
        vv = _inp(lab, c.get(key))
        if vv:
            c[key] = vv

    sh = c.get("signature_habits")
    if not isinstance(sh, list):
        sh = [str(sh)] if sh else []
    sh = [str(x).strip() for x in sh][:2]
    for i in range(2):
        cur = sh[i] if i < len(sh) else ""
        nv = _inp(f"signature_habits[{i}]", cur)
        if nv:
            if i < len(sh):
                sh[i] = nv
            else:
                sh.append(nv)
    c["signature_habits"] = [x for x in sh[:2] if x]

    console.print("\n[dim]──────── innate_traits（对象）────────[/dim]")
    inn_d: dict[str, Any] | None = None
    if isinstance(c.get("innate_traits_detail"), dict):
        inn_d = copy.deepcopy(c["innate_traits_detail"])
    elif isinstance(c.get("innate_traits"), dict):
        inn_d = copy.deepcopy(c["innate_traits"])
    if inn_d is None:
        inn_d = {"personality": [], "talent_physical": [], "core_desire": "", "core_fear": ""}

    pers = inn_d.get("personality") or []
    if not isinstance(pers, list):
        pers = [str(pers)] if pers else []
    pt = _inp("innate_traits.personality（逗号分隔）", "，".join(str(x) for x in pers))
    if pt:
        inn_d["personality"] = _comma_list(pt)

    tal = inn_d.get("talent_physical") or []
    if not isinstance(tal, list):
        tal = [str(tal)] if tal else []
    tt = _inp("innate_traits.talent_physical（逗号分隔）", "，".join(str(x) for x in tal))
    if tt:
        inn_d["talent_physical"] = _comma_list(tt)

    for k, lab in [
        ("core_desire", "innate_traits.core_desire"),
        ("core_fear", "innate_traits.core_fear"),
    ]:
        vv = _inp(lab, inn_d.get(k, ""))
        if vv:
            inn_d[k] = vv
    c["innate_traits"] = inn_d

    console.print("\n[dim]──────── mental_core（文档叙述层，入库存 mental_core_literary）────────[/dim]")
    mcl = c.get("mental_core_literary") if isinstance(c.get("mental_core_literary"), dict) else {}
    mcl = dict(mcl)
    for k, lab in [
        ("intellect", "intellect（心智/阅历叙述）"),
        ("emotional_intelligence", "emotional_intelligence（情商叙述）"),
        ("strategic_thinking", "strategic_thinking（缜密叙述）"),
        ("endurance", "endurance（隐忍叙述）"),
        ("emotional_collapse_behavior", "emotional_collapse_behavior（阈值归零行为）"),
    ]:
        vv = _inp(lab, mcl.get(k, ""))
        if vv:
            mcl[k] = vv

    ec_lit = mcl.get("emotional_capacity")
    ev = _inp("mental_core.emotional_capacity（叙述用阈值 0-100，整数）", ec_lit if isinstance(ec_lit, (int, float)) else "")
    if ev:
        try:
            mcl["emotional_capacity"] = max(0, min(100, int(round(float(ev)))))
        except (TypeError, ValueError):
            pass

    tr = mcl.get("emotional_drain_triggers") or []
    if not isinstance(tr, list):
        tr = [str(tr)] if tr else []
    tv = _inp("emotional_drain_triggers（逗号分隔）", "，".join(str(x) for x in tr))
    if tv:
        mcl["emotional_drain_triggers"] = _comma_list(tv)
    c["mental_core_literary"] = mcl

    console.print("\n[dim]──────── mental_core_panel（引擎五维整数 0-100；入库合并为 mental_core）────────[/dim]")
    mc_cur = c.get("mental_core") if isinstance(c.get("mental_core"), dict) else {}
    panel_keys = ("intelligence", "eq", "meticulousness", "emotional_capacity", "forbearance")
    for k in panel_keys:
        try:
            dv = int(mc_cur.get(k, 50))
        except (TypeError, ValueError):
            dv = 50
        dv = max(0, min(100, dv))
        iv = _inp(f"mental_core_panel.{k}", str(dv))
        if iv:
            try:
                mc_cur[k] = max(0, min(100, int(round(float(iv)))))
            except (TypeError, ValueError):
                mc_cur[k] = dv
    for k in panel_keys:
        mc_cur.setdefault(k, 50)
    c["mental_core_panel"] = {k: mc_cur[k] for k in panel_keys}

    console.print("\n[dim]──────── maturity_level（对象）────────[/dim]")
    md: dict[str, Any] | None = None
    if isinstance(c.get("maturity_level_detail"), dict):
        md = copy.deepcopy(c["maturity_level_detail"])
    elif isinstance(c.get("maturity_level"), dict):
        md = copy.deepcopy(c["maturity_level"])
    if md is None:
        md = {"current_score": "", "illusions_held": [], "growth_trajectory": ""}
    vv = _inp("maturity_level.current_score（低/中低/中/中高/高）", md.get("current_score", ""))
    if vv:
        md["current_score"] = vv
    ill = md.get("illusions_held") or []
    if not isinstance(ill, list):
        ill = [str(ill)] if ill else []
    iv = _inp("maturity_level.illusions_held（逗号分隔）", "，".join(str(x) for x in ill))
    if iv:
        md["illusions_held"] = _comma_list(iv)
    gv = _inp("maturity_level.growth_trajectory", md.get("growth_trajectory", ""))
    if gv:
        md["growth_trajectory"] = gv
    c["maturity_level"] = md

    console.print("\n[dim]──────── 世界与阵营（PROMPT 3）────────[/dim]")
    for key, lab in [
        ("world_position", "world_position"),
        ("independent_agenda", "independent_agenda"),
    ]:
        vv = _inp(lab, c.get(key, ""))
        if vv:
            c[key] = vv

    console.print("  faction_relationship：输入一行 JSON 对象（例 {\"faction_a\":\"关系\"}），回车保留")
    fr_cur = json.dumps(c.get("faction_relationship") or {}, ensure_ascii=False) if isinstance(
        c.get("faction_relationship"), dict
    ) else "{}"
    fj = input(f"  [{_pv(fr_cur, 160)}]：").strip()
    if fj:
        parsed = _parse_json_object(fj)
        if parsed is not None:
            c["faction_relationship"] = parsed
        else:
            console.print("  [yellow]faction_relationship JSON 无法解析，已保留原值[/yellow]")

    console.print("\n[dim]──────── 人性逻辑与状态（模板扩展）────────[/dim]")
    kde = c.get("key_life_events") or []
    if not isinstance(kde, list):
        kde = []
    kv = _inp("key_life_events（逗号分隔）", "，".join(str(x) for x in kde))
    if kv:
        c["key_life_events"] = _comma_list(kv)

    for key, lab in [
        ("current_emotional_drain", "current_emotional_drain（当前情绪透支 0-100 整数）"),
    ]:
        vv = _inp(lab, c.get(key, ""))
        if vv:
            try:
                c[key] = max(0, min(100, int(round(float(vv)))))
            except (TypeError, ValueError):
                pass

    dl = c.get("dominant_logics") or []
    if not isinstance(dl, list):
        dl = []
    dv = _inp("dominant_logics（逗号分隔）", "，".join(str(x) for x in dl))
    if dv:
        c["dominant_logics"] = _comma_list(dv)

    lo = c.get("logic_origins") or []
    if not isinstance(lo, list):
        lo = []
    lov = _inp("logic_origins（逗号分隔，与 dominant_logics 顺位对应时可）", "，".join(str(x) for x in lo))
    if lov:
        c["logic_origins"] = _comma_list(lov)

    console.print("  logic_switch_conditions：一行 JSON 数组（或回车保留）")
    lsc = c.get("logic_switch_conditions")
    lsc_s = json.dumps(lsc, ensure_ascii=False) if isinstance(lsc, list) else "[]"
    lsc_in = input(f"  [{_pv(lsc_s, 120)}]：").strip()
    if lsc_in:
        try:
            raw = json.loads(lsc_in)
            if isinstance(raw, list):
                c["logic_switch_conditions"] = raw
        except json.JSONDecodeError:
            console.print("  [yellow]logic_switch_conditions 非法，已跳过[/yellow]")

    console.print("  traits：一行 JSON 数组（或回车保留）")
    trs = c.get("traits")
    trs_s = json.dumps(trs, ensure_ascii=False) if isinstance(trs, list) else "[]"
    tr_in = input(f"  [{_pv(trs_s, 120)}]：").strip()
    if tr_in:
        try:
            raw = json.loads(tr_in)
            if isinstance(raw, list):
                c["traits"] = raw
        except json.JSONDecodeError:
            console.print("  [yellow]traits 非法，已跳过[/yellow]")

    console.print("  trait_interactions：一行 JSON 对象（或回车保留）")
    ti = c.get("trait_interactions")
    ti_s = json.dumps(ti, ensure_ascii=False) if isinstance(ti, dict) else "{}"
    ti_in = input(f"  [{_pv(ti_s, 120)}]：").strip()
    if ti_in:
        parsed = _parse_json_object(ti_in)
        if parsed is not None:
            pr = parsed.get("preset", [])
            lr = parsed.get("learned", [])
            c["trait_interactions"] = {
                "preset": pr if isinstance(pr, list) else [],
                "learned": lr if isinstance(lr, list) else [],
            }

    normalize_protagonist_card_for_state(c)
    return c
