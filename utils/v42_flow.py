"""
DeepNovel v4.2 初始化链辅助：在 synopsis 尚未由冰山产出时为世界/冰山提供最小可用输入。
"""
from __future__ import annotations

import json
from typing import Any


def stub_synopsis_for_world_build(state: dict) -> dict:
    """
    world_build 依赖 synopsis 文本；新项目在 idea_forge 之后可能尚无宏观构思，
    用题材与用户锚点生成最小 stub，避免空 JSON 逼模型瞎编。
    """
    syn = state.get("synopsis") if isinstance(state.get("synopsis"), dict) else {}
    if (syn.get("title") or "").strip() and (syn.get("world") or "").strip():
        return dict(syn)

    genre = (state.get("genre_request") or "通用网文").strip() or "通用网文"
    ua = state.get("user_anchors") if isinstance(state.get("user_anchors"), dict) else {}
    prot = ua.get("protagonist") if isinstance(ua.get("protagonist"), dict) else {}
    title = (syn.get("title") or "").strip() or f"《{genre}》未命名"
    world = (syn.get("world") or "").strip() or (
        f"题材：{genre}。具体权力结构、稀缺资源与禁忌将由世界设定卡补全。"
    )
    protagonist = (syn.get("protagonist") or "").strip() or (
        str(prot.get("setting") or "").strip()
        or "主角设定见用户锚点与世界设定卡。"
    )
    core = (syn.get("core_conflict") or "").strip() or "核心矛盾将在冰山反推与分卷规划中收紧。"
    direction = (syn.get("direction") or "").strip() or "走向由后续冰山反推与分卷确定。"
    out = {
        **syn,
        "title": title,
        "world": world,
        "protagonist": protagonist,
        "core_conflict": core,
        "direction": direction,
    }
    return out


def _short_json_blob(data: Any, limit: int) -> str:
    try:
        s = json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        s = str(data)
    if len(s) > limit:
        return s[: limit - 20] + "\n…（截断）"
    return s


def synthetic_opening_anchor_for_iceberg(state: dict) -> str:
    """
    v4.2：冰山在 world_build + protagonist_card 之后运行，此时可无 genesis 开篇正文。
    用已锁定档案代替「开篇实录」，供冰山阶段1/2 的 anchor 引用。
    """
    opening = (state.get("genesis_opening_text") or "").strip()
    if opening:
        return opening

    ws = state.get("world_setting") if isinstance(state.get("world_setting"), dict) else {}
    pc = state.get("protagonist_card") if isinstance(state.get("protagonist_card"), dict) else {}
    gr = (state.get("genre_request") or "").strip() or "通用网文"
    ua = state.get("user_anchors") if isinstance(state.get("user_anchors"), dict) else {}

    return (
        "【v4.2 档案锚点·开篇种子尚未点燃】\n"
        "以下为世界设定卡与主角人物卡已锁定内容；请据此推导世界格局、班底与宏观构思，"
        "勿要求已存在开篇正文。\n\n"
        f"题材：{gr}\n\n"
        "## user_anchors（摘录）\n"
        f"{_short_json_blob(ua, 6000)}\n\n"
        "## world_setting（已确认草案或定稿）\n"
        f"{_short_json_blob(ws, 10000)}\n\n"
        "## protagonist_card（已确认）\n"
        f"{_short_json_blob(pc, 8000)}\n"
    )


def shallow_world_archive(world_setting: dict) -> dict:
    """与文档 world_archive 对齐的轻量镜像，便于下游逐步扩展。"""
    if not isinstance(world_setting, dict):
        return {}
    return {
        "basic_rules": world_setting.get("basic_rules", ""),
        "power_structure": list(world_setting.get("power_structure") or []),
        "geography": list(world_setting.get("geography") or []),
        "world_taboos": list(world_setting.get("world_taboos") or []),
        "unique_settings": list(world_setting.get("unique_settings") or []),
        "gray_zone_ecology": list(world_setting.get("gray_zone_ecology") or []),
        "narrative_era": str(world_setting.get("narrative_era") or "").strip(),
    }


def shallow_protagonist_archive(card: dict) -> dict:
    if not isinstance(card, dict):
        return {}
    return dict(card)


