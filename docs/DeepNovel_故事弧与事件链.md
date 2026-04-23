# DeepNovel 故事弧规划与事件链系统 — Cursor 执行文档

> 解决"路径规划步子迈太大、前期就引入高级反派"的根本问题。
> 核心：在 synopsis 和 path_gen 之间插入三个新节点，
> 形成完整的规划漏斗：全书班底 → 分卷规划 → 事件链 → 批次节点
>
> 改动范围：新增3个节点、新增3个数据库字段、修改 path_gen 注入逻辑。

---

## 一、新增的整体流程

```
synopsis → world_setting → protagonist_card
    ↓
[新增] core_cast_gen → human_review_core_cast
    ↓
[新增] story_arc_plan → human_review_story_arc
    ↓
mode_select
    ↓
[每卷开始时执行一次]
    ↓
[新增] event_chain_gen（两步生成）→ human_review_event_chain
    ↓
[每批取 6-10 个事件]
    ↓
path_gen（从事件链取当前批次，转化为节点）
    ↓
expand1 → expand2 → write → tension_check
    ↓
bible_update → update_weight
    ↓
[当前批次完成 → 取下一批事件]
[本卷事件链耗尽 → 下一卷 event_chain_gen]
[全部卷完成 → human_review_batch 结束选项]
```

---

## 二、数据库变更（`memory/schema.sql`）

```sql
-- novel_projects 表新增字段（由 init_db() 幂等迁移，勿手写 story_arcs_json）
ALTER TABLE novel_projects ADD COLUMN core_cast_json TEXT DEFAULT '{}';
-- 全书核心角色班底

ALTER TABLE novel_projects ADD COLUMN event_chain_json TEXT DEFAULT '{}';
-- 当前卷的完整事件链 + 续写游标
-- 格式：{"volume_index": 0, "events": [...], "chain_pos": 0}
-- chain_pos：下一批 path_gen 从 events[chain_pos:] 开始取切片；每批正文全部写完后
-- 在 update_weight_node 中加上本批消费的 last_event_batch_size，并写回 DB（path_gen 驳回不重跑时不会误推进）
```

### volumes_json 每卷新增字段

原有字段保留，新增：

```json
{
  "volume_index": 0,
  "volume_name": "浣衣求生",
  "volume_direction": "主角从底层宫女站稳脚跟",
  "estimated_chapters": 20,
  "plot_nodes": [],
  "has_detailed_plot": false,

  "volume_villain": {
    "name": "张嬷嬷",
    "motivation": "贪财贪权，打压新人巩固地位，成本低收益高"
  },
  "volume_ally": {
    "name": "王老太监",
    "role": "消息来源，关键时刻递话"
  },
  "untouchable_characters": ["皇后", "贵妃", "皇帝", "各宫主位"],
  "location_scope": "浣衣局及底层宫区",
  "max_opponent_level": "掌事嬷嬷",
  "conflict_intensity": "low"
}
```

---

## 三、默认章节数经验值

在 `story_arc_plan_node` 里写死，用户可以调整：

```python
DEFAULT_ARC_PLAN = [
    {
        "volume_index":    0,
        "volume_name":     "（待生成）",
        "estimated_chapters": 20,   # 建立期，节奏紧凑
        "conflict_intensity": "low",
    },
    {
        "volume_index":    1,
        "volume_name":     "（待生成）",
        "estimated_chapters": 25,   # 发展期
        "conflict_intensity": "low_medium",
    },
    {
        "volume_index":    2,
        "volume_name":     "（待生成）",
        "estimated_chapters": 30,   # 升级期
        "conflict_intensity": "medium",
    },
    {
        "volume_index":    3,
        "volume_name":     "（待生成）",
        "estimated_chapters": 30,   # 高潮期
        "conflict_intensity": "high",
    },
    {
        "volume_index":    4,
        "volume_name":     "（待生成）",
        "estimated_chapters": 20,   # 终章
        "conflict_intensity": "high",
    },
]
# 合计 125 章，约 31 万字
```

事件链数量公式：`estimated_chapters × 1.5`（向上取整）

---

## 四、新建 `graph/creation/nodes/core_cast_gen_node.py`

