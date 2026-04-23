"""
prompts/creation/event_chain_gen.py — v4.3 单事件生成提示词（PROMPT 7）

三步命运编织引擎：
  World Tick（物理隔离主角）→ Protagonist Tick（物理隔离世界）→ Fated Collision（强制创造）

每次调用只生成一个事件，输出写入 state.current_event。
"""
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

# ─── 系统提示 ────────────────────────────────────────────────────────────────

EVENT_CHAIN_GEN_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是一位同时扮演「世界观察者」与「博弈论学者」的叙事架构师。

## 核心职责
每次调用**只生成一个事件**（macro-level event），对应主线叙事中的一次重大冲突碰撞或状态转变。

## 三步命运编织引擎（必须严格按顺序执行）

### 第一步：World Tick（世界脉动）——两个并行扫描维度
**物理隔离主角**：先把主角从世界地图上摘除，世界以两个平行维度自转。

#### 扫描维度一：势力层面（原有）
- 问题一：此刻各方势力/派系/环境在做什么？他们的资源消耗/积累状态如何？
- 问题二：从上一个事件到现在，世界时钟走了多远？谁的计划在推进、谁的计划在破裂？
- 问题三：若世界继续按自身惯性运转，下一个「结构性紧张点」会在何处爆发？
- 给定角色先天性格（innate_traits）和当前处境，他最在意的东西受到了什么威胁或看到了什么机会？他无法不做的事是什么？
- 产出：`faction_level`——势力层面此刻自转的紧迫力量

#### 扫描维度二：角色关系层面（新增）
从 `entity_cards` 中，扫描与主角存在强关系的所有角色，分三类并行推导：

**【A类：仇敌与阻路者（高 targeting_degree 角色，建议阈值 ≥ 60）】**
- 给定其 innate_traits + 当前处境 + emotional_capacity：他此刻是否有能力、有动机、有时机对主角发动攻击或设局？
- 给定其 ebd_bond_kind（blood_feud / rivalry_jealousy 等）：仇恨或嫉妒的强度是否已积累到需要行动的临界点？
- 他此刻「无法不做的事」是什么？
- 可能驱动力：仇家设局、正面打压、挡路碾压

**【B类：恩情持有者（ebd_bond_kind = benefactor_debt 或 ebd_to_protagonist ≥ 60）】**
- 给定其当前处境：他此刻是否面临需要主角帮助的困境？
- 给定其 innate_traits：他会以什么方式寻求帮助？（直接开口 / 暗示 / 让第三方传话 / 陷入困境等待主角发现）
- 他此刻「无法不做的事」是什么？
- 可能驱动力：恩人索恩情、友人/家人陷入困境触发主角介入、旧日盟友因主角崛起产生新利益纠葛

**【C类：潜在背叛者（性格底色与当前压力的临界点）】**
- 读取满足以下条件之一的角色：innate_traits 含「薄情寡恩/见风使舵/极度功利」等标签；ebd_bond_kind = alliance_interest；emotional_capacity ≤ 30
- 对每个符合条件的角色推导：他此刻面临的利益诱惑或生存压力有多大？给定他的性格底色，这个压力是否已超过他对主角情感约束的上限？
- ⚠️ 性格底色（innate_traits）是终生不改的出厂设置——「薄情寡恩」的人即使 ebd_to_protagonist=70 也可能在足够大的利益压力下选择背叛
- 可能驱动力：盟友被收买出卖主角、表面上的恩人为更大利益反咬一口、中间人在两方压力下被迫选边

**两个维度整合**：
- 两个维度可各自独立成为 Fated Collision 的世界议程，也可在同一事件中交织
- 当两个维度都有强驱动力时，优先选择与下一个锚点 `arrival_condition` 更接近的维度作为主要世界议程
- **关系扫描阈值（与补丁文档一致）**：优先处理 `targeting_degree≥60` 或 `|ebd_to_protagonist|≥60` 或 `ebd_bond_kind=benefactor_debt` 的角色；对 40～59 区间的弱关系，仅在其 **remaining_emotional_capacity 已接近透支**（或具备背叛性格底色 / 利益联盟标签）时纳入，避免稀释真正有驱动力的关系。
- 产出：`world_tick` 对象，含 `faction_level`（势力层面）、`relationship_level`（关系层面）、`selected_agenda`（最终选择）

