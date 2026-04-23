# DeepNovel 开篇种子系统 — Cursor 执行文档 v2

> 替代 v1 文档，以本文档为准执行。
>
> 核心设计：变量配方引爆开篇（种子），开篇反推一切设定。
> 工程重构：冰山反推拆分为三个并发 LLM 任务，防止单次调用崩溃。
> 新增：金手指/虚构元素的有机融入机制。
> 新增：三幕五卷双轨结构，平衡爽文和正剧两种走向。

---

## 一、知识库更新（`knowledge/story_variables.py`）

### 1.1 变量配方含义定义（不变）

```python
VARIABLE_COMBINATIONS = {
    "targeting_degree": {
        ">=95": "主角被直接消灭（重生/穿越/灵魂转移才能延续）",
        "70-94": "主角重创至绝境（家破/入狱/坠落），生死一线",
        "40-69": "主角被打落谷底但未死，从零开始",
        "10-39": "主角受打压但有喘息空间",
        "<=9":   "无人针对，草根白手起家",
    },
    "emotional_degree": {
        "<-80":   "刻骨背叛（最信任的人举刀/设局）",
        "-80~-50":"被深深伤害，积累的怨恨和耻辱",
        "-50~-20":"被轻视蔑视，普通压制",
        "-20~+20":"中性，普通起点",
        "+20~+60":"有守护的人或目标，情感驱动",
        ">+60":   "珍视的感情破碎，以爱之名的驱动",
    },
    "logic_tone": {
        "复仇逻辑":   "咬牙切齿，血债血偿是唯一目标",
        "野心家逻辑": "往上爬，踩着所有人的头",
        "设局逻辑":   "让他们用自己的手毁掉自己",
        "忍辱逻辑":   "现在忍，积蓄力量等时机",
        "执念逻辑":   "只要一件事，为此放弃一切",
        "绝境逻辑":   "没有退路，死也要拉着垫背",
        "推理逻辑":   "找到规律和漏洞，用信息差破局",
    },
    "mode_tone": {
        "极渊求生":  "每一步都在生死边缘，高压到极致",
        "极渊坠落":  "一切崩坏，没有轻易转机，走向沉重代价",
        "浮沉逆转":  "从最低谷爆发，大起大落",
        "暗流涌动":  "表面平静，危险在水面下积累",
        "极道横推":  "无敌爽文，一路打穿，越战越猛",
    }
}
```

### 1.2 新增：金手指/虚构元素兼容矩阵

