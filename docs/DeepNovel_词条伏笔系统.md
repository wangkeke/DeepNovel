# DeepNovel 词条伏笔系统 — Cursor 修改建议

> 本文档描述将"词条"归入伏笔体系的完整修改方案。
> 核心原则：词条是伏笔的名词子类，不单独建系统，扩展现有 ForeshadowEntry。

---

## 一、数据模型修改

### 1.1 `schemas/blueprint.py` — ForeshadowEntry 扩展

```python
class ForeshadowEntry(BaseModel):
    # ── 原有字段，保持不变 ──────────────────────────────────
    foreshadow_id: str
    surface_meaning: str
    true_meaning: str           # 词条型可以为空，等后续节点确定真实含义
    planted_at_node: int
    collected_at_node: int      # 0 = 尚未安排回收节点
    misdirect_direction: str
    truth_node_ref: str
    is_inferred: bool = False

    # ── 新增字段 ─────────────────────────────────────────────
    foreshadow_type: str = "event"
    # "event"    事件型：某件发生的事埋下的暗示
    # "noun"     词条型：以名词形式出现、尚未解释的伏笔（功法/地名/规则/势力等）
    # "behavior" 行为型：人物的某个反常行为埋下的暗示

    mentioned_by: str = ""
    # 词条型专用：谁在哪个场景里提到了这个词条
    # 格式："老散修（节点1，临死前的交代）"

    story_potential: str = ""
    # 这条伏笔可能推动故事发展的方向（不是确定答案，是可能性）
    # 示例："可能是主角未来的成长方向/某势力的核心秘密/解开身世的线索"

    urgency: str = "latent"
    # "latent"  潜伏：刚埋下或出现次数少，暂不需要推进
    # "building" 蓄力：已出现多次，读者期待值上升，近期需要给出部分回应
    # "ready"   待引爆：时机成熟，应在接下来的批次里安排重要揭示或冲突

    mention_count: int = 1
    # 在正文中被提及的总次数，每次出现自动加1
    # 驱动 urgency 自动升级的依据之一
```

---

### 1.2 `schemas/state.py` — CreationState 无需修改

伏笔地图已经在 State 里，词条型伏笔直接进同一个列表，不新增字段。

---

## 二、数据库修改

### 2.1 `memory/schema.sql` — 伏笔相关表扩展

如果项目中有独立的伏笔表（foreshadow_entries），添加新字段：

```sql
ALTER TABLE foreshadow_entries ADD COLUMN foreshadow_type TEXT DEFAULT 'event';
ALTER TABLE foreshadow_entries ADD COLUMN mentioned_by TEXT DEFAULT '';
ALTER TABLE foreshadow_entries ADD COLUMN story_potential TEXT DEFAULT '';
ALTER TABLE foreshadow_entries ADD COLUMN urgency TEXT DEFAULT 'latent';
ALTER TABLE foreshadow_entries ADD COLUMN mention_count INTEGER DEFAULT 1;
```

---

## 三、bible_update_node 修改

### 3.1 扩展伏笔提取逻辑

`bible_update_node` 在提取伏笔时，在现有的事件型伏笔提取基础上，新增词条型和行为型的识别：

**Prompt 新增说明（写入 BIBLE_UPDATE_USER_TEMPLATE 的伏笔提取部分）：**

```
【伏笔提取规则扩展】

除了原有的事件型伏笔，还需要识别以下两类：

词条型伏笔（foreshadow_type = "noun"）：
  识别特征：
    • 出现了这个世界独有的名词（功法名/地名/势力名/规则名/传说）
    • 被人物提到但没有完整解释，留有神秘感
    • 读者看到这个词会产生"这是什么"的疑问
  
  区分规则（重要）：
    • 某人物实际使用或拥有的能力 → 记入能力卡，不是词条伏笔
    • 某人物提到但主角未拥有的能力/事物 → 词条型伏笔
    • 示例："功德金光"由老散修提及，主角未拥有 → 词条型伏笔
    • 示例："淬体诀"由主角实际修炼 → 能力卡，不是词条伏笔

行为型伏笔（foreshadow_type = "behavior"）：
  识别特征：
    • 某人物做了一个反常的、当时没有解释的行为
    • 这个行为暗示了某个隐藏的动机或秘密

对所有新提取的伏笔，额外填写：
  story_potential：这条伏笔可能推动故事的哪个方向
  urgency：初始默认"latent"
  mention_count：本节是第几次出现（新词条填1，已有词条自动加1）
```

### 3.2 mention_count 自动更新逻辑

`bible_update_node` 在处理已有伏笔时，检查本节正文是否再次提到了已记录的词条型伏笔：

