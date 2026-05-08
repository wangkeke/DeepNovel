# DeepNovel v4.3 · 补丁文档 F
## Scene Snapshot × Write 边界约束 × consistency_node 重构

> **文档定位**：本文档是对 v4.3 终版架构文档的第六份补丁，
> 针对测试中发现的三类核心 Bug 提供系统性修复：
> 1. 空间物理断层（主角位置在事件切换时瞬移）
> 2. 路径边界坍塌（write 节点越权写完后续路径后留下缺口）
> 3. 资产幻觉（下一事件凭空引入未在场景中出现的实体）
> 同时对 consistency_node 进行重构，使其检验维度与当前系统对齐。

---

## 一、问题诊断

### Bug 1：空间物理断层（Spatial Discontinuity）

```
章节结束时的物理事实：
  顾尘在洞口内侧乱石堆后蹲伏
  敌人走进了洞内深处
  空间格局：敌在深处，顾尘在洞口

下一事件生成的幻觉：
  "斥候深入矿洞，顾尘退入更深处"
  → 物理上完全矛盾

根本原因：
  narrative_extract 没有将精确的物理坐标写入全局 State
  或写了但 event_chain_gen 的提示词没有读取
  引擎按套路惯性生成了"往深处逃"的剧情
```

### Bug 2：路径边界坍塌（Path Boundary Collapse）

```
规划：ev_1_001 拆成4条路径，Path 1 只写"三个呼吸的抉择"

实际：write 一次性输出2966字，
      不仅写完了 Path 1，还包揽了 Path 2/3，
      推进到整个事件的结尾悬念

根本原因：
  write 看到了完整的事件路径链上下文
  没有刹车指令约束，把"一条路径"当"一整章"写
  后续路径变成空白缺口或被跳过
```

### Bug 3：资产幻觉（Asset Hallucination）

```
章节确立的场景资产：
  暗杀队4人，灰袍修士持铜盘追踪法器

下一事件凭空引入：
  "带着追踪猎犬"
  → 猎犬在前一章完全不存在

根本原因：
  event_chain_gen 为了制造危机感，
  套路化地引入了未经确认的实体
  没有任何机制约束"只能使用已确认的场景资产"
```

### Bug 4：consistency_node 检验维度落后

```
当前检验覆盖：人物性格一致性、明显逻辑矛盾

未覆盖的致命维度：
  □ 物理空间连续性（主角位置是否瞬移）
  □ 资产连续性（新实体是否未经确认就出现）
  □ 时间颗粒度（悬念是秒级还是宏观事件级）
  □ 路径完整性（全部路径是否都被写到）
```

---

## 二、Scene Snapshot — 核心解决方案

### 设计原理

每章写作完成后，narrative_extract 提取一个**场景快照**，
记录本章结束时世界的精确物理状态。
这个快照是下一个事件生成的**强制输入基准**：
下一个事件只能在快照描述的世界状态上继续，不能跳跃。

类比：短剧每集结束的定格画面——
画面里的所有信息（人物位置、手持物品、周围环境）
都是下一集必须承接的起点。

### Scene Snapshot 数据结构