```python
# 金手指是可选的，不是必须的
# 与现实题材结合才有意义：虚构+现实的化学反应
# 全是虚幻就失去了虚构的意义

FICTIONAL_HOOKS = {
    "宫斗权谋": {
        "options": [
            "无（纯正统权谋，无外挂）",
            "重生（带着前世惨死的记忆和教训）",
            "穿书（现代人穿成书中炮灰/反派）",
            "读心（每天只能感知特定人物的一个真实念头）",
            "预知（能看见某人接下来的一个行动，但无法改变）",
        ],
        "probability": [0.45, 0.20, 0.15, 0.10, 0.10],
        "note": "宫斗核心是人心博弈，金手指不能破坏权谋的逻辑自洽性",
    },
    "修仙玄幻": {
        "options": [
            "无（纯凡人修仙流）",
            "随身空间/残魂导师",
            "熟练度/加点面板系统",
            "万物词条（能看见隐藏属性）",
            "夺舍/双灵魂共体",
            "功德系统（做善事获得力量）",
        ],
        "probability": [0.15, 0.15, 0.25, 0.20, 0.15, 0.10],
        "note": "修仙题材金手指接受度最高，但必须有明确的使用代价或限制",
    },
    "都市现代": {
        "options": [
            "无（纯现实逆袭）",
            "重生（带着未来记忆回到过去）",
            "透视/鉴宝能力",
            "医术觉醒（家传秘术或意外获得）",
            "预知梦（每晚梦见近期将发生的事）",
        ],
        "probability": [0.30, 0.25, 0.15, 0.15, 0.15],
        "note": "都市文金手指要接地气，不能太玄幻，必须能融入现实逻辑",
    },
    "民间灵异": {
        "options": [
            "无（纯世俗法术）",
            "阴阳眼（能看见普通人看不见的东西）",
            "鬼差身份（半官方的阴阳使者）",
            "体内有保护性的阴灵附身",
        ],
        "probability": [0.35, 0.30, 0.20, 0.15],
        "note": "灵异题材本身就是虚构，金手指要与术法体系自洽",
    },
    "盗墓探险": {
        "options": [
            "无（纯技术流，靠本事）",
            "家传秘术（祖辈传下的特殊感知能力）",
            "古物共鸣（接触文物能感受残留信息）",
        ],
        "probability": [0.50, 0.30, 0.20],
        "note": "盗墓题材注重写实感，金手指不宜太强，避免破坏生存张力",
    },
    "重生穿越": {
        "options": [
            "重生本身就是金手指（前世记忆）",
            "穿书（知道剧情走向）",
            "穿越带系统",
            "灵魂互换",
        ],
        "probability": [0.40, 0.30, 0.20, 0.10],
        "note": "本题材以金手指为核心，但必须有明确的局限性和代价",
    },
}

# 题材与变量的兼容约束
GENRE_VARIABLE_CONSTRAINTS = {
    "宫斗权谋": {
        "targeting_range": (15, 90),
        "note": "开篇不会直接被杀，有政治博弈空间",
        "logic_preferred": ["设局逻辑", "忍辱逻辑", "野心家逻辑"],
        "mode_preferred": ["暗流涌动", "浮沉逆转", "极渊求生"],
    },
    "修仙玄幻": {
        "targeting_range": (0, 100),
        "note": "所有变量范围均可，灵活度最高",
        "logic_preferred": ["复仇逻辑", "野心家逻辑", "执念逻辑"],
        "mode_preferred": ["极渊求生", "极道横推", "浮沉逆转"],
    },
    "都市现代": {
        "targeting_range": (0, 95),
        "note": "极端情况（针对度>=95）需要有合理的现实解释",
        "logic_preferred": ["复仇逻辑", "野心家逻辑", "设局逻辑"],
        "mode_preferred": ["暗流涌动", "浮沉逆转", "极道横推"],
    },
    "民间灵异": {
        "targeting_range": (20, 90),
        "note": "灵异元素本身提供压力，变量不需要极端",
        "logic_preferred": ["忍辱逻辑", "推理逻辑", "执念逻辑"],
        "mode_preferred": ["极渊求生", "暗流涌动", "极渊坠落"],
    },
    "盗墓探险": {
        "targeting_range": (30, 85),
        "note": "压力多来自环境和古墓，人为针对不是主轴",
        "logic_preferred": ["推理逻辑", "忍辱逻辑", "设局逻辑"],
        "mode_preferred": ["极渊求生", "暗流涌动"],
    },
}
```

---

## 二、节点一：引爆器（`genesis_ignition_node.py`，替代原 `opening_gen_node.py`）

