# DeepNovel 白皮书落地实现方案

> 依据《DeepNovel 核心架构思想白皮书（大乘圆满版）》、开发期无正式旧数据之前提，以及与现有提示词/管线的**融合策略**（契约优先、哲学并入、正交双维度）整理。  
> 可选二期：`world_tick`、`Karmic Ledger` 硬校验、`scene_router` 等见《下一代迭代深度分析报告》。

---

## 1. 目标与范围

**目标**：将白皮书六层落实为**统一数据契约 + 节点提示词 + 必要解析逻辑**，并与现有 EBD、伏笔、人性逻辑库、`path_gen` 拆章等能力**融合、不冲突**。

**范围**：

- **包含**：`schemas`、`prompts/creation` 核心模板、`graph/creation/nodes` 中与锚点/人物/世界/分卷/事件链/path/expand/write/bible 相关的节点、`memory/entity_db` 与展示层必要字段。
- **不包含（可选二期）**：`world_tick`、Karmic Ledger 硬校验、`scene_router`（本方案验收通过后可另立专项）。

---

## 2. 实施原则（必须遵守）

1. **契约优先**：任何 LLM 输出须先满足**当前节点已解析的 JSON 结构**；新增内容以**可选键**或**扩展 normalize** 接入，避免单节点 JSON 与全链路脱节。
2. **哲学并入、不整段替换**：外部「架构师版」提示词只合并进 **SYSTEM / 任务说明段**，不整体替换导致丢失 `genesis_variables`、`entity_updates` 等硬字段。
3. **正交双维度**：`karmic_resources`（四维）与 `resolution_method`（四法）**并列**，禁止用四维枚举替代四法。
4. **可删旧实现**：无遗产数据前提下，可删除 `behavioral_tendencies` 等已声明废弃且**全局替换完毕**的字段与分支。

---

## 3. 数据契约变更清单

### 3.1 `idea_forge` 输出（state）

| 动作 | 说明 |
|------|------|
| **保留** | `genesis_variables`（五字段）、`user_anchors`：`protagonist`、`opening_scene`、`world_rules`、`characters`、`emotional_lines`、`plot_events` |
| **可选新增** | `user_anchors.reader_catharsis_note`（一句话精神代偿，供下游注入）；或仅放在 SYSTEM 中要求模型内隐完成、不落库 |
| **SYSTEM 增强** | 并入「表层/深层翻译、锚点神圣、代偿识别」；**不要求**改变根 JSON 键名 |

### 3.2 人物卡（主角 / 草稿 / `entity_cards.data_json`）

| 字段 | 说明 |
|------|------|
| **新增** | `innate_traits: list[str]` |
| **新增** | `mental_core`：`{ intelligence, eq, meticulousness, emotional_capacity, forbearance }`（0～100 或统一档位，全项目一致） |
| **新增** | `maturity_note: str`、`current_emotional_drain: int`（可选） |
| **删除** | `behavioral_tendencies`（主角卡已禁；草稿与 `entity_db`、`expand1`、`__main__` 需一并移除引用） |
| **Pydantic** | `schemas/entity.py` 的 `CharacterCard` 与运行时 dict 对齐 |

### 3.3 `world_setting`

| 动作 | 说明 |
|------|------|
| **扩展** | 在 `basic_rules` / `power_structure` / 新增段落中体现：稀缺资源、3～5 股制衡、灰带缝隙、禁忌代价（白皮书动力层） |
| **若结构化** | 可增加 `gray_zone_ecology: list[str]` 等；与 `world_build_node` 解析、synopsis 合并逻辑同步修改 |

### 3.4 `story_arc_plan` 逐卷 JSON

| 动作 | 说明 |
|------|------|
| **评估** | `untouchable_characters` → 是否改为 `dynamic_gray_factions`（对象数组）或保留键名仅改语义（团队定稿后全文件替换） |
| **节奏** | `estimated_chapters`：默认 50～150；短篇/实验通过项目配置 `min_chapters_per_volume` 覆盖 |

