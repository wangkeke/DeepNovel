# DeepNovel v4.3 · 补丁文档 H
## path_state_extract — 路径状态提取与上下文接力

> **文档定位**：本文档是对补丁G的关键补充，修复补丁G中
> "只传最后一句话导致路径间失忆"的致命陷阱。
> 新增轻量级 path_state_extract 节点，在每条路径写完后提取五维状态，
> 作为下一条路径write的上下文注入。
>
> 补丁G的其余内容（单路径单write架构、tension_check题面对齐、
> 对话检测fix等）保持不变，本文档只修订"路径间上下文传递"机制。

---

## 一、补丁G的致命陷阱

### 问题重现

```
路径3（磨坊分析）写完：
  中间段落：林北决定去找城南破庙的独臂傀儡师
  最后一句：林北翻过后窗，无声地跳进磨坊后面的草丛中

补丁G的传递方式：
  → 下一路径write只接收"最后一句话"
  → 即：林北翻过后窗，无声地跳进磨坊后面的草丛中

路径4的write看到的信息：
  ✓ 林北当前在草丛中
  ✗ 林北决定去找傀儡师（路径3中段，被丢弃）
  ✗ 身上有半颗辟谷丹（路径3道具记录，被丢弃）
  ✗ 距周五只有五个时辰（路径3紧张感，被丢弃）

结果：路径4写到需要找第三方时，模型凭空捏造"宋老三"
```

### 根本原因

"最后一句话"只能保证**物理接缝**，无法保证**语义连续**。
路径中间产生的所有关键事实——决策、道具、涌现实体、时间压力——
全部在路径切换时丢失，形成**路径间失忆（Inter-path Amnesia）**。

---

## 二、解决方案：path_state_extract 节点

### 定位

`path_state_extract` 是一个**轻量级的微观提取节点**，
专门为路径间的上下文接力服务。

它与 `narrative_extract`（宏观伏笔/词条提取）**完全不冲突**：

```
path_state_extract：
  触发时机：每条路径write完成后立即触发
  处理对象：单条路径的正文（800-1500字）
  提取目标：这条路径产生的、下一条路径必须知道的关键事实
  输出用途：注入下一条路径的write提示词（路径级接力）
  特点：轻量、快速、结构化

narrative_extract：
  触发时机：全部路径都完成后触发（整章完成）
  处理对象：全部路径的合并正文（完整章节）
  提取目标：伏笔、词条、章节叙事路径链（宏观沉淀）
  输出用途：注入bible_update（档案层沉淀）
  特点：全面、深度、面向全局
```

### 修订后的路径循环流程

```
path_gen → [路径1, 路径2, 路径3, 路径4]

↓ 路径1
write（路径1，无前文状态注入）
  ↓
path_state_extract（提取路径1的五维状态）
  ↓
tension_check（题面对齐校验路径1）
  ↓ 通过
bible_update（更新路径进度，存储路径1状态）

↓ 路径2
write（路径2，注入路径1的五维状态）
  ↓
path_state_extract（提取路径2的五维状态）
  ↓
tension_check（题面对齐校验路径2）
  ↓ 通过
bible_update（更新路径进度，存储路径2状态）

↓ 路径3（关键：注入路径2的五维状态，而不是最后一句话）
write（路径3，注入路径2的五维状态）
  ↓
...（依次循环）

↓ 所有路径完成
narrative_extract（读取全部路径合并正文，宏观提取）
  ↓
consistency_node
  ↓
bible_update（档案层沉淀）
```

---

## 三、path_state_extract 提示词

