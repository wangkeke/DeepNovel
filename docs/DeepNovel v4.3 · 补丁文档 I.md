# 🚀 DeepNovel v4.3 核心架构升级：【多智能体视角：角色叙事流记忆引擎】

## 🎯 一、 架构目标 (Objective)
废弃传统的“全局状态列表（State Tracking）”和“死板的 JSON 差分提取”。将小说的信息差、状态流转、人物动机全部下放到**「角色的内心叙事流 (Append-only Narrative Stream)」**中。
引入【在场提取 vs 离线推演】的双轨制，结合【事件级记忆固化】与【POV 视觉隔离排版】，彻底解决长篇小说生成中的“设定遗忘”、“上帝视角穿帮”、“NPC时间静止”以及“Token上下文爆炸”四大致命痛点。

---

## 💾 二、 数据结构升级 (Data Structure)
**目标文件**：角色档案的定义文件（如 `schemas/state.py` 或数据库 Entity Model）
为每个角色卡（Entity Card）新增以下记忆栈字段，**不设状态位，只做追加（Append-Only）**：

```python
short_term_stream: list[str] =[]   # 短期叙事流切片（当前事件内的微观内心独白/动作记录）
long_term_stream: list[str] =[]    # 长期自传体记忆（事件结束时合并而成的宏观经历）
```

---

## 🛤️ 三、 双轨记忆更新机制 (Dual-Track Memory Update)

### 轨道 A：在场角色显性提取（On-screen Extraction）
**触发时机**：每条路径 (Path) 写完后。
**执行节点**：`narrative_extract_node` (或对应的路径提取节点)
**操作说明**：针对**本段正文实际出场的角色**，调用 LLM 生成 1-2 句话的内心叙事切片，追加到其 `short_term_stream`。

**【强制提取 Prompt 模板】**：
```markdown
【任务：生成角色内心叙事流切片】
请阅读刚刚完成的正文，用【{character_name}】的第一人称视角，写 1-2 句话的内心日记。
必须涵盖（若未发生则跳过）：1.身之所至 2.耳之所闻 3.身之所历 4.心之所向。

🚨 【最高戒律：严禁脑补与过度推演 (STRICT FACTUAL GROUNDING)】 🚨
1. 100%忠实原文：只提取正文中【已发生】的遭遇和角色【确实产生】的内心想法。绝不允许脑补未来计划或未写出的关联！
2. 保留实体：严禁使用“那个人/那个东西”，必须保留具体的专有名词（如：独臂傀儡师、血玉）。
```

### 轨道 B：离线角色暗中推演（Off-screen Simulation）
**触发时机**：`World Tick` 阶段（世界时钟步进时）。
**执行节点**：`event_chain_gen` / `world_tick_node`
**操作说明**：针对**未在正文出场、但带有独立议程 (Agenda) 的反派/配角**。`World Tick` 必须**【同时读取该角色的长期记忆（`long_term_stream`）+ 该角色档案（Entity Card / bible.characters）中的性格、阵营与智力设定】**，推演其幕后行动，并生成**第一人称 1～2 句**后台叙事流，追加到该角色的 `long_term_stream`。

**【性格驱动锁 (Persona-Driven Engine)】**：禁止「套路化扁平思维」——不得一遇摩擦就默认「怀恨报仇、立刻打杀」。推演结果须由**底层性格（Persona）**与**核心诉求**驱动，与身份、资源边界一致。

**【强制推演 Prompt 模板】**（注入到 Tick 节点离线叙事流 LLM）：
```markdown
【任务：NPC 离线行为推演与叙事流生成】
你现在扮演角色：【{character_name}】。
- 你的性格底色与智谋水平：【{character_personality_and_traits}】
- 你的核心目标与所属阵营：【{character_faction_and_goals}】
- 你的近期记忆与恩怨：【{long_term_stream}】

请根据当前的“性格底色”，结合“近期记忆”，推演你在这个时间点（幕后）正在盘算或采取什么行动？并用第一人称写 1~2 句话的内心叙事流切片。

🚨 【性格驱动铁律 (Persona-Driven Rule)】 🚨
1. 严禁无脑复仇：绝对不允许遇到恩怨就只会推导“报仇/打杀”。必须严格符合你的【性格与智谋】！
   - 若你生性多疑，你应选择“暗中调查”。
   - 若你唯利是图，你应寻找“如何利用对方赚钱”。
   - 若你胆小怕事，你应选择“躲避或求饶”。
2. 匹配身份资源：你的行动必须受限于你的身份。底层混混只能去打听消息，高层反派可以调动兵马，严禁越级调用不属于你的资源。
```
（实现上可在上述模板后追加 **World Tick 本条议程** 字段：`current_pressure` / `current_opportunity` / `natural_action` / `action_ripple`，与主 Tick JSON 对齐。）