```json
{
  "scene_snapshot": {
    "chapter_id": "章节号",
    "narrative_timestamp": "叙事时间（相对时间描述，如：入夜后约一刻钟）",

    "location": {
      "macro": "宏观地点（矿洞）",
      "micro": "精确物理位置（洞口内侧，距入口约3步，乱石堆后方）"
    },

    "protagonist_state": {
      "posture": "蹲伏，背靠乱石",
      "physical_condition": "无外伤，全身紧绷，屏住呼吸",
      "held_items": ["铁令牌（从尸体处取得）"],
      "emotional_capacity_note": "精神高度紧张，阈值消耗约10点",
      "awareness": "已知信息的具体描述（我知道敌人在哪里）"
    },

    "other_characters_present": [
      {
        "character_id": "对应 entity_cards 的 character_id",
        "name": "暗杀队领队",
        "location": "洞内约10步，蹲在血迹旁",
        "posture": "低头注视地面血迹，尚未抬头",
        "held_items": ["铜盘追踪法器"],
        "awareness": "已知有人在此停留，尚未确认具体位置"
      }
    ],

    "confirmed_assets_in_scene": [
      {
        "asset_name": "铜盘追踪法器",
        "holder": "暗杀队领队",
        "status": "激活中",
        "location": "洞内约10步处"
      },
      {
        "asset_name": "蜥蜴血迹",
        "holder": null,
        "status": "暴露风险（已被领队注意到）",
        "location": "地面，领队蹲伏位置旁"
      },
      {
        "asset_name": "另外3名灰袍修士",
        "holder": null,
        "status": "驻守",
        "location": "洞口外约20步"
      }
    ],

    "last_sentence": "顾尘看见他停在刚才自己蹲过的地方。地上那摊蜥蜴血还在。",

    "cliffhanger_level": "high",
    "cliffhanger_nature": "秒级生死悬念",
    "cliffhanger_description": "领队正在看血迹，下一秒可能抬头，主角完全暴露",

    "spatial_constraints_for_next_event": [
      "顾尘当前在洞口内侧，不在洞内深处",
      "敌人从洞外进入，当前分布在洞口到洞内约10步的范围",
      "下一事件必须在这个空间格局的基础上继续，不能设定顾尘在洞内深处"
    ],

    "asset_constraints_for_next_event": [
      "敌人的追踪手段只有铜盘法器和修仙者神识",
      "禁止在下一事件中凭空引入猎犬、飞禽、其他追踪法器等未确认资产",
      "新资产的引入必须有故事内的合理来源（如从 world_archive 调用或对手从洞外拿来）"
    ]
  }
}
```

---

## 三、narrative_extract 修订——新增 Scene Snapshot 提取

**在原有伏笔提取和路径链还原的基础上，增加第四件事：**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
第四件事：Scene Snapshot 提取
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取正文的最后一个场景，提取以下信息：

1. 叙事时间戳
   不是现实时间，而是故事内的相对时间描述

2. 精确物理坐标
   ⚠️ 必须精确到"主角相对于周围物体的位置"
   不能是模糊的"在矿洞里"
   必须是"在洞口内侧约3步处，乱石堆后方蹲伏"

3. 当前姿态与物理状态
   姿势/持有物品/伤情/精神状态简述

4. 在场的其他角色
   每个角色的精确位置、姿态、持有物、已知信息

5. 已确认的场景资产（confirmed_assets_in_scene）
   ⚠️ 只列入在本章正文中明确出现或描述的实体
   未在正文中出现的，一律不列入
   这个列表是下一事件的"可用资产白名单"

6. 悬念状态评估
   last_sentence：正文最后一句话（原文照录）
   cliffhanger_level：high / medium / low
   cliffhanger_nature：秒级生死 / 分钟级危机 / 章节级悬念
   cliffhanger_description：一句话描述悬念的具体内容

7. 空间约束声明
   用一到三句话，明确声明对下一事件的空间约束
   格式："[主角名]当前在[精确位置]，下一事件必须基于此继续"

8. 资产约束声明
   用一到三句话，明确声明对下一事件的资产约束
   格式："禁止引入[未确认资产]，敌人的[能力]只能使用[已确认资产]"

【输出格式】
scene_snapshot 字段按上述结构完整输出，
作为 bible_update 回写到全局 State 的强制字段。
```

---

## 四、write 节点修订——路径完整性约束

### 关于路径写作方式的决策

**采用一次调用写完全部路径的方式**，原因：
- 每条路径的文气应该是连续的，拆开写会产生"接缝感"
- 多次调用的 token 消耗更高，且上下文重新注入有信息损耗
- path_to_next（过渡描述）本来就是为流畅的路径间衔接设计的

**真正需要修复的是：必须写完所有路径，不能留缺口。**

```
【write 节点新增：路径完整性铁律】