```python
"""
core_cast_gen_node：生成全书核心角色班底

职责：
  生成贯穿全书的 3 类核心角色：
    ultimate_villain：最终宿敌（全书最高级别对手）
    lifelong_ally：一生挚友（全程陪伴的盟友，1-2个）
    supreme_power：最高掌权者（权力顶端；**可早同框**，`note` 写动态博弈姿态与价码⇄刻意针对度，**禁止**死板「前期不得正面登场」）

这些角色提前锁定，后续任何节点都不能凭空引入
新的同等级角色。
"""
from __future__ import annotations
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from memory.db import update_project_core_cast
import logging

logger = logging.getLogger("deepnovel.core_cast_gen")


async def core_cast_gen_node(state: CreationState) -> Command:
    synopsis   = state.get("synopsis", {})
    world      = state.get("world_setting", {})
    protagonist = state.get("protagonist_card", {})

    node_step("生成全书核心角色班底")

    result = await call_llm_json(
        system="""
你是一个资深网文策划编辑。
根据小说的宏观设定，生成贯穿全书的核心角色班底。
这些角色是全书骨干，不能随意替换。
只返回 JSON，不加任何前言。
""",
        user=f"""
## 小说设定
标题：{synopsis.get('title', '')}
核心冲突：{synopsis.get('core_conflict', '')}
走向：{synopsis.get('direction', '')}
世界观：{synopsis.get('world', '')}
主角：{protagonist.get('standard_name', '')}，{synopsis.get('protagonist', '')}

## 生成任务

生成以下三类核心角色，返回 JSON：
{{
  "ultimate_villain": {{
    "name": "最终宿敌的名字",
    "identity": "身份定位",
    "core_motivation": "为什么和主角产生终极冲突",
    "appears_from_volume": 3,
    "human_logic": "野心家逻辑 / 执念逻辑 / 复仇逻辑（选一个最匹配的）"
  }},
  "lifelong_allies": [
    {{
      "name": "挚友名字",
      "identity": "身份定位",
      "relationship": "和主角的关系起点",
      "appears_from_volume": 0
    }}
  ],
  "supreme_power": {{
    "name": "最高掌权者名字",
    "identity": "身份定位",
    "stance_to_protagonist": "初始立场（漠视/中立/潜在助力）",
    "appears_from_volume": 2,
    "note": "备注（动态博弈纲领）：无硬性出场阶段限制；前中期极致傲慢与随意，低价码时不屑细算后手；大后期价码到时再平视终局绞杀（须结合本书人设撰写）"
  }}
}}
""",
    )

    node_done("核心角色班底生成完成")

    user_input = interrupt({
        "type":    "core_cast_review",
        "content": result,
        "prompt":  "请确认全书核心角色班底",
    })

    action = user_input.get("action", "approve")
    edits  = user_input.get("edits", {})

    final_cast = {**result, **edits}

    await update_project_core_cast(state["project_id"], final_cast)

    return Command(
        update={"core_cast": final_cast},
        goto="story_arc_plan",
    )
```

---

## 五、新建 `graph/creation/nodes/story_arc_plan_node.py`

**实现要点（仓库内代码为准，避免单次 JSON 截断）：**

- **逐卷调用 LLM**：每次只输出 **一个** 卷的 JSON 对象（`NUM_PLAN_VOLUMES=5`），`max_tokens` 适中即可。
- **全局进度锚（防 Pacing Drift）**：串行生成易让模型在前几卷**提前写完终局**。每卷 user 提示注入 `_global_pacing_anchor`：**五卷制**下显性总进度锚为约 **20%×卷号**（第 1 卷≈20% … 第 5 卷收束）；非终卷**禁止**最终决战、一次性解决核心终极矛盾，并为剩余卷保留上升空间。非 5 卷时按卷数均摊百分比。
- **卷间衔接**：每一卷的用户提示中注入 **前序已生成卷的紧凑快照**（卷名、完整方向、地点、烈度、对手上限、正反派名与动机摘要、`untouchable_characters`），并强调与 `synopsis.direction`、宿敌出场卷约束一致，**递进、不重复开局**。
- **框架补全**：同样 **逐卷** 补全；**本批中已补全的前序卷** 会以同样结构注入后续卷，避免禁入名单与层级前后矛盾。

下列代码块为早期设计草稿，逻辑已与上面对齐，**以 `graph/creation/nodes/story_arc_plan_node.py` 源码为准**。