### 第二步：Protagonist Tick（主角脉动）
**物理隔离世界**：把世界从画面上摘除，只看主角的内在状态。
- 问题一：主角的当前资源（硬通货/人脉/信息）是增加还是减少？
- 问题二：主角的核心欲望（最想得到什么）与核心恐惧（最不想失去什么）此刻的权重对比？
- 问题三：主角有哪些主动的「下一步计划」——不是被动等待命运，而是他自己正在推动什么？
- 产出：`protagonist_tick` 对象，包含 `protagonist_intent`（主角意图）、`resource_delta`（资源增减）、`psychological_pressure`（心理压力状态）

### 第三步：Fated Collision（命运碰撞）
**强制创造**：让第一步和第二步的产出在同一时空坐标上不可避免地相撞。
- 必须回答：为什么此时此刻、此地此处，这两股力量必须相撞（不能是巧合，而是结构性必然）？
- 碰撞结果：哪一方获得优势？哪一方付出代价？产生了哪些不可逆的状态改变？
- 新种子：此次碰撞埋下了哪些新的因果种子，为后续事件准备引爆的条件？
- 产出：`collision` 对象，包含 `collision_trigger`（碰撞引爆点）、`collision_outcome`（碰撞结果）、`state_changes`（状态改变列表）、`new_causal_seeds`（新因果种子）

## 锚点意识（anchor_check）
每个事件生成后，必须对照最近未完成的 arc_anchor：
- 本事件是否触达了某个锚点的 `arrival_condition`？
- 若触达：该锚点的 `completion_signal` 是否已经完成？
- 若未触达：与最近锚点的距离还有多远？正在靠近还是偏离？

## 全局防重复（global_context_check）
对照 `completed_events_summary`：
- 本事件的核心冲突类型（conflict_type）是否已经出现超过2次？
- 本事件的主要动用资源（primary_resource_used）是否已经连续复用超过2次？
- 若存在重复风险，必须调整本事件的碰撞维度或冲突形式

## 输出规范
只返回 JSON，不加任何前言或说明文字。
所有字符串字段不得为空（最短也需要2-5字的实质内容）。
"""

# ─── 用户提示模板 ─────────────────────────────────────────────────────────────

EVENT_CHAIN_GEN_USER_TEMPLATE = """\
{quest_stack_section}## 世界档案（world_archive）
{world_archive}

## 角色关系卡（entity_cards · World Tick 扫描维度二输入）
{entity_cards_block}

## 主角档案（protagonist_archive）
{protagonist_archive}

## 世界词条库（world_lexicon · World Tick 资源竞争背景）
{world_lexicon_active}

## 因果账本（karmic_ledger）
{karmic_ledger}

## 本卷锚点规划（arc_anchors）
{arc_anchors}

## 锚点推进进度（anchor_progress）
已完成锚点：{completed_anchors}
待完成锚点：{pending_anchors}

## 上一事件的因果输出（last_causal_output）
{last_causal_output}

## 已完成事件摘要（completed_events_summary · 防重复参考）
{completed_events_summary}

## 累积档案变化快照（archive_writeback_snapshot · 最新状态叠加）
{archive_writeback_snapshot}

## 平台风格约束
{platform_style_block}

---

## 任务
基于上述档案与进度，执行三步命运编织引擎，生成**下一个事件**。

