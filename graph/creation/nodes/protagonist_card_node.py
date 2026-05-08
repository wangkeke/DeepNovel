"""
protagonist_card_node：主角人物卡建立节点

在 world_setting 确认后、冰山反推之前执行（v4.2：主角卡 → iceberg_deduction）。
根据 synopsis 生成主角人物卡草稿，用户确认后写入 entity_cards，
并记录 protagonist_name 到 novel_projects，供后续排除首次出场检测。
"""
from __future__ import annotations
import copy
import json
import aiosqlite
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from prompts.creation.world_build import (
    PROTAGONIST_CARD_FROM_USER_SYSTEM,
    PROTAGONIST_CARD_FROM_USER_TEMPLATE,
    PROTAGONIST_FREE_INPUT_HINT,
)
from prompts.creation.synopsis import PLATFORM_MACRO_HINTS
from knowledge.human_logic_lib import get_logic_names_and_essences
from utils.llm import call_llm_json
from memory.entity_db import upsert_entity_card
from utils.v42_flow import shallow_protagonist_archive, shallow_world_archive
from utils.protagonist_card_normalize import normalize_protagonist_card_for_state
from utils.brainwave_engine import protagonist_card_brainwave_suffix
import uuid as _uuid
from config import DB_PATH
import logging

logger = logging.getLogger(__name__)


def _build_core_drive_quest(card: dict) -> dict | None:
    """从主角卡的 core_desire 生成 core_drive 层任务（永远不完成）。"""
    inn_d = card.get("innate_traits_detail") if isinstance(card.get("innate_traits_detail"), dict) else {}
    core_desire = str(inn_d.get("core_desire") or card.get("core_desire") or "").strip()
    if not core_desire:
        return None
    name = (card.get("standard_name") or card.get("name") or "主角").strip()
    quest_id = f"AQ_CORE_{_uuid.uuid4().hex[:6].upper()}"
    return {
        "quest_id": quest_id,
        "quest_name": core_desire[:60],
        "quest_origin": f"protagonist_card（{name}的先天底色与终极驱动力）",
        "urgency_level": "low",
        "deadline_note": None,
        "current_sub_goal": core_desire[:120],
        "layer": "core_drive",
        "completion_condition": "（core_drive 层任务永远不完成，是角色的永恒底色）",
        "failure_condition": None,
        "evolution_on_completion": None,
        "evolution_on_failure": None,
        "status": "active",
        "planted_chapter": "protagonist_card",
        "emotional_weight": f"这是{name}一切行动的底层引擎，驱动所有选择的根本动机。",
    }


_SUBSTITUTE_PROTAGONIST_NAMES = frozenset(
    {"", "主角", "主人公", "男主", "女主", "未命名"}
)


def _world_archive_prompt_block(state: CreationState) -> str:
    ws = state.get("world_setting")
    if not isinstance(ws, dict):
        ws = {}
    wa = state.get("world_archive")
    if not isinstance(wa, dict) or not (
        (wa.get("basic_rules") or "").strip()
        or (wa.get("power_structure") or [])
    ):
        wa = shallow_world_archive(ws)
    body = json.dumps(wa, ensure_ascii=False, indent=2) if wa else "（暂无结构化档案，请仅从 synopsis 推断）"
    ua = state.get("user_anchors")
    if isinstance(ua, dict) and ua:
        body += "\n\n## user_anchors（用户锚点·禁止推翻）\n" + json.dumps(
            ua, ensure_ascii=False, indent=2
        )[:8000]
    return body


def _genesis_protagonist_substantial(pc: dict) -> bool:
    """冰山预填仅作加速：占位卡（见开篇/通用名）须继续走模型生成。"""
    if not isinstance(pc, dict):
        return False
    name = (pc.get("standard_name") or pc.get("name") or "").strip()
    if name in _SUBSTITUTE_PROTAGONIST_NAMES:
        return False
    if (pc.get("appearance") or "").strip() == "见开篇呈现":
        return False
    return True