```python
"""
story_arc_plan_node：生成全书分卷规划

职责：
  如果 volumes_json 已有内容（框架导入）：
    补全每卷的 volume_villain/volume_ally/untouchable_characters 字段
    不覆盖用户已定义的内容
  如果 volumes_json 为空（普通创作）：
    生成 5 卷规划，写入 volumes_json（实现上为逐卷生成以保证衔接与防截断）

关键约束：
  每卷的 untouchable_characters 必须包含高于本卷级别的所有角色
  volume_villain 的级别不能超过 max_opponent_level
  conflict_intensity 随卷数递增
"""
from __future__ import annotations
import json
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from memory.db import save_framework_to_project, get_volumes
import logging

logger = logging.getLogger("deepnovel.story_arc_plan")

DEFAULT_ESTIMATED_CHAPTERS = [20, 25, 30, 30, 20]
DEFAULT_CONFLICT_INTENSITY  = ["low", "low_medium", "medium", "high", "high"]


async def story_arc_plan_node(state: CreationState) -> Command:
    project_id = state["project_id"]
    synopsis   = state.get("synopsis", {})
    core_cast  = state.get("core_cast", {})

    existing_volumes = await get_volumes(project_id)
    has_existing = bool(existing_volumes)

    node_step("生成分卷规划" if not has_existing else "补全分卷约束字段")

    if has_existing:
        volumes = await _enrich_existing_volumes(
            existing_volumes, synopsis, core_cast
        )
    else:
        volumes = await _generate_volumes(synopsis, core_cast)

    user_input = interrupt({
        "type":    "story_arc_review",
        "content": volumes,
        "prompt":  "请确认全书分卷规划（可调整每卷章节数）",
    })

    action    = user_input.get("action", "approve")
    edits     = user_input.get("edits", {})

    # 用户可以调整章节数
    if "chapter_adjustments" in edits:
        for vol_idx, new_chapters in edits["chapter_adjustments"].items():
            idx = int(vol_idx)
            if idx < len(volumes):
                volumes[idx]["estimated_chapters"] = new_chapters

    await save_framework_to_project(
        project_id    = project_id,
        synopsis      = state.get("synopsis", {}),
        world_setting = state.get("world_setting", {}),
        volumes       = volumes,
        write_rules   = state.get("user_write_rules", ""),
    )

    return Command(
        update={
            "volumes":              volumes,
            "current_volume_index": 0,
        },
        goto="mode_select",
    )


async def _generate_volumes(synopsis: dict, core_cast: dict) -> list:
    """普通创作模式：从 synopsis 生成 5 卷规划"""
    result = await call_llm_json(
        system="""
你是一个资深网文策划编辑。
根据小说设定，生成合理的五卷规划。
每卷要有明确的阶段目标、地点范围、对手级别上限。
只返回 JSON，不加任何前言。
""",
        user=f"""
## 小说设定
{json.dumps(synopsis, ensure_ascii=False)}

## 全书核心角色
最终宿敌：{core_cast.get('ultimate_villain', {}).get('name', '')}
（从第{core_cast.get('ultimate_villain', {}).get('appears_from_volume', 3)}卷开始出现）

## 生成五卷规划

返回 JSON 数组，每个卷包含：
[
  {{
    "volume_index": 0,
    "volume_name": "卷名（4-8字）",
    "volume_direction": "本卷核心目标（一句话）",
    "estimated_chapters": 20,
    "location_scope": "本卷主要活动地点范围",
    "max_opponent_level": "本卷最高对手级别",
    "conflict_intensity": "low / low_medium / medium / high",
    "volume_villain": {{
      "name": "本卷主要反派名字",
      "motivation": "为什么针对主角，成本收益是否合理"
    }},
    "volume_ally": {{
      "name": "本卷主要盟友名字",
      "role": "在本卷承担什么作用"
    }},
    "untouchable_characters": ["高于本卷级别的角色，本卷禁止出现"],
    "plot_nodes": [],
    "has_detailed_plot": false
  }}
]

约束：
  第1卷必须是主角最底层的阶段，对手不能是高层权贵
  每卷的 conflict_intensity 必须递增或持平，不能降低
  untouchable_characters 必须包含比本卷 max_opponent_level 更高级的所有重要角色
""",
    )
    return result if isinstance(result, list) else []


async def _enrich_existing_volumes(
    volumes: list, synopsis: dict, core_cast: dict
) -> list:
    """框架导入模式：补全已有卷的约束字段"""
    result = await call_llm_json(
        system="""
根据已有的分卷信息，补全每卷的约束字段。
只补充缺失的字段，不修改已有内容。
只返回 JSON，不加任何前言。
""",
        user=f"""
## 已有分卷信息
{json.dumps(volumes, ensure_ascii=False)}

## 小说设定
{json.dumps(synopsis, ensure_ascii=False)}

## 全书核心角色
{json.dumps(core_cast, ensure_ascii=False)}

## 任务
为每个卷补全以下字段（如果已存在则保留原值）：
  volume_villain（本卷主要反派）
  volume_ally（本卷主要盟友）
  untouchable_characters（本卷禁止出现的高级角色）
  location_scope（地点范围，如果未定义）
  max_opponent_level（对手上限，如果未定义）
  conflict_intensity（冲突烈度，如果未定义）

返回完整的分卷数组（包含原有字段和补全字段）。
""",
    )
    return result if isinstance(result, list) else volumes
```

