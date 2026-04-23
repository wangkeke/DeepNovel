# DeepNovel v4.3 · 补丁文档 C
## 世界词条库（World Lexicon）

> **文档定位**：本文档是对 v4.3 终版架构文档的第三份补丁，
> 新增 world_lexicon（世界词条库）数据结构及其在各节点中的读写规范。
> 合并时以本文档为准，在 narrative_extract、bible_update、
> event_chain_gen、expand1/2、write 节点中新增对应的读写逻辑。

---

## 一、为什么需要世界词条库？

现有体系有三个层级：

```
world_archive    → 势力、地理、世界物理规则（宏观）
entity_cards     → 角色档案（附着于人）
karmic_ledger    → 伏笔账本（因果链，有引爆终点）
```

缺失的是第四个层级：

```
world_lexicon    → 世界中存在的"砖块"（不附着于人，无引爆终点）
                   地名、药名、器具名、毒素名、功法名...
```

这些"砖块"有两个特性使得它们无法被现有体系覆盖：

**特性一：静态属性必须锁定**
清蕴丹永远治蚀骨阴毒，不会变成治感冒药。
金丹期修士用的清蕴丹与筑基期的规格不同。
这些属性一旦在某章确立，后续章节不能违背——
但模型没有记忆，很容易写着写着就忘了。

**特性二：动态关联持续积累，且名称不能变化**
清蕴丹在第1章是"救治老吴的希望"，
在第3章可能是"被反派截获的筹码"，
在第5章可能是"主角用来交换情报的货币"。
每次出现时携带的语境不同，但这个词条本身的名字和静态属性不变。

---

## 二、词条的三种类型

### 类型A：纯静态词条

不会被"使用"，只会被"提及"或"出现在场景中"。

```
例：
  蚀骨荒原（地名）→ 只有地理属性，不会"被人使用"
  蚀骨阴毒（毒素）→ 只有毒性属性，但会附着在受害者身上
  荒芜道蕴（法则）→ 世界规则层面的概念
```

这类词条只需要静态档案，用于防止描述前后矛盾。

### 类型B：可被持有和使用的词条

有静态属性，同时可以被角色持有、使用、交换、争夺。

```
例：
  清蕴丹  → 静态：治蚀骨阴毒，金丹期规格，市价约50下品灵石
             动态：目前是陆沉的目标资源，尚未获取
  老吴的短刀 → 静态：铁质，刃口布满裂痕，沾染荒气
               动态：目前在陆沉手中，携带未完整词条
  钥匙碎片 → 静态：荒芜道蕴载体，状态沉寂，激活条件未知
             动态：目前的悬赏目标，真实持有者未知
```

这类词条需要静态档案 + 动态持有/关联追踪。

### 类型C：携带动态线索的词条

首次出现时带着不完整的信息（如老吴短刀上的"沾染荒气的..."），
这个不完整本身就是一条线索，意味着后续必然有章节来补完它。

```
例：
  【沾染'荒'气的…】（不完整词条）
  → 这不只是一个物品的属性，而是一条有待揭示的线索
  → 后续某章必然有"短刀词条补全"的事件
  → 如果模型忘了这个词条，那一章就永远不会被触发
```

这类词条需要静态档案 + 动态线索追踪 + 未来触发标记。

---

## 三、world_lexicon 数据结构

