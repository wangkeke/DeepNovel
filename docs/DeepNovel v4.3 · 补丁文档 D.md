# DeepNovel v4.3 · 补丁文档 D
## Active Quest Stack — 动机前置注入与任务生命周期管理

> **文档定位**：本文档是对 v4.3 终版架构文档的第四份补丁，
> 新增 active_quest_stack 数据结构及其在各节点中的生成、注入、管理规范。
> 合并时以本文档为准，在 protagonist_archive、iceberg_deduction、
> expand1、write、bible_update、event_chain_gen 节点中新增对应逻辑。

---

## 一、问题根源

### "后视镜"替代不了"方向盘"

补丁B中的 `chapter_path_chain`（本章叙事路径链）是一个**事后提取**机制——
等正文写完后，提取"主角刚才干了什么"。

这解决不了动机漂移问题。原因：

```
第5章写作时：
  大模型被场景吸引（精彩的打斗/华丽的宝物），忘记写老吴。
  正文产出：主角打怪夺宝，没有提及老吴。

第5章提取时：
  chapter_path_chain 忠实记录：行动1→打怪→行动2→夺宝成功
  老吴没出现在正文，自然不会出现在提取结果里。

第6章写作时：
  系统拿着"夺宝成功"继续推导：下一步卖钱换飞剑？
  "救老吴买清蕴丹"这条核心动机，在第5章已被彻底洗掉。
  老吴惨死，读者落泪。
```

**根本结论**：
动作可以被事后提取，动机必须被事前注入。
主角的执念必须像风筝线，一头攥在系统手里，
无论主角飞进多么宏大的副本，只要这根线一拽，
主角立刻认清自己为什么在拼命。

### 单一静态字符串也不够

如果只是把"救老吴买清蕴丹"作为静态文本死锁在档案里：

```
问题一：任务完成后仍在注入
  老吴在第8章被救了，第12章系统仍注入"三天内买清蕴丹救老吴"
  → 新的漂移：主角已完成的任务继续驱动行为

问题二：多任务并行时没有优先级
  主角同时有"救老吴"和"找钥匙碎片"两个目标
  静态字符串无法表达哪个更紧迫

问题三：任务失败没有自动演化
  老吴死亡时，"救老吴"任务没有机制转化为"为老吴复仇"
  → 叙事断裂，动机消失
```

---

## 二、解决方案：Active Quest Stack

在 `protagonist_archive` 中新增动态任务栈，
替代原有的静态动机描述。

### 数据结构

```json
"active_quest_stack": [
  {
    "quest_id": "AQ_001",
    "quest_name": "救治老吴",
    "quest_origin": "opening_collision（老吴中毒，主角被逼入悬赏）",
    "urgency_level": "critical",
    "deadline_note": "老吴的蚀骨阴毒约三天内致命",
    "current_sub_goal": "进蚀骨荒原获取灵石，购买清蕴丹",
    "layer": "immediate",
    "completion_condition": "老吴服下清蕴丹且脱离生命危险",
    "failure_condition": "老吴死亡",
    "evolution_on_completion": null,
    "evolution_on_failure": {
      "new_quest_name": "为老吴复仇",
      "new_urgency": "high",
      "new_layer": "arc_level",
      "trigger_note": "老吴死亡直接成为下一事件的驱动力"
    },
    "status": "active",
    "planted_chapter": "chapter_1",
    "emotional_weight": "老吴是主角的恩人，救命之恩未报。
                        失去老吴意味着主角在这个世界唯一的情感锚点消失。"
  },
  {
    "quest_id": "AQ_002",
    "quest_name": "验证词条路线可行性",
    "quest_origin": "词条首次出现（钥匙碎片词条在悬赏图旁浮现）",
    "urgency_level": "high",
    "deadline_note": null,
    "current_sub_goal": "进入蚀骨荒原，找到至少一块钥匙碎片或相关线索",
    "layer": "short_term",
    "completion_condition": "成功获取碎片，或确认词条对碎片位置的指示准确",
    "failure_condition": "进入荒原后发现词条信息完全错误或被人为干扰",
    "evolution_on_completion": {
      "new_quest_name": "深入荒芜道蕴传承",
      "trigger_note": "验证成功后，目标升级为获取完整传承"
    },
    "evolution_on_failure": null,
    "status": "active",
    "planted_chapter": "chapter_1",
    "emotional_weight": "这是主角第一次看到自己的词条能力真正指向了某种更大的东西。
                        验证成功意味着他不再只是底层散修，而是掌握了别人看不见的信息差。"
  }
]
```