```python
"""
genesis_ignition_node：变量配方引爆开篇

职责：
  Step1：在题材约束内生成一套变量配方（含金手指）
  Step2：把配方作为整体张力注入，引爆 500-800 字开篇
  Step3：开篇作为 Genesis Stone，等待用户确认

关键原则：
  变量是化学配方，感受整体张力，不是逐条执行模板
  金手指（如有）必须自然融入开篇，禁止写"叮！系统绑定成功"
  开篇不需要交代所有背景，直接切入核心冲突画面
"""
import random
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from knowledge.story_variables import (
    VARIABLE_COMBINATIONS,
    FICTIONAL_HOOKS,
    GENRE_VARIABLE_CONSTRAINTS,
)
from utils.display import node_step, node_done
import logging

logger = logging.getLogger("deepnovel.genesis")


async def genesis_ignition_node(state: CreationState) -> Command:
    genre    = state.get("genre", "通用")
    platform = state.get("platform_style", "番茄男频")

    node_step("生成故事变量配方")

    # ── 生成变量配方 ─────────────────────────────────────────────────
    constraints    = GENRE_VARIABLE_CONSTRAINTS.get(genre, {})
    td_range       = constraints.get("targeting_range", (0, 100))
    logic_preferred = constraints.get("logic_preferred", list(VARIABLE_COMBINATIONS["logic_tone"].keys()))
    mode_preferred  = constraints.get("mode_preferred",  list(VARIABLE_COMBINATIONS["mode_tone"].keys()))

    targeting_degree = random.randint(*td_range)
    emotional_degree = random.randint(-100, 100)
    human_logic      = random.choice(logic_preferred)
    story_mode       = random.choice(mode_preferred)

    # 金手指（可选）
    hook_data  = FICTIONAL_HOOKS.get(genre, {})
    hook_options = hook_data.get("options", ["无"])
    hook_weights = hook_data.get("probability", [1.0 / len(hook_options)] * len(hook_options))
    fictional_hook = random.choices(hook_options, weights=hook_weights, k=1)[0]

    variables = {
        "targeting_degree": targeting_degree,
        "emotional_degree": emotional_degree,
        "human_logic":      human_logic,
        "story_mode":       story_mode,
        "fictional_hook":   fictional_hook,
    }

    logger.info(f"[创世配方] {variables}")
    node_done("变量配方确定")
    node_step("引爆开篇场景")

    # ── 构建配方描述（整体张力，不是逐条）─────────────────────────
    td_desc = _describe_targeting(targeting_degree)
    ed_desc = _describe_emotional(emotional_degree)
    logic_desc = VARIABLE_COMBINATIONS["logic_tone"].get(human_logic, "")
    mode_desc  = VARIABLE_COMBINATIONS["mode_tone"].get(story_mode, "")

    hook_instruction = ""
    if fictional_hook and fictional_hook != "无":
        hook_instruction = f"""
【虚构元素融入要求】
本故事包含虚构元素：{fictional_hook}
要求：
  将此元素自然融入开篇的绝境或关键时刻
  禁止写"叮！系统绑定成功"等廉价旁白
  通过人物的真实感知和行动来呈现
  此元素要与现实题材设定产生化学反应，而非突兀植入
  示例（重生）：不是"我重生了！"而是"那些记忆像碎片一样涌来，
  她分明看见了三年后自己的死"
"""

    result = await call_llm_json(
        system=f"""
你是一位顶级的网文创作者，擅长开局即高潮的写法。
直接切入核心冲突画面，不做背景科普，不废话。
平台风格：{platform}

开篇的三个必要条件：
  1. 清晰呈现主角的当前处境（是谁，在哪，遭遇了什么）
  2. 有极强的情绪冲击（读者必须立刻感受到张力）
  3. 有不可逆的推动力（主角无法回到过去，故事必须继续）

只返回 JSON，不加任何前言。
""",
        user=f"""
## 变量配方（感受整体张力，不是逐条执行）

题材：{genre}

针对度（{targeting_degree}）：{td_desc}
情感度（{emotional_degree:+d}）：{ed_desc}
主角人性逻辑腔调：{human_logic} — {logic_desc}
故事基调：{story_mode} — {mode_desc}

{hook_instruction}

## 任务

写一段 500-800 字的开篇场景。
必须是具体的画面，不是概述。
结尾必须有强烈的不可逆感（读者必须想知道接下来发生什么）。

返回 JSON：
{{
  "opening_text": "开篇正文（500-800字）"
}}
""",
    )

    opening_text = result.get("opening_text", "")
    node_done("开篇引爆完成")

    # ── 用户确认 ──────────────────────────────────────────────────────
    user_input = interrupt({
        "type":    "opening_review",
        "content": {
            "opening_text": opening_text,
            "variables":    variables,
        },
        "prompt": "请确认故事开篇",
    })

    if user_input.get("action") == "regenerate":
        return Command(goto="genesis_ignition")

    return Command(
        update={
            "genesis_opening":   opening_text,
            "genesis_variables": variables,
        },
        goto="iceberg_deduction",
    )


def _describe_targeting(td: int) -> str:
    if td >= 95: return VARIABLE_COMBINATIONS["targeting_degree"][">=95"]
    if td >= 70: return VARIABLE_COMBINATIONS["targeting_degree"]["70-94"]
    if td >= 40: return VARIABLE_COMBINATIONS["targeting_degree"]["40-69"]
    if td >= 10: return VARIABLE_COMBINATIONS["targeting_degree"]["10-39"]
    return VARIABLE_COMBINATIONS["targeting_degree"]["<=9"]

def _describe_emotional(ed: int) -> str:
    if ed < -80:  return VARIABLE_COMBINATIONS["emotional_degree"]["<-80"]
    if ed < -50:  return VARIABLE_COMBINATIONS["emotional_degree"]["-80~-50"]
    if ed < -20:  return VARIABLE_COMBINATIONS["emotional_degree"]["-50~-20"]
    if ed <= 20:  return VARIABLE_COMBINATIONS["emotional_degree"]["-20~+20"]
    if ed <= 60:  return VARIABLE_COMBINATIONS["emotional_degree"]["+20~+60"]
    return VARIABLE_COMBINATIONS["emotional_degree"][">+60"]
```

