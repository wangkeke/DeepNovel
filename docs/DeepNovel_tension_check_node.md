# DeepNovel tension_check_node — Cursor 执行文档

> 在 write 和 bible_update 之间插入轻量张力检查节点。
> 原则：宽松通过，只拦截明显错误，最多重试1次。
> 细节不足不触发重写，只有明显影响阅读体验的错误才触发。

---

## 一、节点位置

```
write → tension_check → bible_update
              ↓ passed=false（severity=major）
            write（带精确修改意见，最多重试1次）
              ↓ 重试后无论结果
            bible_update（强制通过，宁可放过不误杀）
```

---

## 二、新建 `graph/creation/nodes/tension_check_node.py`

```python
"""
tension_check_node：轻量张力检查节点

检查原则：
  - 宽松通过，只拦截明显错误
  - 细节不足不触发重写
  - 最多重试1次，重试后强制通过
  - 只检查三项明显错误：
      1. 推波助澜场景缺少具体行为载体（只写了"他沉默了"）
      2. 代价描写只有抽象总结（找不到具体损失）
      3. 反转节点完全没有铺垫

位置：write → tension_check → bible_update
"""
from __future__ import annotations
import logging
from langgraph.types import Command
from schemas.state import CreationState
from utils.llm import call_llm_json

logger = logging.getLogger("deepnovel.tension_check")

MAX_TENSION_RETRY = 1  # 最多重试1次，之后强制通过


async def tension_check_node(state: CreationState) -> Command:
    draft           = state.get("current_draft", "")
    tension_analysis = state.get("current_expand1", {}).get(
        "tension_analysis", {}
    )
    tension_retry   = state.get("tension_retry_count", 0)
    node_index      = state.get("current_node_index", 0)
    story_path      = state.get("story_path", [])
    node_name       = story_path[node_index].get("node_name", "") \
                      if node_index < len(story_path) else ""

    # 超过重试次数，强制通过
    if tension_retry >= MAX_TENSION_RETRY:
        logger.info(f"[张力检查] 「{node_name}」已重试{tension_retry}次，强制通过")
        return Command(
            update={"tension_retry_count": 0},
            goto="bible_update",
        )

    # 没有张力分析数据，跳过检查
    if not tension_analysis:
        logger.info(f"[张力检查] 「{node_name}」无张力分析数据，跳过")
        return Command(
            update={"tension_retry_count": 0},
            goto="bible_update",
        )

    result = await _check_tension(draft, tension_analysis, node_name)

    if result.get("passed", True):
        logger.info(f"[张力检查] 「{node_name}」通过")
        return Command(
            update={"tension_retry_count": 0},
            goto="bible_update",
        )

    # 有明显错误，触发重写
    issues = result.get("issues", [])
    issue_text = "；".join(issues)
    logger.info(f"[张力检查] 「{node_name}」发现明显错误：{issue_text}")

    return Command(
        update={
            "tension_retry_count": tension_retry + 1,
            "bible": {
                **state.get("bible", {}),
                "rewrite_feedback": _build_rewrite_instruction(
                    issues, tension_analysis
                ),
            },
        },
        goto="write",
    )


async def _check_tension(
    draft: str,
    tension_analysis: dict,
    node_name: str,
) -> dict:
    """
    一次轻量 LLM 调用，只检查三项明显错误。
    只看正文前800字，不全量检查。
    """
    tension_type      = tension_analysis.get("primary_tension", "")
    tension_execution = tension_analysis.get("tension_execution", "")
    info_map          = tension_analysis.get("information_map", [])

    # 提取推波助澜者信息（如有）
    manipulators = [
        p for p in info_map
        if p.get("utilizes_or_hides") or p.get("purpose")
    ]
    manipulator_desc = ""
    if manipulators:
        manipulator_desc = "；".join(
            f"{p['character']}（在利用：{p.get('utilizes_or_hides', '')}）"
            for p in manipulators
        )

    result = await call_llm_json(
        system="""
你是一个网文编辑，正在做快速质检。
只检查最明显的张力落实问题，不挑剔细节。
宁可放过细节不足，也不误判正常内容。
只有严重影响阅读体验的明显错误才返回 passed=false。
只返回 JSON，不加任何前言。
""",
        user=f"""
## 本节张力设计
主要张力形式：{tension_type}
执行方案：{tension_execution}
推波助澜者（如有）：{manipulator_desc or "无"}

## 正文（前800字）
{draft[:800]}

## 检查任务

只检查以下三项，其他问题不管：

检查项1（仅当有推波助澜者时检查）：
  推波助澜者在正文里是否有具体的行为描写？
  （动作/话语/表情/反应，任意一种即可）
  违规标准：只写了"他沉默了"/"他没有说话"，完全没有行为载体

检查项2（仅当本节有代价时检查）：
  正文里是否有具体可见的损失描写？
  （人员/物品/关系/机会的具体损失）
  违规标准：只有抽象总结如"付出了代价"，找不到任何具体损失

检查项3（仅当本节有反转时检查）：
  反转揭露之前，正文里是否存在任何铺垫细节？
  违规标准：反转完全凭空出现，之前毫无暗示

注意：
  如果该项的触发条件不满足（如没有推波助澜者），该项直接跳过
  细节不够精彩不算违规，只有完全缺失才算违规

返回 JSON：
{{
  "passed": true 或 false,
  "issues": ["问题描述（精确到哪个检查项、具体缺什么）"],
  "severity": "minor"（细节不足，直接通过）或 "major"（明显缺失，需修）
}}

再次强调：只有 severity=major 时才返回 passed=false。
""",
    )

    # 二次校验：确保只有 major 才触发
    if result.get("severity") != "major":
        result["passed"] = True

    return result


def _build_rewrite_instruction(issues: list, tension_analysis: dict) -> str:
    """
    根据具体问题生成精确的重写指令。
    不是模糊的"请改进张力"，而是具体到哪一段缺什么。
    """
    lines = ["【张力检查发现以下问题，重写时请针对性修复】\n"]

    for issue in issues:
        lines.append(f"• {issue}")

    # 附上 expand2 的设计方案作为参考
    expand2_design = tension_analysis.get("tension_execution", "")
    if expand2_design:
        lines.append(f"\n参考场景设计方案：\n{expand2_design}")

    lines.append("\n注意：只修复以上问题，其他内容保持不变。")
    return "\n".join(lines)
```

