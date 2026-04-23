# DeepNovel 开篇种子系统 — Cursor 执行文档

> 核心设计：变量引爆开篇，开篇反推一切。
> 不是自上而下填空（先设定再写故事）
> 而是自下而上生长（变量→开篇种子→反推世界/人物/大纲）
>
> 冰山理论：开篇只是冰山露出水面的一角
> 反推时必须推演出水面下庞大的宏观世界
> 防止格局被锁死在开篇的新手村里
>
> 改动：新增 opening_gen_node，重构后续四个推演节点
> 原有的 synopsis/world_build/protagonist_card/core_cast 节点
> 在框架导入模式下仍然保留，本系统是新增的"种子生发"路径

---

## 一、变量配方定义

```python
# knowledge/story_variables.py

# 变量配方：作为整体注入，不是逐个标签
# LLM 感受的是整套配方的化学张力，不是单个数字

VARIABLE_COMBINATIONS = {
    # 针对度含义
    "targeting_degree": {
        ">=95": "主角被直接杀死或等同于死（需要重生/穿越/灵魂转移才能延续）",
        "70-94": "主角重创至绝境（坠崖/入狱/家破人亡），生死一线",
        "40-69": "主角被彻底打落谷底但未死，从零开始",
        "10-39": "主角受到打压但有喘息空间，需要谋划",
        "<=9":   "无人针对，主角从草根白手起家",
    },
    # 情感度含义
    "emotional_degree": {
        "<-80":   "背叛/陷害，刻骨仇恨（相爱的人设局/亲人举刀）",
        "-80~-50":"被深深伤害，积累的怨恨和耻辱",
        "-50~-20":"被轻视蔑视，普通欺压",
        "-20~+20":"中性，普通起点",
        "+20~+60":"有守护的人，情感驱动",
        ">+60":   "珍视的感情破碎（失去挚爱/家园），以爱之名的驱动",
    },
    # 人性逻辑的腔调作用
    "logic_tone": {
        "复仇逻辑":   "咬牙切齿，一定要让对方血债血偿",
        "野心家逻辑": "我要往上爬，踩着所有人的头",
        "设局逻辑":   "我会让你们用自己的手毁掉自己",
        "忍辱逻辑":   "现在忍，等我强大了一定让你们还回来",
        "执念逻辑":   "我只要一件事，为此可以放弃一切",
        "绝境逻辑":   "反正已经没有退路了，死也要拉你们垫背",
    },
    # 故事模式的基调作用
    "mode_tone": {
        "极渊求生":  "每一步都是生死边缘，高压到极致",
        "极渊坠落":  "一切都在崩坏，没有轻易的转机",
        "浮沉逆转":  "从最低谷爆发，大起大落",
        "暗流涌动":  "表面平静，危险在水面下积累",
        "双生棋局":  "两段关系互相牵制，牵一发动全身",
    }
}

# 题材与变量的兼容约束
GENRE_VARIABLE_CONSTRAINTS = {
    "修仙玄幻": {
        "targeting_compatible": "all",
        "emotional_notes": "情感度可以涵盖门派恩怨、道侣背叛等",
        "logic_preferred": ["复仇逻辑", "野心家逻辑", "执念逻辑"],
    },
    "宫斗权谋": {
        "targeting_range": (20, 85),  # 开篇不会直接被杀，有政治博弈空间
        "emotional_notes": "情感背叛往往来自政治利益而非纯粹私情",
        "logic_preferred": ["设局逻辑", "忍辱逻辑", "野心家逻辑"],
    },
    "都市现代": {
        "targeting_range": (0, 95),
        "emotional_notes": "情感背叛多为商业或感情双重背叛",
        "logic_preferred": ["复仇逻辑", "野心家逻辑", "设局逻辑"],
    },
    "民间灵异": {
        "targeting_range": (30, 90),
        "emotional_notes": "情感可包含对阴邪的恐惧、被牵连的无辜者",
        "logic_preferred": ["忍辱逻辑", "推理逻辑", "执念逻辑"],
    },
}
```

---

## 二、新建 `graph/creation/nodes/opening_gen_node.py`

