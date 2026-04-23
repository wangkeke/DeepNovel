from __future__ import annotations
import json
import aiosqlite
from langgraph.types import StreamWriter
from schemas.state import CreationState
from utils.karmic_path import format_fruit_and_seed_for_prompt

from prompts.creation.expand1 import (
    EXPAND1_SYSTEM, EXPAND1_USER_TEMPLATE, EXPAND1_GENRE_EVENT_TEMPLATE,
    LAST_ACTION_INTENT_SECTION,
)
from prompts.creation.platform_styles import (
    RULE_PRECEDENCE_NOTICE,
    LIVING_COMPANION_RULES,
    DEEPNOVEL_LITERARY_CONSTITUTION,
    ADVANCED_LITERARY_RULES,
    platform_planning_bundle,
)
from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING
from utils.llm import call_llm_json
from utils.json_cot import flatten_cot_output
from utils.genre_lexicon import genre_lexicon_banner
from memory.entity_db import (
    get_all_entity_names, get_entities_by_names,
    get_character_cards_with_tendencies, get_character_abilities,
    get_character_traits_and_interactions,
)
from memory.db import (
    get_available_character_names_for_volume,
    get_faction_cards_for_volume,
)
from config import DB_PATH
from knowledge.human_logic_lib import format_character_logics, HUMAN_LOGIC_LIB
from prompts.common.emotional_bond_doctrine import (
    build_ebd_constraint,
    merge_ebd_entries_for_expand1,
)
from prompts.common.variable_elasticity import VARIABLE_ELASTICITY_RULE_BLOCK


def _karmic_evolution_section(node: dict) -> str:
    """path_gen 演化层：四维资源、扣机、果种、成长触发 → 注入 expand1。"""
    kr = node.get("karmic_resources") or []
    if isinstance(kr, str) and kr.strip():
        kr = [kr.strip()]
    if not isinstance(kr, list):
        kr = []
    ml = (node.get("mental_lever") or "").strip()
    fs = node.get("fruit_and_seed") if isinstance(node.get("fruit_and_seed"), dict) else {}
    cg = (node.get("character_growth_trigger") or "").strip()
    if not kr and not ml and not fs and (not cg or cg == "无"):
        return ""
    lines: list[str] = ["## 演化层指令（path_gen；因果与成长须与下文 3W1H 一致）\n"]
    if kr:
        lines.append(
            "- 本节点动用的四维资源子集："
            + "、".join(str(x).strip() for x in kr if str(x).strip())
        )
    if ml:
        lines.append(f"- 精神扣机：{ml}")
    fs_line = format_fruit_and_seed_for_prompt(fs)
    if fs_line:
        lines.append(f"- 果/种与兑现：{fs_line}")
    if cg and cg != "无":
        lines.append(f"- 成长/成熟度触发：{cg}")
    return "\n".join(lines) + "\n"


def _bible_karmic_anchor_tail(state: CreationState) -> str:
    """将 bible 中因果账本与锚点审计尾迹注入 expand1，供 3W1H 与后文承接。"""
    bb = state.get("bible") or {}
    parts: list[str] = []
    inv = bb.get("karmic_seeds_inventory") or []
    if isinstance(inv, list) and inv:
        parts.append("\n## 近期因果种子（bible_update 归档；分析须考虑延续/回收）")
        for x in inv[-6:]:
            if not isinstance(x, dict):
                continue
            sid = (x.get("seed_id") or "?").strip()
            desc = (x.get("description") or "").strip()[:120]
            if desc or sid:
                parts.append(f"- [{sid}] {desc}")
    ledger = bb.get("last_karmic_ledger_updates")
    if isinstance(ledger, dict):
        harv = ledger.get("seeds_harvested") or []
        if isinstance(harv, list) and harv:
            parts.append("\n## 上章已兑现的因果种子（承接语用）")
            for h in harv[-4:]:
                if isinstance(h, dict):
                    pid = (h.get("seed_id") or "?").strip()
                    pay = (h.get("actual_payoff") or "").strip()[:100]
                    parts.append(f"- 引爆 [{pid}]：{pay}")
    aic = bb.get("anchor_integrity_check")
    if isinstance(aic, dict) and (aic.get("status") or "").strip().upper() == "WARNING":
        conf = aic.get("conflicts") or []
        if isinstance(conf, list):
            cj = "；".join(str(c).strip() for c in conf if str(c).strip())[:400]
        else:
            cj = str(conf)[:400]
        parts.append(
            "\n## ⚠️ 用户锚点审计（上章 WARNING）\n"
            f"{cj or '（无细节）'} — 本节须避免加重与用户私货的冲突。"
        )
    fsn = bb.get("faction_shift_notes_last")
    if isinstance(fsn, list) and fsn:
        parts.append(
            "\n## 上章势力立场快照（bible_update）\n"
            + "\n".join(f"- {str(x).strip()}" for x in fsn[:12] if str(x).strip())
        )
    return "".join(parts)


