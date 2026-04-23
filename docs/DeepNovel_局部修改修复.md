# DeepNovel 局部修改修复 — Cursor 执行文档

> 修复所有 human_review 节点的"局部修改被全量重生成"问题。
> 核心原则：用户只改什么，就只更新什么，其余内容原样保留。

---

## 一、问题说明

当前所有 human_review 节点的修改逻辑是：
```
收集用户意见 → 把意见+原始内容一起发给模型 → 模型重新生成完整内容
```

导致用户只想改一个字段或一个节点，结果整体都变了。

正确逻辑应该是：
```
展示当前内容的各个字段/节点
用户逐一确认或修改
只有用户主动输入的部分才更新
其余部分原样保留，不经过模型
```

---

## 二、`human_review_synopsis_node` 修改

### 当前行为
用户输入修改意见 → 整个宏观构思重新生成

### 修复后行为
逐字段展示，用户直接编辑，回车保留原值

### 修改代码

```python
async def human_review_synopsis_node(state: CreationState) -> Command:
    synopsis = state["synopsis"]

    # ── 逐字段展示和编辑 ─────────────────────────────────────
    user_input = interrupt({
        "type": "synopsis_review",
        "content": synopsis,
        "prompt": _build_synopsis_prompt(synopsis),
    })

    action = user_input.get("action", "approve")

    if action == "approve":
        return Command(
            update={"synopsis_approved": True},
            goto="path_gen",
        )

    elif action == "edit":
        # 只更新用户明确修改的字段，其余保留原值
        edits = user_input.get("edits", {})
        updated_synopsis = {
            "title":          edits.get("title")          or synopsis.get("title", ""),
            "world":          edits.get("world")          or synopsis.get("world", ""),
            "protagonist":    edits.get("protagonist")    or synopsis.get("protagonist", ""),
            "core_conflict":  edits.get("core_conflict")  or synopsis.get("core_conflict", ""),
            "direction":      edits.get("direction")      or synopsis.get("direction", ""),
        }
        # 有字段需要模型重新生成时（用户输入了修改意见但不是直接替换值）
        regenerate_fields = user_input.get("regenerate_fields", [])
        if regenerate_fields:
            updated_synopsis = await _regenerate_synopsis_fields(
                updated_synopsis, regenerate_fields,
                user_input.get("field_feedback", {})
            )
        return Command(
            update={
                "synopsis": updated_synopsis,
                "synopsis_approved": False,
            },
            goto="human_review_synopsis",  # 重新展示修改后的结果
        )
```

### `__main__.py` 对应的 `_handle_interrupt` 修改

```python
elif prompt_type in ("synopsis_review", "synopsis"):
    synopsis = content

    console.print()
    console.print(Panel(
        f"[bold]标题：[/bold]{synopsis.get('title', '')}\n\n"
        f"[bold]世界观：[/bold]{synopsis.get('world', '')}\n\n"
        f"[bold]主角：[/bold]{synopsis.get('protagonist', '')}\n\n"
        f"[bold]核心冲突：[/bold]{synopsis.get('core_conflict', '')}\n\n"
        f"[bold]走向：[/bold]{synopsis.get('direction', '')}",
        title="📖 宏观构思",
        border_style="cyan",
        expand=False,
    ))

    console.print("\n[cyan][1][/cyan] 满意，继续规划故事路径")
    console.print("[cyan][2][/cyan] 修改某个字段")
    choice = input("\n请输入选项：").strip()

    if choice == "1":
        return {"action": "approve"}

    else:
        # 逐字段编辑，回车保留原值
        console.print("\n[dim]直接回车保留原值，输入新内容则替换[/dim]\n")
        edits = {}
        fields = [
            ("title",         "标题",   synopsis.get("title", "")),
            ("world",         "世界观", synopsis.get("world", "")),
            ("protagonist",   "主角",   synopsis.get("protagonist", "")),
            ("core_conflict", "核心冲突", synopsis.get("core_conflict", "")),
            ("direction",     "走向",   synopsis.get("direction", "")),
        ]
        for key, label, current in fields:
            console.print(f"[bold]{label}：[/bold]{current}")
            new_val = input(f"修改为（回车保留）：").strip()
            if new_val:
                edits[key] = new_val
            console.print()

        return {"action": "edit", "edits": edits}
```

---

## 三、`human_review_path_node` 修改

### 当前行为
用户输入修改意见 → 整批节点（10个）全部重新生成

### 修复后行为
用户可以选择修改单个节点或重新规划全部

### 修改代码

