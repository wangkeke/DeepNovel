"""
write_node：正文写作节点
根据 expand2 的场景设计方案写作正文，返回纯文本（不包装为 JSON）。
使用 core.llm.call_llm_text() 调用，由 config.py 统一管理模型和参数。

同时负责：
  - 注入世界设定卡（静态背景）
  - 检测本节点的首次出场人物，生成人物卡草稿（存入 pending_char_cards）
  - 首次出场人物的外貌描述注入 prompt，要求正文自然带出
"""
from __future__ import annotations
import logging
from langgraph.types import StreamWriter
from schemas.state import CreationState
from prompts.creation.write import WRITE_SYSTEM, WRITE_USER_TEMPLATE
from prompts.creation.world_build import CHAR_CARD_DRAFT_SYSTEM, CHAR_CARD_DRAFT_USER_TEMPLATE
from utils.llm import call_llm, call_llm_json
from memory.entity_db import get_all_ability_names
from utils.mental_core import normalize_mental_core_dict
from config import get_weight_description, DB_PATH
import aiosqlite
from prompts.creation.platform_styles import (
    PLATFORM_STYLES,
    RULE_PRECEDENCE_NOTICE,
    LIVING_COMPANION_RULES,
    POV_AND_CUTAWAY_RULES,
    IMMERSIVE_POV_RULES,
    DEEPNOVEL_LITERARY_CONSTITUTION,
    ADVANCED_LITERARY_RULES,
    platform_macro_user_block,
)
from prompts.common.variable_elasticity import VARIABLE_ELASTICITY_RULE_BLOCK
from utils.v42_flow import protagonist_archive_prompt_block

logger = logging.getLogger(__name__)


def _format_world_setting_section(world_setting: dict) -> str:
    """将世界设定卡格式化为 prompt 前缀段落（静态背景宪法）。"""
    if not world_setting:
        return ""
    lines = ["## 世界设定（全书宪法，写作必须遵守）\n"]
    if br := world_setting.get("basic_rules"):
        lines.append(f"基础规则：{br}")
    gz = world_setting.get("gray_zone_ecology", [])
    if isinstance(gz, list) and gz:
        lines.append("灰色缝隙生态：" + "；".join(str(x) for x in gz))
    for label, key in [("权力结构", "power_structure"), ("地理框架", "geography"),
                        ("世界禁忌", "world_taboos"), ("独特设定", "unique_settings")]:
        items = world_setting.get(key, [])
        if items:
            lines.append(f"{label}：" + "；".join(items))
    return "\n".join(lines) + "\n\n"


async def _get_existing_char_names(project_id: str) -> set[str]:
    """查询 entity_cards 中已存在的人物名（name），用于判断是否首次出场。"""
    if not project_id:
        return set()
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT name FROM entity_cards WHERE project_id = ? AND card_type = 'character'",
                (project_id,)
            ) as cur:
                rows = await cur.fetchall()
        return {r["name"] for r in rows}
    except Exception as e:
        logger.warning(f"查询人物卡失败: {e}")
        return set()


async def _generate_char_card_drafts(
    draft: str,
    new_char_names: list[str],
) -> list[dict]:
    """
    为首次出场人物生成角色卡草稿。
    轻量 LLM 调用，仅用于生成初始草稿，用户在 human_review_write 中确认。
    """
    if not new_char_names:
        return []
    try:
        excerpt = draft[:2000]  # 截取正文前段，足够推断外貌和行为倾向
        char_list = "\n".join(f"- {name}" for name in new_char_names)
        result = await call_llm_json(
            CHAR_CARD_DRAFT_SYSTEM,
            CHAR_CARD_DRAFT_USER_TEMPLATE.format(
                draft_excerpt=excerpt,
                character_names=char_list,
            ),
        )
        cards = result.get("character_cards", [])
        out_cards: list[dict] = []
        for c in cards if isinstance(cards, list) else []:
            if not isinstance(c, dict):
                continue
            c = dict(c)
            c["mental_core"] = normalize_mental_core_dict(c.get("mental_core"))
            if not isinstance(c.get("innate_traits"), list):
                c["innate_traits"] = []
            out_cards.append(c)
        return out_cards
    except Exception as e:
        logger.warning(f"生成人物卡草稿失败: {e}")
        return []