```json
{
  "lexicon_id": "词条唯一标识（如 LEX_001）",
  "term": "词条标准名称（此名称在全书不能变化）",
  "term_type": "A（纯静态）/ B（可持有）/ C（携带线索）",
  "category": "地名 / 药物 / 器具 / 毒素 / 功法 / 法则 / 组织 / 其他",

  "static_profile": {
    "definition": "这个词条是什么，一句话说清楚",
    "inherent_attributes": [
      "属性1（如：治疗蚀骨阴毒）",
      "属性2（如：金丹期修士服用规格与筑基期不同）",
      "属性3（如：市价约50下品灵石）"
    ],
    "hard_constraints": [
      "绝对不能违背的属性（如：不能用于治疗非蚀骨阴毒的症状）"
    ],
    "world_physics_basis": "这个词条基于世界设定中的哪条物理规则存在"
  },

  "dynamic_associations": [
    {
      "chapter_id": "首次出现的章节号",
      "event_id": "关联的事件 event_id",
      "association_type": "持有 / 目标 / 筹码 / 威胁 / 线索 / 其他",
      "holder": "当前持有者或关联角色的 character_id（无则填null）",
      "context_note": "此章中这个词条承载的具体语境",
      "is_active": true
    }
  ],

  "incomplete_clue": {
    "has_incomplete_clue": false,
    "clue_fragment": "不完整的词条内容（如：沾染'荒'气的…）",
    "trigger_condition": "什么情况下会补全这条线索",
    "completion_status": "pending / revealed"
  },

  "first_appearance": {
    "chapter_id": "首次出现的章节号",
    "appearance_mode": "static（纯静态出现）/ dynamic（携带动态线索出现）",
    "was_noticed_by_protagonist": true
  }
}
```

---

## 四、词条与伏笔的关系

词条和伏笔是两个独立的系统，但可以关联：

```
词条（world_lexicon）：
  描述"这个东西是什么"和"它当前处于什么语境中"
  静态属性永远锁定
  动态关联持续追加
  没有"引爆"的概念，只有"再次出现"

伏笔（karmic_ledger）：
  描述"这个细节将在未来引爆"
  有明确的引爆时机和方式
  引爆后关闭

关联示例：
  老吴短刀上的不完整词条【沾染'荒'气的…】
  → 在 world_lexicon 中：这是一个 C类词条，has_incomplete_clue = true
  → 在 karmic_ledger 中：这也是一条伏笔（短刀词条的补全会在某章触发）
  → 二者的 ID 互相引用，形成关联
  → 区别：词条记录的是"这个短刀的属性"，伏笔记录的是"这个秘密将被揭示"
```

---

## 五、各节点的读写规范

### narrative_extract（新增词条提取逻辑）

在原有伏笔提取的基础上，增加第三件事：词条识别与注册。

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━
第三件事：词条识别与注册
━━━━━━━━━━━━━━━━━━━━━━━━━━━

读取正文，识别以下类型的词条候选项：

【识别标准】
以下情况需要注册为词条：

1. 具名的地名、丹药、器具、毒素、功法、特殊材料
   且其属性在正文中有任何形式的描述或暗示

2. 首次出现或属性有新增的已有词条

3. 携带不完整信息的物品（如：【沾染'荒'气的…】这类不完整词条）

【不需要注册为词条的情况】

- 泛指的普通物品（一把椅子、几块灵石）
- 已在 world_archive 中作为势力或地理单元注册的内容
  （不重复注册，但可以在 world_archive 对应条目中新增属性）
- 被角色持有的普通随身物品（没有特殊属性或线索）

【词条类型判断】

正文中这个词条是：
- 只被提及，没有被使用或持有 → 类型A
- 被某人持有/使用/争夺/交换 → 类型B
- 携带了不完整信息或有待揭示的属性 → 类型C
  （类型C通常同时也是类型B）

【词条与伏笔的关联判断】

如果一个词条满足以下条件，同时在 karmic_ledger 中注册一条伏笔：
- 类型C（携带不完整线索），且
- 不完整线索的揭示在故事中有明确的因果价值

在伏笔条目中通过 lexicon_ref 字段引用对应词条的 lexicon_id。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
词条输出规范（追加到 narrative_extract 输出中）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