### 3.5 `path_gen` 每节点

| 新增 | 说明 |
|------|------|
| `karmic_resources` | `["信息差","人际杠杆","时间差","地理优势"]` 的子集（多选） |
| `mental_lever` | 短文本：何种精神维度主导使用上述资源 |
| **保留** | `resolution_method`、`tension_*`、线头铁律、`_event_id` 等现有字段 |

### 3.6 `event_chain` 事件项

| 增强 | 说明 |
|------|------|
| `connection_to_previous` | 文案升级为「上一果如何成为本因」（因果继承） |
| **可选** | `payoff_hint` / 关联 `foreshadow_id` |

### 3.7 `bible_update` 输出

| 动作 | 说明 |
|------|------|
| **保留** | `named_characters_in_scene`、`entity_updates`（含 targeting/EBD 说明）、`new_events`、伏笔、`ability_updates`、`role_shift_events` 等现有结构 |
| **可选新增** | `entity_updates[].mental_status_note` 或写入 `chapter_behavior_note` 延伸 |
| **禁止** | 用简化 JSON 整体替换现有 schema |

### 3.8 `write` / `consistency`

| 动作 | 说明 |
|------|------|
| **合并** | 白皮书呈现层（平权、Show not tell、感官、幕间建议、松弛感非强制）入 `WRITE_SYSTEM`；与现有对话占比、张力写法去重合并 |
| **consistency** | 增加 Show not tell、空洞情绪词检查；「四维推导」在资源账本未上线前可写弱约束 |

---

## 4. 分阶段任务与文件清单

### Phase A — 契约定稿与全局检索基线（约 0.5 天）

- [ ] 定稿：`mental_core` 五键英文名、数值范围、分卷灰度字段最终命名。
- [ ] 全仓库检索：`behavioral_tendencies`、`untouchable_characters`（若改名）列出全部引用，形成勾选表。

**产出**：一页《字段名词表》+ 引用清单。

---

### Phase B — Schema 与存储（约 1～2 天）

| 文件 | 任务 |
|------|------|
| `schemas/entity.py` | 增加 `MentalCore`、`CharacterCard` 新字段；废弃字段在注释或文档中标明 |
| `memory/entity_db.py` | 读写卡片字段；移除 `behavioral_tendencies` 专用逻辑，改为 `innate_traits` / `mental_core` |
| `schemas/state.py` | 若有顶层 `user_anchors` 扩展，补可选字段说明 |

---

### Phase C — 提示词融合（按节点，约 2～3 天）

| 文件 | 任务 |
|------|------|
| `graph/creation/nodes/idea_forge_node.py` | `_IDEA_FORGE_SYSTEM` + `_IDEA_FORGE_JSON_TASK`：并入代偿/锚点哲学；**JSON 块保持现有键**；可选 `reader_catharsis_note` 若采用则 `_normalize_user_anchors` 放行 |
| `prompts/creation/world_build.py` | `WORLD_BUILD_*`：动力层资源/灰度/制衡；输出契约与 §3.3 一致 |
| `prompts/creation/story_direction.py` | 若 `EXTRACT_ALL` 仍生成旧主角结构，与新版人物卡对齐 |
| `prompts/creation/world_build.py` | `PROTAGONIST_*`、`CHAR_CARD_DRAFT_*`：新灵魂层 JSON；移除 `behavioral_tendencies` |
| `graph/creation/nodes/story_arc_plan_node.py` | `_VOLUME_JSON_SPEC`、`_norm_one_volume`、system 中与分卷/灰度/节奏相关段 |
| `prompts/creation/path_gen.py` | `PATH_GEN_SYSTEM` + USER：四维 + `mental_lever`；节点 JSON 示例增加两键 |
| `graph/creation/nodes/path_gen_node.py` | 透传/默认新字段；`utils/display` 若展示节点则增加两键 |
| `graph/creation/nodes/event_chain_gen_node.py` | user 模板中 `connection_to_previous` 等新文案 |
| `prompts/creation/expand1.py` | 注入 `mental_core` 块（若已有 `_mental_profile_block_for_expand1` 则扩展） |
| `prompts/creation/write.py` | 合并呈现层；删除重复条 |
| `prompts/creation/bible_update.py` | USER 增加精神/因果提取指引；**不改顶层 JSON 骨架** |
| `prompts/creation/consistency.py` | 检查项合并 |

