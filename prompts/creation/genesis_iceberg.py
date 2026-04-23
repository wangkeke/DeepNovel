# 开篇种子点燃 + 冰山两段式反推（cast∥world → synopsis）

from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from prompts.creation.synopsis import PLATFORM_MACRO_HINTS, GENRE_LEXICON_SLUG_HINT

ICEBERG_PROMPT4_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是 DeepNovel 冰山反推引擎（文档 PROMPT 4）。
你只根据给定的 **world_archive** 与 **protagonist_archive**（及变量配方）推导开篇瞬间的结构化结果，
禁止凭题材套路另编主角姓名、性别、职衔或替换叙事主视角。

须完成：World Tick at Opening → Protagonist Tick at Opening → Opening Collision（含质量校验）→ Iceberg Undercurrents（含来源三：capabilities 暗流检查）→ opening_tone。
推导须可追溯到档案中的势力/处境/人性字段；禁止输出散文化「宏观构思」替代 JSON。

## 冰山水面下的结构——第四步补充：来源三（capabilities 引发的潜伏危机）

在原有两个暗流来源检查（势力 resource_claim 冲突 + 角色 independent_agenda 冲突）完成后，增加第三个检查：

**检查点A：金手指的暴露风险**
- protagonist_archive.capabilities.golden_finger.exposure_risk 描述的后果，是否本身构成一条暗流？
- 在开篇中的哪个细节，可能被未来的敌人/觊觎者注意到但还没引发警觉？

**检查点B：金手指代价的积累危机**
- golden_finger.cost_and_limit 描述的代价，是否会在某个关键节点爆发？
- 在开篇中是否有某个细节暗示了代价的存在，但读者此刻以为只是普通描写？

**检查点C：金手指与性格的悲剧张力**
- golden_finger.gf_type 和主角 innate_traits 之间，是否存在天然的悲剧组合？
- 例如：等价交换金手指 + 护短性格 → 必然有一天主角需要献祭他最在意的人换取力量
- 这种张力从开篇就注定，是最深的冰山层

**检查点D：核心配角的 capabilities 构成的外部威胁**
- 反派/关键配角的 golden_finger / unique_traits，是否会在未来某节点对主角构成其完全没有预见的致命威胁？
- 在开篇中是否有某个不经意的细节，日后回头看会发现那正是此能力的隐性显现？

**capabilities 暗流的双重标准**（必须遵守）：
- 对初读的读者：surface_trace 只是普通细节，不会引起警觉
- 对回头重读的读者：会恍然大悟「原来这里已经在说了」
- 禁止让 surface_trace 太明显（第一遍就猜到），也禁止太隐晦（引爆时读者没有共鸣）

只返回一个 JSON 对象，键名与层级必须与用户消息「输出规范」完全一致，不要 markdown 围栏，不要前言。
"""

ICEBERG_PROMPT4_USER = """
## world_archive（JSON）
{world_archive_json}

## protagonist_archive（主角档案全文 · 叙事主视角唯一来源）
{protagonist_archive_text}

## 题材（用户原文）
{genre_request}

## 变量配方（针对度/感情度/人性逻辑等）
{variables_block}

## 用户额外意见（可空）
{extra_feedback}