```python
"""
opening_gen_node：开篇种子生成节点

职责：
  Step1：LLM 作为整体感受变量配方，引爆开篇场景（500-800字）
  Step2：用户确认开篇
  Step3：开篇作为 Genesis Stone，反推四个维度：
         人物班底（微观+宏观）/ 世界设定（局部+宏观）
         大纲主线（冰山理论）/ 变量轨迹初始值

关键原则：
  变量是化学配方，不是 if-else 触发器
  开篇是种子，后续反推不能被局限在开篇的格局里
  必须区分微观（开篇级）和宏观（全书级）
"""
from __future__ import annotations
import json
import random
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.llm import call_llm_json, call_llm
from utils.display import node_step, node_done
from knowledge.story_variables import (
    VARIABLE_COMBINATIONS,
    GENRE_VARIABLE_CONSTRAINTS,
)
import logging

logger = logging.getLogger("deepnovel.opening_gen")


async def opening_gen_node(state: CreationState) -> Command:
    genre    = state.get("genre", "通用")
    platform = state.get("platform_style", "番茄男频")

    node_step("生成故事开篇种子")

    # ── Step 1：引爆开篇 ─────────────────────────────────────────────
    opening_text, variables = await _ignite_opening(genre, platform)

    node_done("开篇生成完成")

    # ── Step 2：用户确认开篇 ─────────────────────────────────────────
    user_input = interrupt({
        "type":    "opening_review",
        "content": {
            "opening_text": opening_text,
            "variables":    variables,
        },
        "prompt": "请确认故事开篇",
    })

    action = user_input.get("action", "approve")
    if action == "regenerate":
        # 重新引爆（变量重新组合）
        return Command(goto="opening_gen")

    node_step("从开篇反推世界/人物/大纲（冰山扩展）")

    # ── Step 3：冰山扩展，反推四个维度 ──────────────────────────────
    deduction = await _iceberg_deduction(opening_text, genre, platform, variables)

    node_done("开篇反推完成")

    return Command(
        update={
            "opening_text":          opening_text,
            "opening_variables":     variables,
            "synopsis":              deduction.get("synopsis", {}),
            "world_setting":         deduction.get("world_setting", {}),
            "protagonist_card":      deduction.get("protagonist_card", {}),
            "core_cast":             deduction.get("core_cast", {}),
            "variable_trajectories": deduction.get("variable_trajectories", []),
        },
        goto="human_review_opening_deduction",
    )


# ── 引爆开篇 ────────────────────────────────────────────────────────

async def _ignite_opening(genre: str, platform: str) -> tuple[str, dict]:
    """
    让 LLM 作为整体感受变量配方，引爆开篇场景。
    变量是化学配方，不是触发器模板。
    """
    constraints = GENRE_VARIABLE_CONSTRAINTS.get(genre, {})
    td_range = constraints.get("targeting_range", (0, 100))
    preferred_logics = constraints.get("logic_preferred", [])

    # 构建变量配方描述（整体注入，不是逐个标签）
    variable_formula_prompt = f"""
## 变量配方参考（感受整体张力，不是逐条执行）

针对度参考范围（本题材合理范围：{td_range[0]}-{td_range[1]}）：
{chr(10).join(f"  {k}：{v}" for k, v in VARIABLE_COMBINATIONS["targeting_degree"].items())}

情感度参考：
{chr(10).join(f"  {k}：{v}" for k, v in VARIABLE_COMBINATIONS["emotional_degree"].items())}

人性逻辑腔调（本题材倾向：{', '.join(preferred_logics)}）：
{chr(10).join(f"  {k}：{v}" for k, v in VARIABLE_COMBINATIONS["logic_tone"].items())}

故事模式基调：
{chr(10).join(f"  {k}：{v}" for k, v in VARIABLE_COMBINATIONS["mode_tone"].items())}
"""

    # 让 LLM 先确定配方，再引爆开篇
    result = await call_llm_json(
        system=f"""
你是一个顶级的网文故事开篇创作者。
你的任务是：
  1. 在脑海中为这个故事确定一套内部张力配方（变量组合）
  2. 用这套配方引爆一个极致张力的开篇场景
  3. 开篇要具体、有画面感、有极强的情绪冲击

重要原则：
  变量是化学配方，感受整体张力，不是逐条套模板
  开篇必须是一个具体的场景，不是背景介绍
  开篇的格局可以从微观到宏观——一个具体事件可以埋下改变世界的种子
  开篇不需要交代所有背景，但必须让读者感受到：
    这个人是谁（性格/处境）
    发生了什么（极致的戏剧冲突）
    他/她为什么无法回头（不可逆的情节推动力）

平台风格：{platform}（影响文风和节奏）
题材：{genre}

只返回 JSON，不加任何前言。
""",
        user=f"""
{variable_formula_prompt}

## 你的任务

第一步：在脑海中确定一套变量配方
  根据上面的参考，选择最能产生戏剧张力的组合
  配方必须内部自洽（变量之间要能产生化学反应，不是随机拼凑）
  配方要与题材兼容

第二步：用这套配方引爆开篇
  500-800字的具体场景
  必须有极强的情绪冲击
  结尾必须有不可逆的推动力（让主角无法回到过去）

返回 JSON：
{{
  "variables": {{
    "targeting_degree": 85,
    "emotional_degree": -90,
    "human_logic": "复仇逻辑",
    "story_mode": "极渊求生",
    "internal_reasoning": "为什么选择这套配方（一句话）"
  }},
  "opening_text": "开篇正文（500-800字）"
}}
""",
    )

    opening_text = result.get("opening_text", "")
    variables    = result.get("variables", {})
    return opening_text, variables


# ── 冰山扩展：从开篇反推四个维度 ───────────────────────────────────

async def _iceberg_deduction(
    opening_text: str,
    genre: str,
    platform: str,
    variables: dict,
) -> dict:
    """
    从开篇种子反推：人物/世界/大纲/变量轨迹
    冰山理论：开篇是露出水面的一角，反推水面下的庞大宏观世界
    """
    result = await call_llm_json(
        system="""
你是一个顶级的网文策划编辑。
你的任务是从一个开篇场景（种子），反推出完整的小说设定。

冰山理论（最重要的原则）：
  开篇只是冰山露出水面的一角
  你的任务是推演出水面下庞大的宏观世界
  绝对不能把故事格局局限在开篇的"新手村"里
  开篇中出现的敌人是"表层敌人"，背后必然有更深的宏观势力
  开篇所在的地点是"局部地图"，背后必然有更宏大的世界地图
  主角开篇的目标是"短期目标"，命运中必然埋藏着影响全局的长期使命

区分微观和宏观（必须同时包含两个层次）：
  微观：开篇直接呈现的人物、地点、冲突
  宏观：隐藏在幕后的更高阶势力、更广阔的世界、更深远的命运

逻辑生长原则：
  所有设定都必须能解释和支撑开篇场景
  不能凭空造设定，必须是开篇的有机延伸
  反推时问自己：为什么开篇中的事情会发生？背后是什么在推动？

只返回 JSON，不加任何前言。
""",
        user=f"""
## 开篇场景（种子）
{opening_text}

## 开篇变量配方（已确定）
针对度：{variables.get('targeting_degree')}
情感度：{variables.get('emotional_degree')}
人性逻辑：{variables.get('human_logic')}
故事模式：{variables.get('story_mode')}

## 题材：{genre}  平台：{platform}

## 任务：从开篇种子反推以下四个维度

返回 JSON（所有内容必须从开篇中有机生长出来）：

{{
  "protagonist_card": {{
    "standard_name": "主角名字（从开篇中提取或顺理成章推演）",
    "appearance": "外貌（从开篇中呈现的特征）",
    "background_summary": "背景经历（解释为什么主角会经历开篇的事）",
    "traits_display": [
      "遇险时 → 开篇中呈现的具体反应",
      "真正愤怒时 → 基于开篇情境推演",
      "面对不可逆处境时 → 基于开篇推演",
      "最执着的事 → 开篇埋下的执念"
    ],
    "dominant_logics": ["主角的人性逻辑，与变量配方中的人性逻辑呼应"],
    "immediate_motive": "开篇直接产生的短期动机",
    "destiny_seed": "开篇埋下的命运种子（主角未来为何会卷入更大格局）"
  }},

  "core_cast": {{
    "local_cast": [
      {{
        "name": "开篇直接出场或暗示的初期人物",
        "role": "protagonist_side / antagonist / neutral",
        "identity": "身份",
        "connection_to_opening": "与开篇事件的直接关联",
        "relationship_type": "关系类型",
        "initial_emotional": 开篇时主角对此人的情感度数值,
        "initial_targeting": 此人对主角的针对度数值
      }}
    ],
    "macro_shadow_cast": [
      {{
        "name": "隐身幕后、开篇未直接出场的高阶势力或终极反派",
        "identity": "在宏观世界中的地位",
        "connection_to_opening": "这个幕后势力如何间接导致了开篇的事件（微观与宏观的暗线联系）",
        "appears_from_volume": 3
      }}
    ],
    "ultimate_villain": {{
      "name": "全书最终宿敌（可以是幕后之人）",
      "core_motivation": "为什么与主角产生终极冲突",
      "appears_from_volume": 3,
      "human_logic": "人性逻辑"
    }}
  }},

  "world_setting": {{
    "local_environment": "开篇所在的微观环境（具体地点和生态）",
    "macro_world_hierarchy": "开篇所在地在整个宏观世界中的位置（强制设定更高维度的地理或位面）",
    "world_rules": [
      "影响开篇的核心规则（直接解释为什么开篇会发生）",
      "统治整个宏观世界的至高法则（即使主角目前接触不到）"
    ],
    "power_structure": ["微观权力结构", "宏观权力顶端（开篇未出现但存在）"],
    "unique_settings": ["开篇暗示的独特世界元素"]
  }},

  "synopsis": {{
    "title": "基于开篇气质的标题（2-8字）",
    "world": "世界观一句话（从开篇生长出的宏观世界）",
    "protagonist": "主角定位（行事方式和核心驱动，不写单一技能）",
    "core_conflict": "核心冲突（微观冲突如何演化为宏观对决）",
    "direction": "故事走向（阶梯式格局放大路线）",
    "escalation_path": "格局放大路径：开篇的局部冲突→中期的阶段目标→最终颠覆宏观世界的终极冲突",
    "volume_1_goal": "第一卷微观目标（解决开篇直接产生的麻烦）",
    "ultimate_goal": "全书终极宏观目标（主角命运中埋藏的更大使命）"
  }},

  "variable_trajectories": [
    {{
      "pair": "主角 × [初期反派]",
      "initial_emotional": 开篇时的情感度数值,
      "initial_targeting": 开篇时的针对度数值,
      "human_logics": ["人性逻辑"],
      "story_mode": "故事模式",
      "trajectory_hint": "这段关系在全书中大致的变化方向（一句话）"
    }}
  ]
}}
""",
    )

    return result
```