"lexicon_updates": [
  {
    "action": "new（新注册）/ update_static（更新静态属性）
               / update_dynamic（新增动态关联）",
    "lexicon_id": "如果是update，填写已有词条的 lexicon_id",
    "term": "词条标准名称",
    "term_type": "A / B / C",
    "category": "类别",
    "static_profile": {
      "definition": "一句话定义",
      "inherent_attributes": ["本章确立的属性列表"],
      "hard_constraints": ["本章确立的约束条件"],
      "world_physics_basis": "依据的世界物理规则"
    },
    "dynamic_association": {
      "chapter_id": "当前章节号",
      "event_id": "当前事件 event_id",
      "association_type": "持有/目标/筹码/威胁/线索/其他",
      "holder": "持有者 character_id（null表示无）",
      "context_note": "此章的具体语境"
    },
    "incomplete_clue": {
      "has_incomplete_clue": false,
      "clue_fragment": "不完整词条原文",
      "trigger_condition": "补全条件",
      "karmic_ledger_ref": "关联的伏笔 seed_id（null表示不关联）"
    }
  }
]
```

---

### bible_update（新增词条回写逻辑）

```
【world_lexicon 更新（新增）】

来源：读取 narrative_extract 的 lexicon_updates 字段。

对每条词条更新执行以下操作：

action = "new"：
  在 world_lexicon 中新增词条条目，
  static_profile 完整写入，
  dynamic_associations 初始化为当前章节的关联。

action = "update_static"：
  找到对应词条，在 static_profile 中追加新属性。
  ⚠️ 追加，不覆盖。已确立的属性不能被修改，只能新增。
  如果新属性与已有属性矛盾，标注冲突，路由到 human_review。

action = "update_dynamic"：
  找到对应词条，在 dynamic_associations 中追加新关联。
  将上一条关联的 is_active 设为 false，新关联的 is_active 设为 true。
  （同一时刻，一个词条只有一条 active 关联，
   但历史关联保留，构成完整的动态线索链）

词条完整性校验：
  如果某个词条的静态属性在本章的使用中被违背
  （例：清蕴丹被用于治疗非蚀骨阴毒的症状），
  标注违约，在 anchor_integrity_check 中报告。
```

bible_update 输出规范中新增 `lexicon_updates_applied` 字段：

```json
"lexicon_updates_applied": [
  {
    "lexicon_id": "词条标识",
    "term": "词条名称",
    "action_taken": "new / update_static / update_dynamic",
    "conflict_detected": false,
    "conflict_note": "如有冲突，描述冲突内容"
  }
]
```

---

### event_chain_gen（读取词条库的相关规范）

在运行三步命运编织引擎时，将 world_lexicon 中的 active 词条
注入 World Tick 的背景信息：

```
【world_lexicon 注入 World Tick】

读取 world_lexicon 中所有 is_active = true 的动态关联，
按以下优先级筛选注入：

优先级1：类型C词条（携带未完整线索的词条）
  → 这些词条在世界中"等待被触发"
  → World Tick 在推导势力和角色的自然行动时，
    应考虑这些词条是否可能成为事件的触发点

优先级2：高价值的B类词条（被多方势力关联的词条）
  → 如钥匙碎片（陆沉的目标/灰蛇的悬赏/百里世家的觊觎）
  → 这类词条本身就是资源竞争的焦点，可以直接成为事件驱动力

优先级3：当前持有者正在进行中的动态关联
  → 如清蕴丹（陆沉的当前目标）
  → 主角需求（Protagonist Tick）应与这些词条保持一致
```

---

### expand1/expand2/write（词条一致性约束）

在 expand1 的状态确认步骤中，新增词条一致性检查：

```
【词条一致性检查（新增到 expand1 第一步）】

读取本章场景中将要出现的词条，
对照 world_lexicon 中的 static_profile：

- 本章计划如何使用这个词条？
- 是否违背了 hard_constraints？
- 持有者是否与 dynamic_associations 中的 active 关联一致？

