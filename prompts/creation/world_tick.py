"""三步命运编织引擎 - World Tick 提示词。"""

from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

WORLD_TICK_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是这个世界的无感情观察者。
你的任务不是讲主角的故事，而是模拟：
如果主角不存在，这个世界此刻正在发生什么。

只做两件事：
1) 世界暗流自转：推导各角色/势力在没有主角时的自然行动；
2) 主角生存轨迹：锁定主角当下最深的生存刚需与代价上限。

禁止在此步骤输出“命运交汇结论”，那是下一节点 Protagonist Collision 的工作。
只返回 JSON，不加前言。"""


WORLD_TICK_USER_TEMPLATE = """## 本章基本信息
章节名：{node_name}
核心张力：{tension_design}
本章起点状态：{input_state_hint}
本章目标状态：{output_state_hint}

## 世界设定（势力与稀缺资源）
{world_setting_summary}

## 关键角色当前状态
{char_cards_summary}

## 上一章末尾状态
{prev_output_state}

## 本卷事件链节奏参考
{event_chain_context}

输出 JSON：
{{
  "node_index": {node_index},
  "independent_agendas": [
    {{
      "character_or_faction": "角色或势力名",
      "current_pressure": "最紧迫压力",
      "current_opportunity": "当前机会",
      "natural_action": "无主角时自然行动",
      "action_ripple": "行动波及"
    }}
  ],
  "world_events_in_motion": [
    "宏观事件"
  ],
  "protagonist_need": "主角最深刚需",
  "protagonist_cost_ceiling": "主角可承受代价上限"
}}"""


def format_world_tick_section(tick: dict) -> str:
    """将 current_world_tick 格式化为注入文本。"""
    if not tick:
        return ""
    agendas = tick.get("independent_agendas") or []
    agenda_lines = []
    for ag in agendas:
        agenda_lines.append(
            f"  • **{ag.get('character_or_faction', '?')}**：{ag.get('current_pressure', '')}\n"
            f"    → 自然行动：{ag.get('natural_action', '')}\n"
            f"    → 波及：{ag.get('action_ripple', '')}"
        )
    world_events = tick.get("world_events_in_motion") or []
    world_lines = "\n".join(f"  • {x}" for x in world_events) if world_events else "  （无）"
    return (
        "## World Tick（世界自转）\n\n"
        "### 世界独立议程\n"
        + ("\n".join(agenda_lines) if agenda_lines else "  （无）")
        + "\n\n### 宏观事件背景\n"
        + world_lines
        + "\n\n### 主角生存刚需\n"
        + f"  需求：{tick.get('protagonist_need', '')}\n"
        + f"  代价上限：{tick.get('protagonist_cost_ceiling', '')}"
    )
