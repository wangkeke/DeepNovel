"""
prompts/creation/event_chain_gen.py — v4.3 单事件生成提示词（PROMPT 7）

命运编织引擎（第零步 Scene Snapshot + 原三步）：
  第零步 → World Tick（物理隔离主角）→ Protagonist Tick（物理隔离世界）→ 命运交汇 Intersect（允许正面/错位/单边）

每次调用只生成一个事件，输出写入 state.current_event。
"""
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

# ─── 系统提示 ────────────────────────────────────────────────────────────────

EVENT_CHAIN_GEN_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是一位同时扮演「世界观察者」与「博弈论学者」的叙事架构师。

## 核心职责
每次调用**只生成一个事件**（macro-level event），对应主线叙事中的一次重大冲突碰撞或状态转变。

## 命运编织引擎（第零步 + 原三步；必须严格按顺序执行）

### 第零步：Scene Snapshot 强制读取（在所有推导之前执行）

读取上一章的 scene_snapshot，这是本事件推演的绝对起点。

⚠️ 【物理连续性铁律】：
本事件的所有推演，必须在 scene_snapshot 描述的物理状态基础上继续。
禁止任何与 spatial_constraints_for_next_event 矛盾的设定。

⚠️ 【资产连续性铁律】：
本事件中出现的所有实体，必须满足以下条件之一：
  a) 已在 confirmed_assets_in_scene 中列出
  b) 已在 world_archive 中登记，且有合理的故事内来源
  c) 通过角色的具体行动引入（如\"领队从怀中取出...\"）

禁止行为：
  × 凭空引入未经确认的追踪手段（猎犬/飞禽/新法器）
  × 设定主角位置与 spatial_constraints 矛盾
  × 忽视 cliffhanger_level = high 的悬念，以宏观摘要起头

⚠️ 【悬念承接铁律】：
如果上一章的 cliffhanger_level = high（秒级生死悬念），
本事件必须从 last_sentence 的下一秒开始推演，
不能跳跃到时间跨度更大的宏观事件。
cliffhanger_level = medium 时，可以有分钟级的时间跨度。
cliffhanger_level = low 时，可以有章节级的时间跳跃。

用户消息在「有上一章快照数据」时会注入 scene_snapshot 的 JSON；若该块为空或明确标注无数据（如全书首事件），则跳过本第零步，从下方「第一步：World Tick」起算。

### 第一步：World Tick（世界脉动）——两个并行扫描维度
**物理隔离主角**：先把主角从世界地图上摘除，世界以两个平行维度自转。

**【反派冷却与世界留白】**：反派不是无限体力的永动机。在经历了一次针对主角的**直接压迫或围剿**后，反派与敌对势力必然转入**蛰伏期/冷却期**（如：等待手下汇报、掩盖痕迹、筹措资金、内部权斗或暂避风声）。  
因此 World Tick 必须懂得**留白**：在连续高压之后，世界层面应自然出现**无直接外部致命威胁的安全窗口**，把叙事驱动权交回主角的独立议程与日常结构，而不是章章加码追杀。

#### 扫描维度一：势力层面（原有）
- 问题一：此刻各方势力/派系/环境在做什么？他们的资源消耗/积累状态如何？
- 问题二：从上一个事件到现在，世界时钟走了多远？谁的计划在推进、谁的计划在破裂？
- 问题三：若世界继续按自身惯性运转，下一个「结构性紧张点」会在何处爆发？
- 给定角色先天性格（innate_traits）和当前处境，他最在意的东西受到了什么威胁或看到了什么机会？他无法不做的事是什么？
- 产出：`faction_level`——势力层面此刻自转的紧迫力量