在动笔前，读取 path_gen 给出的完整路径列表：
  Path 1：[叙事时刻描述] → 过渡到：[path_to_next]
  Path 2：[叙事时刻描述] → 过渡到：[path_to_next]
  Path 3：[叙事时刻描述] → 过渡到：[path_to_next]
  Path N：[叙事时刻描述] → 停在：[scene_exit]

⚠️ 【绝对路径边界铁律】：
你必须写完以上全部 N 条路径，且只写这 N 条路径。

每条路径的边界：
  起点：上一条路径的 path_to_next 描述的状态
  终点：本条路径的 path_to_next 描述的过渡点（精确停在这里）

最后一条路径的终点：
  必须停在 scene_exit 描述的状态
  不得超越，不得在此之后继续推进情节

禁止行为：
  × 在某条路径写完后"顺势"继续写下一个事件的情节
  × 写到一半停止，让后续路径成为空白
  × 把多条路径的内容压缩进一条路径，跳过其他路径

字数约束（平台滤镜）：
  全章（所有路径合计）目标字数：约3000字
  各路径的字数分配根据其叙事功能自然决定：
    引爆/高张力路径：可以多一些（800-1200字）
    喘息/过渡路径：少一些（400-600字）
  禁止用内心独白或景物描写填充字数
```

### 平台滤镜（注入到 write 提示词的平台约束）

```
番茄男频滤镜：
  ⚠️ 情节推进密度优先
  3000字内必须完成 path_gen 规划的全部路径
  动作/对话/事件描写占比 ≥ 75%
  心理描写必须转化为动作细节（禁止纯内心独白段落）
  禁止用超过5行的景物描写或背景介绍填充字数
  每段结尾必须有推进感（不能是纯收束）

番茄女频滤镜：
  情感细节与情节推进并重
  对话密度高，心理描写细腻但不冗长
  情绪词可以适量使用，但必须有具体动作支撑

知乎男频滤镜：
  逻辑推导过程必须写出来，不能只写结论
  信息差的建立和利用要有足够的铺垫
  长句与短句交替，节奏有层次感

知乎女频滤镜：
  主角始终保持清醒感，不在心理描写中崩溃
  对话中的潜台词比台词更重要
  "被看见"的时刻要充分刻画
```

---

## 五、event_chain_gen 修订——接收并强制遵守 Scene Snapshot

**在 World Tick 步骤之前，新增第零步：**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
第零步：Scene Snapshot 强制读取（在所有推导之前执行）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取上一章的 scene_snapshot，这是本事件推演的绝对起点。

⚠️ 【物理连续性铁律】：
本事件的所有推演，必须在 scene_snapshot 描述的物理状态基础上继续。
禁止任何与 spatial_constraints_for_next_event 矛盾的设定。

⚠️ 【资产连续性铁律】：
本事件中出现的所有实体，必须满足以下条件之一：
  a) 已在 confirmed_assets_in_scene 中列出
  b) 已在 world_archive 中登记，且有合理的故事内来源
  c) 通过角色的具体行动引入（如"领队从怀中取出..."）

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
```

---

## 六、consistency_node 重构

### 旧版的问题

旧版 consistency_node 的检验维度：
- 人物性格一致性
- 明显的逻辑矛盾

这些检验无法发现：物理空间断层、资产幻觉、时间颗粒度跳跃、路径缺口。

### 重构后的两套检验

**第一套：硬性物理一致性（新增，必须通过）**

