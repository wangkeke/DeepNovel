"""
human_review_write_node：write 后的正文质量确认节点

若 state 中有 pending_trait_interaction_update（来自上一节 bible_update 的检测），
在用户批准本章时一并展示，用户确认后追加 learned 叠加规则。

在 write_node 生成正文后介入，用户看到实际写出来的文字效果。
同时：若本章有首次出场的新人物（write_node 生成了 pending_char_cards），
      将人物卡草稿一并展示，用户可确认或修改。

[1] 满意，存库继续       → bible_update（chapter_approved=True）
[2] 文笔/节奏有问题      → expand2（重跑场景设计+写作，保持 expand1 方向不变）
[3] 方向有问题，大改     → expand1（从头重新分析，代价最大）

职责：质量确认，防止文笔不满意。方向问题应尽量在 human_review_expand 阶段拦住。
"""
from __future__ import annotations
import logging
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.path_relay import v43_chapter_display_name
from memory.entity_db import append_learned_trait_interaction
from utils.llm import call_llm_json
from utils.text_metrics import prose_char_count

logger = logging.getLogger(__name__)


async def parse_user_feedback(feedback: str) -> dict:
    """
    对用户修改意见做前置解析，提取确定性信息和方向性信息。
    结果存入 bible.rewrite_feedback_parsed，供 expand1 使用。
    """
    if not feedback or not feedback.strip():
        return {"confirmed_facts": [], "direction": "", "placeholder_names": []}

    result = await call_llm_json(
        system=(
            "你是一个小说编辑助手。"
            "分析用户的修改意见，区分必须保留的事实和需要创作转化的方向。"
            "只返回 JSON，不加任何前言。"
        ),
        user=f"""
用户修改意见：
{feedback}

请提取：
1. confirmed_facts：用户明确说出的、必须在小说中体现的具体事实
   （经历、关系、动机、情感基调等，不包括人物名字）
2. direction：用户想要的逻辑方向或情节走向（一句话概括）
3. placeholder_names：意见中出现的、明显是占位符的名字
   （如张三、李四、某人等，这些名字不应直接用在小说里）

返回 JSON：
{{
  "confirmed_facts": ["事实1", "事实2"],
  "direction": "方向描述",
  "placeholder_names": ["张三"]
}}
""",
    )
    return result or {"confirmed_facts": [], "direction": feedback, "placeholder_names": []}