如果发现不一致：
→ 在 expand1 输出中标注词条一致性警告
→ 说明当前计划与词条档案的冲突点
→ 由 expand1 自行修正，或路由到 human_review_expand
```

write 节点不需要额外修改——
词条一致性在 expand1 层已经校验，write 只负责执行。

---

## 六、词条的生命周期

```
初次出现
  ↓ narrative_extract 识别并注册
  ↓ bible_update 写入 world_lexicon
  ↓ 状态：已登记，static_profile 初始化，
          dynamic_associations 记录首次关联

再次出现（普通使用）
  ↓ narrative_extract 识别为 update_dynamic
  ↓ bible_update 追加新的动态关联，旧关联 is_active = false
  ↓ 状态：static 不变，dynamic 追加

再次出现（揭示新属性）
  ↓ narrative_extract 识别为 update_static
  ↓ bible_update 在 static_profile 中追加新属性
  ↓ 状态：static 扩充，动态关联同步更新
  ↓ 如果是 C类词条的不完整线索被补全：
    completion_status 从 pending 改为 revealed
    关联的 karmic_ledger 伏笔触发引爆流程

成为历史词条（不再活跃）
  ↓ 当某个词条的所有 dynamic_associations 都变为 is_active = false，
    且在若干章后没有新的关联
  ↓ 词条保留在档案中（静态属性永久存档），
    不再注入 event_chain_gen 的 World Tick
  ↓ 状态：归档，供回溯查询
```

---

## 七、词条库与各系统的关系图

```
world_lexicon
  ↑ 写入来源：narrative_extract → bible_update
  ↓ 读取用途：

  event_chain_gen
    ← 读取 active 词条，作为 World Tick 的背景信息
    ← 特别关注 C类词条的触发条件

  expand1
    ← 读取本章相关词条的 static_profile
    ← 进行词条一致性校验

  karmic_ledger（伏笔账本）
    ↔ C类词条与对应伏笔互相引用（lexicon_ref / karmic_ledger_ref）
    → C类词条的 completion_status 变为 revealed 时，
      触发关联伏笔的引爆流程

  protagonist_archive / entity_cards（角色档案）
    ← 角色"持有"某词条时，在词条的 dynamic_associations 中记录，
      在角色档案的 signature_items 中记录
    → 两者通过 lexicon_id 互相引用，不重复存储静态属性
```

---

## 八、与第一章测试的对应

以第一章为例，词条库应该包含的条目：

```
LEX_001  蚀骨荒原    A类  地名
  静态：边荒绝地最深处区域，进去十个能活着出来一个
  动态：本章作为故事背景反复出现，尚无具体关联者

LEX_002  蚀骨阴毒    A类  毒素
  静态：慢慢蚀穿经脉最后烂掉骨头，解药是清蕴丹
  动态：老吴（victim），chapter_1，is_active=true

LEX_003  清蕴丹      B类  药物
  静态：治蚀骨阴毒，市价50下品灵石（起码）
  动态：陆沉的目标资源，尚未获取，chapter_1，is_active=true

LEX_004  续脉丹      B类  药物
  静态：治经脉枯竭，市价约7下品灵石
  动态：陆沉的目标资源，尚未获取，chapter_1，is_active=true

LEX_005  缓毒散      B类  药物
  静态：暂时缓解蚀骨阴毒，约3块灵石一副，可争取10天
  动态：陆沉的备选方案，尚未获取，chapter_1，is_active=true

LEX_006  老吴的短刀  C类  器具
  静态：铁质，刃口布满细密裂痕，刀身暗红污渍洗不掉
  动态：陆沉持有，chapter_1，is_active=true
  不完整线索：【沾染'荒'气的…】，后续几字未看清
  触发条件：主角在某个事件中再次专注观察此刀，
            或接触同源道蕴时词条自动补全
  关联伏笔：[待注册为 karmic_ledger 条目]

LEX_007  钥匙碎片    C类  器具
  静态：承载荒芜道蕴，状态沉寂，激活条件：接触同源道蕴或地脉节点
  动态：灰蛇悬赏目标，实际持有者未知，chapter_1，is_active=true
  关联伏笔：[karmic_ledger F001_05]