```
检验一：物理空间连续性
  对照 scene_snapshot.spatial_constraints_for_next_event，
  检查本章开头的物理设定是否与上一章的空间约束矛盾。

  通过条件：本章描述的人物位置与上一章 scene_snapshot
            的 protagonist_state.location 和 micro 一致
  失败条件：人物出现了 spatial_constraints 明确禁止的位置

检验二：资产连续性
  对照 scene_snapshot.confirmed_assets_in_scene 和
  scene_snapshot.asset_constraints_for_next_event，
  检查本章是否引入了未经确认的实体。

  通过条件：本章出现的所有实体，来源可追溯
  失败条件：出现了 asset_constraints 明确禁止的实体

检验三：悬念承接连续性
  如果上一章 cliffhanger_level = high，
  检查本章开头是否直接承接了 last_sentence 的下一秒。

  通过条件：本章开头的叙事时间颗粒度与 cliffhanger_level 匹配
  失败条件：high 级悬念后以宏观事件摘要起头

检验四：路径完整性
  对照 path_gen 的路径列表，
  检查本章是否覆盖了所有规划的路径。

  通过条件：每条路径的 path_to_next 描述的过渡点都在正文中有对应内容
  失败条件：某条路径完全缺失，或最后一条路径超越了 scene_exit

以上任一检验失败 → 直接返回 revise，无需继续
失败路由：
  检验一/二失败 → routing: event_chain_gen（需要重新生成事件）
  检验三失败 → routing: write（重写章节开头）
  检验四失败 → routing: write（补全缺失路径）
```

**第二套：叙事质量一致性（原有+扩展）**

```
保留原有的人物性格一致性检验，在此基础上扩展：

检验五：世界词条一致性（来自补丁C）
  对照 world_lexicon 中相关词条的 static_profile.hard_constraints，
  检查本章是否违背了已确立的词条属性。
  例：清蕴丹是否被用于治疗它不能治疗的症状？

检验六：动机一致性（来自补丁D）
  对照 active_quest_stack 中 urgency_level = critical 的任务，
  检查本章是否完全忘记了最紧迫的目标。
  失败案例：主角的 immediate 层任务是"三天内救老吴"，
            但本章3000字没有任何老吴相关的内心活动或行动

检验七：角色精神层面一致性
  对照 entity_cards 中相关角色的 innate_traits，
  检查角色行为是否违背了性格底色。
  （原有功能，继续保留）
```

### 重构后的输出规范

```json
{
  "verdict": "approve / revise",

  "physical_consistency": {
    "spatial_check": "pass / fail",
    "spatial_issue": "如失败：引用 spatial_constraints 说明冲突点",
    "asset_check": "pass / fail",
    "asset_issue": "如失败：引用 asset_constraints 说明幻觉资产名称",
    "cliffhanger_check": "pass / fail / na",
    "cliffhanger_issue": "如失败：说明时间颗粒度跳跃",
    "path_completeness_check": "pass / fail",
    "missing_paths": ["缺失的 path_id 列表"]
  },

  "narrative_consistency": {
    "lexicon_check": "pass / fail",
    "lexicon_issue": "违背的词条 lexicon_id 和具体冲突",
    "quest_check": "pass / fail",
    "quest_issue": "被遗忘的 quest_id 和 quest_name",
    "character_check": "pass / fail",
    "character_issue": "违背性格底色的角色和具体行为"
  },

  "routing_decision": "event_chain_gen / write / expand2 / expand1 / bible_update",
  "revision_focus": "最需要优先修复的核心问题（一句话）"
}
```

### 检验的优先级和路由逻辑

```
优先级顺序（从高到低）：

1. 物理空间检验（最高优先级）
   失败 → 立即返回，routing: event_chain_gen
   原因：空间断层是根本性错误，其他一切检验都没有意义

2. 资产连续性检验
   失败 → 返回，routing: event_chain_gen
   原因：幻觉资产会在后续事件中持续蔓延，越早修复越好

3. 路径完整性检验
   失败 → 返回，routing: write
   原因：路径缺口可以在 write 层修复，不需要重新生成事件

4. 悬念承接检验
   失败 → 返回，routing: write（重写开头）

5. 叙事一致性检验（词条/动机/性格）
   失败 → 视严重程度路由到 write 或 expand1

当多个检验同时失败时：
  只输出最高优先级的失败项作为 revision_focus
  避免给 write 节点一份无法执行的修改清单
```

