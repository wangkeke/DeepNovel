# DeepNovel v4.3 · 架构重构专项文档（终版）
## 事件驱动的分层叙事架构

> **文档定位**：本文档是对 v4.2 主文档中
> `story_arc_plan`（PROMPT 6）、`event_chain_gen`（PROMPT 7）、
> `path_gen`、`expand1`（PROMPT 8）、`expand2`（PROMPT 9）
> 五个节点的专项重构，内容以本文档为准，合并时覆盖主文档对应章节。

---

## 一、核心设计原则：层级与处理对象必须匹配

本架构最重要的约束是：**每个节点只处理属于它这个层级的问题**。

```
层级        处理对象           核心问题                    主要工具
─────────────────────────────────────────────────────────────────────
卷级    →  锚点（方向约束）   本卷必须经历哪些关键转折？   story_arc_plan
事件级  →  事件（抽象单元）   这件事为什么在此刻发生？     三步命运编织引擎 + 因果环
路径级  →  叙事展开           这件事怎么一步步呈现？       叙事拆解（编剧视角）
章节级  →  单个路径           这一章怎么规划？             档案状态 + 全局辅助
场景级  →  场景序列           拆成哪些具体场景？           角色性格 + 当前状态
文字级  →  正文               怎么写？                     写作信仰
```

**最常见的错误**是把下层工具用到了上层节点，
或者让上层节点预测下层节点的工作——这都会制造冗余和一致性难题。

---

## 二、架构全貌与循环结构

### 两个嵌套循环

```
【外循环：事件循环】
story_arc_plan（输出 arc_anchors）
  ↓
event_chain_gen（生成一个事件）
  ↓
path_gen（把这个事件拆解为叙事路径，每条路径 = 一章）
  ↓
【内循环：章节循环，对每条路径执行】
expand1 → expand2 → write → tension_check → auto_review → bible_update
  ↓
bible_update 判断：当前事件的所有路径是否写完？
  ├─ 否 → 继续内循环（下一条路径 → expand1）
  └─ 是 → 判断是否进入外循环下一轮
              ├─ 锚点未全部完成 → event_chain_gen（下一个事件）
              └─ 所有锚点完成 + 章节数 >= 50 → 卷收束
```

### 完整流程图

```
START
  └─ load
       ├─ 新项目 → idea_forge
       ├─ 续传有未完成章节 → expand1
       └─ 续传无未完成章节 → event_chain_gen

【初始化链】
idea_forge
  └─ world_build → human_review_world
       └─ protagonist_card → human_review_protagonist
            └─ iceberg_deduction → human_review_iceberg
                 └─ genesis_ignition → human_review_genesis
                      └─ story_arc_plan → human_review_story_arc
                           └─ mode_select

【事件循环】
event_chain_gen（生成一个事件）
  └─ human_review_event（人工模式）/ 直接进入（自动模式）
       └─ path_gen（叙事路径拆解）
            └─ human_review_path（人工模式）/ 直接进入（自动模式）

【章节循环（对每条路径执行）】
expand1（章节规划）
  ├─ 人工模式 → human_review_expand
  │              ├─ 驳回 → 回 expand1
  │              └─ 通过 → expand2
  └─ 自动模式 → expand2

expand2（场景拆解）
  └─ write（正文生成）
       └─ tension_check
            ├─ 需重写 → 回 write
            ├─ 自动审稿 → auto_review
            └─ 人工审稿 → human_review_write
                              ├─ 通过 → bible_update
                              ├─ 文字问题 → write
                              ├─ 场景问题 → expand2
                              └─ 方向问题 → expand1

bible_update
  回写档案 + 更新 anchor_progress
  判断内循环是否完成：
  ├─ 当前事件还有未完成路径 → 回到 expand1（下一条路径）
  └─ 当前事件所有路径已完成 → 判断外循环
        ├─ 锚点未全部完成 → event_chain_gen（下一个事件）
        ├─ 所有锚点完成 + 章节数 >= 50 + 人工模式 → human_review_batch
        │     ├─ 继续下一卷 → story_arc_plan
        │     └─ 结束创作 → END
        └─ 所有锚点完成 + 章节数 >= 50 + 自动模式 → story_arc_plan

【auto_review 中枢路由】
可路由到：expand1 / expand2 / write /
          human_review_expand / human_review_write /
          bible_update / human_review_batch / END
```

---

## 三、节点提示词（重构部分）

### PROMPT 6 · `story_arc_plan` — 分卷规划（新增 arc_anchors）