def _format_single_logic(card: dict) -> str:
    """单人物的人性逻辑文本。"""
    parts = []
    for logic_name in card.get("dominant_logics", []):
        logic = HUMAN_LOGIC_LIB.get(logic_name, {})
        if logic:
            steps = "\n".join(f"    {step}" for step in logic.get("execution_steps", []))
            parts.append(f"{logic_name}：{logic.get('core_essence', '')}\n  执行程序：\n{steps}")
    return "\n".join(parts) if parts else "无"


def _ebd_targeting_axes_line(card: dict) -> str:
    """数据库最新 EBD（主观）与 targeting_degree（客观针对 0-100）一并注入 expand1。"""
    parts: list[str] = []
    ebd = card.get("ebd_to_protagonist")
    if ebd is not None and str(ebd).strip() != "":
        try:
            parts.append(f"EBD（情感纽带度）{int(ebd)}")
        except (TypeError, ValueError):
            parts.append(f"EBD（情感纽带度）{ebd}")
    td = card.get("targeting_degree")
    if td is not None and str(td).strip() != "":
        try:
            parts.append(f"针对度（客观威胁/压制）{max(0, min(100, int(round(float(td)))))}/100")
        except (TypeError, ValueError):
            pass
    if not parts:
        return ""
    return "  关系双轴：" + " · ".join(parts) + "\n"


def _mental_profile_block_for_expand1(card: dict) -> str:
    ms = (card.get("current_mental_state") or "").strip()
    gp = (card.get("mental_growth_path") or "").strip()
    rs = (card.get("reverse_scale") or "").strip()
    mat = (card.get("maturity_level") or "").strip()
    mc = card.get("mental_core") if isinstance(card.get("mental_core"), dict) else {}
    mc_line = ""
    if mc:
        mc_line = (
            f"  精神面板(0-100)：心{mc.get('intelligence', '?')} 情{mc.get('eq', '?')} "
            f"缜{mc.get('meticulousness', '?')} 阈{mc.get('emotional_capacity', '?')} "
            f"忍{mc.get('forbearance', '?')} 透支{card.get('current_emotional_drain', 0)}\n"
        )
    inn = card.get("innate_traits") if isinstance(card.get("innate_traits"), list) else []
    inn_line = ""
    if inn:
        inn_line = f"  先天底色：{'；'.join(str(x) for x in inn[:8])}\n"
    if not (ms or gp or rs or mat or mc_line or inn_line):
        return ""
    extra = ""
    if mat:
        extra += f"  成熟度表述：{mat}\n"
    return (
        inn_line
        + mc_line
        + extra
        + f"  心智成熟度：{ms or '未知'}\n"
        + f"  心智成长轨迹：{gp or '未知'}\n"
        + f"  绝对逆鳞：{rs or '无'}\n"
    )


def _format_character_for_expand1(card: dict, traits_str: str) -> str:
    """按角色类型格式化人物信息，供 expand1 注入。"""
    name = card.get("name", card.get("standard_name", ""))
    role = card.get("role", "minor")
    logic_str = _format_single_logic(card)
    axes = _ebd_targeting_axes_line(card)
    mental = _mental_profile_block_for_expand1(card)

    if role == "protagonist":
        return f"""
{name}（主角）
  外貌：{card.get('appearance', '')}
  行为倾向：{traits_str}
  人性逻辑：{logic_str}
  当前状态：{card.get('current_status', '')}{mental}{axes}"""

    if role == "core_supporting":
        return f"""
{name}（核心配角）
  行为倾向：{traits_str}
  人性逻辑：{logic_str}
  当前状态：{card.get('current_status', '')}{mental}{axes}"""

    if role == "antagonist":
        switch_conds = card.get("logic_switch_conditions", [])
        switch_str = "; ".join(
            f"{c.get('condition','')}→{c.get('switch_to','')}" for c in switch_conds
        ) if switch_conds else "无"
        return f"""
{name}（反派）
  人性逻辑：{logic_str}
  真实动机：{card.get('true_motive', '')}
  当前对主角的威胁：{card.get('current_status', '')}
  极端处境下的逻辑切换：{switch_str}{mental}{axes}"""

    if role == "neutral":
        tipping = card.get("tipping_conditions", [])
        tipping_str = "; ".join(tipping) if tipping else "无"
        return f"""
{name}（中立者）
  利益立场：{card.get('neutral_stance', '')}
  倒向条件：{tipping_str}
  当前与各方关系：{card.get('current_status', '')}{mental}{axes}"""

    # minor：过路角色
    _line = f"{name}：{card.get('current_status', '')}"
    if mental.strip():
        _line = _line + "\n" + mental.rstrip("\n")
    return f"{_line}\n{axes}" if axes.strip() else _line


