# DeepNovel 伏笔系统 — Cursor 完整优化文档 v2

> 替代 v1 文档，以本文档为准执行。
> 主要变更：去掉收尾模式，human_review_batch 选项简化为三个。

---

## 一、设计概览

### 伏笔的状态组合

```
mystery_type：
  'normal'    普通伏笔，参与 urgency 升级，注入 path_gen
  'permanent' 持续引力型，不升级，不注入 path_gen，只在状态面板展示

is_backbone：
  0  支线伏笔，参与 urgency 自动升级
  1  主线伏笔，只记录 mention_count，不升级，不注入 path_gen

urgency：
  'latent'   潜伏
  'building' 蓄力
  'ready'    待引爆（path_gen 收到提示，安排回收）
```

### 回收节奏两种模式

```
即收型（urgency 直接写入 'ready'）：
  埋下后 1-2 批就要交代的伏笔
  跳过计数机制，path_gen 立刻看到

积累型（通过 mention_count 累积到阈值触发 ready）：
  需要多次出现才成熟的伏笔
  ready_threshold 由用户在首次提取时设定
  building 触发点 = ceil(ready_threshold × 0.6)
```

### building / ready 阈值对照表

```
ready_threshold | building触发 | ready触发
      3         |      2       |     3     ← 默认值
      4         |      3       |     4
      5         |      3       |     5
      6         |      4       |     6
      8         |      5       |     8
     10         |      6       |    10
```

---

## 二、数据库变更（`memory/schema.sql`）

### 2.1 新建 foreshadow_entries 表

```sql
CREATE TABLE IF NOT EXISTS foreshadow_entries (
    foreshadow_id       TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL,

    foreshadow_type     TEXT DEFAULT 'event',
    -- 'event'=事件型 / 'noun'=词条型 / 'behavior'=行为型

    surface_meaning     TEXT NOT NULL,
    true_meaning        TEXT DEFAULT '',
    planted_at_node     INTEGER DEFAULT 0,
    collected_at_node   INTEGER DEFAULT 0,
    -- 0 = 尚未回收

    misdirect_direction TEXT DEFAULT '',
    mentioned_by        TEXT DEFAULT '',
    story_potential     TEXT DEFAULT '',

    mystery_type        TEXT DEFAULT 'normal',
    -- 'normal' / 'permanent'

    is_backbone         INTEGER DEFAULT 0,
    -- 0=支线伏笔 / 1=主线伏笔

    urgency             TEXT DEFAULT 'latent',
    -- 'latent' / 'building' / 'ready'

    mention_count       INTEGER DEFAULT 1,

    ready_threshold     INTEGER DEFAULT 3,
    -- 积累型：达到此次数触发 ready
    -- 即收型：urgency 直接写 ready，此字段忽略

    is_inferred         INTEGER DEFAULT 0,

    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_foreshadow_project_urgency
    ON foreshadow_entries(project_id, urgency, collected_at_node);

CREATE UNIQUE INDEX IF NOT EXISTS idx_foreshadow_unique
    ON foreshadow_entries(project_id, surface_meaning);
```

---

## 三、`memory/db.py` 新增函数

### 3.1 `save_foreshadow`

```python
async def save_foreshadow(project_id: str, entry: dict) -> None:
    """新增或更新一条伏笔。以 (project_id, surface_meaning) 为唯一键。"""
    async with get_connection() as conn:
        await conn.execute("""
            INSERT INTO foreshadow_entries (
                foreshadow_id, project_id, foreshadow_type,
                surface_meaning, true_meaning,
                planted_at_node, collected_at_node,
                misdirect_direction, mentioned_by,
                story_potential, mystery_type, is_backbone,
                urgency, mention_count, ready_threshold, is_inferred
            ) VALUES (
                :foreshadow_id, :project_id, :foreshadow_type,
                :surface_meaning, :true_meaning,
                :planted_at_node, :collected_at_node,
                :misdirect_direction, :mentioned_by,
                :story_potential, :mystery_type, :is_backbone,
                :urgency, :mention_count, :ready_threshold, :is_inferred
            )
            ON CONFLICT(project_id, surface_meaning) DO UPDATE SET
                true_meaning = CASE
                    WHEN excluded.true_meaning != ''
                    THEN excluded.true_meaning
                    ELSE foreshadow_entries.true_meaning
                END,
                story_potential = CASE
                    WHEN excluded.story_potential != ''
                    THEN excluded.story_potential
                    ELSE foreshadow_entries.story_potential
                END,
                mystery_type    = excluded.mystery_type,
                is_backbone     = excluded.is_backbone,
                urgency         = excluded.urgency,
                ready_threshold = excluded.ready_threshold,
                updated_at      = datetime('now')
        """, entry)
        await conn.commit()
```