## 输出规范（只输出下列 JSON；键名保持一致）
{{
  "world_tick_at_opening": {{
    "active_faction": "正处于行动节点的势力（与 world_archive 权力结构可对应；无则写具体衙门/派系称谓）",
    "natural_action": "这股势力此刻自然采取的行动",
    "pressure_radius": "压力波及到哪个圈层/位置"
  }},
  "protagonist_tick_at_opening": {{
    "position": "主角所在圈层与具体处境（须与档案 world_position/职衔/性别一致）",
    "deepest_need": "此刻最在意的东西（来自档案推导）",
    "core_principle": "此刻遵守的核心生存原则",
    "emotional_anchor": "感情度投射的情感对象；低感情度可为 null"
  }},
  "opening_collision": {{
    "created_detail": "被创造出的交汇细节（须同时服务世界议程与主角刚需）",
    "world_meaning": "该细节对世界的意义",
    "protagonist_meaning": "该细节对主角的意义（须与主角意义不同）",
    "forced_entry": "主角被什么逼进交汇点",
    "principle_challenged": "被挑战的本能或原则",
    "quality_check": "三个条件是否全部满足（是/否 + 一句说明）"
  }},
  "iceberg_undercurrents": [
    {{
      "source": "暗流来源（势力资源矛盾 / 角色独立议程冲突 / 金手指代价积累 / 金手指暴露风险 / 性格悲剧张力 / 配角能力外部威胁）",
      "capability_source": {{
        "character_id": "涉及的角色 character_id（非 capabilities 来源则填 null）",
        "capability_field": "golden_finger / unique_traits / signature_items（非 capabilities 来源则填 null）",
        "tension_type": "暴露风险 / 代价积累 / 性格悲剧 / 外部威胁 / null"
      }},
      "surface_trace": "在开篇中几乎察觉不到的痕迹（双重标准：初读普通细节，回读恍然大悟）",
      "estimated_emergence": "大致在第几卷/阶段浮出水面"
    }}
  ],
  "opening_tone": "由以上推导自然呈现的开篇基调（非口号）"
}}
"""


GENESIS_OPENING_USER = """
## 题材（用户原文）
{genre_request}

## 目标平台
{platform_style}
{platform_hint}

{locked_protagonist_section}

{iceberg_prompt4_user_note}

{user_anchors_section}

{flavor_section}

## 已锁定的变量配方（必须贯彻）
{variables_block}

## 金手指/超自然设定
{fictional_hook}

## 骨骼参考（可空）
{blueprint_section}

## 用户意见（重生成时）
{feedback_section}

请写出开篇场景 JSON。
"""

GENESIS_OPENING_INSTRUCTIONS = """你是顶级网文开篇创作者。
变量配方已经由系统采样锁定，你必须严格用给定的针对度/情感度/人性逻辑/故事模式/金手指来写开篇，
不得自行改数值；整体感受配方张力，不要逐条念说明书。

【主角一致性·最高优先级】若 system 消息含「已锁定主角档案」与/或「冰山 PROMPT4」JSON：开篇正文叙事主体必须是该主角本人，
且须落实 PROMPT4 中 opening_collision / protagonist_tick / opening_tone 的叙事落点（不得另编一套故事）。
姓名用字、性别、身份阶层与世界位置须与档案及 PROMPT4 一致；禁止另造主角名、禁止换人（包括把已定男主写成女主或反之）、禁止同名不同人。
若该段落与 user_anchors 中主角信息冲突，以「已锁定主角档案」与 PROMPT4 为准。

【铁律】必须严格遵守用户消息中的【题材核心风味与禁忌】：勿串频（例如权谋不写武侠对打、悬疑不靠空降鬼魂收场、职场不写成无脑修仙）。

要求：
- 500～800 字具体场景，强画面与情绪冲击；禁止纯设定说明书
- 若用户消息变量块中出现【情感度落地铁律】，必须按条内要求用具体场面落实；其余档位须与「情感度：数值 — 释义」一致：正数侧体现信任/温情/支持向，负数侧体现敌意/伤害/背叛向，不得把高情感度写成全员冷漠敌对
- **无挂配方**：当用户消息「金手指」为「无（…）」或变量块顶部出现【金手指铁律·当前为无挂配方】时，**禁止**前世/重生/穿越记忆/系统等任何外挂叙事，只能靠当场信息与人物本事；不得写「上一世」「死过一次才明白」类句子
- 虚构元素/金手指须融入人物感知与行动，禁止「叮！系统绑定成功」类廉价旁白
- 若用户消息「金手指/虚构钩子」全文含 ⚠️ 逻辑铁律且**非无挂**，正文须与之完全一致（尤其重生记忆的截止时刻、读心范围、回档锚点等），禁止常识悖论
- 结尾必须有不可逆推动力（主角无法回到过去）
- 平台节奏、句式与「反报菜名、反口号尾、Show don't tell」等须同时满足：本系统消息后半的【平台风格】（若有）与【反 AI 降智与叙事质感控制】；用户消息中的目标平台名称须与所选风格块一致理解

