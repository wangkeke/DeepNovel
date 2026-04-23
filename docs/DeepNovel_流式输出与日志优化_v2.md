# DeepNovel 流式输出与日志优化 v2 — Cursor 执行文档

> **v1 文档已作废，本文档完全替代。**
>
> 核心设计变更：流式输出不在节点内部实现，而是通过 LangGraph 原生的
> `graph.astream_events()` 在 CLI 层统一捕获。节点只负责业务逻辑，
> 展示层与执行层完全分离。

---

## 零、设计原则

```
节点层（nodes/）：
  只调用 LLM、处理数据、更新 State
  不做任何 console.print，不感知"是否在流式"
  统一使用 call_llm() / call_llm_json()（见 utils/llm.py）

CLI 层（__main__.py）：
  使用 graph.astream_events() 替代 graph.ainvoke()
  在事件循环里统一处理：节点状态显示、token 流输出、完成提示
  根据 metadata["langgraph_node"] 判断当前节点，决定是否展示 token

为什么这样更好：
  1. 节点代码干净，无 UI 代码混入
  2. 切换模型只改 config，节点不动
  3. 流式是 astream_events 的能力，不依赖 OpenAI SDK 的 stream API
```

---

## 一、保持不变的文件

以下文件与 v1 文档**完全一致**，如果已按 v1 创建，**不需要改动**：

- `utils/__init__.py`
- `utils/logging_config.py`
- `config.py`（新增字段部分）
- `schemas/state.py`（新增 `rewrite_count` 部分）

---

## 二、需要新建的文件

### 2.1 `utils/llm.py`（全新设计，替代 v1 版本）

```python
"""
统一 LLM 调用工具。

对外提供两个函数：
  call_llm(system, user)       → str   用于 write_node（正文，纯文本）
  call_llm_json(system, user)  → dict  用于所有需要 JSON 输出的节点

底层使用 LangChain 的 ChatOpenAI / ChatAnthropic，而不是直接调用 SDK。
这样 LangGraph 的 astream_events 可以自动捕获 token 级别的流式事件，
节点代码本身无需做任何流式处理。

模型切换：只改环境变量，节点代码不变。
  LLM_PROVIDER=deepseek  → ChatOpenAI（兼容 DeepSeek API）
  LLM_PROVIDER=anthropic → ChatAnthropic
  LLM_PROVIDER=openai    → ChatOpenAI（官方 OpenAI）
"""

import asyncio
import json
import logging
import os

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger("deepnovel.llm")


def get_llm():
    """
    返回 LangChain LLM 实例。
    根据 LLM_PROVIDER 环境变量选择底层实现。
    """
    provider  = os.getenv("LLM_PROVIDER", "deepseek").lower()
    model     = os.getenv("LLM_MODEL",     "deepseek-chat")
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            max_tokens=max_tokens,
        )
    else:
        # deepseek / openai 都走 ChatOpenAI，通过 base_url 区分
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
            max_tokens=max_tokens,
        )


async def call_llm(system: str, user: str, retries: int = 3) -> str:
    """
    调用 LLM，返回原始文本字符串。

    适用场景：write_node（正文写作），输出是纯文本不是 JSON。
    流式 token 由上层 astream_events 自动捕获，这里不做任何流式处理。
    """
    llm = get_llm()
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    for attempt in range(retries):
        try:
            response = await llm.ainvoke(messages)
            return response.content
        except Exception as e:
            logger.warning(f"call_llm 第 {attempt + 1} 次失败: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)

    return ""


async def call_llm_json(system: str, user: str, retries: int = 3) -> dict:
    """
    调用 LLM，解析并返回 JSON dict。

    适用场景：所有需要结构化输出的节点（pass1a/1b、expand1/2、
              bible_update、consistency、path_gen、synopsis 等）。
    自动清理 markdown 代码块包装（```json ... ```）。
    失败时指数退避重试。
    """
    raw = await call_llm(system, user, retries)
    try:
        return _parse_json(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM JSON 解析失败: {e}\n原始输出（前500字）:\n{raw[:500]}")


def _parse_json(raw: str) -> dict:
    """清理 LLM 输出中可能存在的 markdown 包装，然后解析 JSON"""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    return json.loads(text)
```