---

## 六、新建 `graph/creation/nodes/event_chain_gen_node.py`

```python
"""
event_chain_gen_node：生成当前卷的完整事件链

两步生成法：
  Step 1：生成骨架（极简格式，estimated_chapters × 1.5 个事件）
  Step 2：按批10个填充细节，滑动窗口保证衔接

双轨设计：
  主角线（80%）：主角主动参与的冲突和成长
  世界线（20%）：背景板事件，世界自然运转

写完节奏比预期快的保障：
  1.5倍系数本身是缓冲
  世界线事件随时可以增减调整节奏
"""
from __future__ import annotations
import json
import math
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from memory.db import save_event_chain, get_volumes
import logging

logger = logging.getLogger("deepnovel.event_chain_gen")

EVENTS_PER_DETAIL_BATCH = 10  # 每次填充细节的事件数量


async def event_chain_gen_node(state: CreationState) -> Command:
    project_id   = state["project_id"]
    vol_index    = state.get("current_volume_index", 0)
    volumes      = await get_volumes(project_id)

    if vol_index >= len(volumes):
        logger.warning(f"卷索引越界：{vol_index}，共{len(volumes)}卷")
        return Command(goto="human_review_batch")

    current_vol  = volumes[vol_index]
    est_chapters = current_vol.get("estimated_chapters", 20)
    total_events = math.ceil(est_chapters * 1.5)

    node_step(f"生成第{vol_index+1}卷事件链骨架（共{total_events}个事件）")

    # ── Step 1：生成骨架 ──────────────────────────────────────────────
    skeleton = await _gen_skeleton(current_vol, total_events, state)

    node_done(f"骨架生成完成，共{len(skeleton)}个事件")
    node_step("填充事件细节（按批处理）")

    # ── Step 2：按批填充细节 ───────────────────────────────────────────
    detailed_events = []
    for i in range(0, len(skeleton), EVENTS_PER_DETAIL_BATCH):
        batch     = skeleton[i: i + EVENTS_PER_DETAIL_BATCH]
        context   = detailed_events[-5:] if detailed_events else []
        detailed  = await _fill_details(batch, context, current_vol, state)
        detailed_events.extend(detailed)
        logger.info(f"  细节填充进度：{min(i+EVENTS_PER_DETAIL_BATCH, len(skeleton))}/{len(skeleton)}")

    node_done("事件链生成完成")

    # ── 让用户确认 ────────────────────────────────────────────────────
    user_input = interrupt({
        "type":    "event_chain_review",
        "content": {
            "volume_name":   current_vol.get("volume_name", ""),
            "volume_index":  vol_index,
            "total_events":  len(detailed_events),
            "events":        detailed_events,
        },
        "prompt": "请确认本卷事件链（可增删调整）",
    })

    action = user_input.get("action", "approve")
    if action == "edit":
        detailed_events = user_input.get("edited_events", detailed_events)

    # 写入数据库
    await save_event_chain(project_id, vol_index, detailed_events)

    return Command(
        update={
            "current_event_chain":      detailed_events,
            "current_event_chain_pos":  0,
        },
        goto="path_gen",
    )


async def _gen_skeleton(
    volume: dict, total_events: int, state: dict
) -> list:
    """Step 1：生成极简骨架，只有事件名和主要人物"""

    synopsis    = state.get("synopsis", {})
    protagonist = state.get("protagonist_card", {})
    core_cast   = state.get("core_cast", {})

    villain   = volume.get("volume_villain", {})
    ally      = volume.get("volume_ally", {})
    forbidden = volume.get("untouchable_characters", [])

    result = await call_llm_json(
        system="""
你是一个资深网文策划编辑。
生成连贯的事件骨架，每个事件只需要名称和主要出场人物。
必须严格保证前后因果关系，不能出现逻辑断裂。
只返回 JSON 数组，不加任何前言。
""",
        user=f"""
## 本卷信息
卷名：{volume.get('volume_name', '')}
核心目标：{volume.get('volume_direction', '')}
地点范围：{volume.get('location_scope', '')}
冲突烈度：{volume.get('conflict_intensity', 'low')}
本卷主要反派：{villain.get('name', '')}（动机：{villain.get('motivation', '')}）
本卷主要盟友：{ally.get('name', '')}
本卷禁止出现的角色：{', '.join(forbidden)}

## 主角信息
{protagonist.get('standard_name', '')}：{synopsis.get('protagonist', '')}

## 任务
生成 {total_events} 个连贯事件，格式如下：
[
  {{
    "id": 1,
    "name": "事件名称（10-15字，偏抽象）",
    "event_type": "protagonist_line 或 world_line",
    "main_chars": ["出场人物1", "出场人物2"]
  }}
]

事件构成比例：
  主角线（protagonist_line）：约占 80%
  世界线（world_line）：约占 20%（背景板事件，世界自然发生的变化）

约束：
  禁止出现以下角色：{', '.join(forbidden)}
  冲突烈度限制为：{volume.get('conflict_intensity', 'low')}
  low = 言语羞辱/刁难/繁重差事/被人占便宜
  low_medium = 栽赃/孤立/断人小财路
  medium = 构陷/暗中算计/动用关系打压
  high = 投毒/谋害/性命之忧/朝堂级别斗争
""",
    )
    return result if isinstance(result, list) else []


async def _fill_details(
    batch: list,
    context: list,
    volume: dict,
    state: dict,
) -> list:
    """Step 2：为一批骨架事件填充完整细节"""

    context_text = ""
    if context:
        context_text = "前序已完成事件（用于衔接）：\n" + "\n".join(
            f"  {e['id']}. {e['name']}" for e in context
        )

    result = await call_llm_json(
        system="""
为给定的事件骨架填充完整的细节字段。
必须保证每个事件与前序事件逻辑连贯。
connection_to_previous 字段必须填写，说明如何承接上一个事件。
只返回 JSON 数组，不加任何前言。
""",
        user=f"""
{context_text}

## 待填充的事件骨架
{json.dumps(batch, ensure_ascii=False)}

## 地点和烈度约束
地点范围：{volume.get('location_scope', '')}
冲突烈度：{volume.get('conflict_intensity', 'low')}
本卷反派：{volume.get('volume_villain', {}).get('name', '')}
本卷盟友：{volume.get('volume_ally', {}).get('name', '')}

## 为每个事件填充以下字段，返回完整 JSON 数组

[
  {{
    "id": 1,
    "name": "保持原名不变",
    "event_type": "保持原类型不变",
    "main_chars": ["保持原有，可补充"],
    "location": "具体地点",
    "motivation": "为什么这件事会发生（从人性逻辑出发，成本收益合理）",
    "conflict_intensity": "具体烈度级别",
    "connection_to_previous": "承接上一个事件的哪个状态（必填）",
    "foreshadow_plant": "本事件埋下的伏笔（可以为空）",
    "foreshadow_collect": "本事件回收的伏笔（可以为空）",
    "has_reversal": false,
    "reversal_hint": "如果有反转，简述反转内容（没有则为空）",
    "tension_type": "信息差张力/反转张力/推波助澜张力/困境张力/代价张力/悬念张力"
  }}
]
""",
    )
    return result if isinstance(result, list) else batch
```