### 3.2 `update_foreshadow_mention`

```python
import math

async def update_foreshadow_mention(
    project_id: str,
    surface_meaning: str
) -> str:
    """
    正文中出现已有伏笔词条时调用，mention_count +1。
    根据类型决定是否升级 urgency，返回新的 urgency。
    """
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT foreshadow_id, mention_count,
                   mystery_type, is_backbone,
                   urgency, ready_threshold
            FROM foreshadow_entries
            WHERE project_id = ? AND surface_meaning = ?
        """, (project_id, surface_meaning))
        row = await cursor.fetchone()
        if not row:
            return "latent"

        # 主线伏笔或持续引力型：只计数，不升级
        if row["is_backbone"] or row["mystery_type"] == "permanent":
            await conn.execute("""
                UPDATE foreshadow_entries
                SET mention_count = mention_count + 1,
                    updated_at = datetime('now')
                WHERE foreshadow_id = ?
            """, (row["foreshadow_id"],))
            await conn.commit()
            return row["urgency"]

        # 即收型（urgency 已是 ready）：只计数
        if row["urgency"] == "ready":
            await conn.execute("""
                UPDATE foreshadow_entries
                SET mention_count = mention_count + 1,
                    updated_at = datetime('now')
                WHERE foreshadow_id = ?
            """, (row["foreshadow_id"],))
            await conn.commit()
            return "ready"

        # 积累型普通伏笔：按阈值升级
        new_count = row["mention_count"] + 1
        threshold = row["ready_threshold"]
        building_threshold = math.ceil(threshold * 0.6)

        new_urgency = (
            "ready"    if new_count >= threshold else
            "building" if new_count >= building_threshold else
            "latent"
        )

        await conn.execute("""
            UPDATE foreshadow_entries
            SET mention_count = ?,
                urgency = ?,
                updated_at = datetime('now')
            WHERE foreshadow_id = ?
        """, (new_count, new_urgency, row["foreshadow_id"]))
        await conn.commit()
        return new_urgency
```

### 3.3 `get_node_foreshadows`

```python
async def get_node_foreshadows(
    project_id: str, node_index: int
) -> list[dict]:
    """获取某节点新增的伏笔，供 human_review_write 展示。"""
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT * FROM foreshadow_entries
            WHERE project_id = ? AND planted_at_node = ?
            ORDER BY created_at
        """, (project_id, node_index))
        return [dict(r) for r in await cursor.fetchall()]
```

### 3.4 `get_pending_foreshadows`

```python
async def get_pending_foreshadows(project_id: str) -> list[dict]:
    """
    获取所有待推进伏笔（urgency=ready，未回收）。
    供 path_gen_node 注入使用。
    不包含主线伏笔和持续引力型。
    """
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT * FROM foreshadow_entries
            WHERE project_id = ?
              AND urgency = 'ready'
              AND collected_at_node = 0
              AND is_backbone = 0
              AND mystery_type != 'permanent'
            ORDER BY mention_count DESC
            LIMIT 5
        """, (project_id,))
        return [dict(r) for r in await cursor.fetchall()]
```

### 3.5 `get_story_status`

