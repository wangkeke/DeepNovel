# DeepNovel 小说结局与持续引力系统 — 优化文档 v2

> 核心原则：系统只做记录和展示，不做决策。
> 何时结束、何时揭露核心谜题——判断权完全在用户手里。
> 系统不判断"该结束了"，只把故事状态呈现清楚。

---

## 一、结局的三件事（写作原则，不影响代码）

```
第一件：最重要的主线悬念必须有答案
  不是所有伏笔都回收，但主线的必须有交代

第二件：核心人物的命运从人性逻辑推导出来
  每个人按照自己的逻辑走到最后
  命运是逻辑的自然结果，不是作者的安排
  示例：
    野心家逻辑的反派 → 只会被外力终止，不会主动放弃
    复仇逻辑的主角 → 复仇完成后可能有空虚感
    设局逻辑的主角 → 得到了一切，但失去了什么

第三件：给读者一个情感落点
  情节上的圆满和情感上的共鸣是两回事
  结局需要一个让读者"停在那里"的时刻
  首尾呼应是最有力的情感落点——
  第一章的某个细节在最后一章以完全不同的方式出现
```

---

## 二、伏笔分层管理

### 2.1 四种伏笔状态

```
mystery_type 字段：
  'normal'    普通伏笔
              mention_count 正常累积
              urgency 自动升级：latent → building(3次) → ready(5次)
              注入 path_gen 的"待推进伏笔"列表
              示例：灰蓝衫子宫女的背后指使

  'staged'    阶段性谜题
              分批逐步揭露
              urgency 最高升到 building，不自动到 ready
              需要用户手动推进到下一阶段
              示例：某个分卷揭露的秘密

  'permanent' 持续引力型
              贯穿全书，每次接近它反而发现它更深
              mention_count 只记录"指向它的证据数量"
              不触发任何 urgency 升级
              永远不注入 path_gen
              只在故事状态面板静默展示
              只在用户主动选择"开始揭露核心谜题"时才安排揭露
              示例：《盗墓笔记》中的"终极"

is_backbone 字段：
  0  支线伏笔：参与 urgency 自动升级
  1  主线伏笔：与核心冲突直接相关
              mention_count 记录但不触发 urgency 升级
              不注入 path_gen 待推进列表
              只在故事状态面板展示
              用户手动标记回收
              示例：家族冤案真相、幕后主谋身份
```

### 2.2 持续引力与普通伏笔的本质区别

```
普通伏笔：答案在某处等着被找到
  触发模式：词条本身在正文中直接出现 → mention_count +1

持续引力：每次接近它反而发现它更深
  触发模式：指向它的支线证据被揭露 → 谜题更深一层
  正文中的出现都是间接指向，从未被直接说清楚
```

### 2.3 "指向证据"的防过热机制

持续引力本身不升级，但指向它的支线证据是普通伏笔，正常升级和回收：

```
"终极"不过热
    ↓ 指向它的支线证据正常循环
"青铜门后的秘密" → building → ready → 在某批被揭露
    ↓ 揭露时指向了"终极"，但终极本身依然未解
"吴邪父亲的真实身份" → 同上循环
    ↓
支线证据一条条回收，主线谜题一层层加深
主线谜题始终保持潜伏，直到用户主动决定揭露
```

---

## 三、伏笔性质识别时机

### 3.1 首次提取时询问用户

伏笔第一次被 `bible_update` 提取时，在 `human_review_write` 界面弹出询问：

```
╭─────────────────────────────────────────────╮
│ 🔖 检测到新伏笔：「终极的真相」              │
│                                             │
│ 这条伏笔的性质是？                           │
│ [1] 普通伏笔（会在某个节点揭露）             │
│ [2] 阶段性谜题（分几批逐步揭露）             │
│ [3] 持续引力（贯穿全书，由我决定揭露时机）   │
╰─────────────────────────────────────────────╯
```

用户选择后写入 `mystery_type` 字段，后续自动按对应规则处理。

### 3.2 主线伏笔的识别

`bible_update` 的 Prompt 新增说明：