---

## 三、新建 `graph/creation/nodes/human_review_opening_deduction_node.py`

```python
"""
human_review_opening_deduction_node：用户确认开篇反推结果

分四个模块展示：
  开篇场景（再次展示）
  主角人物卡（微观+命运种子）
  世界设定（局部+宏观）
  大纲主线（格局放大路径）
  核心人物班底（本地+幕后）

用户可以逐模块确认或重新生成
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from memory.db import (
    save_framework_to_project,
    update_project_core_cast,
    save_variable_trajectories,
)


async def human_review_opening_deduction_node(state: CreationState) -> Command:
    user_input = interrupt({
        "type": "opening_deduction_review",
        "content": {
            "opening_text":     state.get("opening_text", ""),
            "protagonist_card": state.get("protagonist_card", {}),
            "world_setting":    state.get("world_setting", {}),
            "synopsis":         state.get("synopsis", {}),
            "core_cast":        state.get("core_cast", {}),
        },
        "prompt": "请确认开篇反推的设定",
    })

    action = user_input.get("action", "approve")

    if action == "regenerate_opening":
        # 重新引爆开篇
        return Command(goto="opening_gen")

    if action == "approve":
        project_id = state["project_id"]

        # 写入数据库
        await save_framework_to_project(
            project_id    = project_id,
            synopsis      = state.get("synopsis", {}),
            world_setting = state.get("world_setting", {}),
            volumes       = [],
            write_rules   = "",
        )
        await update_project_core_cast(project_id, state.get("core_cast", {}))
        await save_variable_trajectories(
            project_id, state.get("variable_trajectories", [])
        )

        return Command(
            update={"synopsis_approved": True, "world_approved": True},
            goto="story_arc_plan",
        )
```