---

## 三、节点二：冰山并发推演（`iceberg_deduction_node.py`，替代原推演逻辑）

```python
"""
iceberg_deduction_node：从开篇种子并发反推三个维度

工程核心：asyncio.gather 并发三个独立 LLM 专家
  专家1：人物解构（微观出场人物 + 宏观幕后势力）
  专家2：世界架构（局部环境 + 宏观世界地位）
  专家3：大纲主线（格局放大路径）

冰山原则：
  开篇只是露出水面的一角
  反推必须同时包含微观（开篇级）和宏观（全书级）
  禁止把格局锁死在开篇的新手村里
"""
import asyncio
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
import logging

logger = logging.getLogger("deepnovel.iceberg")


async def iceberg_deduction_node(state: CreationState) -> Command:
    opening   = state.get("genesis_opening", "")
    variables = state.get("genesis_variables", {})
    genre     = state.get("genre", "通用")
    platform  = state.get("platform_style", "番茄男频")

    node_step("冰山并发推演（三专家并行）")

    # ── 三专家并发执行 ────────────────────────────────────────────────
    cast_result, world_result, synopsis_result = await asyncio.gather(
        _deduce_cast(opening, genre, variables),
        _deduce_world(opening, genre),
        _deduce_synopsis(opening, genre, variables),
    )

    node_done("冰山推演完成")

    # ── 用户确认推演结果 ──────────────────────────────────────────────
    user_input = interrupt({
        "type": "iceberg_review",
        "content": {
            "opening_text":    opening,
            "cast_result":     cast_result,
            "world_result":    world_result,
            "synopsis_result": synopsis_result,
        },
        "prompt": "请确认从开篇反推的设定",
    })

    if user_input.get("action") == "regenerate_opening":
        return Command(goto="genesis_ignition")

    if user_input.get("action") == "regenerate_deduction":
        return Command(goto="iceberg_deduction")

    # ── 写入 State（兼容原有字段）────────────────────────────────────
    protagonist_card = cast_result.get("protagonist", {})
    return Command(
        update={
            "protagonist_card": protagonist_card,
            "core_cast":        cast_result,
            "world_setting":    world_result,
            "synopsis":         synopsis_result,
            # 变量轨迹初始值（供 story_arc_plan 使用）
            "variable_trajectories": _build_initial_trajectories(
                cast_result, variables
            ),
        },
        goto="story_arc_plan",
    )


async def _deduce_cast(opening: str, genre: str, variables: dict) -> dict:
    """专家1：人物解构，区分微观出场人物和宏观幕后势力"""
    return await call_llm_json(
        system="""
你是人物解构专家。贯彻冰山理论：
  从开篇不仅提取在场的小人物（微观）
  更要推测出幕后的更高阶势力（宏观）
  开篇出现的敌人往往只是工具，真正的推手在更深处

命运种子原则：
  主角的短期动机（解决眼前麻烦）之外
  必须埋下一个更深的命运种子（为何终将卷入宏观格局）

只返回 JSON，不加任何前言。
""",
        user=f"""
## 开篇场景
{opening}

## 变量配方参考
针对度：{variables.get('targeting_degree')}
情感度：{variables.get('emotional_degree')}
人性逻辑：{variables.get('human_logic')}
金手指：{variables.get('fictional_hook', '无')}

## 任务：反推人物班底

返回 JSON：
{{
  "protagonist": {{
    "standard_name": "主角名字（从开篇中提取或顺理成章推演）",
    "appearance": "外貌特征（1-2个最有辨识度的细节）",
    "background_summary": "背景（解释为什么主角会经历开篇的事）",
    "traits_display": [
      "遇险时 → 开篇中呈现的具体反应",
      "真正愤怒时 → 基于开篇推演",
      "被逼到绝境时 → 基于变量配方推演",
      "最执着的事 → 开篇埋下的执念"
    ],
    "dominant_logics": ["{variables.get('human_logic')}"],
    "immediate_motive": "开篇直接产生的短期动机",
    "destiny_seed": "开篇埋下的命运种子（主角为何终将卷入宏观格局）"
  }},
  "local_cast": [
    {{
      "name": "开篇直接出场或暗示的初期人物",
      "role": "antagonist / protagonist_side / neutral",
      "identity": "身份",
      "connection_to_opening": "与开篇事件的直接关联",
      "initial_emotional": 主角对此人的初始情感度数值,
      "initial_targeting": 此人对主角的初始针对度数值
    }}
  ],
  "macro_shadow_cast": [
    {{
      "name": "幕后高阶势力或终极反派（开篇未直接出场）",
      "identity": "在宏观世界中的地位",
      "connection_to_opening": "此势力如何间接导致了开篇的事件（建立微观与宏观的暗线联系）",
      "appears_from_volume": 3
    }}
  ],
  "ultimate_villain": {{
    "name": "全书最终宿敌",
    "core_motivation": "为什么与主角产生终极冲突",
    "appears_from_volume": 3,
    "human_logic": "野心家逻辑或其他"
  }}
}}
""",
    )


async def _deduce_world(opening: str, genre: str) -> dict:
    """专家2：世界架构，区分局部环境和宏观世界体系"""
    return await call_llm_json(
        system="""
你是世界架构专家。贯彻冰山理论：
  开篇发生的地方是局部（新手村）
  必须推演出这个局部在宏观世界中处于什么位置
  宏观世界的至高规则即使主角现在接触不到，也必须存在

所有设定都必须能解释和支撑开篇场景（逻辑反推，不是凭空创作）

只返回 JSON，不加任何前言。
""",
        user=f"""
## 开篇场景
{opening}

## 题材：{genre}

## 任务：反推世界设定

返回 JSON：
{{
  "local_environment": "开篇所在的微观环境（具体地点、权力生态、生存规则）",
  "macro_world_hierarchy": "开篇所在地在整个宏观世界中处于什么层级/位置（强制推演出更高维度）",
  "world_rules": [
    "直接影响开篇的局部法则（解释为什么这些事会发生）",
    "统治整个宏观世界的至高法则（即使主角目前接触不到）"
  ],
  "power_structure": [
    "微观权力结构（开篇涉及的势力）",
    "宏观权力顶端（开篇未出现但存在的更高层）"
  ],
  "unique_settings": ["开篇暗示的独特世界元素"]
}}
""",
    )


async def _deduce_synopsis(opening: str, genre: str, variables: dict) -> dict:
    """专家3：大纲主线，格局放大路径"""
    return await call_llm_json(
        system="""
你是网文主编。贯彻冰山理论：
  不能让主角永远在开篇的新手村打转
  必须规划出阶梯式的格局放大路线
  从局部小冲突→中期阶段目标→最终颠覆宏观格局

只返回 JSON，不加任何前言。
""",
        user=f"""
## 开篇场景
{opening}

## 变量配方
故事模式：{variables.get('story_mode')}
人性逻辑：{variables.get('human_logic')}
金手指：{variables.get('fictional_hook', '无')}

## 任务：反推故事大纲

返回 JSON：
{{
  "title": "小说标题（2-8字，基于开篇气质）",
  "core_hook": "一句话核心看点",
  "protagonist_desc": "主角定位（行事方式和核心驱动，不写单一技能标签）",
  "core_conflict": "核心冲突（微观冲突如何演化为宏观对决）",
  "volume_1_goal": "第一卷微观目标（解决开篇直接产生的麻烦）",
  "escalation_path": "格局放大路径（局部麻烦→中期阶段目标→终极宏观冲突）",
  "ultimate_goal": "全书终极宏观目标（主角命运中埋藏的更大使命）",
  "direction": "整体走向（一段话概述）"
}}
""",
    )


def _build_initial_trajectories(cast_result: dict, variables: dict) -> list:
    """从推演结果构建变量轨迹的初始值"""
    trajectories = []
    protagonist_name = cast_result.get("protagonist", {}).get("standard_name", "主角")

    for char in cast_result.get("local_cast", []):
        trajectories.append({
            "pair":             f"{protagonist_name} × {char.get('name','')}",
            "initial_emotional": char.get("initial_emotional", 0),
            "initial_targeting": char.get("initial_targeting", 0),
            "human_logics":     [variables.get("human_logic", "推理逻辑")],
            "story_mode":       variables.get("story_mode", "暗流涌动"),
            "trajectory_hint":  "待分卷规划时推演",
        })

    if cast_result.get("ultimate_villain"):
        villain = cast_result["ultimate_villain"]
        trajectories.append({
            "pair":             f"{protagonist_name} × {villain.get('name','')}",
            "initial_emotional": -10,
            "initial_targeting": 5,
            "human_logics":     [villain.get("human_logic", "野心家逻辑")],
            "story_mode":       variables.get("story_mode", "暗流涌动"),
            "trajectory_hint":  "全书宿敌，开篇尚未出场",
        })

    return trajectories
```