---

## 七、`path_gen_node.py` 修改

### 7.1 从事件链取当前批次

```python
from memory.db import get_event_chain

# 获取当前卷的事件链
vol_index   = state.get("current_volume_index", 0)
chain_pos   = state.get("current_event_chain_pos", 0)
event_chain = state.get("current_event_chain") \
              or (await get_event_chain(state["project_id"], vol_index))

# 取当前批次（6-10个事件）
BATCH_SIZE = 8
current_batch = event_chain[chain_pos: chain_pos + BATCH_SIZE]

if not current_batch:
    # 本卷事件链耗尽，进入下一卷
    return Command(
        update={"current_volume_index": vol_index + 1},
        goto="event_chain_gen",
    )
```

### 7.2 新增注入内容

在构造 user_prompt 时，注入事件链和本卷约束：

```python
volumes      = await get_volumes(state["project_id"])
current_vol  = volumes[vol_index] if vol_index < len(volumes) else {}
forbidden    = current_vol.get("untouchable_characters", [])
villain      = current_vol.get("volume_villain", {})

# 事件链批次注入
event_batch_text = "\n".join(
    f"  {i+1}. [{e.get('tension_type','')}] {e['name']}"
    f"（{e.get('location','')}）"
    f"— {e.get('motivation','')}"
    for i, e in enumerate(current_batch)
)

# 禁止角色注入
forbidden_text = "、".join(forbidden) if forbidden else "无"

# 本卷反派注入
villain_text = (
    f"{villain.get('name','')}（动机：{villain.get('motivation','')}）"
    if villain else "无"
)
```