---

### 2.2 `utils/display.py`（调整版，删掉 v1 中流式相关的两个函数）

```python
"""
节点执行状态展示工具。

所有函数只负责打印状态文字，不处理 LLM token 流。
token 流的展示在 __main__.py 的 astream_events 循环里处理。
"""

from rich.console import Console
from rich.panel import Panel

console = Console()


def node_step(step_name: str):
    """节点内部子步骤开始（在节点函数里调用，可选）"""
    console.print(f"  [yellow]→[/yellow] {step_name}...", end="")


def node_done(result_summary: str = ""):
    """步骤完成"""
    if result_summary:
        console.print(f"  [green]✓[/green]  [dim]{result_summary}[/dim]")
    else:
        console.print(f"  [green]✓[/green]")


def node_warn(msg: str):
    """节点警告（不中断流程）"""
    console.print(f"\n  [yellow]⚠[/yellow]  {msg}")


def node_error(msg: str):
    """节点错误"""
    console.print(f"\n  [red]✗[/red]  {msg}")


def print_blueprint_saved(blueprint_id: str, title: str):
    """骨骼存储完成提示"""
    console.print(Panel(
        f"[green]骨骼提取完成[/green]\n\n"
        f"ID：[bold]{blueprint_id}[/bold]\n"
        f"书名：{title}",
        border_style="green",
        expand=False
    ))


def print_interrupt_prompt(prompt_type: str, content: dict):
    """
    interrupt 节点的统一展示格式。
    prompt_type: "synopsis" | "path"
    """
    if prompt_type == "synopsis":
        console.print(Panel(
            f"[bold]标题：[/bold]{content.get('title', '')}\n\n"
            f"[bold]世界观：[/bold]{content.get('world', '')}\n\n"
            f"[bold]主角：[/bold]{content.get('protagonist', '')}\n\n"
            f"[bold]核心冲突：[/bold]{content.get('core_conflict', '')}\n\n"
            f"[bold]走向：[/bold]{content.get('direction', '')}",
            title="📖 宏观构思",
            border_style="cyan",
            expand=False
        ))
    elif prompt_type == "path":
        nodes = content.get("nodes", [])
        lines = []
        for i, node in enumerate(nodes):
            lines.append(
                f"  [bold]{i + 1}.[/bold]  "
                f"[cyan]{node.get('node_name', '')}[/cyan]\n"
                f"      {node.get('one_liner', '')}"
            )
        console.print(Panel(
            "\n".join(lines),
            title=f"🗺  故事路径（共 {len(nodes)} 个节点）",
            border_style="cyan",
            expand=False
        ))
```

---

## 三、需要修改的文件

### 3.1 `__main__.py`（核心修改：create 命令改用 astream_events）

在文件顶部保留 `setup_logging()` 调用（和 v1 一致）。

**主要修改是 `run_create` 函数（或对应的 create 命令处理函数），替换为：**