**节点职责**：从档案推导分卷宏观骨架，在现有输出基础上新增
arc_anchors 作为事件循环的方向约束。

**关于两次 LLM 调用的选择**：

可以选择以下任一方式实现：
- **一次调用**：直接在现有 JSON 中新增 arc_anchors 字段（推荐，保持原子性）
- **两次调用**：第一次保持原有输出不变，第二次专门生成 arc_anchors

以下采用一次调用方案，在现有输出规范末尾追加 arc_anchors。

**上游输入**：world_archive + protagonist_archive +
opening_collision + iceberg_structure + user_anchors。

```
你是一位深谙商业网文节奏的结构设计师。

你现在拥有：完整的世界势力格局、主角的性格与成长轨迹、
开篇的碰撞结构和冰山暗流。
分卷规划必须从这些已有的真实信息中推导出来，而不是凭空设计情节。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
原有规划约束（保持不变）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

【篇幅参考】
单卷参考篇幅：50～150章，根据世界观宏大程度与博弈复杂度动态分配。
⚠️ 每卷不得少于50章。
实际章节数由事件循环自然决定，不强行填充。

【破冰必须闪电，连锁才是正餐】
开篇碰撞在1-3个路径内极速解决，破局后迎接更大连锁反应。

【卷与卷之间的麻烦守恒】
每卷结束时主角必然圈层跃迁，下一卷麻烦维度升级。

【暗流浮现节奏】
iceberg_undercurrents 中每条暗流必须在某一卷浮出水面，
不要全部集中在同一卷爆发。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
新增：arc_anchors 设计规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━

arc_anchors 是本卷事件循环的方向约束，event_chain_gen 每次生成事件时
都会检查当前锚点进度，引导事件走向。

【锚点的数量规则】
- 锚点1：永远是开篇碰撞（直接来自 opening_collision，不重新推导）
- 锚点N：永远是圈层跃迁（对应 protagonist_ending_position）
- 中间锚点：2-3个，对应本卷必须经历的关键转折
- 总数控制在3-5个（超过5个变成微观管控，压制有机生长空间）

【锚点只约束类型和到达条件，不约束具体内容】
具体是哪个事件触达锚点、以什么方式触达，由事件循环自然生成。

【里程碑类型枚举】
- 开篇碰撞：世界运转与主角需求的第一次交汇
- 规则反转：主角发现表面规则之下的真实游戏
- 结盟：整合可用资源，建立脆弱联盟
- 破局：精神层面驱动四维资源，完成决定性行动
- 圈层跃迁：进入更高圈层，旧麻烦解决，新维度麻烦开始
- 伏笔引爆：前置伏笔在意想不到的时机爆发
- 暗流浮现：iceberg_undercurrents 中某条暗流浮出水面

━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出规范（现有字段 + 新增 arc_anchors）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "arc_id": "卷号",
  "arc_title": "卷名",
  "estimated_chapters": {
    "min": 50,
    "reference_range": "60-90（参考区间，非硬性要求）"
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
  "main_antagonist_this_arc": "本卷核心对手及其资源诉求",
  "new_factions_entering": ["新介入的势力"],
  "undercurrents_emerging": ["本卷计划浮现的暗流"],
  "key_foreshadows_planted": ["本卷需要埋下的新伏笔方向"],
  "key_foreshadows_payoff": ["本卷计划引爆的前卷伏笔"],
  "maturity_events": ["成熟度跃迁的触发方向"],

  "arc_anchors": [
    {
      "anchor_id": 1,
      "milestone_type": "开篇碰撞",
      "arrival_condition": "主角已被卷入冲突，触发条件和违背原则
                           与 opening_collision 一致",
      "content_source": "直接继承 opening_collision，不由事件循环重新生成",
      "completion_signal": "主角完成了违背本能原则的介入行为"
    },
    {
      "anchor_id": 2,
      "milestone_type": "从枚举中选择",
      "arrival_condition": "到达此锚点时，世界状态必须满足的条件。
                           用档案字段描述：
                           如某角色的 emotional_capacity 已降至阈值、
                           某势力的 current_status 已转为守势、
                           某条 karmic_ledger 伏笔已埋入等",
      "undercurrent_source": "如对应 iceberg_undercurrents 某条暗流，
                             填写该暗流 source 字段；否则填 null",
      "completion_signal": "判断此锚点已完成的可观察信号"
    },
    {
      "anchor_id": "N（最后一个）",
      "milestone_type": "圈层跃迁",
      "arrival_condition": "protagonist_ending_position 中描述的
                           状态变化已基本发生",
      "completion_signal": "主角进入新圈层的标志性事件已发生"
    }
  ]
}
```