在 PATH_GEN_USER_TEMPLATE 里新增段落：

```
## 本批事件链（严格按此规划节点路径，不允许引入以外的内容）

{event_batch_text}

## 本卷约束

本卷主要反派：{villain_text}
本卷绝对禁止出现的角色：{forbidden_text}
本卷冲突烈度上限：{current_vol.get('conflict_intensity', 'low')}

冲突烈度说明：
  low        = 言语羞辱/刁难/繁重差事/被人占便宜
  low_medium = 栽赃/孤立/断人小财路
  medium     = 构陷/暗中算计/动用关系打压
  high       = 投毒/谋害/性命之忧

禁止：
  超过冲突烈度上限的情节
  禁止角色列表中的角色出现
  引入事件链以外的新主线冲突
```

### 7.3 批次位置与 `last_event_batch_size`

- `path_gen` 只设置 **`last_event_batch_size = len(current_batch)`**，**不**在节点内改写 `current_event_chain_pos`（避免路径被驳回后游标已前移、的事件）。
- 在 **`update_weight_node`** 中，当检测到本批章节已全部写完（`current_node_index >= len(story_path)`）时，执行  
  `chain_pos += last_event_batch_size`，`last_event_batch_size` 归零，并 `update_event_chain_pos` 写回 `event_chain_json`。
- 若 `path_gen` 发现 `chain_pos >= len(events)`：先 **本卷 / 卷间** 路由——仍有下一卷则 `current_volume_index += 1` 并 **`goto event_chain_gen`**；否则 **`goto human_review_batch`**（勿在 `current_node_index` 已越界时仍进入 `expand1`）。

---

## 八、`memory/db.py` 新增函数

```python
实现以 `memory/db.py` 为准：`save_event_chain`、`get_event_chain_record`、`update_event_chain_pos`、`update_project_core_cast`、`get_core_cast`，均使用 `aiosqlite` + `DB_PATH`（与项目其余 DB 访问一致）。
```

---

## 九、`__main__.py` 新增 interrupt 处理

### 9.1 `core_cast_review`

```python
elif prompt_type == "core_cast_review":
    cast = content

    villain = cast.get("ultimate_villain", {})
    allies  = cast.get("lifelong_allies", [])
    supreme = cast.get("supreme_power", {})

    console.print(Panel(
        f"[bold]最终宿敌：[/bold]{villain.get('name','')}（{villain.get('identity','')}）\n"
        f"  动机：{villain.get('core_motivation','')}\n"
        f"  从第{villain.get('appears_from_volume',3)}卷开始出现\n\n"
        f"[bold]一生挚友：[/bold]" +
        "、".join(a.get('name','') for a in allies) + "\n\n"
        f"[bold]最高掌权者：[/bold]{supreme.get('name','')}（{supreme.get('identity','')}）\n"
        f"  初始立场：{supreme.get('stance_to_protagonist','')}\n"
        f"  从第{supreme.get('appears_from_volume',2)}卷开始出现",
        title="👥 全书核心角色班底",
        border_style="cyan",
        expand=False,
    ))

    console.print("\n[cyan][1][/cyan] 确认")
    console.print("[cyan][2][/cyan] 重新生成")
    choice = input("\n请输入选项：").strip()

    if choice == "2":
        return {"action": "regenerate"}
    return {"action": "approve"}
```

