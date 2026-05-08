from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from prompts.common.realism_doctrine import WORLD_AND_PROTAGONIST_REALISM_DOCTRINE

WORLD_BUILD_SYSTEM = (
    DEEPNOVEL_CONSTITUTION
    + "\n\n"
    + WORLD_AND_PROTAGONIST_REALISM_DOCTRINE
    + "\n\n"
    + """你是一个世界观设计师，同时也是资源稀缺与灰度博弈的架构师。
根据已确认的宏观构思，生成一份世界设定卡。
世界设定卡是全书的"宪法"——一旦确认，全书不再变动。
冲突须能从【有限资源（权、钱、自身实力、情感、领土等）】与【势力制衡】中推导，善恶是利益投影而非固定标签。
若用户消息中包含「冰山反推·世界结构基底」JSON：须**继承**其中的核心规则、权力层级与关键事实，在此基础上精炼与扩写；禁止无因果地颠覆已给出的结构性设定。
须给出独立字段 narrative_era（字符串）：与 user 消息中的「叙事时代与语体锚点」一致且可执行；须与文后「时代语料隔离法则」自洽（禁止古今语料混搭；不做穷举禁词，由模型按时代肌理自行约束词界）。
只返回 JSON，不加任何前言。"""
)

WORLD_BUILD_USER_TEMPLATE = """## 题材与目标平台（全书固定；势力舞台须与读者赛道一致）

题材：{genre_request}

{platform_macro_hint}

## 已确认的宏观构思

{synopsis_text}

## 冰山反推·世界结构基底（继承约束；若无则写「（无）」并从宏观构思推导）

{iceberg_world_baseline}

{narrative_era_section}
## 任务

根据宏观构思，生成一份精简的世界设定卡。
要求：
- basic_rules 须点明**何种稀缺资源**导致阶层倾轧或规则压迫；并落实 System 中「四、宏大叙事与人性驱动」：人驱万物、时代结构性冲突、多诉求交织，**禁止**道具中心主义（不可把全书矛盾写成「举世争夺单一物件」）
- power_structure 至少 3～5 条，每条写清**利益冲突或互相钳制**（非单极碾压空话）
- gray_zone_ecology：缝隙中的掮客、灰产、破戒者等**至少 1～2 条**，便于借力打力
- narrative_era 须与上节锚点一致，写清时代类别、具体锚点与词汇/认知边界（抽象描述即可，勿堆禁词表）
- 各字段正文须遵守 System 文末「时代语料隔离法则」
- 每条尽量简短，设定卡不是百科全书

返回 JSON：
{{
  "basic_rules": "核心运行逻辑：何种有限资源、如何导致倾轧（50-120字）",
  "power_structure": [
    "势力A与势力B：核心利益冲突与脆弱平衡（一句话）"
  ],
  "gray_zone_ecology": [
    "灰色缝隙：谁在此交换情报/资源、生存逻辑（一句话）"
  ],
  "geography": [
    "地域名：地理+是否垄断某种地缘/信息/时间资源（一句话）"
  ],
  "world_taboos": [
    "最高禁忌及违反后的典型代价（一句话）"
  ],
  "unique_settings": [
    "区别于同类小说的特有元素（一句话，让读者觉得新鲜）"
  ],
  "narrative_era": "与上节锚点一致：古代|近代|现代|架空 + 具体锚点 + 禁用词/机制（40-120字）"
}}"""

# 续传/修改时用于展示当前设定供 LLM 参考
WORLD_BUILD_REVISE_USER_TEMPLATE = """## 题材与目标平台（全书固定）

题材：{genre_request}

{platform_macro_hint}

{narrative_era_section}
## 已确认的宏观构思

{synopsis_text}

## 冰山反推·世界结构基底（修改时勿与此矛盾，除非用户意见明确要求）

{iceberg_world_baseline}

## 当前世界设定草稿

{current_world_setting}

## 用户的修改意见

{feedback}

## 任务

根据用户意见修改世界设定卡，保持未提及的部分不变。
除非用户意见明确要求改动时代或语体，须保持 narrative_era 与上节「叙事时代与语体锚点」一致。
返回完整的修改后 JSON（格式同上）。"""

# 主角人物卡：终端展示用短文案（实际交互见 __main__ 自由输入）
PROTAGONIST_FREE_INPUT_HINT = """用一句话或几个关键词描述你心中的主角即可（不必审题）。
例如：清冷腹黑、病秧子其实武功盖世、极度抠门但有底线、长得像林黛玉心眼却狠、贪财女史等。
直接**回车**：由模型根据当前宏观构思与题材自行生成主角。"""

PROTAGONIST_INPUT_QUESTIONS = [PROTAGONIST_FREE_INPUT_HINT]