---

## 四、`story_arc_plan_node.py` Prompt 更新：三幕五卷双轨结构

在 `_generate_volumes` 函数的 system prompt 里，替换原有的分卷约束为以下内容：

```python
system="""
你是一个资深网文策划编辑。
根据开篇种子和故事设定，规划五卷的完整叙事结构。

必须遵守【三幕五卷双轨结构】，非单调每卷稳升，必须有波峰波谷：

【第一幕 · 卷1：破冰与极渊求生期】
开局三种模式（择一，与开篇自洽）：
  A. 低位起点：底层草根，在规则夹缝中求生
  B. 高位压力：怀璧其罪或身份遗患，遭遇降维打击
  C. 高位跌落：起点高位，遭构陷后坠入极渊重建

无论哪种开局，本卷主角必须持续处于结构性高压。
本卷严禁越阶扳倒全书终极反派。
以建立生存闭环和翻盘线头为胜。

【第二幕 · 卷2-3：棋面破壳与代理人战争】
主角建立基本盘，拔除高位者的核心羽翼。
引起高位者实质重视，进入系统性代理人对抗。
卷2-3严禁与全书终极宿敌完成终局收束型对决。
卷3结尾必须是清晰的阶段性高点（为卷4提供落差或延续）。

【第三幕 · 卷4：核心转折节点（双轨平衡，择一）】

★ 路线A：灵魂黑夜与极限反转
适合：悬疑/复仇/重压逆袭/虐主正剧流
叙事核心：前期过猛终触命脉，遭遇惨烈滑铁卢。
可安排：底牌曝光/羽翼剪除/打入死牢/废功流放等（按题材落地）
关键：反派重入傲慢猫鼠心态（针对度可阶段性暴跌至10）
主角利用傲慢盲区完成最关键质变，暗中布局翻盘伏笔。

★ 路线B：极道横推与层层打穿
适合：无敌流/系统爽文/极道升级/一路横推类
叙事核心：拒绝强行"抑"！主角携卷3大胜之威，
不低头不减速，直接打碎旧规则最后壁垒，杀入反派大本营。
压力来源：敌人更强、规模更大、升级体系解锁更恐怖上限
变量体现：针对度直线飙升至80-90（反派倾尽全力围剿）
主角在极度密集的正面高压下完成终极突破。

两条路线都必须承接卷3的高点，
产生清晰的拐点感（A是落差感，B是升级感），
禁止平淡过桥。

【第四幕 · 卷5：王车易位与终局清算】
全盘解禁。承接卷4拐点后的新格局。
无论走路线A（涅槃归来）还是路线B（一路杀穿）
本卷必须与终极宿敌在同一棋局上进行生杀兑子。
必须让终局Boss全面下场，收束全书核心矛盾。
针对度锁死100，不死不休。

【硬性指令】
  禁止单调"每卷稳升一级"流水账
  禁止第2-3卷提前消费终局对决
  输出时标注卷4选择了路线A还是路线B
  解释该选择如何与开篇变量配方自洽

只返回 JSON，不加任何前言。
"""
```