只返回 JSON：
{"opening_text": "（正文）"}
"""

GENESIS_OPENING_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + GENESIS_OPENING_INSTRUCTIONS

ICEBERG_STAGE1_WORLD_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是网文世界观架构师。只根据【开篇正文】与【变量配方】做有机延展。
你必须严格遵守用户消息最上方的【锚点约束】：local_environment、world_rules 须与开篇场景与已暗示规则一致，禁止为填字段编造另一故事背景。

【圈层嵌套与世界观纵深法则（长线连载的基石，全题材通用！）】
绝对禁止将世界观写成扁平、一眼望到头的单机地图！为了支撑长篇巨著，世界必须具备令人窒息的“结构性纵深”！
1. 【题材自适应的圈层设计】：
   - 若为幻想题材（修仙/科幻/末日）：向外延伸。开篇的宗门/星球只是冰山一角，之上必须有更高维度的位面、法则制定者或文明收割者。
   - 若为现实/半现实题材（宫斗/都市/悬疑/民国）：向内深潜。绝不能写成修仙！格局的放大表现为“权力圈层与利益网络的剥洋葱”。例如：开篇的职场恶霸，背后是操纵行业的资本财阀；开篇的后宫争宠，背后是延续百年的世家门阀与皇权更迭的惊天血案。
2. 【规则的绝对碾压感】：世界的最高层必须掌握着让底层人绝望的“核心规则”（无论这规则是修仙界的天道，还是现实世界里的资本垄断/皇权礼教），世界的上限必须极高！

【动态制衡与灰度法则（极其重要：拒绝单极世界！）】：
绝对禁止将世界的权力结构写成“只有主角和反派”的单调模式！权力生态必须符合【制衡（Checks and Balances）】的真实逻辑：
1. 必须存在多方势力的相互钳制（如：明面的正统官方、暗处的庞大邪派、唯利是图的世家财阀、夹缝中的散人联盟）。
2. 拒绝非黑即白：正派势力过大必生腐败（打着正派旗号行苟且之事）；邪派能在打压下存活必然是因为与高层有隐秘的利益输送。世界必须充满这种伪善与灰色的生态张力！

开篇呈现：局部环境须扎实可感；对顶端圈层/宏观金字塔的定位可精炼，勿喧宾夺主。power_structure 与 world_rules 须体现上述制衡与灰度，忌只列反派与底层两极。
只返回 JSON，不加前言。所有字段用中文短句或字符串数组，数组元素为字符串。"""

ICEBERG_STAGE1_WORLD_USER = """
{anchor_block}
## 变量配方
{variables_block}

## 开篇正文
{opening_text}

## 输出 JSON 模板
{{
  "local_environment": "开篇所在的微观环境",
  "macro_world_hierarchy": "开篇所在地在整个宏观世界/权力金字塔中的位置。⚠️必须强制推演出极其宏大、森严的最高权力层/利益集团/上界，拉爆该题材的纵深天花板！",
  "world_rules": ["联系开篇的直接规则", "统治宏观世界的更高法则（主角暂不可及）"],
  "power_structure": ["微观权力一句", "宏观顶端一句"],
  "unique_settings": ["至少一条独特设定"]
}}
"""

