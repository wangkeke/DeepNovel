# DeepNovel 人物性格系统 — 补充实现文档

> Cursor 已整理的四个核心结论（顺序/冲击强度/冲击力类型/职责分工）不在此重复。
> 本文档只覆盖 Cursor 整理之外的三个部分：
> 1. 特质叠加的动态机制
> 2. expand1 的性格反应分析 Prompt
> 3. write 节点的注入方式和写作禁忌

---

## 一、特质叠加（trait_interactions）的动态机制

### 1.1 为什么要动态

人物卡建立时可以预设一部分叠加规则（天生的），但有些叠加模式是被故事经历塑造出来的，必须在故事推进中追加。

```
示例：
  林默第1节的急躁+隐忍：
    被压迫时急躁，但知道打不过所以隐忍
    → source: "preset"

  林默经历矿洞十个节点压迫后的急躁+隐忍：
    急躁已被压到很深的位置
    表面极度平静，但这种平静比任何愤怒都更危险
    → source: "learned"，learned_from_node: 10
```

### 1.2 数据结构

```python
class TraitInteraction(BaseModel):
    combo: list[str]          # 参与叠加的特质名
    condition: str            # 触发这个叠加的情境条件
    result: str               # 叠加后的实际反应
    reader_expectation: str   # 读者/其他人物预期看到什么
    actual: str               # 实际发生的（反差或超预期的部分）
    interaction_type: str     # "contrast" / "amplify" / "both"
    source: str               # "preset"（天生）/ "learned"（经历习得）
    learned_from_node: int    # source=learned时，从哪个节点开始形成
```

### 1.3 learned 叠加的触发时机

`bible_update` 在重大事件节点后检测：某个特质的触发方式是否发生了本质变化。

检测到变化时，在下一次 `human_review_write` 界面末尾提示：

```
╭──────────────────────────────────────────────╮
│ 📌 人物性格变化                               │
│                                              │
│ 「林默」经历了连续压迫                        │
│ 急躁+隐忍的叠加方式可能已发生变化             │
│                                              │
│ [Y] 确认并追加新的叠加记录                    │
│ [N] 暂时跳过                                 │
╰──────────────────────────────────────────────╯
```

用户确认后，模型根据已有节点记录自动生成新叠加规则草稿，用户修改确认后追加到 `trait_interactions`，不覆盖原有记录。

---

## 二、expand1 的性格反应分析 Prompt

在现有 expand1 的 Schema 里新增 `character_reaction_analysis` 字段：

```python
# prompts/creation/expand1.py
# 在 EXPAND1_OUTPUT_SCHEMA 里新增

"character_reaction_analysis": [
    {
        "character_name": "str - 人物名",
        "shock_intensity": "低/中/高/极端",
        "shock_reason": "str - 为什么是这个强度",
        "activated_traits": [
            {
                "name": "str - 特质名",
                "weight": "主导/次要/压制",
                "reason": "str - 当前情境下为什么是这个权重"
            }
        ],
        "interaction_hit": "str - 命中的叠加规则名，无则填'无'",
        "interaction_type": "contrast/amplify/both/none",
        "external_appearance": "str - 其他人物和读者会看到什么",
        "internal_reality": "str - 这个人物真实的状态是什么",
        "key_detail": "str - 用什么具体细节暗示内外的落差",
        "write_instruction": "str - write节点需要注意的具体写法"
    }
]
```

**Prompt 里对这个字段的说明：**

```
【性格反应分析】

对每个本节涉及的主要人物，基于其特质清单分析：

1. 本节事件对这个人物的冲击强度（低/中/高/极端）
   极端 = 命运转折，平时从未见过的反应
   高   = 重大危机，明显强化的反应
   中   = 普通冲突，一般程度的反应
   低   = 日常波动，小幅反应

2. 激活了哪些特质，各自权重如何
   主导 = 当前情境下这个特质权重最高，决定行为方向
   次要 = 被激活但被主导特质覆盖
   压制 = 通常会激活但在此情境下被抑制

3. 是否命中 trait_interactions 里的叠加规则
   如果命中，直接使用已有规则的 reader_expectation 和 actual
   如果未命中，根据当前权重博弈推演新的叠加结果

4. 输出具体行为预测（这是给 write 节点的执行指令）
   外部表现：其他人物和读者会看到的行为
   内部实际：这个人物真实的状态（可以与外部表现完全相反）
   关键细节：用一个具体的小细节暗示内外落差
   执行要求：write 节点如何把这个反差写出来而不用直接说破
```

---

## 三、write 节点的注入方式和写作禁忌

### 3.1 注入内容变更

```
改前：注入原始 traits 清单（特质标签）
改后：注入 expand1 输出的 character_reaction_analysis（行为预测）

注入格式：
  {character_name}在本节的行为预测：
    外部表现：{external_appearance}
    内部实际：{internal_reality}
    关键细节：{key_detail}
    执行要求：{write_instruction}

外貌只在该人物首次出场的节点注入，后续节点不重复注入。
```

### 3.2 写作禁忌（写入 WRITE_SYSTEM）

```
【人物表现禁忌】

禁止直接说出情绪：
  ❌ "他感到非常愤怒"
  ❌ "她很难过"
  ❌ "他的急躁本性显露了出来"
  ✅ 通过行为表现：他摔了什么/说了什么/或者什么都没说

禁止直接说出动机：
  ❌ "他这样做是因为他凉薄"
  ❌ "出于好胜心，他决定..."
  ✅ 让行为本身传达动机，不做解释

禁止快速化解冲突：
  冲突场景结束时，至少有一方的处境比开始时更糟
  或者表面和解但内部矛盾更深
  冲突不需要在同一节点内解决

人物性格通过行为积累呈现，不通过描述呈现。
读者应该从五个节点的行为里感受到这个人是什么性格，
而不是从作者的一句"他是个急性子"里得知。
```

---

## 四、需要修改的文件（仅补充部分）

| 文件 | 改动内容 |
|---|---|
| `schemas/entity.py` | CharacterTrait 新增 TraitInteraction，增加 source 和 learned_from_node 字段 |
| `prompts/creation/expand1.py` | EXPAND1_OUTPUT_SCHEMA 新增 character_reaction_analysis 字段，Prompt 新增性格反应分析说明 |
| `prompts/creation/write.py` | WRITE_SYSTEM 新增写作禁忌，注入内容从 traits 改为 character_reaction_analysis |
| `graph/creation/nodes/expand1_node.py` | 加载涉及人物的 traits 和 trait_interactions，输出 character_reaction_analysis |
| `graph/creation/nodes/write_node.py` | 注入 expand1 的行为预测而非原始 traits |
| `graph/creation/nodes/bible_update_node.py` | 新增 learned 叠加规则变化检测逻辑 |
| `graph/creation/nodes/human_review_write_node.py` | 新增 learned 叠加规则更新的确认提示 |

---

*DeepNovel 人物性格系统补充文档 v1.0*