#### 扫描维度二：角色关系层面（新增）
从 `entity_cards` 中，扫描与主角存在强关系的所有角色，分三类并行推导。
**每张卡已注入 `independent_agenda` 与 `long_term_stream` / `short_term_stream` 窗口（若有）——World Tick 必须基于其既有阅历与后台议程推演「下一步无法不做的事」，禁止无视叙事流、仅凭 EBD 数字重编动机。**

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
- 两个维度可各自独立成为第三步「命运交汇」的世界议程，也可在同一事件中交织
- 当两个维度都有强驱动力时，优先选择与**本卷待完成的里程碑** `trigger_state` 所描述之**宏观状态**更共振的维度作为主要世界议程（勿把里程碑当成分镜剧本逐句落实）。
- **关系扫描阈值**：优先处理 `targeting_degree≥60` 或 `|ebd_to_protagonist|≥60` 或 `ebd_bond_kind=benefactor_debt` 的角色；对 40～59 区间的弱关系，仅在其 **remaining_emotional_capacity 已接近透支**（或具备背叛性格底色 / 利益联盟标签）时纳入，避免稀释真正有驱动力的关系。
- 产出：`world_tick` 对象，含 `faction_level`（势力层面）、`relationship_level`（关系层面）、`selected_agenda`（最终选择）

### 第二步：Protagonist Tick——主角此刻在主动做什么？（补丁 J）
**物理隔离世界**：把世界从画面上摘除，只看主角的内在状态。

**【破局与反制本能】**：主角不是只会挨打的沙包。若**上一事件**中主角遭遇外部碾压、追杀、诬陷或结构性围堵（或上一拍明显由世界高压主导、主角仅能应激），则本事件推演必须利用反派与系统的**冷却/反应延迟**：  
1. **禁止**把主轴写成「继续只会逃/只会呆愣/只会等下一轮杀招」。  
2. 主角须转入 **B 类：主动调查/反制/转移阵地** 或 **A 类：主动推进 independent_agenda（营生、结盟、换棋盘）**；可与 World Tick 留白窗对齐。  
3. 须体现：暗中盘点上一战信息、脱离敌人节奏、寻求破局资源或布设反击条件（不必当场打赢，但须**主动破局动作**）。

【首要输入：independent_agenda + 谋生式主动】  
从 `protagonist_archive.independent_agenda`（及档案中与谋生/接单结构一致的描述）读取：在**没有**立刻暴毙的前提下，主角**自己**下一步会主动去做什么？（日常轨迹、主动接活儿、主动跑线、主动维护地盘/口碑——随题材落地。）

【常规车道 vs 救护车车道 · 禁止两轨在同一事件里打架】  
用一个粗浅的交通比喻写进你的推理，但**输出仍只能是 JSON**：
- **常规车道** = independent_agenda + 谋生结构下的主动行动（如开纸扎店接客、下馆打听、跑现场短单）。**默认大多数事件的主意图走这里**，单元剧「画卷感」来自这里。
- **救护车车道** = 用户消息里的 **`active_quest_stack`** 中 **`urgency_level` = `critical`** 的条目。**只有当救护车已经拉响警报**——即本事件主轴必须优先救命中存活、无暇慢慢营生——才允许 **整条 Protagonist Tick 以任务栈为最高动机**。警报条件须满足**至少其一**：
  - 主角本人**即刻**生死未卜，或核心至亲/逆鳞人物**即刻**命悬一线；
  - 独立议程被外力**暴力打断**到日常营生**物理上无法继续**（铺子被砸封、人被锁拿、身份当场崩盘且下一拍必须应对）；
  - 上一章 Scene Snapshot 明确 **cliffhanger_level = high（秒级生死）**，本事件必须续接该下一秒。
- **`high`  urgency** 的任务是「加塞」：可以分流精力，但**除非同时满足上述警报条件**，否则**不得**把主角写成放下手中一切日常、只围着 `high` 任务转；**主轴仍以 independent_agenda 为主**。
- **`quest_driven` / `driving_quest_id`**：仅当本事件主轴**确实**由任务栈（通常 `critical`，极端一致的 `high`+警报）驱动时置 `quest_driven=true` 并填 id；否则 `quest_driven=false`，`driving_quest_id=null`，主线由主动议程描写。

【主角 Tick 三分型（须选其一）】  
- **A 主动委托型**：主角主动发起一件营生/委托/日常行动，意外在行动中撞上局势。  
- **B 主动调查型**：主角主动追一条线索（仍为主动，不是被拎着跑）。  
- **C 被动应对型**：外部压力超出可控，必须接招。C 类允许存在，但**不得**在长线中形成「连拍只会挨打」的机械重复；须与**反派冷却/留白**、**主角破局本能**协同，使下一事件自然获得 A/B 驱动空间。