PROTAGONIST_CARD_FROM_USER_SYSTEM = (
    DEEPNOVEL_CONSTITUTION
    + "\n\n"
    + WORLD_AND_PROTAGONIST_REALISM_DOCTRINE
    + "\n\n"
    + """你是精通人格心理学的角色设计师（与《DeepNovel 重构文档》PROMPT 3「灵魂层·主角卡」一致）。
角色不是属性面板的集合，而是有独立意志的生命体。
须结合用户消息中的 world_archive 与 synopsis：先理解资源格局与势力生态，再写主角的初始处境与性格表现。

【读者赛道与主角性别】须严格遵守用户消息中的「题材」与「目标平台与读者定位」：女频平台默认主角为女性（姓名、称谓、社会处境须一致），男频平台默认主角为男性；若用户主角印象或 user_anchors 明确要求另一性别，以用户明示为准。禁止在无说明时套用另一频道的典型男主/女主模板。

【硬性要求】只返回一个 JSON 对象，不加前言、不加 markdown 围栏。
【叙事字段】appearance / persona / signature_habits / reverse_scale 必须给出；reverse_scale 为绝对逆鳞，禁止空字符串。
【引擎对接】除文档型 mental_core 外，必须另给 mental_core_panel：五键 0～100 整数
（intelligence, eq, meticulousness, emotional_capacity, forbearance），须与 mental_core 文字一致，禁止全 50 敷衍。
先天属性允许内在矛盾；成熟度高不等于没有情感；逆鳞被触时仍可大悲，但可转入缜密行动。

【补丁 J · independent_agenda】
`independent_agenda` 不是「终极目标清单句」（禁止只写「我要查明真相/我要活命」这类空泛一句话）。
须写清：**无外部事件时主角也会主动去做的事**——日常/高频行动轨迹、内在驱动（不是谁逼他，是他自己认为该做）、与谋生与世界接触方式如何衔接（开店接客、跑现场、接短单、下墓、审计进场等，随题材）。
错误：只写目的不写行动；或与气质不符的硬造派单组织依赖。"""
)

PROTAGONIST_CARD_FROM_USER_TEMPLATE = """## 题材与目标平台（必须遵守；决定主角性别与叙事切入）

题材：{genre_request}

{platform_macro_hint}

## 用户的主角印象（可为空）

{user_impression_section}

## world_archive（当前世界档案 · 决定主角初始处境）

{world_archive_section}

## 已确认的宏观构思（synopsis）

{synopsis_text}
{feedback_section}
## 任务

将用户印象、world_archive 与 synopsis 融合为立体主角。用户未写印象时，完全依据档案、题材、目标平台与 synopsis 推断。

须严格按下列 JSON 结构输出（字段名勿改；无内容用 ""、[] 或 {{}}）：

{{
  "character_id": "本书内唯一标识",
  "name": "姓名",
  "aliases": [],
  "appearance": "仅客观外貌一句",
  "persona": "外在生存伪装/保护色，禁止抄外貌",
  "signature_habits": ["微动作1", "微动作2"],
  "reverse_scale": "绝对逆鳞：触及时如何反应（须具体）",
  "innate_traits": {{
    "personality": ["性格2-4条，允许内在矛盾"],
    "talent_physical": ["天赋或生理特征"],
    "core_desire": "最深处想要什么",
    "core_fear": "最深处惧怕什么"
  }},
  "mental_core": {{
    "intellect": "智商水平 + 社会阅历（分开写清）",
    "emotional_intelligence": "情商",
    "strategic_thinking": "思维缜密性",
    "emotional_capacity": 80,
    "emotional_drain_triggers": ["消耗精神阈值的情境"],
    "emotional_collapse_behavior": "阈值归零时的极端行为",
    "endurance": "隐忍度"
  }},
  "mental_core_panel": {{
    "intelligence": 0,
    "eq": 0,
    "meticulousness": 0,
    "emotional_capacity": 0,
    "forbearance": 0
  }},
  "maturity_level": {{
    "current_score": "低|中低|中|中高|高",
    "illusions_held": ["当前仍保有的幻想——成长靶点"],
    "growth_trajectory": "在哪些事件后可能发生跃迁"
  }},
  "world_position": "基于 world_archive：当前圈层与资源",
  "independent_agenda": "无外部事件时：主角日常主动做什么（具体行动轨迹+内在驱动+与谋生/圈层接触的衔接，禁止仅写终极目标一句）",
  "faction_relationship": {{}},
  "core_motif": "叙事用核心底色（80-200字，可从欲求/恐惧提炼）",
  "background_summary": "出身与关键经历（50-120字）",
  "key_life_events": ["经历1", "经历2"],
  "current_emotional_drain": 0,
  "dominant_logics": ["人性逻辑名称1", "名称2"],
  "logic_origins": ["说明1", "说明2"],
  "logic_switch_conditions": [{{"condition": "极端处境", "switch_to": "切换到的逻辑"}}],
  "traits": [],
  "trait_interactions": {{"preset": [], "learned": []}}
}}

人性逻辑名称可参考（不必全用）：
{logic_names_and_essences}
"""

