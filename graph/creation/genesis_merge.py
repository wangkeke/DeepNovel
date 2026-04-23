"""
冰山反推结果 → synopsis / world_setting / 主角卡 形状对齐（全书班底由写作期 bible_update 生长）。
"""
from __future__ import annotations
import json
from typing import Any

from knowledge.story_variables import map_genre_bucket

_BUCKET_LEXICON: dict[str, list[str]] = {
    "古代权谋": ["generic", "palace"],
    "玄幻修仙": ["generic", "xianxia"],
    "都市职场": ["generic", "urban_business"],
    "重生穿越": ["generic", "game_system"],
    "民间灵异": ["generic", "xianxia"],
    "盗墓探险": ["generic", "historical"],
    "悬疑推理": ["generic", "romance"],
    "末日科幻": ["generic", "scifi"],
    "恐怖灵异": ["generic", "xianxia"],
    "民国年代": ["generic", "historical"],
    "霸总": ["generic", "romance", "urban_business"],
    "校园": ["generic", "romance"],
    "生活伦理": ["generic", "romance"],
    "宫斗权谋": ["generic", "palace"],
    "修仙玄幻": ["generic", "xianxia"],
    "都市现代": ["generic", "urban_business"],
    "通用": ["generic"],
}


def genre_lexicon_for_bucket(bucket: str) -> list[str]:
    return list(_BUCKET_LEXICON.get(bucket) or ["generic"])


