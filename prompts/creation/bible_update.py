from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

BIBLE_UPDATE_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是一个故事档案管理员。
从刚写完的正文中提取关键信息，以结构化格式更新实体知识库。

【双坐标人物轴（与后续 EBD 专线配合）】
- EBD（ebd_to_protagonist，Pass 2 专用增量）：主观情感纽带 −100～+100，不在本 JSON 里改字段名，由系统根据正文另算。
- targeting_degree（本 Pass 须在 data_patch 写明）：**客观**针对度 / 结构威胁强度，整数 **0～100**（对主角形成制度、暴力、权势或信息压制的「冷酷事实」强度）。
  对反面角色、施害者、高位施压者、手握生杀权之人：必须给出或更新 targeting_degree，与正文压力匹配。
  对纯粹温情盟友（无结构威胁）：可填 0～15 或省略；中性路人可省略。

【精神阈值与因果账本（白皮书·演化层 / 档案回写）】
- character 类 entity_updates 可含 **emotional_capacity_delta**：整数，对人物卡 `mental_core.emotional_capacity`（0～100）的**增量**；**负数表示本章消耗精神阈值**（如 -12），正数极少用（恢复/扩容剧情）。无则省略或填 0。
- **karmic_ledger_updates**：本章新埋下的因果种子 / 引爆的前序种子（与伏笔可重叠但侧重「谁持有这颗雷、预计何时爆」）。
- **anchor_integrity_check**：对照创作前用户锚点，正文是否出现明显违背；不确定时 status 填 PASS。

【capabilities 状态追踪（补丁新增）】
检查本章正文，判断以下 capabilities 字段是否需要更新，在 entity_updates 对应角色的 capabilities_delta 字段中记录：

- **golden_finger.current_state**：本章是否使用了金手指？current_state 如何变化？是否触发了 cost_and_limit 中描述的代价？
- **signature_items**：本章是否有标志性物品丢失/损毁/被夺/被使用？哪个 item_id 的 current_status 需要更新？
- **unique_traits 的 double_edge**：本章是否触发了某个特质的负面效应？如果触发，相关角色的 emotional_capacity 是否应当额外消耗？
- **capabilities 暗流进度**：本章是否有任何情节使某条 capabilities 暗流（金手指暴露风险/代价积累/性格悲剧）更接近浮出水面？如果是，在 karmic_ledger_updates 中更新对应伏笔的 estimated_payoff。

无变化时 capabilities_delta 各子字段填 null，整个字段可省略。

**capabilities_delta 的信号来源**：以本章正文为准做推断；若正文中人物对金手指/物品/特质的使用或代价已有**可核对的明确描写**，应优先据此填写。**不要求** write 节点在正文外单独输出元数据——作者已将「capabilities 信号」内化进叙事时，你从正文读取即可。

只返回 JSON，不加任何前言。"""

BIBLE_UPDATE_USER_TEMPLATE = """## 刚完成的正文（第 {seq} 节：{node_name}）

{current_draft}

## 当前已知实体摘要

{entity_summary}

## 任务

从正文中提取实体变化和事件，按以下格式返回（只包含本节点有变化的内容）。

【动态人物生长（全局班底改由本章档案驱动，勿预设终局盟友/宿敌）】
1. 顶层必须输出 named_characters_in_scene：本节正文中**出现姓名且有戏份**的所有人物（含首次出场），勿漏。
2. 每个人物的 character 类 entity_updates 须尽量填写（基于**本章行为**，可覆盖旧认知）：
   - current_role：protagonist | ally | antagonist | neutral | unknown（仅反映本章观察，勿写死全书）
   - stance_to_protagonist：相对主角立场一句话（可随剧情修订）
   - chapter_behavior_note：本章行为/动机趋向≤40字，供下一节 expand 承接
   - targeting_degree：整数 0～100，**客观**权势/暴力/规则针对度（见 system）。反派与高位施压者**必填或随本章更新**；无威胁感的盟友可低或省略。
   - emotional_capacity_delta：可选整数。仅当正文明确写出强忍、濒临崩溃、精神透支等时填写负数消耗；无则省略。

card_type 取值：character（人物）| location（地点）| item（道具）| faction（势力）

ability_updates：只记录人物实际使用或明确拥有的能力（持有者验证）：
  add：该人物在本节实际使用、习得或获得的能力（非仅听说/见识）
  upgrade：该人物已有能力在本节突破升级
  deactivate：该人物已有能力被夺/损毁/封印

  能力定义：必须是人物通过训练/觉醒/获得道具等方式主动习得的技能或特殊手段。
  以下情况绝不记录为该人物的能力（应记入词条伏笔或忽略）：
    • 其他人物提到的能力（听说了≠拥有）
    • 敌人使用的能力（见识了≠掌握）
    • 规则文本中的惩罚/状态描述（如"失去静默""违反规则"这类规则概念）
    • 人物正在执行的普通行为（如"保持静默"是行为，不是能力）
  提取时必须确认：[谁] 在 [什么场景下] [实际习得或拥有] 了这个能力。

