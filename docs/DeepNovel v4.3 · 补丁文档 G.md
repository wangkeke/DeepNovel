# DeepNovel v4.3 · 补丁文档 G
## Write 节点架构修订：单路径单次生成

> **文档定位**：本文档修订补丁F中"一次write写完全部N条路径"的决策，
> 改为"单路径单次write"。此修订覆盖补丁F中关于write节点路径写作方式
> 的全部内容，其余补丁F内容（Scene Snapshot、consistency_node重构等）保持不变。

---

## 一、为什么需要修订补丁F的决策

### 补丁F的原始决策

```
"采用一次调用写完全部路径的方式"
理由：路径间文气应该是连续的，拆开写会产生"接缝感"
```

### 这个决策在测试中导致的问题

**问题一：颗粒度坍塌**

一个事件被 path_gen 拆解为4条路径，4个不同的物理场景：
```
路径1：广场（目击灵根、介入黑吃黑）
路径2：下水道（发现古仙庭禁制、清点物资）
路径3：城南磨坊（分析选项）
路径4：西门驿亭（伏击铁算盘）
```

一次write写完4条路径 → 约6000字 → 4个场景各1500字
→ 每个场景根本无法落地，变成疯狂赶大纲
→ 读者感受：人物在瞬移，情绪张力无法在任何一个场景中积累

**问题二：模型注意力漂移**

单次生成超过3000字后，模型的局部逻辑开始漂移。
测试中出现：前文铺垫去找"城南破庙的独臂傀儡师"，
结尾变成去找"西门守夜人宋老三"——两个完全不同的人物。
这不是模型能力问题，而是超出最优注意力窗口的必然结果。

**问题三：质检无法精确校验**

当write输出了4个场景的6000字正文，
tension_check无法判断"当前路径的核心动作是否被正确执行"，
只能做模糊的张力检验，导致文不对题也能通过。

### 接缝感问题的实际解法

补丁F担心的"接缝感"可以通过在每次write提示词中注入
"上一路径的最后一句话"来解决，而不是强行在一次调用中写完所有路径。

---

## 二、修订后的架构决策

### 单路径单次write

```
旧方案（补丁F）：
  path_gen → [路径1, 路径2, 路径3, 路径4]
  → 一次write → 全部4条路径的正文（约3000-6000字）
  → tension_check（模糊校验）
  → narrative_extract
  → bible_update

新方案（补丁G）：
  path_gen → [路径1, 路径2, 路径3, 路径4]

  → write（路径1）→ tension_check（精确校验路径1）→ 通过
  → write（路径2，注入路径1末句）→ tension_check（精确校验路径2）→ 通过
  → write（路径3，注入路径2末句）→ tension_check（精确校验路径3）→ 通过
  → write（路径4，注入路径3末句）→ tension_check（精确校验路径4）→ 通过

  → narrative_extract（读取全部4条路径的合并正文）
  → bible_update
```

### 章节的概念重新定义

```
旧定义：一章 = 一次write的输出 ≈ 3000字

新定义：
  一章 = 一个事件的全部路径的正文合集
  一个路径 = 一次write的输出 ≈ 800-1500字

全章总字数 = 各路径字数之和
  2条路径的事件 → 约1600-3000字/章
  4条路径的事件 → 约3200-6000字/章
  路径数由 path_gen 根据事件复杂度决定，不由字数目标倒推
```

---

## 三、修订后的write节点提示词

**节点职责**：只写当前这一条路径的正文，精确停在路径的 scene_exit 处。

```
你是一位小说家。
你现在要写的是当前路径的正文——只有这一条路径，不多也不少。

━━━━━━━━━━━━━━━━━━━━━━━━━━━
当前路径信息
━━━━━━━━━━━━━━━━━━━━━━━━━━━

路径名称：{path_name}
叙事时刻：{path_name}（读者此刻看到了什么）
叙事功能：{narrative_function}
视角角色：{pov_character}
场景停止点：{scene_exit}（你必须在这里停止）

上一路径的末句（承接点）：
{previous_path_last_sentence}
（从这句话的下一秒开始写，不要重复这句话）

━━━━━━━━━━━━━━━━━━━━━━━━━━━
【绝对边界铁律】
━━━━━━━━━━━━━━━━━━━━━━━━━━━

你只写当前路径（{path_name}）的内容。

⚠️ 禁止越界：
  × 不得推进到下一条路径的场景
  × 不得自行安排场景转换（禁止用 *** 或空行分割后进入新场景）
  × 不得超越 scene_exit 描述的状态继续推进情节

⚠️ 必须完成：
  ✓ 覆盖本路径叙事功能（{narrative_function}）
  ✓ 在本路径中必须有一个角色做出真实的选择（有代价）
  ✓ 正文以 scene_exit 描述的状态自然结束

━━━━━━━━━━━━━━━━━━━━━━━━━━━
字数与节奏约束
━━━━━━━━━━━━━━━━━━━━━━━━━━━

单路径字数目标：800-1500字
  引爆/高张力路径：1000-1500字
  建立信息/喘息路径：800-1000字

[平台滤镜（由系统注入当前平台的具体约束）]

━━━━━━━━━━━━━━━━━━━━━━━━━━━
动笔前的六项确认（检查清单，确认后忘掉它，专注写作）
━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 这条路径的核心动作，由谁的意志驱动？
2. 本路径涉及的资源/能力，在前文有铺垫吗？
3. 扣动关键动作的，是角色的精神层面，而非资源自动生效
4. 本路径结束时，留下了什么开口（指向 scene_exit）？
5. 角色的成长体现在行为差异，不体现在内心独白的解释
6. user_anchors 没有被触碰

确认通过，开始写作。
```