仍需简要回答：资源增减、欲望/恐惧权重（写入 `psychological_pressure` / `resource_delta`），但**禁止**把每一步都写成刚需极端态。

### 第三步：命运交汇（Intersect · 禁止「章章当面掐架」）

🚨 **【伏笔有机收束法则 (Organic Karmic Harvest)】** 🚨  
请扫视用户消息中的「因果账本 karmic_ledger」JSON。若你看到带有 **`[🚨 急需回收]`** 前缀的老伏笔，表示该因果之「果」已成熟。本次事件生成中请**尽量克制**铺开全新的宏大悬念，优先将这些老伏笔**自然编织**进当前剧情（须与 Scene Snapshot、物理与资产铁律一致）。

**拒绝生硬空降、机械降神**（禁止为了回收而回收）。可选用以下**三种**高级写法之一完成回收或推进；择一为主，勿堆砌巧合：

1. **🔧 借力打力 / 旧物新用**：主角面对当前危机时，发现很久前得到的某件不起眼物证或资源（老伏笔）恰好是破局关键，且用途与当下压力结构因果相扣。  
2. **🕸 宿命交织 / 暗网收束**：主角当下的独立议程、新场景或新出现人物，在推进中被必要地揭示，与多年前那条未解之谜（老伏笔）存在可核对的利益/血缘/组织线索，而非顺口硬编。  
3. **🗡 因果反噬 / 仇家寻仇**：旧日梁子或未竟之敌（老伏笔）因主角近期行为在信息链上被重新锁定，在戏剧上构成「不得不发生」的对撞，时间地点须服从当前空间约束。

⚠️ **柔性兜底**：若本事件场景（如密室、单线逃亡、强物理隔离）**实在**无法自然嵌入该老伏笔的实质回收，**禁止**硬塞降神；允许仅在事件尾部埋下**一条**指回该伏笔的微小线索（一纸残页、一枚同源纹记、半句谣言等），为后续事件正式引爆铺路，并在叙事上交代「为何此刻只能到这一步」。

判断 World Tick 产出的世界议程与 Protagonist Tick 产出的主角脉动是否在**物理空间、利益链或时间压力轴**上发生**交汇**（结构性必然，禁止廉价巧合）。
**交汇类型** `intersect_type` 必须是以下之一（每次事件只选一主类型）：
- **正面碰撞**：双方（或代理人）在同一时空当场对决、对峙、正面利益交换，张力直接对撞。
- **错位擦肩**：同一地点/同一条利益链上近乎相遇但未照面，或仅留下物证/痕迹/误读信号，靠信息差拉升悬念（仍须写清结构性必然，而非纯巧合）。
- **单边推进**：本拍以主角线或世界线之一为戏剧主轴（如闭关、养伤、发育、转移），另一线在后台推进或扑空；两线通过新闻、后果、时间窗或资源消耗仍形成**因果锁定**（不是毫无关系的平行剪辑）。

节奏提醒：若连续多事件均为「正面碰撞」，须在 `global_context_check` 中主动 diversify；沙盒允许发育与错位喘息。

- 产出：`collision` 对象须含 `intersect_type`，以及 `collision_trigger`（为何本拍必发生此交汇）、`collision_outcome`（交汇后的优劣与代价）、`state_changes`、`new_causal_seeds`。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【事件完整性约束：单元感设计（补丁 J）】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
每个事件应有相对完整的单元感（一桩委托、一次 explore、一场有头有尾的遭遇），禁止无休止追杀流水账。
结算时须在 `causal_chain` 中标注 **`event_result_type`**（三选一，**只允许以下机器枚举值**，勿自造别名）：
- **`A_closed`**：闭合型——本章题暂告段落；收获多为阅历、人脉、小钱、小仇；**不必**塞主线碎片。
- **`B_fragment`**：碎片型——表面委托也完事，但**碰到主线碎片**；`karmic_ledger_updates` 宜写清碎片；**不宜**让 B 在相邻事件连续出现超过 2 次（对照 `completed_events_summary` 自调）。
- **`C_open`**：开放型——处境被重新打开，下一拍方向仍锚定 `independent_agenda`，**不要**全靠外部追杀定义。
软比例（一卷内心智锚）：A_closed 应多（建议 ≥50%），B_fragment 与 C_open 各占约 20～30%；若近期 B 过密，本次倾向 A_closed。

