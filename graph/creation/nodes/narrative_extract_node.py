"""
narrative_extract_node：叙事信息提取节点

在正文通过 auto_review / human_review_write 之后触发，以分析者视角：
1. 提取真正的伏笔（因果判断，不是名词扫描）
2. 还原本章实际叙事路径链，并与 path_gen 规划对比
3. 识别并注册世界词条（World Lexicon）
4. 提取 Scene Snapshot（章末物理/资产/悬念基准，补丁 F）

被打回重写的正文不触发此节点，避免对废稿做无效提取。
"""
from __future__ import annotations
import json
import logging
from langgraph.types import StreamWriter
from schemas.state import CreationState
from prompts.creation.narrative_extract import (
    NARRATIVE_EXTRACT_SYSTEM,
    NARRATIVE_EXTRACT_USER_TEMPLATE,
)
from utils.llm import call_llm_json
from utils.display import node_step, node_done, console
from rich.panel import Panel
from memory.db import get_active_lexicon_entries
from utils.path_relay import effective_chapter_draft

logger = logging.getLogger(__name__)


def _build_planned_paths_text(state: CreationState) -> str:
    """从 current_event_paths 提取 path_gen 原始路径规划文本。"""
    event_paths = state.get("current_event_paths") or {}
    if not event_paths:
        return "（无 path_gen 规划数据）"

    event_name = event_paths.get("event_name", "")
    paths = event_paths.get("paths") or []
    if not paths:
        return f"事件：{event_name}\n（无路径数据）"

    lines = [f"事件：{event_name}"]
    for i, p in enumerate(paths, 1):
        path_id   = p.get("path_id", f"path_{i}")
        moment    = p.get("moment_description") or p.get("narrative_function", "")
        func      = p.get("narrative_function", "")
        key_scene = p.get("key_scene", "")
        ptn       = (p.get("path_to_next") or "").strip()
        extra = ""
        if ptn:
            extra += f"\n     过渡到（path_to_next）：{ptn}"
        lines.append(
            f"  {i}. [{path_id}] {moment}"
            + (f"（{func}）" if func and func != moment else "")
            + (f"\n     关键场景：{key_scene}" if key_scene else "")
            + extra
        )
    gexit = (event_paths.get("scene_exit") or "").strip()
    if gexit:
        lines.append(f"\n全章 scene_exit（最后一拍后须停于此，不得越界）：\n  {gexit}")
    return "\n".join(lines)


def _build_event_planning_context(state: CreationState) -> str:
    """注入 narrative_extract：event_result_type 与 tick 类型，引导伏笔从严/从宽。"""
    ev = state.get("current_event") or {}
    if not isinstance(ev, dict) or not ev:
        return "（尚无 current_event；按正文做中性提取）"
    cc = ev.get("causal_chain") if isinstance(ev.get("causal_chain"), dict) else {}
    er = str(cc.get("event_result_type") or "").strip()
    imm = str(cc.get("immediate_effect") or "").strip()[:160]
    hid = str(cc.get("hidden_seeds") or "").strip()[:220]
    pt = ev.get("protagonist_tick") if isinstance(ev.get("protagonist_tick"), dict) else {}
    ptt = str(pt.get("protagonist_tick_type") or "").strip()
    summ = str(ev.get("event_summary") or "").strip()[:120]
    lines = [
        f"event_result_type: {er or '（缺省）'}",
        f"protagonist_tick_type: {ptt or '（缺省）'}",
        f"event_summary: {summ or '（无）'}",
    ]
    if imm:
        lines.append(f"immediate_effect（规划）: {imm}")
    if hid:
        lines.append(f"hidden_seeds（规划）: {hid}")
    return "\n".join(lines)