---

## 四、修订后的 tension_check 节点

单路径单次write后，tension_check可以做精确的题面对齐校验。

### 新增：题面对齐硬拦截（最高优先级）

```
在所有原有检验之前，新增第零项检验：

【检验零：题面对齐（必须首先通过）】

对照 path_gen 给出的当前路径定义：
  path_name：{path_name}
  narrative_function：{narrative_function}
  pov_character：{pov_character}
  scene_exit：{scene_exit}

检验本次正文是否与上述定义对齐：

对齐检验一：物理场景
  正文发生的主要地点，是否与 path_name 描述的叙事时刻一致？
  例：path_name 是"水渠深处的账本重算"
      正文却全程在西门驿亭 → 不对齐，直接失败

对齐检验二：核心动作
  正文中是否包含了 narrative_function 要求的核心内容？
  例：narrative_function 是"建立信息（让读者知道账本里有什么）"
      正文完全没有账本相关内容 → 不对齐，直接失败

对齐检验三：视角角色
  正文是否以 pov_character 为视角角色？
  （允许短暂的其他视角，但主视角必须一致）

对齐检验四：边界遵守
  正文是否在 scene_exit 描述的状态处停止？
  是否出现了下一条路径的场景内容？

以上任一对齐检验失败 → 立即返回 revise，routing: write
不进行后续检验，不浪费资源
```

### 修订后的完整输出规范

在补丁F的 consistency_node 输出规范基础上，tension_check 新增：

```json
{
  "path_alignment": {
    "scene_match": "pass / fail",
    "scene_issue": "如失败：正文实际场景 vs path_name 期望场景",
    "function_match": "pass / fail",
    "function_issue": "如失败：缺少的核心内容描述",
    "pov_match": "pass / fail",
    "boundary_respected": "pass / fail",
    "boundary_issue": "如失败：越界到了哪条路径的内容"
  },
  "verdict": "pass / revise",
  "routing": "write / expand2 / expand1",
  "revision_focus": "一句话，最优先修复的核心问题"
}
```

---

## 五、单路径循环的状态机设计

### 路径进度追踪（新增到全局 State）

```json
"path_progress": {
  "current_event_id": "ev_1_001",
  "total_paths": 4,
  "paths_status": [
    {
      "path_id": "ev_1_001_p01",
      "path_name": "广场目击",
      "status": "completed",
      "last_sentence": "他的目光落在那枚令牌上，停了三秒。"
    },
    {
      "path_id": "ev_1_001_p02",
      "path_name": "水渠深处的账本重算",
      "status": "in_progress",
      "last_sentence": null
    },
    {
      "path_id": "ev_1_001_p03",
      "path_name": "磨坊分析选项",
      "status": "pending",
      "last_sentence": null
    },
    {
      "path_id": "ev_1_001_p04",
      "path_name": "驿亭伏击",
      "status": "pending",
      "last_sentence": null
    }
  ],
  "current_path_index": 1,
  "all_paths_text": "已完成路径的正文合集（用于 narrative_extract 读取）"
}
```

### 循环控制逻辑（bible_update 执行）

```
每条路径写完并通过 tension_check 后，bible_update 执行：

1. 将本路径正文追加到 path_progress.all_paths_text
2. 更新本路径状态为 completed，记录 last_sentence
3. 检查是否还有 pending 状态的路径：

   如果有：
     current_path_index += 1
     从 paths_status 读取下一条路径的定义
     注入 previous_path_last_sentence（当前路径的 last_sentence）
     路由回 write（下一条路径）

   如果没有（所有路径 completed）：
     读取 all_paths_text（全部路径的合并正文）
     路由到 narrative_extract（处理整章的合并正文）
```