```
你是一个极为严谨的网文"场记"与"状态追踪员"。
请仔细阅读这段刚刚完成的小说正文，
沿着事件发展的时间线，像剥洋葱一样，
把剧情中【刚刚发生改变或确立的关键事实】提取出来。

你的提取必须服务于一个核心目标：
确保下一段写作的模型，不会因为看不到这段正文，
而凭空捏造或遗忘任何已经确立的设定。

请严格按照以下 JSON 格式输出，如果某一项没有发生变化，填"无"：

{
  "path_id": "当前路径的 path_id",

  "1_physical_state": {
    "end_location": "角色当前精确的物理位置（例：磨坊后院草丛中，距后窗约3步）",
    "end_posture_and_status": "角色最后的动作姿态与生理状态（例：蹲伏，左手捏着半颗丹药）",
    "last_sentence": "正文的最后一句话（原文照录，用于物理接缝）"
  },

  "2_inventory_delta": {
    "description": "道具/资源的消耗、获得或位置转移",
    "changes": [
      "消耗了半颗辟谷丹（原有一颗，现剩半颗）",
      "剩余半颗辟谷丹已藏入袖口夹层"
    ]
  },

  "3_emergent_entities": {
    "description": "正文中由作者自由发挥出来的具体人名/地名/法器名/势力名，下一段不能忘记或改变",
    "entities": [
      {
        "name": "独臂傀儡师",
        "type": "人物",
        "established_fact": "城南破庙的散修，每周五出现，是林北决定联系的第三方"
      },
      {
        "name": "城南破庙",
        "type": "地点",
        "established_fact": "独臂傀儡师的活动地点，是林北的下一个目标地"
      }
    ]
  },

  "4_character_decision": {
    "final_decision": "放弃与矮个子交易，前往城南破庙寻找独臂傀儡师",
    "decision_basis": "傀儡师能提供的信息价值高于矮个子，且风险更可控",
    "this_decision_drives_next_path": "下一段剧情必须以此决定为驱动，不得出现与此矛盾的行动"
  },

  "5_immediate_tension": {
    "urgency": "距周五傀儡师出现还有不到五个时辰",
    "active_threats": ["铁算盘势力可能正在附近搜查"],
    "atmosphere": "高度紧张，时间压力极大"
  }
}

⚠️ 特别注意 emergent_entities：
这是最容易被遗漏的关键信息。
正文中每出现一个具体的人名/地名/法器名，
无论是主要还是次要，都必须收录进来。
下一段的模型如果没有这个列表，就会现场捏造新名字，造成设定漂移。
```

---

## 四、write 节点的上下文注入格式

将 path_state_extract 的输出，转化为下一条路径write提示词的前文注入块：

```python
def build_path_relay_context(path_state: dict) -> str:
    """将五维状态转化为下一条路径的上下文注入"""

    physical = path_state.get("1_physical_state", {})
    inventory = path_state.get("2_inventory_delta", {})
    entities = path_state.get("3_emergent_entities", {})
    decision = path_state.get("4_character_decision", {})
    tension = path_state.get("5_immediate_tension", {})

    entity_lines = []
    for e in entities.get("entities", []):
        entity_lines.append(
            f"  · {e['name']}（{e['type']}）：{e['established_fact']}"
        )

    inventory_lines = [
        f"  · {c}" for c in inventory.get("changes", [])
    ]

    relay = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
【前文已确立的核心事实——必须完整继承，不得修改或遗忘】
━━━━━━━━━━━━━━━━━━━━━━━━━━━

【写作起点（物理接缝）】
主角当前位置：{physical.get('end_location', '未知')}
姿态与状态：{physical.get('end_posture_and_status', '未知')}
接缝句（从这句话的下一秒开始写，不要重复）：
"{physical.get('last_sentence', '')}"

【已确立的关键实体（严禁改名或替换）】
{chr(10).join(entity_lines) if entity_lines else '  · 无新增实体'}

【道具/资源变动（严格遵守，不得矛盾）】
{chr(10).join(inventory_lines) if inventory_lines else '  · 无变动'}

【主角的核心决策（驱动本段剧情的方向）】
{decision.get('final_decision', '无')}
⚠️ {decision.get('this_decision_drives_next_path', '')}

【当前紧张氛围（情绪气口）】
紧迫压力：{tension.get('urgency', '无')}
活跃威胁：{', '.join(tension.get('active_threats', ['无']))}
整体氛围：{tension.get('atmosphere', '无')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    return relay.strip()
```