# 人物卡草稿生成 prompt（write_node / bible_update_node 检测到新人物时调用，排除主角）
# 字段与 PROMPT 3（docs/DeepNovel_重构文档_完整版.md）对齐，保证配角卡与主角卡同构。
CHAR_CARD_DRAFT_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是一个精通人格心理学的人物设计师。
根据刚写完的正文，为首次出场的人物生成角色卡草稿（与主角卡 PROMPT 3 同构）。
每个角色都是完全独立的智能体，拥有自己的欲求、恐惧、逆鳞与人性逻辑。
只返回 JSON，不加任何前言。"""

CHAR_CARD_DRAFT_USER_TEMPLATE = """## 刚完成的正文

{draft_excerpt}

## 需要为以下人物生成角色卡

{character_names}

## 任务

根据正文中的描写，为每个人物生成角色卡草稿。
结构与主角卡（PROMPT 3）同构：先天三维 + 精神面板（文档叙述 + 引擎整数）+ 成熟度 + 逆鳞 + 独立议程 + **capabilities（金手指/特质/标志物等与主角卡同构）**。
**必须基于正文已有描写推断**；正文无直接描写时，依角色身份/处境合理估算，标注为（估算）。
若某配角无任何超常能力：capabilities.golden_finger.has_golden_finger=false，unique_traits 可为空数组。

外貌提取规则（严格遵守）：
  只写身体和面部的客观特征，能让读者在人群中认出即可。
  不写气质、神态、站姿、眼神等动态描述。
  不用"却/但/而"等转折连词。
  若正文没有符合标准的外貌描写，appearance 填 ""，等后续节点补充。

innate_traits 填对象（与主角卡一致）：
  personality：性格特征 2-4 条，允许内在矛盾；
  talent_physical：天赋/生理特征（无则 []）；
  core_desire：此人最深处想要的是什么；
  core_fear：此人最深处惧怕的是什么。

mental_core 填叙述文字（引擎层由 mental_core_panel 整数驱动）：
  intellect：心智+阅历；emotional_intelligence：情商；
  strategic_thinking：缜密性；endurance：隐忍度；
  emotional_capacity：整数 0-100（精神阈值，默认 60）；
  emotional_drain_triggers：消耗阈值的情境；
  emotional_collapse_behavior：阈值归零时的极端行为。

mental_core_panel 填整数（0-100，须与 mental_core 叙述一致，禁止全 50）：
  intelligence、eq、meticulousness、emotional_capacity、forbearance。

返回 JSON：
{{
  "character_cards": [
    {{
      "standard_name": "标准名称",
      "aliases": ["别称1"],
      "appearance": "最有辨识度的1-2个外貌特点（15字以内）",
      "persona": "外在生存伪装/保护色（无则空字符串）",
      "signature_habits": ["可观察微动作1", "微动作2"],
      "reverse_scale": "绝对逆鳞：触碰时如何反应（须具体，无则填无）",
      "innate_traits": {{
        "personality": ["性格特征2-4条"],
        "talent_physical": ["天赋/生理特征"],
        "core_desire": "最深处欲求",
        "core_fear": "最深处恐惧"
      }},
      "mental_core": {{
        "intellect": "心智水平+阅历（分开描述）",
        "emotional_intelligence": "情商",
        "strategic_thinking": "思维缜密性",
        "emotional_capacity": 60,
        "emotional_drain_triggers": ["消耗情绪控制力的情境"],
        "emotional_collapse_behavior": "阈值归零时极端行为",
        "endurance": "隐忍度"
      }},
      "mental_core_panel": {{
        "intelligence": 50,
        "eq": 50,
        "meticulousness": 50,
        "emotional_capacity": 60,
        "forbearance": 50
      }},
      "maturity_level": {{
        "current_score": "低|中低|中|中高|高",
        "illusions_held": ["当前保有幻想——成长靶点"],
        "growth_trajectory": "在哪些事件后可能跃迁"
      }},
      "world_position": "当前圈层与掌握的资源",
      "independent_agenda": "无外部事件时的生活目标与行动计划",
      "faction_relationship": {{}},
      "core_motif": "叙事核心底色（可从欲求/恐惧提炼，≤120字）",
      "background_summary": "出身与关键经历（≤80字）",
      "current_emotional_drain": 0,
      "dominant_logics": ["人性逻辑名称"],
      "traits": [
        {{
          "name": "特质名",
          "trigger": "触发情境",
          "expression": "外在表现",
          "suppressed_by": ["被压制的情况"]
        }}
      ],
      "trait_interactions": {{
        "preset": [
          {{
            "combo": ["特质1", "特质2"],
            "condition": "触发叠加的情境",
            "result": "叠加后的实际反应",
            "reader_expectation": "读者预期",
            "actual": "实际发生的",
            "interaction_type": "contrast或amplify"
          }}
        ],
        "learned": []
      }},
      "capabilities": {{
        "combat_skills": [],
        "dao_foundation": null,
        "signature_items": [],
        "golden_finger": {{
          "has_golden_finger": false,
          "gf_type": null,
          "core_ability": null,
          "activation_condition": null,
          "cost_and_limit": null,
          "exposure_risk": null,
          "current_state": null
        }},
        "unique_traits": []
      }}
    }}
  ]
}}"""
