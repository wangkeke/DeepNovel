# DeepNovel 完整框架导入功能 — Cursor 执行文档

> 支持用户导入已有的完整小说框架文档（.txt / .md）。
> 核心设计：解析分层 + 字段扩展，兼容现有数据结构。
> 改动不破坏现有流程，框架导入是新增的并行入口。

---

## 一、整体流程

```
用户选择 [3] 导入完整框架
    ↓
输入文件路径（.txt / .md）
    ↓
framework_parse_node：解析框架文档
  → 识别世界观/人物/卷信息/情节粒度
    ↓
human_review_framework：用户确认解析结果（逐模块展示）
  → 可逐字段编辑，回车保留
    ↓
写入数据库（synopsis/world_setting/character_cards/volumes/foreshadow_seeds/write_rules）
    ↓
mode_select_node：选择人工/自动模式
    ↓
进入 path_gen（以当前卷的 volume_direction 为约束）
    ↓
后续流程与现有流程完全一致
```

---

## 二、数据库变更（`memory/schema.sql`）

```sql
-- novel_projects 表新增字段
ALTER TABLE novel_projects ADD COLUMN volumes_json TEXT DEFAULT '[]';
-- 存储所有卷的结构化信息

ALTER TABLE novel_projects ADD COLUMN current_volume_index INTEGER DEFAULT 0;
-- 当前正在写的卷（0开始）

ALTER TABLE novel_projects ADD COLUMN user_write_rules TEXT DEFAULT '';
-- 用户框架中的创作铁则，注入 WRITE_SYSTEM
```

### volumes_json 结构

```json
[
  {
    "volume_index": 0,
    "volume_name": "深山学艺·人心初考",
    "volume_direction": "立稳主角底色，完成师傅人心考验，埋下全文核心伏笔",
    "estimated_chapters": 12,
    "plot_nodes": [
      "学艺日常：师傅培养谨慎心性，刻入守底线规矩",
      "师傅终极考验：凶宅闹鬼实为人为，领悟人心比鬼毒",
      "师傅失踪：返山发现师傅不在，字条桃木牌，决定入城寻师"
    ],
    "has_detailed_plot": true,
    "completed_node_count": 0,
    "is_completed": false
  }
]
```

---

## 三、新建 `graph/creation/nodes/framework_parse_node.py`

