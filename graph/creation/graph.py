"""
小说创作流图（NovelCreationGraph）

图结构：
```
START → load ──┬── (新项目) v4.2：idea_forge → human_review_brainwave → world_build → human_review_world → protagonist_card
               │              → iceberg_deduction → human_review_iceberg → genesis_ignition
               │              → core_cast_gen → human_review_core_cast → story_arc_plan → …
               │              （开篇种子在冰山与人物/世界档案之后点燃；核心班底由 core_cast_gen 生成，配角由 bible_update 生长）
               ├── (续传，有路径)  → world_tick（章节三步引擎）
               └── (续传，无路径) ─┘
                                   path_gen → human_review_path（批准）

【章节三步命运编织引擎（章节级；幂等）】
human_review_path(批准) / update_weight(未完) / load(续传) → world_tick → protagonist_collision → expand1

expand1 → human_review_expand（方向确认）
              ↓ 批准                ↓ 修改 → expand1
          expand2 → write → consistency → tension_check → human_review_write（质量确认）
              ↑                    ↓ [1] 满意    → bible_update
              │                    ↓ [2] 文笔问题 → expand2（保持方向）
              └────────────────────↓ [3] 方向问题 → expand1

bible_update → update_weight
    ↓ continue   → world_tick（下章三步引擎）
    ↓ batch_done → human_review_batch
         ├── [1] continue → path_gen（下一批）
         └── [2] done     → END

[legacy] synopsis → human_review_synopsis（v4.2 不走此路，仅保留兼容）
```
"""
from langgraph.graph import StateGraph, END, START
from schemas.state import CreationState
from memory.checkpointer import get_checkpointer

from graph.creation.nodes.blueprint_load_node import blueprint_load_node
from graph.creation.nodes.synopsis_node import synopsis_node
from graph.creation.nodes.idea_forge_node import idea_forge_node
from graph.creation.nodes.genesis_ignition_node import genesis_ignition_node
from graph.creation.nodes.iceberg_deduction_node import iceberg_deduction_node
from graph.creation.nodes.human_review_iceberg_node import human_review_iceberg_node
from graph.creation.nodes.human_review_node import (
    human_review_synopsis_node,
    human_review_path_node,
)

from graph.creation.nodes.world_build_node import world_build_node
from graph.creation.nodes.human_review_world_node import human_review_world_node
from graph.creation.nodes.human_review_brainwave_node import human_review_brainwave_node
from graph.creation.nodes.protagonist_card_node import protagonist_card_node
from graph.creation.nodes.human_review_expand_node import human_review_expand_node
from graph.creation.nodes.human_review_write_node import human_review_write_node
from graph.creation.nodes.human_review_role_shift_node import human_review_role_shift_node
from graph.creation.nodes.path_gen_node import path_gen_node, path_gen_v43_node
from graph.creation.nodes.expand1_node import expand1_node, expand1_v43_node
from graph.creation.nodes.expand2_node import expand2_node
from graph.creation.nodes.write_node import write_node
from graph.creation.nodes.path_state_extract_node import path_state_extract_node
from graph.creation.nodes.bible_update_node import bible_update_node, _bible_update_v43_routing
from graph.creation.nodes.auto_arc_transition_node import auto_arc_transition_node
from graph.creation.nodes.update_weight_node import update_weight_node
from graph.creation.nodes.human_review_batch_node import human_review_batch_node
from graph.creation.nodes.auto_review_node import auto_review_node
from graph.creation.nodes.mode_select_node import mode_select_node
from graph.creation.nodes.tension_check_node import tension_check_node
from graph.creation.nodes.consistency_node import consistency_node