user prompt 里新增开篇种子注入：

```python
user=f"""
## 开篇种子（Genesis Stone，所有设定的逻辑起点）
{synopsis.get('direction', '')}

## 创世变量配方
故事模式：{state.get('genesis_variables', {}).get('story_mode', '')}
人性逻辑：{state.get('genesis_variables', {}).get('human_logic', '')}
针对度：{state.get('genesis_variables', {}).get('targeting_degree', 0)}

## 全书大纲
核心冲突：{synopsis.get('core_conflict', '')}
格局放大路径：{synopsis.get('escalation_path', '')}
第一卷目标：{synopsis.get('volume_1_goal', '')}
终极目标：{synopsis.get('ultimate_goal', '')}

## 核心人物
终极宿敌：{core_cast.get('ultimate_villain', {}).get('name', '')}
（从第{core_cast.get('ultimate_villain', {}).get('appears_from_volume', 3)}卷开始出场）

## 生成五卷规划

返回 JSON 数组，每卷包含：
[
  {{
    "volume_index": 0,
    "volume_name": "卷名（4-8字）",
    "volume_direction": "本卷核心目标",
    "estimated_chapters": 20,
    "arc_track": "路线A（灵魂黑夜）/ 路线B（极道横推）/ 不适用（仅卷4填写）",
    "location_scope": "本卷主要地点范围",
    "max_opponent_level": "本卷最高对手级别",
    "conflict_intensity": "low / low_medium / medium / high",
    "volume_villain": {{
      "name": "本卷主要反派",
      "motivation": "动机（成本收益合理）"
    }},
    "volume_ally": {{
      "name": "本卷主要盟友",
      "role": "在本卷的作用"
    }},
    "untouchable_characters": ["本卷禁止刻意对立的高阶角色"],
    "targeting_at_end": 本卷结束时的主要反派针对度数值,
    "emotional_at_end": 本卷结束时主角对主要反派的情感度数值,
    "variable_change_reason": "变量为什么会发生这样的变化",
    "plot_nodes": [],
    "has_detailed_plot": false
  }}
]
"""
```