ICEBERG_STAGE1_CAST_USER = """
{anchor_block}
## 变量配方
{variables_block}

## 开篇正文
{opening_text}

## 输出 JSON 模板
{{
  "local_cast": [
    {{
      "name": "姓名",
      "role": "protagonist_side",
      "identity": "身份",
      "connection_to_opening": "与开篇事件关系",
      "relationship_type": "亲缘/敌对/暧昧等",
      "initial_emotional": -20,
      "initial_targeting": 10,
      "current_mental_state": "（protagonist_side 必填）当前心智与成熟度：处于抛弃幻想、减少内耗的哪一阶段？须与环境与开篇言行一致",
      "mental_growth_path": "（protagonist_side 必填）全书心智升级轨迹（精神层面如何蜕变）",
      "reverse_scale": "（protagonist_side 必填）绝对逆鳞：触之必引发冷静、不计代价的正面对决与杀伐；禁止失智咆哮",
      "capabilities": {{
        "golden_finger": {{
          "has_golden_finger": false,
          "gf_type": "（参考六大类型：信息降维/规则豁免/绝对资源/伴生外挂/概念系/凡人流；无则null）",
          "core_ability": "核心能力描述（无则null）",
          "activation_condition": "触发条件（无则null）",
          "cost_and_limit": "代价与限制——戏剧张力来源（无挂时null）",
          "exposure_risk": "一旦暴露的后果（无则null）",
          "current_state": "当前积累/剩余状态（无则null）"
        }},
        "unique_traits": [
          {{
            "trait_name": "特质名称（protagonist_side 可填；无则空数组）",
            "trait_effect": "实际效果",
            "double_edge": "负面代价（特质必须有代价）"
          }}
        ]
      }}
    }},
    {{
      "name": "核心对立者姓名",
      "role": "antagonist",
      "identity": "身份",
      "connection_to_opening": "与开篇事件关系",
      "relationship_type": "敌对/制衡等",
      "initial_emotional": -40,
      "initial_targeting": 30,
      "current_mental_state": "（antagonist 必填）当前心智与成熟度（如：狂妄独裁者 / 极致利己的冷静猎手）",
      "mental_growth_path": "（antagonist 必填）其在全书中的心智/认知演变方向",
      "reverse_scale": "（antagonist 必填）其绝对逆鳞或无",
      "capabilities": {{
        "golden_finger": {{
          "has_golden_finger": false,
          "gf_type": "反派/配角金手指类型（无则null）",
          "core_ability": "核心能力（无则null）",
          "cost_and_limit": "代价与限制（无则null）",
          "exposure_risk": "暴露后果（无则null）",
          "current_state": "当前状态（无则null）"
        }},
        "unique_traits": []
      }}
    }}
  ],
  "protagonist_card": {{
    "standard_name": "须与 local_cast 中主角 name 一致",
    "appearance": "外貌（一句话高辨识度）",
    "current_mental_state": "当前心智与成熟度（抛弃幻想/内耗阶段须写清；须与开篇与环境法则一致）",
    "mental_growth_path": "全书心智升级轨迹（精神层面正向蜕变路径）",
    "reverse_scale": "绝对逆鳞（触之必冷静对决与杀伐；表现为理智而非失智吼叫）",
    "background_summary": "背景摘要",
    "traits_display": ["行为侧写1", "行为侧写2"],
    "dominant_logics": ["人性逻辑标签"],
    "immediate_motive": "当下最直接驱动（可空）",
    "destiny_seed": "长线宿命种子（可空）",
    "capabilities": {{
      "combat_skills": [
        {{
          "skill_name": "功法/武功/流派名称（现实题材填null；无修炼体系填null）",
          "system": "所属体系（如：儒家剑道/佛门金身；现实/都市填null）",
          "current_level": "当前境界或熟练程度",
          "signature_technique": "标志性招式或用法（可选）"
        }}
      ],
      "dao_foundation": "所修大道/核心法则（修仙/玄幻文适用；现实文填null）",
      "signature_items": [
        {{
          "item_id": "item_001",
          "item_name": "物品名称（如：佩剑「霜降」/工具包/令牌；无则空数组）",
          "item_function": "实际功能或象征意义",
          "concealment": "是否刻意隐藏（是/否）",
          "current_status": "在身/丢失/已损毁/被夺"
        }}
      ],
      "golden_finger": {{
        "has_golden_finger": false,
        "gf_type": "（信息降维类/规则豁免类/绝对资源类/伴生外挂类/概念系类/凡人流类；无则null）",
        "core_ability": "核心能力的具体描述（无则null）",
        "activation_condition": "触发或使用条件（无则null）",
        "cost_and_limit": "代价与限制（这是戏剧张力来源，必须真实存在；无挂时null）",
        "exposure_risk": "一旦暴露会引发什么后果（无则null）",
        "current_state": "当前积累程度/剩余次数/是否已激活（无则null）"
      }},
      "unique_traits": [
        {{
          "trait_name": "特质名称（如：痛觉缺失/过目不忘/天生镇魂体；无则空数组）",
          "trait_effect": "实际效果描述",
          "double_edge": "负面效应或代价（特质必须有代价，否则是作弊）"
        }}
      ]
    }}
  }},
  "macro_shadow_cast": [
    {{
      "name": "幕后势力或高阶存在",
      "identity": "地位",
      "connection_to_opening": "如何间接导致开篇惨案/困局",
      "appears_from_volume": 2
    }}
  ],
  "ultimate_villain": {{
    "name": "全书最终宿敌（⚠️网文铁律：不一定非要是最高统治者/皇帝/宗主！完全可以是主角的宿命劲敌、昔日背叛的挚友/爱人、隐藏幕后夺取主角机缘的黑手、或是杀害主角亲友的具体仇人）",
    "identity": "与 name 匹配的身份或势力称谓（须具体可呼名道姓；优先具名自然人/具体黑手，少用空泛的「制度」「天道」代替人）",
    "core_motivation": "与主角产生终极冲突的【极度私人的渊源】。⚠️禁止假大空：不要写「因为阶级制度/大道之争」这类泛化。必须落地到绝对的私人利益与爱恨情仇上（例如：他就是当年下令挖走主角灵根/陷害主角家族的真凶；或者他为了飞升/上位，必须吸干主角或主角挚爱的心血。不是你死就是我亡！）。",
    "appears_from_volume": 3,
    "human_logic": "马基雅维利逻辑 / 野心家逻辑 / 执念逻辑 / 复仇逻辑",
    "current_mental_state": "终局宿敌当前心智与成熟度",
    "mental_growth_path": "其在全书中的心智/认知演变方向",
    "reverse_scale": "其绝对逆鳞或无"
  }}
}}
"""