```python
async def get_story_status(project_id: str) -> dict:
    """获取故事状态面板数据，供 human_review_batch 展示。"""
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT surface_meaning, mention_count
            FROM foreshadow_entries
            WHERE project_id = ? AND mystery_type = 'permanent'
            ORDER BY created_at
        """, (project_id,))
        permanent = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute("""
            SELECT surface_meaning, mention_count
            FROM foreshadow_entries
            WHERE project_id = ? AND is_backbone = 1
              AND collected_at_node = 0
            ORDER BY planted_at_node
        """, (project_id,))
        backbone = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute("""
            SELECT surface_meaning, urgency, mention_count
            FROM foreshadow_entries
            WHERE project_id = ?
              AND is_backbone = 0
              AND mystery_type != 'permanent'
              AND urgency IN ('building', 'ready')
              AND collected_at_node = 0
            ORDER BY
                CASE urgency WHEN 'ready' THEN 0 ELSE 1 END,
                mention_count DESC
        """, (project_id,))
        pending = [dict(r) for r in await cursor.fetchall()]

        return {
            "permanent": permanent,
            "backbone":  backbone,
            "pending":   pending,
        }
```

### 3.6 `collect_foreshadow`

```python
async def collect_foreshadow(
    foreshadow_id: str,
    collected_at_node: int
) -> None:
    """标记伏笔已回收。"""
    async with get_connection() as conn:
        await conn.execute("""
            UPDATE foreshadow_entries
            SET collected_at_node = ?,
                updated_at = datetime('now')
            WHERE foreshadow_id = ?
        """, (collected_at_node, foreshadow_id))
        await conn.commit()
```

### 3.7 `activate_permanent_foreshadow`

```python
async def activate_permanent_foreshadow(foreshadow_id: str) -> None:
    """
    用户选择开始揭露某条持续引力谜题时调用。
    将 permanent 转为 normal + urgency=ready。
    """
    async with get_connection() as conn:
        await conn.execute("""
            UPDATE foreshadow_entries
            SET mystery_type = 'normal',
                urgency = 'ready',
                updated_at = datetime('now')
            WHERE foreshadow_id = ?
        """, (foreshadow_id,))
        await conn.commit()
```

---

## 四、`bible_update_node.py` 修改

### 4.1 Prompt 新增伏笔识别说明

在 `BIBLE_UPDATE_USER_TEMPLATE` 的伏笔提取部分补充：

```
【伏笔提取规则】

提取三类伏笔：

事件型（foreshadow_type='event'）：
  某件发生的事埋下的暗示
  表面看是普通情节，回头看是关键铺垫

词条型（foreshadow_type='noun'）：
  出现了这个世界独有的名词，被提到但未完整解释
  区分规则（重要）：
    主角实际使用或拥有的 → 能力卡，不是伏笔
    别人提到但主角未拥有的 → 词条型伏笔

行为型（foreshadow_type='behavior'）：
  某人物做了反常的、当时没有解释的行为
  暗示了隐藏的动机或秘密

主线伏笔标注规则：
  如果这条伏笔与核心冲突直接相关，标注 is_backbone: true
  示例：
    "家族冤案的真正主谋" → is_backbone: true
    "灰蓝衫子宫女是谁"   → is_backbone: false
```

### 4.2 伏笔写入独立表

拿到 LLM 返回结果后：

```python
from memory.db import save_foreshadow, update_foreshadow_mention
from ulid import ULID

node_index = state["current_node_index"]
project_id = state["project_id"]

# 写入新伏笔（性质默认值，human_review 时用户可修改）
for f in result.get("planted_foreshadows", []):
    await save_foreshadow(project_id, {
        "foreshadow_id":       f.get("foreshadow_id") or str(ULID()),
        "project_id":          project_id,
        "foreshadow_type":     f.get("foreshadow_type", "event"),
        "surface_meaning":     f.get("surface_meaning", ""),
        "true_meaning":        f.get("true_meaning", ""),
        "planted_at_node":     node_index,
        "collected_at_node":   0,
        "misdirect_direction": f.get("misdirect_direction", ""),
        "mentioned_by":        f.get("mentioned_by", ""),
        "story_potential":     f.get("story_potential", ""),
        "mystery_type":        "normal",
        "is_backbone":         1 if f.get("is_backbone") else 0,
        "urgency":             "latent",
        "mention_count":       1,
        "ready_threshold":     3,
        "is_inferred":         0,
    })

# 扫描正文，更新已有词条的 mention_count
current_draft = state.get("current_draft", "")
async with get_connection() as conn:
    cursor = await conn.execute("""
        SELECT surface_meaning FROM foreshadow_entries
        WHERE project_id = ? AND mystery_type = 'normal'
          AND collected_at_node = 0
    """, (project_id,))
    existing = await cursor.fetchall()

for row in existing:
    if row["surface_meaning"] in current_draft:
        await update_foreshadow_mention(project_id, row["surface_meaning"])
```

