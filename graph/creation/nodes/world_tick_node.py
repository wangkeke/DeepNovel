"""
world_tick_node：三步命运编织引擎

白皮书·演化层 §4 "世界自转与引力交汇法则" 落地节点。

职责：
  1. 隔离主角，模拟各势力/角色在主角不存在时的独立行动议程（世界暗流自转）
  2. 隔离世界，锁定主角此刻最深的生存刚需（主角生存轨迹）
  3. 找到双方轨迹中的"资源焦点"并校验三项引力交汇标准（引力交汇）
  4. 最多重试 MAX_RETRIES 次；失败后仍透传输出，不阻断流程（expand1 有备用）
  5. 将结果存入 current_world_tick，供下游 expand1 消费

插入位置：
  human_review_path  → world_tick → expand1（首章）
  update_weight      → world_tick → expand1（后续章）
  load（续传有路径）  → world_tick → expand1
"""
from __future__ import annotations

import json
import logging
from langgraph.types import Command, StreamWriter
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from utils.v42_flow import protagonist_archive_prompt_block
from prompts.creation.world_tick import (
    WORLD_TICK_SYSTEM,
    WORLD_TICK_USER_TEMPLATE,
)

logger = logging.getLogger("deepnovel.world_tick")

MAX_RETRIES = 2


# ── 辅助函数 ──────────────────────────────────────────────────────────────────

def _summarize_world_setting(world_setting: dict) -> str:
    """将 world_setting 压缩为简短的势力描述。"""
    if not world_setting:
        return "（世界设定未生成）"
    lines = []
    basic = world_setting.get("basic_rules", "")
    if basic:
        lines.append(f"核心规则：{basic[:120]}")
    for ps in (world_setting.get("power_structure") or [])[:5]:
        lines.append(f"• {str(ps)[:80]}")
    for gz in (world_setting.get("gray_zone_ecology") or [])[:2]:
        lines.append(f"  灰色地带：{str(gz)[:60]}")
    return "\n".join(lines) or "（暂无势力信息）"


def _summarize_char_cards(characters: dict, current_chapter: int, limit: int = 5) -> str:
    """取最近章节活跃的角色做简短摘要。"""
    if not characters:
        return "（无角色信息）"
    # 按 last_seen_seq 降序取前 N 个（不包含主角——主角已在 protagonist_card 里）
    cards = []
    for name, c in characters.items():
        if not isinstance(c, dict):
            continue
        last_seq = c.get("last_seen_seq") or c.get("established_at_seq", 0) or 0
        cards.append((last_seq, name, c))
    cards.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for _, name, c in cards[:limit]:
        role = c.get("current_role", "")
        stance = c.get("stance_to_protagonist", "")
        note = c.get("chapter_behavior_note", "") or c.get("innate_traits_summary", "")
        ec = c.get("emotional_capacity", 100)
        lines.append(
            f"• **{name}** [{role}] 立场：{stance}\n"
            f"  最近动向：{note[:60] or '（无记录）'}  精神阈值余量：{ec}"
        )
    return "\n".join(lines) if lines else "（无近期活跃角色）"


def _build_event_chain_context(
    event_chain: list,
    chain_pos: int,
    node_index: int,
    story_path: list,
) -> str:
    """展示当前批次附近的事件链里程碑（供 World Tick 了解宏观节奏）。"""
    if not event_chain:
        return "（事件链未生成）"
    # 找到当前 story_path 节点对应的 _event_id
    current_event_id: int | None = None
    if node_index < len(story_path):
        eid = story_path[node_index].get("_event_id")
        try:
            current_event_id = int(eid) if eid is not None else None
        except (TypeError, ValueError):
            pass

    lines = []
    for ev in event_chain[max(0, chain_pos - 1): chain_pos + 4]:
        if not isinstance(ev, dict):
            continue
        eid = ev.get("id")
        name = ev.get("event_name") or ev.get("name", "")
        milestone = ev.get("milestone_category", "")
        line_type = ev.get("line_type", "protagonist_line")
        marker = " ◀ 当前" if eid == current_event_id else ""
        lines.append(f"  [{eid}] {name}（{milestone}/{line_type}）{marker}")
    return "\n".join(lines) if lines else "（事件链内容为空）"