```python
# __main__.py

from utils.logging_config import setup_logging
setup_logging()  # 必须在所有其他 import 之前

import asyncio
from rich.console import Console
from rich.rule import Rule
from langgraph.types import Command

console = Console()

# ── 节点名称映射（用于展示，key = 图中的节点函数名）──────────────
NODE_DISPLAY_NAMES = {
    "expand1_node":      "3W1H 分析",
    "expand2_node":      "场景设计",
    "write_node":        "正文写作",
    "bible_update_node": "更新故事圣经",
    "consistency_node":  "一致性检查",
    "path_gen_node":     "规划故事路径",
    "synopsis_node":     "生成宏观构思",
    "blueprint_load_node": "加载骨骼",
}

# ── 这些节点的 token 输出需要实时展示到终端 ──────────────────────
STREAM_TO_CONSOLE_NODES = {"write_node"}


async def run_create(genre: str, blueprint_id: str, thread_id: str):
    """
    创作流入口。使用 astream_events 实现：
    1. 节点状态实时显示（▶ 节点名 / ✓ 完成）
    2. write_node 的正文 token 实时流出
    3. interrupt 节点的人工确认
    """
    from graph.creation.graph import build_creation_graph
    from memory.checkpointer import get_checkpointer

    checkpointer = await get_checkpointer()
    graph = await build_creation_graph(checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "project_id":    thread_id,
        "genre_request": genre,
        "blueprint_id":  blueprint_id,
        "bible": {                          # 初始化空圣经结构
            "characters":            {},
            "events":                [],
            "planted_foreshadows":   [],
            "collected_foreshadows": [],
            "world_state":           "",
        },
        "rewrite_count":      0,
        "post_pivot":         False,
        "pivot_records":      [],
        "completed_chapters": [],
        "creation_complete":  False,
        "error":              None,
    }

    input_data = initial_state

    # ── 主循环：处理 interrupt 和正常执行 ──────────────────────────
    while True:
        result = await _run_with_streaming(graph, input_data, config)

        # 检查是否命中 interrupt（等待用户输入）
        interrupts = result.get("__interrupt__", [])
        if not interrupts:
            break  # 正常完成

        # 处理 interrupt
        interrupt_data = interrupts[0].value
        user_response  = await _handle_interrupt(interrupt_data)
        input_data     = Command(resume=user_response)

    console.print("\n[bold green]✓ 创作完成！[/bold green]")


async def _run_with_streaming(graph, input_data, config: dict) -> dict:
    """
    用 astream_events 运行图，处理节点状态显示和 token 流式输出。
    遇到 interrupt 时自动停止并返回当前 state。
    """
    current_node   = None
    in_write_node  = False
    final_state    = {}

    async for event in graph.astream_events(input_data, config, version="v2"):
        event_type = event["event"]
        event_name = event.get("name", "")
        metadata   = event.get("metadata", {})
        lg_node    = metadata.get("langgraph_node", "")

        # ── 节点开始 ──────────────────────────────────────────────
        if event_type == "on_chain_start" and lg_node in NODE_DISPLAY_NAMES:
            if lg_node != current_node:
                current_node  = lg_node
                display_name  = NODE_DISPLAY_NAMES[lg_node]
                in_write_node = (lg_node in STREAM_TO_CONSOLE_NODES)

                if in_write_node:
                    # write_node：打印分隔线，准备接收 token 流
                    console.print()
                    console.rule(
                        f"[bold white] {display_name} [/bold white]",
                        style="dim"
                    )
                    console.print()
                else:
                    console.print(
                        f"\n  [yellow]→[/yellow] {display_name}...",
                        end=""
                    )

        # ── 节点结束 ──────────────────────────────────────────────
        elif event_type == "on_chain_end" and lg_node in NODE_DISPLAY_NAMES:
            if in_write_node:
                # write_node 结束：打印字数
                output = event.get("data", {}).get("output", {})
                draft  = output.get("current_draft", "") if isinstance(output, dict) else ""
                console.print()
                console.print(
                    f"  [green]✓[/green]  [dim]共 {len(draft)} 字[/dim]"
                )
                in_write_node = False
            elif lg_node == current_node:
                console.print(f"  [green]✓[/green]")

        # ── LLM token 流（只展示 write_node 的输出）──────────────
        elif event_type == "on_chat_model_stream" and in_write_node:
            chunk = event["data"].get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                console.print(chunk.content, end="", highlight=False)

        # ── 图执行完成，获取最终 state ────────────────────────────
        elif event_type == "on_chain_end" and event_name == "LangGraph":
            output = event.get("data", {}).get("output", {})
            if isinstance(output, dict):
                final_state = output

    return final_state


async def _handle_interrupt(interrupt_data: dict) -> dict:
    """
    处理 interrupt 节点的用户交互。
    interrupt_data 是 interrupt() 传入的 dict，
    结构由 human_review_node 决定。
    """
    from utils.display import print_interrupt_prompt, console

    prompt_type = interrupt_data.get("type", "")
    content     = interrupt_data.get("content", {})

    console.print()
    console.print("[bold]需要人工确认[/bold]")
    print_interrupt_prompt(prompt_type, content)

    if prompt_type == "synopsis":
        console.print("\n[cyan][1][/cyan] 满意，继续规划故事路径")
        console.print("[cyan][2][/cyan] 修改 - 请附上修改意见")
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        else:
            feedback = input("请输入修改意见：").strip()
            return {"action": "revise", "feedback": feedback}

    elif prompt_type == "path":
        console.print("\n[cyan][1][/cyan] 满意，开始写作")
        console.print("[cyan][2][/cyan] 修改 - 请附上修改意见")
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        else:
            feedback = input("请输入修改意见：").strip()
            return {"action": "revise", "feedback": feedback}

    return {"action": "approve"}  # 默认通过
```