_ABILITY_DETECT_SYSTEM = (
    "你是一个能力识别助手。只提取人物通过训练/觉醒/获得道具等方式习得的技能或特殊手段。"
    "规则文本概念、普通行为、惩罚描述均不是能力。只返回 JSON，不加任何前言。"
)
_ABILITY_DETECT_USER = """\
已知该节点涉及人物：{char_names}
已记录的能力名称（这些不需要特殊标注）：[{known_ability_names}]

正文（节选）：
{draft_excerpt}

请识别正文中人物实际习得或拥有的能力/功法/技能名称。
以下不是能力，不要填入：
  • 规则文本中的惩罚/状态概念（如"失去静默""违反规则"）
  • 人物正在执行的普通行为（如"保持静默"是行为不是能力）
  • 他人提到但该人物未拥有的
返回JSON：
{{
  "abilities_detected": [
    {{"name": "能力名", "char_name": "使用者（不确定填'未知'）", "is_known": true}}
  ]
}}
is_known=true 表示该能力已在已记录列表中；is_known=false 表示首次出现未记录。
"""


async def _detect_ability_usage(
    draft: str,
    key_characters: list[str],
    known_names: set[str],
) -> list[dict]:
    """轻量 LLM 调用，扫描正文中出现的能力名称并标注是否已记录。"""
    if not key_characters:
        return []
    try:
        result = await call_llm_json(
            _ABILITY_DETECT_SYSTEM,
            _ABILITY_DETECT_USER.format(
                char_names="、".join(key_characters),
                known_ability_names="、".join(known_names) if known_names else "（暂无记录）",
                draft_excerpt=draft[:3000],
            ),
        )
        return result.get("abilities_detected", [])
    except Exception as e:
        logger.warning(f"能力检测 LLM 调用失败: {e}")
        return []