在write节点的提示词构建中，将此接力块注入到路径定义之前：

```python
def build_write_prompt(path_def: dict, relay_context: str) -> str:
    prompt = ""
    if relay_context:  # 不是第一条路径时注入
        prompt += relay_context + "\n\n"
    prompt += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
当前路径信息
━━━━━━━━━━━━━━━━━━━━━━━━━━━
路径名称：{path_def['path_name']}
叙事功能：{path_def['narrative_function']}
...（其余路径信息）
"""
    return prompt
```

---

## 五、路径进度追踪的数据结构更新

在补丁G的 `path_progress` 基础上，新增 `path_state` 字段：

```json
"path_progress": {
  "current_event_id": "ev_1_001",
  "total_paths": 4,
  "paths_status": [
    {
      "path_id": "ev_1_001_p01",
      "path_name": "广场目击",
      "status": "completed",
      "path_state": {
        "1_physical_state": {
          "end_location": "广场东侧茶摊旁",
          "end_posture_and_status": "站立，手握令牌",
          "last_sentence": "他的目光落在那枚令牌上，停了三秒。"
        },
        "2_inventory_delta": {
          "changes": ["获得铁令牌一枚（从尸体处取得）"]
        },
        "3_emergent_entities": {
          "entities": [
            {
              "name": "铁算盘",
              "type": "势力/人物",
              "established_fact": "雇主背后的中间人，令牌持有者的上线"
            }
          ]
        },
        "4_character_decision": {
          "final_decision": "暂时保留令牌，利用信息差展开调查",
          "this_decision_drives_next_path": "下一段必须基于持有令牌这一事实推进"
        },
        "5_immediate_tension": {
          "urgency": "令牌持有者的死亡随时可能被发现",
          "active_threats": ["广场上还有其他人目击了事件"],
          "atmosphere": "表面平静，内部高度戒备"
        }
      }
    },
    {
      "path_id": "ev_1_001_p02",
      "path_name": "水渠深处的账本重算",
      "status": "in_progress",
      "path_state": null
    }
  ],
  "current_path_index": 1,
  "all_paths_text": "已完成路径的正文合集"
}
```

---

## 六、bible_update 路径循环控制的修订

在补丁G的路径循环控制基础上，新增状态传递：

```
每条路径写完并通过 tension_check 后：

1. path_state_extract 已经运行并产出五维状态 JSON
2. bible_update 执行：
   a. 将本路径正文追加到 path_progress.all_paths_text
   b. 将 path_state_extract 的输出存入本路径的 path_state 字段
   c. 更新本路径状态为 completed
   d. 检查是否还有 pending 路径：

   如果有：
     current_path_index += 1
     读取下一条路径的定义
     读取当前路径的 path_state（五维状态）
     调用 build_path_relay_context() 生成接力上下文
     路由到 write（注入接力上下文 + 下一路径定义）

   如果没有：
     读取 all_paths_text
     路由到 narrative_extract（整章宏观提取）
```

---

## 七、微观提取 vs 宏观提取的完整分工

```
┌─────────────────────────────────────────────────────────┐
│           微观层：路径间接力（path_state_extract）         │
├─────────────────────────────────────────────────────────┤
│ 触发时机  每条路径write完成后立即                          │
│ 处理对象  单条路径正文（800-1500字）                       │
│ 提取目标  五维状态（物理/道具/实体/决策/张力）              │
│ 输出用途  注入下一条路径的write（路径级接力）               │
│ 生命周期  路径循环内有效，路径循环结束后归档               │
└─────────────────────────────────────────────────────────┘
            ↓ 全部路径完成后触发
┌─────────────────────────────────────────────────────────┐
│           宏观层：档案沉淀（narrative_extract）            │
├─────────────────────────────────────────────────────────┤
│ 触发时机  全部路径完成后（整章完成）                       │
│ 处理对象  全部路径合并正文（完整章节）                     │
│ 提取目标  真正的伏笔/词条/章节叙事路径链                   │
│ 输出用途  注入bible_update（档案层沉淀）                   │
│ 生命周期  全书有效，持续积累                              │
└─────────────────────────────────────────────────────────┘
```