### 四个任务层级

```
immediate    → 时辰/天级别，极度紧迫，直接影响生死（救老吴）
short_term   → 章节/事件级别，阶段性目标（找钥匙碎片）
arc_level    → 卷级别，整卷的叙事目标（筑基突破）
core_drive   → 终极层，角色底色的永恒驱动力（掌握定价权）
```

`core_drive` 层的任务永远不会被标记为 completed，
它是主角性格底色的一部分，贯穿全书。

### urgency_level 枚举

```
critical  → 不立即处理会有人死亡/主角被摧毁
high      → 不处理会显著恶化局势
medium    → 需要推进但有缓冲空间
low       → 长线目标，不影响当前行动
```

---

## 三、任务的生成时机

任务不是预先规划的，而是从故事的真实逻辑中自然涌现。
以下是各类任务的标准生成时机：

### immediate / short_term 层任务

由以下节点生成并推入任务栈：

**1. iceberg_deduction 阶段（卷初始化）**

开篇碰撞（opening_collision）推导完成后，
从 Protagonist Tick 的输出中提取初始任务：

```
Protagonist Tick 输出的"主角此刻最在意的东西"
→ 直接成为第一个 immediate 层任务的 quest_name 和 current_sub_goal

Fated Collision 中"主角被逼进交汇点的原因"
→ 成为该任务的 quest_origin

初始任务的 deadline_note 和 emotional_weight
由 iceberg_deduction 根据 protagonist_archive 推导填写
```

**2. bible_update 阶段（章节完成后）**

bible_update 在完成档案回写后，检查是否需要推入新任务：

触发条件（满足任一即推入新任务）：
- 本章出现了新的角色危机（新的人处于危险中）
- 本章建立了新的承诺或债务关系（主角欠了谁/被谁欠了）
- 本章世界线事件改变了主角的处境（新势力介入/新资源出现）
- 本章某个已有词条的动态关联发生了关键变化

推入时机：在 anchor_progress 更新之后，在路由到下一章之前。

**3. event_chain_gen 阶段（Fated Collision 后）**

当三步命运编织引擎完成碰撞设计后，
如果本事件创造了新的紧迫需求（Protagonist Tick 发现了新的"最在意的东西"），
且当前任务栈中没有对应任务，推入新任务。

### arc_level 层任务

由 `story_arc_plan` 在生成 arc_anchors 的同时推入：

```
arc_level 任务与 arc_anchors 一一对应：
  每个锚点对应主角在该卷需要完成的叙事目标
  锚点的 arrival_condition 对应任务的 completion_condition
  锚点的 milestone_type 对应任务的大致方向

arc_level 任务不直接注入 expand1 的最高紧迫层，
而是作为 short_term 任务的上层目标上下文出现。
```

### core_drive 层任务

由 `protagonist_card` 生成时一次性写入：
从 `core_desire` 字段直接转化，永远不更新，永远不完成。

---

## 四、文学滤镜铁律（最重要的工程约束）

### 问题

引入"任务栈"这个概念后，模型在 write 节点生成正文时，
极有可能被术语污染，写出以下内容：

```
❌ 危险样本一（直接暴露任务系统）：
  "林默心想，我现在的紧迫任务是救老吴。"

❌ 危险样本二（游戏化旁白）：
  "林默的复仇任务进度更新了，当前完成度：37%。"

❌ 危险样本三（系统流语气）：
  "他明确了当前目标：在三天内购买清蕴丹。"
```

这些写法会让读者瞬间出戏，将文学叙事降格为游戏攻略。

