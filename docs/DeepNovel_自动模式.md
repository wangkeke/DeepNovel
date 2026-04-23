# DeepNovel 自动模式 — Cursor 执行文档

> 本文档只描述自动模式相关的改造，不涉及已有的人工模式逻辑。
> 核心设计：用 auto_review_node 替代所有人工确认节点，
> 内部根据 review_type 走不同的判断逻辑，自己生成修改意见继续推进，
> 连续2次仍不通过才通知用户介入。

---

## 一、触发时机

自动模式在宏观构思确认之后、路径规划之前启动。
世界设定、主角人物卡、宏观构思三个节点无论什么模式都必须人工确认。

```
世界设定确认 → 人工（不变）
主角人物卡确认 → 人工（不变）
宏观构思确认 → 人工（不变）
    ↓
在 human_review_synopsis_node 批准后，询问创作模式：
  [1] 人工模式（每个节点都需要确认）
  [2] 自动模式（全自动推进，方向问题时自动修正）
      → 输入最大章节数（如：50）
    ↓
路径规划之后的所有确认节点由 auto_review_node 接管
```

---

## 二、State 新增字段（`schemas/state.py`）

```python
class CreationState(TypedDict):
    # 原有字段不变...

    # 自动模式相关
    auto_mode:        bool   # 是否自动模式，默认 False
    max_chapters:     int    # 最大章节数，0=不限制
    auto_retry_count: int    # 当前节点自动重试次数，通过后重置为 0
    pending_review_type: str # 当前待审核的类型：'path'/'write'/'batch'
```

---

## 三、数据库变更（`memory/schema.sql`）

```sql
-- novel_projects 表新增字段
ALTER TABLE novel_projects ADD COLUMN auto_mode INTEGER DEFAULT 0;
ALTER TABLE novel_projects ADD COLUMN max_chapters INTEGER DEFAULT 0;
```

---

## 四、新增节点（`graph/creation/nodes/auto_review_node.py`）