from graph.creation.nodes.human_review_story_arc_node import human_review_story_arc_node
from graph.creation.nodes.story_arc_plan_node import story_arc_plan_node
from graph.creation.nodes.event_chain_gen_node import event_chain_gen_node
from graph.creation.nodes.human_review_event_chain_node import human_review_event_chain_node
from graph.creation.nodes.core_cast_gen_node import core_cast_gen_node
from graph.creation.nodes.human_review_core_cast_node import human_review_core_cast_node
from graph.creation.nodes.world_tick_node import world_tick_node
from graph.creation.nodes.protagonist_collision_node import protagonist_collision_node
from graph.creation.nodes.narrative_extract_node import narrative_extract_node


# ─── 路由函数 ─────────────────────────────────────────────────────────────────

def _route_after_load(state: CreationState) -> str:
    """
    load 节点之后的路由：
      - 续传且有未完成路径 → expand1（直接继续写）
      - 续传但当前批次全完 → path_gen（规划下一批）
      - 新项目             → idea_forge → human_review_brainwave → world_build → … → genesis_ignition → story_arc_plan
    """
    if state.get("resume_from_db"):
        if state.get("story_path"):
            return "world_tick"  # 续传有路径 → 先过章节级三步引擎
        return "path_gen"
    return "idea_forge"


def check_creation_done(state: CreationState) -> str:
    """
    创作完成路由：
      - 当前批次节点全部写完 → batch_done
      - 未完成 → continue（expand1 下一个节点）
    """
    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    return "continue" if current_idx < len(story_path) else "batch_done"


def _is_batch_done(state: CreationState) -> bool:
    """当前批次节点是否全部写完"""
    current_idx = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    return current_idx >= len(story_path)


def route_review(state: CreationState) -> str:
    """根据 auto_mode 决定走人工确认还是自动确认"""
    if state.get("auto_mode"):
        return "auto_review"
    review_type = state.get("pending_review_type", "")
    return {
        "path":   "human_review_path",
        "expand": "human_review_expand",
        "write":  "human_review_write",
        "batch":  "human_review_batch",
    }.get(review_type, "human_review_path")


# ─── 图构建 ───────────────────────────────────────────────────────────────────