---

### PROMPT 7 · `event_chain_gen` — 单事件生成

**节点职责**：每次调用只生成一个事件，回答"这件事为什么在此刻发生"。
不预测这个事件怎么展开，那是 path_gen 的工作。

**上游输入**：
- world_archive（当前真实状态）
- protagonist_archive（当前真实状态，含 emotional_capacity 剩余量）
- karmic_ledger（全量伏笔状态）
- arc_anchors + anchor_progress（当前锚点完成状态）
- 上一个事件的 causal_output
- **【全局视角】已完成事件摘要列表**（防止事件重复或高度相似）

```
你是这个世界此刻的观察者，同时也是一位冷静的博弈论学者。
你的任务是生成当前时刻世界中自然发生的下一个事件。

每次调用只生成一个事件。
这个事件是什么，由三步命运编织引擎从真实档案状态中推导出来，
不是被规划出来的。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
【全局视角：防止重复】
━━━━━━━━━━━━━━━━━━━━━━━━━━━

在运行引擎之前，先读取已完成事件摘要列表：
- 已使用过的核心冲突类型（如：信息差暴露、势力正面对抗、盟友背叛）
- 已使用过的四维资源组合（如：连续三个事件都以"信息差"为主要资源）
- 已完成的锚点（不要生成重复到达同一锚点的事件）

⚠️ 全局视角是约束，不是创作来源。
用它来排除重复，但事件本身必须从当下档案状态中生长。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
锚点导向
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取 anchor_progress 中下一个待完成的锚点：
- 如果当前档案状态自然接近该锚点的 arrival_condition：
  → 本次事件可以触达该锚点
- 如果当前状态距离该锚点还远：
  → 本次事件正常生成，推进状态向锚点方向自然演进
  → 不强行跳跃到锚点

⚠️ 锚点是目的地，不是强制路径。
事件不需要直接"走向"锚点，只需要在推进世界状态。
状态累积到位时，锚点会自然到达。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
第一步：World Tick——物理隔离主角
━━━━━━━━━━━━━━━━━━━━━━━━━━━

在这一步，主角不存在。
从 world_archive 中，找出此刻处于最紧张节点的角色或势力：

处境分析（从当前档案状态读取）：
- 哪股势力的 current_status 正处于临界状态？
- 哪个角色的 independent_agenda 与当前处境产生了最强烈的摩擦？
- 是否有角色的 emotional_capacity 已接近透支临界点？

性格投射（从 innate_traits 推导，不套模板）：
给定他的先天性格和当前处境，他最在意的东西受到了什么威胁或看到了什么机会？
他无法不做的事是什么？

输出：此刻世界正在自转的最紧迫的力量（来自档案推导）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
第二步：Protagonist Tick——物理隔离世界
━━━━━━━━━━━━━━━━━━━━━━━━━━━

在这一步，世界的其他力量暂时不存在。
从 protagonist_archive 中读取主角此刻：

- 最在意的东西（core_desire + 当前 world_position）
- 最惧怕发生的事（core_fear）
- 当前 emotional_capacity 剩余量对行为选择的实际影响
  （透支状态下的角色，其行为选择与正常状态时不同）
- 此刻遵守的最核心生存原则（innate_traits + 当前 maturity_level 推导）

输出：主角此刻最深的一个需求，以及他为此愿意和不愿意付出什么。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
第三步：Fated Collision——强制创造，而非寻找
━━━━━━━━━━━━━━━━━━━━━━━━━━━

给定世界的紧迫力量和主角的最深需求，
在二者之间强制构建一个逻辑自洽的连接细节。

这个细节必须是被创造出来的，不是碰巧已经存在的，
但必须符合 world_physics 和相关势力的 internal_logic。

质量校验（三个条件必须同时满足）：
- 交汇点对世界有一种意义，对主角有完全不同的另一种意义
- 主角被他最在意的东西逼进了这个交汇点
- 进入要求他违背某个本能或原则

三个条件全部满足，事件成立。
如不满足，调整创造的细节，直到三个条件全部成立。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
因果环声明
━━━━━━━━━━━━━━━━━━━━━━━━━━━

每个事件必须声明：
- 它的"因"来自哪里（上一个事件的哪个 causal_output 触发了它）
- 它的"果"将成为未来哪个事件的"因"（即使模糊方向也必须给出）

第一个事件的"因"来自 opening_collision。
整卷最后一个事件的"果"必须埋下至少一颗种子，
指向下一卷的某个尚未明确的矛盾。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "event_id": "事件唯一标识（如 arc1_ev003）",

  "event_name": "事件的简短名称（如：吏部郎中设局构陷）",
  "event_summary": "事件的一句话描述，用于注入全局摘要列表",

  "world_tick": {
    "active_force": "世界此刻自转的紧迫力量（来自档案推导，注明溯源）",
    "character_or_faction": "驱动这股力量的角色或势力",
    "cannot_not_do": "给定性格和处境，他无法不做的事"
  },

  "protagonist_tick": {
    "deepest_need": "主角此刻最深的需求（来自档案推导）",
    "capacity_state": "emotional_capacity 当前状态对行为的实际影响",
    "core_principle": "此刻遵守的最核心生存原则"
  },

  "collision": {
    "created_detail": "被强制创造出的交汇细节",
    "world_meaning": "这个细节对世界的意义",
    "protagonist_meaning": "这个细节对主角的意义",
    "forced_entry": "主角被什么逼进了这个交汇点",
    "principle_challenged": "进入时被挑战的本能或原则",
    "quality_check": "三个条件是否全部满足（是/否+说明）"
  },

  "event_core": {
    "conflict_type": "核心冲突类型（如：信息差暴露/势力正面对抗/盟友背叛）",
    "karmic_resources": {
      "info_gap": "本事件中的信息差",
      "human_leverage": "可利用的人际杠杆",
      "time_pressure": "时间差与死线",
      "geo_advantage": "地理或环境优势"
    },
    "resolution_direction": "事件大致朝什么方向解决（不展开具体行动，
                            留给 path_gen 拆解）"
  },

  "causal_chain": {
    "causal_input": "触发本事件的前置事件 event_id 及其 causal_output",
    "causal_output": {
      "immediate_fruit": "表面上的胜负结果",
      "hidden_seed": "这个结果暗中埋下的未来隐患",
      "payoff_timing": "immediate（下一事件）/ delayed（方向描述）"
    }
  },

  "anchor_check": {
    "touches_anchor": true/false,
    "anchor_id": "如果触达某锚点，填写 anchor_id；否则填 null",
    "arrival_condition_met": "如触达锚点，说明 arrival_condition 如何满足"
  },

  "global_context_check": {
    "conflict_type_overlap": "与已完成事件的冲突类型是否有重复？如有，
                             说明本事件如何形成差异",
    "resource_combination_overlap": "四维资源组合是否与近期事件高度相似？
                                    如有，说明差异"
  }
}
```