```python
"""
auto_review_node：自动模式下替代所有人工确认节点。

替代范围：
  human_review_path  → review_type='path'
  human_review_write → review_type='write'
  human_review_batch → review_type='batch'

判断分级：
  直接通过（不调用 LLM）：
    - batch 类型且未达 max_chapters → 直接继续下一批
    - batch 类型且达到 max_chapters → 直接结束

  LLM 判断（方向性决策）：
    - path：路径是否符合 synopsis 的核心冲突和走向
    - write：正文是否与事件路径链吻合 + 是否有明显人物行为矛盾

异常处理：
  LLM 判断不通过 → 自动生成修改意见继续推进
  连续2次不通过 → 通知用户介入，临时切回人工确认
"""
from __future__ import annotations
from langgraph.types import Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from memory.db import (
    get_entity_cards_by_names,
    get_pending_foreshadows,
    load_chapters_count,
    get_project_max_chapters,
)
import logging

logger = logging.getLogger("deepnovel.auto_review")

MAX_AUTO_RETRY = 2


async def auto_review_node(state: CreationState) -> Command:
    review_type = state.get("pending_review_type", "")
    retry_count = state.get("auto_retry_count", 0)

    if review_type == "path":
        return await _review_path(state, retry_count)
    elif review_type == "write":
        return await _review_write(state, retry_count)
    elif review_type == "batch":
        return await _review_batch(state)
    else:
        logger.warning(f"未知的 review_type: {review_type}，直接通过")
        return _direct_pass(state, review_type)


# ── 路径确认 ────────────────────────────────────────────────────────────────

async def _review_path(state: CreationState, retry_count: int) -> Command:
    """
    判断这批路径是否符合整体故事方向。
    数据来源：State（synopsis + story_path）
    """
    synopsis   = state.get("synopsis", {})
    story_path = state.get("story_path", [])

    result = await call_llm_json(
        system="""
你是一个有经验的网文编辑，正在审核一批故事节点路径。
判断这批路径是否符合整体故事方向，给出明确的决策。
只返回 JSON，不加任何前言。
""",
        user=f"""
## 整体故事方向
标题：{synopsis.get('title', '')}
核心冲突：{synopsis.get('core_conflict', '')}
走向：{synopsis.get('direction', '')}

## 待确认的路径（共 {len(story_path)} 个节点）
{_format_path(story_path)}

判断：
1. 这批节点的整体方向是否符合核心冲突和故事走向？
2. 节点之间是否有明显的逻辑断层？

返回 JSON：
{{
  "decision": "approve" 或 "revise",
  "reason": "判断依据（一句话）",
  "revision_suggestion": "如果 revise，具体修改建议"
}}
"""
    )

    if result.get("decision") == "approve":
        logger.info(f"[自动] 路径确认通过：{result.get('reason', '')}")
        return Command(
            update={
                "path_approved":      True,
                "current_node_index": 0,
                "auto_retry_count":   0,
                "pending_review_type": "",
            },
            goto="expand1",
        )

    else:
        logger.info(f"[自动] 路径需修改：{result.get('reason', '')}")

        if retry_count >= MAX_AUTO_RETRY:
            # 超过重试次数，通知用户介入
            logger.warning("[自动] 路径连续修改失败，切回人工确认")
            return _fallback_to_human(state, "path", result.get("reason", ""))

        return Command(
            update={
                "path_approved":   False,
                "auto_retry_count": retry_count + 1,
                "synopsis": {
                    **state.get("synopsis", {}),
                    "path_feedback": result.get("revision_suggestion", ""),
                },
            },
            goto="path_gen",
        )


# ── 章节确认 ────────────────────────────────────────────────────────────────

async def _review_write(state: CreationState, retry_count: int) -> Command:
    """
    判断正文质量：
      1. 正文是否与事件路径链基本吻合
      2. 是否出现明显的人物行为矛盾
    数据来源：State + 数据库（entity_cards）
    """
    project_id  = state.get("project_id", "")
    draft       = state.get("current_draft", "")
    expand1     = state.get("current_expand1", {})
    node_index  = state.get("current_node_index", 0)
    story_path  = state.get("story_path", [])
    node_name   = story_path[node_index].get("node_name", "") if node_index < len(story_path) else ""

    # 取事件路径链
    event_path_chain = expand1.get("event_path_chain", [])

    # 查涉及人物的行为倾向
    involved_chars = _extract_character_names(draft, state)
    char_cards     = await get_entity_cards_by_names(project_id, involved_chars)

    result = await call_llm_json(
        system="""
你是一个网文编辑，正在审核一个章节的正文质量。
重点检查方向性问题，不挑剔文笔。
只返回 JSON，不加任何前言。
""",
        user=f"""
## 本节事件路径链（预期发生的事）
{chr(10).join(f"{i+1}. {e}" for i, e in enumerate(event_path_chain))}

## 涉及人物的行为倾向
{_format_char_cards(char_cards)}

## 正文（前500字）
{draft[:500]}

判断以下两点：
1. 正文的情节走向是否与事件路径链基本吻合？
2. 人物的行为是否与其行为倾向明显矛盾？

返回 JSON：
{{
  "decision": "approve" 或 "revise",
  "reason": "判断依据（一句话）",
  "revision_suggestion": "如果 revise，具体修改建议"
}}
"""
    )

    if result.get("decision") == "approve":
        logger.info(f"[自动] 章节「{node_name}」确认通过")
        return Command(
            update={
                "auto_retry_count":   0,
                "pending_review_type": "",
            },
            goto="bible_update",
        )

    else:
        logger.info(f"[自动] 章节「{node_name}」需修改：{result.get('reason', '')}")

        if retry_count >= MAX_AUTO_RETRY:
            logger.warning(f"[自动] 章节「{node_name}」连续修改失败，切回人工确认")
            return _fallback_to_human(state, "write", result.get("reason", ""))

        return Command(
            update={
                "auto_retry_count": retry_count + 1,
                "bible": {
                    **state.get("bible", {}),
                    "rewrite_feedback": result.get("revision_suggestion", ""),
                },
            },
            goto="expand1",
        )


# ── 批次确认 ────────────────────────────────────────────────────────────────

async def _review_batch(state: CreationState) -> Command:
    """
    批次完成后的自动决策。
    直接通过，不调用 LLM。
    数据来源：数据库（chapters 数量 + max_chapters 配置）
    """
    project_id   = state.get("project_id", "")
    completed    = await load_chapters_count(project_id)
    max_chapters = state.get("max_chapters", 0) or await get_project_max_chapters(project_id)

    if max_chapters > 0 and completed >= max_chapters:
        logger.info(f"[自动] 已完成 {completed} 章，达到上限 {max_chapters}，结束创作")
        return Command(
            update={"creation_complete": True, "pending_review_type": ""},
            goto="__end__",
        )

    logger.info(f"[自动] 已完成 {completed} 章，继续规划下一批")
    return Command(
        update={
            "story_path":          [],
            "path_approved":       False,
            "current_node_index":  0,
            "creation_complete":   False,
            "pending_review_type": "",
        },
        goto="path_gen",
    )


# ── 降级回人工 ──────────────────────────────────────────────────────────────

def _fallback_to_human(
    state: CreationState,
    review_type: str,
    reason: str,
) -> Command:
    """
    连续自动修改失败，通知用户介入。
    临时切回对应的人工确认节点。
    """
    from rich.console import Console
    console = Console()
    console.print(
        f"\n[yellow]⚠[/yellow]  自动模式无法解决当前问题，需要您介入\n"
        f"  问题：{reason}\n"
        f"  请手动处理后继续。"
    )

    goto_map = {
        "path":  "human_review_path",
        "write": "human_review_write",
        "batch": "human_review_batch",
    }

    return Command(
        update={
            "auto_retry_count":    0,
            "pending_review_type": review_type,
        },
        goto=goto_map.get(review_type, "human_review_path"),
    )


def _direct_pass(state: CreationState, review_type: str) -> Command:
    return Command(
        update={"pending_review_type": ""},
        goto="expand1",
    )


# ── 辅助函数 ────────────────────────────────────────────────────────────────

def _format_path(story_path: list) -> str:
    return "\n".join(
        f"{i+1}. {n.get('node_name', '')}：{n.get('one_liner', '')}"
        for i, n in enumerate(story_path)
    )


def _format_char_cards(cards: list) -> str:
    if not cards:
        return "无"
    lines = []
    for c in cards:
        traits = c.get("traits_display", [])
        lines.append(
            f"{c.get('standard_name', '')}：\n" +
            "\n".join(f"  • {t}" for t in traits[:3])  # 只取前3条，控制长度
        )
    return "\n".join(lines)


def _extract_character_names(draft: str, state: dict) -> list[str]:
    """从正文中提取出现的人物名（简单实现：从人物卡列表里匹配）"""
    all_names = [
        c.get("standard_name", "")
        for c in state.get("character_cards", [])
        if c.get("standard_name")
    ]
    return [name for name in all_names if name in draft]
```