```python
async def human_review_path_node(state: CreationState) -> Command:
    story_path = state.get("story_path", [])

    user_input = interrupt({
        "type": "path_review",
        "content": story_path,
        "prompt": _build_path_prompt(story_path),
    })

    action = user_input.get("action", "approve")

    if action == "approve":
        return Command(
            update={"path_approved": True, "current_node_index": 0},
            goto="expand1",
        )

    elif action == "edit_node":
        # 只重新生成用户指定的某个节点
        target_index = user_input.get("node_index", 0)
        feedback = user_input.get("feedback", "")

        updated_node = await _regenerate_single_node(
            story_path, target_index, feedback, state
        )
        new_path = story_path.copy()
        new_path[target_index] = updated_node

        return Command(
            update={
                "story_path":    new_path,
                "path_approved": False,
            },
            goto="human_review_path",  # 重新展示修改后的路径
        )

    elif action == "regenerate_all":
        # 用户明确要求重新规划全部
        feedback = user_input.get("feedback", "")
        return Command(
            update={
                "path_approved": False,
                "synopsis": {
                    **state.get("synopsis", {}),
                    "path_feedback": feedback,
                },
            },
            goto="path_gen",
        )


async def _regenerate_single_node(
    story_path: list,
    target_index: int,
    feedback: str,
    state: dict,
) -> dict:
    """
    只重新生成路径中的某一个节点。
    注入上下文：前一个节点的 output_state 和后一个节点的 input_state（如有）。
    """
    from utils.llm import call_llm_json
    from prompts.creation.path_gen import SINGLE_NODE_REGEN_SYSTEM

    prev_node = story_path[target_index - 1] if target_index > 0 else None
    next_node = story_path[target_index + 1] if target_index < len(story_path) - 1 else None
    current_node = story_path[target_index]

    user_prompt = f"""
## 当前节点（需要修改）
{current_node}

## 用户修改意见
{feedback}

## 上下文约束
前一个节点结尾状态：{prev_node.get('output_state_hint', '') if prev_node else '无（这是第一个节点）'}
后一个节点开始状态：{next_node.get('input_state_hint', '') if next_node else '无（这是最后一个节点）'}

## 要求
只重新生成这一个节点，保持与前后节点的连续性。
返回单个节点的 JSON，格式与原节点完全一致。
"""
    return await call_llm_json(SINGLE_NODE_REGEN_SYSTEM, user_prompt)
```

### `__main__.py` 对应的 `_handle_interrupt` 修改

```python
elif prompt_type in ("path_review", "path"):
    story_path = content if isinstance(content, list) else content.get("nodes", [])

    # 展示路径
    lines = []
    for i, node in enumerate(story_path):
        lines.append(
            f"  [bold]{i+1}.[/bold]  "
            f"[cyan]{node.get('node_name', '')}[/cyan]\n"
            f"      {node.get('one_liner', '')}"
        )
    console.print(Panel(
        "\n".join(lines),
        title=f"🗺  故事路径（共 {len(story_path)} 个节点）",
        border_style="cyan",
        expand=False,
    ))

    console.print("\n[cyan][1][/cyan] 满意，开始写作")
    console.print("[cyan][2][/cyan] 修改某个节点")
    console.print("[cyan][3][/cyan] 重新规划全部路径")
    choice = input("\n请输入选项：").strip()

    if choice == "1":
        return {"action": "approve"}

    elif choice == "2":
        # 只修改指定节点
        console.print("\n请输入要修改的节点编号（1开始）：")
        node_num = input("编号：").strip()
        if node_num.isdigit():
            node_index = int(node_num) - 1
            target = story_path[node_index] if 0 <= node_index < len(story_path) else None
            if target:
                console.print(f"\n当前第{node_num}节：")
                console.print(f"  {target.get('node_name', '')}")
                console.print(f"  {target.get('one_liner', '')}")
                feedback = input("\n修改意见：").strip()
                return {
                    "action":     "edit_node",
                    "node_index": node_index,
                    "feedback":   feedback,
                }
        return {"action": "approve"}  # 编号无效时默认通过

    else:
        # 重新规划全部
        feedback = input("请输入重新规划的意见：").strip()
        return {"action": "regenerate_all", "feedback": feedback}
```

---

## 四、`human_review_protagonist_node` 修改

### 当前行为
用户输入修改意见 → 整张人物卡重新生成

### 修复后行为
逐字段展示，用户直接编辑，行为倾向可以逐条编辑或追加

### 修改代码（`__main__.py` 的 `_handle_interrupt`）

