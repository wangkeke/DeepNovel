"""三步命运编织引擎 - Protagonist Collision 提示词。"""

from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

PROTAGONIST_COLLISION_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是最高维度的“命运交汇设计师”。
⚠️【核心动作铁律：是“创设捏合”，绝不是被动“寻找”！】
不要去“寻找”世界议程与主角刚需的碰撞点，因为表面上它们往往毫无关联。
你的任务是：作为上帝之手，利用资源重叠、信息错位、人员交集，
将“世界的独立议程”与“主角的生存刚需”【强行且极其逻辑自洽地捏合在一起】。

💡 捏合示范（卷级）：
- 割裂的平行线（严禁）：世界议程在高层运转，主角只在底层处理私事，二者互不相干。
- 神级自洽捏合（必须采用）：高层议程对资源进行重新分配，恰好卡住主角的生存刚需，
  主角为保命/保人/保核心利益，被迫打破既有本能，主动或被动卷入风暴中心。

接下来，请根据当前卷的定位，灵活选择交汇弹性烈度（余波擦伤 / 视线交错 / 宿命对撞），
并输出“为何这次捏合成立”的清晰逻辑链。

必须做引力三校验：
1) 资源焦点在双方轨迹中都是高优先级；
2) 主角介入由自身刚需逼出，不是主动凑热闹；
3) 主角介入需要违背某个本能或原则。

三项都通过才算成立。只返回 JSON。"""


PROTAGONIST_COLLISION_USER_TEMPLATE = """## 本章信息
章节名：{node_name}
核心张力：{tension_design}

## World Tick 输出（只读输入）
{world_tick_json}

输出 JSON：
{{
  "node_index": {node_index},
  "resource_focal_point": "共同资源焦点",
  "collision_type": "主动撞上 / 被动卷入 / 远远感知信号",
  "protagonist_driven_by_need": true,
  "instinct_or_principle_violated": "主角被迫违背的本能或原则",
  "gravity_check_passed": true,
  "collision_summary": "一句话说明这次交汇为何成立"
}}"""


PROTAGONIST_COLLISION_RETRY_PREFIX = """上次引力校验失败：{failure_reason}
请调整交汇点并重新输出，直到三项校验全部通过。"""


def format_protagonist_collision_section(collision: dict) -> str:
    """将 current_protagonist_collision 格式化为 expand1 注入段落。"""
    if not collision:
        return ""
    return (
        "## Protagonist Collision（引力交汇）\n\n"
        f"- 资源焦点：**{collision.get('resource_focal_point', '')}**\n"
        f"- 碰撞类型：{collision.get('collision_type', '')}\n"
        f"- 主角是否被刚需逼入：{collision.get('protagonist_driven_by_need', False)}\n"
        f"- 被迫违背本能/原则：{collision.get('instinct_or_principle_violated', '')}\n"
        f"- 交汇摘要：{collision.get('collision_summary', '')}"
    )