```python
"""
framework_parse_node：解析用户上传的完整框架文档

职责：
  1. 读取文档内容
  2. 用 LLM 解析成结构化数据（分层识别粒度）
  3. 写入 state，供 human_review_framework 展示确认

解析的内容：
  synopsis：从主线/题材/风格提取
  world_setting：从基础设定提取
  protagonist_card：从主角设定提取
  character_cards：从配角团提取
  foreshadow_seeds：从前置伏笔提取
  write_rules：从创作铁则提取
  volumes：卷信息列表（含粒度识别）
"""
from __future__ import annotations
import json
from pathlib import Path
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done, node_warn
import logging

logger = logging.getLogger("deepnovel.framework_parse")


async def framework_parse_node(state: CreationState) -> dict:
    file_path = state.get("framework_file_path", "")
    if not file_path:
        return {"error": "未指定框架文件路径"}

    # 读取文档
    path = Path(file_path)
    if not path.exists():
        return {"error": f"文件不存在：{file_path}"}

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return {"error": "文件内容为空"}

    node_step("解析框架文档")

    result = await call_llm_json(
        system="""
你是一个专业的网文策划编辑，负责解析用户提供的小说创作框架文档。
将文档内容结构化提取到指定的 JSON 格式中。

提取规则：
  - 完整保留用户描述的所有具体内容，不做任何删减或改写
  - 人物名字按原文保留，不做修改
  - 卷信息提取时，判断每卷是否有具体情节点（has_detailed_plot）：
    有明确列出具体情节事件 → true
    只有大方向描述 → false
  - 创作铁则提取为完整文本，保留原文措辞
只返回 JSON，不加任何前言。
""",
        user=f"""
## 框架文档内容
{content}

## 提取任务

返回以下 JSON 结构（所有字段都尽量提取，提取不到则用空值）：
{{
  "synopsis": {{
    "title": "小说标题（如有）",
    "world": "世界观（一段话）",
    "protagonist": "主角定位（行事方式和核心动机，不写单一技能标签）",
    "core_conflict": "核心冲突",
    "direction": "整体走向"
  }},
  "world_setting": {{
    "basic_rules": "世界核心规则",
    "power_structure": ["势力1", "势力2"],
    "geography": ["地点1"],
    "taboos": ["禁忌1"],
    "unique_settings": ["独特设定1"]
  }},
  "protagonist_card": {{
    "standard_name": "主角名字",
    "appearance": "外貌（一句话，1-2个辨识特征）",
    "background_summary": "背景经历",
    "traits_display": [
      "遇险时 → 具体行为",
      "真正愤怒时 → 具体行为",
      "面对重要的人时 → 具体行为",
      "被逼到极限时 → 具体行为（失控时刻）",
      "最执着的事 → 具体描述"
    ],
    "dominant_logics": ["人性逻辑名称，如：设局逻辑、忍辱逻辑"]
  }},
  "character_cards": [
    {{
      "standard_name": "人物名",
      "role": "core_supporting / antagonist / neutral",
      "appearance": "外貌一句话",
      "background_summary": "背景经历",
      "traits_display": ["行为倾向1", "行为倾向2"],
      "relationship_to_protagonist": "与主角的关系"
    }}
  ],
  "foreshadow_seeds": [
    {{
      "surface_meaning": "伏笔表面描述",
      "story_potential": "这条伏笔可能推动故事的方向",
      "mystery_type": "normal / permanent",
      "ready_threshold": 3
    }}
  ],
  "write_rules": "创作铁则完整文本（保留原文措辞）",
  "volumes": [
    {{
      "volume_index": 0,
      "volume_name": "卷名",
      "volume_direction": "本卷核心目标和大方向",
      "estimated_chapters": 12,
      "plot_nodes": [
        "具体情节点1（如有）",
        "具体情节点2（如有）"
      ],
      "has_detailed_plot": true
    }}
  ]
}}
""",
    )

    node_done(f"解析完成：{len(result.get('volumes', []))} 卷，{len(result.get('character_cards', []))} 个配角")

    return {
        "framework_parsed": result,
        "synopsis":        result.get("synopsis", {}),
        "world_setting":   result.get("world_setting", {}),
        "protagonist_card": result.get("protagonist_card", {}),
        "character_cards_draft": result.get("character_cards", []),
        "foreshadow_seeds": result.get("foreshadow_seeds", []),
        "user_write_rules": result.get("write_rules", ""),
        "volumes_draft":   result.get("volumes", []),
    }
```

---

## 四、新建 `graph/creation/nodes/human_review_framework_node.py`

```python
"""
human_review_framework_node：用户确认框架解析结果

分模块展示，用户可以逐字段编辑。
确认后写入数据库，进入 mode_select_node。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.db import (
    save_framework_to_project,
    save_foreshadow,
    save_character_card,
)
from ulid import ULID


async def human_review_framework_node(state: CreationState) -> Command:
    parsed = state.get("framework_parsed", {})

    user_input = interrupt({
        "type":    "framework_review",
        "content": parsed,
        "prompt":  "请确认框架解析结果",
    })

    action = user_input.get("action", "approve")
    edits  = user_input.get("edits", {})

    if action == "approve":
        # 合并用户编辑（只覆盖有输入的字段）
        final_synopsis      = {**parsed.get("synopsis", {}),      **edits.get("synopsis", {})}
        final_world         = {**parsed.get("world_setting", {}),  **edits.get("world_setting", {})}
        final_protagonist   = {**parsed.get("protagonist_card", {}), **edits.get("protagonist_card", {})}
        final_volumes       = edits.get("volumes", parsed.get("volumes", []))
        final_write_rules   = edits.get("write_rules", parsed.get("write_rules", ""))

        project_id = state["project_id"]

        # 写入数据库
        await save_framework_to_project(
            project_id    = project_id,
            synopsis      = final_synopsis,
            world_setting = final_world,
            volumes       = final_volumes,
            write_rules   = final_write_rules,
        )

        # 写入配角卡
        for card in parsed.get("character_cards", []):
            await save_character_card(project_id, card)

        # 写入伏笔种子
        for i, f in enumerate(parsed.get("foreshadow_seeds", [])):
            await save_foreshadow(project_id, {
                "foreshadow_id":   str(ULID()),
                "project_id":      project_id,
                "foreshadow_type": "noun",
                "surface_meaning": f.get("surface_meaning", ""),
                "true_meaning":    "",
                "planted_at_node": 0,
                "collected_at_node": 0,
                "story_potential": f.get("story_potential", ""),
                "mystery_type":    f.get("mystery_type", "normal"),
                "is_backbone":     0,
                "urgency":         "latent",
                "mention_count":   1,
                "ready_threshold": f.get("ready_threshold", 3),
                "is_inferred":     0,
                "mentioned_by":    "框架导入",
                "misdirect_direction": "",
            })

        return Command(
            update={
                "synopsis":           final_synopsis,
                "world_setting":      final_world,
                "protagonist_card":   final_protagonist,
                "user_write_rules":   final_write_rules,
                "current_volume_index": 0,
                "synopsis_approved":  True,
                "world_approved":     True,
            },
            goto="mode_select",
        )
```