---

## 三、`schemas/state.py` 新增字段

```python
class CreationState(TypedDict):
    # 原有字段不变...

    # ★ 新增
    tension_retry_count: int  # 张力检查的重试次数，通过后重置为 0
```

---

## 四、`graph/creation/graph.py` 修改

### 4.1 注册新节点

```python
from graph.creation.nodes.tension_check_node import tension_check_node

builder.add_node("tension_check", tension_check_node)
```

### 4.2 修改边

```python
# 改前：write → bible_update（或 human_review_write）
# 改后：write → tension_check → bible_update（或 human_review_write）

# 人工模式：
builder.add_edge("write", "tension_check")

# tension_check 的出边
builder.add_conditional_edges(
    "tension_check",
    lambda state: (
        "write"        if state.get("tension_retry_count", 0) > 0
                          and not state.get("tension_passed", True)
        else "human_review_write"
             if not state.get("auto_mode")
        else "bible_update"
    ),
    {
        "write":               "write",
        "human_review_write":  "human_review_write",
        "bible_update":        "bible_update",
    },
)
```

---

## 五、`graph/creation/nodes/human_review_write_node.py` 微调

在展示正文给用户之前，如果 `tension_check` 发现了 minor 问题（通过了但有轻微不足），在界面上附加提示，供用户参考：

```python
# 在展示正文预览之后，判断是否有 minor 问题
tension_issues = state.get("tension_minor_issues", [])
if tension_issues:
    console.print(
        Panel(
            "\n".join(f"  • {i}" for i in tension_issues),
            title="💡 张力参考提示（不影响保存，仅供参考）",
            border_style="dim",
            expand=False,
        )
    )
```

同时在 `tension_check_node` 里，把 minor 问题也存入 state：

```python
# tension_check_node 里，即使 passed=true，也把 minor 问题存起来
minor_issues = result.get("issues", []) if result.get("severity") == "minor" else []
return Command(
    update={
        "tension_retry_count":  0,
        "tension_minor_issues": minor_issues,  # 供 human_review 展示
    },
    goto="bible_update",
)
```

---

## 六、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `graph/creation/nodes/tension_check_node.py` | 新建，完整实现见第二章 |
| `schemas/state.py` | 新增 tension_retry_count、tension_minor_issues |
| `graph/creation/graph.py` | 注册节点；write 改为先连 tension_check；tension_check 的出边逻辑 |
| `graph/creation/nodes/human_review_write_node.py` | 展示 minor 问题作为参考提示 |

**不需要修改：** write_node、expand 节点、bible_update、path_gen、所有提取流节点。

---

*DeepNovel tension_check_node 实现文档 v1.0*
