from __future__ import annotations
from typing import Annotated, NotRequired, TypedDict
import operator


def _merge_shallow_dict(left: object, right: object) -> dict:
    """LangGraph 同 tick 多节点写 dict 时用浅合并，后者键覆盖前者。"""
    a = dict(left) if isinstance(left, dict) else {}
    b = dict(right) if isinstance(right, dict) else {}
    return {**a, **b}


# ─── 提取流 State ────────────────────────────────────────────────────────────
class ExtractionState(TypedDict):
    # 输入
    source_type: str                       # "file" | "url" | "library"
    source_path: str
    raw_text: str

    # 切分结果
    segments: list[dict]                   # {index, title, text, char_count, source_chapters}
    total_segments: int

    # Pass 1 累积
    # ⚠️ 用 Annotated + operator.add 让 LangGraph 自动合并列表，而不是覆盖
    current_batch_index: int
    current_pass1a_result: dict            # 用于 Pass 1a 和 1b 之间传递数据
    batch_summaries: Annotated[list[dict], operator.add]  # 每批次摘要（含 event_path_chain）
    entity_registry: dict                  # 实体注册表 dict（不存 Pydantic 实例）
    pass1_context: dict                    # 延续上下文

    # 真相清单
    truth_manifest: dict

    # Pass 2 累积
    pass2_batch_index: int                 # 在原文档基础上加了这行方便通过校验
    foreshadow_entries: Annotated[list[dict], operator.add]

    # Pass 3 输出
    blueprint: dict                        # 最终 NovelBlueprint dict

    # 控制
    is_fragment: bool
    extraction_complete: bool
    error: str | None