async def _save_protagonist_to_db(
    project_id: str,
    protagonist_name: str,
    card: dict,
) -> None:
    """将主角人物卡写入 entity_cards，并更新 novel_projects.protagonist_name。"""
    if not project_id or not protagonist_name:
        return
    try:
        habits = card.get("signature_habits") if isinstance(card.get("signature_habits"), list) else []
        data_patch = {
            "appearance":            card.get("appearance", ""),
            "core_motif":            card.get("core_motif", ""),
            "persona":               card.get("persona", ""),
            "signature_habits":      habits,
            "first_appearance_seq":  0,
            "role":                  "protagonist",
            "background_summary":    card.get("background_summary", ""),
            "current_mental_state":  card.get("current_mental_state", ""),
            "mental_growth_path":    card.get("mental_growth_path", ""),
            "reverse_scale":         card.get("reverse_scale", ""),
            "key_life_events":       card.get("key_life_events", []),
            "dominant_logics":       card.get("dominant_logics", []),
            "logic_switch_conditions": card.get("logic_switch_conditions", []),
            "innate_traits":         card.get("innate_traits", []),
            "mental_core":           card.get("mental_core", {}),
            "current_maturity":      card.get("current_maturity", card.get("maturity_level", "")),
            "maturity_level":        card.get("maturity_level", ""),
            "current_emotional_drain": card.get("current_emotional_drain", 0),
            "character_id":            card.get("character_id", ""),
            "world_position":          card.get("world_position", ""),
            "independent_agenda":      card.get("independent_agenda", ""),
            "faction_relationship":    card.get("faction_relationship") or {},
            "mental_core_literary":    card.get("mental_core_literary") or {},
            "innate_traits_detail":    card.get("innate_traits_detail") or {},
            "maturity_level_detail":   card.get("maturity_level_detail") or {},
        }
        if card.get("traits"):
            data_patch["traits"] = card["traits"]
        ti = card.get("trait_interactions")
        if ti and isinstance(ti, dict):
            data_patch["trait_interactions"] = {
                "preset":  ti.get("preset", []),
                "learned": ti.get("learned", []),
            }

        await upsert_entity_card(
            project_id=project_id,
            card_type="character",
            name=protagonist_name,
            data_patch=data_patch,
            seq=0,
            aliases=card.get("aliases", []),
        )

        async with aiosqlite.connect(str(DB_PATH)) as conn:
            await conn.execute(
                """UPDATE novel_projects
                   SET protagonist_name = ?, updated_at = datetime('now')
                   WHERE project_id = ?""",
                (protagonist_name, project_id),
            )
            await conn.commit()
    except Exception as e:
        logger.warning(f"保存主角人物卡失败: {e}")


