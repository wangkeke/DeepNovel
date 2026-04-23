# DeepNovel v4.2 · 专项重构文档
## 事件链两阶段混合架构 × 卷规划重构

> **文档定位**：本文档是对 v4.2 主文档中 `story_arc_plan`（PROMPT 6）与
> `event_chain_gen`（PROMPT 7）两个节点的专项重构，内容以本文档为准，
> 合并时覆盖主文档对应章节。

---

## 一、为什么需要重构？

### 旧方案的根本缺陷

旧版 event_chain_gen 的生成流程是：

```
生成骨架（N个事件）→ 按批填充细节
```

这本质上是**先规划，再填充**。模型在生成骨架时处于上帝视角，
已经知道第21个事件是什么，因此中间每个事件都在隐性地"走向预定终点"。

这与白皮书的核心原则直接矛盾：

> 并非事件推动人，而是人推动事件。
> 每个事件是角色在当下处境下自然做出选择的结果，
> 而不是被预定终点倒推出来的过程。

**批量生成的具体问题**：

- 事件细节填充时，模型可能丢失事件（日志中 ID 9/10/19/20 被丢失并用骨架补回），
  说明批量填充本身就是不稳定的
- 骨架阶段已经确定了所有事件的走向，循环推导的输入并不是真实更新的世界状态，
  而是预想的状态，角色的 emotional_capacity 消耗、势力的 current_status 变化、
  karmic_ledger 的新增伏笔，都没有真正影响后续事件的生成

**旧版 story_arc_plan 的配合缺陷**：

卷规划的输出是散落在多个叙述性字段里的信息，event_chain_gen 无法直接读取
明确的锚点位置和到达条件，只能自行推断——这又把"自由发挥"的空间还给了模型。

---

## 二、两阶段混合架构的设计原理

### 核心矛盾与解法

纯粹的批量生成：全局可控，但事件不是推导出来的，是设计出来的。

纯粹的逐事件循环推导：每个事件都真实生长，但没有全局意识，事件链可能跑偏。

**解法：锚点约束战略方向，循环推导负责有机生长。**

```
锚点1 ──循环推导──> 事件 ──> 事件 ──> 事件 ──> 锚点2
                    ↑                           ↑
              每次推导后                   临近时做
              立刻回写档案                漂移校验

锚点2 ──循环推导──> 事件 ──> 事件 ──> 锚点3
```

锚点是战略约束，只规定里程碑类型（如"规则反转"），不规定具体内容。
锚点之间的所有事件，由循环推导从真实的当下档案状态中自然生长。

---

## 三、重构后的 `story_arc_plan`（PROMPT 6 完整版）

**节点职责**：从档案推导分卷宏观骨架，并生成 event_chain_gen Phase 1
可以直接读取的显式锚点列表。

**上游输入**：world_archive + protagonist_archive +
opening_collision + iceberg_structure + user_anchors。

**下游输出**：arc_plan（含 arc_anchors），注入 event_chain_gen。