---

## 五、图结构修改（`graph/creation/graph.py`）

### 5.1 注册新节点

```python
from graph.creation.nodes.auto_review_node import auto_review_node

builder.add_node("auto_review", auto_review_node)
```

### 5.2 新增路由函数

```python
def route_review(state: CreationState) -> str:
    """根据模式决定走人工确认还是自动确认"""
    if state.get("auto_mode"):
        return "auto_review"
    review_type = state.get("pending_review_type", "")
    return {
        "path":  "human_review_path",
        "write": "human_review_write",
        "batch": "human_review_batch",
    }.get(review_type, "human_review_path")
```

### 5.3 修改相关边

在 `path_gen`、`write`、`update_weight` 节点完成后，不再直接连接到对应的 human_review 节点，而是先经过路由：

```python
# path_gen 完成后
builder.add_conditional_edges(
    "path_gen",
    lambda state: route_review({**state, "pending_review_type": "path"}),
    {
        "human_review_path": "human_review_path",
        "auto_review":       "auto_review",
    },
)

# write 完成后
builder.add_conditional_edges(
    "write",
    lambda state: route_review({**state, "pending_review_type": "write"}),
    {
        "human_review_write": "human_review_write",
        "auto_review":        "auto_review",
    },
)

# update_weight 完成后（批次审核）
builder.add_conditional_edges(
    "update_weight",
    lambda state: (
        route_review({**state, "pending_review_type": "batch"})
        if state.get("auto_mode") and _is_batch_done(state)
        else check_creation_done(state)
    ),
    {
        "human_review_batch": "human_review_batch",
        "auto_review":        "auto_review",
        "expand1":            "expand1",
    },
)
```