async def protagonist_card_node(state: CreationState) -> Command:
    synopsis   = state.get("synopsis", {})
    project_id = state.get("project_id", "")
    user_input_answers: dict = dict(state.get("protagonist_user_input") or {})

    genesis_pc = state.get("genesis_protagonist_card") or {}
    if isinstance(genesis_pc, dict) and _genesis_protagonist_substantial(genesis_pc):
        card = dict(genesis_pc)
        card.pop("behavioral_tendencies", None)
        normalize_protagonist_card_for_state(card)
        sh = card.get("signature_habits")
        if isinstance(sh, list):
            card["signature_habits"] = [str(x).strip() for x in sh if str(x).strip()][:2]
        elif isinstance(sh, str) and sh.strip():
            card["signature_habits"] = [sh.strip()]
        else:
            card["signature_habits"] = card.get("signature_habits") or []
        protagonist_name = (card.get("standard_name") or card.get("name") or "").strip() or "主角"
        user_input = interrupt({
            "type": "protagonist_review",
            "content": {"protagonist_name": protagonist_name, "card": card},
        })
        action = user_input.get("action", "approve")
        confirmed = user_input.get("confirmed_card", card)
        if isinstance(confirmed, dict):
            confirmed = copy.deepcopy(confirmed)
            normalize_protagonist_card_for_state(confirmed)
        else:
            confirmed = card
        final_name = (
            confirmed.get("standard_name") or confirmed.get("name") or protagonist_name
        ).strip() or protagonist_name
        if project_id:
            await _save_protagonist_to_db(project_id, final_name, confirmed)
        core_drive_quest = _build_core_drive_quest(confirmed)
        existing_qs = list(state.get("active_quest_stack") or [])
        if core_drive_quest:
            existing_qs = [q for q in existing_qs if q.get("layer") != "core_drive"]
            existing_qs.append(core_drive_quest)
        return Command(
            update={
                "protagonist_name": final_name,
                "protagonist_card": confirmed,
                "protagonist_archive": shallow_protagonist_archive(confirmed),
                "genesis_protagonist_card": {},
                "active_quest_stack": existing_qs,
            },
            goto="iceberg_deduction",
        )

    synopsis_text = json.dumps(synopsis, ensure_ascii=False, indent=2)

    # 旧 checkpoint：四问合并为一条印象，避免永远卡在「未收到印象」
    if not user_input_answers.get("_protagonist_impression_received") and any(
        user_input_answers.get(k) for k in (
            "protagonist_feature", "danger_reaction", "anger_trigger", "obsession",
        )
    ):
        merged = " ".join(
            str(user_input_answers.get(k) or "").strip()
            for k in ("protagonist_feature", "danger_reaction", "anger_trigger", "obsession")
            if user_input_answers.get(k)
        ).strip()
        return Command(
            update={
                "protagonist_user_input": {
                    **user_input_answers,
                    "protagonist_impression": merged,
                    "_protagonist_impression_received": True,
                },
            },
            goto="protagonist_card",
        )

    # 第一步：自由印象输入（一回车也可：由模型按大纲发挥）
    if not user_input_answers.get("_protagonist_impression_received"):
        interrupt_val = interrupt({
            "type": "protagonist_input",
            "content": {"hint": PROTAGONIST_FREE_INPUT_HINT},
        })
        pack = interrupt_val if isinstance(interrupt_val, dict) else {}
        impression = (pack.get("protagonist_impression") or "").strip()
        return Command(
            update={
                "protagonist_user_input": {
                    **{k: v for k, v in user_input_answers.items() if not k.startswith("_")},
                    "protagonist_impression": impression,
                    "_protagonist_impression_received": True,
                },
            },
            goto="protagonist_card",
        )

    impression = (user_input_answers.get("protagonist_impression") or "").strip()
    if impression:
        user_impression_section = f"用户原话：{impression}"
    else:
        user_impression_section = (
            "（用户未填写任何印象，直接回车跳过。请仅依据宏观构思、题材、目标平台与走向，"
            "自行设计主角，仍须写满文档 JSON 中的 appearance、persona、signature_habits、reverse_scale 等必填项。）"
        )

    world_archive_section = _world_archive_prompt_block(state)
    genre_request = (state.get("genre_request") or "").strip() or "通用网文"
    platform_style = (state.get("platform_style") or "").strip() or "通用网文"
    platform_macro_hint = PLATFORM_MACRO_HINTS.get(
        platform_style, PLATFORM_MACRO_HINTS["通用网文"]
    )

    # 第二步：根据印象 + world_archive + synopsis 生成人物卡
    pc_user = PROTAGONIST_CARD_FROM_USER_TEMPLATE.format(
        genre_request=genre_request,
        platform_macro_hint=platform_macro_hint,
        user_impression_section=user_impression_section,
        world_archive_section=world_archive_section,
        synopsis_text=synopsis_text,
        feedback_section="",
        logic_names_and_essences=get_logic_names_and_essences(),
    ) + protagonist_card_brainwave_suffix(state)
    result = await call_llm_json(
        PROTAGONIST_CARD_FROM_USER_SYSTEM,
        pc_user,
    )

    card = result if isinstance(result, dict) else result.get("character_card", result)
    if isinstance(card, dict):
        card.pop("behavioral_tendencies", None)
        normalize_protagonist_card_for_state(card)
        sh = card.get("signature_habits")
        if isinstance(sh, list):
            card["signature_habits"] = [str(x).strip() for x in sh if str(x).strip()][:2]
        elif isinstance(sh, str) and sh.strip():
            card["signature_habits"] = [sh.strip()]
        else:
            card["signature_habits"] = []
    protagonist_name = (card.get("standard_name") or card.get("name") or "").strip()
    if not protagonist_name:
        protagonist_name = "主角"

    user_input = interrupt({
        "type": "protagonist_review",
        "content": {
            "protagonist_name": protagonist_name,
            "card": card,
        },
    })

    action = user_input.get("action", "approve")
    confirmed = user_input.get("confirmed_card", card)
    if isinstance(confirmed, dict):
        confirmed = copy.deepcopy(confirmed)
        normalize_protagonist_card_for_state(confirmed)
    else:
        confirmed = card
    final_name = (
        confirmed.get("standard_name") or confirmed.get("name") or protagonist_name
    ).strip() or protagonist_name
    if project_id:
        await _save_protagonist_to_db(project_id, final_name, confirmed)
    core_drive_quest = _build_core_drive_quest(confirmed)
    existing_qs2 = list(state.get("active_quest_stack") or [])
    if core_drive_quest:
        existing_qs2 = [q for q in existing_qs2 if q.get("layer") != "core_drive"]
        existing_qs2.append(core_drive_quest)
    return Command(
        update={
            "protagonist_name": final_name,
            "protagonist_card": confirmed,
            "protagonist_archive": shallow_protagonist_archive(confirmed),
            "active_quest_stack": existing_qs2,
        },
        goto="iceberg_deduction",
    )