---

### 3.2 所有节点文件：统一替换 LLM 调用方式

**修改规则（对所有节点文件执行）：**

```
找到：
  from [任意路径] import call_llm_with_retry
  或任何直接使用 openai.AsyncOpenAI / anthropic.AsyncAnthropic 的调用

替换为：
  from utils.llm import call_llm        # write_node 用这个
  from utils.llm import call_llm_json   # 其他所有节点用这个
```

**各节点的具体替换方式：**

```python
# ── write_node.py ─────────────────────────────────────────────
# 改前：
result = await call_llm_with_retry(WRITE_SYSTEM, user_prompt)
draft = result  # 或 result["content"] 等

# 改后：
from utils.llm import call_llm
draft = await call_llm(WRITE_SYSTEM, user_prompt)
# draft 就是正文字符串，token 流由 astream_events 自动捕获

# ── 其他所有节点（synopsis, expand1, expand2,
#    bible_update, consistency, path_gen,
#    pass1a, pass1b, truth, pass2, pass3）─────────────────────
# 改前：
result = await call_llm_with_retry(SYSTEM, user_prompt)

# 改后：
from utils.llm import call_llm_json
result = await call_llm_json(SYSTEM, user_prompt)
# result 是 dict，后续解析逻辑不变
```

---

### 3.3 `graph/creation/nodes/consistency_node.py`（保持 v1 的重写计数逻辑）

此处的逻辑与 v1 文档一致，只需同时把 LLM 调用改为 `call_llm_json`：

```python
from utils.llm import call_llm_json
from utils.display import node_warn

result = await call_llm_json(CONSISTENCY_SYSTEM, user_prompt)

passed     = result.get("passed", True)
is_pivot   = result.get("is_pivot", False)
violations = result.get("violations", [])

rewrite_count = state.get("rewrite_count", 0)
MAX_REWRITES  = 2

if not passed and not is_pivot:
    if rewrite_count >= MAX_REWRITES:
        node_warn(
            f"一致性检查连续失败 {rewrite_count + 1} 次，强制通过。"
            f"违规：{'; '.join(violations)}"
        )
        passed = True

return {
    "consistency_result": result,
    "has_violation":      not passed and not is_pivot,
    "post_pivot":         is_pivot or state.get("post_pivot", False),
    "pivot_records": (
        [{"node": state["current_node_index"], "reason": result.get("pivot_reason")}]
        if is_pivot else []
    ),
    "rewrite_count": rewrite_count + 1 if (not passed and not is_pivot) else 0,
}
```

---

### 3.4 `schemas/state.py`（同 v1，补充 rewrite_count 和 bible 默认结构说明）

```python
# CreationState 新增一个字段
rewrite_count: int   # 当前节点重写次数，consistency 通过后重置为 0

# ⚠️ bible 的初始值必须在 __main__.py 的 initial_state 里显式设置（见 3.1 节）
# 不能依赖 TypedDict 的默认值，因为 LangGraph State 不支持 TypedDict 默认值
```

---

## 四、不需要修改的文件

```
所有 prompts/ 下的文件          - 不动
所有 graph/*/graph.py           - 不动（图结构不变）
所有 graph/extraction/nodes/    - 只改 LLM 调用方式（见 3.2 节的统一规则）
tools/                          - 不动
memory/                         - 不动
```

---

## 五、修改完成后的终端效果