LEX_008  阴骨草      B类  药材
  静态：蚀骨荒原特产，三块灵石一株，功效未记录
  动态：集市摊主在售，chapter_1，is_active=false（仅路过提及）

LEX_009  古修士信物  C类  器具（类型待确认）
  静态：奇异纹路，无法辨识材质，带有古老气息，求购方出价高
  动态：未知求购者（告示），chapter_1，主角未注意到
  不完整线索：与钥匙碎片同体系？属性完全未知
  触发条件：主角后续注意到这张告示，或在荒原中遇到此类物品
```

从这个列表可以看出：
- 清蕴丹/续脉丹/缓毒散是**功能道具词条**，不是伏笔，但需要静态属性锁定
- 老吴短刀和古修士信物是**C类词条**，同时也是伏笔
- 这两个系统各司其职，互补不替代

---

## 九、设计决策记录

### 9.1 为什么动态关联要保留历史记录而不是覆盖？

一个词条的动态关联历史，本身就是这个世界的叙事线索之一。
清蕴丹从"陆沉救老吴的目标"到"被反派截获的筹码"到"交换情报的货币"，
这条变化链条是世界真实发展的见证。

如果只保留最新关联而删除历史，模型在后续事件中将失去"这个东西之前在谁手里"
的上下文，容易产生持有者混乱的问题。

### 9.2 为什么 C类词条同时注册伏笔，而不是直接用词条替代伏笔？

词条描述"这个东西是什么状态"，伏笔描述"这个秘密将被揭示"。
老吴短刀的不完整词条：
- 词条层面：这个刀有荒气污染，具体什么状态未知（物品的属性状态）
- 伏笔层面：这个秘密将在某个事件中以意想不到的方式被揭示（因果契约）

两个维度不可替代：词条会持续存在，伏笔在引爆后关闭。

### 9.3 为什么 static_profile 只能追加不能覆盖？

静态属性一旦在正文中确立，就成为了读者与作品之间的"世界契约"。
读者记住了"清蕴丹治蚀骨阴毒"，后续如果改成"清蕴丹其实治筋骨损伤"，
这是对读者信任的背叛。

追加是允许的（"清蕴丹不仅治蚀骨阴毒，还能辅助稳固筑基期经脉"），
覆盖是禁止的。bible_update 在执行 update_static 时，
如果检测到新属性与已有属性矛盾，必须路由到 human_review，
而不是自动覆盖。

---

## 十、与 v4.3 终版文档的对照变更说明

| 节点 | 变更类型 | 核心变更内容 |
|------|---------|------------|
| narrative_extract | 扩展 | 新增第三件事：词条识别与注册；输出规范新增 lexicon_updates 字段 |
| bible_update | 扩展 | 新增 world_lexicon 更新逻辑（new/update_static/update_dynamic）；输出规范新增 lexicon_updates_applied 字段 |
| event_chain_gen | 扩展 | World Tick 注入 world_lexicon 中的 active 词条，按优先级（C类→多方关联B类→当前进行中）筛选 |
| expand1 | 扩展 | 第一步状态确认新增词条一致性检查，防止违背已确立的 hard_constraints |
| 数据结构 | 新增 | world_lexicon 完整数据结构定义（lexicon_id/term/term_type/static_profile/dynamic_associations/incomplete_clue） |

---

> **文档版本**：DeepNovel v4.3 补丁 C
> **补丁内容**：世界词条库（World Lexicon）完整设计
> **三种词条类型**：
>   A类（纯静态，防描述矛盾）
>   B类（可持有，静态锁定+动态追踪）
>   C类（携带线索，静态+动态+不完整线索触发）
> **核心原则**：
>   静态属性只追加不覆盖（世界契约）；
>   动态关联保留历史链（叙事见证）；
>   词条与伏笔互补不替代（两个维度各司其职）。