---

## 五、`__main__.py` 新增 interrupt 处理

### 5.1 `opening_review`

```python
elif prompt_type == "opening_review":
    opening_text = content.get("opening_text", "")
    variables    = content.get("variables", {})

    console.print(Panel(
        opening_text,
        title="📖 故事开篇",
        border_style="cyan",
        expand=False,
    ))

    hook = variables.get("fictional_hook", "无")
    hook_str = f"  金手指：{hook}\n" if hook and hook != "无" else ""

    console.print(
        f"\n[dim]创世配方：\n"
        f"  针对度={variables.get('targeting_degree')}  "
        f"情感度={variables.get('emotional_degree'):+d}\n"
        f"  逻辑={variables.get('human_logic')}  "
        f"模式={variables.get('story_mode')}\n"
        f"{hook_str}[/dim]"
    )

    console.print("\n[cyan][1][/cyan] 满意，基于此开篇推演设定")
    console.print("[cyan][2][/cyan] 重新生成开篇（重新掷骰子）")
    choice = input("\n请输入选项：").strip()

    return {"action": "regenerate" if choice == "2" else "approve"}
```

### 5.2 `iceberg_review`

```python
elif prompt_type == "iceberg_review":
    opening      = content.get("opening_text", "")
    cast         = content.get("cast_result", {})
    world        = content.get("world_result", {})
    synopsis     = content.get("synopsis_result", {})

    console.print(Panel(
        opening[:200] + "...",
        title="📖 开篇种子（Genesis Stone）",
        border_style="dim",
        expand=False,
    ))

    console.print(Panel(
        f"[bold]标题：[/bold]{synopsis.get('title', '')}\n\n"
        f"[bold]核心看点：[/bold]{synopsis.get('core_hook', '')}\n\n"
        f"[bold]第一卷目标：[/bold]{synopsis.get('volume_1_goal', '')}\n\n"
        f"[bold]格局放大路径：[/bold]{synopsis.get('escalation_path', '')}\n\n"
        f"[bold]终极目标：[/bold]{synopsis.get('ultimate_goal', '')}",
        title="🌊 冰山全貌（微观→宏观格局）",
        border_style="cyan",
        expand=False,
    ))

    console.print(Panel(
        f"[bold]局部环境：[/bold]{world.get('local_environment', '')}\n\n"
        f"[bold]宏观世界地位：[/bold]{world.get('macro_world_hierarchy', '')}\n\n"
        f"[bold]核心规则：[/bold]\n" +
        "\n".join(f"  • {r}" for r in world.get("world_rules", [])),
        title="🌍 世界设定（局部+宏观）",
        border_style="cyan",
        expand=False,
    ))

    protagonist = cast.get("protagonist", {})
    console.print(Panel(
        f"[bold]{protagonist.get('standard_name', '')}[/bold]\n\n"
        f"命运种子：{protagonist.get('destiny_seed', '')}\n\n"
        f"短期动机：{protagonist.get('immediate_motive', '')}\n\n"
        f"行为倾向：\n" +
        "\n".join(f"  • {t}" for t in protagonist.get("traits_display", [])),
        title="👤 主角人物卡",
        border_style="cyan",
        expand=False,
    ))

    local_cast  = cast.get("local_cast", [])
    shadow_cast = cast.get("macro_shadow_cast", [])
    cast_lines  = []
    if local_cast:
        cast_lines.append("[bold]开篇人物：[/bold]")
        for c in local_cast:
            cast_lines.append(f"  • {c.get('name','')}（{c.get('identity','')}）")
    if shadow_cast:
        cast_lines.append("\n[bold]冰山之下（幕后势力）：[/bold]")
        for c in shadow_cast:
            cast_lines.append(
                f"  • {c.get('name','')}（{c.get('identity','')}）\n"
                f"    暗线：{c.get('connection_to_opening','')}"
            )

    console.print(Panel(
        "\n".join(cast_lines),
        title="👥 人物班底（微观+宏观）",
        border_style="cyan",
        expand=False,
    ))

    console.print("\n[cyan][1][/cyan] 确认，进入分卷规划")
    console.print("[cyan][2][/cyan] 重新推演设定（保留开篇）")
    console.print("[cyan][3][/cyan] 重新生成开篇和设定")
    choice = input("\n请输入选项：").strip()

    if choice == "3":
        return {"action": "regenerate_opening"}
    if choice == "2":
        return {"action": "regenerate_deduction"}
    return {"action": "approve"}
```