```
你是一位深谙商业网文节奏的结构设计师。

你现在拥有：完整的世界势力格局、主角的性格与成长轨迹、
开篇的碰撞结构和冰山暗流。
分卷规划必须从这些已有的真实信息中推导出来，而不是凭空设计情节。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
基本约束
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【篇幅是参考，不是枷锁】
单卷参考篇幅：50～150章，根据世界观宏大程度与博弈复杂度动态分配。
这是参考上限，而非硬性要求。
实际章节数由循环推导自然生成，不强行填充或压缩。
⚠️ 但每卷不得少于50章——低于此数，多方博弈就没有物理空间展开。

【破冰必须闪电，连锁才是正餐】
开篇的微型危机（即 opening_collision），必须在1-3个里程碑内极速解决。
破冰之后，用广阔篇幅迎接由此引发的更大连锁反应。

【卷与卷之间的麻烦守恒】
每卷结束时，主角的段位/圈层必然已经跃迁。
下一卷的麻烦量级大于上一卷——不是线性叠加，而是维度升级。

【暗流的浮现节奏】
iceberg_undercurrents 中的每条暗流，必须在某一卷中被安排浮出水面。
不要让所有暗流都在同一卷里爆发，也不要让某几卷完全没有暗流浮现。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
arc_anchors 的设计规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

arc_anchors 是本卷的战略锚点列表，是 event_chain_gen Phase 1 的
唯一读取来源。

锚点的数量规则：
- 锚点1：永远是开篇碰撞（直接来自 iceberg_deduction 的 opening_collision）
- 锚点N：永远是圈层跃迁（对应 protagonist_ending_position）
- 中间锚点：2-3个，对应本卷必须发生的关键转折
- 总数控制在3-5个
  ⚠️ 超过5个就变成微观管控，会压制循环推导的有机生长空间

锚点的内容规则：
- 每个锚点只定义里程碑类型（见下方枚举），不定义具体内容
- 每个锚点声明 arrival_condition：到达时世界状态必须满足什么条件
- 具体发生什么，由锚点之间的循环推导自然生成

里程碑类型枚举：
- 开篇碰撞：世界运转与主角需求的第一次交汇
- 规则反转：主角发现表面规则之下的真实游戏
- 结盟：利用人际杠杆，整合可用资源
- 破局：精神层面驱动四维资源，完成决定性行动
- 圈层跃迁：主角进入更高圈层，旧麻烦解决，新维度麻烦开始
- 伏笔引爆：前置伏笔在最意想不到的时机爆发
- 暗流浮现：iceberg_undercurrents 中某条暗流浮出水面

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "total_arcs": "预计总卷数",
  "arcs": [
    {
      "arc_id": "卷号",
      "arc_title": "卷名",
      "estimated_chapters": {
        "target_range": "50-80（参考区间，非硬性要求）",
        "derivation_note": "实际章节数由锚点间的循环推导自然决定"
      },
      "arc_theme": "本卷主角要解决的根本矛盾",
      "protagonist_starting_position": {
        "tier": "所在圈层",
        "resources": "掌握的资源",
        "maturity_score": "当前成熟度档位",
        "emotional_capacity": "当前精神阈值剩余量"
      },
      "protagonist_ending_position": {
        "tier": "跃迁后的圈层",
        "maturity_change": "成熟度变化描述",
        "key_illusion_shattered": "本卷打破的幻想"
      },

      "arc_anchors": [
        {
          "anchor_id": 1,
          "position": "early（约第1-3个事件）",
          "milestone_type": "开篇碰撞",
          "arrival_condition": "主角已被卷入冲突，触发条件和违背原则与
                               opening_collision 一致",
          "content_source": "直接来自 iceberg_deduction 的 opening_collision，
                            不由循环推导重新生成",
          "content_constraint": "具体碰撞细节已在 opening_collision 中锁定"
        },
        {
          "anchor_id": 2,
          "position": "mid-early（约第N个事件，给出大致区间）",
          "milestone_type": "规则反转/暗流浮现/伏笔引爆（从枚举中选择）",
          "arrival_condition": "到达此锚点时，世界状态必须满足的条件
                               （如：主角的某项资源已被消耗、
                               某股势力的 current_status 已发生变化、
                               某个 karmic_ledger 中的伏笔已埋下）",
          "content_constraint": "只约束里程碑类型，具体内容由循环推导生成；
                                如果此锚点对应 iceberg_undercurrents 中某条暗流，
                                声明 source 字段"
        }
        // 中间锚点按需增加，总数3-5个
        ,
        {
          "anchor_id": "N（最后一个）",
          "position": "late（约最后2-3个事件）",
          "milestone_type": "圈层跃迁",
          "arrival_condition": "主角已完成本卷核心目标，
                               protagonist_ending_position 中描述的
                               状态变化已基本发生",
          "content_constraint": "跃迁的具体方式由循环推导生成，
                                必须对应 maturity_events 中的某个触发事件"
        }
      ],

      "background_context": {
        "main_antagonist": "本卷核心对手及其资源诉求（来自 world_archive）",
        "new_factions_entering": ["新介入的势力（来自 world_archive faction_id）"],
        "undercurrents_scheduled": ["本卷计划浮现的暗流（来自 iceberg_undercurrents）"],
        "foreshadows_to_plant": ["本卷需要埋下的新伏笔方向"],
        "foreshadows_to_harvest": ["本卷计划引爆的前卷伏笔（来自 karmic_ledger）"],
        "maturity_events": ["主角/核心角色的成熟度跃迁触发事件"]
      }
    }
  ]
}

⚠️ arc_anchors 是机器可读的执行契约，event_chain_gen 直接读取。
⚠️ background_context 是人类可读的背景描述，供人工审核参考，
   不作为 event_chain_gen 的直接输入。
```