def _append_capabilities_lines(card: dict, lines: list[str]) -> None:
    """金手指/武功/大道/标志物/特质；供 archive 块与 CLI 主角卡复用。"""
    caps = card.get("capabilities")
    if not isinstance(caps, dict) or not caps:
        return
    lines.append("**capabilities（能力档案）**:")

    gf = caps.get("golden_finger")
    has_gf_content = False
    if isinstance(gf, dict):
        has_gf_content = bool(
            gf.get("has_golden_finger")
            or (str(gf.get("core_ability") or "").strip())
            or (str(gf.get("gf_type") or "").strip())
        )
    if isinstance(gf, dict) and has_gf_content:
        gf_type = str(gf.get("gf_type") or "未知类型").strip()
        core_ability = str(gf.get("core_ability") or "").strip()
        act = str(gf.get("activation_condition") or "").strip()
        cost = str(gf.get("cost_and_limit") or "").strip()
        exposure = str(gf.get("exposure_risk") or "").strip()
        current_state_gf = str(gf.get("current_state") or "").strip()
        lines.append(f"  金手指 [{gf_type}]:")
        if core_ability:
            lines.append(f"    核心能力: {core_ability[:200]}")
        if act:
            lines.append(f"    触发条件: {act[:200]}")
        if cost:
            lines.append(f"    代价与限制: {cost[:200]}")
        if exposure:
            lines.append(f"    暴露风险: {exposure[:150]}")
        if current_state_gf:
            lines.append(f"    当前状态: {current_state_gf[:150]}")
    else:
        lines.append("  金手指: 无")

    combat_skills = caps.get("combat_skills") or []
    if isinstance(combat_skills, list) and combat_skills:
        skill_parts = []
        for sk in combat_skills[:5]:
            if not isinstance(sk, dict):
                continue
            sn = str(sk.get("skill_name") or "").strip()
            lv = str(sk.get("current_level") or "").strip()
            if sn:
                skill_parts.append(f"{sn}（{lv}）" if lv else sn)
        if skill_parts:
            lines.append(f"  武功/功法: {' / '.join(skill_parts)}")

    dao = str(caps.get("dao_foundation") or "").strip()
    if dao and dao.lower() != "null":
        lines.append(f"  修炼大道: {dao[:150]}")

    sig_items = caps.get("signature_items") or []
    if isinstance(sig_items, list) and sig_items:
        item_parts = []
        for it in sig_items[:4]:
            if not isinstance(it, dict):
                continue
            iname = str(it.get("item_name") or "").strip()
            istatus = str(it.get("current_status") or "在身").strip()
            if iname:
                item_parts.append(f"{iname}[{istatus}]")
        if item_parts:
            lines.append(f"  标志性物品: {' / '.join(item_parts)}")

    unique_traits = caps.get("unique_traits") or []
    if isinstance(unique_traits, list) and unique_traits:
        trait_parts = []
        for ut in unique_traits[:3]:
            if not isinstance(ut, dict):
                continue
            tname = str(ut.get("trait_name") or "").strip()
            teffect = str(ut.get("trait_effect") or "").strip()[:80]
            tdouble = str(ut.get("double_edge") or "").strip()[:80]
            if tname:
                trait_parts.append(
                    f"{tname}（效果: {teffect}；代价: {tdouble}）" if teffect else tname
                )
        if trait_parts:
            lines.append(f"  独特特质: {' / '.join(trait_parts)}")


def protagonist_capabilities_cli_block(card: dict, max_chars: int = 5000) -> str:
    """CLI「主角人物卡」一屏：仅 capabilities，与 archive 中金手指段同源。"""
    if not isinstance(card, dict):
        return ""
    caps = card.get("capabilities")
    if not isinstance(caps, dict) or not caps:
        return "（尚无 capabilities 结构化字段：金手指/武功/特质等将在冰山或开篇注入后显示）"
    lines: list[str] = []
    _append_capabilities_lines(card, lines)
    if len(lines) <= 0:
        return "（capabilities 为空）"
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n…（截断）"
    return text