---

## 六、narrative_extract 和 consistency_node 的适配

### narrative_extract 的输入变化

```
旧输入：单次write的正文（一次全部路径）
新输入：all_paths_text（全部路径完成后的合并正文）

narrative_extract 的处理对象不变（依然是完整的章节正文），
只是接收时机变了（等所有路径都完成后才触发）。

Scene Snapshot 依然从合并正文的最后一条路径中提取，
不受路径拆分影响。
```

### consistency_node 的适配

```
单路径 tension_check 已经在每条路径完成时做了路径级校验。
最终的 consistency_node 在 narrative_extract 之后运行，
处理的是合并正文，做全局一致性检验：

  物理空间连续性（跨路径的场景衔接是否合理）
  资产连续性（补丁F的 confirmed_assets 约束）
  动机一致性（补丁D的 active_quest_stack）
  词条一致性（补丁C的 world_lexicon）
  角色性格一致性

不再需要检验"路径完整性"（因为每条路径都经过了独立的 tension_check）。
```

---

## 七、代码层需要修复的独立问题

以下两个问题与架构决策无关，是独立的代码fix：

### Fix 1：对话占比检测的引号字符集问题

**问题**：`dialogue_markers` 缺少中文弯引号 U+201C（`"`）和 U+201D（`"`）

**修复**（`auto_review_node.py` 中的 `_check_dialogue_ratio`）：

```python
# 原版（有问题）
dialogue_markers = ["「", "」", '"', '"', "'", "'", '"', "'"]

# 修复版（新增 Unicode 弯引号）
dialogue_markers = [
    "「", "」",           # 中文书名号式引号
    "\u201c", "\u201d",  # Unicode 左右弯双引号 " "
    "\u2018", "\u2019",  # Unicode 左右弯单引号 ' '
    '"', "'",             # ASCII 直引号（备用）
]
```

### Fix 2：章节名为空的问题

**问题**：`node_name` 来自 `story_path[node_index]`，v4.3 路径结构与旧 `story_path` 字段不同步

**修复方向**：在路径进度追踪的 `path_progress.paths_status` 中，
每条路径的 `path_name` 字段直接作为 tension_check 和 auto_review 的章节名来源，
不再依赖旧的 `story_path[node_index]`。

---

## 八、与各补丁文档的对照变更说明

| 补丁 | 变更状态 | 说明 |
|------|---------|------|
| 补丁F：write路径完整性铁律 | **覆盖修订** | "一次写完全部路径"改为"单路径单次write" |
| 补丁F：Scene Snapshot | **保持不变** | 依然从最后一条路径的正文中提取 |
| 补丁F：consistency_node重构 | **保持不变** | 但移除"路径完整性检验"（已由tension_check覆盖） |
| 补丁F：event_chain_gen第零步 | **保持不变** | Scene Snapshot 强制读取逻辑不变 |
| 补丁D：bible_update循环控制 | **扩展** | 新增路径进度追踪和单路径循环控制逻辑 |

---

## 九、设计决策记录

### 9.1 为什么单路径单write优于一次写完？

接缝感是可控的（注入上一路径末句），但漂移是不可控的。
超过3000字的单次生成中，模型局部逻辑漂移是必然发生的，
不是通过更好的提示词能根本解决的——这是LLM的注意力机制决定的。

宁可有轻微的接缝感，不能有"傀儡师变宋老三"这样的设定漂移。
接缝感读者可以接受，设定漂移是直接出戏的。

### 9.2 为什么tension_check要做题面对齐而非只做张力检验？

单路径write后，"当前路径的核心动作"是完全明确的，
校验标准从模糊的"张力是否足够"变成了精确的"这条路径要求的内容是否在正文中"。
精确的校验标准产生精确的校验结果，杜绝"文不对题仍然通过"的问题。

### 9.3 章节字数会增加吗？

不会整体增加，会更合理地分配：
- 原来：一次write压缩4条路径进3000-6000字（平均每条750-1500字）
- 现在：每条路径800-1500字，4条路径总计3200-6000字
总字数范围相同，但每条路径的字数不再被平均压缩，
高张力路径可以充分展开，喘息路径可以适当简短。

---

> **文档版本**：DeepNovel v4.3 补丁 G
> **核心修订**：write节点从"一次写完全部路径"改为"单路径单次write"
> **同步修复**：tension_check新增题面对齐硬拦截；对话检测引号字符集；章节名来源
> **核心原则**：
>   单路径单场景，模型注意力集中，漂移从根本上消除；
>   接缝感可以用上一路径末句解决，漂移不可以靠提示词解决；
>   精确的路径边界产生精确的校验标准。