### 9.2 `story_arc_review`

```python
elif prompt_type == "story_arc_review":
    volumes = content
    lines   = []
    for v in volumes:
        lines.append(
            f"  第{v['volume_index']+1}卷「{v.get('volume_name','')}」"
            f"  {v.get('estimated_chapters',20)}章  "
            f"  烈度：{v.get('conflict_intensity','low')}\n"
            f"    方向：{v.get('volume_direction','')}\n"
            f"    地点：{v.get('location_scope','')}\n"
            f"    反派：{v.get('volume_villain',{}).get('name','')}\n"
            f"    禁入：{', '.join(v.get('untouchable_characters',[]))}"
        )

    console.print(Panel(
        "\n\n".join(lines),
        title="📚 全书分卷规划",
        border_style="cyan",
        expand=False,
    ))

    console.print("\n[cyan][1][/cyan] 确认")
    console.print("[cyan][2][/cyan] 调整某卷章节数")
    console.print("[cyan][3][/cyan] 重新生成")
    choice = input("\n请输入选项：").strip()

    if choice == "2":
        console.print("请输入卷号和新章节数，格式：1=25 （空格分隔多个）")
        adjustments_input = input("> ").strip()
        adjustments = {}
        for item in adjustments_input.split():
            if "=" in item:
                vol_str, ch_str = item.split("=", 1)
                if vol_str.isdigit() and ch_str.isdigit():
                    adjustments[str(int(vol_str) - 1)] = int(ch_str)
        return {"action": "approve", "edits": {"chapter_adjustments": adjustments}}

    if choice == "3":
        return {"action": "regenerate"}
    return {"action": "approve"}
```

### 9.3 `event_chain_review`

```python
elif prompt_type == "event_chain_review":
    data    = content
    events  = data.get("events", [])
    vol_name = data.get("volume_name", "")

    protagonist_events = [e for e in events if e.get("event_type") == "protagonist_line"]
    world_events       = [e for e in events if e.get("event_type") == "world_line"]

    lines = []
    for e in events:
        prefix = "📌" if e.get("event_type") == "protagonist_line" else "🌍"
        lines.append(
            f"  {prefix} {e['id']:03d}. {e['name']}"
            f"  [{e.get('tension_type','')[:4]}]"
        )

    console.print(Panel(
        "\n".join(lines),
        title=f"📋 「{vol_name}」事件链（主角线{len(protagonist_events)}个 + 世界线{len(world_events)}个）",
        border_style="cyan",
        expand=False,
    ))

    console.print("\n[cyan][1][/cyan] 确认，开始创作")
    console.print("[cyan][2][/cyan] 重新生成事件链")
    choice = input("\n请输入选项：").strip()

    if choice == "2":
        return {"action": "regenerate"}
    return {"action": "approve"}
```

---

## 十、`graph/creation/graph.py` 修改

### 10.1 注册新节点

```python
from graph.creation.nodes.core_cast_gen_node   import core_cast_gen_node
from graph.creation.nodes.story_arc_plan_node  import story_arc_plan_node
from graph.creation.nodes.event_chain_gen_node import event_chain_gen_node

builder.add_node("core_cast_gen",   core_cast_gen_node)
builder.add_node("story_arc_plan",  story_arc_plan_node)
builder.add_node("event_chain_gen", event_chain_gen_node)
```

### 10.2 修改边