```python
elif prompt_type == "protagonist_review":
    card = content

    console.print(Panel(
        f"[bold]标准名：[/bold]{card.get('standard_name', '')}\n\n"
        f"[bold]外貌：[/bold]{card.get('appearance', '')}\n\n"
        f"[bold]行为倾向：[/bold]\n" +
        "\n".join(f"  • {t}" for t in card.get("traits_display", [])),
        title="👤 主角人物卡",
        border_style="cyan",
        expand=False,
    ))

    console.print("\n[cyan][1][/cyan] 确认，建立主角人物卡")
    console.print("[cyan][2][/cyan] 修改某个字段")
    choice = input("\n请输入选项：").strip()

    if choice == "1":
        return {"action": "approve"}

    else:
        console.print("\n[dim]直接回车保留原值[/dim]\n")
        edits = {}

        # 名字
        console.print(f"[bold]标准名：[/bold]{card.get('standard_name', '')}")
        new_name = input("修改为（回车保留）：").strip()
        if new_name:
            edits["standard_name"] = new_name

        # 外貌
        console.print(f"\n[bold]外貌：[/bold]{card.get('appearance', '')}")
        new_appearance = input("修改为（回车保留）：").strip()
        if new_appearance:
            edits["appearance"] = new_appearance

        # 行为倾向
        console.print("\n[bold]行为倾向：[/bold]")
        traits = card.get("traits_display", [])
        trait_edits = []
        for i, t in enumerate(traits):
            console.print(f"  [{i+1}] {t}")
            new_t = input(f"  修改第{i+1}条（回车保留）：").strip()
            trait_edits.append(new_t if new_t else t)

        # 追加新的行为倾向
        console.print("\n追加新行为倾向？（直接回车跳过）")
        extra = input("新条目：").strip()
        if extra:
            trait_edits.append(extra)

        if trait_edits != traits:
            edits["traits_display"] = trait_edits

        return {"action": "edit", "edits": edits}
```

### `human_review_protagonist_node.py` 对应修改

```python
if action == "edit":
    edits = user_input.get("edits", {})
    updated_card = {
        **card,  # 保留所有原有字段
        **{k: v for k, v in edits.items() if v},  # 只覆盖用户修改的字段
    }
    return Command(
        update={"protagonist_card": updated_card},
        goto="human_review_protagonist",  # 重新展示确认
    )
```

---

## 五、`prompts/creation/path_gen.py` 新增

新增单节点重新生成的 system prompt：

```python
SINGLE_NODE_REGEN_SYSTEM = """
你是一个故事结构师。
根据用户修改意见，重新生成故事路径中的单个节点。

要求：
- 只修改用户指定的内容
- 必须与前一个节点的结尾状态自然衔接
- 必须与后一个节点的开始状态保持一致（如有）
- 保持与整批节点相同的格式和字段结构
- 只返回单个节点的 JSON，不加任何前言
"""
```

---

## 六、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `graph/creation/nodes/human_review_synopsis_node.py` | 新增 edit 分支，只更新用户修改的字段 |
| `graph/creation/nodes/human_review_path_node.py` | 新增 edit_node 分支，只重新生成指定节点；新增 `_regenerate_single_node` 函数 |
| `graph/creation/nodes/human_review_protagonist_node.py` | 新增 edit 分支，只更新用户修改的字段 |
| `prompts/creation/path_gen.py` | 新增 `SINGLE_NODE_REGEN_SYSTEM` |
| `__main__.py` | 三个 interrupt 类型的处理逻辑全部改为逐字段/逐节点交互 |

**不需要修改：** path_gen_node、synopsis_node、expand 节点、write 节点、bible_update、所有提取流节点。

---

## 七、修改后的交互效果

### 宏观构思修改
```
[1] 满意  [2] 修改某个字段

选2后：
  标题：重启人生          → 直接回车保留
  世界观：2024年...       → 输入新内容替换
  主角：前世因贪婪...     → 直接回车保留
  核心冲突：...           → 直接回车保留
  走向：...               → 直接回车保留

只有世界观被更新，其余四个字段不变。
```

### 故事路径修改
```
[1] 满意  [2] 修改某个节点  [3] 重新规划全部

选2后：
  请输入节点编号：3
  当前第3节：风雪入宫门 / 罪臣之女踏入宫门...
  修改意见：改成主角被人陷害，险些入狱

只有第3节被重新生成，其余9个节点原样保留。
```

### 人物卡修改
```
[1] 确认  [2] 修改某个字段

选2后：
  标准名：陈锋 → 输入 楚天
  外貌：...    → 直接回车保留
  行为倾向：
    [1] 遇险时... → 直接回车保留
    ...
    [7] 最执着... → 直接回车保留
  追加新行为倾向？→ 直接回车跳过

只有名字被更新，其余全部保留。
```

---

*DeepNovel 局部修改修复文档 v1.0*