---

### `path_gen` — 事件叙事路径拆解

**节点职责**：把 event_chain_gen 给出的事件定义，
从编剧视角拆解为读者需要跟随的叙事路径序列。
每条路径对应一章。

这不是规划"章节类型"，而是回答：
**这件事，读者需要经历哪几个时间切片、哪几个视角转换、
哪几个关键场景，才能感受到这件事的完整重量？**

**上游输入**：
- event_chain_gen 的完整输出（事件定义）
- 相关角色当前档案状态（innate_traits + mental_core + emotional_capacity）
- **【全局视角】已完成路径的叙事节奏分布**（最近N章的节奏序列）
- karmic_ledger（哪些伏笔可以在本事件的某条路径中自然呈现）

```
你是一位编剧，你刚刚拿到了一个事件的定义：
它的核心冲突是什么，涉及哪些角色，大致朝哪个方向解决。

你的任务是把这个事件拆解为读者需要跟随的叙事路径。
不是预测章节类型，不是规划行动细节——
而是回答：这件事，应该让读者经历哪几个时刻？

━━━━━━━━━━━━━━━━━━━━━━━━━━━
叙事拆解的基本原则
━━━━━━━━━━━━━━━━━━━━━━━━━━━

【一个事件通常包含2-5条路径】
路径数量由事件的复杂度和涉及角色数决定，
不是所有事件都需要5条路径，简单的事件2-3条就够。

【每条路径是一个叙事时刻，不是一个行动步骤】
路径描述的是"读者此刻看到了什么"，而不是"角色做了什么"。
例如：
  不是 → "沈砚去拜访赵秉忠"
  而是 → "沈砚在赵府书房中第一次感受到了对方的真实分量"

【路径的叙事功能可以是多样的】
- 建立信息（让读者知道某件事）
- 制造悬念（让读者感到有什么不对但说不清楚）
- 释放张力（让之前积累的压力得到出口）
- 人物呈现（让某个角色在压力下显现出真实的性格底色）
- 埋下伏笔（让某个细节在读者心中留下印记，等待未来引爆）
- 喘息（让读者在高压后得到呼吸，同时悄悄种下新的不安）

【全局叙事节奏的约束】
读取已完成路径的节奏分布。
如果最近3-4章都是高张力叙事，本事件的路径中应该有喘息时刻。
如果最近几章一直在铺垫，本事件应该有释放张力的路径。
避免单调，保持故事的呼吸感。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
伏笔的自然嵌入
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取 karmic_ledger 中已埋下但尚未引爆的伏笔，
判断本事件的哪条路径可以自然地展示某条伏笔的迹象，
或者引爆某条已经成熟的伏笔。

⚠️ 伏笔的嵌入必须是自然的——
它应该出现在路径本身逻辑允许的位置，而不是被硬塞进去。
如果没有合适的位置，就不嵌入，等待下一个事件。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "event_id": "对应 event_chain_gen 的 event_id",
  "event_name": "对应事件名称",
  "total_paths": "本事件拆解的路径总数（2-5）",

  "paths": [
    {
      "path_id": "路径唯一标识（如 arc1_ev003_p1）",
      "path_name": "这条路径的叙事时刻描述
                   （读者此刻看到了什么，如：
                   '沈砚在赵府书房中第一次感受到对方的真实分量'）",
      "narrative_function": "这条路径的叙事功能
                            （建立信息/制造悬念/释放张力/
                            人物呈现/埋下伏笔/喘息）",
      "pov_character": "本路径的视角角色",
      "key_characters_present": ["本路径中出现的关键角色"],
      "foreshadow_embedded": {
        "seed_id": "如果本路径嵌入了某条伏笔，填写 seed_id；否则填 null",
        "embed_type": "展示迹象 / 引爆 / null"
      },
      "path_to_next": "这条路径结束时，留下什么开口引向下一条路径"
    }
  ],

  "rhythm_note": "本事件整体的叙事节奏说明
                 （如：前两条路径建立压力，第三条释放，第四条埋下新不安）",

  "global_rhythm_adjustment": "基于全局节奏分布，本事件做了什么节奏调整"
}
```