def protagonist_archive_prompt_block(card: dict, max_chars: int = 8000) -> str:
    """
    格式化主角档案为供 LLM 推导的段落。
    文档 §5.3：protagonist_archive → iceberg / story_arc / event_chain / expand / write 全量传递。
    包含 PROMPT 3 所有关键字段：精神面板数值 + 叙述、先天/成熟度对象、逆鳞、处境议程。
    """
    if not isinstance(card, dict):
        return "（主角档案未生成）"
    name = (card.get("standard_name") or card.get("name") or "主角").strip()
    cid = (card.get("character_id") or "").strip()
    mc = card.get("mental_core") if isinstance(card.get("mental_core"), dict) else {}
    mcl = card.get("mental_core_literary") if isinstance(card.get("mental_core_literary"), dict) else {}
    inn = card.get("innate_traits") or []
    inn_d = card.get("innate_traits_detail") if isinstance(card.get("innate_traits_detail"), dict) else {}
    ml_d = card.get("maturity_level_detail") if isinstance(card.get("maturity_level_detail"), dict) else {}
    ml_str = (card.get("current_maturity") or card.get("maturity_level") or "").strip()

    lines = ["## protagonist_archive（主角档案 · 推导引擎核心输入；文档 PROMPT 3）"]
    id_str = f" | id={cid}" if cid else ""
    lines.append(f"**姓名**: {name}{id_str}")
    als = card.get("aliases") or []
    if isinstance(als, list) and als:
        lines.append(f"**别名**: {', '.join(str(x) for x in als[:12] if str(x).strip())}")

    if (card.get("background_summary") or "").strip():
        lines.append(f"**出身与关键经历**: {str(card['background_summary'])[:500]}")

    if card.get("appearance"):
        lines.append(f"**外貌**: {card['appearance']}")
    if card.get("persona"):
        lines.append(f"**外在假面**: {card['persona']}")
    if card.get("reverse_scale"):
        lines.append(f"**绝对逆鳞**: {card['reverse_scale']}（触碰时不论理性程度必然反应）")

    if isinstance(inn, list) and inn:
        lines.append(f"**先天底色(list)**: {', '.join(str(x) for x in inn[:12])}")
    if inn_d:
        cd = str(inn_d.get("core_desire") or "").strip()
        cf = str(inn_d.get("core_fear") or "").strip()
        pl = list(inn_d.get("personality") or [])
        tl = list(inn_d.get("talent_physical") or [])
        if pl:
            lines.append(f"  - personality: {', '.join(str(x) for x in pl[:6])}")
        if tl:
            lines.append(f"  - talent: {', '.join(str(x) for x in tl[:4])}")
        if cd:
            lines.append(f"  - core_desire: {cd[:300]}")
        if cf:
            lines.append(f"  - core_fear: {cf[:300]}")

    if mc:
        drain = card.get("current_emotional_drain", 0)
        panel = (
            f"心智(intelligence)={mc.get('intelligence','?')}  "
            f"情商(eq)={mc.get('eq','?')}  "
            f"缜密(meticulousness)={mc.get('meticulousness','?')}  "
            f"阈值(emotional_capacity)={mc.get('emotional_capacity','?')}  "
            f"隐忍(forbearance)={mc.get('forbearance','?')}  "
            f"当前透支={drain}"
        )
        lines.append(f"**精神面板(0-100)**: {panel}")
    if mcl:
        lines.append("**精神面板(文档叙述)**:")
        for k, lab in [
            ("intellect", "心智"),
            ("emotional_intelligence", "情商"),
            ("strategic_thinking", "缜密"),
            ("endurance", "隐忍"),
            ("emotional_collapse_behavior", "阈值崩溃行为"),
        ]:
            v = str(mcl.get(k) or "").strip()
            if v:
                lines.append(f"  - {lab}: {v[:200]}")
        triggers = mcl.get("emotional_drain_triggers") or []
        if isinstance(triggers, list) and triggers:
            lines.append(f"  - 阈值消耗触发: {'; '.join(str(x) for x in triggers[:5])}")

    if ml_d:
        score = str(ml_d.get("current_score") or "").strip()
        ill = [str(x) for x in (ml_d.get("illusions_held") or []) if str(x).strip()]
        gt = str(ml_d.get("growth_trajectory") or "").strip()
        lines.append(f"**成熟度**: 档位={score or '未知'}")
        if ill:
            lines.append(f"  - 当前保有幻想(成长靶点): {'; '.join(ill[:4])}")
        if gt:
            lines.append(f"  - 跃迁预期: {gt[:200]}")
    elif ml_str:
        lines.append(f"**成熟度**: {ml_str[:200]}")

    if card.get("world_position"):
        lines.append(f"**世界位置/圈层**: {str(card['world_position'])[:300]}")
    if card.get("independent_agenda"):
        lines.append(f"**独立议程(无外部事件时的目标)**: {str(card['independent_agenda'])[:300]}")
    if card.get("core_motif"):
        lines.append(f"**叙事核心底色**: {str(card['core_motif'])[:300]}")

    fr = card.get("faction_relationship")
    if isinstance(fr, dict) and fr:
        lines.append(f"**阵营关系初始档**: {_short_json_blob(fr, 600)}")

    dl = card.get("dominant_logics") or []
    if isinstance(dl, list) and dl:
        lines.append(f"**人性逻辑**: {', '.join(str(x) for x in dl[:4])}")
    lo = card.get("logic_origins") or []
    if isinstance(lo, list) and lo:
        lines.append(f"**逻辑渊源**: {'；'.join(str(x) for x in lo[:6] if str(x).strip())}")
    lsc = card.get("logic_switch_conditions")
    if isinstance(lsc, list) and lsc:
        lines.append(f"**逻辑切换条件**: {_short_json_blob(lsc, 800)}")

    kle = card.get("key_life_events") or []
    if isinstance(kle, list) and kle:
        lines.append(f"**关键人生节点**: {'；'.join(str(x) for x in kle[:8] if str(x).strip())}")

    traits = card.get("traits") or []
    if isinstance(traits, list) and traits:
        bits = []
        for t in traits[:6]:
            if not isinstance(t, dict):
                continue
            nm = str(t.get("name") or "").strip()
            tr = str(t.get("trigger") or "").strip()[:80]
            if nm:
                bits.append(f"{nm}" + (f"（触发：{tr}）" if tr else ""))
        if bits:
            lines.append(f"**特质条目**: {' / '.join(bits)}")

    ti = card.get("trait_interactions")
    if isinstance(ti, dict) and (ti.get("preset") or ti.get("learned")):
        lines.append(f"**特质叠加规则**: {_short_json_blob(ti, 700)}")

    sh = card.get("signature_habits") or []
    if isinstance(sh, list) and sh:
        lines.append(f"**标志性微动作**: {'; '.join(str(x) for x in sh[:3])}")

    _append_capabilities_lines(card, lines)

    # 活跃任务栈（补丁 D）
    qs = card.get("active_quest_stack") or []
    if isinstance(qs, list):
        active_qs = [q for q in qs if isinstance(q, dict) and q.get("status") == "active"]
        if active_qs:
            lines.append("\n**活跃任务栈（active_quest_stack · 动机锚点）**:")
            urg_icon = {"critical": "⚠️", "high": "→", "medium": "·", "low": "○"}
            for q in active_qs[:6]:
                layer = q.get("layer", "")
                urg = q.get("urgency_level", "")
                icon = urg_icon.get(urg, "·")
                lines.append(f"  {icon} [{layer}|{urg}] {q.get('quest_name', '')}")
                sg = str(q.get("current_sub_goal") or "").strip()
                if sg:
                    lines.append(f"    子目标：{sg[:150]}")
                dn = str(q.get("deadline_note") or "").strip()
                if dn and urg in ("critical", "high"):
                    lines.append(f"    截止：{dn[:80]}")
                ew = str(q.get("emotional_weight") or "").strip()
                if ew and urg in ("critical", "high"):
                    lines.append(f"    情感重量：{ew[:100]}")

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars - 20] + "\n…（截断）"
    return result


def collision_display_v43(
    collision: dict[str, Any] | None,
    event_core: dict[str, Any] | None,
) -> tuple[str, str]:
    """
    v4.3 event_chain_gen 的 collision 使用 collision_trigger / collision_outcome；
    旧 UI 字段 conflict_surface / twist 为空时，用结构化字段回退，避免审核面板空白。
    """
    col = collision if isinstance(collision, dict) else {}
    cs = str(col.get("conflict_surface") or "").strip()
    tw = str(col.get("twist") or "").strip()
    if not cs:
        tr = str(col.get("collision_trigger") or "").strip()
        oc = str(col.get("collision_outcome") or "").strip()
        parts = [p for p in (tr, oc) if p]
        cs = "｜".join(parts) if parts else ""
    if not tw:
        ec = event_core if isinstance(event_core, dict) else {}
        tw = str(ec.get("tension_peak") or "").strip()
    return cs, tw