---

## 四、重构后的 `event_chain_gen`（PROMPT 7 完整版）

**节点职责**：基于两阶段混合架构生成本卷完整事件链。
Phase 1 读取 arc_anchors 锁定战略锚点，
Phase 2 在锚点之间运行循环推导有机生长事件。

**上游输入**：world_archive（全量）+ protagonist_archive +
所有配角卡 + karmic_ledger + 上一批事件最终状态 +
当前卷 arc_plan（含 arc_anchors）。

```
你是这个世界的造物主，同时也是一位冷静的博弈论学者。
你需要为本卷生成一条因果自洽、张力饱满的事件链。

事件链的生成必须严格遵循两阶段混合架构，不可跳过任何步骤。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
强制输入（运行前必须注入）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 全量人物档案：
   每个重要角色的 innate_traits + mental_core + maturity_level
   + independent_agenda + 当前 emotional_capacity 剩余量

2. 全量势力档案：
   每股势力的 resource_claim + relationships + current_status

3. 当前因果账本（Karmic Ledger）：
   所有已埋下但尚未引爆的伏笔（seed_id + holder + estimated_payoff）

4. 上一卷/上一批事件的最终状态：
   哪些"果"已经发生，尚未成为"因"的部分是什么

5. 当前卷的 arc_plan（含 arc_anchors）：
   本卷的战略锚点列表，Phase 1 直接读取

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 1：锚点读取与三步命运编织（一次性，不循环）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

从 arc_anchors 中读取本卷的所有锚点，锁定：
- 每个锚点的里程碑类型
- 每个锚点的 arrival_condition
- 锚点的数量与大致位置区间

锚点1（开篇碰撞）特殊处理：
直接从 iceberg_deduction 的 opening_collision 读取，
不再重新运行三步命运编织引擎——开篇碰撞已经在 iceberg_deduction
阶段被推导和创造，这里直接继承。

对中间锚点和最后锚点，运行三步命运编织引擎：

【Step 1：World Tick——物理隔离主角】

在这一步，主角不存在。
从全量人物档案和势力档案中，对每一个重要角色/势力独立运行推导：

处境分析（从 current_status 和 karmic_ledger 中读取）：
他最近得到了什么？失去了什么？面临什么威胁？看到了什么机会？

性格投射（从 innate_traits 推导，不套用模板）：
给定他的先天性格，他评判当前处境的视角是什么？
他最在意的东西在当前处境下是否受到威胁或有机可乘？

自然行动：
给定性格和处境，他不得不做什么？
（不是"他能为故事做什么"，而是"他无法不做什么"）

输出：N个并行的世界议程，每个都有来自档案的溯源依据。

【Step 2：Protagonist Tick——物理隔离世界】

在这一步，世界的其他事件暂时不存在。
从 protagonist_archive 中读取，推导主角此刻：

- 最在意的东西（来自 core_desire + 当前 world_position）
- 最惧怕发生的事（来自 core_fear）
- 为了最在意的东西愿意付出的代价上限
  （来自 endurance + maturity_level）
- 目前遵守的最核心生存原则
  （来自 innate_traits + 当前成熟度推导）

输出：主角当前最深的一个需求，以及他为此愿意和不愿意做的事。

【Step 3：Fated Collision——强制创造，而非寻找】

给定世界议程和主角需求，在二者之间强制构建一个逻辑自洽的连接细节。
这个细节必须是被创造出来的，不是碰巧已经存在的，
但必须符合 world_physics 和选定势力的 internal_logic。

质量校验（三个条件必须同时满足）：
- 交汇点对世界有一种意义，对主角有完全不同的另一种意义
- 主角进入这个交汇点，是被他最在意的东西逼进去的
- 进入要求他违背某个本能或原则

三个条件全部满足，碰撞成立。
如果不满足，调整创造的细节或选定的世界议程，重新校验。

Phase 1 输出：
- 各锚点之间的"世界状态预期"——锚点的 arrival_condition 对应的世界状态
- 开篇碰撞锚点的完整细节（直接继承自 opening_collision）
- 中间各锚点的碰撞设计草案（供 Phase 2 的漂移校验使用）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 2：循环推导（锚点之间逐事件运行）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

每个锚点之间的事件，通过以下循环逐一生成。
每次循环只生成一个事件，生成后立刻回写档案，再推导下一个。

【单次循环的执行步骤】

Step A：读取当前档案状态
  从 world_archive、protagonist_archive、karmic_ledger 中
  读取上一事件结束后的真实世界状态。
  ⚠️ 必须是上一事件回写后的状态，不是 Phase 1 时预想的状态。

Step B：运行四步推导引擎

  第一步：锁定当前处境
  从档案中读取每个相关角色此刻拥有什么资源、缺少什么、
  掌握哪些信息、对哪些一无所知、面临什么威胁、看到了什么机会。

  第二步：从性格推导意志
  给定这个角色的先天性格和当前成熟度：
  他最想要的是什么？他最惧怕的是什么？
  他评判这个处境的视角，和别人有什么根本不同？

  第三步：从意志推导最优行动
  给定他的资源、信息状态和性格意志：
  他能采取的行动有哪些？每种行动的代价和收益是什么？
  哪种行动是他这个人在这个时刻最自然会选择的？

  第四步：推导对手的应对
  对手用同样的逻辑推导出了什么？
  双方的推导链在哪个节点产生了交叉？
  谁的信息更完整？谁的性格让他做出了对方没有预料到的选择？

  ⚠️ 推导走完后，自然生长出的行动可能对应某个古老智谋的名字，
  也可能是全新的组合。这都不重要。
  重要的是它来自角色的内部逻辑，而不是从模板里取来的。

Step C：生成本事件的完整输出（见输出规范）

Step D：立刻回写档案
  将本事件的结果回写到：
  - 相关角色的 emotional_capacity（消耗量）
  - 相关势力的 current_status（如有变化）
  - karmic_ledger（新埋伏笔 / 已引爆伏笔）
  ⚠️ 回写必须在下一次循环开始前完成，确保每次推导的输入
  是真实更新的世界状态。

Step E：漂移校验（临近下一锚点时触发）
  当距离下一个锚点还有1-2个事件时，运行漂移校验：

  检查当前世界状态是否满足下一锚点的 arrival_condition。

  情况一：状态与 arrival_condition 自然吻合
  → 继续循环，锚点事件将自然生成

  情况二：状态轻微偏离（关键指标接近但未完全满足）
  → 在当前事件中对某个角色的行动做微调，使状态贴近 arrival_condition
  → 微调必须符合角色性格逻辑，不能强行让角色做出违背性格的事

  情况三：状态严重偏离（无法在1-2个事件内自然走向锚点）
  → 不强行接上逻辑断裂的锚点
  → 输出漂移报告，标记偏离程度和原因
  → 路由到 human_review_event_chain，由人工决定：
     a) 接受当前走向，调整锚点内容
     b) 接受当前走向，跳过该锚点
     c) 回滚到上一个锚点，重新推导

Step F：判断是否继续循环
  如果未到达下一锚点的位置区间 → 继续循环（回到 Step A）
  如果已到达下一锚点的位置区间且漂移校验通过 → 生成锚点事件，
  然后继续下一段锚点间的循环

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
因果环的强制咬合规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

事件链是首尾咬合的因果环，不是线性排列。

每生成一个事件节点时，必须同时声明：
- 它的"因"来自哪里（上一事件的哪个 causal_output 触发了它）
- 它的"果"将成为未来哪个节点的"因"（即使模糊方向也必须给出）

整条事件链的最后一个事件，必须埋下至少一颗种子，
指向下一卷的某个还未明确的矛盾——链的结尾，是下一条链的开口。

禁止出现孤立的事件节点（只有果没有因，或只有因没有果）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
单事件输出规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

每次循环生成一个事件，输出以下结构：

{
  "event_id": "事件唯一标识（如 arc1_e003）",
  "is_anchor": false,
  "anchor_id": null,

  "causal_input": {
    "from_event": "触发本事件的前置事件 event_id",
    "trigger_mechanism": "前置事件的哪个果触发了本事件的因"
  },

  "world_state_at_start": {
    "key_changes_since_last": ["上一事件回写后，档案发生了哪些关键变化"]
  },

  "derivation_log": {
    "who_drives": "谁的意志在驱动本事件（来自四步推导的第一步）",
    "their_logic": "他的性格+处境+意志推导出的行动逻辑（第二、三步）",
    "opponent_response": "对手的推导与应对（第四步）"
  },

  "milestone_type": "入局探索/规则反转/结盟/破局/圈层跃迁/伏笔埋设/伏笔引爆",

  "conflict_core": "本事件的核心矛盾",

  "karmic_resources": {
    "info_gap": "本事件中的信息差",
    "human_leverage": "可利用的人际杠杆",
    "time_pressure": "时间差与死线",
    "geo_advantage": "地理或环境优势"
  },

  "mental_lever": {
    "protagonist_trait": "主角用哪项精神层面维度驱动破局",
    "antagonist_trait": "对手用哪项精神层面维度设局"
  },

  "resolution_path": "破局的具体路径（从推导引擎自然生成）",
  "resolution_cost": "破局的代价（精神消耗/关系损伤/暴露风险）",

  "causal_output": {
    "immediate_fruit": "表面上的胜负结果",
    "hidden_seed": "这个结果暗中埋下的未来隐患",
    "payoff_timing": "immediate（下一事件）/ delayed（第N个事件方向）"
  },

  "archive_writeback": {
    "character_updates": [
      {
        "character_id": "角色标识",
        "emotional_capacity_delta": "本事件消耗量（负数）或恢复量（正数）",
        "maturity_trigger": "是否触发成熟度跃迁（null或描述）"
      }
    ],
    "faction_updates": [
      {
        "faction_id": "势力标识",
        "status_change": "current_status 变化描述"
      }
    ],
    "karmic_ledger_updates": {
      "seeds_planted": [
        {
          "seed_id": "伏笔标识",
          "description": "伏笔内容",
          "holder": "持有者",
          "estimated_payoff": "预计引爆时机"
        }
      ],
      "seeds_harvested": [
        {
          "seed_id": "被引爆的伏笔标识",
          "actual_payoff": "实际引爆方式"
        }
      ]
    }
  },

  "drift_check": {
    "next_anchor_id": "下一个锚点的 anchor_id",
    "distance_to_anchor": "还有几个事件到达下一锚点",
    "arrival_condition_status": "满足/轻微偏离/严重偏离",
    "adjustment_made": "如有微调，描述调整内容（无调整填null）"
  }
}

锚点事件的输出在以上基础上新增：

{
  "is_anchor": true,
  "anchor_id": "对应 arc_anchors 中的 anchor_id",
  "arrival_condition_met": "arrival_condition 是否完全满足（是/否+说明）",
  "phase1_design_vs_actual": "Phase 1 时的碰撞设计草案与实际生成内容的差异说明"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 2 完成条件
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

以下任一条件成立时，本卷事件链生成完成：

条件一：最后一个锚点（圈层跃迁）已生成，
且主角状态符合 protagonist_ending_position 的描述。

条件二：漂移校验触发了严重偏离报告，
路由到 human_review_event_chain 等待人工决策。

完成后，输出本卷事件链的汇总索引：

{
  "arc_id": "卷号",
  "total_events_generated": "实际生成的事件总数",
  "anchor_events": ["已完成的锚点 event_id 列表"],
  "estimated_chapters": "基于事件数量和密度估算的实际章节数",
  "chain_integrity_check": {
    "orphan_events": ["无 causal_input 的孤立事件（应为空）"],
    "open_seeds": ["已埋下但本卷内未引爆的伏笔 seed_id 列表"],
    "next_arc_entry_seed": "指向下一卷的种子事件描述"
  }
}
```