---

### PROMPT 8（修订版）· `expand1` — 章节规划

**节点职责**：针对 path_gen 给出的单条路径，
结合当前真实档案状态，规划这一章怎么写。

**定位**：以单条路径为主，以全局档案状态为辅。
path_gen 告诉你这条路径的叙事时刻和功能，
expand1 告诉你在当前真实状态下，这个叙事时刻应该怎么落地。

**上游输入**：
- path_gen 中本条路径的完整定义
- 当前真实档案状态（上一章 bible_update 回写后）：
  world_archive + protagonist_archive + karmic_ledger
- 上一章的 causal_output

```
你是一位章节规划师。
你拿到了这条路径的叙事定义：它的叙事时刻是什么，功能是什么，
视角是谁，留下什么开口。

你的任务是在当前真实的世界状态下，规划这一章如何落地。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
第一步：状态确认
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取当前真实档案状态：
- 视角角色的 emotional_capacity 当前剩余量
- 视角角色的 maturity_level 当前档位
- 相关角色的 innate_traits 和 mental_core 当前状态
- karmic_ledger 中与本路径相关的伏笔状态

⚠️ 档案状态是真实的，不是规划时预想的。
一个精神阈值已透支到20的角色，他在这章的表现
必须反映这个透支状态，而不是按路径定义中
"他应该表现得稳定"来写。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
第二步：确认叙事功能与章节形态
━━━━━━━━━━━━━━━━━━━━━━━━━━━

path_gen 给出了本路径的叙事功能。
结合当前真实档案状态，确认本章的自然形态：

- 如果功能是"释放张力"，当前角色状态支撑这个释放吗？
  如果支撑，确认；如果不支撑（如角色还没有足够的积累），
  说明偏差，本章形态调整为"继续积累"。

- 如果功能是"喘息"，当前世界状态允许喘息吗？
  如果某个外部压力突然升级（来自档案的 current_status 变化），
  本章可能无法完全喘息，调整为"短暂喘息后被打断"。

⚠️ path_gen 的路径定义是基于事件生成时的档案状态制定的，
而 expand1 是在若干章之后执行的，档案状态可能已经发生变化。
expand1 的职责之一就是检查并消化这个差异。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
第三步：确认驱动力和因果咬合
━━━━━━━━━━━━━━━━━━━━━━━━━━━

谁在驱动这一章？
不是"剧情需要"，而是"某个角色基于他的性格和当前处境，
在这条路径的叙事时刻里，不得不做某件事"。

本章的因来自哪里（上一章的 causal_output）？
本章的果将指向哪里（本路径定义中的 path_to_next）？

━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出规范
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "path_id": "对应 path_gen 的 path_id",
  "chapter_tone": "本章的自然基调（与 narrative_function 对照后确认或调整）",
  "function_confirmed": "path_gen 的叙事功能是否在当前状态下成立
                        （成立/调整，如调整说明原因和调整后的功能）",

  "chapter_driver": "谁在驱动这一章，意志是什么",
  "key_state_factors": [
    "影响本章落地方式的关键档案状态
    （如：主角 emotional_capacity 仅剩20，导致本章的隐忍有崩溃风险）"
  ],

  "causal_input": "本章的因（来自上一章 causal_output）",
  "causal_output_direction": "本章的果将指向哪里",
  "hidden_seed": "如果本章是喘息功能，悄悄埋下的种子（其他功能填null）"
}
```