---

## 五、`__main__.py` 修改

### 5.1 创建方式新增选项

```python
console.print("\n请选择创建方式：")
console.print("  [1] 自动生成（只需输入题材，系统生成所有设定）")
console.print("  [2] 我已有故事方向（输入后系统据此生成设定，需要确认）")
console.print("  [3] 导入完整框架（已有完整的世界观/人物/剧情规划）")
mode = input("\n请输入选项：").strip()

if mode == "3":
    console.print("\n请输入框架文档路径（支持 .txt .md）：")
    file_path = input("> ").strip()
    background = _load_background(file_path)  # 复用已有的文件读取函数
    if background:
        initial_state["framework_file_path"] = file_path
        initial_state["creation_mode"] = "framework"
```

### 5.2 `_handle_interrupt` 新增 framework_review 处理

```python
elif prompt_type == "framework_review":
    content = interrupt_data.get("content", {})

    console.print("\n[bold]请确认框架解析结果[/bold]")
    console.print("[dim]直接回车保留，输入新内容则替换[/dim]\n")

    edits = {}

    # ── 宏观构思 ─────────────────────────────────────────────
    synopsis = content.get("synopsis", {})
    console.print(Panel(
        f"标题：{synopsis.get('title', '')}\n"
        f"世界观：{synopsis.get('world', '')}\n"
        f"主角：{synopsis.get('protagonist', '')}\n"
        f"核心冲突：{synopsis.get('core_conflict', '')}\n"
        f"走向：{synopsis.get('direction', '')}",
        title="📖 宏观构思",
        border_style="cyan",
        expand=False,
    ))
    syn_edit = input("修改宏观构思某个字段？[回车跳过 / 输入字段名=新内容]：").strip()
    if syn_edit:
        # 简单解析 field=value 格式
        edits["synopsis"] = _parse_field_edits(syn_edit, synopsis)

    # ── 卷信息 ────────────────────────────────────────────────
    volumes = content.get("volumes", [])
    console.print(f"\n[bold]共 {len(volumes)} 卷：[/bold]")
    for v in volumes:
        detail = "有详细情节" if v.get("has_detailed_plot") else "只有方向"
        console.print(
            f"  第{v['volume_index']+1}卷：{v['volume_name']}"
            f"  [dim]（{detail}，约{v.get('estimated_chapters', '?')}章）[/dim]"
        )
    vol_confirm = input("\n卷信息是否正确？[回车确认 / 输入修改意见]：").strip()
    # 卷信息修改较复杂，如有修改意见记录下来但不做字段级编辑
    if vol_confirm:
        edits["volumes_feedback"] = vol_confirm

    # ── 创作铁则 ──────────────────────────────────────────────
    write_rules = content.get("write_rules", "")
    if write_rules:
        console.print(Panel(
            write_rules[:300] + ("..." if len(write_rules) > 300 else ""),
            title="📋 创作铁则（已提取）",
            border_style="dim",
            expand=False,
        ))

    # ── 配角数量确认 ──────────────────────────────────────────
    char_count = len(content.get("character_cards", []))
    foreshadow_count = len(content.get("foreshadow_seeds", []))
    console.print(
        f"\n[dim]解析到 {char_count} 个配角，"
        f"{foreshadow_count} 条前置伏笔[/dim]"
    )

    console.print("\n[cyan][1][/cyan] 确认，开始创作")
    console.print("[cyan][2][/cyan] 重新解析（如解析结果有明显错误）")
    choice = input("\n请输入选项：").strip()

    if choice == "2":
        return {"action": "reparse"}
    return {"action": "approve", "edits": edits}
```