async def write_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "write"})
    expand2       = state.get("current_expand2", {})
    blueprint     = state.get("blueprint", {})
    weight        = state.get("blueprint_weight", 0.5)
    world_setting = state.get("world_setting", {})
    project_id    = state.get("project_id", "")
    
    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    current_node = story_path[current_idx] if current_idx < len(story_path) else {}
    node_name    = current_node.get("node_name", f"章节_{current_idx}")

    # 平台风格
    platform = state.get("platform_style", "通用网文")
    platform_style_text = PLATFORM_STYLES.get(platform, "")

    # 主角档案（性别/身份/性格锚点，写作最高约束；防跨题材/性别漂移）
    protagonist_card = state.get("protagonist_card") or {}
    if not protagonist_card.get("standard_name"):
        pn = (state.get("protagonist_name") or "").strip()
        if pn:
            protagonist_card = dict(protagonist_card)
            protagonist_card["standard_name"] = pn
    protagonist_archive_section = ""
    if protagonist_card:
        pa_text = protagonist_archive_prompt_block(protagonist_card, max_chars=3000)
        if pa_text.strip():
            protagonist_archive_section = (
                "## 【已锁定主角档案（最高优先级·写作须与此严格一致）】\n"
                "⚠️ 叙事主视角的姓名、性别、身份与性格**必须**与以下档案完全一致；"
                "禁止引入与档案矛盾的描述，禁止更改主角性别或职衔。\n\n"
                + pa_text
                + "\n\n"
            )

    # 平台+题材+受众定位宏观约束（防选女频写男主、选宫斗写玄幻）
    platform_macro_section = platform_macro_user_block(
        state, heading="目标平台与受众定位（写作风格、感情线浓度、叙事节奏须与此一致）"
    )

    # 用户创作铁则（框架导入时）
    user_write_rules = state.get("user_write_rules", "") or ""
    user_write_rules_section = (
        f"\n\n【用户指定创作铁则（最高优先级，必须严格遵守）】\n{user_write_rules}\n"
        if user_write_rules else ""
    )

    weight_description = get_weight_description(weight)

    # 伏笔植入说明：从 expand2 的 foreshadow_plan 提取
    foreshadow_plan = expand2.get("foreshadow_plan", [])
    plant_instructions = [
        f"  • [{f.get('foreshadow_id', '?')}] "
        f"在「{f.get('target_scene', '?')}」场景中"
        f"{'植入' if f.get('action') == 'plant' else '回收'}："
        f"{f.get('surface_expression', '')}"
        for f in foreshadow_plan
    ]
    foreshadow_plant_instructions = (
        "\n".join(plant_instructions) if plant_instructions else "无特定伏笔任务"
    )

    # 一致性违规（重写时传入）
    consistency_violations = state.get("consistency_result", {}).get("violations", [])
    if isinstance(consistency_violations, list):
        violations_text = "、".join(consistency_violations) if consistency_violations else "无（首稿）"
    else:
        violations_text = str(consistency_violations) if consistency_violations else "无（首稿）"

    # 上一版修改意见（auto_review 或人工回退时注入，如对话占比不足等）
    rewrite_feedback = (state.get("bible", {}) or {}).get("rewrite_feedback", "").strip()
    rewrite_feedback_section = (
        f"\n\n## 上一版修改要求\n\n{rewrite_feedback}\n\n"
        if rewrite_feedback else ""
    )

    # 创世开篇种子：全书首个写作节点须正文衔接，禁止另起炉灶
    completed = state.get("completed_chapters", [])
    opening_seed_section = ""
    _seed = (state.get("synopsis") or {}).get("opening_seed_text") or ""
    vol0 = int(state.get("current_volume_index", 0) or 0) == 0
    if _seed.strip() and current_idx == 0 and not completed and vol0:
        opening_seed_section = (
            "## 【已锁定开篇正文（最高优先级·本书固定开端）】\n\n"
            + _seed.strip()
            + "\n\n【接续铁律 · 极度重要】\n"
            "① 上述文本是本书第一章的**固定开端**，已经完成创作，**禁止重写、改写或再次描述其中已发生的事件**。\n"
            "② 你的写作任务只有一个：从上述文本**最后一句话的场景状态出发**，向后续写新内容。\n"
            "③ 新内容须与下方事件路径链吻合，人物行为、物品状态、地点须与开篇无矛盾。\n"
            "④ 最终输出 = 【上述开篇原文（一字不改地复制）】+【你写的续文】，两段合并为完整章节。\n\n"
        )

    # 上一章结尾承接（非首章时注入，强制本章开头直接承接）
    prev_chapter_section = ""
    if completed:
        prev_ending = completed[-1][-350:] if len(completed[-1]) >= 350 else completed[-1]
        if prev_ending.strip():
            prev_chapter_section = (
                "## ⚠️ 上一章结尾（必须直接承接，不可跳过）\n\n"
                f"上一章最后一段：\n{prev_ending}\n\n"
                "【硬性约束】本章第一段必须直接承接上一章的场面："
                "人物位置、场景、时间线必须连续。"
                "禁止在没有任何交代的情况下切换到新地点或新场景。\n\n"
            )

    # 事件路径链（已由用户确认）→ 主要叙事导航
    event_chain = state.get("pending_event_path_chain", [])
    event_path_chain_text = "\n".join(
        f"  {i + 1}. {step}" for i, step in enumerate(event_chain)
    ) if event_chain else "  （无事件链，按场景设计自由发挥）"

    # ─── 首次出场人物检测（排除主角，主角在 world 后已建立）────────────────────
    key_characters = current_node.get("key_characters", [])
    if isinstance(key_characters, str):
        key_characters = [n.strip() for n in key_characters.split("、") if n.strip()]

    protagonist_name = state.get("protagonist_name", "")
    existing_names = await _get_existing_char_names(project_id)
    # 主角不触发首次出场人物卡确认（已在 protagonist_card 建立）
    candidates = [n for n in key_characters if n not in existing_names]
    new_char_names = [n for n in candidates if n != protagonist_name]

    # 首次出场人物的外貌注入（仅本节点，后续不重复）
    # 此时人物卡草稿还未生成，先用简单提示，草稿在写完正文后生成
    first_appearance_section = ""
    if new_char_names:
        first_appearance_section = (
            "## 首次出场人物（必须在正文中自然带出外貌）\n\n"
            + "\n".join(f"  • {name}：本节首次出场，请用1-2句自然的描写带出最有辨识度的外貌特征"
                        for name in new_char_names)
            + "\n\n"
        )

    # 关键对话（expand2 场景设计产出），必须在正文中体现
    scenes = expand2.get("scenes", [])
    key_dialogues_lines = []
    for sc in scenes:
        dialogues = sc.get("key_dialogues", [])
        for d in dialogues:
            speaker = d.get("speaker", "?")
            listener = d.get("listener", "?")
            surface = d.get("surface_meaning", "")
            hidden = d.get("hidden_meaning", "")
            func = d.get("function", "")
            parts = [f"• {speaker} → {listener}：{surface}（作用：{func}）"]
            if hidden:
                parts.append(f"  潜台词：{hidden}")
            key_dialogues_lines.append("\n".join(parts))
    key_dialogues_section = (
        "\n".join(key_dialogues_lines) if key_dialogues_lines else
        "（本节点无预设关键对话，按事件路径自然发挥）"
    )

    # 动机文学滤镜（补丁 D：动笔前确认步骤）
    expand1_cur = state.get("current_expand1") or {}
    quest_context = expand1_cur.get("quest_context") if isinstance(expand1_cur.get("quest_context"), dict) else {}
    quest_filter_section = ""
    if quest_context and (quest_context.get("primary_driver") or quest_context.get("emotional_undercurrent")):
        driver = (quest_context.get("primary_driver") or "").strip()
        undercurrent = (quest_context.get("emotional_undercurrent") or "").strip()
        quest_filter_section = (
            "## 【动笔前文学滤镜确认（补丁D）】\n\n"
            "在动笔前，先读取以下 quest_context，然后默念这道铁律：\n\n"
            f"  本章主要动机驱动：{driver}\n"
            + (f"  情感底色渗透方式：{undercurrent}\n" if undercurrent else "")
            + "\n"
            "  -> 「主角为什么在这里拼命？」（内心知道答案）\n"
            "  -> 「我会在正文中直接说出这个答案吗？」（绝对不会）\n"
            "  -> 「我会让读者通过主角的身体和行动感受到这个答案吗？」（是的）\n\n"
            "【绝对禁止】在正文中出现：任务、目标、完成条件、进度等系统化词汇；\n"
            "角色在内心独白中直接陈述目标清单；旁白对角色目标的系统化解释。\n\n"
            "确认完毕，开始写作。\n\n"
        )

    # 性格行为预测（expand1 输出），write 按此执行
    expand1 = state.get("current_expand1", {})
    reaction_analysis = expand1.get("character_reaction_analysis", [])
    if reaction_analysis:
        lines = ["## 人物本节行为预测（必须严格遵守）\n"]
        for r in reaction_analysis:
            name = r.get("character_name", "?")
            ext = r.get("external_appearance", "")
            inner = r.get("internal_reality", "")
            detail = r.get("key_detail", "")
            inst = r.get("write_instruction", "")
            lines.append(
                f"{name}：\n  外部表现：{ext}\n  内部实际：{inner}\n  "
                f"关键细节：{detail}\n  执行要求：{inst}"
            )
        character_reaction_section = "\n\n".join(lines) + "\n\n"
    else:
        character_reaction_section = ""
    
    user_prompt = (
        protagonist_archive_section
        + platform_macro_section
        + ("\n\n" if platform_macro_section.strip() else "")
        + WRITE_USER_TEMPLATE.format(
            world_setting_section=_format_world_setting_section(world_setting),
            opening_seed_section=opening_seed_section,
            first_appearance_section=first_appearance_section,
            prev_chapter_section=prev_chapter_section,
            quest_filter_section=quest_filter_section,
            node_name=node_name,
            event_path_chain_text=event_path_chain_text,
            emotional_arc=expand2.get("emotional_arc", ""),
            key_dialogues_section=key_dialogues_section,
            weight_description=weight_description,
            writing_style=blueprint.get("layer2", {}).get("writing_style", ""),
            writing_skills=blueprint.get("layer2", {}).get("writing_skills", ""),
            foreshadow_plant_instructions=foreshadow_plant_instructions,
            violations_if_rewrite=violations_text,
            character_reaction_section=character_reaction_section,
            rewrite_feedback_section=rewrite_feedback_section,
        )
    )

    # 主角身份一致性自检规则注入 system（写作前强制自检）
    prot_name = (protagonist_card.get("standard_name") or "").strip()
    prot_gender_hint = ""
    if prot_name:
        # 从 protagonist_card 中提取性别/身份关键字，给 system 一条硬铁律
        synopsis_prot_desc = (state.get("synopsis") or {}).get("protagonist", "")
        prot_gender_hint = (
            f"\n\n【主角一致性自检铁律（落笔前必须核查）】\n"
            f"本书叙事主角为「{prot_name}」。"
            f"{'设定摘要：' + synopsis_prot_desc[:200] if synopsis_prot_desc else ''}\n"
            "⚠️ 正文中主角的姓名、性别、身份标签（如官职、派系、外貌等）须与已锁定主角档案严格一致。"
            "禁止在正文中以与档案矛盾的性别代词、称谓或身份描述指代主角；"
            "禁止因题材/平台联想而自行更改主角性别。"
        )

    write_system_final = (
        RULE_PRECEDENCE_NOTICE.strip()
        + "\n\n"
        + WRITE_SYSTEM.format(
            platform_style=platform_style_text,
            user_write_rules_section=user_write_rules_section,
        )
        + f"\n\n{LIVING_COMPANION_RULES}"
        + f"\n\n{POV_AND_CUTAWAY_RULES}"
        + f"\n\n{IMMERSIVE_POV_RULES}"
        + f"\n\n{DEEPNOVEL_LITERARY_CONSTITUTION}"
        + f"\n\n{ADVANCED_LITERARY_RULES}"
        + f"\n\n{VARIABLE_ELASTICITY_RULE_BLOCK}"
        + prot_gender_hint
        + "\n"
    )
    draft = await call_llm(
        write_system_final,
        user_prompt,
        max_tokens=8000,
    )

    # 开篇种子此前仅作 prompt 上下文；若不拼入正文，入库后读者看不到（无头尸首章）
    if (
        _seed.strip()
        and current_idx == 0
        and not completed
        and vol0
    ):
        draft = _seed.strip() + "\n\n" + (draft or "").strip()

    # ─── 生成首次出场人物卡草稿 ──────────────────────────────────────────────
    pending_char_cards: list[dict] = []
    if new_char_names:
        pending_char_cards = await _generate_char_card_drafts(draft, new_char_names)

    # ─── 能力使用检测：扫描正文，标注已知/未知能力 ───────────────────────────
    pending_ability_checks: list[dict] = []
    if project_id and key_characters:
        try:
            known_ability_names = await get_all_ability_names(project_id, key_characters)
            detected = await _detect_ability_usage(draft, key_characters, known_ability_names)
            # 只保留未记录的能力（is_known=False）
            pending_ability_checks = [
                {
                    "ability_name": ab.get("name", ""),
                    "char_name":    ab.get("char_name", "未知"),
                }
                for ab in detected
                if not ab.get("is_known", True) and ab.get("name")
            ]
        except Exception as e:
            logger.warning(f"能力使用检测失败: {e}")

    # ─── 词条伏笔预提取（供 human_review_write 展示）─────────────────────────────
    out = {
        "current_draft":          draft,
        "pending_char_cards":     pending_char_cards,
        "pending_ability_checks": pending_ability_checks,
        "pending_noun_foreshadows": [],
    }
    if state.get("auto_mode"):
        out["pending_review_type"] = "write"
    return out