role_shift_events：仅在角色行为明显符合以下任意一条时才填写（不确定就不填）：
  • betrayal：主动伤害/出卖主角（不是误会，有明确的主动背叛行为）
  • opposition：主动站到了与主角对立的势力一方
  • concealment：隐瞒了影响主角命运走向的关键信息（非无意遗漏）

关键事件判断标准（满足任意一条即为 is_key_event=true）：
  • 主角和某配角共同面对了一个危机（并肩应对，非路过）
  • 某配角的行动直接改变了主角的处境（救了/坑了/帮了，有实质影响）
  • 主角为某配角付出了代价（资源/机会/受伤）
  • 某配角对主角说出了影响其决策的关键信息
key_event_participants：满足上述条件的配角名列表（主角本人不计入）
key_event_type：positive=帮助主角 / negative=伤害主角 / neutral=无明确倾向

【伏笔提取规则】

⚠️ 伏笔的定义（必须通过此标准才能入库）：
  「此刻种下，读者第一遍看以为是普通细节，未来某个出乎意料的事件中成为关键因素，回头看才恍然大悟。」

**强制排除（以下情况绝对不入库）：**
- 当前章节立即需要解决的功能道具（如救人用的药、当前任务目标的报酬）—— 这是当前任务，不是伏笔
- 世界设定的具体化词条（如力量体系的状态描述、激活条件列表）—— 这是设定说明，不是伏笔
- 已被正文正面解释清楚的内容 —— 已解释 = 没有暗示 = 不是伏笔
- `estimated_payoff` 只能写「未来某章提到」的内容 —— 必须能说清楚"在哪类事件中以什么方式引爆"，否则不入库

**入库三类伏笔（满足上述定义才能使用以下分类）：**

事件型（foreshadow_type=\"event\"）：
  某件发生的事埋下的暗示
  表面看是普通情节，回头看是关键铺垫
  示例：某人临死前握住主角手腕说了一句话，当时不明所以，后来揭示是传递了秘密

词条型（foreshadow_type=\"noun\"）：
  出现了这个世界独有的名词，被提及但未解释，且未来会以意想不到的方式成为关键
  区分规则（重要）：
    主角实际使用或拥有的 → 能力卡，不是伏笔
    别人提到但主角未拥有的，且有引爆潜力的 → 词条型伏笔
    仅是世界背景/设定词条，无特定引爆点 → 不入库

行为型（foreshadow_type=\"behavior\"）：
  某人物做了反常的、当时没有解释的行为
  暗示了隐藏的动机或秘密
  必须有具体异常细节，不能是"感觉有点奇怪"

主线伏笔标注规则：
  如果这条伏笔与核心冲突直接相关，标注 is_backbone: true

**数量控制**：每章入库伏笔建议 2～5 条，宁缺毋滥；第一章不超过 5 条。
karmic_ledger 膨胀会在后续事件生成中产生大量噪音，质量优先于数量。

新词条 urgency 默认 \"latent\"，mention_count 填 1。