---

### Phase D — 节点逻辑与 UI（约 1～2 天）

| 文件 | 任务 |
|------|------|
| `graph/creation/nodes/protagonist_card_node.py` | 新字段校验/清洗 |
| `graph/creation/nodes/bible_update_node.py` | 解析可选 `mental_*`；合并进 entity 写回 |
| `graph/creation/nodes/write_node.py` | 新人物草稿契约 |
| `__main__.py` / `utils/display.py` | 展示主角卡新字段；移除 `behavioral_tendencies` 展示 |

---

### Phase E — 联调与验收（约 1 天）

- 跑通：新项目 `idea_forge → … → path_gen → expand1 → write → bible_update` 至少一章。
- 抽检：JSON 能通过解析；path 节点含 `karmic_resources` + `mental_lever`；圣经仍写出 `entity_updates` 与伏笔。

---

## 5. 提示词融合操作细则（防冲突）

1. **idea_forge**：只改字符串常量 `_IDEA_FORGE_SYSTEM` / `_IDEA_FORGE_JSON_TASK`；**不删** `genesis_variables` 与 `user_anchors` 子结构示例。
2. **path_gen**：在【破局方式多样化】前后增加【白皮书：四维弹药与精神扣机】；节点示例 JSON **追加**两行，不删 `resolution_method`。
3. **write**：新段落插在【写作规范】或【人物表现禁忌】附近；与「对话占比」「六种张力」重复句合并为一条。
4. **bible_update**：只在「任务」与人物提取说明中增加指引；**返回 JSON 示例**仍以 `bible_update.py` 现有块为准。

---

## 6. 验收标准

| # | 标准 |
|---|------|
| 1 | `idea_forge` 输出仍含 `genesis_variables` + 完整 `user_anchors`，且锚点语义可追溯 |
| 2 | 人物卡含 `innate_traits` + `mental_core`，全链路不再依赖 `behavioral_tendencies` |
| 3 | `path_gen` 节点同时出现 `karmic_resources`（四维子集）与 `resolution_method`（四法之一） |
| 4 | `world_setting` 体现资源竞争与多股制衡（文案或结构化） |
| 5 | `bible_update` 仍能解析落库；EBD / targeting / 伏笔逻辑不回归 |
| 6 | 正文与审稿与 Show not tell、白皮书呈现层一致，规则无互相矛盾 |

---

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Prompt 过长 | 白皮书用 800～1200 字「压缩宪法」单文件，各节点只引用小节 |
| 模型漏填新键 | `path_gen_node` 对缺省 `karmic_resources` 填空列表或打日志警告 |
| 节奏 50 章硬伤短篇 | `min_chapters_per_volume` 或 `creation_mode` 在 `story_arc_plan` 读取 |

---

## 8. 建议执行顺序

`Phase A 定稿` → `Phase B schema + entity_db` → `Phase C idea_forge + world_build + protagonist/draft` → `Phase C story_arc + path + event_chain` → `Phase C expand + write + bible + consistency` → `Phase D 节点与 UI` → `Phase E 联调`

---

## 9. 关联文档

- `docs/DeepNovel 核心架构思想白皮书_最终篇.md` — 思想源本  
- `docs/DeepNovel_下一代迭代深度分析报告.md` — 资源账本、world_tick、EBD 路由等增强项  

---

*文档版本：与对话中「落地实现方案」合并稿一致，供开发排期与评审使用。*