```
伏笔提取时，如果这条伏笔与核心冲突直接相关
（即它的揭露会直接影响主角核心目标的达成或终结），
在输出里标注 is_backbone: true

示例：
  "家族冤案的真正主谋" → is_backbone: true
  "灰蓝衫子宫女是谁"   → is_backbone: false
```

---

## 四、`human_review_batch` 界面

每批节点完成后展示故事状态，选项完全由用户控制：

```
╭───────────────────────── 故事状态 ──────────────────────────╮
│                                                             │
│ 持续引力谜题：                                              │
│   • 终极的真相                        [permanent · 潜伏中] │
│                                                             │
│ 主线伏笔（未回收）：                                        │
│   • 家族冤案的真正主谋                [backbone · 未揭露]   │
│   • 丽妃掌握的女主秘密                [backbone · 未揭露]   │
│                                                             │
│ 支线伏笔（待推进）：                                        │
│   • 灰蓝衫子宫女的背后指使            [ready · 待引爆]      │
│   • 张嬷嬷知道的那件事                [building · 蓄力]     │
│                                                             │
╰─────────────────────────────────────────────────────────────╯

[1] 继续规划下一批节点
[2] 进入收尾模式（我觉得故事快结束了）
[3] 开始揭露核心谜题
[4] 结束创作
```

### 4.1 各选项的系统行为

```
[1] 继续（普通模式）：
    path_gen 正常工作
    注入支线伏笔的待推进列表
    不注入主线伏笔，不注入 permanent 谜题

[2] 收尾模式：
    novel_projects.story_mode 更新为 'ending'
    path_gen 行为改变：
      不引入新的主要人物或主线冲突
      优先安排主线伏笔回收
      节奏从"升级"转为"收束"
      支线伏笔继续正常回收

[3] 揭露核心谜题：
    用户选择哪条 permanent 伏笔开始揭露
    选定的伏笔临时转为 staged 类型
    纳入接下来批次的规划范围
    由用户控制揭露节奏，不自动加速

[4] 结束创作：
    检查是否有未回收的主线伏笔
    有则提示（不强制）：
      「以下主线伏笔尚未回收，确认结束？」
      [确认结束] [取消，继续写]
    用户确认后保存，生成完整小说文件
```

---

## 五、结局节点的情感落点设计

`expand1` 在收尾模式的节点里，输出新增字段：

```python
"emotional_landing": {
    "final_feeling": "读者读完最后一句话，心里停留的是什么感受",
    "echo_with_opening": "与全书第一章的哪个细节形成呼应（可以为空）",
    "character_final_state": {
        "人物名": "他/她最终停在了什么状态（不是情节结果，是内心状态）"
    }
}
```

---

## 六、数据库变更

```sql
-- foreshadow_entries 表新增两个字段
ALTER TABLE foreshadow_entries
    ADD COLUMN mystery_type TEXT DEFAULT 'normal';
    -- 'normal' / 'staged' / 'permanent'

ALTER TABLE foreshadow_entries
    ADD COLUMN is_backbone INTEGER DEFAULT 0;
    -- 0=支线伏笔 / 1=主线伏笔

-- novel_projects 表新增字段
ALTER TABLE novel_projects
    ADD COLUMN story_mode TEXT DEFAULT 'normal';
    -- 'normal'=普通模式 / 'ending'=收尾模式

ALTER TABLE novel_projects
    ADD COLUMN core_mystery TEXT DEFAULT '';
    -- 全书核心持续引力谜题描述（可为空）
```

---

## 七、`memory/db.py` 函数修改

### 7.1 `update_foreshadow_mention` 修改