---

## 五、`human_review_write_node.py` 修改

### 5.1 展示本节新增伏笔

正文预览之后展示：

```python
from memory.db import get_node_foreshadows

new_foreshadows = await get_node_foreshadows(project_id, node_index)

if new_foreshadows:
    lines = []
    for f in new_foreshadows:
        type_label = {
            "event": "事件型", "noun": "词条型", "behavior": "行为型"
        }.get(f["foreshadow_type"], "未知")
        backbone_label = "【主线】" if f["is_backbone"] else ""
        lines.append(
            f"  • {backbone_label}[{f['foreshadow_id'][:8]}] "
            f"{f['surface_meaning']}  {type_label}\n"
            f"    潜力方向：{f['story_potential'] or '待确认'}"
        )
    console.print(Panel(
        "\n".join(lines),
        title="🔖  本节伏笔记录",
        border_style="dim",
        expand=False,
    ))
```

### 5.2 伏笔性质确认（首次提取时逐条询问）

```python
for f in new_foreshadows:
    console.print(f"\n[dim]确认伏笔性质：[/dim] {f['surface_meaning']}")
    console.print("  [cyan][1][/cyan] 普通伏笔（系统管理推进节奏）")
    console.print("  [cyan][2][/cyan] 持续引力（贯穿全书，由我决定揭露时机）")
    nature = input("  请选择 [1/2，回车默认1]：").strip() or "1"

    if nature == "2":
        await conn.execute("""
            UPDATE foreshadow_entries
            SET mystery_type = 'permanent', urgency = 'latent'
            WHERE foreshadow_id = ?
        """, (f["foreshadow_id"],))
    else:
        console.print("  回收节奏：")
        console.print("  [cyan][A][/cyan] 尽快回收（下1-2批安排）")
        console.print("  [cyan][B][/cyan] 自定义阈值（出现N次后触发）")
        rhythm = input("  请选择 [A/B，回车默认A]：").strip().upper() or "A"

        if rhythm == "A":
            await conn.execute("""
                UPDATE foreshadow_entries
                SET urgency = 'ready', ready_threshold = 1
                WHERE foreshadow_id = ?
            """, (f["foreshadow_id"],))
        else:
            console.print("  阈值参考：3-5=普通伏笔  6+=贯穿多卷的重要线索")
            t = input("  请输入阈值 [回车默认3]：").strip()
            threshold = int(t) if t.isdigit() else 3
            threshold = max(1, min(threshold, 20))
            await conn.execute("""
                UPDATE foreshadow_entries
                SET ready_threshold = ?, urgency = 'latent'
                WHERE foreshadow_id = ?
            """, (threshold, f["foreshadow_id"]))

    await conn.commit()
```

---

## 六、`path_gen_node.py` 修改

构造 user_prompt 时注入待推进伏笔：

```python
from memory.db import get_pending_foreshadows

pending = await get_pending_foreshadows(state["project_id"])

pending_text = "\n".join(
    f"  • {f['surface_meaning']}"
    f"（已提及{f['mention_count']}次）"
    f"— {f['story_potential'] or '待确认'}"
    for f in pending
) if pending else "无"

# 注入 PATH_GEN_USER_TEMPLATE 对应占位符
# {pending_foreshadows_text} → pending_text
```

---

## 七、`human_review_batch_node.py` 修改

### 7.1 展示故事状态面板