async def human_review_write_node(state: CreationState) -> Command:
    draft                  = state.get("current_draft", "")
    chain                  = state.get("pending_event_path_chain", [])
    current_idx            = state.get("current_node_index", 0)
    story_path             = state.get("story_path", [])
    pending_char_cards     = state.get("pending_char_cards", [])
    pending_ability_checks = state.get("pending_ability_checks", [])
    pending_noun_foreshadows = state.get("pending_noun_foreshadows", [])

    node_name = (
        story_path[current_idx].get("node_name", f"第{current_idx + 1}章")
        if current_idx < len(story_path)
        else f"第{current_idx + 1}章"
    )
    if state.get("current_event_paths") and (state.get("path_progress") or {}).get("paths_status"):
        node_name = v43_chapter_display_name(state)

    pending_trait_updates = state.get("pending_trait_interaction_update", [])

    project_id = state.get("project_id", "")
    global_seq = story_path[current_idx].get("_seq", current_idx + 1) if current_idx < len(story_path) else current_idx + 1

    # narrative_extract 在 approve 后触发，审核界面不展示旧的 noun_foreshadow 数据
    new_foreshadows: list = []
    advanced_foreshadows: list = []

    tension_minor_issues = state.get("tension_minor_issues", [])

    interrupt_payload: dict = {
        "type": "write_review",
        "project_id": project_id,
        "content": {
            "node_name":                      node_name,
            "node_index":                     current_idx,
            "event_path_chain":               chain,
            "draft_preview":                  draft[:600] + ("…" if len(draft) > 600 else ""),
            "word_count":                     prose_char_count(draft),
            "pending_ability_checks":         pending_ability_checks,
            "pending_trait_interaction_update": pending_trait_updates,
            "pending_noun_foreshadows":       pending_noun_foreshadows,
            "new_foreshadows":                new_foreshadows,
            "advanced_foreshadows":           advanced_foreshadows,
            "tension_minor_issues":           tension_minor_issues,
        },
    }

    # 如果有新人物卡草稿，附在 interrupt payload 里供用户确认
    if pending_char_cards:
        interrupt_payload["new_character_cards"] = pending_char_cards
        interrupt_payload["content"]["has_new_characters"] = True

    user_input = interrupt(interrupt_payload)

    action   = user_input.get("action", "approve")
    feedback = user_input.get("feedback", "").strip()

    # 用户确认/修改的人物卡（approve 路径才保存）
    confirmed_char_cards = user_input.get("confirmed_char_cards", pending_char_cards)

    # 用户对未记录能力的处理决定
    # ability_decisions: list[{ability_name, char_name, decision: "add"|"extend"|"ignore"}]
    # decision="add" → 新能力，加到人物卡；"extend"→已有能力自然延伸，不单独记录；"ignore"→笔误
    ability_decisions: list[dict] = user_input.get("ability_decisions", [])

    # 用户对特质叠加变化的确认（Y=追加 learned，N=跳过）
    trait_interaction_confirmed = user_input.get("trait_interaction_confirmed", False)

    # 用户对词条伏笔 story_potential 的补充（surface_meaning -> story_potential）
    noun_foreshadow_story_potential_edits = user_input.get("noun_foreshadow_story_potential_edits", {})

    if action == "approve":
        project_id = state.get("project_id", "")
        if trait_interaction_confirmed and pending_trait_updates and project_id:
            for ti in pending_trait_updates:
                char_name = ti.get("character_name", "")
                suggested = ti.get("suggested_interaction", {})
                seq = ti.get("seq", 0)
                if not char_name or not suggested:
                    continue
                interaction = {
                    **suggested,
                    "learned_from_seq": seq,
                    "trigger_event":   ti.get("trigger_event", ""),
                }
                try:
                    await append_learned_trait_interaction(project_id, char_name, interaction)
                except Exception as e:
                    logger.warning(f"append_learned_trait_interaction 失败 ({char_name}): {e}")

        return Command(
            update={
                "chapter_approved":            True,
                "confirmed_char_cards":        confirmed_char_cards,
                "pending_char_cards":          [],
                "ability_decisions":           ability_decisions,
                "pending_ability_checks":      [],
                "pending_trait_interaction_update": [],
                "pending_noun_foreshadows":    [],
                "noun_foreshadow_story_potential_edits": noun_foreshadow_story_potential_edits,
            },
            goto="narrative_extract",
        )

    updated_path = list(story_path)
    node_patch   = updated_path[current_idx] if current_idx < len(updated_path) else {}

    if action == "rewrite_prose":
        # 只重跑 expand2+write，保留 expand1 的分析方向
        if current_idx < len(updated_path):
            updated_path[current_idx] = {
                **node_patch,
                "prose_feedback": feedback,
                "chapter_feedback": "",      # 清除上次方向意见
            }
        return Command(
            update={
                "chapter_approved":         False,
                "story_path":               updated_path,
                "pending_event_path_chain": [],
                "pending_char_cards":       [],
                "pending_ability_checks":   [],
                "pending_noun_foreshadows": [],
                "current_draft":            "",
            },
            goto="expand2",
        )

    else:  # rewrite_direction → 回到 expand1
        parsed = await parse_user_feedback(feedback) if feedback else {}
        if current_idx < len(updated_path):
            updated_path[current_idx] = {
                **node_patch,
                "chapter_feedback": feedback,
                "prose_feedback":   "",      # 清除上次文笔意见
            }
        bible_update = {
            **state.get("bible", {}),
            "rewrite_feedback": feedback,
            "rewrite_feedback_parsed": parsed,
        }
        return Command(
            update={
                "chapter_approved":         False,
                "expand1_approved":         False,
                "expand1_event_draft":      [],
                "story_path":               updated_path,
                "bible":                    bible_update,
                "pending_event_path_chain": [],
                "pending_char_cards":       [],
                "pending_ability_checks":   [],
                "pending_noun_foreshadows": [],
                "current_draft":            "",
            },
            goto="expand1",
        )