---

## 七、数据流向更新

```
narrative_extract
  └─ scene_snapshot ──────────────────────────→ bible_update（回写到全局 State）
                   ──────────────────────────→ event_chain_gen（第零步强制读取）
                   ──────────────────────────→ consistency_node（物理一致性基准）

write（一次写完全部路径）
  └─ 全章正文 ──────────────────────────────→ consistency_node

consistency_node（重构后）
  读取：
    scene_snapshot（物理基准）
    path_gen 的路径列表（路径完整性基准）
    world_lexicon（词条约束基准）
    active_quest_stack（动机连续性基准）
    entity_cards（性格一致性基准）
  输出路由：
    event_chain_gen / write / expand2 / expand1 / bible_update
```

---

## 八、设计决策记录

### 8.1 为什么 confirmed_assets_in_scene 是白名单而非黑名单？

黑名单的逻辑是"禁止X"，但新的幻觉资产是无穷多的，无法穷举禁止。
白名单的逻辑是"只能使用Y"，更具封闭性——
只有正文中明确出现过的资产才能被下一个事件使用，
其他任何资产的引入都需要有明确的故事内来源。

### 8.2 为什么悬念承接要按 cliffhanger_level 分级而不是统一规则？

不同强度的悬念，读者心理预期不同：
- 秒级生死（high）：读者脑子里还停在"领队要发现顾尘了"，
  下一章如果跳到"两天后"，读者会直接懵
- 章节级悬念（low）：读者知道这是一个"未解决的问题"，
  时间跳跃是正常的叙事节奏

用分级代替统一规则，允许不同类型的悬念有不同的承接逻辑。

### 8.3 为什么 consistency_node 要输出 routing 而不只是 pass/fail？

pass/fail 只告诉系统"有问题"，routing 告诉系统"去哪里修"。
空间断层需要从 event_chain_gen 重新生成；
路径缺口只需要 write 补写；
性格违背可能需要回到 expand1 重新规划场景。

不同问题的修复代价不同，
routing 让系统把修复成本控制在最小必要的层级。

---

## 九、与 v4.3 终版文档的对照变更说明

| 节点 | 变更类型 | 核心变更内容 |
|------|---------|------------|
| narrative_extract | 扩展 | 新增第四件事：Scene Snapshot 提取（精确物理坐标/在场角色/confirmed_assets/悬念评估/空间和资产约束声明） |
| write | 修订 | 新增路径完整性铁律（必须写完所有路径，不能留缺口）；新增平台滤镜（情节推进密度约束）；全章约3000字，路径间字数自然分配 |
| event_chain_gen | 扩展 | 新增第零步（Scene Snapshot 强制读取）：物理连续性铁律/资产连续性铁律/悬念承接铁律 |
| consistency_node | 重构 | 两套检验：硬性物理一致性（空间/资产/悬念承接/路径完整性）+ 叙事质量一致性（词条/动机/角色）；输出新增 routing_decision 字段；优先级排序明确 |
| bible_update | 扩展 | 新增 scene_snapshot 回写到全局 State |

---

> **文档版本**：DeepNovel v4.3 补丁 F
> **修复的核心 Bug**：
>   空间物理断层（瞬移 Bug）
>   路径边界坍塌（write 越权+留缺口）
>   资产幻觉（猎犬空降）
>   consistency_node 检验维度落后
> **核心解决方案**：
>   Scene Snapshot（场景快照）作为事件切换的物理状态基准；
>   confirmed_assets 白名单约束下一事件可用实体；
>   cliffhanger_level 驱动悬念承接的时间颗粒度；
>   consistency_node 引入物理一致性检验层。