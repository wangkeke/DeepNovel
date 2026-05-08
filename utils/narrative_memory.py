"""
补丁 I：角色叙事流 — 组装 POV 认知面板、流字段规范化、与主角恩怨相关的长记忆过滤。
"""
from __future__ import annotations

from typing import Any, Mapping

from prompts.creation.narrative_memory import POV_MEMORY_PANEL_TEMPLATE


def ensure_memory_streams(card: dict | None) -> dict:
    """保证人物卡 dict 含 short_term_stream / long_term_stream（append-only 列表）。"""
    c = dict(card) if isinstance(card, dict) else {}
    st = c.get("short_term_stream")
    lt = c.get("long_term_stream")
    if not isinstance(st, list):
        c["short_term_stream"] = []
    if not isinstance(lt, list):
        c["long_term_stream"] = []
    return c


def format_long_term_snippet_for_tick(card: dict, n: int = 5) -> str:
    """World Tick 轨道 B：取最近 n 条 long_term 供性格驱动推演（多行展示）。"""
    lt = list(ensure_memory_streams(card).get("long_term_stream") or [])
    tail = [str(x).strip() for x in lt[-n:] if str(x).strip()]
    if not tail:
        return "（尚无长期记忆条目）"
    return "\n".join(f"· {x}" for x in tail)


def format_character_personality_for_tick(card: dict) -> str:
    """从 bible/Entity 卡抽取性格与智谋相关字段，供 Tick 离线叙事注入。"""
    c = ensure_memory_streams(card)
    parts: list[str] = []
    traits = c.get("innate_traits")
    if isinstance(traits, list) and traits:
        parts.append("先天底色：" + "；".join(str(t) for t in traits[:8]))
    mc = c.get("mental_core")
    if isinstance(mc, dict) and mc:
        bits = [f"{k}={v}" for k, v in list(mc.items())[:12]]
        if bits:
            parts.append("mental_core：" + "，".join(bits))
    ap = str(c.get("appearance") or "").strip()
    if ap:
        parts.append("外貌要点：" + ap[:200])
    bg = str(c.get("background_summary") or "").strip()
    if bg:
        parts.append("背景摘要：" + bg[:220])
    note = str(c.get("chapter_behavior_note") or "").strip()
    if note:
        parts.append("近期行径旁注：" + note[:160])
    return "；".join(parts) if parts else "（档案未载明性格细节：按议程与身份常识推演）"


def format_character_faction_goals_for_tick(
    card: dict,
    character_name: str,
    state: Mapping[str, Any],
) -> str:
    """阵营、角色位、对主角立场；若与 core_cast 宿敌同名则加注宿敌动机线索。"""
    c = ensure_memory_streams(card)
    nm = (character_name or "").strip()
    parts: list[str] = []
    role = str(c.get("current_role") or "").strip()
    stance = str(c.get("stance_to_protagonist") or "").strip()
    if role:
        parts.append(f"当前角色位：{role}")
    if stance:
        parts.append(f"对主角立场：{stance}")
    cc = state.get("core_cast") if isinstance(state.get("core_cast"), dict) else {}
    uv = cc.get("ultimate_villain") if isinstance(cc.get("ultimate_villain"), dict) else {}
    if uv and str(uv.get("name") or "").strip() == nm:
        ident = str(uv.get("identity") or "").strip()
        parts.append("核心班底登记：全书宿敌位" + (f"（{ident[:40]}）" if ident else ""))
        mot = str(uv.get("core_motivation") or "").strip()
        if mot:
            parts.append("宿敌动机线索：" + mot[:160])
    return "；".join(parts) if parts else "（阵营与目标未登记：仅依据议程与常识推演）"


def _fmt_stream_lines(lines: list[Any], max_items: int | None = None) -> str:
    out: list[str] = []
    seq = lines[-max_items:] if max_items and len(lines) > max_items else lines
    for x in seq:
        s = str(x).strip()
        if s:
            out.append(s)
    return "\n".join(out) if out else "（无）"


def filter_opposing_long_term(
    long_term: list[Any],
    protagonist_name: str,
    max_items: int = 6,
) -> list[str]:
    """
    仅保留与主角恩怨强相关的长记忆条目（启发式：含主角名或常见对立语义）。
    更久远的生平事迹过滤掉，防 Token 稀释。
    """
    pn = (protagonist_name or "").strip()
    keys = ("仇", "恨", "敌", "报复", "除掉", "杀", "利用", "棋", "陷阱", "盯上", "布局")
    picked: list[str] = []
    for x in long_term or []:
        s = str(x).strip()
        if not s:
            continue
        if pn and pn in s:
            picked.append(s)
            continue
        if any(k in s for k in keys):
            picked.append(s)
    # 取时间上最近的若干条
    return picked[-max_items:] if picked else []