---

## 🧹 四、 事件级记忆固化 (Event-level Consolidation)
**触发时机**：当【当前事件 (Event) 的所有路径全部写完】、进入事件级结算时。
**执行节点**：`bible_update_node` 
**操作说明**：对本事件内出场角色的 `short_term_stream` 触发**带实体锁的合并**，随后清空短记忆栈。

**【强制合并 Prompt 模板】**：
```markdown
【任务：角色事件级记忆固化 (Event-level Consolidation)】
以下是【{character_name}】在刚结束的事件中积累的内心叙事切片。请合并为一段不超过 3 句话的“事件回忆录”。

🚨 【保真合并铁律 (Entity Lock)】 🚨
1. 提取锁：识别这几条切片中的所有关键实体（具体人名、地名、特殊物品名）。
2. 保真锁：在精简句子时，【绝对不允许】遗漏或删减任何一个关键实体名词！
3. 视角锁：保持第一人称，输出带有因果关系、体现该角色在该事件最终得失的内心独白。
```
*(合并后 append 到 `long_term_stream`，并将 `short_term_stream` 清空置为 `[]`)*。

---

## 🎭 五、 上下文按需注入与 POV 隔离排版 (Context Injection)
**目标文件**：`prompts/creation/write.py` 和 `expand.py`
**操作说明**：组装 System Prompt 时，只拉取被蓝图确认**“在当前场景出场”**的角色阅历，并进行滑动窗口过滤。

**【注入过滤策略（防 Token 爆炸与焦点稀释）】**：
1. **主角注入**：`short_term_stream` (全部) + **`long_term_stream[-5:]` (绝对禁止全量注入，只取最近 5 个事件的滑动窗口！更久远的底色由任务系统托底)**。
2. **对立角色注入**：`short_term_stream` (全部) + `long_term_stream` 中**仅与主角恩怨强相关的条目** (过滤掉无关的生平事迹)。

**【POV 隔离排版模板】**（请直接修改组装逻辑）：
```markdown
━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎭 【本场出场角色·内心叙事流认知面板】
━━━━━━━━━━━━━━━━━━━━━━━━━━━
注意：本章采用【{main_pov_character}】POV视点。请严格遵守信息不对称原则！主角绝对不能未卜先知其他角色的私密阅历！

🟢 【主视角：{main_pov_character} 的近期叙事流】
(这是他走到这一步的心路历程与已知情报，请以此驱动他的动作！)
[近期长记忆]：{filtered_mc_long_term}
[刚刚发生]：{mc_short_term}

🔴 【对台戏角色：{opposing_character}】
(主角【绝对不知道】他内心的以下盘算，请用以刻画其反馈动作，严禁主角说破！)
[他的秘密与恩怨]：{filtered_oppo_long_term}
[当前状态]：{oppo_short_term}

🔴 【突发介入角色：{surprise_character}】
(主角可能早忘了他，但他一直记着以下仇恨/目的)[他的暗中盘算(Tick推演)]：{surprise_long_term}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## ✅ 六、 验收标准 (Definition of Done)
1. **防幻觉验证**：提取的短切片中，绝对不包含正文中未实际写出的推理或未来动作。
2. **防遗漏验证**：事件级合并发生后，原短切片中的特定物品名（如：碎玄链、伪灵脉碎片）必须 100% 保留在生成的长自传中。
3. **离线推演验证**：确认 `World Tick` 生成的反派暗中推演记忆，能被正确压入其 `long_term_stream` 且不污染主角的记录；且推演须显式消费 **Entity Card 性格字段 + `long_term_stream` 窗口**，避免「一律报仇」的扁平套路。
4. **防上帝视角验证**：生成正文时，林北（主角）的心理活动与台词中，绝对不能泄露 🔴 对台戏角色面板里的专属情报。
5. **Token 稳定验证**：主角的长记忆注入必须截断为 `[-5:]`，确保进入长篇中后期时 API 负载与上下文窗口保持恒定。