---

## 八、对比：补丁G vs 补丁H

```
信息传递方式对比：

补丁G（有陷阱）：
  路径3末句："林北翻过后窗，跳进草丛"
  路径4知道：林北在草丛
  路径4不知道：去找傀儡师、剩半颗丹药、距周五5小时
  结果：路径4现场捏造"宋老三"

补丁H（修复后）：
  路径3的五维状态：
    物理：草丛中，蹲伏
    道具：半颗辟谷丹在袖口
    实体：独臂傀儡师（城南破庙，周五）
    决策：去找傀儡师，不找矮个子
    张力：距周五5小时，铁算盘在附近
  路径4知道：全部上述信息
  结果：路径4自然地推进"找傀儡师"的剧情线
```

---

## 九、设计决策记录

### 9.1 为什么专门设一个 path_state_extract 而不是让 write 自己输出状态？

write 的职责是写好正文，输出结构化状态是另一种认知模式。
如果要求 write 同时输出高质量正文和精确的五维状态 JSON，
两种模式互相干扰——正文质量下降，状态提取也不精确。

专门的 path_state_extract 节点，让 AI 切换到"场记模式"，
读取已经写好的正文，专注于提取事实，而不是生成创意内容。
职责分离带来的是两边都更高质量。

### 9.2 为什么 emergent_entities 是最重要的维度？

从测试中发现：模型漂移最常见的形式是"涌现实体的名字被替换"。
"独臂傀儡师"变成"宋老三"，不是因为模型不知道要找第三方，
而是因为它在路径4看不到"独臂傀儡师"这个具体的名字，
只能现场捏造一个新的名字来填充"找第三方"这个情节槽。

专门为涌现实体设一个强制提取维度，并在注入时明确标注
"严禁改名或替换"，可以从根本上杜绝名字漂移问题。

### 9.3 这套机制的 token 消耗是否合理？

每条路径（800-1500字）额外触发一次轻量提取调用。
path_state_extract 的输入只有单条路径正文，输出是结构化 JSON，
估计每次额外消耗约500-800 token（主要是输出的 JSON）。

相比于因为漂移导致的路径重写（每次重写约2000-3000 token），
这个额外消耗是值得的。

---

## 十、与各补丁文档的对照变更说明

| 补丁 | 变更状态 | 说明 |
|------|---------|------|
| 补丁G：路径间传递"最后一句话" | **覆盖修订** | 改为传递五维状态JSON（path_state_extract输出） |
| 补丁G：其余内容 | **保持不变** | 单路径单write、tension_check题面对齐、对话检测fix均不变 |
| 补丁F：narrative_extract | **保持不变** | 触发时机和职责不变，只是现在由bible_update在所有路径完成后触发 |
| 补丁D：bible_update循环控制 | **扩展** | 新增path_state存储和接力上下文生成逻辑 |

---

> **文档版本**：DeepNovel v4.3 补丁 H
> **修复的核心问题**：路径间失忆（Inter-path Amnesia）
> **解决方案**：path_state_extract 五维状态提取 + 结构化接力注入
> **五个维度**：
>   物理状态（防止瞬移）
>   道具变动（防止道具吃书）
>   涌现实体（防止名字漂移，最关键）
>   核心决策（防止动机漂移）
>   即时张力（保留情绪气口）
> **与narrative_extract的分工**：
>   微观接力（路径级，路径间有效）vs 宏观沉淀（章节级，全书有效）