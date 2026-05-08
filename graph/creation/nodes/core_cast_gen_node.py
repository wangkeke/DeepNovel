"""
core_cast_gen_node：生成全书核心角色班底

生成贯穿全书的 ultimate_villain / lifelong_allies / supreme_power；
草稿写入 state.core_cast_draft，由 human_review_core_cast 确认后入库并进入分卷规划。
"""
from __future__ import annotations
import json
from langgraph.types import Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from prompts.common.high_tier_dynamic import FULL_OPPONENT_DOCTRINE
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from prompts.creation.platform_styles import platform_planning_bundle
from utils.v42_flow import shallow_world_archive
import logging

logger = logging.getLogger("deepnovel.core_cast_gen")


async def core_cast_gen_node(state: CreationState) -> Command:
    synopsis = state.get("synopsis", {}) or {}
    protagonist = dict(state.get("protagonist_card") or {})
    if not protagonist.get("standard_name"):
        pn = (state.get("protagonist_name") or "").strip()
        if pn:
            protagonist["standard_name"] = pn

    # 续传且 DB 已有班底时跳过生成
    existing = state.get("core_cast") or {}
    uv = existing.get("ultimate_villain") if isinstance(existing, dict) else {}
    if state.get("resume_from_db") and isinstance(uv, dict) and (uv.get("name") or "").strip():
        return Command(goto="story_arc_plan")

    pre_draft = state.get("core_cast_draft") or {}
    pre_uv = pre_draft.get("ultimate_villain") if isinstance(pre_draft, dict) else {}
    if (
        isinstance(pre_uv, dict)
        and (pre_uv.get("name") or "").strip()
        and not state.get("resume_from_db")
    ):
        return Command(goto="human_review_core_cast")

    node_step("生成全书核心角色班底")
    wa = state.get("world_archive")
    if not isinstance(wa, dict) or not (
        (str(wa.get("basic_rules") or "").strip())
        or (wa.get("power_structure") or [])
    ):
        ws = state.get("world_setting") if isinstance(state.get("world_setting"), dict) else {}
        wa = shallow_world_archive(ws)
    world_archive_block = ""
    if wa:
        world_archive_block = (
            "\n## 【世界档案 world_archive（最高掌权者/皇帝称谓须与此及 power_structure 一致，禁止另起年号或改名）】\n"
            + json.dumps(wa, ensure_ascii=False, indent=2)
            + "\n"
        )
    _sp_note_example = (
        "备注（动态博弈纲领）：此角色不受任何硬性出场阶段限制，随时可以出入全场景。"
        "但他在面对主角前中期的表现必须遵循【极致的傲慢与随意】：初期他只把主角视为一粒随手可以捻死的灰尘、"
        "或偶然好用的低级一次性工具。他的随口试探或无心发落，可能给主角带来九死一生的死劫，"
        "但他本人绝不会为这个底层棋子的死活耗费任何心机、也绝不留任何复杂的后手。"
        "只有当大后期主角真正建立起能动摇其基本盘的势力时，他才会剥下漫不经心的伪装，"
        "进行平视的、不死不休的真龙绞杀。"
    )
    result = await call_llm_json(
        system=DEEPNOVEL_CONSTITUTION + "\n\n" + f"""
你是一个资深网文策划编辑。
根据小说的宏观设定，生成贯穿全书的核心角色班底。
这些角色是全书骨干，不能随意替换。
只返回 JSON，不加任何前言。

【沙盒特工铁律】
- 你在向世界里投放**活生生的对手与盟友**，**禁止**写「第几章/第几卷才允许出场」类通告单。
- 用 `independent_agenda` 写其**当前独立图谋**（后台在忙什么），用 `action_trigger` 写**与主角线发生硬碰撞的触发条件**（价码到线时自然入场）。
- 碰撞须遵守下文 **价码 ⇄ 刻意针对度**；`note` 仍须写**动态博弈姿态**（可早同框、早碾压式擦过），与 `note` 描述一致。

{FULL_OPPONENT_DOCTRINE}
""",
        user=f"""
{platform_planning_bundle(state)}
{world_archive_block}
## 小说设定
标题：{synopsis.get('title', '')}
核心冲突：{synopsis.get('core_conflict', '')}
走向：{synopsis.get('direction', '')}
世界观：{synopsis.get('world', '')}
主角：{protagonist.get('standard_name', '')}，{synopsis.get('protagonist', '')}

## 生成任务

生成以下三类核心角色，返回 JSON。
`supreme_power.note`：用一段连贯中文概括**本书**最高掌权者的动态姿态（须体现傲慢/随意/不屑细算后手，与价码匹配；勿照抄示例用语，但要同等力度的纲领）。

【主角主感情基线 · lifelong_allies】
- `lifelong_allies` 为 **1～4 人** 的数组（书名宿敌不在此列）；其中 **至少一人** `ebd_bond_kind` 须为 **`family` 或 `romance`**（与 synopsis 中 family/romance 两线不得低于一条铁律一致）。
- **亲情**：可多人，各自 **EBD 独立**，允许一正一负、双正、双负或灰区。
- **爱情/红颜 1：N**：可有多条 `ebd_bond_kind: romance`；在 `relationship` 或 `ebd_note` 中标清 **单恋（谁恋谁）**、**双向**或**未明朗**，禁止默认全员双向深爱。
- 其余槽位可为 `friendship` / `benefactor_debt` 等，与主轴并存。
- **心智三字段（须填写）**：`ultimate_villain` 与 `lifelong_allies` 每一项均须含 `current_mental_state`（当前心智与成熟度）、`mental_growth_path`（心智升级轨迹）、`reverse_scale`（绝对逆鳞，无则填「无」），与冰山/主角卡口径一致。

{{
  "ultimate_villain": {{
    "name": "最终宿敌的名字",
    "identity": "身份定位",
    "core_motivation": "为什么和主角产生终极冲突",
    "independent_agenda": "此人在世界后台的独立图谋（不要写第几章出场，只写其当前目的与资源动作）",
    "action_trigger": "与主角线发生硬碰撞/认真针对的门槛条件（价码与针对度须可辩）",
    "human_logic": "马基雅维利逻辑 / 野心家逻辑 / 执念逻辑 / 复仇逻辑（选一个最匹配的）",
    "current_mental_state": "当前心智与成熟度（如：天真易内耗 / 极度理智果决）",
    "mental_growth_path": "全书心智升级轨迹",
    "reverse_scale": "绝对逆鳞（无则填无）",
    "ebd_to_protagonist": -30,
    "ebd_bond_kind": "blood_feud",
    "ebd_type": "结构性敌对·尚未正面结仇",
    "ebd_note": "情感坐标（非终态）；与 docs/EBD 文档一致"
  }},
  "lifelong_allies": [
    {{
      "name": "亲人或拟亲属名",
      "identity": "身份定位",
      "relationship": "与主角的亲缘/制衡关系",
      "independent_agenda": "在故事当下其独立推进的人生/家族/事业议程",
      "action_trigger": "会迫使其与主角强绑或撕破脸的状态条件",
      "current_mental_state": "当前心智与成熟度",
      "mental_growth_path": "心智升级轨迹",
      "reverse_scale": "绝对逆鳞（无则填无）",
      "ebd_to_protagonist": 25,
      "ebd_bond_kind": "family",
      "ebd_type": "庇护与期待并存",
      "ebd_note": "可与另一亲属 EBD 取反号对照"
    }},
    {{
      "name": "红颜或情感线角色名",
      "identity": "身份定位",
      "relationship": "单恋主角/双向/暧昧未明（写明）",
      "independent_agenda": "其个人当下最执着的目标或处境",
      "action_trigger": "会迫使其在剧情中必须表态/站队/与主角对撞的条件",
      "current_mental_state": "当前心智与成熟度",
      "mental_growth_path": "心智升级轨迹",
      "reverse_scale": "绝对逆鳞（无则填无）",
      "ebd_to_protagonist": 15,
      "ebd_bond_kind": "romance",
      "ebd_type": "好感萌芽或单方面倾慕",
      "ebd_note": "若 1：N 则多名 romance 分列数组元素"
    }}
  ],
  "supreme_power": {{
    "name": "最高掌权者名字",
    "identity": "身份定位",
    "stance_to_protagonist": "初始立场（漠视/中立/潜在助力）",
    "independent_agenda": "作为结构顶端的日常棋局与核心利益（不要写出场表）",
    "action_trigger": "主角或局势触及何种红线时，会从「背景」转为「亲自介入或降维打击」",
    "note": "{_sp_note_example}",
    "ebd_to_protagonist": -10,
    "ebd_bond_kind": "contempt_instrumental",
    "ebd_type": "漠视·不在意",
    "ebd_note": "高位价码与刻意针对度须与 FULL_OPPONENT_DOCTRINE 一致"
  }}
}}

ebd_bond_kind 仅限：friendship | romance | family | rivalry_jealousy | benefactor_debt | alliance_interest | contempt_instrumental | blood_feud
ebd_to_protagonist 整数 −100～100；初始为出场时「对主角」情感坐标。
""",
    )
    if not isinstance(result, dict):
        result = {}
    node_done("核心角色班底生成完成")

    # 写入草稿并由独立审核节点 interrupt；否则 resume 时本会重跑 LLM
    return Command(
        update={"core_cast_draft": result},
        goto="human_review_core_cast",
    )