def pick_opposing_and_surprise(
    state: Mapping[str, Any],
    main_pov: str,
) -> tuple[str, str, str]:
    """
    返回 (对台戏角色名, 突发介入角色名)。
    对台：core_cast 宿敌名；突发：world_tick 第一条 agenda 中非主角且非对台之名。
    """
    main = (main_pov or "").strip() or "主角"
    opposing = ""
    cc = state.get("core_cast") or {}
    if isinstance(cc, dict):
        uv = cc.get("ultimate_villain") or {}
        if isinstance(uv, dict):
            opposing = str(uv.get("name") or "").strip()

    surprise = ""
    tick = state.get("current_world_tick") or {}
    agendas = tick.get("independent_agendas") or [] if isinstance(tick, dict) else []
    if isinstance(agendas, list):
        for ag in agendas:
            if not isinstance(ag, dict):
                continue
            nm = str(ag.get("character_or_faction") or "").strip()
            if not nm or nm == main or nm == opposing:
                continue
            surprise = nm
            break

    if not opposing:
        opposing = "（未定名宿敌）"
    if not surprise:
        surprise = "（无）"
    return opposing, surprise, main


def build_narrative_memory_pov_section(state: Mapping[str, Any]) -> str:
    """
    按补丁 I §五 注入过滤策略组装 POV 面板；无 bible 人物数据时返回空串。
    """
    bible = state.get("bible") or {}
    chars = bible.get("characters") if isinstance(bible, dict) else None
    if not isinstance(chars, dict) or not chars:
        return ""

    path_def = None
    try:
        from utils.path_relay import get_current_v43_path_def

        path_def = get_current_v43_path_def(state)
    except Exception:
        path_def = None

    main_pov = ""
    if isinstance(path_def, dict):
        main_pov = str(path_def.get("pov_character") or "").strip()
    if not main_pov:
        main_pov = str(state.get("protagonist_name") or "").strip() or "主角"

    opposing_label, surprise_label, _ = pick_opposing_and_surprise(state, main_pov)

    mc_card = ensure_memory_streams(chars.get(main_pov) if isinstance(chars.get(main_pov), dict) else {})
    mc_short = _fmt_stream_lines(mc_card.get("short_term_stream") or [])
    mc_long = mc_card.get("long_term_stream") or []
    if isinstance(mc_long, list):
        mc_long_lines = [str(x).strip() for x in mc_long[-5:] if str(x).strip()]
    else:
        mc_long_lines = []
    filtered_mc_long = "\n".join(f"  · {x}" for x in mc_long_lines) if mc_long_lines else "（无）"

    oppo_card = ensure_memory_streams(
        chars.get(opposing_label) if isinstance(chars.get(opposing_label), dict) else {}
    )
    if opposing_label not in chars or not isinstance(chars.get(opposing_label), dict):
        oppo_card = {"short_term_stream": [], "long_term_stream": []}
    pn = str(state.get("protagonist_name") or "").strip()
    oppo_long_filtered = filter_opposing_long_term(
        oppo_card.get("long_term_stream") or [], pn, max_items=6,
    )
    filtered_oppo_long = (
        "\n".join(f"  · {x}" for x in oppo_long_filtered) if oppo_long_filtered else "（无）"
    )
    oppo_short = _fmt_stream_lines(oppo_card.get("short_term_stream") or [])

    sur_card = ensure_memory_streams(
        chars.get(surprise_label) if isinstance(chars.get(surprise_label), dict) else {}
    )
    if surprise_label not in chars or surprise_label == "（无）":
        surprise_long = "（无）"
    else:
        sur_lt = sur_card.get("long_term_stream") or []
        if isinstance(sur_lt, list) and sur_lt:
            surprise_long = "\n".join(f"  · {str(x).strip()}" for x in sur_lt[-3:] if str(x).strip())
        else:
            surprise_long = "（无）"

    return POV_MEMORY_PANEL_TEMPLATE.format(
        main_pov_character=main_pov,
        filtered_mc_long_term=filtered_mc_long,
        mc_short_term=mc_short,
        opposing_character=opposing_label,
        filtered_oppo_long_term=filtered_oppo_long,
        oppo_short_term=oppo_short,
        surprise_character=surprise_label,
        surprise_long_term=surprise_long,
    ).strip()


def parse_inner_stream_batch(raw: dict | Any) -> list[dict[str, str]]:
    """解析 path_state / inner LLM 返回的 slices。"""
    if not isinstance(raw, dict):
        return []
    slices = raw.get("slices") or raw.get("inner_narrative_slices") or []
    if not isinstance(slices, list):
        return []
    out: list[dict[str, str]] = []
    for it in slices:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("character_name") or it.get("name") or "").strip()
        sl = str(it.get("inner_slice") or it.get("slice") or "").strip()
        if nm and sl:
            out.append({"character_name": nm, "inner_slice": sl})
    return out