ICEBERG_STAGE1_CAST_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是网文人物与势力结构师。只根据【开篇正文】与【变量配方】推演人物与对撞结构。
你必须严格遵守用户消息最上方的【锚点约束】：local_cast 须含开篇中的主角（姓名与原文一致）与核心对立人物；connection_to_opening 必须指向原文已写事件，禁止替换施害者。
冰山原则：局部出场人物 + 幕后高阶阴影势力都要有；ultimate_villain 字段名保留以兼容下游，**默认按商业网文优先写成与主角有私人恩怨/利益对撞的具名终局对手**（夺机缘、害亲友、背叛、情敌、血仇等）。仅在开篇明确无具体恶人、且题材确为纯环境求生时，才可退化为高度人格化的「代表某种压榨的具体负责人」而非抽象拯救世界式对立。勿为填字段编造与开篇无关的灭世型反派。

【生存哲学与人设面具法则（极度重要：认清环境，拒绝脸谱化的懦弱！）】：
主角的【外在假面】必须是其为了在当前环境中利益最大化而选择的“生存策略”，绝对禁止将“低调”写成毫无魅力的“懦弱、木讷、受气包”！
请根据主角的处境与智慧，赋予其匹配的高级生存面具：

1. 【高压奴役/绝对被控环境】（如：底阶杂役、宫女、死士营）：
   - 生存策略：必须极致的“顺从与降低存在感”。
   - 高级写法：外表唯唯诺诺、挑不出错处，但内心是极度清醒的冷血算计。主角的“苟”是为了活命和寻找一击毙命的反噬机会，绝非真的懦弱无能。