async def _mark_node_writing(project_id: str, seq: int) -> None:
    """将 story_nodes 对应行状态更新为 writing，幂等。"""
    if not project_id:
        return
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            await conn.execute(
                "UPDATE story_nodes SET status='writing' WHERE project_id=? AND seq=?",
                (project_id, seq),
            )
            await conn.commit()
    except Exception:
        pass


async def expand1_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "expand1"})
    story_path  = state.get("story_path", [])
    current_idx = state.get("current_node_index", 0)
    
    if current_idx >= len(story_path):
        return {}
        
    current_node = story_path[current_idx]

    # seq 从1开始；DB 中 seq_offset 已在 human_review_path 写入时确定
    # 此处只做 status=writing 的标记，seq 与 DB 保持一致
    project_id = state.get("project_id", "")
    seq = current_node.get("_seq", current_idx + 1)   # _seq 由 human_review_path 注入
    await _mark_node_writing(project_id, seq)
    
    prev_output = ""
    if current_idx > 0:
        prev_output = story_path[current_idx - 1].get("output_state_hint", "")

    # ── 上一章结尾的行动意图（bible_update 提取，必须承接）──
    last_action_intent = state.get("last_action_intent", "").strip()
    if not last_action_intent and project_id and current_idx >= 0:
        try:
            async with aiosqlite.connect(str(DB_PATH)) as conn:
                cursor = await conn.execute(
                    "SELECT last_action_intent FROM novel_projects WHERE project_id = ?",
                    (project_id,),
                )
                row = await cursor.fetchone()
                if row and row[0]:
                    last_action_intent = (row[0] or "").strip()
        except Exception:
            pass
    last_action_intent_section = (
        "\n" + LAST_ACTION_INTENT_SECTION.format(last_action_intent=last_action_intent)
        if last_action_intent else ""
    )

    # 用户对上一版正文的修改意见（由 human_review_write / human_review_expand 回传）
    # 优先使用解析结果（human_review_write 方向大改时的前置解析）
    bible = state.get("bible", {})
    parsed = bible.get("rewrite_feedback_parsed", {})
    raw_feedback = bible.get("rewrite_feedback", "") or current_node.get("chapter_feedback", "")

    if parsed and parsed.get("confirmed_facts"):
        facts_text = "\n".join(f"  • {f}" for f in parsed["confirmed_facts"])
        direction_text = parsed.get("direction", "")
        placeholder_str = ", ".join(parsed.get("placeholder_names", [])) or "无"
        feedback_section = f"""

## 用户修改要求

必须在本节中体现的确定事实：
{facts_text}

用户希望的方向：
{direction_text}

注意：用户意见中出现的以下名字是占位符，不要直接用在小说里：{placeholder_str}
"""
    elif raw_feedback:
        feedback_section = "\n\n" + USER_FEEDBACK_HANDLING.format(user_feedback=raw_feedback)
    else:
        feedback_section = ""

    # ── 人物信息注入（按角色类型区分：主角/核心配角/反派/中立者/过路角色）──
    # 浮动配角过滤：只加载当前卷已出场的角色
    current_vol_index = state.get("current_volume_index", 0)
    available_char_names = (
        await get_available_character_names_for_volume(project_id, current_vol_index)
        if project_id else set()
    )

    personality_section = ""
    character_logics_section = ""
    ebd_constraint_section = ""
    if project_id:
        key_characters = current_node.get("key_characters", [])
        if isinstance(key_characters, str):
            key_characters = [n.strip() for n in key_characters.split("、") if n.strip()]
        # 过滤：仅保留本卷已出场的角色（主角始终保留）
        protagonist_name = state.get("protagonist_name", "")
        key_characters = [
            n for n in key_characters
            if n in available_char_names or n == protagonist_name
        ]
        if key_characters:
            try:
                traits_map = await get_character_traits_and_interactions(project_id, key_characters)
                char_cards = await get_character_cards_with_tendencies(project_id, key_characters)
                protagonist_name = state.get("protagonist_name", "")
                blocks: list[str] = []
                for name in key_characters:
                    card = next((c for c in (char_cards or []) if c.get("name") == name), None)
                    if not card:
                        card = {"name": name, "role": "minor", "current_status": ""}
                    if card.get("role", "minor") == "minor" and name == protagonist_name:
                        card = {**card, "role": "protagonist"}
                    ti_data = traits_map.get(name, {})
                    traits = ti_data.get("traits", [])
                    interactions = ti_data.get("trait_interactions", {})
                    preset = interactions.get("preset", []) or []
                    learned = interactions.get("learned", []) or []

                    if traits:
                        trait_strs = []
                        for t in traits:
                            trig = t.get("trigger", "")
                            expr = t.get("expression", "")
                            sup = t.get("suppressed_by", [])
                            sup_str = f"，被压制于：{';'.join(sup)}" if sup else ""
                            trait_strs.append(
                                f"{t.get('name','')}：触发={trig}，表现={expr}{sup_str}"
                            )
                        traits_str = "\n  ".join(trait_strs)
                        if preset or learned:
                            for p in preset:
                                combo = "+".join(p.get("combo", []))
                                traits_str += f"\n  预设叠加【{combo}】{p.get('condition','')}→{p.get('result','')}"
                            for lr in learned:
                                combo = "+".join(lr.get("combo", []))
                                traits_str += f"\n  习得叠加【{combo}】第{lr.get('learned_from_seq','?')}节后：{lr.get('result','')}"
                    else:
                        if card.get("core_motif") or card.get("persona"):
                            habits = card.get("signature_habits") or []
                            hb = "；".join(habits) if habits else ""
                            traits_str = (
                                f"核心底色：{card.get('core_motif', '')}\n"
                                f"外在假面：{card.get('persona', '')}\n"
                                f"标志性微动作：{hb or '（无）'}"
                            )
                        else:
                            inn = card.get("innate_traits") if isinstance(
                                card.get("innate_traits"), list
                            ) else []
                            if inn:
                                traits_str = "先天底色：" + "；".join(str(x) for x in inn)
                            else:
                                traits_str = "（待补充 innate_traits / core_motif）"
                    blocks.append(_format_character_for_expand1(card, traits_str))
                if blocks:
                    personality_section = (
                        "\n\n## 涉及人物（按角色类型区分，场景设计应体现）\n"
                        + "\n".join(blocks)
                    )

                try:
                    merged_ebd = merge_ebd_entries_for_expand1(
                        char_cards or [],
                        key_characters,
                        state.get("core_cast"),
                    )
                    etxt = build_ebd_constraint(merged_ebd)
                    if etxt.strip():
                        ebd_constraint_section = "\n\n" + etxt
                except Exception:
                    pass

                # 人性逻辑注入（供 logic_analysis 分析）
                logic_text = format_character_logics(char_cards)
                character_logics_section = (
                    "本节涉及人物的主导逻辑：\n" + logic_text
                    if logic_text
                    else "本节涉及人物无主导逻辑记录。logic_analysis 仍必填，无主导逻辑的人物可填 opponent_blind_spot 与 exploitation_point 为空。"
                )
            except Exception:
                pass

    # ── 势力卡注入（框架导入时，按节点内容匹配）──
    faction_section = ""
    if project_id:
        all_factions = await get_faction_cards_for_volume(project_id, current_vol_index)
        if all_factions:
            node_text = (current_node.get("node_name", "") or "") + (current_node.get("one_liner", "") or "")
            involved = [
                f for f in all_factions
                if f.get("name", "") in node_text
                or any(m and m in node_text for m in f.get("core_members", []))
            ]
            if involved:
                lines = []
                for fa in involved:
                    members = "、".join(fa.get("core_members", [])) or "无"
                    lines.append(
                        f"{fa.get('name', '')}（{fa.get('faction_type', 'neutral')}）："
                        f"{fa.get('description', '')} | 目标：{fa.get('goals', '')} | "
                        f"对主角立场：{fa.get('stance_to_protagonist', '')} | 核心成员：{members}"
                    )
                faction_section = (
                    "\n\n## 本节涉及势力\n" + "\n".join(f"  • {ln}" for ln in lines) + "\n"
                )

    if not character_logics_section:
        character_logics_section = "本节涉及人物无主导逻辑记录。logic_analysis 仍必填。"

    sc = (current_node.get("scene_cause") or "").strip()
    sp = (current_node.get("scene_process") or "").strip()
    sr = (current_node.get("scene_result") or "").strip()
    sm = (current_node.get("scene_momentum") or "").strip()
    if sc or sp or sr or sm:
        scene_unit_section = (
            "## 场景单元（来自事件链 → 路径转化，须与下文 3W1H 一致，禁止另编主线）\n\n"
            f"起因：{sc or '（无）'}\n"
            f"经过：{sp or '（无）'}\n"
            f"结果：{sr or '（无）'}\n"
            f"推动力（衔接下一场景）：{sm or '（无）'}\n"
        )
    else:
        scene_unit_section = ""

    # ── 能力列表注入（让模型破局时优先使用已有能力，不凭空发明）──
    ability_section = ""
    if project_id:
        key_characters = current_node.get("key_characters", [])
        if isinstance(key_characters, str):
            key_characters = [n.strip() for n in key_characters.split("、") if n.strip()]
        if key_characters:
            try:
                abilities_map = await get_character_abilities(project_id, key_characters)
                if abilities_map:
                    lines = []
                    for char_name, abs_list in abilities_map.items():
                        for ab in abs_list:
                            level = ab.get("level", "")
                            limitation = ab.get("limitation", "")
                            lim_str = f"  限制：{limitation}" if limitation else ""
                            lines.append(
                                f"  • {ab.get('name', '?')}（{ab.get('type', '')}）"
                                f"[{level}]：{ab.get('description', '')}{lim_str}"
                            )
                        ability_section += f"\n{char_name} 的已知能力：\n" + "\n".join(lines) + "\n"
                        lines = []
                    ability_section = (
                        "\n\n## 当前人物能力（破局设计优先使用已有能力，不要凭空发明新技能）\n"
                        + ability_section.strip()
                    )
            except Exception:
                pass

    # ── 实体卡片注入（仅有修改意见时触发，避免无谓 DB 查询）──
    entity_section = ""
    if raw_feedback and project_id:
        try:
            known_names = await get_all_entity_names(project_id)
            # 简单子字符串匹配：在 feedback 文本中找到已知实体名
            matched = [n for n in known_names if n and n in raw_feedback]
            if matched:
                cards = await get_entities_by_names(project_id, matched)
                if cards:
                    card_lines = []
                    for c in cards:
                        data_str = json.dumps(c["data"], ensure_ascii=False)
                        card_lines.append(
                            f"- [{c['card_type']}] {c['name']}：{data_str}"
                        )
                    entity_section = (
                        "\n\n## 相关实体已知信息（来自知识库）\n"
                        + "\n".join(card_lines)
                    )
        except Exception:
            pass  # 实体注入失败不阻断主流程

    # bible 字段现在存 entity_summary 轻量摘要；附因果账本与锚点尾迹供下游消费
    bible_summary = (state.get("bible", {}).get("entity_summary", "") or "") + _bible_karmic_anchor_tail(
        state
    )

    # ── 题材施压事件注入 ──
    pressure_chain_type = current_node.get("pressure_chain_type", "")
    genre_event_section = ""
    genre_dicts: list[dict] = state.get("genre_dicts", [])
    matched_genres: list[str] = state.get("matched_genres", [])
    if genre_dicts and pressure_chain_type:
        # 从所有匹配题材中汇总施压事件，做关键词模糊匹配
        all_pressure: list[str] = []
        for gd in genre_dicts:
            all_pressure.extend(gd.get("pressure_events", []))
        # 以 pressure_chain_type 中的词片段过滤相关事件
        filter_words = [w for w in pressure_chain_type.replace("型", "").split() if len(w) >= 2]
        matched_events = [
            e for e in all_pressure
            if any(w in e for w in filter_words)
        ] or all_pressure[:6]  # 无关键词命中时取前6条作通用参考
        genre_event_section = "\n" + EXPAND1_GENRE_EVENT_TEMPLATE.format(
            pressure_chain_type=pressure_chain_type,
            genre_name="、".join(matched_genres) if matched_genres else "本题材",
            matched_pressure_events="、".join(matched_events[:8]),
        )
        
    _path_empty = "（无特殊说明）"
    opening_seed_section = ""
    _seed = (state.get("synopsis") or {}).get("opening_seed_text") or ""
    _vol0 = int(state.get("current_volume_index", 0) or 0) == 0
    if (
        _seed.strip()
        and current_idx == 0
        and not (state.get("completed_chapters") or [])
        and _vol0
    ):
        opening_seed_section = (
            "## 【已锁定开篇种子（全书首节点分析须与此接续，禁止另编矛盾开头）】\n\n"
            + _seed.strip()
            + "\n\n本节 3W1H 与事件路径草案必须承接上述开场之后的发展。\n\n"
        )
    user_prompt = EXPAND1_USER_TEMPLATE.format(
        opening_seed_section=opening_seed_section,
        node_name=current_node.get("node_name", ""),
        pressure_chain_type=pressure_chain_type,
        resolution_chain_type=current_node.get("resolution_chain_type", ""),
        input_state_hint=current_node.get("input_state_hint", ""),
        output_state_hint=current_node.get("output_state_hint", ""),
        scene_unit_section=scene_unit_section,
        tension_type=current_node.get("tension_type", ""),
        tension_design=current_node.get("tension_design", ""),
        reader_expectation=current_node.get("reader_expectation") or _path_empty,
        expectation_breaker=current_node.get("expectation_breaker") or _path_empty,
        node_result=current_node.get("node_result") or _path_empty,
        cost_for_protagonist=current_node.get("cost_for_protagonist") or _path_empty,
        character_choice=current_node.get("character_choice") or _path_empty,
        next_node_trigger=current_node.get("next_node_trigger") or _path_empty,
        karmic_evolution_section=_karmic_evolution_section(current_node),
        bible_summary=bible_summary,
        prev_output_state=prev_output,
        last_action_intent_section=last_action_intent_section,
        genre_event_section=genre_event_section,
        personality_section=personality_section,
        ebd_constraint_section=ebd_constraint_section,
        faction_section=faction_section,
        character_logics_section=character_logics_section,
    ) + ability_section + feedback_section + entity_section

    gbanner = genre_lexicon_banner(
        state.get("synopsis") or {}, state.get("matched_genres") or []
    )
    # 平台+题材+受众定位宏观约束（只注入 macro hints，不重复完整写作皮囊）
    _platform_macro = platform_planning_bundle(state, skin_max_chars=0)
    expand1_sys = (
        RULE_PRECEDENCE_NOTICE.strip()
        + "\n\n"
        + EXPAND1_SYSTEM
        + (f"\n\n{gbanner}\n" if gbanner.strip() else "")
        + (f"\n\n{_platform_macro}\n" if _platform_macro.strip() else "")
        + f"\n\n{VARIABLE_ELASTICITY_RULE_BLOCK}\n"
        + f"\n\n{LIVING_COMPANION_RULES}"
        + f"\n\n{DEEPNOVEL_LITERARY_CONSTITUTION}"
        + f"\n\n{ADVANCED_LITERARY_RULES}"
    )

    raw = await call_llm_json(expand1_sys, user_prompt, max_tokens=8000)
    result = flatten_cot_output(raw if isinstance(raw, dict) else {})
    
    return {
        "current_expand1":     result,
        "expand1_event_draft": result.get("event_path_draft", []),
        "expand1_approved":    False,
        # 覆盖 path_gen 遗留的 "path"，供 auto_review 与后续边一致路由到 expand 类审核
        "pending_review_type": "expand",
    }