---

### PROMPT 9（修订版）· `expand2` — 场景拆解

**节点职责**：把 expand1 规划好的章节方向，
拆解为具体的场景序列。

**上游输入**：
- expand1 的完整输出
- 相关角色当前档案状态（innate_traits + mental_core + emotional_capacity）
- path_gen 中本路径的 key_characters_present 和 foreshadow_embedded

```
你需要把 expand1 规划好的章节方向，拆解为具体的场景序列。

你没有固定的场景结构需要遵守。
叙事功能是"释放张力"的章节和功能是"喘息"的章节，
场景形态可以完全不同——这正是小说呼吸感的来源。

在拆解场景时，从角色的当前档案状态出发：
- 他的 emotional_capacity 现在还有多少？
- 他的 maturity_level 当前处于什么阶段？
- 他的 independent_agenda 在这个场景中是否被推进或受阻？

这些信息决定了角色在场景中的真实反应，
而不是剧情需要他做出什么反应。

你唯一需要保证的是：

每一个场景必须有一个"人在驱动它"——
某个角色基于他的性格和处境，在这个场景里做了一个真实的选择。
这个选择对他而言有代价，且代价与他当前最在意的东西直接相关。

如果某个场景结束后，没有任何角色做出任何真实的选择，
这个场景是无效场景。

【输出规范】
{
  "path_id": "对应 path_id",
  "scene_count": "本章预计场景数量",
  "scenes": [
    {
      "scene_id": "场景编号",
      "pov_character": "视角角色",
      "scene_nature": "场景的自然形态
                      （对抗/试探/喘息/伏笔呈现/震撼/转折等，不限于此）",
      "character_decision": "谁在这个场景里做了什么真实的选择，代价是什么",
      "relevant_mental_state": "视角角色当前的 emotional_capacity
                               和 maturity_level 状态对本场景的影响",
      "foreshadow_action": "如果本场景对应 path_gen 中的 foreshadow_embedded，
                           说明伏笔如何在场景中自然呈现（否则填null）",
      "scene_exit": "场景结束时留下的开口"
    }
  ]
}
```

---

### PROMPT 13（修订版）· `bible_update` — 档案回写与循环控制

**节点职责**：每章写作完成后，回写所有档案，
更新路径完成状态，判断内循环是否完成，
判断是否触发外循环下一轮或卷收束。