```python
# 伪代码，在 bible_update_node.py 里实现

# 1. 获取所有已记录的词条型伏笔
existing_noun_foreshadows = [
    f for f in current_foreshadows
    if f["foreshadow_type"] == "noun"
]

# 2. 检查本节正文里是否出现了这些词条的名称
for foreshadow in existing_noun_foreshadows:
    noun_name = foreshadow["surface_meaning"]  # 词条名称
    if noun_name in current_draft:
        foreshadow["mention_count"] += 1
        # 3. 根据 mention_count 自动升级 urgency
        foreshadow["urgency"] = _calc_urgency(foreshadow["mention_count"])

def _calc_urgency(mention_count: int) -> str:
    if mention_count >= 5:
        return "ready"      # 出现5次以上，必须安排回收
    elif mention_count >= 3:
        return "building"   # 出现3次以上，读者期待值上升
    else:
        return "latent"     # 出现次数少，继续潜伏
```

---

## 四、path_gen_node 修改

### 4.1 注入待处理伏笔

`path_gen_node` 在规划下一批节点路径时，把处于"蓄力"和"待引爆"状态的伏笔推送进来：

**在 `path_gen_node.py` 里，构造 user_prompt 时新增：**

```python
# 从伏笔地图里筛选需要推进的伏笔
pending_foreshadows = [
    f for f in state.get("foreshadow_map", [])
    if f.get("urgency") in ("building", "ready")
    and f.get("collected_at_node", 0) == 0  # 尚未回收
]

# 按紧迫度排序
pending_foreshadows.sort(
    key=lambda f: {"ready": 0, "building": 1}.get(f.get("urgency"), 2)
)

# 注入 Prompt
pending_foreshadows_text = "\n".join(
    f"  [{f['urgency']}] {f['surface_meaning']} "
    f"（已提及{f['mention_count']}次）— {f['story_potential']}"
    for f in pending_foreshadows[:5]  # 最多注入5条，避免上下文过长
) if pending_foreshadows else "无"
```

**PATH_GEN_USER_TEMPLATE 新增段落：**

```
## 待推进的伏笔线索

以下伏笔已积累足够期待值，本批节点路径中需要安排相应处理：

{pending_foreshadows_text}

处理要求：
  [ready] 待引爆：必须在本批节点里安排一次重要揭示、激活或冲突
  [building] 蓄力：在本批节点里至少有一次侧面触及或部分回应
  
注意：不需要完整解释词条，可以只是推进一步、让读者感受到故事在向前走。
```

---

## 五、human_review_write_node 修改

### 5.1 在章节审核界面展示词条伏笔提取结果

在现有的能力使用检测之后，新增词条伏笔的展示：

```python
# 筛选本节新提取的词条型伏笔
new_noun_foreshadows = [
    f for f in new_foreshadows
    if f.get("foreshadow_type") == "noun"
]

if new_noun_foreshadows:
    console.print(Panel(
        "\n".join(
            f"  • [cyan]{f['surface_meaning']}[/cyan]"
            f"  [dim]由 {f['mentioned_by']} 提及[/dim]\n"
            f"    潜力方向：{f['story_potential']}"
            for f in new_noun_foreshadows
        ),
        title="🔖  新增词条伏笔",
        border_style="dim",
        expand=False,
    ))
```

### 5.2 用户可以在审核时补充 story_potential

在展示词条伏笔后，给用户一个可选的补充机会：

```
🔖  新增词条伏笔
  • 功德金光  由老散修提及
    潜力方向：（模型推测）可能与主角的修炼方向有关

[可选] 为以上词条补充故事方向？[y/n]：
```

用户选 y 可以直接修正或补充 `story_potential`，比模型的推测更准确。选 n 保持模型推测，继续。

---

## 六、需要修改的文件总结

| 文件 | 改动内容 |
|---|---|
| `schemas/blueprint.py` | ForeshadowEntry 新增 5 个字段 |
| `memory/schema.sql` | foreshadow_entries 表新增 5 列（如有独立表） |
| `graph/creation/nodes/bible_update_node.py` | 新增词条型/行为型伏笔识别，mention_count 自动更新，urgency 自动升级 |
| `graph/creation/nodes/path_gen_node.py` | 注入 pending_foreshadows，PATH_GEN_USER_TEMPLATE 新增待推进伏笔段落 |
| `graph/creation/nodes/human_review_write_node.py` | 新增词条伏笔展示和用户补充 story_potential 的交互 |
| `prompts/creation/bible_update.py` | BIBLE_UPDATE_USER_TEMPLATE 新增词条型伏笔识别规则和区分说明 |
| `prompts/creation/path_gen.py` | PATH_GEN_USER_TEMPLATE 新增待推进伏笔段落 |

**不需要修改的文件：**
所有 schema 文件（除 blueprint.py）、图结构文件、提取流相关文件。

---

*DeepNovel 词条伏笔系统 Cursor 修改建议 v1.0*