---

## 五、两个节点之间的数据流

```
story_arc_plan
  ├─ arc_anchors ──────────────────────────────→ event_chain_gen Phase 1（直接读取）
  └─ background_context ───────────────────────→ event_chain_gen（背景参考）

event_chain_gen Phase 1
  ├─ 锚点碰撞草案 ────────────────────────────→ Phase 2 漂移校验的比对基准
  └─ 锁定锚点位置和 arrival_condition ─────────→ Phase 2 每次循环的导航目标

event_chain_gen Phase 2（每次循环）
  ├─ 读取：world_archive + protagonist_archive + karmic_ledger（当前真实状态）
  ├─ 生成：单事件输出
  ├─ 回写：archive_writeback → world_archive + protagonist_archive + karmic_ledger
  └─ 漂移校验：drift_check → 决定是否微调或路由到 human_review

event_chain_gen 完成
  └─ 事件链汇总索引 ───────────────────────────→ path_gen（按事件生成章节路径）
                    ───────────────────────────→ expand1（每章读取对应事件详情）
```

---

## 六、与主文档的对照变更说明

| 主文档位置 | 变更内容 |
|-----------|---------|
| PROMPT 6 story_arc_plan 输出规范 | 新增 `arc_anchors` 字段；`estimated_chapters` 改为软性参考区间；原 `opening_micro_crisis`、`undercurrents_emerging`、`key_foreshadows_*`、`maturity_events` 字段移入 `background_context`，不再作为机器可读的直接输入 |
| PROMPT 7 event_chain_gen 整体 | 原"骨架+批量填充"架构完全替换为"Phase 1 锚点读取+Phase 2 循环推导"两阶段架构；新增单事件输出规范（含 `archive_writeback` 和 `drift_check`）；新增 Phase 2 完成条件和汇总索引 |
| 第六章设计决策 | 新增 6.7：为什么选择两阶段混合架构而非纯循环推导或纯批量生成 |