返回 JSON：
{{
  "named_characters_in_scene": ["本节出现的全部有姓名人物"],
  "entity_updates": [
    {{
      "name": "标准名称",
      "card_type": "character",
      "aliases": ["别名1"],
      "current_role": "ally | antagonist | neutral | unknown（本章标签）",
      "stance_to_protagonist": "本章观察：相对主角立场一句话",
      "chapter_behavior_note": "本章行为/动机趋向≤40字",
      "targeting_degree": 65,
      "emotional_capacity_delta": 0,
      "mental_status_note": "本章是否出现精神阈值消耗、隐忍爆发或成熟度跃迁的线索（≤40字，无则空字符串）",
      "status_change": "当前物理/社会地位变化（如有）",
      "location_change": "当前位置变化（如有）",
      "new_relations": [
        {{"target": "对象名", "type": "关系类型", "note": "简短说明"}}
      ],
      "knowledge_gains": "获得了什么新信息（如有）",
      "hidden_info": "模型推断的未揭示秘密（如有）",
      "capabilities_delta": {{
        "golden_finger_state_change": "金手指状态变化描述（null表示无变化）",
        "items_status_change": ["item_id → 新状态（如：item_001 → 丢失；无变化则空数组）"],
        "trait_triggered": "触发的特质 double_edge 描述（null表示未触发）",
        "capability_undercurrent_progress": "是否有 capabilities 暗流更接近浮出水面（null或一句话描述）"
      }}
    }},
    {{
      "name": "天剑峰",
      "card_type": "location",
      "status_change": "控制势力变化（如有）",
      "note": "其他重要变化"
    }}
  ],
  "new_events": [
    {{
      "description": "本节点发生的关键事件（一句话，20字以内）",
      "characters": ["涉及人物名"],
      "locations": ["涉及地点名"],
      "items": ["涉及道具名"],
      "is_foreshadow": false,
      "foreshadow_id": null,
      "is_key_event": false,
      "key_event_participants": [],
      "key_event_type": "positive"
    }}
  ],
  "ability_updates": [
    {{
      "character_name": "角色名",
      "operation": "add（新增）| upgrade（升级）| deactivate（失效/损耗）",
      "ability": {{
        "name": "能力名称",
        "type": "功法|道具|身体素质|社会资源|知识|特异能力",
        "description": "具体效果（30字以内）",
        "level": "初步掌握|熟练|精通|极致",
        "source": "第X节，什么事件触发（如 upgrade/deactivate 则描述触发原因）",
        "limitation": "限制条件和代价（如无则留空）",
        "growth_potential": true
      }}
    }}
  ],
  "role_shift_events": [
    {{
      "character_name": "角色标准名",
      "trigger_type": "betrayal（主动伤害/出卖主角）| opposition（站到对立势力）| concealment（隐瞒影响命运的信息）",
      "trigger_description": "本节触发行为的一句话描述（15字以内）",
      "evidence": "正文中支持这一判断的具体描写（引用或转述，20字以内）"
    }}
  ],
  "planted_foreshadows": [
    {{
      "foreshadow_id": "F编号",
      "surface_meaning": "读者当时的理解/词条名称（5-20字）",
      "surface_expression": "正文中的具体文字（与 surface_meaning 二选一，向后兼容）",
      "foreshadow_type": "event（事件型）| noun（词条型）| behavior（行为型）",
      "is_backbone": false,
      "mentioned_by": "词条型专用：谁在哪个场景提到，如'老散修（节点1，临死前的交代）'",
      "story_potential": "这条伏笔可能推动故事的哪个方向（可能性，非确定答案）",
      "estimated_payoff": "【必填，否则不入库】预计在哪类事件中以什么方式引爆——须具体到场景类型或人物关系，如「主角进入荒原遭遇袭击时被迫激活，cost触发」；禁止填「未来某章」「有引爆潜力」等空话",
      "urgency": "latent（默认）| building（蓄力）| ready（待引爆）",
      "mention_count": 1,
      "planned_collection_node": 0,
      "true_meaning": "词条型可留空"
    }}
  ],
  "collected_foreshadows": ["已回收的伏笔ID列表"],
  "trait_interaction_changes": [
    {{
      "character_name": "角色名",
      "trigger_event": "触发特质叠加方式变化的事件（一句话）",
      "seq": 10,
      "suggested_interaction": {{
        "combo": ["特质1", "特质2"],
        "condition": "连续压迫后的反击等情境",
        "result": "叠加后的实际反应（如：表面极度平静，比任何愤怒都更危险）",
        "reader_expectation": "读者预期看到什么",
        "actual": "实际发生的"
      }}
    }}
  ],
  "karmic_ledger_updates": {{
    "seeds_planted": [
      {{
        "seed_id": "伏笔或因果种子标识（可与 foreshadow_id 呼应）",
        "description": "埋下的因/持有的雷",
        "holder": "持有叙事势能的角色",
        "estimated_payoff": "预计引爆时机或事件类型"
      }}
    ],
    "seeds_harvested": [
      {{
        "seed_id": "被引爆的前序种子标识",
        "actual_payoff": "实际引爆方式"
      }}
    ]
  }},
  "faction_shift_notes": ["势力立场因利益变化的简短描述（无则 []）"],
  "anchor_integrity_check": {{
    "status": "PASS 或 WARNING",
    "conflicts": ["若 WARNING：与用户锚点潜在冲突点"]
  }}
}}

trait_interaction_changes：仅当某角色经历重大事件后，其特质叠加方式发生本质变化时填写。
例如：长期压迫后，急躁+隐忍的互动从"急躁主导、隐忍压制"变为"表面平静、内心更危险"。
不确定则不填。"""

LAST_BATCH_ENDING_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是一个故事状态分析师。
根据最后一个节点的内容，提炼批次结尾的衔接状态。
只返回 JSON，不加任何前言。"""

LAST_BATCH_ENDING_USER_TEMPLATE = """## 本批最后一个节点（第 {seq} 节：{node_name}）

正文摘要：
{draft_excerpt}

当前实体摘要：
{entity_summary}

## 任务

提炼本批结尾状态，供下一批 path_gen 做硬衔接约束。

返回 JSON：
{{
  "protagonist_status": "主角当前一句话处境（不超过40字）",
  "unresolved_clues": [
    "未解决线索1（15字以内）",
    "未解决线索2（15字以内）",
    "未解决线索3（15字以内）"
  ],
  "next_emotional_tone": "下一批必须接续的情感基调（如：愤怒压抑中的隐忍、绝境中燃起希望）"
}}"""
