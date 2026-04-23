# DeepNovel 用户意见处理 — Cursor 修复文档

> 修复所有接收用户修改意见的节点，确保确定性信息不丢失，方向性信息被正确转化。

---

## 一、问题说明

当前所有节点对用户修改意见的处理方式是"提取关键词套模板"，导致：
- 用户明确给出的具体经历、关系、情感基调被替换成通用套路
- 用户作为逻辑描述用的占位符名字（如"张三"）被当成真实角色名写进小说

---

## 二、通用处理规则（新增 Prompt 片段）

### 2.1 新建 `prompts/common/feedback_handling.py`

```python
# prompts/common/feedback_handling.py

USER_FEEDBACK_HANDLING = """
## 处理用户修改意见

用户意见：
{user_feedback}

在开始生成之前，先完成以下两步分析：

【第一步：提取确定性信息（必须在输出中保留）】

必须保留的内容：
  • 具体经历（如：盗墓出身、坐牢20年、父母离世、兄弟散亡）
  • 明确的人物关系（如：兄弟、父母、哥哥姐姐）
  • 核心动机（如：带兄弟走正道、弥补遗憾、为某人复仇）
  • 情感基调（如：忏悔、救赎、愤怒、执念）
  • 明确的时间跨度或关键事件节点

可以由模型自由处理的内容：
  • 人物名字
    用户意见里出现的名字往往是占位符（如"张三""李四"）
    模型应根据题材和风格重新命名，不照搬用户的占位符
    例外：如果用户在之前的交互中已确认了某个名字，则保留
  • 具体场景细节（用户给方向，模型负责细节）
  • 对话内容（用户描述的逻辑，模型转化成具体对话）

【第二步：理解方向性信息（需要创作转化）】

用户意见里可能包含逻辑思路或情节方向，例如：
  "主角被人陷害，在关键时刻反败为胜"
  → 这是逻辑方向，不是具体情节
  → 保留"被陷害→反败为胜"的逻辑
  → 由模型设计具体的陷害方式、反转手段、场景

【禁止事项】
  ✗ 用题材通用模板替换用户的具体描述
  ✗ 忽略用户明确提到的任何经历、关系或动机
  ✗ 把用户的具体故事"升华"成另一个套路
  ✗ 照搬用户意见中的占位符名字作为正式角色名
"""
```

---

## 三、需要修改的节点文件

### 3.1 `prompts/creation/synopsis.py`

**修改位置：** `SYNOPSIS_USER_TEMPLATE`

在模板开头，`{user_feedback_section}` 占位符处替换为完整的反馈处理段落。

**修改前（找到类似这样的代码）：**
```python
SYNOPSIS_USER_TEMPLATE = """
...
{user_feedback_section}
...
"""

# 调用时
user_feedback_section = f"## 用户修改意见\n{feedback}" if feedback else ""
```

**修改后：**
```python
from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING

SYNOPSIS_USER_TEMPLATE = """
## 用户需求
题材：{genre_request}

## 骨骼参考（{weight_description}）
...（原有内容不变）...

{feedback_section}
"""

# 调用时（在 synopsis_node.py 里）
if feedback:
    feedback_section = USER_FEEDBACK_HANDLING.format(user_feedback=feedback)
else:
    feedback_section = ""
```

---

### 3.2 `prompts/creation/path_gen.py`

**修改位置：** `PATH_GEN_USER_TEMPLATE`

**修改方式：** 和 synopsis 完全相同，找到处理 `path_feedback` 的地方替换：

```python
from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING

# 在 path_gen_node.py 构造 user_prompt 时
if path_feedback:
    feedback_section = USER_FEEDBACK_HANDLING.format(
        user_feedback=path_feedback
    )
    user_prompt += f"\n\n{feedback_section}"
```

---

### 3.3 `graph/creation/nodes/expand1_node.py`

**修改位置：** 处理 `rewrite_feedback` 的地方

```python
from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING

# 在构造 expand1 的 user_prompt 时
rewrite_feedback = state.get("bible", {}).get("rewrite_feedback", "")
if rewrite_feedback:
    feedback_section = USER_FEEDBACK_HANDLING.format(
        user_feedback=rewrite_feedback
    )
    user_prompt = feedback_section + "\n\n" + user_prompt
    # 放在最前面，让模型先处理用户意见再看其他内容
```

---

### 3.4 `graph/creation/nodes/human_review_write_node.py`

**修改位置：** 用户选择重写时收集修改意见的地方

在收集到用户输入后，对意见做一次**前置解析**，把确定性信息提取出来存入 bible，
供 expand1 使用：