### 文学滤镜铁律（必须注入 expand1 和 write 提示词）

```
【文学转化铁律——动机注入专用】

以下"当前动机锁定"内容，仅供你（AI）理解角色此刻的
内心焦灼、行动优先级和情感底色。

【绝对禁止】在正文中出现以下内容：
  × "任务"、"目标"、"完成条件"、"紧迫程度"等系统化词汇
  × 任何形式的进度描述（"完成了X%"、"还差X步"）
  × 角色在内心独白中直接陈述自己的目标清单
  × 旁白对角色目标的系统化解释

【必须做到的文学转化】
将动机转化为以下具体的文学呈现形式：

角色的生理反应：
  "救老吴"的紧迫感 →
  呼吸节奏的变化、手心的汗、无法控制的视线反复扫向沙漏

角色的潜意识动作：
  时间压力的焦灼 →
  走路时无意识地加快步频、说话时语气比平时更短促

角色内心的画面闪回：
  情感重量 →
  在高压时刻，某个人的脸突然闯入脑海，带来力量或带来软弱

角色的决策偏向：
  优先级排序 →
  面对两个选择时，某个选项被下意识放弃，原因读者能感受到但角色没有说出来

正确示范（救老吴的紧迫感在打斗场景中的转化）：
  "蝙蝠的毒牙擦过他的脖颈，眼前一阵发黑。
   但他猛地咬碎舌尖，脑海里划过老吴那张发青的脸。
   '还剩两个时辰……'
   他犹如疯魔一般，迎着毒雾冲了上去。"

这段文字从未出现"任务"、"目标"这些词，
但读者清楚地感受到了主角在拼命的原因。
这才是正确的动机转化方式。
```

---

## 五、各节点的读写规范

### expand1（任务注入点）

在原有状态确认步骤之前，新增任务栈读取：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
第零步：动机锁定（在所有推导之前执行）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取 protagonist_archive.active_quest_stack 中
所有 status = active 的任务，按以下规则注入：

注入格式：
【当前动机锁定（按紧迫度排序）】

⚠️ [urgency_level = critical 的任务]
  任务名：{quest_name}
  当前子目标：{current_sub_goal}
  情感重量：{emotional_weight}
  截止压力：{deadline_note}

→ [urgency_level = high 的任务]
  任务名：{quest_name}
  当前子目标：{current_sub_goal}

（arc_level 和 core_drive 层任务以上层背景的形式注入，不占主要位置）

[文学滤镜铁律]（见上方完整文本，此处必须附上）

━━━━━━━━━━━━━━━━━━━━━━━━━━━
注入规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━

如果本章的叙事功能是"喘息节点"：
  immediate 层任务仍然注入，但以更低的焦虑浓度呈现——
  不是当前时刻的紧迫行动，而是背景中的持续压力。
  说明："本章是喘息时刻，动机作为角色内心的底色存在，
        不驱动当前主要行动，但读者应能感受到它还在那里。"

如果本章的叙事功能是"引爆节点"：
  immediate 层任务以最高浓度注入，
  本章的引爆应该直接服务于或威胁到该任务的完成。
```

expand1 输出规范新增 `quest_context` 字段：

```json
"quest_context": {
  "injected_quests": ["注入的 quest_id 列表"],
  "primary_driver": "本章主要被哪个任务驱动",
  "emotional_undercurrent": "本章中，动机如何以文学方式渗透到叙事底层"
}
```

### write（文学滤镜执行点）

在原有六项检查清单之前，新增任务滤镜确认：

```
在动笔前，先读取 expand1 传递的 quest_context。
然后默念这道铁律：

"主角为什么在这里拼命？"（内心知道答案）
"我会在正文中直接说出这个答案吗？"（绝对不会）
"我会让读者通过主角的身体和行动感受到这个答案吗？"（是的）