---

## 六、`path_gen_node.py` 修改

### 6.1 注入卷信息约束

在构造 user_prompt 时，加载当前卷的信息：

```python
from memory.db import get_current_volume

# 获取当前卷信息
current_vol_index = state.get("current_volume_index", 0)
volumes = await get_volumes(state["project_id"])
current_volume = volumes[current_vol_index] if current_vol_index < len(volumes) else None

# 构造卷约束文本
volume_constraint = ""
if current_volume:
    vol_direction = current_volume.get("volume_direction", "")
    plot_nodes    = current_volume.get("plot_nodes", [])
    has_detail    = current_volume.get("has_detailed_plot", False)

    if has_detail and plot_nodes:
        # 有详细情节：要求按情节点生成节点路径
        volume_constraint = f"""
## 本卷情节约束（严格按照以下情节点规划节点路径）

本卷名称：{current_volume.get('volume_name', '')}
本卷方向：{vol_direction}

用户已规划的情节点（必须全部体现，顺序不变）：
{chr(10).join(f"{i+1}. {p}" for i, p in enumerate(plot_nodes))}

要求：
  将以上情节点拆解为标准节点路径格式
  每个情节点可以对应1-3个节点
  不要添加用户未提及的新主线情节
  细节和场景可以创作补全
"""
    elif vol_direction:
        # 只有方向：在方向约束下自由规划
        volume_constraint = f"""
## 本卷方向约束

本卷名称：{current_volume.get('volume_name', '')}
本卷核心目标：{vol_direction}

要求：
  在以上方向约束下规划节点路径
  节点内容需服务于本卷核心目标
  可以自由发挥具体情节，但不能偏离方向
"""
```

### 6.2 注入用户写作铁则

```python
user_write_rules = state.get("user_write_rules", "")
if user_write_rules:
    user_rules_section = f"""
## 用户创作铁则（规划时必须遵守）
{user_write_rules}
"""
```

---

## 七、`prompts/creation/write.py` 修改

在 `WRITE_SYSTEM` 末尾加占位符，由 `write_node.py` 动态注入用户铁则：

```python
WRITE_SYSTEM = """
...原有内容不变...

{user_write_rules_section}

只返回正文，不加任何 JSON 包装或解释。
"""
```

在 `write_node.py` 注入时：

```python
user_write_rules = state.get("user_write_rules", "")
user_rules_section = f"""
【用户指定创作铁则（最高优先级，必须严格遵守）】
{user_write_rules}
""" if user_write_rules else ""

system = WRITE_SYSTEM.format(
    platform_style=platform_style_text,
    user_write_rules_section=user_rules_section,
)
```

---

## 八、`memory/db.py` 新增函数

```python
async def save_framework_to_project(
    project_id: str,
    synopsis: dict,
    world_setting: dict,
    volumes: list,
    write_rules: str,
) -> None:
    """将框架解析结果写入 novel_projects 表"""
    import json
    async with get_connection() as conn:
        await conn.execute("""
            UPDATE novel_projects SET
                synopsis_json     = ?,
                world_setting_json = ?,
                volumes_json      = ?,
                user_write_rules  = ?,
                updated_at        = datetime('now')
            WHERE project_id = ?
        """, (
            json.dumps(synopsis,      ensure_ascii=False),
            json.dumps(world_setting, ensure_ascii=False),
            json.dumps(volumes,       ensure_ascii=False),
            write_rules,
            project_id,
        ))
        await conn.commit()


async def get_volumes(project_id: str) -> list:
    """获取小说的卷信息列表"""
    import json
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT volumes_json FROM novel_projects
            WHERE project_id = ?
        """, (project_id,))
        row = await cursor.fetchone()
        if not row or not row["volumes_json"]:
            return []
        return json.loads(row["volumes_json"])


async def update_volume_progress(
    project_id: str,
    volume_index: int,
    completed_node_count: int,
    is_completed: bool = False,
) -> None:
    """更新指定卷的完成进度"""
    import json
    volumes = await get_volumes(project_id)
    if volume_index < len(volumes):
        volumes[volume_index]["completed_node_count"] = completed_node_count
        volumes[volume_index]["is_completed"] = is_completed
    async with get_connection() as conn:
        await conn.execute("""
            UPDATE novel_projects SET
                volumes_json = ?,
                current_volume_index = ?,
                updated_at = datetime('now')
            WHERE project_id = ?
        """, (
            json.dumps(volumes, ensure_ascii=False),
            volume_index if not is_completed else volume_index + 1,
            project_id,
        ))
        await conn.commit()
```