---

## 四、`__main__.py` 新增两个 interrupt 处理

### 4.1 `opening_review`

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

    console.print(
        f"\n[dim]内部配方："
        f"针对度={variables.get('targeting_degree')}  "
        f"情感度={variables.get('emotional_degree'):+d}  "
        f"逻辑={variables.get('human_logic')}  "
        f"模式={variables.get('story_mode')}[/dim]"
    )

    console.print("\n[cyan][1][/cyan] 满意，基于此开篇生成设定")
    console.print("[cyan][2][/cyan] 重新生成开篇")
    choice = input("\n请输入选项：").strip()

    if choice == "2":
        return {"action": "regenerate"}
    return {"action": "approve"}
```

### 4.2 `opening_deduction_review`

```python
elif prompt_type == "opening_deduction_review":
    opening    = content.get("opening_text", "")
    synopsis   = content.get("synopsis", {})
    world      = content.get("world_setting", {})
    protagonist = content.get("protagonist_card", {})
    cast       = content.get("core_cast", {})

    # 再次展示开篇
    console.print(Panel(
        opening[:300] + "...",
        title="📖 开篇（种子）",
        border_style="dim",
        expand=False,
    ))

    # 展示格局放大路径
    console.print(Panel(
        f"[bold]标题：[/bold]{synopsis.get('title', '')}\n\n"
        f"[bold]核心冲突：[/bold]{synopsis.get('core_conflict', '')}\n\n"
        f"[bold]第一卷目标：[/bold]{synopsis.get('volume_1_goal', '')}\n\n"
        f"[bold]格局放大：[/bold]{synopsis.get('escalation_path', '')}\n\n"
        f"[bold]终极目标：[/bold]{synopsis.get('ultimate_goal', '')}",
        title="🌊 冰山全貌（微观→宏观）",
        border_style="cyan",
        expand=False,
    ))

    # 展示世界设定
    console.print(Panel(
        f"[bold]局部环境：[/bold]{world.get('local_environment', '')}\n\n"
        f"[bold]宏观世界地位：[/bold]{world.get('macro_world_hierarchy', '')}\n\n"
        f"[bold]核心规则：[/bold]\n" +
        "\n".join(f"  • {r}" for r in world.get("world_rules", [])),
        title="🌍 世界设定",
        border_style="cyan",
        expand=False,
    ))

    # 展示主角
    console.print(Panel(
        f"[bold]标准名：[/bold]{protagonist.get('standard_name', '')}\n\n"
        f"[bold]命运种子：[/bold]{protagonist.get('destiny_seed', '')}\n\n"
        f"[bold]短期动机：[/bold]{protagonist.get('immediate_motive', '')}\n\n"
        f"[bold]行为倾向：[/bold]\n" +
        "\n".join(f"  • {t}" for t in protagonist.get("traits_display", [])),
        title="👤 主角人物卡",
        border_style="cyan",
        expand=False,
    ))

    # 展示人物班底
    local_cast  = cast.get("local_cast", [])
    shadow_cast = cast.get("macro_shadow_cast", [])
    cast_lines  = ["[bold]本地人物（开篇出场）：[/bold]"]
    for c in local_cast:
        cast_lines.append(f"  • {c.get('name','')}（{c.get('identity','')}）")
    cast_lines.append("\n[bold]幕后势力（冰山之下）：[/bold]")
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
    console.print("[cyan][2][/cyan] 重新生成开篇和设定")
    choice = input("\n请输入选项：").strip()

    if choice == "2":
        return {"action": "regenerate_opening"}
    return {"action": "approve"}