确认完毕，开始写作。
```

### bible_update（任务生命周期管理点）

在原有档案回写完成后，新增任务生命周期检查：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
任务生命周期检查
━━━━━━━━━━━━━━━━━━━━━━━━━━━

对 active_quest_stack 中每个 status = active 的任务执行检查：

检查一：completion_condition 是否在本章满足？

判断方式：
  对照本章正文内容和档案更新结果，
  判断 completion_condition 描述的状态是否已经发生。

如果满足：
  → status 改为 completed
  → completed_chapter 记录为当前章节号
  → 如果有 evolution_on_completion，将演化任务推入任务栈
    （推入时 status = active，planted_chapter = 当前章节号）
  → 在 karmic_ledger 中记录任务完成事件（作为一条已引爆的伏笔）

检查二：failure_condition 是否在本章满足？

如果满足：
  → status 改为 failed
  → failed_chapter 记录为当前章节号
  → 如果有 evolution_on_failure，将演化任务推入任务栈
  → evolution_on_failure 的演化任务通常紧迫度更高
    （老吴死亡→复仇任务的紧迫度从 high 可能跃升为 critical）
  → 演化任务自动成为下一个事件的驱动力候选
    （在 event_chain_gen 下一次运行时，
     Protagonist Tick 将直接读取这个新任务）

检查三：是否需要推入新任务？

满足以下任一条件时推入：
  a) 本章出现了新的角色危机（新的人处于危险中）
  b) 本章建立了新的承诺或债务关系
  c) 本章世界线事件显著改变了主角处境
  d) 本章某个词条的动态关联发生了关键变化
     且当前任务栈中没有对应任务

推入时的 urgency_level 判断：
  涉及生死 → critical
  涉及重要利益或关键机遇 → high
  涉及长期布局 → medium / low

检查四：任务子目标更新

如果任务仍在进行中，但本章推进了子目标：
  更新 current_sub_goal 为下一阶段的具体行动方向
  （例："获取灵石"完成后，更新为"前往坊市购买清蕴丹"）
```

bible_update 输出规范新增 `quest_stack_updates` 字段：

```json
"quest_stack_updates": {
  "completed_quests": ["本章完成的 quest_id 列表"],
  "failed_quests": ["本章失败的 quest_id 列表"],
  "evolved_quests": [
    {
      "from_quest_id": "原任务 quest_id",
      "to_quest_id": "演化后的新任务 quest_id",
      "evolution_type": "completion / failure"
    }
  ],
  "new_quests_added": ["本章新推入的 quest_id 列表"],
  "sub_goal_updates": [
    {
      "quest_id": "更新的任务 quest_id",
      "old_sub_goal": "原子目标",
      "new_sub_goal": "更新后的子目标"
    }
  ]
}
```

### event_chain_gen（任务与事件的关联）

在 Protagonist Tick 步骤中，直接从任务栈读取：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
第二步：Protagonist Tick（修订版）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取 active_quest_stack 中 urgency_level = critical
或 high 的 active 任务。

这些任务的 current_sub_goal 直接构成主角"此刻最深的需求"，
不需要重新从 core_desire 推导——任务栈已经是推导的结果。

输出：
{
  "deepest_need": "来自 immediate 层任务的 current_sub_goal",
  "emotional_weight": "来自任务的 emotional_weight 字段",
  "core_principle": "从 innate_traits + maturity_level 推导（保持不变）",
  "quest_driven": true,
  "driving_quest_id": "AQ_001"
}

如果任务栈为空（所有任务都已完成或失败）：
  说明主角处于"悬空状态"——这本身就是一个需要填充的叙事空间。
  回退到从 core_desire + 当前 world_position 推导主角需求。
  同时触发 human_review：提示"主角当前无活跃任务，请检查是否需要推入新任务"。
```

---

## 六、任务栈与现有体系的关系

```
arc_anchors（卷级战略锚点）
  ↔ arc_level 层任务
  arc_anchors 决定故事走向（世界层面）
  arc_level 任务决定主角的叙事目标（人物层面）
  二者从不同维度约束故事不跑偏

karmic_ledger（伏笔账本）
  ← 任务完成/失败时，在 karmic_ledger 中记录
  任务和伏笔是不同的东西：
  任务是主角的动机驱动，伏笔是世界的因果线索
  但任务的演化（老吴死亡→复仇）本身可以成为一条伏笔的引爆

