"""补丁 I：角色叙事流记忆引擎 — 提示词（与《补丁文档 I》正文对齐，勿随意改写措辞）。"""
from __future__ import annotations

from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

# ── 轨道 A：在场角色显性提取（单路径正文 · 可多角色一批）────────────────────────
INNER_STREAM_BATCH_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是网文场记，只根据 user 中的「本段正文」做事实提取。
user 中会给出【本事件规划类型 event_result_type / protagonist_tick_type】：生成 inner_slice 时**语气**须与之协调——
B 型可写对主线碎片的疑虑与追踪欲；A 型偏阅历与人情落地，忌篇篇阴谋论；C 型偏压力与被迫应对。
只输出 JSON，无前言。JSON 结构固定为：
{"slices":[{"character_name":"标准姓名","inner_slice":"第一人称内心日记1-2句"}]}
若正文未出现某候选角色，不要为其生成条目。不得编造正文未写的情节。"""

INNER_STREAM_BATCH_USER = """【任务：生成角色内心叙事流切片】
请阅读刚刚完成的正文，对下列**仅当其在正文中有台词、动作或明确在场描写**的角色，分别用该角色【第一人称】写 1-2 句话的内心日记。
必须涵盖（若未发生则跳过）：1.身之所至 2.耳之所闻 3.身之所历 4.心之所向。

🚨 【最高戒律：严禁脑补与过度推演 (STRICT FACTUAL GROUNDING)】 🚨
1. 100%忠实原文：只提取正文中【已发生】的遭遇和角色【确实产生】的内心想法。绝不允许脑补未来计划或未写出的关联！
2. 保留实体：严禁使用“那个人/那个东西”，必须保留具体的专有名词（如：独臂傀儡师、血玉）。

## 本路径 ID
{path_id}

## 本事件规划语境（补丁 J · 语气指引；不得覆盖正文事实）
{event_planning_context}

## 候选角色名（仅在为真出场时输出一条；勿为未出场者编造）
{character_names}

## 本路径正文（刚由 write 生成）
{draft}

请输出 JSON：{{"slices":[{{"character_name":"…","inner_slice":"…"}}]}}。无合格角色时 slices 为 []。"""

# ── 事件级记忆固化 ───────────────────────────────────────────────────────────
CONSOLIDATION_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你只合并内心叙事切片为一段「自传式」长篇记忆增量，输出 JSON：
{{"event_memoir":"不超过三句话的第一人称事件回忆录，须保留所有关键实体名词；须与「近期长篇摘录」在人称与时间线上衔接，避免机械重复原句"}}
无有效输入时 event_memoir 可为「无」。"""

CONSOLIDATION_USER = """【任务：角色事件级记忆固化 (Event-level Consolidation)】
以下是【{character_name}】在刚结束的本段叙事中积累的内心叙事切片。请合并为一段不超过 3 句话的“事件回忆录”，并看作压入 long_term_stream 的**自传增量**（不是孤立金句）。

🚨 【保真合并铁律 (Entity Lock)】 🚨
1. 提取锁：识别这几条切片中的所有关键实体（具体人名、地名、特殊物品名）。
2. 保真锁：在精简句子时，【绝对不允许】遗漏或删减任何一个关键实体名词！
3. 视角锁：保持第一人称，输出带有因果关系、体现该角色在该事件最终得失的内心独白。
4. 承接锁：参考下方「近期长篇自传摘录」，若存在则与之情绪与事实连续；若无则忽略本条。

## 近期 long_term_stream 摘录（仅供衔接；勿整段照抄）
{long_term_recent}

## 切片（按时间顺序）
{slices_text}

请严格按系统说明返回 JSON。"""

# ── 轨道 B：World Tick 后台叙事（性格驱动锁 · 补丁 I 文档第三节修订）──────────
OFFSCREEN_TICK_USER = """【任务：NPC 离线行为推演与叙事流生成】
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

🚨 【事实锚点：须与 World Tick 本条议程自洽 (STRICT FACTUAL GROUNDING)】 🚨
1. 下列议程句为「世界自转」推演结果，你的内心叙事须与之相容，勿编造与之下矛盾的行动。
2. 勿引入上文未出现的专有实体名；须用具体名称，禁用「那个人/那东西」。

## World Tick 独立议程（推演锚点）
- 当前压力：{current_pressure}
- 当前机会：{current_opportunity}
- 无主角时自然行动：{natural_action}
- 行动波及：{action_ripple}"""

OFFSCREEN_TICK_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你只输出 JSON：{{"backroom_line":"1~2句第一人称内心叙事流，须符合性格驱动铁律、身份资源边界与 user 中的议程锚点"}}
禁止输出数组以外包裹。"""

# ── POV 隔离排版（由 utils.narrative_memory 组装变量后嵌入 write/expand）──────
POV_MEMORY_PANEL_TEMPLATE = """━━━━━━━━━━━━━━━━━━━━━━━━━━━
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
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