---

## 六、数据库变更（`memory/schema.sql`）

```sql
ALTER TABLE novel_projects ADD COLUMN genesis_opening TEXT DEFAULT '';
ALTER TABLE novel_projects ADD COLUMN genesis_variables_json TEXT DEFAULT '{}';
```

---

## 七、`schemas/state.py` 新增字段

```python
class CreationState(TypedDict):
    # 原有字段不变...

    # ★ 新增
    genesis_opening:   str   # 开篇场景正文
    genesis_variables: dict  # 引爆开篇的变量配方（含金手指）
```

---

## 八、`graph/creation/graph.py` 修改

```python
from graph.creation.nodes.genesis_ignition_node import genesis_ignition_node
from graph.creation.nodes.iceberg_deduction_node import iceberg_deduction_node

builder.add_node("genesis_ignition", genesis_ignition_node)
builder.add_node("iceberg_deduction", iceberg_deduction_node)

builder.add_edge("genesis_ignition",  "iceberg_deduction")
builder.add_edge("iceberg_deduction", "story_arc_plan")

# load 节点新增路由：creation_mode="opening" → genesis_ignition
```

```python
# __main__.py 创建方式选项新增
console.print("  [2] 让系统用变量引爆开篇（种子生发模式，自动生成全部设定）")

if mode == "2":
    initial_state["creation_mode"] = "opening"
```

---

## 九、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `knowledge/story_variables.py` | 新增 FICTIONAL_HOOKS 金手指矩阵；补全 GENRE_VARIABLE_CONSTRAINTS |
| `graph/creation/nodes/genesis_ignition_node.py` | 新建，替代原 opening_gen_node |
| `graph/creation/nodes/iceberg_deduction_node.py` | 新建，asyncio.gather 并发三专家 |
| `graph/creation/nodes/story_arc_plan_node.py` | system prompt 替换为三幕五卷双轨结构；user prompt 注入开篇种子 |
| `graph/creation/graph.py` | 注册新节点；load 新增 opening 路由 |
| `__main__.py` | 创建方式新增选项；新增两个 interrupt 处理 |
| `memory/schema.sql` | 新增 genesis_opening、genesis_variables_json |
| `schemas/state.py` | 新增 genesis_opening、genesis_variables |

**不需要修改：** event_chain_gen、path_gen、expand、write 及所有后续节点。
三条创建路径（框架导入/故事方向/开篇种子）最终都汇入 story_arc_plan，后续流程完全共用。

---

## 十、核心设计原则

```
变量是化学配方：
  作为整体感受张力，不是逐条执行模板
  不同配方产生不同的"腔调和底色"

开篇是种子：
  所有设定从开篇有机生长，不是凭空创作
  必须能解释和支撑开篇的每一个细节

冰山并发：
  三专家并发，防止单次调用注意力稀释
  人物/世界/大纲各自专注，互不干扰

格局放大（防新手村锁定）：
  反推必须包含微观（开篇级）和宏观（全书级）
  local_cast + macro_shadow_cast（暗线联系）

三幕五卷双轨（平衡爽文和正剧）：
  路线A：灵魂黑夜，涅槃反转（虐主/正剧/悬疑）
  路线B：极道横推，一路打穿（爽文/无敌/系统流）
  根据开篇变量配方的story_mode自动倾向，不强制
```

---

*DeepNovel 开篇种子系统 v2.0*
*工程重构：并发三专家；新增金手指矩阵；三幕五卷双轨平衡爽文与正剧*