---

## 九、`human_review_batch_node.py` 修改

在批次完成展示里，新增卷进度信息：

```python
from memory.db import get_volumes

volumes = await get_volumes(state["project_id"])
current_vol_index = state.get("current_volume_index", 0)

if volumes:
    current_vol = volumes[current_vol_index] if current_vol_index < len(volumes) else None
    if current_vol:
        console.print(
            f"\n[dim]当前进度：第{current_vol_index+1}卷 / 共{len(volumes)}卷"
            f"「{current_vol.get('volume_name', '')}」[/dim]"
        )

# 批次审核完成后，检查是否需要切换到下一卷
completed_chapters = await load_chapters_count(state["project_id"])
if current_vol and completed_chapters >= current_vol.get("estimated_chapters", 999):
    await update_volume_progress(
        state["project_id"],
        current_vol_index,
        completed_chapters,
        is_completed=True,
    )
    console.print(
        f"[green]✓[/green]  "
        f"第{current_vol_index+1}卷「{current_vol.get('volume_name', '')}」已完成"
    )
```

---

## 十、`graph/creation/graph.py` 修改

### 10.1 注册新节点

```python
from graph.creation.nodes.framework_parse_node import framework_parse_node
from graph.creation.nodes.human_review_framework_node import human_review_framework_node

builder.add_node("framework_parse",   framework_parse_node)
builder.add_node("human_review_framework", human_review_framework_node)
```

### 10.2 新增框架导入路径的边

```python
# 框架导入流程（新增路径）
builder.add_edge("framework_parse", "human_review_framework")
builder.add_edge("human_review_framework", "mode_select")

# load 节点根据 creation_mode 决定走哪条路
builder.add_conditional_edges(
    "load",
    lambda state: (
        "framework_parse" if state.get("creation_mode") == "framework"
        else "synopsis"
    ),
    {
        "framework_parse": "framework_parse",
        "synopsis":        "synopsis",
    },
)
```

---

## 十一、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `memory/schema.sql` | novel_projects 新增 volumes_json、current_volume_index、user_write_rules |
| `memory/db.py` | 新增 save_framework_to_project、get_volumes、update_volume_progress |
| `graph/creation/nodes/framework_parse_node.py` | 新建 |
| `graph/creation/nodes/human_review_framework_node.py` | 新建 |
| `graph/creation/graph.py` | 注册新节点；load 节点新增条件路由 |
| `graph/creation/nodes/path_gen_node.py` | 注入卷约束和用户写作铁则 |
| `graph/creation/nodes/write_node.py` | 注入用户写作铁则到 WRITE_SYSTEM |
| `prompts/creation/write.py` | WRITE_SYSTEM 末尾加 user_write_rules_section 占位符 |
| `graph/creation/nodes/human_review_batch_node.py` | 展示卷进度；批次完成后更新卷状态 |
| `__main__.py` | 创建方式新增选项3；新增 framework_review 的 interrupt 处理 |
| `schemas/state.py` | 新增 framework_file_path、creation_mode、framework_parsed、volumes_draft、user_write_rules、current_volume_index |

**不需要修改：** expand 节点、bible_update、tension_check、auto_review、所有提取流节点。

---

*DeepNovel 完整框架导入功能实现文档 v1.0*