def _build_karmic_ledger_summary(state: CreationState) -> str:
    """汇总当前 karmic_ledger 已有伏笔，供去重参考。"""
    ledger = state.get("karmic_ledger") or []
    if not ledger:
        # 兼容 bible 存储
        bible = state.get("bible") or {}
        ledger = bible.get("karmic_seeds_inventory") or []

    if not ledger:
        return "（当前无已有伏笔）"

    lines = []
    for seed in ledger[:30]:  # 最多展示30条避免 prompt 过长
        sid  = seed.get("seed_id") or seed.get("foreshadow_id", "?")
        desc = seed.get("description") or seed.get("surface_meaning", "")
        payoff = seed.get("estimated_payoff") or seed.get("story_potential", "")
        lines.append(f"  [{sid}] {desc}  →引爆方向：{payoff}")
    return "\n".join(lines)


def _build_world_entities_text(state: CreationState) -> str:
    """提取 world_archive 中的势力和地点名称。"""
    world_archive = state.get("world_archive") or {}
    world_setting = state.get("world_setting") or {}

    lines: list[str] = []

    # 势力
    factions = world_archive.get("gray_factions") or world_setting.get("power_structure") or []
    if isinstance(factions, list) and factions:
        faction_names = []
        for f in factions:
            if isinstance(f, dict):
                faction_names.append(f.get("name") or str(f))
            else:
                faction_names.append(str(f))
        if faction_names:
            lines.append("势力：" + "、".join(faction_names[:20]))

    # 地点
    geo = world_archive.get("geography") or world_setting.get("geography") or []
    if isinstance(geo, list) and geo:
        geo_names = [str(g) for g in geo[:20]]
        lines.append("地点：" + "、".join(geo_names))
    elif isinstance(geo, str) and geo:
        lines.append(f"地点：{geo[:200]}")

    return "\n".join(lines) if lines else "（无已注册势力/地点数据）"