2. 【高危自由/丛林法则环境】（如：散修、民间术士、末日废土）——这是最经典的“苟道流”！
   - 生存策略：和光同尘，绝不当出头鸟，但绝不吃亏。
   - 高级写法：外表看起来是个普普通通、平平无奇的路人。遇事第一反应是退至众人身后，绝不多管闲事。但这种“苟”是建立在【极度敏锐的嗅觉、被迫害妄想症和超强底牌】之上的！一旦被逼入死角或触及底线，出手必是雷霆万钧、杀人扬灰、斩草除根。

3. 【江湖市井/利益交换环境】（如：赏金猎人、黑市商人、现代职场）：
   - 生存策略：利益至上，圆滑变通。
   - 高级写法：市俗、笑面虎、见人说人话。靠真本事吃饭，外表可以贪财好色、插科打诨，但在大是大非和核心利益上有一条绝对不退的死线。

4. 【高位开局/体制内环境】（如：世家嫡子、宗门执事、朝臣）：
   - 生存策略：体面与规则的利用。
   - 高级写法：不怒自威、滴水不漏。擅长打太极和阳谋，用规矩杀人，带有上位者的从容。

⚠️ 核心总结：主角可以苟，可以低调，可以市俗。但【绝对不能是一个傻子/受气包】。他们的每一副面具，都必须透着属于他们那个阶层的“生存智慧”与“反差张力”！

上述要求须落实到 **protagonist_card** 与 local_cast：**protagonist_side** 与 **antagonist** 条目【必须】填写 current_mental_state、mental_growth_path、reverse_scale，与《创作最高宪法》及开篇言行一致，勿与生存面具/气质侧写矛盾。

local_cast 中 **neutral**（路人或绝对边缘中立者）对上述三字段可填「无」或省略，避免 JSON 臃肿。

initial_emotional / initial_targeting 必须是整数。
ebd_bond_kind 在 local_cast 可省略（合并层会处理）；role 取 protagonist_side | antagonist | neutral。

**capabilities 字段（极度重要）**：金手指不是主角专属！反派的「气运观测」、配角的「窃听心声」、NPC的「随身空间」——任何影响博弈格局的实体能力都必须在 capabilities 中记录。local_cast 中 protagonist_side 与 antagonist 须填写 capabilities.golden_finger 和 capabilities.unique_traits；neutral 可省略 capabilities 以控制 JSON 体积。protagonist_card 须填写完整的 capabilities（含 combat_skills / dao_foundation / signature_items / golden_finger / unique_traits）。