```

---

## 五、`graph/creation/graph.py` 修改

### 5.1 注册新节点

```python
from graph.creation.nodes.opening_gen_node import opening_gen_node
from graph.creation.nodes.human_review_opening_deduction_node import (
    human_review_opening_deduction_node
)

builder.add_node("opening_gen",                    opening_gen_node)
builder.add_node("human_review_opening_deduction", human_review_opening_deduction_node)
```

### 5.2 新增路径的边

```python
# 开篇种子路径（新增，与框架导入路径并列）
builder.add_edge("opening_gen", "human_review_opening_deduction")
builder.add_edge("human_review_opening_deduction", "story_arc_plan")

# load 节点新增路由分支
# creation_mode = "opening" → opening_gen
# （与 "framework" 和 "normal" 并列）
```

### 5.3 `__main__.py` 创建方式新增选项

```python
console.print("  [1] 我已有故事方向或完整框架（文字或文件）")
console.print("  [2] 让系统用变量引爆开篇（种子生发模式）")  # ← 新增
console.print("  [3] 指定题材（手动输入）")
console.print("  [4] 从题材列表选择")

if mode == "2":
    initial_state["creation_mode"] = "opening"
    # 不需要输入任何内容，系统自动引爆
```

---

## 六、数据库变更

```sql
-- novel_projects 表新增字段
ALTER TABLE novel_projects ADD COLUMN opening_text TEXT DEFAULT '';
ALTER TABLE novel_projects ADD COLUMN opening_variables_json TEXT DEFAULT '{}';
```

```python
# memory/db.py 新增