async def _build_existing_lexicon_text(project_id: str, state: CreationState) -> str:
    """汇总当前 world_lexicon 已有词条，供 LLM 判断 new / update。"""
    # 优先从 state 读（最新）
    lexicon_state = state.get("world_lexicon") or []
    if lexicon_state:
        lines = []
        for entry in lexicon_state[:40]:
            if not isinstance(entry, dict):
                continue
            lid   = entry.get("lexicon_id", "?")
            term  = entry.get("term", "?")
            ttype = entry.get("term_type", "A")
            defn  = (entry.get("static_profile") or {}).get("definition", "")
            lines.append(f"  [{lid}] {term}（{ttype}类）：{defn[:60]}")
        if lines:
            return "\n".join(lines)

    # state 无数据则从 DB 读
    if not project_id:
        return "（当前词条库为空）"
    try:
        entries = await get_active_lexicon_entries(project_id, limit=40)
        if not entries:
            return "（当前词条库为空）"
        lines = []
        for e in entries:
            lid   = e.get("lexicon_id", "?")
            term  = e.get("term", "?")
            ttype = e.get("term_type", "A")
            defn  = e.get("static_profile", {}).get("definition", "")
            lines.append(f"  [{lid}] {term}（{ttype}类）：{defn[:60]}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning(f"读取 world_lexicon 失败: {exc}")
        return "（词条库读取失败）"


async def narrative_extract_node(
    state: CreationState,
    writer: StreamWriter,
) -> dict:
    """
    以分析者视角提取已审核正文的伏笔、叙事路径链和世界词条。
    输出写入 state['narrative_extract_result']。
    """
    node_step("叙事信息提取（伏笔 + 路径链 + 词条）")

    raw_draft = str(state.get("current_draft") or "")
    draft = effective_chapter_draft(state)
    used_all_paths_fallback = not raw_draft.strip() and bool((draft or "").strip())
    if not draft.strip():
        logger.warning("narrative_extract: 正文为空，跳过提取")
        node_done("正文为空，跳过")
        return {"narrative_extract_result": {}}

    project_id = state.get("project_id", "")

    # 构建上下文
    planned_paths_text    = _build_planned_paths_text(state)
    karmic_ledger_summary = _build_karmic_ledger_summary(state)
    world_entities_text   = _build_world_entities_text(state)
    existing_lexicon_text = await _build_existing_lexicon_text(project_id, state)

    # 章节号（用于生成 foreshadow_id 前缀）
    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    global_seq  = (
        story_path[current_idx].get("_seq", current_idx + 1)
        if current_idx < len(story_path)
        else current_idx + 1
    )

    # 当前事件 ID（供 dynamic_association 注入）
    current_event   = state.get("current_event") or {}
    current_event_id = current_event.get("event_id", "")

    user_prompt = NARRATIVE_EXTRACT_USER_TEMPLATE.format(
        draft=draft[:8000],
        planned_paths=planned_paths_text,
        event_planning_context=_build_event_planning_context(state),
        karmic_ledger_summary=karmic_ledger_summary,
        world_entities=world_entities_text,
        existing_lexicon=existing_lexicon_text,
    )

    try:
        result = await call_llm_json(
            NARRATIVE_EXTRACT_SYSTEM,
            user_prompt,
        )
    except Exception as e:
        logger.warning(f"narrative_extract LLM 调用失败: {e}")
        result = {}

    foreshadows      = result.get("foreshadows") or []
    path_chain_info  = result.get("chapter_path_chain") or {}
    lexicon_updates  = result.get("lexicon_updates") or []
    scene_snapshot   = result.get("scene_snapshot") or {}
    if isinstance(scene_snapshot, dict) and scene_snapshot:
        scene_snapshot = dict(scene_snapshot)
        scene_snapshot.setdefault("chapter_id", str(global_seq))

    # 为未设置 foreshadow_id 的条目补充 ID
    for i, f in enumerate(foreshadows):
        if not f.get("foreshadow_id"):
            f["foreshadow_id"] = f"F{global_seq:03d}_{i + 1:02d}"

    # 为词条更新补全 chapter_id / event_id
    for lu in lexicon_updates:
        if isinstance(lu, dict):
            da = lu.get("dynamic_association")
            if isinstance(da, dict):
                if not da.get("chapter_id"):
                    da["chapter_id"] = str(global_seq)
                if not da.get("event_id") and current_event_id:
                    da["event_id"] = current_event_id

    new_count    = sum(1 for f in foreshadows if f.get("karmic_ledger_action") == "new")
    update_count = sum(1 for f in foreshadows if f.get("karmic_ledger_action") == "update")
    deviation    = path_chain_info.get("deviation_exists", False)
    deviation_label = "[!] 有偏差" if deviation else "[OK] 路径一致"
    lex_new   = sum(1 for lu in lexicon_updates if lu.get("action") == "new")
    lex_upd   = sum(1 for lu in lexicon_updates if lu.get("action") in ("update_static", "update_dynamic"))

    node_done(
        f"伏笔：新增 {new_count}，追加 {update_count}  |  "
        f"词条：新注册 {lex_new}，更新 {lex_upd}  |  路径：{deviation_label}"
    )

    # ── CLI 展示：路径链 + 伏笔 + 词条（文档第八节 + 补丁C）──────────────────────
    _display_narrative_extract_result(
        foreshadows, path_chain_info, new_count, update_count, lexicon_updates, scene_snapshot
    )

    out: dict = {
        "narrative_extract_result": {
            "foreshadows":        foreshadows,
            "chapter_path_chain": path_chain_info,
            "lexicon_updates":    lexicon_updates,
            "scene_snapshot":     scene_snapshot if isinstance(scene_snapshot, dict) else {},
            "global_seq":         global_seq,
        }
    }
    # 下游 bible_update 读 current_draft；若此前仅 all_paths_text 有稿，在此回填以免入库空串
    if used_all_paths_fallback:
        out["current_draft"] = draft
        logger.info(
            "narrative_extract：已用 path_progress.all_paths_text 回填 state.current_draft 供 bible_update"
        )
    return out


def _display_narrative_extract_result(
    foreshadows: list,
    path_chain_info: dict,
    new_count: int,
    update_count: int,
    lexicon_updates: list | None = None,
    scene_snapshot: dict | None = None,
) -> None:
    """在 CLI 展示 narrative_extract 提取的路径链和伏笔（文档第八节规范）。"""
    # ── 路径链面板 ──
    actual_chain  = path_chain_info.get("actual_chain", "")
    planned_chain = path_chain_info.get("planned_chain", "")
    deviation     = path_chain_info.get("deviation_exists", False)
    deviation_note = path_chain_info.get("deviation_note", "")

    chain_content = ""
    if actual_chain:
        chain_content += f"[bold]本章叙事路径链（实际）：[/bold]\n{actual_chain}\n\n"
    if planned_chain:
        chain_content += f"[bold]path_gen 规划：[/bold]\n{planned_chain}\n\n"
    if deviation:
        chain_content += f"[yellow][!] 路径偏差：{deviation_note}[/yellow]"
    else:
        chain_content += "[green][OK] 路径执行一致[/green]"

    if chain_content.strip():
        console.print(Panel(
            chain_content.strip(),
            title="本章叙事路径链（分析者还原）",
            border_style="cyan",
            expand=False,
        ))

    # ── Scene Snapshot（补丁 F）──────────────────────────────────────────────
    if isinstance(scene_snapshot, dict) and scene_snapshot:
        loc = scene_snapshot.get("location") or {}
        micro = loc.get("micro", "") if isinstance(loc, dict) else ""
        cliff = scene_snapshot.get("cliffhanger_level", "")
        last_s = (scene_snapshot.get("last_sentence") or "")[:120]
        snap_lines = [
            f"[bold]cliffhanger_level[/bold]: {cliff}",
            f"[bold]精确位置 micro[/bold]: {micro}" if micro else "",
            f"[bold]末句摘录[/bold]: {last_s}{'…' if len(str(scene_snapshot.get('last_sentence', ''))) > 120 else ''}",
        ]
        console.print(Panel(
            "\n".join(x for x in snap_lines if x),
            title="Scene Snapshot（章末物理基准）",
            border_style="magenta",
            expand=False,
        ))

    # ── 伏笔面板 ──
    if not foreshadows:
        return

    new_lines    = []
    update_lines = []
    for f in foreshadows:
        fid    = f.get("foreshadow_id", "?")
        surf   = f.get("surface_appearance", "")[:80]
        payoff = f.get("estimated_payoff_type", "")
        action = f.get("karmic_ledger_action", "new")
        if action == "new":
            new_lines.append(f"  • [{fid}] {surf}\n    引爆方向：{payoff}")
        else:
            target = f.get("update_target_id", "?")
            new_lines.append(f"  • 追加至 [{target}]：{surf}")

    panel_lines = []
    if new_lines:
        panel_lines.append(f"[bold]新增（真正的伏笔）[/bold]（{new_count} 条）")
        panel_lines.extend(new_lines[:10])
    if update_lines:
        panel_lines.append(f"\n[bold]已有伏笔追加细节[/bold]（{update_count} 条）")
        panel_lines.extend(update_lines[:5])

    if panel_lines:
        console.print(Panel(
            "\n".join(panel_lines),
            title="🔖  伏笔记录（因果判断）",
            border_style="dim",
            expand=False,
        ))

    # ── 词条面板 ──
    if not lexicon_updates:
        return

    lex_lines = []
    for lu in lexicon_updates:
        if not isinstance(lu, dict):
            continue
        term   = lu.get("term", "?")
        ttype  = lu.get("term_type", "A")
        action = lu.get("action", "new")
        cat    = lu.get("category", "")
        defn   = (lu.get("static_profile") or {}).get("definition", "")[:60]
        clue   = (lu.get("incomplete_clue") or {})
        has_clue = clue.get("has_incomplete_clue", False)
        action_label = {"new": "🆕 新注册", "update_static": "📝 追加属性", "update_dynamic": "🔄 更新关联"}.get(action, action)
        lex_lines.append(
            f"  {action_label}  [{ttype}类/{cat}] {term}"
            + (f"：{defn}" if defn else "")
            + (" ⚡不完整线索" if has_clue else "")
        )

    if lex_lines:
        console.print(Panel(
            "\n".join(lex_lines),
            title="📦  世界词条库更新",
            border_style="blue",
            expand=False,
        ))