# ─── 创作流 State ────────────────────────────────────────────────────────────
class CreationState(TypedDict):
    project_id: str
    genre_request: str
    blueprint_id: str

    blueprint: dict
    blueprint_weight: float

    synopsis: dict
    synopsis_approved: Annotated[bool, lambda x, y: y]  # 取最后写入值，避免多节点同步写冲突

    story_path: list[dict]
    path_approved: Annotated[bool, lambda x, y: y]
    # v4.3：同 tick 内 bible_update 与其它节点可能均递增/重置该索引，须末值归约
    current_node_index: Annotated[int, lambda x, y: y]

    current_expand1: dict
    current_expand2: dict
    # expand1 生成的草稿事件路径链，供 human_review_expand 展示（方向确认）
    expand1_event_draft: list[str]
    # human_review_expand 设置，控制 expand1 → expand2 的条件边
    expand1_approved: Annotated[bool, lambda x, y: y]
    # expand2 生成的完整事件路径链，供 human_review_write 展示（质量确认）
    pending_event_path_chain: list[str]
    # human_review_write 设置，控制 → bible_update 的条件边
    chapter_approved: Annotated[bool, lambda x, y: y]
    # 同 tick 多节点可能先后覆写正文片段，须末值归约，否则 LangGraph InvalidUpdateError
    current_draft: Annotated[str, lambda x, y: y]

    # characters 子 dict 可含补丁 I：short_term_stream / long_term_stream（append-only 内心叙事流）
    # 多节点同 tick 更新 bible（如 bible_update + consistency 写入 rewrite_feedback）须浅合并
    bible: Annotated[dict, _merge_shallow_dict]

    pivot_records: Annotated[list[dict], operator.add]
    post_pivot: bool

    creation_complete: bool
    # True = 自由创作模式，blueprint_load_node 未找到匹配骨骼时设置
    free_creation: bool
    # True = 从已有项目 DB 记录中续传，blueprint_load_node 设置
    resume_from_db: bool

    # 当前卷（批次）的卷名和副标题，由 path_gen_node 生成，确认后写入 DB
    volume_name:    str
    volume_tagline: str

    # 当前第几批（从 0 开始），human_review_batch_node 在 continue 时自增
    # path_gen_node 用于选择弧度模板（OPENING / DEVELOPING / MATURE）
    batch_index: int

    # 题材匹配结果（blueprint_load_node 设置，path_gen / expand1 使用）
    matched_genres: list[str]    # 匹配到的标准题材名列表
    genre_dicts: list[dict]      # 对应的题材词典数据列表

    # 世界设定卡（静态，synopsis 确认后 world_build 生成并锁定，全书不变）
    # 结构：{basic_rules, power_structure, geography, world_taboos, unique_settings, gray_zone_ecology?, narrative_era?}
    world_setting: dict
    world_setting_confirmed: bool
    world_setting_feedback: str  # human_review_world 修改意见，world_build_node 消费后清空

    # 主角标准名（protagonist_card 建立时写入，续传时从 DB 加载，write 排除首次出场检测）
    protagonist_name: str
    protagonist_card_feedback: str  # 主角人物卡修改意见
    protagonist_user_input: dict    # 主角印象：protagonist_impression（自由描述）；可含 legacy 四问键

    # 新人物卡草稿（write_node 检测首次出场时生成，human_review_write 展示给用户确认）
    # 多节点同 tick 写入时用末值归约，避免 InvalidUpdateError
    pending_char_cards: Annotated[list[dict], lambda x, y: y]
    # 用户确认后的人物卡（human_review_write / auto_review 写入，bible_update 保存到 entity_cards）
    # 多节点同 tick 写入时用末值归约
    confirmed_char_cards: Annotated[list[dict], lambda x, y: y]

    # 角色立场变化待确认列表（bible_update_node 填写，human_review_role_shift 消费）
    # 每项：{character_name, trigger_type, trigger_description, evidence,
    #        current_role, established_at_seq, current_seq}
    # 同 tick 多写入须末值归约（否则 LangGraph InvalidUpdateError）
    pending_role_shifts: Annotated[list[dict], lambda x, y: y]

    # 本节正文中出现但能力卡里未记录的能力，供 human_review_write 展示给用户确认
    # 每项：{ability_name, char_name}
    # 多节点同 tick 写入时用末值归约（与 pending_char_cards 一致）
    pending_ability_checks: Annotated[list[dict], lambda x, y: y]

    # 用户对未记录能力的处理决定，bible_update_node 消费后清零
    # 每项：{ability_name, char_name, decision: "add"|"extend"|"ignore",
    #        ability_type?, ability_desc?, ability_limit?}
    ability_decisions: Annotated[list[dict], operator.add]

    # bible_update 检测到特质叠加方式变化时填写，human_review_write 确认后消费
    # 每项：{character_name, trigger_event, seq, suggested_interaction}
    pending_trait_interaction_update: Annotated[list[dict], operator.add]

    # 词条伏笔：write_node 预提取，human_review_write 展示，用户可补充 story_potential
    # 多节点同 tick 写入时用末值归约
    pending_noun_foreshadows: Annotated[list[dict], lambda x, y: y]
    noun_foreshadow_story_potential_edits: Annotated[dict, _merge_shallow_dict]

    # 上一章结尾的行动意图（bible_update 从章节尾 200 字提取，expand1 硬约束承接）
    last_action_intent: str
    # 目标平台风格（创作启动时选择，全书固定）：番茄男频/番茄女频/知乎男频/知乎女频/通用网文
    platform_style: str

    # 故事方向模式：auto | story_direction | framework
    creation_mode: str
    # 框架导入：文件路径、解析结果
    framework_file_path: str
    framework_parsed: dict
    volumes_draft: list
    user_write_rules: str
    current_volume_index: int
    # extract_all 的完整结果（synopsis + world_setting + protagonist_card），仅 creation_mode=story_direction 时使用
    story_direction_result: dict

    # 故事弧：分卷规划、事件链；配角以 entity_cards + bible_update 生长
    protagonist_card: dict
    core_cast: dict  # 兼容旧库；新流程常为空
    core_cast_draft: dict  # 废弃占位，防旧 checkpoint
    story_arc_volumes_draft: list
    # 分卷规划「重新生成」时用户意见；story_arc_plan 消费后须清空
    story_arc_regen_feedback: str
    volumes: list
    current_event_chain: list
    current_event_chain_pos: int
    # 事件链待确认草稿（interrupt 须在独立节点，避免 resume 时整段重跑 LLM）
    # 取最后写入值：path_gen 与 event_chain_gen 曾可能被同一步错误并行调度，须避免 InvalidUpdateError
    event_chain_draft: Annotated[list, lambda x, y: y]
    last_event_batch_size: int
    # Phase 1 锚点碰撞草案缓存：{vol_index: {anchor_id: design_dict}}
    # event_chain_gen 写入，human_review_event_chain 可读取用于展示漂移诊断
    arc_phase1_anchor_designs: dict

    # 用户原始脑洞（可选）；idea_forge_node 与 framework 文件合并解析后写入 user_anchors / genesis_variables
    user_raw_input: str
    user_anchors: dict                # opening_scene / world_rules / characters / emotional_lines / plot_events
    # v4.3 补丁 E：脑洞引擎完整输出（user_anchors 文档形、brainwave_formula、downstream_instructions 等）
    brainwave_engine: dict
    # 叙事时代与语体锚点（脑洞根级 narrative_era → world_build 写入 world_setting；镜像入 world_archive）
    narrative_era: str
    # 脑洞人审通过后 True → world_build；从 world 修订回上游重炼时须置 False
    brainwave_approved: bool
    # human_review_brainwave / human_review_world(修订) 写入，idea_forge 消费后清空
    brainwave_regen_feedback: str

    # ── 开篇种子 / 冰山反推（新项目替代直出 synopsis）────────────────────
    genesis_variables: dict           # sample_variables 结果 + genre_bucket
    genesis_opening_text: str        # 用户确认后的开篇正文
    genesis_opening_candidate: str   # LLM 生成的待确认开篇
    genesis_opening_feedback: str    # 开篇重新生成时的用户意见
    skip_world_build_regen: bool     # True 时 world_build 可跳过 LLM（仅特殊恢复场景；冰山确认后应为 False）
    genesis_protagonist_card: dict   # 冰山主角卡预填 → protagonist_card 直进 review
    iceberg_review_payload: dict    # 待人审：synopsis / world_setting / protagonist
    iceberg_deduction_feedback: str # 要求重新冰山反推时的意见
    # 阶段1 LLM 原始 JSON 快照；宏观构思「仅重做」时喂回阶段2，避免世界/班底漂移
    iceberg_stage1_world_raw: dict
    iceberg_stage1_cast_raw: dict
    iceberg_synopsis_only: bool     # True=本轮只跑阶段2并冻结 state 中已定世界与班底
    iceberg_world_snapshot: dict    # 冰山阶段1 合并后的世界结构，供 world_build 继承，勿被修订稿覆盖

    # 自动模式相关（宏观构思确认后选择）
    auto_mode: bool              # 是否自动模式，默认 False
    # 自动化边界：arc=单卷自动后待人开下一卷；book=跨卷自动（与 auto_mode 配合）
    auto_target: str
    # 全书自动停笔：已完结事件数 ≥ 此值则结束；0=不限制（novel_projects.max_chapters 列仍存该上限）
    max_auto_events: int
    # 全书已完结并结算的事件总数（仅在 bible_update 外循环步进时 +1）
    global_settled_event_count: int
    # 换卷时记录当时的 global_settled_event_count；本卷内事件数 = 全局 - 此值
    volume_start_event_count: int
    auto_retry_count: Annotated[int, lambda x, y: y]       # 兼容旧版，等价 auto_retry_count_path
    auto_retry_count_path: Annotated[int, lambda x, y: y]   # path 类型重试次数
    auto_retry_count_expand: Annotated[int, lambda x, y: y]  # expand 类型重试次数
    auto_retry_count_write: Annotated[int, lambda x, y: y]   # write 类型重试次数
    auto_total_retry_count: Annotated[int, lambda x, y: y]  # 当前路径总重试次数（跨类型），事件回合完成后清零
    # 多节点可能同一步写 path/expand/write（如 graph 路由覆盖），须取末值而非抛 InvalidUpdateError
    pending_review_type: Annotated[str, lambda x, y: y]  # 'path'/'expand'/'write'/'batch'

    # 张力检查（write 与 bible_update 之间）
    tension_retry_count: Annotated[int, lambda x, y: y]     # 张力检查重试次数，通过后重置为 0
    tension_minor_issues: Annotated[list, lambda x, y: y]   # 同 tick 多节点写入时取末值

    # v4.2 档案镜像（与 world_setting / protagonist_card 同步扩展，供推导与事件链注入）
    world_archive: dict
    protagonist_archive: dict
    karmic_ledger: list  # 伏笔与因果种子；结构随 bible 演进
    creation_flow_version: str

    # 三步命运编织引擎输出（world_tick_node 写入，expand1_node 消费）
    # 结构：{node_index, independent_agendas, world_events_in_motion,
    #         protagonist_need, protagonist_cost_ceiling, collision_point}
    # node_index 与 current_node_index 相同时为有效缓存，可跳过重算
    current_world_tick: dict
    # 引力交汇节点输出（protagonist_collision_node 写入，expand1_node 消费）
    current_protagonist_collision: dict

    # ── v4.3 事件驱动分层叙事架构字段 ────────────────────────────────────────
    # 里程碑推进状态，由 event_chain_gen 更新、bible 收卷判定时读取
    # 结构：{completed: [milestone_id, …], pending: [milestone_id, …]}
    # 同 tick 多节点可能各写子键，须浅合并
    milestone_progress: Annotated[dict, _merge_shallow_dict]

    # 路径推进状态，由 bible_update / path_state_extract 等多节点写入
    # 结构：{current_event_id, completed_paths: [path_id, …], remaining_paths: [path_id, …]}
    path_progress: Annotated[dict, _merge_shallow_dict]

    # 已完结事件摘要（仅在外循环 bible_update 结算时 operator.add 一条），供 event_chain_gen 防重复
    # 每项：{event_id, event_name, conflict_type, primary_resource_used, event_result_type, protagonist_tick_type, milestone_touched}
    completed_events_summary: Annotated[list, operator.add]

    # 最近 N 章节奏分布，由 path_gen 追加，供下一次 path_gen 注入全局节奏约束
    # 结构：{last_n_paths: [{path_id, narrative_function}], rhythm_note}
    recent_rhythm: Annotated[dict, _merge_shallow_dict]

    # 当前单事件输出（event_chain_gen 写入，path_gen 消费）
    # 结构：event_id, event_name, event_summary, world_tick{}, protagonist_tick{},
    #        collision{}, event_core{}, causal_chain{}, milestone_check{}, global_context_check{}
    current_event: Annotated[dict, _merge_shallow_dict]

    # 当前事件拆解出的路径列表（path_gen 写入，expand1 逐路径消费）
    # 结构：{event_id, event_name, total_paths, paths[], rhythm_note, global_rhythm_adjustment}
    current_event_paths: Annotated[dict, _merge_shallow_dict]

    # narrative_extract 节点输出（在正文通过审核后触发）
    # 结构：{foreshadows, chapter_path_chain, lexicon_updates, scene_snapshot, global_seq, …}
    narrative_extract_result: Annotated[dict, _merge_shallow_dict]

    # 上一章末场景快照（补丁 F）：narrative_extract → bible_update 写入全局；
    # 供 event_chain_gen 第零步、consistency_node 物理基准、下一事件空间/资产约束。
    scene_snapshot: Annotated[dict, _merge_shallow_dict]

    # 世界词条库（World Lexicon）— 补丁 C
    # 每项结构见文档 DeepNovel v4.3 补丁 C § 三
    # {lexicon_id, term, term_type, category, static_profile, dynamic_associations, incomplete_clue, first_appearance}
    world_lexicon: list

    # 活跃任务栈（Active Quest Stack）— 补丁 D
    # 结构见文档 DeepNovel v4.3 补丁 D § 二
    # 每项：{quest_id, quest_name, quest_origin, urgency_level, deadline_note,
    #         current_sub_goal, layer, completion_condition, failure_condition,
    #         evolution_on_completion, evolution_on_failure, status,
    #         planted_chapter, emotional_weight}
    # layer 枚举：immediate / short_term / arc_level / core_drive
    # urgency_level 枚举：critical / high / medium / low
    # status 枚举：active / completed / failed
    active_quest_stack: list

    # scripts/test_long_form_sandbox：为 True 时不走 DB 续传，以免误覆盖 global_settled_event_count
    _sandbox_skip_db_resume: NotRequired[bool]
    # scripts/test_long_form_sandbox：压低卷 target_events 有效阈值，使事件驱动沙盒能触发换卷（生产勿设）
    _sandbox_arc_relaxed: NotRequired[bool]

    error: str | None