world_lexicon（世界词条库）
  ← 某些词条的动态变化可以触发新任务推入
  例：清蕴丹被反派截获（词条 update_dynamic）
  → 触发新任务："重新获取清蕴丹"

active_quest_stack（任务栈）
  ↑ 任务来源：
    iceberg_deduction（初始任务）
    bible_update（新涌现任务）
    event_chain_gen（Fated Collision 后的新需求）
    story_arc_plan（arc_level 任务）
    protagonist_card（core_drive 任务）

  ↓ 任务消费：
    expand1（最高紧迫层注入写作提示词）
    event_chain_gen Protagonist Tick（直接读取当前需求）
```

---

## 七、设计决策记录

### 7.1 为什么用任务栈而不是单一字段？

单一静态字段（如 `current_motivation: "救老吴"`）有三个致命缺陷：
任务完成后无法退出、多任务无法排优先级、任务失败无法自动演化。

任务栈解决了所有三个问题，同时通过 `urgency_level` 自然排序，
通过 `evolution_on_completion/failure` 实现动机的有机演化。

### 7.2 为什么文学滤镜必须是"铁律"而不是"建议"？

"任务"这个词本身就是一个游戏化概念。
大模型在训练数据中见过大量将任务系统直接写进正文的 LitRPG 作品，
如果不明确禁止，它会自然地向这个方向漂移。

文学滤镜的本质是：让 AI 知道这些结构化信息是**私密的导演指令**，
不是需要在正文中表演出来的台词。

### 7.3 core_drive 层任务为什么永远不完成？

角色的底色驱动（掌握定价权、逃脱棋子命运）不是一个可以"完成"的任务，
而是驱动角色做出所有选择的底层引擎。

如果它能被完成，主角就不再有驱动力——
这通常意味着故事结束，或者进入一个需要新驱动力的新阶段。
在 DeepNovel 的体系中，这个状态由 arc_anchors 的圈层跃迁来标记，
而不是由 core_drive 任务的 completion 来处理。

### 7.4 任务推入的时机为什么分散在多个节点？

任务不是被设计出来的，而是从故事的真实逻辑中自然涌现。
分散在 iceberg_deduction（初始）、bible_update（章节完成后）、
event_chain_gen（碰撞后）的推入时机，
确保任务的产生总是有故事逻辑的支撑，
而不是被某个节点统一"规划"出来的。

---

## 八、与 v4.3 终版文档的对照变更说明

| 节点 | 变更类型 | 核心变更内容 |
|------|---------|------------|
| protagonist_archive | 扩展 | 新增 active_quest_stack 字段，替代原有静态动机描述 |
| iceberg_deduction | 扩展 | 开篇碰撞推导完成后，自动生成初始任务推入任务栈 |
| story_arc_plan | 扩展 | 生成 arc_anchors 的同时，推入对应的 arc_level 层任务 |
| protagonist_card | 扩展 | core_desire 字段直接转化为 core_drive 层任务，永远不完成 |
| expand1 | 扩展 | 新增第零步（动机锁定），读取任务栈并以文学滤镜格式注入 |
| write | 扩展 | 新增动笔前文学滤镜确认步骤；输出规范不变（只输出正文） |
| bible_update | 扩展 | 新增任务生命周期检查（完成/失败/演化/子目标更新/新任务推入） |
| event_chain_gen | 修订 | Protagonist Tick 优先读取任务栈，而非重新推导 |

---

> **文档版本**：DeepNovel v4.3 补丁 D
> **补丁内容**：Active Quest Stack — 动机前置注入与任务生命周期管理
> **核心原则**：
>   动机必须前置注入，绝不依赖事后提取；
>   任务有生命周期（生成/推进/完成/失败/演化）；
>   文学滤镜铁律确保结构化动机不污染正文的文学性；
>   任务栈与 arc_anchors 从人物/世界两个维度双重约束故事不跑偏。