---

## 六、`human_review_synopsis_node.py` 修改

在宏观构思批准后，询问创作模式：

```python
if user_input.get("action") == "approve":
    # 询问创作模式
    mode_input = interrupt({
        "type": "mode_select",
        "prompt": (
            "请选择创作模式：\n"
            "[1] 人工模式（每个节点都需要确认）\n"
            "[2] 自动模式（全自动推进，方向问题时自动修正）"
        ),
    })

    auto_mode    = mode_input.get("auto_mode", False)
    max_chapters = mode_input.get("max_chapters", 0)

    return Command(
        update={
            "synopsis_approved": True,
            "auto_mode":         auto_mode,
            "max_chapters":      max_chapters,
        },
        goto="path_gen",
    )
```

### `__main__.py` 补充 mode_select 处理

```python
elif prompt_type == "mode_select":
    console.print("\n请选择创作模式：")
    console.print("  [1] 人工模式")
    console.print("  [2] 自动模式")
    choice = input("\n请输入选项：").strip()

    if choice == "2":
        max_ch = input("最大章节数（直接回车=不限制）：").strip()
        max_chapters = int(max_ch) if max_ch.isdigit() else 0
        console.print(f"[dim]自动模式已启动，最大章节数：{max_chapters or '不限制'}[/dim]")
        return {"auto_mode": True, "max_chapters": max_chapters}
    else:
        return {"auto_mode": False, "max_chapters": 0}
```

---

## 七、`memory/db.py` 新增函数

```python
async def load_chapters_count(project_id: str) -> int:
    """获取已完成章节数量"""
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT COUNT(*) as cnt FROM chapters
            WHERE project_id = ?
        """, (project_id,))
        row = await cursor.fetchone()
        return row["cnt"] if row else 0


async def get_project_max_chapters(project_id: str) -> int:
    """从数据库读取最大章节数配置"""
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT max_chapters FROM novel_projects
            WHERE project_id = ?
        """, (project_id,))
        row = await cursor.fetchone()
        return row["max_chapters"] if row else 0


async def get_entity_cards_by_names(
    project_id: str, names: list[str]
) -> list[dict]:
    """根据名字列表查询人物卡"""
    if not names:
        return []
    placeholders = ",".join("?" * len(names))
    async with get_connection() as conn:
        cursor = await conn.execute(f"""
            SELECT standard_name, traits_display
            FROM entity_cards
            WHERE project_id = ? AND standard_name IN ({placeholders})
        """, [project_id] + names)
        return [dict(r) for r in await cursor.fetchall()]
```

---

## 八、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `schemas/state.py` | 新增 auto_mode、max_chapters、auto_retry_count、pending_review_type |
| `memory/schema.sql` | novel_projects 新增 auto_mode、max_chapters 字段 |
| `memory/db.py` | 新增 load_chapters_count、get_project_max_chapters、get_entity_cards_by_names |
| `graph/creation/nodes/auto_review_node.py` | 新建，完整实现见第四章 |
| `graph/creation/graph.py` | 注册新节点；新增 route_review 路由函数；修改 path_gen/write/update_weight 的出边 |
| `graph/creation/nodes/human_review_synopsis_node.py` | 批准后询问创作模式 |
| `__main__.py` | 新增 mode_select 类型的 interrupt 处理 |

**不需要修改：** human_review_path、human_review_write、human_review_batch（原有节点保留，自动模式下被绕过）、所有提取流节点、expand 节点、write 节点。

---

*DeepNovel 自动模式优化文档 v1.0*