```
你是这部小说世界的"全知档案员"。
你的职责除了更新档案，还要控制两个循环的推进节奏。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
原有职责（保持不变）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

角色状态回写：
- 哪个角色的 emotional_capacity 发生了消耗？当前剩余量？
- 哪个角色的 maturity_level 发生了跃迁？触发事件？哪个维度提升？
- 哪个角色的 innate_traits 在特定压力下表现出了什么具体面向？

势力状态回写：
- 哪股势力的 current_status 因本章事件发生了变化？
- 哪股势力的 relationships 产生了微妙偏移？

karmic_ledger 更新：
- 本章埋下了哪个伏笔？（seed_id + 描述 + holder + estimated_payoff）
- 本章引爆了哪个前置伏笔？（与 estimated_payoff 的偏差？）

user_anchors 完整性校验：
- 本章内容是否触碰了 user_anchors 中的任何条目？

━━━━━━━━━━━━━━━━━━━━━━━━━━━
新增职责：路径完成追踪（内循环控制）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

更新当前事件的路径完成状态：
- 标记本章对应的 path_id 为已完成
- 检查当前事件的所有 paths 是否全部已完成

【内循环判断】
如果当前事件还有未完成的路径：
→ termination_action: "continue_inner_loop"
→ 下一条路径的 path_id 是什么

如果当前事件所有路径已完成：
→ 触发外循环判断

━━━━━━━━━━━━━━━━━━━━━━━━━━━
新增职责：锚点追踪与卷收束（外循环控制）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

在当前事件所有路径完成后，检查锚点进度：

对照 arc_anchors 中每个未完成锚点的 completion_signal，
判断当前事件是否触达了某个锚点。

【外循环判断】

条件检查：
  - anchor_all_complete：所有 arc_anchors 是否全部完成？
  - chapter_count_sufficient：已完成章节数 >= 50？

判断结果：
  - 两个条件都不满足 → event_chain_gen（继续生成下一个事件）
  - 只缺锚点未完成 → event_chain_gen（继续，优先引导向未完成锚点）
  - 只缺章节数不足 → event_chain_gen（继续生成事件，进入尾声阶段）
  - 两个条件都满足 → 触发卷收束

━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出规范（在原有规范基础上新增）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  // 原有所有字段保持不变

  "path_progress": {
    "current_event_id": "当前事件 event_id",
    "completed_path_id": "本章对应的 path_id",
    "remaining_paths": ["当前事件还未完成的 path_id 列表"],
    "inner_loop_complete": true/false
  },

  "anchor_progress": {
    "completed_anchors": ["已完成的 anchor_id 列表"],
    "newly_completed": "本次外循环判断中新完成的 anchor_id（可为null）",
    "pending_anchors": ["尚未完成的 anchor_id 列表"],
    "completion_note": "触发锚点 completion_signal 的具体内容描述"
  },

  "loop_control": {
    "inner_loop_action": "continue_inner_loop / trigger_outer_loop",
    "next_path_id": "如继续内循环，下一条路径的 path_id",
    "outer_loop_action": "continue_event_loop / trigger_arc_end / null（内循环未完成时）",
    "arc_termination_reason": "如触发卷收束，说明原因"
  },

  "arc_completion_summary": {
    // 仅在 outer_loop_action = trigger_arc_end 时输出
    "arc_id": "完成的卷号",
    "actual_chapters": "实际完成章节数",
    "actual_events": "实际完成事件数",
    "protagonist_state_at_end": {
      "tier": "最终圈层",
      "maturity_score": "最终成熟度档位",
      "emotional_capacity": "最终精神阈值"
    },
    "open_seeds_for_next_arc": ["未引爆的伏笔 seed_id，传递给下一卷"],
    "next_arc_entry_pressure": "主角进入下一卷时的初始压力描述"
  }
}
```

---

## 四、全局视角的信息结构

全局视角需要在两个层级提供：

### event_chain_gen 需要的全局视角

```json
"completed_events_summary": [
  {
    "event_id": "arc1_ev001",
    "event_name": "事件名称",
    "conflict_type": "核心冲突类型",
    "primary_resource_used": "主要使用的四维资源类型",
    "anchor_touched": "触达的锚点 anchor_id（null 表示未触达）"
  }
]
```

只需要足够判断"是否重复"的最小信息量，不需要完整事件内容。

### path_gen 需要的全局视角

```json
"recent_rhythm": {
  "last_n_paths": [
    {
      "path_id": "arc1_ev001_p1",
      "narrative_function": "建立信息/制造悬念/释放张力/等"
    }
  ],
  "rhythm_note": "最近N章的节奏分布描述（如：连续3章高张力，需要喘息）"
}
```

---

## 五、档案数据流向图（v4.3 终版）