```python
from memory.db import get_story_status

status = await get_story_status(state["project_id"])

lines = []

if status["permanent"]:
    lines.append("[dim]持续引力谜题：[/dim]")
    for f in status["permanent"]:
        lines.append(f"  • {f['surface_meaning']}  [dim][潜伏中][/dim]")

if status["backbone"]:
    lines.append("\n[dim]主线伏笔（未回收）：[/dim]")
    for f in status["backbone"]:
        lines.append(f"  • {f['surface_meaning']}  [dim][未揭露][/dim]")

if status["pending"]:
    lines.append("\n[dim]支线伏笔（待推进）：[/dim]")
    for f in status["pending"]:
        urgency_label = "[red]待引爆[/red]" if f["urgency"] == "ready" \
                        else "[yellow]蓄力[/yellow]"
        lines.append(f"  • {f['surface_meaning']}  {urgency_label}")

if lines:
    console.print(Panel(
        "\n".join(lines),
        title="故事状态",
        border_style="dim",
        expand=False,
    ))
```

### 7.2 选项简化为三个

```python
console.print("\n[cyan][1][/cyan] 继续规划下一批节点")
console.print("[cyan][2][/cyan] 开始揭露核心谜题")
console.print("[cyan][3][/cyan] 结束创作")

choice = input("\n请输入选项：").strip()

if choice == "1":
    return Command(
        update={"story_path": [], "path_approved": False,
                "current_node_index": 0, "creation_complete": False},
        goto="path_gen",
    )

elif choice == "2":
    # 展示所有 permanent 伏笔，让用户选择开始揭露哪一条
    permanent = status["permanent"]
    if not permanent:
        console.print("[dim]当前没有持续引力谜题。[/dim]")
        # 重新展示选项
    else:
        for i, f in enumerate(permanent):
            console.print(f"  [{i+1}] {f['surface_meaning']}")
        idx = input("选择要开始揭露的谜题编号：").strip()
        if idx.isdigit() and 1 <= int(idx) <= len(permanent):
            target = permanent[int(idx) - 1]
            # 从数据库里找到对应 foreshadow_id
            cursor = await conn.execute("""
                SELECT foreshadow_id FROM foreshadow_entries
                WHERE project_id = ? AND surface_meaning = ?
            """, (state["project_id"], target["surface_meaning"]))
            row = await cursor.fetchone()
            if row:
                await activate_permanent_foreshadow(row["foreshadow_id"])
                console.print(f"[green]✓[/green] 已将「{target['surface_meaning']}」纳入推进计划")
    # 选完后继续规划下一批
    return Command(
        update={"story_path": [], "path_approved": False,
                "current_node_index": 0, "creation_complete": False},
        goto="path_gen",
    )

else:  # choice == "3"
    # 检查未回收的主线伏笔
    if status["backbone"]:
        names = "、".join(f["surface_meaning"] for f in status["backbone"])
        console.print(
            f"\n[yellow]⚠[/yellow]  以下主线伏笔尚未回收：{names}\n"
            f"确认结束？[y/n]："
        )
        confirm = input().strip().lower()
        if confirm != "y":
            # 重新展示选项
            pass

    return Command(
        update={"creation_complete": True},
        goto="__end__",
    )
```

---

## 八、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `memory/schema.sql` | 新建 foreshadow_entries 表和两个索引 |
| `memory/db.py` | 新增 7 个函数（见第三章） |
| `graph/creation/nodes/bible_update_node.py` | 伏笔写入独立表；扫描正文更新 mention_count；Prompt 新增识别规则 |
| `graph/creation/nodes/human_review_write_node.py` | 展示本节伏笔；新增性质和回收节奏确认交互 |
| `graph/creation/nodes/path_gen_node.py` | 注入待推进伏笔 |
| `graph/creation/nodes/human_review_batch_node.py` | 展示故事状态面板；选项简化为三个 |

**不需要修改：** write_node、expand1/2、synopsis、blueprint_load、所有提取流节点、工具层。

---

*DeepNovel 伏笔系统优化文档 v2.0*
*去掉收尾模式，human_review_batch 简化为三个选项*