只返回 JSON，不加前言。"""

ICEBERG_STAGE2_SYNOPSIS_SYSTEM = (
    DEEPNOVEL_CONSTITUTION + "\n\n"
    + "你是商业网文策划。已有【开篇正文】、变量配方、以及阶段1产出的【人物/世界 JSON】。\n"
    "你的任务：生成与下游 synopsis_node 兼容的宏观构思 JSON，并补全扩展战略字段。\n"
    "你必须严格遵守用户消息中的【锚点约束】与【PROMPT4】JSON：主角姓名、性别、职衔须与 protagonist_archive / 阶段1班底一致；"
    "核心冲突须与 PROMPT4 的 opening_collision 可互证；"
    "escalation_path、volume_1_goal、core_conflict 必须从开篇锚点与 PROMPT4 交汇逐级放大，禁止套与开篇无关的题材模板。\n"
    "必须与阶段1设定自洽，不得另起炉灶；格局须沿「圈层深潜」或「位阶外扩」从开篇阶梯放大到全书（勿默认换地图修仙；现实题材以利益网/权力金字塔升维为主）。\n\n"
    "【认知颠覆与长线格局放大法则（全题材通用的破窗效应！）】\n"
    "在规划《格局放大路径 (escalation_path)》时，绝对禁止让主角在同一个层次里无限循环打怪！必须写出极具震撼力的【认知颠覆】！\n"
    "1. 【虚假的目标与真相剥离】：主角在卷 1、卷 2 拼命争夺的东西或坚信的真理，在后期必须被证明只是“冰山一角”甚至是一个“巨大的谎言”。（例如：宫斗中，以为斗倒了所有妃子就能安稳，却发现皇帝的宠爱本身就是为了制衡世家而设下的毒局；悬疑中，抓到了连环杀手，却发现他只是某个庞大社会犯罪网络的清道夫）。\n"
    "2. 【私欲驱动打破天花板】：主角的终极目标依然是出于“极致的护短/复仇/求生等私欲”。但为了实现这个私欲，TA被迫发现，如果不把头顶那层“吃人的旧规则/旧利益集团”彻底砸碎，自己和在乎的人永远只是案板上的鱼肉！从而将私人恩怨，极其自然且被动地升华为颠覆整个行业/朝堂/世界格局的终极博弈！\n\n"
    "{platform_hint_block}\n\n"
    "只返回 JSON，不加前言。\n\n"
    + GENRE_LEXICON_SLUG_HINT
    + "\n\n【扩展字段】\n"
    "- core_hook：一句话钩子（读者为什么追读）\n"
    "- volume_1_goal：第一卷要解决的微观目标\n"
    "- escalation_path：局部麻烦 → 中期阶段 → 终局格局（一条链）；须体现圈层递进或认知颠覆节点，禁止同层重复打脸凑字数\n"
    "- ultimate_goal：全书终极宏观目标。【私欲底色】核心动机须接地气（求生、复仇、护短、夺权、自保）；**主角可自始至终只为私欲，绝不强制升华大义**，禁止一开场心怀天下。【可选被动大义】仅当剧情逼至「不掀翻棋盘/旧制度就无法保护自己和在乎之人」的绝境时才**允许**；无此绝境则保持私人恩怨纯粹性。\n\n"
    "【感情基线铁律】\n"
    "family_emotion_line 与 romance_emotion_line 不得同时为「无」或空。\n"
)

ICEBERG_STAGE2_SYNOPSIS_USER = """
{prompt4_block}
{anchor_block}
## 题材需求（原文）
{genre_request}

## 变量配方（锁定）
{variables_block}

## 开篇正文（种子）
{opening_text}

## 阶段1·世界快照（JSON）
{world_json}

## 阶段1·班底快照（JSON）
{cast_json}

## 用户额外意见（可空）
{extra_feedback}

## 输出 JSON 键
{{
  "title": "2-8字",
  "world": "世界观一句话",
  "protagonist": "行事方式+驱动力，禁止单技能标签",
  "core_conflict": "须含各方为何卷入、对主角的敌意/压制或可感知阻力从何而来；若存在明确反派则写针对动机及主角变强后对立如何升级。**若是日常/求生/种田/攻略流而无单片反派**，则写核心阶级矛盾、环境排斥力、规则与资源挤压等对主角的持续压迫，不得硬编无名魔王凑数。",
  "direction": "走向",
  "family_emotion_line": "…",
  "romance_emotion_line": "…",
  "genre_lexicon_keys": ["generic", "…"],
  "core_hook": "…",
  "volume_1_goal": "…",
  "escalation_path": "…",
  "ultimate_goal": "全书终极宏观目标。⚠️【私欲底色与可选的被动大义】：主角的核心动机必须是极其接地气的‘凡人私欲’（如求生、复仇、护短、夺权、自保）。【主角完全可以自始至终只为私欲而战，绝不强制升华！】绝对禁止一开场就心怀天下。只有在剧情将其逼到‘不掀翻整个棋盘/旧制度，就无法保护自己和在乎之人’的绝对绝境时，才【允许】出现向‘大义’的被动转变。若无此绝境，请永远保持私人恩怨的纯粹性！"
}}
"""


def platform_hint_for(style: str) -> str:
    s = (style or "").strip() or "通用网文"
    return PLATFORM_MACRO_HINTS.get(s, PLATFORM_MACRO_HINTS["通用网文"])