```python
async def update_foreshadow_mention(
    project_id: str, surface_meaning: str
) -> str:
    """
    正文中出现已有伏笔词条时调用。
    根据 mystery_type 和 is_backbone 决定是否升级 urgency。
    返回新的 urgency。
    """
    async with get_connection() as conn:
        cursor = await conn.execute("""
            SELECT foreshadow_id, mention_count, mystery_type, is_backbone
            FROM foreshadow_entries
            WHERE project_id = ? AND surface_meaning = ?
        """, (project_id, surface_meaning))
        row = await cursor.fetchone()
        if not row:
            return "latent"

        # 主线伏笔和持续引力型：只更新 mention_count，不升级 urgency
        if row["is_backbone"] or row["mystery_type"] == "permanent":
            await conn.execute("""
                UPDATE foreshadow_entries
                SET mention_count = mention_count + 1,
                    updated_at = datetime('now')
                WHERE foreshadow_id = ?
            """, (row["foreshadow_id"],))
            await conn.commit()
            return "latent"

        new_count = row["mention_count"] + 1

        # 阶段性谜题：最高升到 building，不自动到 ready
        if row["mystery_type"] == "staged":
            new_urgency = "building" if new_count >= 3 else "latent"
        else:
            # 普通伏笔：正常升级
            new_urgency = (
                "ready"    if new_count >= 5 else
                "building" if new_count >= 3 else
                "latent"
            )

        await conn.execute("""
            UPDATE foreshadow_entries
            SET mention_count = ?, urgency = ?, updated_at = datetime('now')
            WHERE foreshadow_id = ?
        """, (new_count, new_urgency, row["foreshadow_id"]))
        await conn.commit()
        return new_urgency
```

### 7.2 新增 `get_story_status` 函数

```python
async def get_story_status(project_id: str) -> dict:
    """
    获取故事状态面板所需的全部数据。
    供 human_review_batch 展示使用。
    """
    async with get_connection() as conn:
        # 持续引力谜题
        cursor = await conn.execute("""
            SELECT * FROM foreshadow_entries
            WHERE project_id = ? AND mystery_type = 'permanent'
            ORDER BY created_at
        """, (project_id,))
        permanent = [dict(r) for r in await cursor.fetchall()]

        # 主线伏笔（未回收）
        cursor = await conn.execute("""
            SELECT * FROM foreshadow_entries
            WHERE project_id = ? AND is_backbone = 1
              AND collected_at_node = 0
            ORDER BY planted_at_node
        """, (project_id,))
        backbone = [dict(r) for r in await cursor.fetchall()]

        # 支线伏笔（待推进：building + ready，未回收）
        cursor = await conn.execute("""
            SELECT * FROM foreshadow_entries
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
            "permanent":  permanent,
            "backbone":   backbone,
            "pending":    pending,
        }
```

### 7.3 新增 `activate_permanent_foreshadow` 函数

```python
async def activate_permanent_foreshadow(foreshadow_id: str) -> None:
    """
    用户选择开始揭露某条持续引力谜题时调用。
    将 permanent 临时转为 staged，纳入正常推进流程。
    """
    async with get_connection() as conn:
        await conn.execute("""
            UPDATE foreshadow_entries
            SET mystery_type = 'staged',
                urgency = 'building',
                updated_at = datetime('now')
            WHERE foreshadow_id = ?
        """, (foreshadow_id,))
        await conn.commit()
```

---

## 八、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `memory/schema.sql` | foreshadow_entries 新增 mystery_type、is_backbone；novel_projects 新增 story_mode、core_mystery |
| `memory/db.py` | 修改 update_foreshadow_mention；新增 get_story_status、activate_permanent_foreshadow |
| `graph/creation/nodes/bible_update_node.py` | 伏笔提取时标注 is_backbone；Prompt 新增主线伏笔识别说明 |
| `graph/creation/nodes/human_review_write_node.py` | 新增伏笔性质询问界面（首次提取时弹出） |
| `graph/creation/nodes/human_review_batch_node.py` | 展示故事状态面板；实现四个选项的逻辑 |
| `graph/creation/nodes/path_gen_node.py` | 根据 story_mode 切换普通/收尾模式；收尾模式不引入新主线冲突 |
| `graph/creation/nodes/expand1_node.py` | 收尾模式下输出新增 emotional_landing 字段 |
| `prompts/creation/path_gen.py` | 新增收尾模式的 Prompt 约束段落 |
| `prompts/creation/expand1.py` | 新增收尾模式下的 emotional_landing 输出要求 |

**不需要修改：** write_node、synopsis_node、blueprint_load_node、所有提取流节点、工具层。

---

*DeepNovel 小说结局与持续引力系统优化文档 v2.0*
*去掉了故事结束判断逻辑和故事驱动方式选择，结束权完全交给用户*