```python
from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING
from utils.llm import call_llm_json

async def parse_user_feedback(feedback: str) -> dict:
    """
    对用户修改意见做前置解析，提取确定性信息和方向性信息。
    结果存入 bible.rewrite_feedback_parsed，供 expand1 使用。
    """
    if not feedback.strip():
        return {"confirmed_facts": [], "direction": feedback}

    result = await call_llm_json(
        system=(
            "你是一个小说编辑助手。"
            "分析用户的修改意见，区分必须保留的事实和需要创作转化的方向。"
            "只返回 JSON，不加任何前言。"
        ),
        user=f"""
用户修改意见：
{feedback}

请提取：
1. confirmed_facts：用户明确说出的、必须在小说中体现的具体事实
   （经历、关系、动机、情感基调等，不包括人物名字）
2. direction：用户想要的逻辑方向或情节走向（一句话概括）
3. placeholder_names：意见中出现的、明显是占位符的名字
   （如张三、李四、某人等，这些名字不应直接用在小说里）

返回 JSON：
{{
  "confirmed_facts": ["事实1", "事实2"],
  "direction": "方向描述",
  "placeholder_names": ["张三"]
}}
"""
    )
    return result

# 在用户选择重写后
feedback = input("请输入修改意见：").strip()
if feedback:
    parsed = await parse_user_feedback(feedback)
    return Command(
        update={
            "rewrite_count": 0,
            "bible": {
                **state.get("bible", {}),
                "rewrite_feedback": feedback,
                "rewrite_feedback_parsed": parsed,  # ★ 新增解析结果
            },
        },
        goto="expand1",
    )
```

---

### 3.5 `graph/creation/nodes/expand1_node.py`（补充）

在构造 Prompt 时，如果有解析结果，优先使用解析结果而不是原始意见：

```python
parsed = state.get("bible", {}).get("rewrite_feedback_parsed", {})
raw_feedback = state.get("bible", {}).get("rewrite_feedback", "")

if parsed and parsed.get("confirmed_facts"):
    # 有解析结果，用结构化的方式注入
    facts_text = "\n".join(f"  • {f}" for f in parsed["confirmed_facts"])
    direction_text = parsed.get("direction", "")

    feedback_instruction = f"""
## 用户修改要求

必须在本节中体现的确定事实：
{facts_text}

用户希望的方向：
{direction_text}

注意：用户意见中出现的以下名字是占位符，不要直接用在小说里：
{', '.join(parsed.get('placeholder_names', [])) or '无'}
"""
elif raw_feedback:
    # 没有解析结果，用通用处理规则
    from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING
    feedback_instruction = USER_FEEDBACK_HANDLING.format(
        user_feedback=raw_feedback
    )
else:
    feedback_instruction = ""

# 把 feedback_instruction 注入 user_prompt 最前面
user_prompt = feedback_instruction + "\n\n" + user_prompt
```

---

### 3.6 `graph/creation/nodes/synopsis_node.py`

**修改位置：** 构造 user_prompt 的地方

找到处理 `user_feedback` 的代码，替换为使用 `USER_FEEDBACK_HANDLING`：

```python
from prompts.common.feedback_handling import USER_FEEDBACK_HANDLING

feedback = synopsis.get("user_feedback", "")
if feedback:
    feedback_section = USER_FEEDBACK_HANDLING.format(user_feedback=feedback)
else:
    feedback_section = ""

user_prompt = SYNOPSIS_USER_TEMPLATE.format(
    ...
    feedback_section=feedback_section,
    ...
)
```

---

## 四、新建文件

```
prompts/
  common/
    __init__.py          （空文件）
    feedback_handling.py （见第二章）
```

---

## 五、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `prompts/common/__init__.py` | 新建，空文件 |
| `prompts/common/feedback_handling.py` | 新建，通用 Prompt 片段 |
| `prompts/creation/synopsis.py` | 替换 user_feedback_section 为 USER_FEEDBACK_HANDLING |
| `prompts/creation/path_gen.py` | 同上，处理 path_feedback |
| `graph/creation/nodes/synopsis_node.py` | 注入时使用 USER_FEEDBACK_HANDLING |
| `graph/creation/nodes/path_gen_node.py` | 同上 |
| `graph/creation/nodes/expand1_node.py` | 优先使用解析结果，fallback 用 USER_FEEDBACK_HANDLING |
| `graph/creation/nodes/human_review_write_node.py` | 新增 parse_user_feedback 函数，收集意见时做前置解析 |

**不需要修改：** write_node、bible_update、consistency、所有提取流节点。

---

## 六、修复效果验证

修复后，对任意用户修改意见，`parse_user_feedback` 应该能正确拆解出：

```
confirmed_facts：用户明确说出的经历、关系、动机、情感基调
direction：用户想要的逻辑方向（一句话）
placeholder_names：意见中出现的占位符名字（如张三、某人、李四等）
```

**验证方法：**

在 `human_review_write_node` 收到用户意见后，打印 `parse_user_feedback` 的返回结果：

```python
parsed = await parse_user_feedback(feedback)
print("[调试] 意见解析结果：")
print(f"  确定性信息：{parsed.get('confirmed_facts', [])}")
print(f"  方向：{parsed.get('direction', '')}")
print(f"  占位符名字：{parsed.get('placeholder_names', [])}")
```

**检查标准：**

1. `confirmed_facts` 是否完整覆盖了用户意见里所有明确的事实
   如有遗漏 → 调整 `parse_user_feedback` 的 Prompt

2. `placeholder_names` 是否正确识别了非正式角色名
   如误判了真实角色名 → 调整 Prompt 里的识别规则

3. 最终生成的内容是否体现了 `confirmed_facts` 里的所有条目
   如有丢失 → 检查 `expand1_node` 的注入逻辑是否正确

---

*DeepNovel 用户意见处理修复文档 v1.0*