async def save_opening(
    project_id: str,
    opening_text: str,
    variables: dict,
) -> None:
    import json
    async with get_connection() as conn:
        await conn.execute("""
            UPDATE novel_projects
            SET opening_text = ?,
                opening_variables_json = ?,
                updated_at = datetime('now')
            WHERE project_id = ?
        """, (
            opening_text,
            json.dumps(variables, ensure_ascii=False),
            project_id,
        ))
        await conn.commit()
```

---

## 七、`schemas/state.py` 新增字段

```python
class CreationState(TypedDict):
    # 原有字段不变...

    # ★ 新增
    opening_text:      str   # 开篇场景正文
    opening_variables: dict  # 引爆开篇的变量配方
```

---

## 八、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `knowledge/story_variables.py` | 补充变量含义描述和题材兼容约束 |
| `graph/creation/nodes/opening_gen_node.py` | 新建，包含引爆开篇和冰山扩展 |
| `graph/creation/nodes/human_review_opening_deduction_node.py` | 新建，用户确认界面 |
| `graph/creation/graph.py` | 注册新节点；load 节点新增 opening 路由 |
| `__main__.py` | 创建方式新增选项2；新增两个 interrupt 处理 |
| `memory/schema.sql` | novel_projects 新增 opening_text、opening_variables_json |
| `memory/db.py` | 新增 save_opening |
| `schemas/state.py` | 新增 opening_text、opening_variables |

**不需要修改：** story_arc_plan 及之后的所有节点（开篇反推完成后流程完全一致）。
框架导入路径（creation_mode=framework）保持不变，两条路径最终汇入 story_arc_plan。

---

## 九、核心设计原则

```
变量是化学配方，不是 if-else 触发器：
  感受整体张力，不是逐条执行
  化学反应产生的是"腔调和底色"，不是"模板和套路"

开篇是种子，后续是生长：
  所有设定从开篇中有机延伸
  不能凭空造设定，必须能解释和支撑开篇

冰山理论防止格局锁死：
  开篇只是冰山一角
  反推必须同时包含微观（开篇级）和宏观（全书级）
  local_cast + macro_shadow_cast（暗线联系）
  local_environment + macro_world_hierarchy
  volume_1_goal + ultimate_goal + escalation_path

两种开篇类型都支持：
  宿命死局型：开篇直接点出最终宿敌（锁定目标）
  草根风云型：开篇只是引子（通过冰山扩展推演出幕后大Boss）
```

---

*DeepNovel 开篇种子系统实现文档 v1.0*
*变量引爆开篇，开篇反推一切，冰山理论防止格局锁死*