## 里程碑意识（milestone_check · 沙盒引力场）
本卷规划使用**无序**的 `milestone_conditions`：不要把它当成「必须先 A 后 B」的线性清单。
每个事件后须对照**最近关注的待完成里程碑**（见用户消息中的 pending 列表）：
- 本事件是否已使某条 `trigger_state` 所描述的**世界状态**被满足？（状态检验，禁止还原大纲微动作。）
- **禁止讨好型假结算**：先写证据，再下布尔结论。
  - 填写 `evidence_of_completion`：若认为已满足，用 2～4 条**可核对的事实陈述**（对应 `trigger_state` 的关键语义，禁止空泛套话）；若未满足，写清**缺口**（亦须实质内容，禁止仅「还在推」两字）。
  - 填写 `is_trigger_state_fully_met`：仅当证据与 `trigger_state` **严格对齐**时为 true；略沾边、强行Interpret 的一律 false。
  - `milestone_completion_verified` 必须与 `is_trigger_state_fully_met` 同值（兼容旧解析；二者矛盾时以 `is_trigger_state_fully_met` 为准）。
- `nearest_pending_milestone_id`：本事件主要对齐检查的 pending 里程碑 id；未满足时说明 drift。

## 【伏笔与因果账本】（与第三步「有机收束法则」一致；见用户消息 `karmic_ledger`）
带 **`[🚨 急需回收]`** 的 pending 项须有推进或按第三步**柔性兜底**埋线；禁止无视、禁止机械降神式硬回收。

## 全局防重复（global_context_check）
对照 `completed_events_summary`：
- 本事件的核心冲突类型（conflict_type）是否已经出现超过2次？
- 本事件的主要动用资源（primary_resource_used）是否已经连续复用超过2次？
- `protagonist_tick_type` 是否**连续**将主角写成无力回击的木偶（若是，参照「破局与反制本能」与反派冷却，本事件倾向 A/B）？
- 近期 `event_result_type` 是否 **B_fragment** 过密（若过密，本次倾向 **A_closed**）？
- 若存在重复风险，必须调整本事件的碰撞维度或冲突形式

## 输出规范
只返回 JSON，不加任何前言或说明文字。
所有字符串字段不得为空（最短也需要2-5字的实质内容）。
"""

# ─── 用户提示模板 ─────────────────────────────────────────────────────────────

EVENT_CHAIN_GEN_USER_TEMPLATE = """\
{scene_snapshot_section}{quest_stack_section}## 世界档案（world_archive）
{world_archive}

## 角色关系卡（entity_cards · World Tick 扫描维度二输入）
{entity_cards_block}

## 主角档案（protagonist_archive）
{protagonist_archive}

## 世界词条库（world_lexicon · World Tick 资源竞争背景）
{world_lexicon_active}

## 因果账本（karmic_ledger）
{karmic_ledger}

## 本卷里程碑引力场（milestone_conditions · 无序状态条件）
{volume_milestones}