```
idea_forge
  └─ user_anchors ──────────────────────────→ 所有后续节点

world_build
  └─ world_archive ─────────────────────────→ protagonist_card
                   ─────────────────────────→ iceberg_deduction
                   ─────────────────────────→ story_arc_plan
                   ─────────────────────────→ event_chain_gen（当前真实状态）
                   ─────────────────────────→ path_gen（当前真实状态）
                   ─────────────────────────→ expand1（当前真实状态）
                   ←──────────────────────── bible_update（每章回写）

protagonist_card
  └─ protagonist_archive ───────────────────→ iceberg_deduction
                         ───────────────────→ story_arc_plan
                         ───────────────────→ event_chain_gen（当前真实状态）
                         ───────────────────→ path_gen（当前真实状态）
                         ───────────────────→ expand1/expand2（当前真实状态）
                         ←───────────────── bible_update（每章回写）

iceberg_deduction
  └─ opening_collision + iceberg_structure →→ genesis_ignition
                                          →→ story_arc_plan

story_arc_plan
  └─ arc_anchors ───────────────────────────→ event_chain_gen（锚点导向）
                 ───────────────────────────→ bible_update（锚点校验基准）

event_chain_gen
  └─ 单事件输出 ────────────────────────────→ path_gen
               ────────────────────────────→ completed_events_summary（追加）

path_gen
  └─ 路径列表 ──────────────────────────────→ expand1（当前路径定义）
             ──────────────────────────────→ recent_rhythm（追加）

karmic_ledger（由 bible_update 持续维护）
  └─ 全量伏笔状态 ──────────────────────────→ event_chain_gen
                  ─────────────────────────→ path_gen（伏笔嵌入参考）
                  ─────────────────────────→ expand1
                  ←─────────────────────── bible_update（每章回写）

anchor_progress（由 bible_update 持续维护）
  └─ 锚点完成状态 ──────────────────────────→ event_chain_gen（锚点导向）
                  ─────────────────────────→ bible_update（外循环判断依据）

path_progress（由 bible_update 持续维护）
  └─ 路径完成状态 ──────────────────────────→ bible_update（内循环判断依据）
                  ─────────────────────────→ expand1（当前路径定位）
```

---

## 六、设计决策记录

### 6.1 为什么 path_gen 是叙事拆解而不是推导引擎？

推导引擎回答"角色在处境下会怎么行动"，这是 expand1/2 层的问题。
path_gen 回答的是"这件事需要让读者经历哪几个时刻"，
这是编剧层面的叙事感知问题，与角色行动逻辑无关。

将推导引擎放在 path_gen 层，会导致在整章的行动细节还没有确认的情况下，
就预测角色的具体行为——这个预测到了 expand1/2 时会与真实档案状态冲突。

### 6.2 expand1 为什么不再运行三步命运编织引擎？

三步命运编织引擎回答"这件事为什么在此刻发生"，这已经在 event_chain_gen 完成了。
expand1 面对的是一条已经定义好叙事时刻的路径，它不需要再问"为什么发生"，
而是要问"在当前真实状态下，这个叙事时刻如何落地"。

两个不同的问题，不需要同一个工具。

### 6.3 全局视角为什么只提供摘要而不是完整内容？

完整内容会超过上下文窗口限制，而且大部分历史内容对当前节点没有价值。
摘要只提供"足够判断是否重复/节奏是否均衡"的最小信息量，
让模型把注意力集中在当下真实状态，而不是在历史信息中迷失。

### 6.4 卷的章节数为什么不预先确定？

预先确定章节数会强迫写作节点在特定章数填满或截断，
这与"让故事从人性内部生长"的原则矛盾。
事件循环 + 锚点追踪的组合，让卷的结束成为一个自然收敛的结果：
当所有锚点完成且章节数达到最低阈值时，这一卷的故事自然有了终点。

---

## 七、与主文档的对照变更说明

| 节点 | 变更类型 | 核心变更内容 |
|------|---------|------------|
| story_arc_plan | 扩展 | 现有输出不变，新增 arc_anchors 字段 |
| event_chain_gen | 重构 | 每次调用只生成一个事件；三步命运编织引擎仍在此层；新增全局视角输入；新增 anchor_check 和 global_context_check 输出字段 |
| path_gen | 重构 | 职责明确为叙事拆解（编剧视角）；不再运行推导引擎；新增全局叙事节奏输入；输出为叙事时刻列表而非章节类型预测 |
| expand1 | 重构 | 不再运行三步命运编织引擎；以单条路径为主，以全局档案状态为辅；核心职责变为"确认路径定义在当前真实状态下的落地方式" |
| expand2 | 微调 | 输入来源从 expand1 的 3W1H 推导改为路径叙事时刻 + 档案状态；场景结构约束保持不变 |
| bible_update | 扩展 | 新增路径完成追踪（内循环控制）；新增锚点追踪与卷收束判断（外循环控制）；新增 arc_completion_summary 字段 |

---

> **文档版本**：DeepNovel v4.3 终版
> **核心变更**：确立事件驱动的分层叙事架构；
> event_chain_gen 单事件生成（三步命运编织引擎）；
> path_gen 叙事拆解（编剧视角，每条路径 = 一章）；
> expand1 路径落地确认（档案状态驱动）；
> 两个嵌套循环（事件循环 + 章节循环）由 bible_update 统一控制。
> **核心原则**：引擎的抽象层级必须与节点的处理对象匹配。