# ════════════════════════════════════════════════════════════════════════════════
# v4.3 路径落地确认节点
# ════════════════════════════════════════════════════════════════════════════════

from prompts.creation.expand1 import EXPAND1_V43_SYSTEM, EXPAND1_V43_USER_TEMPLATE  # noqa: E402
from langgraph.types import Command  # noqa: E402
import logging  # noqa: E402

logger_v43 = logging.getLogger("deepnovel.expand1_v43")


def _get_current_path_definition(state: CreationState) -> dict | None:
    """
    从 current_event_paths 中按 path_progress.remaining_paths[0] 找到当前路径定义。
    """
    event_paths = state.get("current_event_paths") or {}
    if not isinstance(event_paths, dict):
        return None

    path_progress = state.get("path_progress") or {}
    remaining = path_progress.get("remaining_paths") or []

    if not remaining:
        return None

    current_path_id = remaining[0]
    paths = event_paths.get("paths") or []
    if not isinstance(paths, list):
        return None

    for path in paths:
        if isinstance(path, dict) and path.get("path_id") == current_path_id:
            return path

    # 如果没找到匹配的 path_id，返回第一个
    if paths and isinstance(paths[0], dict):
        return paths[0]

    return None


def _get_prev_causal_output(state: CreationState) -> str:
    """从 state 中提取上一章的因果输出。"""
    expand1 = state.get("current_expand1") or {}
    if isinstance(expand1, dict):
        causal_out = expand1.get("causal_output_direction", "")
        if causal_out:
            return causal_out

    bible = state.get("bible") or {}
    if isinstance(bible, dict):
        last_intent = bible.get("last_causal_output", "")
        if last_intent:
            return str(last_intent)

    last_action_intent = state.get("last_action_intent", "")
    if last_action_intent:
        return last_action_intent

    return "（第一章：无前序因果输出）"