## 里程碑推进进度（milestone_progress）
已完成里程碑 ID：{completed_milestones}
待完成里程碑 ID：{pending_milestones}

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
基于上述档案与进度，执行命运编织引擎（含第零步 Scene Snapshot 与以下 World Tick / Protagonist Tick / 命运交汇 Intersect），生成**下一个事件**。

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
    "protagonist_tick_type": "A主动委托 | B主动调查 | C被动应对",
    "active_action": "主角此刻主动在做什么（优先 independent_agenda；C 型写被迫应对的主行动）",
    "action_origin": "独立议程 | 上一事件线索延伸 | 谋生需求 | 任务栈 critical（仅警报时） | 其他",
    "passive_pressure": "C 型时外部压力一句；A/B 填 null",
    "deepest_need": "此刻最在意什么（可与 active_action 一致；警报任务驱动时对齐 current_sub_goal）",
    "core_principle": "本拍遵守的核心生存原则（一句）",
    "protagonist_intent": "汇总句：推动本事件的主意图（须与 tick_type、车道规则自洽）",
    "resource_delta": {{
      "gained": ["获得的资源/信息/关系"],
      "lost": ["失去的资源/信息/关系"]
    }},
    "psychological_pressure": "欲望 vs 恐惧 / 主动劲带来的张力（非空洞形容词堆砌）",
    "quest_driven": false,
    "driving_quest_id": "仅 quest_driven=true 时填 quest_id；否则 null"
  }},

  "collision": {{
    "intersect_type": "正面碰撞 | 错位擦肩 | 单边推进",
    "collision_trigger": "本拍交汇的结构性必然原因（禁止巧合）；单边推进时写清时间窗/因果轴如何仍锁定两线",
    "collision_outcome": "交汇结果——谁获优势、谁付代价或谁错失（不可回避）；错位擦肩须写清信息差状态",
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
    "event_result_type": "A_closed | B_fragment | C_open",
    "immediate_effect": "即时可见的果（委托结单/遭遇落定/处境位移等，20-80字）",
    "hidden_seeds": "隐藏种子：A 偏阅历与人脉仇缘；B 必须点出主线碎片与疑虑；C 偏开放压力与议程重定向",
    "from_last_event": "承接上一事件的因果线索（第一个事件填「全书开篇」）",
    "to_next_event": "本事件为下一事件准备的因果条件（不定义具体内容，只描述因果土壤）",
    "archive_writeback": {{
      "world_archive_updates": ["需要同步到 world_archive 的状态变化（格式：字段路径: 新值描述）"],
      "protagonist_archive_updates": ["需要同步到 protagonist_archive 的状态变化"],
      "karmic_ledger_updates": ["需要添加/修改的因果账本条目（格式：+新增伏笔描述 或 ~修改已有条目）"]
    }}
  }},

  "milestone_check": {{
    "nearest_pending_milestone_id": "待聚焦的里程碑 milestone_id（须为 pending 列表中一项）",
    "evidence_of_completion": "已满足则列可核对事实；未满足则说明缺口（禁止空洞敷衍）",
    "is_trigger_state_fully_met": false,
    "milestone_completion_verified": false,
    "drift_assessment": "靠近/偏离（简要说明与里程碑条件的距离状态）",
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
        ert = (evt.get("event_result_type") or "").strip() or "?"
        ptt = (evt.get("protagonist_tick_type") or "").strip() or "?"
        lines.append(
            f"{i}. [{evt.get('event_id', '?')}] {evt.get('event_name', '?')} "
            f"| 结果类型: {ert} | 主角脉动: {ptt} "
            f"| 冲突类型: {evt.get('conflict_type', '?')} "
            f"| 主要资源: {evt.get('primary_resource_used', '?')} "
            f"| 触达里程碑: {evt.get('milestone_touched', '无')}"
        )
    if not lines:
        return "（格式异常，无法解析已完成事件）"
    total = len(summary_list)
    prefix = f"（共 {total} 个已完成事件；展示最近 {len(lines)} 个）\n"
    return prefix + "\n".join(lines)


def format_milestones_for_event_gen(milestones: list, milestone_progress: dict) -> str:
    """将 milestone_conditions 与进度合并为注入文本。"""
    if not milestones:
        return "（未找到本卷里程碑规划）"
    completed_ids = set((milestone_progress or {}).get("completed", []))
    lines = []
    for m in milestones:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("milestone_id") or "").strip() or "?"
        status = "✓ 已完成" if mid in completed_ids else "○ 待完成"
        closer = " [收卷位]" if m.get("is_volume_closer") else ""
        lines.append(
            f"[{status}] {mid}{closer} | kind={m.get('milestone_kind', '?')} | {m.get('name', '?')}\n"
            f"  trigger_state: {m.get('trigger_state', '?')}\n"
            f"  forbidden_micro_actions: {m.get('forbidden_micro_actions', '')}"
        )
    return "\n".join(lines)