```python
# protagonist_card → core_cast_gen（新增）
builder.add_edge("protagonist_card", "core_cast_gen")

# core_cast_gen → story_arc_plan（新增）
builder.add_edge("core_cast_gen", "story_arc_plan")

# story_arc_plan → mode_select（替代原来 protagonist_card → mode_select）
builder.add_edge("story_arc_plan", "mode_select")

# mode_select → event_chain_gen（替代原来 mode_select → path_gen）
builder.add_edge("mode_select", "event_chain_gen")

# event_chain_gen → path_gen
builder.add_edge("event_chain_gen", "path_gen")

# 框架导入流程：human_review_framework → story_arc_plan
# （替代原来 human_review_framework → mode_select）
builder.add_edge("human_review_framework", "story_arc_plan")
```

### 10.3 批内 / 链内 / 卷间路由（与 `human_review_batch` 配合）

**原则：先看本批 `story_path` 是否写完，再看事件链是否还有剩余，最后才切换卷。**

1. **`update_weight` → `expand1` | `human_review_batch` | `auto_review`**（保持现有实现）  
   - `current_node_index < len(story_path)` → 本批未写完 → **`expand1`**。  
   - 否则本批已写完：人工模式 → **`human_review_batch`**；自动模式 → **`auto_review`（batch）**。  
   - 在本批刚写完的这一次 `update_weight` 里推进 **`chain_pos`**（见 7.3），**不要**在这里依据 `chain_pos >= len(chain)` 跳 `event_chain_gen`，否则会与「路径人工确认」时序冲突。

2. **`human_review_batch` 选择「继续」**  
   - 若 **`chain_pos >= len(current_event_chain)`** 且 **还有下一卷** →  
     `current_volume_index += 1`，清空或重载链占位，`batch_index += 1`，**`goto event_chain_gen`**。
   - 否则 **链上仍有事件** → **`goto path_gen`**（取下一切片）。

3. **`path_gen` 入口（防御性）**  
   - 若已 **`chain_pos >= len(events)`** 且还有下一卷 → 直接 **`event_chain_gen`**；若无下一卷 → **`human_review_batch`**。  
   - 避免 `story_path` 已空而仍误入 **`expand1`** 的越界。

4. **自动模式**：`_review_batch` 中与人工 **`human_review_batch`** 保持同一卷切换逻辑（下一卷前先进 **`event_chain_gen`**）。

```python
# update_weight 仍使用 _is_batch_done + expand1 / human_review_batch / auto_review
# 不在此处根据事件链是否耗尽跳转 event_chain_gen
```

---

## 十一、`schemas/state.py` 新增字段

```python
class CreationState(TypedDict):
    # 原有字段不变...

    # ★ 新增
    core_cast:                dict    # 全书核心角色班底
    volumes:                  list    # 分卷规划列表（同 volumes_json）
    current_event_chain:      list    # 当前卷的完整事件链
    current_event_chain_pos:  int     # 当前事件链的批次位置
```

---

## 十二、需要修改的文件总结

| 文件 | 改动 |
|---|---|
| `memory/schema.sql` | novel_projects 新增 core_cast_json、event_chain_json |
| `memory/db.py` | 新增 save_event_chain、get_event_chain、update_project_core_cast、get_core_cast |
| `graph/creation/nodes/core_cast_gen_node.py` | 新建 |
| `graph/creation/nodes/story_arc_plan_node.py` | 新建 |
| `graph/creation/nodes/event_chain_gen_node.py` | 新建 |
| `graph/creation/nodes/path_gen_node.py` | 从事件链取批次；新增事件链和禁止角色注入 |
| `graph/creation/graph.py` | 注册节点；修改边；新增卷切换路由 |
| `schemas/state.py` | 新增 protagonist_card、core_cast、volumes、current_event_chain、current_event_chain_pos、last_event_batch_size |
| `graph/creation/nodes/update_weight_node.py` | 本批完成后推进 chain_pos |
| `graph/creation/nodes/human_review_batch_node.py` | 链耗尽且仍有下一卷时进 event_chain_gen |
| `graph/creation/nodes/auto_review_node.py` | batch 续写时同上 |
| `utils/display.py` / `__main__.py` | 三种新 interrupt 展示与输入 |
| `__main__.py` | 新增三个 interrupt 类型的处理 |

**不需要修改：** expand 节点、write 节点、bible_update、tension_check、auto_review、所有提取流节点。

---

*DeepNovel 故事弧规划与事件链系统实现文档 v1.0*
*解决"前期引入高级反派"和"路径规划步子太大"的根本问题*