_LITERARY_FILTER_RULE = """
【文学转化铁律——动机注入专用】

以下"当前动机锁定"内容，仅供你（AI）理解角色此刻的内心焦灼、行动优先级和情感底色。

【绝对禁止】在正文中出现以下内容：
  × "任务"、"目标"、"完成条件"、"紧迫程度"等系统化词汇
  × 任何形式的进度描述（"完成了X%"、"还差X步"）
  × 角色在内心独白中直接陈述自己的目标清单
  × 旁白对角色目标的系统化解释

【必须做到的文学转化】将动机转化为以下具体的文学呈现形式：
  · 角色的生理反应：紧迫感 → 呼吸节奏变化、手心的汗、视线反复扫向某处
  · 角色的潜意识动作：时间压力 → 走路无意识加快步频、说话语气比平时更短促
  · 角色内心的画面闪回：情感重量 → 高压时刻某人的脸突然闯入脑海
  · 角色的决策偏向：优先级 → 面对两个选择时某个选项被下意识放弃，读者能感受到但角色没说出来
"""


def _build_quest_motivation_section(state: CreationState, chapter_function: str = "") -> str:
    """
    构建动机锁定注入段（补丁 D：第零步）：
    读取 active_quest_stack 中 status=active 的任务，按紧迫度格式化注入。
    """
    qs = state.get("active_quest_stack") or []
    if not isinstance(qs, list):
        return ""
    active = [q for q in qs if isinstance(q, dict) and q.get("status") == "active"]
    if not active:
        return ""

    # 按紧迫度排序：critical > high > medium > low，core_drive 放最后
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    layer_order = {"immediate": 0, "short_term": 1, "arc_level": 2, "core_drive": 3}
    active.sort(key=lambda q: (
        layer_order.get(q.get("layer", "short_term"), 4),
        order.get(q.get("urgency_level", "low"), 4),
    ))

    lines = ["━━━━━━━━━━━━━━━━━━━━━━━━━━━",
             "第零步：动机锁定（在所有推导之前执行）",
             "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
             "",
             "【当前动机锁定（按紧迫度排序）】",
             ""]

    for q in active:
        layer = q.get("layer", "")
        urg = q.get("urgency_level", "")
        if layer == "core_drive":
            # core_drive 作为背景上层目标
            lines.append(f"〖核心底色驱动〗{q.get('quest_name', '')}")
            continue
        if layer == "arc_level":
            lines.append(f"（卷级背景目标）{q.get('quest_name', '')}：{q.get('current_sub_goal', '')[:80]}")
            continue
        if urg == "critical":
            lines.append(f"⚠️  [紧迫：critical]  任务名：{q.get('quest_name', '')}")
            sg = (q.get("current_sub_goal") or "").strip()
            if sg:
                lines.append(f"  当前子目标：{sg[:150]}")
            ew = (q.get("emotional_weight") or "").strip()
            if ew:
                lines.append(f"  情感重量：{ew[:150]}")
            dn = (q.get("deadline_note") or "").strip()
            if dn:
                lines.append(f"  截止压力：{dn[:80]}")
        elif urg == "high":
            lines.append(f"→  [高优先：high]  任务名：{q.get('quest_name', '')}")
            sg = (q.get("current_sub_goal") or "").strip()
            if sg:
                lines.append(f"  当前子目标：{sg[:120]}")
        else:
            lines.append(f"·  [{urg}]  {q.get('quest_name', '')}：{q.get('current_sub_goal', '')[:80]}")
        lines.append("")

    # 章节功能适配注释
    if chapter_function:
        func_lower = chapter_function.lower()
        if "喘息" in chapter_function or "breath" in func_lower:
            lines.append(
                "注入规则（本章是喘息节点）：immediate 层任务仍然注入，"
                "但以更低的焦虑浓度呈现——不是当前时刻的紧迫行动，"
                "而是背景中的持续压力。"
            )
        elif "引爆" in chapter_function or "climax" in func_lower:
            lines.append(
                "注入规则（本章是引爆节点）：immediate 层任务以最高浓度注入，"
                "本章的引爆应直接服务于或威胁到该任务的完成。"
            )

    lines.append(_LITERARY_FILTER_RULE)
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n")
    return "\n".join(lines)