def _validate_world_tick(tick: dict) -> tuple[bool, str]:
    """校验 world_tick 最小输出完整性。"""
    if not (tick.get("independent_agendas") or []):
        return False, "independent_agendas 为空：未模拟任何势力的独立行动"
    if not (tick.get("protagonist_need") or "").strip():
        return False, "protagonist_need 为空"
    return True, ""


# ── 主节点 ────────────────────────────────────────────────────────────────────

async def world_tick_node(state: CreationState, writer: StreamWriter) -> Command:
    writer({"node_status": "started", "node": "world_tick"})

    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])

    # ── 幂等跳过：同一章已计算过，直接复用 ────────────────────────────────────
    existing_tick = state.get("current_world_tick") or {}
    if isinstance(existing_tick, dict) and existing_tick.get("node_index") == current_idx:
        logger.info(f"[world_tick] 章节 #{current_idx} 已有 tick，跳过重算直接转 protagonist_collision")
        node_step("三步命运编织（复用缓存）")
        node_done()
        return Command(goto="protagonist_collision")

    # ── 构建输入材料 ──────────────────────────────────────────────────────────
    current_node: dict = story_path[current_idx] if current_idx < len(story_path) else {}
    node_name       = current_node.get("node_name") or f"第{current_idx + 1}章"
    tension_design  = current_node.get("tension_design") or current_node.get("tension_type") or "（未提供）"
    input_state     = current_node.get("input_state_hint") or "（未提供）"
    output_state    = current_node.get("output_state_hint") or "（未提供）"
    prev_output     = current_node.get("scene_result") or state.get("last_action_intent") or "（上章结局未记录）"

    world_setting   = state.get("world_setting") or {}
    bible           = state.get("bible") or {}
    characters      = bible.get("characters") or {}
    event_chain     = state.get("current_event_chain") or []
    chain_pos       = int(state.get("current_event_chain_pos") or 0)
    protagonist_card = state.get("protagonist_card") if isinstance(state.get("protagonist_card"), dict) else {}

    world_setting_summary = _summarize_world_setting(world_setting)
    # 注入完整主角档案（文档 §PROMPT 7 强制输入第1条：全量人物档案）
    prot_archive = protagonist_archive_prompt_block(protagonist_card) if protagonist_card else ""
    char_cards_summary = (
        (prot_archive + "\n\n### 其他近期活跃角色\n" + _summarize_char_cards(characters, current_idx))
        if prot_archive else _summarize_char_cards(characters, current_idx)
    )
    event_chain_context   = _build_event_chain_context(event_chain, chain_pos, current_idx, story_path)

    node_step(f"World Tick（世界自转）推演「{node_name}」")

    # ── LLM 调用 + 重试 ───────────────────────────────────────────────────────
    tick: dict = {}
    for attempt in range(MAX_RETRIES + 1):
        user_content = WORLD_TICK_USER_TEMPLATE.format(
            node_name=node_name,
            tension_design=tension_design,
            input_state_hint=input_state,
            output_state_hint=output_state,
            world_setting_summary=world_setting_summary,
            char_cards_summary=char_cards_summary,
            prev_output_state=prev_output,
            event_chain_context=event_chain_context,
            node_index=current_idx,
        )
        try:
            result = await call_llm_json(WORLD_TICK_SYSTEM, user_content)
            if not isinstance(result, dict):
                raise ValueError("LLM 返回非 dict")
            tick = result
        except Exception as exc:
            logger.warning(f"[world_tick] LLM 调用失败（attempt={attempt}）: {exc}")
            if attempt >= MAX_RETRIES:
                # 降级：生成一个空的 tick，不阻断流程
                tick = {"node_index": current_idx, "_fallback": True}
                break
            continue

        passed, reason = _validate_world_tick(tick)
        if passed:
            logger.info(f"[world_tick] 「{node_name}」校验通过（attempt={attempt}）")
            break

        logger.info(f"[world_tick] 校验失败（attempt={attempt}）：{reason}")
        if attempt >= MAX_RETRIES:
            logger.warning(f"[world_tick] 已达最大重试次数，使用最后输出继续")

    # 确保 node_index 正确记录，供幂等检查
    tick["node_index"] = current_idx

    node_done()
    logger.info(
        f"[world_tick] 完成。agendas={len(tick.get('independent_agendas') or [])}, "
        f"need={(tick.get('protagonist_need') or '')[:30]}"
    )

    return Command(
        update={"current_world_tick": tick},
        goto="protagonist_collision",
    )