async def build_creation_graph(db_path: str = "workspace/blueprints.db"):
    """构建创作流图，挂载 Checkpointer"""
    builder = StateGraph(CreationState)

    # ── 节点注册 ──
    builder.add_node("load",                    blueprint_load_node)
    builder.add_node("idea_forge",              idea_forge_node)
    builder.add_node("genesis_ignition",        genesis_ignition_node)
    builder.add_node("iceberg_deduction",        iceberg_deduction_node)
    builder.add_node("human_review_iceberg",     human_review_iceberg_node)
    builder.add_node("synopsis",                synopsis_node)
    builder.add_node("human_review_synopsis",   human_review_synopsis_node)
    builder.add_node("world_build",             world_build_node)
    builder.add_node("human_review_brainwave",  human_review_brainwave_node)
    builder.add_node("human_review_world",      human_review_world_node)
    builder.add_node("protagonist_card",        protagonist_card_node)
    builder.add_node("path_gen",                path_gen_node)
    builder.add_node("human_review_path",       human_review_path_node)
    builder.add_node("expand1",                 expand1_node)
    builder.add_node("human_review_expand",     human_review_expand_node)
    builder.add_node("expand2",                 expand2_node)
    builder.add_node("write",                   write_node)
    builder.add_node("path_state_extract",     path_state_extract_node)
    builder.add_node("human_review_write",      human_review_write_node)
    builder.add_node("bible_update",            bible_update_node)
    builder.add_node("auto_arc_transition",    auto_arc_transition_node)
    builder.add_node("human_review_role_shift", human_review_role_shift_node)
    builder.add_node("update_weight",           update_weight_node)
    builder.add_node("human_review_batch",      human_review_batch_node)
    builder.add_node("auto_review",             auto_review_node)
    builder.add_node("mode_select",             mode_select_node)
    builder.add_node("consistency",             consistency_node)
    builder.add_node("tension_check",           tension_check_node)
    builder.add_node("human_review_story_arc", human_review_story_arc_node)
    builder.add_node("story_arc_plan",          story_arc_plan_node)
    builder.add_node("event_chain_gen",         event_chain_gen_node)
    builder.add_node("human_review_event_chain", human_review_event_chain_node)
    builder.add_node("core_cast_gen",            core_cast_gen_node)
    builder.add_node("human_review_core_cast",   human_review_core_cast_node)
    builder.add_node("world_tick",               world_tick_node)
    builder.add_node("protagonist_collision",    protagonist_collision_node)

    # ── v4.3 新节点注册 ──
    # human_review_event 在 T12 新建；此处用占位，避免图编译失败
    # 若 human_review_event_node.py 已存在，则导入；否则用 human_review_event_chain_node 代替
    try:
        from graph.creation.nodes.human_review_event_node import human_review_event_node
        builder.add_node("human_review_event", human_review_event_node)
    except ImportError:
        # T12 尚未完成时，用 human_review_event_chain_node 作为临时占位
        builder.add_node("human_review_event", human_review_event_chain_node)

    builder.add_node("path_gen_v43",       path_gen_v43_node)
    builder.add_node("expand1_v43",        expand1_v43_node)
    builder.add_node("narrative_extract",  narrative_extract_node)

    # ── 边定义 ──
    builder.add_edge(START, "load")

    # load 之后：新项目 / 续传有路径（先过三步引擎） / 续传无路径
    builder.add_conditional_edges(
        "load",
        _route_after_load,
        {
            "idea_forge":  "idea_forge",
            "path_gen":    "path_gen",
            "world_tick":  "world_tick",
        },
    )

    # 开篇种子链仅用 Command(goto=…) 串联，避免与静态边叠加导致同一步内重复写入 iceberg_review_payload（InvalidUpdateError）。
    # v4.2：world_build → protagonist_card → iceberg_deduction → human_review_iceberg → genesis_ignition → story_arc_plan（全程 Command 与条件边混排，勿叠静态边）

    # 章节循环三步引擎链（幂等：同一章已推算过则快速跳过）
    # human_review_path / update_weight / load(续传) → world_tick → protagonist_collision → expand1
    # 重试链（human_review_expand/human_review_write → expand1）直接进 expand1，world_tick 幂等跳过
    builder.add_edge("world_tick", "protagonist_collision")
    # protagonist_collision 内部 Command(goto="expand1") — 不挂静态边，与 Command 叠加会双调度

    # ── legacy Synopsis 链（v4.2 新项目不走此路；仅保留供 human_review_synopsis_node 内部兜底循环） ──
    # idea_forge 由节点内 Command 进入 human_review_brainwave，勿叠静态出边
    builder.add_edge("synopsis", "human_review_synopsis")

    # synopsis 确认后 → world_build；拒绝 → 重新 synopsis
    builder.add_conditional_edges(
        "human_review_synopsis",
        lambda s: "world_build" if s.get("synopsis_approved") else "synopsis",
        {"world_build": "world_build", "synopsis": "synopsis"},
    )

    # world_build 生成后进入用户确认
    builder.add_edge("world_build", "human_review_world")

    # human_review_brainwave 仅由节点内 Command(goto=…) 出队（通过 → world_build；驳回 → idea_forge），勿叠条件边

    # 世界设定确认 → protagonist_card（主角人物卡）；修改 → 回到脑洞引擎重炼
    builder.add_conditional_edges(
        "human_review_world",
        lambda s: "protagonist_card" if s.get("world_setting_confirmed") else "idea_forge",
        {"protagonist_card": "protagonist_card", "idea_forge": "idea_forge"},
    )

    # 主角人物卡：仅由 protagonist_card_node 的 Command(goto=…) 串联（自环 / → iceberg_deduction）。
    # 勿挂 conditional_edges：与 Command 叠加时，若 state 中残留已确认的 protagonist_card（checkpoint），
    # 可能在「印象输入→自环」同一步内误开 iceberg，导致冰山先于人物卡审核。
    # 核心班底链：genesis_ignition → core_cast_gen → human_review_core_cast → story_arc_plan
    # 全部由节点内 Command(goto=…) 串联；core_cast_gen 在续传时如已有班底可直接跳到 story_arc_plan。
    # 分卷确认链：story_arc_plan → human_review_story_arc → mode_select → event_chain_gen
    # → human_review_event_chain → path_gen 全部由各节点 Command(goto=…) 串联。
    # 勿再叠静态边，否则会同一步并行调度下一节点，引发 InvalidUpdateError（例如重生成事件链时
    # human_review_event_chain 指向 event_chain_gen 的同时静态边仍指向 path_gen，对 event_chain_draft 双写）。

    # path_gen 仅由节点内 Command(goto=…) 出队（成功 → human_review_path / auto_review）；
    # 勿再挂 conditional_edges，否则与 Command(goto=event_chain_gen) 并行，误开空路径审核。



    # ── v4.3 事件生成链边 ──
    # event_chain_gen → human_review_event（v4.3 单事件审核）或 → path_gen_v43（自动模式）
    # 路由由 event_chain_gen_node 内部 Command(goto=…) 决定，无需此处静态边

    # human_review_event → path_gen_v43（通过）或 → event_chain_gen（驳回/重新生成）
    builder.add_conditional_edges(
        "human_review_event",
        lambda s: "path_gen_v43" if s.get("path_approved", False) else "event_chain_gen",
        {"path_gen_v43": "path_gen_v43", "event_chain_gen": "event_chain_gen"},
    )

    # path_gen_v43 → human_review_path（路由由节点 Command 决定；此处用 human_review_path 兼容审核）
    # expand1_v43 的 conditional_edges（与旧 expand1 复用相同审核节点）
    builder.add_conditional_edges(
        "expand1_v43",
        lambda s: route_review({**s, "pending_review_type": "expand"}),
        {
            "human_review_expand": "human_review_expand",
            "auto_review":        "auto_review",
        },
    )

    # 路径批次确认后路由：
    # v4.3 流程（current_event_paths 已设置）→ expand1_v43
    # 旧流程 → world_tick（章节级三步引擎）
    # 驳回 → 重跑 path_gen（旧流程）或 path_gen_v43（v4.3 流程）
    def _route_after_human_review_path(s: CreationState) -> str:
        if not s.get("path_approved"):
            return "path_gen_v43" if s.get("current_event_paths") else "path_gen"
        return "expand1_v43" if s.get("current_event_paths") else "world_tick"

    builder.add_conditional_edges(
        "human_review_path",
        _route_after_human_review_path,
        {
            "world_tick":  "world_tick",
            "expand1_v43": "expand1_v43",
            "path_gen":    "path_gen",
            "path_gen_v43": "path_gen_v43",
        },
    )

    # 写作循环：expand1 完成后 自动模式→auto_review 人工模式→human_review_expand → expand2 → write
    # 须强制 pending_review_type=expand：path_gen 会留下 "path"，若沿用则 route_review 误导向 human_review_path（未注册）→ KeyError
    builder.add_conditional_edges(
        "expand1",
        lambda s: route_review({**s, "pending_review_type": "expand"}),
        {
            "human_review_expand": "human_review_expand",
            "auto_review":        "auto_review",
        },
    )

    # 方向确认：批准 → expand2；修改 → expand1（旧流程）或 expand1_v43（v4.3 流程）
    builder.add_conditional_edges(
        "human_review_expand",
        lambda s: (
            "expand2"     if s.get("expand1_approved") else
            "expand1_v43" if s.get("current_event_paths") else
            "expand1"
        ),
        {"expand2": "expand2", "expand1": "expand1", "expand1_v43": "expand1_v43"},
    )

    builder.add_edge("expand2", "write")
    # write → path_state_extract（补丁 H：五维接力）→ consistency（补丁 F）→ tension_check
    builder.add_edge("write", "path_state_extract")
    builder.add_edge("path_state_extract", "consistency")
    builder.add_conditional_edges(
        "tension_check",
        lambda s: s.get("_tension_goto", "human_review_write"),
        {
            "human_review_write": "human_review_write",
            "auto_review":        "auto_review",
            "write":              "write",
        },
    )

    # 质量确认：满意 → narrative_extract（叙事提取）→ bible_update；
    #          文笔问题 → expand2；方向问题 → expand1_v43（v4.3 流程）或 expand1（旧流程）
    builder.add_conditional_edges(
        "human_review_write",
        lambda s: (
            "narrative_extract" if s.get("chapter_approved") else
            "expand2"           if s.get("expand1_approved") else
            "expand1_v43"       if s.get("current_event_paths") else
            "expand1"
        ),
        {
            "narrative_extract": "narrative_extract",
            "expand2":           "expand2",
            "expand1":           "expand1",
            "expand1_v43":       "expand1_v43",
        },
    )

    # narrative_extract 完成后 → bible_update
    builder.add_edge("narrative_extract", "bible_update")

    # bible_update 完成后：
    # v4.3 模式：根据 loop_control 决定内循环/外循环/卷收束
    # 旧模式：有待确认的立场变化 → human_review_role_shift；否则直接 → update_weight
    def _route_after_bible_update(s: CreationState) -> str:
        # v4.3 双循环控制（current_event_paths 存在表明处于 v4.3 流程）
        if s.get("current_event_paths"):
            pending_roles = s.get("pending_role_shifts") or []
            if pending_roles:
                return "human_review_role_shift"
            v43_route = _bible_update_v43_routing(s)
            return v43_route
        # 旧流程
        pending = s.get("pending_role_shifts") or []
        return "human_review_role_shift" if pending else "update_weight"

    builder.add_conditional_edges(
        "bible_update",
        _route_after_bible_update,
        {
            "human_review_role_shift": "human_review_role_shift",
            "update_weight":           "update_weight",
            "expand1_v43":             "expand1_v43",    # 内循环：下一路径
            "event_chain_gen":         "event_chain_gen",  # 外循环：下一事件
            "human_review_batch":      "human_review_batch",  # 卷收束
            "auto_arc_transition":     "auto_arc_transition",  # 自动卷过渡（auto_mode+arc/book）
        },
    )
    builder.add_edge("human_review_role_shift", "update_weight")

    # update_weight 完成后：未写完 → world_tick（下一章三步引擎）→ expand1；写完 → batch 路由
    def _route_after_update_weight(s: CreationState) -> str:
        if not _is_batch_done(s):
            return "world_tick"  # 下一章开始前先过三步命运编织引擎
        if s.get("auto_mode"):
            return route_review({**s, "pending_review_type": "batch"})
        return "human_review_batch"

    builder.add_conditional_edges(
        "update_weight",
        _route_after_update_weight,
        {
            "world_tick":         "world_tick",
            "human_review_batch": "human_review_batch",
            "auto_review":        "auto_review",
        },
    )

    # human_review_batch：继续下一批 或 结束
    builder.add_conditional_edges(
        "human_review_batch",
        lambda state: "done" if state.get("creation_complete") else "next",
        {
            "next": "path_gen",
            "done": END,
        },
    )

    # auto_review 根据审核结果路由到各目标节点
    builder.add_conditional_edges(
        "auto_review",
        lambda s: s.get("_auto_review_goto", "expand2"),
        {
            "expand1":             "expand1",
            "expand1_v43":         "expand1_v43",
            "expand2":             "expand2",
            "write":               "write",
            "path_gen":            "path_gen",
            "path_gen_v43":        "path_gen_v43",
            "event_chain_gen":     "event_chain_gen",
            "human_review_path":   "human_review_path",
            "human_review_expand": "human_review_expand",
            "human_review_write":  "human_review_write",
            "narrative_extract":   "narrative_extract",
            "bible_update":        "bible_update",
            "human_review_batch":  "human_review_batch",
            "__end__":             END,
        },
    )

    checkpointer = await get_checkpointer(db_path)
    return builder.compile(checkpointer=checkpointer)