def _build_lexicon_check_section(state: CreationState) -> str:
    """
    构建词条一致性检查段（补丁 C）：
    从 world_lexicon 提取与本章场景相关词条，列出 hard_constraints，
    提醒 expand1_v43 在状态确认步骤时检查是否违背。
    """
    lexicon = state.get("world_lexicon") or []
    if not lexicon:
        return ""

    # 只取 B/C 类有 active 关联的词条（最相关）
    relevant: list[dict] = []
    for entry in lexicon:
        if not isinstance(entry, dict):
            continue
        ttype = entry.get("term_type", "A")
        dyn   = entry.get("dynamic_associations") or []
        has_active = any(isinstance(d, dict) and d.get("is_active", False) for d in dyn)
        if ttype in ("B", "C") and has_active:
            relevant.append(entry)
        elif ttype == "C":
            relevant.append(entry)

    if not relevant:
        return ""

    lines = ["## 词条一致性检查（补丁C：第一步状态确认新增）\n",
             "以下词条在档案中已确立静态属性，本章使用时须遵守 hard_constraints：\n"]
    for e in relevant[:10]:
        term = e.get("term", "?")
        sp   = e.get("static_profile") or {}
        constraints = sp.get("hard_constraints") or []
        defn = sp.get("definition", "")
        dyn  = e.get("dynamic_associations") or []
        active = next(
            (d for d in reversed(dyn) if isinstance(d, dict) and d.get("is_active", False)),
            None,
        )
        holder_note = ""
        if active:
            holder = active.get("holder") or ""
            assoc  = active.get("association_type", "")
            holder_note = f"（当前 {assoc}：{holder or '未知'}）"
        lines.append(f"  • [{e.get('term_type', 'B')}类] {term}{holder_note}：{defn[:60]}")
        for c in constraints[:3]:
            lines.append(f"    ⚠️ 约束：{c}")
        clue = e.get("incomplete_clue") or {}
        if clue.get("has_incomplete_clue"):
            lines.append(f"    ⚡ 不完整线索：{clue.get('clue_fragment', '')}  触发条件：{clue.get('trigger_condition', '')}")
    lines.append("\n如本章计划使用上述词条，请在 state_audit_note 中确认未违背 hard_constraints，或说明调整方案。")
    return "\n".join(lines) + "\n"