### 新增设计决策 6.7

**为什么选择两阶段混合架构？**

纯批量生成的问题：事件是被设计出来的，不是推导出来的。
骨架阶段已知终点，中间每个事件都在隐性地走向预定结局，
角色的真实状态变化无法影响后续事件。

纯循环推导的问题：没有全局意识，事件链可能持续跑偏，
到故事中段已经面目全非，且模型自己无法发现。

两阶段混合架构的核心逻辑：

锚点是战略约束，只约束里程碑类型和到达条件，不约束具体内容。
这保证了故事不会跑偏，同时给每个事件的有机生长留出了足够空间。

循环推导保证每个事件都从真实的当下状态中生长出来。
每次循环读取的是上一事件回写后的档案，不是 Phase 1 时预想的状态。
这意味着一个角色在事件3中情绪透支，会切实影响他在事件4中的选择——
而不是按照骨架规划继续"扮演"那个情绪稳定的角色。

漂移校验是安全阀，而不是纠错器。
它不强行把偏离的事件链掰回锚点，而是在严重偏离时暂停并报告，
让人工决策是接受新走向还是回滚——这是对有机生长的尊重，
而不是对预定结局的强制维护。

---

> **文档版本**：专项重构文档 · 配套 DeepNovel v4.2
> **适用节点**：story_arc_plan（PROMPT 6）、event_chain_gen（PROMPT 7）
> **核心变更**：story_arc_plan 新增 arc_anchors 显式锚点字段；
> event_chain_gen 从批量生成架构完全重构为两阶段混合架构（Phase 1 锚点读取 + Phase 2 逐事件循环推导）。
