# prompts/creation/story_direction.py
# 故事方向模式：detect_gender_and_platform + extract_all_from_background

from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

DETECT_GENDER_PLATFORM_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """分析故事背景，判断主角性别和适合的平台风格。
只返回 JSON，不加任何前言。"""

DETECT_GENDER_PLATFORM_USER = """## 故事背景

{background}

## 任务

返回 JSON：
{{
  "protagonist_gender": "male" 或 "female",
  "recommended_platform": "番茄男频" 或 "番茄女频" 或 "知乎男频" 或 "知乎女频",
  "recommended_genre": "题材名（如现代重生、都市异能，从故事推断）",
  "reason": "判断依据一句话"
}}"""

EXTRACT_ALL_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是一个网文策划编辑。
用户提供了他的创作意图和关键要素，你需要在完整保留这些要素的基础上，
发挥创作能力补全所有细节，生成一套完整的小说设定。

处理规则：
  必须保留：用户明确说出的经历、关系、动机、情感基调
  创作补全：世界观细节、次要人物、具体场景、情节走向
  自由命名：人物名字参考用户描述，但可以根据题材风格调整
  禁止：用通用套路替换用户的具体描述
  synopsis 内 `family_emotion_line` 与 `romance_emotion_line` 不得同时为「无」或空：至少一条须有可写感情主轴（亲情可多号正负并存；爱情可 1：N、单恋或双向，见 EBD §2.6）。

只返回 JSON，不加任何前言。"""

EXTRACT_ALL_USER = """## 用户故事方向（创作意图与关键要素）

{background}

## 目标平台

{platform}

## 题材

{genre}

## 任务

根据故事方向创作生成全部设定，返回 JSON：
{{
  "synopsis": {{
    "title": "小说标题（2-8字）",
    "world": "世界观（1-2句话）",
    "protagonist": "主角描述（行事方式和思维逻辑，不写单一技能标签）",
    "core_conflict": "核心冲突",
    "direction": "故事走向",
    "family_emotion_line": "亲情主轴（可多组对立/正负）；无则「无」，但与 romance 不可双无",
    "romance_emotion_line": "爱情/红颜 1：N、单恋或双向；无则「无」，但与 family 不可双无"
  }},
  "world_setting": {{
    "basic_rules": "世界核心规则（一段话）",
    "power_structure": ["势力1：描述", "势力2：描述"],
    "geography": ["地点1：描述", "地点2：描述"],
    "world_taboos": ["禁忌1", "禁忌2"],
    "unique_settings": ["独特设定1", "独特设定2"]
  }},
  "protagonist_card": {{
    "standard_name": "主角名字（从用户背景里取，如用户未指定则创作一个符合题材的名字）",
    "appearance": "外貌（一句话，最有辨识度的1-2个特点）",
    "innate_traits": ["先天性格底色2-4条，如贪财、护短、多疑，可含内在矛盾"],
    "persona": "外在社会化伪装（⚠️严禁抄写外貌！必须写ta在当前环境中的伪装策略）",
    "mental_core": {{
      "intelligence": 50,
      "eq": 50,
      "meticulousness": 50,
      "emotional_capacity": 60,
      "forbearance": 50
    }},
    "signature_habits": [
      "可拍摄的微动作1（⚠️禁止抽象口号，必须是身体动作）",
      "可拍摄的微动作2（可选）"
    ],
    "current_maturity": "开篇当下成熟度/处境阶段（非道德审判，须与用户经历匹配）",
    "maturity_level": "开篇当下成熟度/处境阶段（非道德审判，须与用户经历匹配）",
    "current_emotional_drain": 0,
    "current_mental_state": "开篇当下心智与情绪基调（可与 maturity_level 互补）",
    "mental_growth_path": "全书精神/处事升级轨迹",
    "reverse_scale": "逆鳞：触之不死不休，表现为冷静果决而非咆哮失智",
    "background_summary": "背景经历（完整保留用户描述的经历）",
    "micro_reactions": [
      "遇险时 → 具体可观察行为",
      "真正愤怒时 → 具体行为",
      "面对兄弟/家人时 → 具体行为",
      "被逼到极限时 → 具体行为（须有一条失控或质变时刻）",
      "最执着的事 → 具体描述"
    ]
  }}
}}"""