async def expand1_v43_node(state: CreationState, writer: StreamWriter) -> Command:
    """
    v4.3 路径落地确认节点：
    1. 从 current_event_paths 按 path_progress.remaining_paths[0] 读取当前路径定义
    2. 注入真实档案状态（world_archive, protagonist_archive，不再经过 world_tick）
    3. 调用新提示词执行三步落地确认
    4. 输出新字段：path_id, chapter_tone, function_confirmed, chapter_driver 等
    """
    writer({"node_status": "started", "node": "expand1_v43"})

    current_path = _get_current_path_definition(state)
    if not current_path:
        logger_v43.warning("expand1_v43：无法找到当前路径定义，检查 current_event_paths 和 path_progress")
        return Command(
            update={"current_expand1": {}, "expand1_approved": False, "pending_review_type": "expand"},
            goto="path_gen_v43" if state.get("current_event_paths") else "event_chain_gen",
        )

    path_id = current_path.get("path_id", "unknown")

    # 序号标记
    project_id = state.get("project_id", "")
    await _mark_node_writing(project_id, current_path.get("_seq", 0))

    # 格式化路径定义
    try:
        path_definition_text = json.dumps(current_path, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        path_definition_text = str(current_path)

    # 档案状态（直接读取，不经过 world_tick）
    wa = state.get("world_archive") or state.get("world_setting") or {}
    if isinstance(wa, dict) and wa:
        try:
            world_archive_text = json.dumps(wa, ensure_ascii=False, indent=2)
            if len(world_archive_text) > 6000:
                world_archive_text = world_archive_text[:6000] + "\n…（截断）"
        except (TypeError, ValueError):
            world_archive_text = str(wa)[:3000]
    else:
        synopsis = state.get("synopsis") or {}
        world_archive_text = f"世界观摘要：{synopsis.get('world', '（未提供）')}"

    from utils.v42_flow import protagonist_archive_prompt_block as _pab_v43
    pa = state.get("protagonist_archive") or state.get("protagonist_card") or {}
    protagonist_archive_text = _pab_v43(pa) if pa else f"主角名：{state.get('protagonist_name', '（未知）')}"

    # 因果账本
    karmic_ledger = state.get("karmic_ledger") or []
    if isinstance(karmic_ledger, list) and karmic_ledger:
        try:
            karmic_text = json.dumps(karmic_ledger[-15:], ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            karmic_text = str(karmic_ledger)[:3000]
    else:
        karmic_text = "（无）"

    prev_causal = _get_prev_causal_output(state)

    # 用户修改意见（如有）
    bible = state.get("bible") or {}
    raw_feedback = bible.get("rewrite_feedback", "") or current_path.get("chapter_feedback", "")
    feedback_section = ""
    if raw_feedback:
        from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING
        feedback_section = "\n\n" + USER_FEEDBACK_HANDLING.format(user_feedback=raw_feedback)

    # 词条一致性检查段（补丁 C：第一步状态确认新增）
    lexicon_check_section = _build_lexicon_check_section(state)

    # 动机锁定注入段（补丁 D：第零步）
    path_func = current_path.get("narrative_function", "")
    quest_motivation_section = _build_quest_motivation_section(state, chapter_function=path_func)

    user_prompt = EXPAND1_V43_USER_TEMPLATE.format(
        quest_motivation_section=quest_motivation_section,
        path_definition=path_definition_text,
        world_archive=world_archive_text,
        protagonist_archive=protagonist_archive_text,
        karmic_ledger=karmic_text,
        prev_causal_output=prev_causal,
        lexicon_check_section=lexicon_check_section,
        path_id=path_id,
    ) + feedback_section

    # 注入平台风格约束
    _platform_macro = platform_planning_bundle(state, skin_max_chars=0)
    expand1_v43_sys = (
        EXPAND1_V43_SYSTEM
        + (f"\n\n{_platform_macro}\n" if _platform_macro.strip() else "")
    )

    raw = await call_llm_json(expand1_v43_sys, user_prompt, max_tokens=4000)
    result = raw if isinstance(raw, dict) else {}

    # 确保关键字段存在
    result.setdefault("path_id", path_id)
    result.setdefault("chapter_tone", "")
    result.setdefault("function_confirmed", "")
    result.setdefault("chapter_driver", "")
    result.setdefault("key_state_factors", [])
    result.setdefault("causal_input", "")
    result.setdefault("causal_output_direction", "")
    result.setdefault("hidden_seed", "无")
    result.setdefault("quest_context", {
        "injected_quests": [],
        "primary_driver": "",
        "emotional_undercurrent": "",
    })

    return Command(
        update={
            "current_expand1": result,
            "expand1_approved": False,
            "pending_review_type": "expand",
        },
        goto="auto_review" if state.get("auto_mode") else "human_review_expand",
    )