def _num(v: Any, default: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _txt(v: Any, default: str = "") -> str:
    """LLM JSON 可能把动机等写成数字；统一成可 .strip 的字符串。"""
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return default
    s = str(v).strip()
    return s if s else default


def world_setting_from_iceberg(world_raw: dict, genre_request: str) -> dict:
    """冰山 world JSON → world_build_node 期望的五键结构。"""
    if not isinstance(world_raw, dict):
        world_raw = {}
    rules = world_raw.get("world_rules") or []
    if not isinstance(rules, list):
        rules = [str(rules)] if rules else []
    loc = _txt(world_raw.get("local_environment"))
    macro = _txt(world_raw.get("macro_world_hierarchy"))
    basic_parts = []
    if rules:
        basic_parts.append("\n".join(str(r) for r in rules))
    if loc:
        basic_parts.append(f"局部环境：{loc}")
    if macro:
        basic_parts.append(f"宏观位阶：{macro}")
    basic_rules = "\n\n".join(basic_parts) if basic_parts else loc or macro or "（由开篇有机延展的世界规则待补全）"

    ps = world_raw.get("power_structure") or []
    if not isinstance(ps, list):
        ps = [str(ps)] if ps else []
    geo: list[str] = []
    if loc:
        geo.append(loc)
    if macro:
        geo.append(macro)
    uniq = world_raw.get("unique_settings") or []
    if not isinstance(uniq, list):
        uniq = [str(uniq)] if uniq else []

    return {
        "basic_rules": basic_rules,
        "power_structure": [str(x) for x in ps if str(x).strip()],
        "geography": geo,
        "world_taboos": [],
        "unique_settings": [str(x) for x in uniq if str(x).strip()],
    }


def protagonist_name_from_cast_local(cast_raw: dict) -> str:
    """班底 JSON 中 protagonist_side 的姓名（冰山阶段1未单独返回 protagonist_card 时用）。"""
    if not isinstance(cast_raw, dict):
        return ""
    _bad = frozenset({"主角", "主人公", "男主", "女主", ""})
    for c in cast_raw.get("local_cast") or []:
        if not isinstance(c, dict):
            continue
        if str(c.get("role", "")).strip() != "protagonist_side":
            continue
        n = _txt(c.get("name"))
        if n and n not in _bad:
            return n
    return ""


def synopsis_merge(
    stage2: dict,
    opening_text: str,
    variables: dict,
    genre_request: str,
    iceberg_prompt4: dict | None = None,
) -> dict:
    """Stage2 宏观 JSON + 开篇/变量 → 与 synopsis_node 兼容的一屏 dict（含扩展字段）。"""
    if not isinstance(stage2, dict):
        stage2 = {}
    bucket = (variables or {}).get("genre_bucket") or map_genre_bucket(genre_request)
    lex = stage2.get("genre_lexicon_keys")
    if not isinstance(lex, list) or not lex:
        lex = genre_lexicon_for_bucket(bucket)

    fam = _txt(stage2.get("family_emotion_line")) or "无"
    rom = _txt(stage2.get("romance_emotion_line")) or "无"
    if fam in ("无", "") and rom in ("无", ""):
        fam = "与开篇强相关的亲属或拟亲属张力（待你在确认页细化）"

    base = {
        "title": _txt(stage2.get("title"), "未命名"),
        "world": _txt(stage2.get("world")),
        "protagonist": _txt(stage2.get("protagonist")),
        "core_conflict": _txt(stage2.get("core_conflict")),
        "direction": _txt(stage2.get("direction")),
        "family_emotion_line": fam,
        "romance_emotion_line": rom,
        "genre_lexicon_keys": lex[:3] if lex else ["generic"],
        "opening_seed_text": _txt(opening_text),
        "genre_variable_snapshot": json.dumps(variables or {}, ensure_ascii=False),
    }
    for key in ("core_hook", "volume_1_goal", "escalation_path", "ultimate_goal"):
        v = stage2.get(key)
        if v is not None and str(v).strip():
            base[key] = str(v).strip()
    if isinstance(iceberg_prompt4, dict) and iceberg_prompt4:
        base["iceberg_prompt4"] = iceberg_prompt4
    return base


def protagonist_card_from_iceberg(pc: dict, existing_card: dict | None = None) -> dict:
    """
    冰山 protagonist_card → protagonist_card_node 可用草稿。
    策略：以 existing_card（已在 protagonist_card_node 中建立的完整 PROMPT 3 卡）为基础，
    用冰山侧新增/补充的字段 merge 进去；不窄映射替换，不丢 PROMPT 3 全字段。
    若无 existing_card，则从冰山 pc 中尽量填充所有 PROMPT 3 字段。
    """
    if not isinstance(pc, dict):
        pc = {}
    if isinstance(existing_card, dict) and existing_card:
        import copy
        card = copy.deepcopy(existing_card)
        # 只补充 existing_card 里空缺的字段；以及更新冰山侧独有字段
        ice_only_keys = (
            "current_mental_state", "mental_growth_path", "immediate_motive", "destiny_seed",
        )
        for k in ice_only_keys:
            v = _txt(pc.get(k))
            if v and not (card.get(k) or "").strip():
                card[k] = v
        # 逆鳞：若 existing_card 有则保留，否则用冰山
        if not (card.get("reverse_scale") or "").strip():
            rs = _txt(pc.get("reverse_scale"))
            if rs:
                card["reverse_scale"] = rs
        # 若冰山提供了更多 key_life_events 且原卡为空
        if not card.get("key_life_events"):
            im_m = _txt(pc.get("immediate_motive"))
            dest = _txt(pc.get("destiny_seed"))
            kle = [x for x in [im_m, dest] if x][:2]
            if kle:
                card["key_life_events"] = kle
        return card

    # ── 无 existing_card：从冰山 pc 尽量构造完整 PROMPT 3 草稿 ──
    habits: list[str] = []
    for src in (pc.get("micro_reactions"), pc.get("traits_display"), pc.get("signature_habits")):
        if not isinstance(src, list):
            continue
        for t in src:
            s = str(t).strip()
            if s and len(habits) < 8:
                habits.append(s[:160])
            if len(habits) >= 8:
                break
        if len(habits) >= 8:
            break
    logics = pc.get("dominant_logics") or []
    if not isinstance(logics, list):
        logics = [str(logics)]
    motif = "；".join(str(x) for x in logics if str(x).strip())[:400]
    appearance = _txt(pc.get("appearance"))
    im_m = _txt(pc.get("immediate_motive"))
    innate_raw = pc.get("innate_traits")
    if isinstance(innate_raw, dict):
        innate_d = innate_raw
        innate = []
        for k in ("personality", "talent_physical"):
            for x in (innate_raw.get(k) or []):
                s = str(x).strip()
                if s:
                    innate.append(s)
        innate = innate[:12]
    elif isinstance(innate_raw, list):
        innate_d = {}
        innate = [str(x).strip() for x in innate_raw if str(x).strip()][:12]
    else:
        innate_d = {}
        innate = []
    mc_raw = pc.get("mental_core") if isinstance(pc.get("mental_core"), dict) else {}
    maturity = _txt(pc.get("current_maturity")) or _txt(pc.get("maturity_level"))
    drain = _num(pc.get("current_emotional_drain"), 0)
    drain = max(0, min(100, drain))
    persona_raw = (
        _txt(pc.get("persona"))
        or _txt(pc.get("external_mask"))
        or _txt(pc.get("social_mask"))
    )
    persona = persona_raw or ("谨慎克制，先观察局势再表态" if appearance else "外在姿态待开篇细化")

    card: dict = {
        "character_id":          _txt(pc.get("character_id"), ""),
        "name":                  _txt(pc.get("name")) or _txt(pc.get("standard_name"), "主角"),
        "standard_name":         _txt(pc.get("standard_name"), "主角") or "主角",
        "aliases":               list(pc.get("aliases") or []),
        "appearance":            appearance,
        "persona":               persona[:300],
        "signature_habits":      habits if habits else ["遇险时先观察再动", "压力下话更少"],
        "reverse_scale":         _txt(pc.get("reverse_scale"), ""),
        "innate_traits":         innate,
        "innate_traits_detail":  innate_d if innate_d else {},
        "mental_core":           mc_raw,
        "current_maturity":      maturity,
        "maturity_level":        maturity,
        "current_emotional_drain": drain,
        "core_motif":            motif or (im_m[:200] if im_m else "隐忍蓄力"),
        "background_summary":    _txt(pc.get("background_summary"), ""),
        "key_life_events":       [],
        "dominant_logics":       [str(x) for x in logics if str(x).strip()][:4],
        "logic_origins":         [],
        "logic_switch_conditions": [],
        "world_position":        _txt(pc.get("world_position"), ""),
        "independent_agenda":    _txt(pc.get("independent_agenda"), ""),
        "faction_relationship":  pc.get("faction_relationship") if isinstance(pc.get("faction_relationship"), dict) else {},
        "traits":                list(pc.get("traits") or []),
        "trait_interactions":    pc.get("trait_interactions") if isinstance(pc.get("trait_interactions"), dict) else {"preset": [], "learned": []},
        # 冰山侧独有字段（保留供 expand / bible 参考）
        "current_mental_state":  _txt(pc.get("current_mental_state"), ""),
        "mental_growth_path":    _txt(pc.get("mental_growth_path"), ""),
    }
    dest = _txt(pc.get("destiny_seed"))
    if dest or im_m:
        card["key_life_events"] = [x for x in [im_m, dest] if x][:2]
    return card


def core_cast_from_iceberg(cast_raw: dict, synopsis_title: str = "") -> dict:
    """
    冰山 core_cast JSON → core_cast_gen 同构的 core_cast_draft（含 EBD 占位）。
    """
    if not isinstance(cast_raw, dict):
        cast_raw = {}
    uv_src = cast_raw.get("ultimate_villain") or {}
    if not isinstance(uv_src, dict):
        uv_src = {}
    vol_uv = max(1, _num(uv_src.get("appears_from_volume"), 3))

    ultimate_villain = {
        "name": _txt(uv_src.get("name"), "宿敌") or "宿敌",
        "identity": _txt(uv_src.get("identity"), "立场对立的终极对手"),
        "core_motivation": _txt(uv_src.get("core_motivation")) or "利益与道路的根本冲突",
        "appears_from_volume": vol_uv,
        "human_logic": _txt(uv_src.get("human_logic"), "野心家逻辑"),
        "current_mental_state": _txt(uv_src.get("current_mental_state")),
        "mental_growth_path": _txt(uv_src.get("mental_growth_path")),
        "reverse_scale": _txt(uv_src.get("reverse_scale")),
        "ebd_to_protagonist": _num(uv_src.get("ebd_to_protagonist"), -35),
        "ebd_bond_kind": _txt(uv_src.get("ebd_bond_kind"), "blood_feud"),
        "ebd_type": _txt(uv_src.get("ebd_type"), "结构性敌对·冰山露角"),
        "ebd_note": _txt(uv_src.get("ebd_note"), "开篇已埋对立的宏观延伸"),
    }

    allies: list[dict] = []
    seen: set[str] = set()
    for c in cast_raw.get("local_cast") or []:
        if not isinstance(c, dict):
            continue
        name = _txt(c.get("name"))
        if not name or name in seen:
            continue
        if name == ultimate_villain["name"]:
            continue
        role = _txt(c.get("role"), "neutral")
        if role == "antagonist":
            continue
        seen.add(name)
        has_fam = any(a.get("ebd_bond_kind") == "family" for a in allies)
        has_rom = any(a.get("ebd_bond_kind") == "romance" for a in allies)
        if not has_fam:
            bond = "family"
        elif not has_rom:
            bond = "romance"
        else:
            bond = "friendship"
        ie = _num(c.get("initial_emotional"), 15)
        conn = _txt(
            c.get("connection_to_opening")
            or c.get("relationship_type")
            or c.get("ebd_note")
        )
        allies.append({
            "name": name,
            "identity": _txt(c.get("identity")) or "开篇相关人物",
            "relationship": _txt(c.get("relationship_type") or c.get("connection_to_opening")) or "羁绊待演",
            "appears_from_volume": 0,
            "current_mental_state": _txt(c.get("current_mental_state")),
            "mental_growth_path": _txt(c.get("mental_growth_path")),
            "reverse_scale": _txt(c.get("reverse_scale")),
            "ebd_to_protagonist": max(-100, min(100, ie)),
            "ebd_bond_kind": bond,
            "ebd_type": "开篇现场情感坐标",
            "ebd_note": conn[:200] if conn else "",
        })
        if len(allies) >= 4:
            break

    has_family = any((a.get("ebd_bond_kind") == "family") for a in allies)
    has_romance = any((a.get("ebd_bond_kind") == "romance") for a in allies)
    if allies and not has_family and not has_romance:
        allies[0]["ebd_bond_kind"] = "family"
        allies[0]["ebd_note"] = allies[0].get("ebd_note") or "亲情/拟亲属锚点（自动保底）"
    elif allies and has_family and not has_romance and len(allies) < 2:
        allies.append({
            "name": "未名情感线",
            "identity": "与主角有情感张力的开篇相关者",
            "relationship": "单恋/暧昧/双向未定，待人审细化",
            "appears_from_volume": 0,
            "current_mental_state": "",
            "mental_growth_path": "",
            "reverse_scale": "",
            "ebd_to_protagonist": 12,
            "ebd_bond_kind": "romance",
            "ebd_type": "好感或单方面牵挂",
            "ebd_note": "班底低保：满足 family∨romance 与 synopsis 铁律",
        })

    if not allies:
        allies = [{
            "name": "未命名羁绊",
            "identity": "开篇现场的核心关系人",
            "relationship": "亲属或拟亲属锚点",
            "appears_from_volume": 0,
            "current_mental_state": "",
            "mental_growth_path": "",
            "reverse_scale": "",
            "ebd_to_protagonist": 40,
            "ebd_bond_kind": "family",
            "ebd_type": "庇护与拉扯并存",
            "ebd_note": "请在人审班底时改名补全",
        }]

    shadows = cast_raw.get("macro_shadow_cast") or []
    sp_src: dict[str, Any] = {}
    if isinstance(shadows, list) and shadows and isinstance(shadows[0], dict):
        sp_src = shadows[0]
    if not sp_src:
        sp_src = {
            "name": ultimate_villain["name"],
            "identity": ultimate_villain["identity"],
            "connection_to_opening": "幕后结构与开篇惨事的因果链",
            "appears_from_volume": max(vol_uv, 2),
        }
    vol_sp = max(1, _num(sp_src.get("appears_from_volume"), 2))
    supreme_power = {
        "name": _txt(sp_src.get("name"), "最高掌权者"),
        "identity": _txt(sp_src.get("identity"), "宏观秩序顶端"),
        "stance_to_protagonist": "漠视",
        "appears_from_volume": vol_sp,
        "note": (
            "叙事侧重可参考本卷次；对主角前中期表现为极致随意与傲慢，不当平等对手；"
            "中后期主角撼动其基本盘后才进入真对决。"
        ),
        "ebd_to_protagonist": -12,
        "ebd_bond_kind": "contempt_instrumental",
        "ebd_type": "漠视·高位碾压姿态",
        "ebd_note": "与 FULL_OPPONENT_DOCTRINE 价码一致",
    }

    return {
        "ultimate_villain": ultimate_villain,
        "lifelong_allies": allies,
        "supreme_power": supreme_power,
    }