```
(deepnovel) PS> uv run python __main__.py create --genre "玄幻逆袭" --blueprint-id 01KKK5GME9K0

需要人工确认
╭─────────────────────────────────────────────────────╮
│ 📖 宏观构思                                          │
│                                                     │
│ 标题：万古神帝                                       │
│ 世界观：以血脉定尊卑的九天神域...                    │
│ 核心冲突：从矿洞最底层挣扎求生，到觉醒血脉...        │
╰─────────────────────────────────────────────────────╯
[1] 满意，继续规划故事路径
[2] 修改 - 请附上修改意见

请输入选项：1

  → 规划故事路径...  ✓  10 个节点

需要人工确认
╭──────────────────────────────────────────────────╮
│ 🗺  故事路径（共 10 个节点）                      │
│   1.  矿洞绝境，血契初现                          │
│       濒死矿奴以血触发沉睡力量的第一次微弱悸动    │
│   2.  血纹残片，暗夜传薪                          │
│       ...                                         │
╰──────────────────────────────────────────────────╯
[1] 满意，开始写作
[2] 修改 - 请附上修改意见

请输入选项：1

  → 3W1H 分析...  ✓
  → 场景设计...  ✓

───────────────── 正文写作 ─────────────────

矿镐落下，又抬起。

每一次挥动，都像在拖动一具不属于自己的、灌满了铅的躯体...
（token 实时流出）

  ✓  1247 字

  → 更新故事圣经...  ✓
  → 一致性检查...  ✓

  → 3W1H 分析...  ✓
  ...（下一个节点）

✓ 创作完成！
```

---

## 六、改动范围总结

| 状态 | 文件 | 说明 |
|---|---|---|
| **新建** | `utils/__init__.py` | 包声明（同 v1） |
| **新建** | `utils/logging_config.py` | 日志配置（同 v1，无变化） |
| **新建** | `utils/display.py` | 展示函数（精简版，删掉流式相关两个函数） |
| **新建** | `utils/llm.py` | **全新设计**：`get_llm()` + `call_llm()` + `call_llm_json()` |
| **修改** | `config.py` | 补充 LLM_PROVIDER 等环境变量（同 v1） |
| **修改** | `__main__.py` | **核心修改**：create 命令改用 `astream_events` |
| **修改** | `schemas/state.py` | 新增 `rewrite_count`（同 v1） |
| **修改** | `graph/creation/nodes/write_node.py` | `call_llm_with_retry` → `call_llm` |
| **修改** | `graph/creation/nodes/synopsis_node.py` | → `call_llm_json` |
| **修改** | `graph/creation/nodes/expand1_node.py` | → `call_llm_json` |
| **修改** | `graph/creation/nodes/expand2_node.py` | → `call_llm_json` |
| **修改** | `graph/creation/nodes/bible_update_node.py` | → `call_llm_json` |
| **修改** | `graph/creation/nodes/consistency_node.py` | → `call_llm_json` + 重写计数逻辑 |
| **修改** | `graph/creation/nodes/path_gen_node.py` | → `call_llm_json` |
| **修改** | `graph/extraction/nodes/pass1a_node.py` | → `call_llm_json` |
| **修改** | `graph/extraction/nodes/pass1b_node.py` | → `call_llm_json` |
| **修改** | 其余提取流节点 | → `call_llm_json` |
| **不动** | 所有 `prompts/` 文件 | 无需改动 |
| **不动** | 所有 `graph/*/graph.py` | 无需改动 |
| **不动** | `tools/`, `memory/` | 无需改动 |

---

## 七、常见问题

**Q：`astream_events` 里的 `on_chain_start` 会对图本身和每个节点都触发，
怎么只过滤节点？**

A：通过 `metadata["langgraph_node"]` 判断。这个字段只有在 LangGraph 的节点
执行上下文中才存在，图本身触发的事件这个字段为空字符串或不存在。
代码里已用 `if lg_node in NODE_DISPLAY_NAMES` 过滤。

**Q：为什么只有 `write_node` 的 token 流出，synopsis 不流？**

A：synopsis 的输出是 JSON，流式显示 JSON 构造过程对用户没有意义。
`write_node` 的输出是正文，流式展示才有阅读体验。
如果需要增加其他节点的流式展示，把节点名加入 `STREAM_TO_CONSOLE_NODES` 集合即可。

**Q：切换成 Anthropic Claude 怎么配置？**

A：
```bash
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-20250514
ANTHROPIC_API_KEY=sk-ant-...
```
节点代码不需要任何改动。