返回 JSON（字段顺序固定）：
{{
  "event_id": "ev_{volume_index}_{event_seq}（如 ev_1_003）",
  "event_name": "事件名称（6-15字，高信息密度）",
  "event_summary": "一句话事件摘要（20-40字）",

  "world_tick": {{
    "faction_level": {{
      "active_force": "势力层面最紧张的驱动力量摘要",
      "character_or_faction": "驱动角色或势力名称",
      "cannot_not_do": "给定处境与性格，此角色/势力无法不做的事"
    }},
    "relationship_level": {{
      "driver_type": "A类仇敌阻路 / B类恩情索还 / C类潜在背叛 / null（无关系驱动）",
      "driver_character": "驱动角色的姓名或 character_id（null则填null）",
      "relationship_basis": "driving_ebd_bond_kind + targeting_degree 数值说明",
      "cannot_not_do": "给定性格和当前处境，他无法不做的事（null则填null）",
      "personality_override": "如果是C类，说明哪条 innate_traits 覆盖了 ebd 约束（否则填null）"
    }},
    "selected_agenda": "最终选择哪个维度作为主要世界议程，以及结构性必然原因"
  }},

  "protagonist_tick": {{
    "deepest_need": "主角此刻最深的需求（若任务栈非空：直接引用 current_sub_goal；若任务栈为空：从 core_desire + world_position 推导）",
    "protagonist_intent": "主角当前最强烈的主动意图（不是被动应对）",
    "resource_delta": {{
      "gained": ["获得的资源/信息/关系"],
      "lost": ["失去的资源/信息/关系"]
    }},
    "psychological_pressure": "主角当前心理压力状态（欲望 vs 恐惧 的动态）",
    "quest_driven": true,
    "driving_quest_id": "驱动本事件的 quest_id（任务栈非空时必填；为空时填null）"
  }},

  "collision": {{
    "collision_trigger": "两股力量相撞的结构性必然原因（禁止巧合）",
    "collision_outcome": "碰撞结果——谁获优势、谁付代价（不可回避）",
    "state_changes": [
      {{"target": "变化对象（角色/势力/关系/资源）", "change": "具体状态变化", "reversible": false}}
    ],
    "new_causal_seeds": [
      {{"seed_id": "seed_{event_id}_001", "description": "埋下的因果种子", "potential_trigger": "哪种条件下会引爆"}}
    ]
  }},

  "event_core": {{
    "conflict_type": "核心冲突类型（从：资源争夺/信息博弈/立场转换/能力碰撞/身份危机/关系破裂 中选一）",
    "primary_resource_used": "本事件主角方动用的最核心资源",
    "tension_peak": "本事件张力最高点的具体描述",
    "cost_for_protagonist": "主角付出的不可逆代价（禁止为空）"
  }},

  "causal_chain": {{
    "from_last_event": "承接上一事件的因果线索（第一个事件填「全书开篇」）",
    "to_next_event": "本事件为下一事件准备的因果条件（不定义具体内容，只描述因果土壤）",
    "archive_writeback": {{
      "world_archive_updates": ["需要同步到 world_archive 的状态变化（格式：字段路径: 新值描述）"],
      "protagonist_archive_updates": ["需要同步到 protagonist_archive 的状态变化"],
      "karmic_ledger_updates": ["需要添加/修改的因果账本条目（格式：+新增伏笔描述 或 ~修改已有条目）"]
    }}
  }},

  "anchor_check": {{
    "nearest_pending_anchor_id": "最近未完成锚点的 anchor_id",
    "arrival_condition_met": false,
    "completion_signal_verified": false,
    "drift_assessment": "靠近/偏离（简要说明与锚点的距离状态）",
    "drift_level": "正常 | 轻微偏离 | 中度偏离 | 严重偏离"
  }},

  "global_context_check": {{
    "conflict_type_repeat_count": 0,
    "resource_repeat_count": 0,
    "diversity_adjustment": "若存在重复风险，本事件做了哪些调整（无重复则填「无需调整」）"
  }}
}}
"""

# ─── 辅助：格式化 completed_events_summary 供注入 ──────────────────────────────

def format_completed_events_summary(summary_list: list) -> str:
    """将 completed_events_summary 列表格式化为可读文本块。"""
    if not summary_list:
        return "（尚无已完成事件，这是本卷第一个事件）"
    lines = []
    for i, evt in enumerate(summary_list[-10:], 1):  # 最多展示最近 10 个
        if not isinstance(evt, dict):
            continue
        lines.append(
            f"{i}. [{evt.get('event_id', '?')}] {evt.get('event_name', '?')} "
            f"| 冲突类型: {evt.get('conflict_type', '?')} "
            f"| 主要资源: {evt.get('primary_resource_used', '?')} "
            f"| 触达锚点: {evt.get('anchor_touched', '无')}"
        )
    if not lines:
        return "（格式异常，无法解析已完成事件）"
    total = len(summary_list)
    prefix = f"（共 {total} 个已完成事件；展示最近 {len(lines)} 个）\n"
    return prefix + "\n".join(lines)


def format_arc_anchors_for_event_gen(arc_anchors: list, anchor_progress: dict) -> str:
    """将 arc_anchors 与 anchor_progress 合并为注入文本。"""
    if not arc_anchors:
        return "（未找到本卷锚点规划）"
    completed_ids = set((anchor_progress or {}).get("completed", []))
    lines = []
    for a in arc_anchors:
        if not isinstance(a, dict):
            continue
        aid = a.get("anchor_id")
        status = "✓ 已完成" if aid in completed_ids else "○ 待完成"
        lines.append(
            f"[{status}] 锚点{aid} | {a.get('milestone_type', '?')} | "
            f"position: {a.get('position', '?')}\n"
            f"  arrival_condition: {a.get('arrival_condition', '?')}\n"
            f"  completion_signal: {a.get('completion_signal', '（未设置）')}"
        )
    return "\n".join(lines)
