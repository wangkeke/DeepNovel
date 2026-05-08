# DeepNovel v4.3 · 长线抗压测试开发指南
## 极速沙盒推演测试脚本（Time-Lapse Sandbox Simulation）

> **文档用途**：将本文档完整发给 Cursor Agent，
> 让它创建专属的长线测试脚本 `scripts/test_long_form_sandbox.py`。
> 本脚本用于在不生成完整正文的情况下，
> 以极低成本验证 DeepNovel v4.3 引擎在长篇距（50-100个事件）下的
> 状态机稳定性、记忆遗忘率和逻辑自洽性。

### 架构纠偏补丁（实现脚本前必读）

1. **禁止**用过程式 `while` 循环顺序调用 `run_event_chain_gen` / `run_path_gen` / 假 `run_stub_write`：**必须**走真实 **LangGraph**（`stream` / `Command(goto=…)`），以测真实路由与 Path 内循环。Stub 应通过 **`patch` 劫持 `write` 所用 LLM**，而非替换整张图。
2. **雷达二（离线 NPC）** 必须观测 **`long_term_stream`**（及可选 Tick 标记），**禁止**用 **`short_term_stream`** 判定未出场 NPC；否则将恒定误报 `NPC_DORMANT`。

---

## 一、核心设计原则

### 为什么需要这个测试脚本？

当前手动测试的问题：
- 每章需要生成2000-3000字正文，耗时耗钱
- 前3章看起来正常的问题，到第20章才会暴露
- 人物崩坏、伏笔遗忘、逻辑死锁无法提前发现
- 换卷逻辑的 Bug 在短测试中永远不会触发

**极速沙盒推演的核心思路**：
把"文笔渲染"层完全 Stub 化，只保留"状态机运转"层，
实现 100 倍速推演，让 30 个事件的测试成本等于以前 1 个事件的成本。

### Stub 化策略

```
正常模式：
  write_node → 生成 2000-3000 字精美正文

测试模式（Stub 化）：
  write_node → 生成 50-100 字核心动作流梗概
  格式要求：必须包含人物动作 + 关键物品 + 场景终态
  示例：
    "陈阎在南津渡口废弃仓库蹲守三小时，用阴骨草引来追踪的
     铜盘法器，趁领队分神之际从后窗逃出，随身带走了那枚铁令牌。
     此刻他藏在地铁B2出口的维修间里，令牌揣在怀中，
     外面传来对讲机的喊话声。"

其他所有逻辑节点保持真实运转：
  event_chain_gen → 真实运行（真实测试状态机流转）
  path_gen → 真实运行
  write → **真实进入图谱节点**，仅 LLM 调用被 Stub（见下文「LangGraph 基座」）
  path_state_extract → 真实运行（真实测试记忆提取与 Path 内循环）
  narrative_extract → 真实运行（真实测试伏笔提取）
  bible_update → 真实运行（真实测试档案回写）
  consistency_node → 真实运行（真实测试一致性校验）
```

### LangGraph 基座（必读 · 禁止过程式主循环）

DeepNovel v4.3 的流转由 **LangGraph** 实现：`Command(goto=…)`、条件边、以及 **Path 内循环**（同一 Event 下 `write` → `path_state_extract` → 下一路径 `write`）均由**真实图边**驱动，而不是 Python 里手写顺序函数。

**错误做法（文档旧版示例已废弃）**  
在测试脚本中用 `while event_num < max_events:` 依次调用 `run_event_chain_gen(state)`、`run_path_gen(state)`、`run_stub_write(state)`……  

**为何致命**  
- **测不到真路由**：换卷、人工审核中断、`auto_arc_transition` 等依赖真实边；顺序调用等于另写一套假状态机，**路由 Bug、死锁 Bug 会被放过**。  
- **抹杀 Path 内循环**：一个 Event 对应多条 Path，必须在图内多次经过 `write`；单次 `run_stub_write` **无法模拟**该内循环。

**正确做法：真实图谱 + 劫持（Mock）LLM**  
1. 使用仓库已编译的创作图（与 `__main__` / 入口一致），通过 **`compiled_graph.stream(...)`**（或项目暴露的等价 `invoke`/`stream` API）驱动运行。  
2. **不要**实现一套「假 `run_*_node`」顺序管道；**要**在测试里用 **`unittest.mock.patch`**（或 `pytest` 的 `monkeypatch`）在图运行前 **动态拦截** `write_node` 内部调用的 **`call_llm` / `call_llm_json`**（以实际 import 路径为准）。  
3. 拦截后改为：用轻量模型 + 本文 **`STUB_WRITE_SYSTEM` / `STUB_WRITE_USER_TEMPLATE`** 生成 50～100 字动作梗概返回，使 **节点返回值与路由行为** 与生产路径一致，仅降低 token 成本。  
4. **事件计数 / 停条件**：以 **`state["completed_events_summary"]` 长度** 或侦测图在 `event_chain_gen` 节点完成后的状态为准，**不要**用简单 `event_num++` 对齐「人工想象中的事件」而忽略了人工审核、自动模式分支等。

实现脚本时，须在 README 或脚本头注释中写明：**本测试依赖真实 LangGraph，Stub 仅限 Write 的 LLM 层。**

---

## 二、脚本创建指令（发给 Cursor 的完整内容）

### 基本信息

**任务目标**：
创建测试脚本 `scripts/test_long_form_sandbox.py`，
测试 DeepNovel v4.3 引擎在长篇距（默认30个事件）下的
状态流转稳定性、记忆遗忘率和逻辑自洽性。

**配置参数**（支持命令行参数）：

```bash
# 基本用法
python scripts/test_long_form_sandbox.py \
  --project-id proj_test_001 \
  --genre "民间灵异" \
  --idea "过阴师爷陈阎追查师父死因" \
  --max-events 30 \
  --stub-model claude-haiku-4-5-20251001

# 从快照恢复继续运行
python scripts/test_long_form_sandbox.py \
  --resume-from logs/snapshots/snapshot_ev025.json \
  --max-events 30

# 注入探针实体（用于实体连续性测试）
python scripts/test_long_form_sandbox.py \
  --probe-entities "独臂傀儡师,铁令牌,引煞阵" \
  --max-events 30
```

---

### 核心修改：write 层 Stub 化（仅 Mock LLM，不调换节点）

**修改位置**：测试脚本 **不** 替换 `write_node` 整节点；在图 **`stream` 运行前** 对 **`write_node` 所使用的 LLM 调用** 做 `patch`，返回 Stub 梗概文本。

**Stub 版 write_node 的提示词**（写入脚本常量）：

```python
STUB_WRITE_SYSTEM = """
你是一个极简剧本场记。
你的任务不是写小说，而是用最少的文字记录"刚刚这条路径里发生了什么"。
"""

STUB_WRITE_USER_TEMPLATE = """
当前路径定义：
  路径名称：{path_name}
  叙事功能：{narrative_function}
  视角角色：{pov_character}
  场景终点：{scene_exit}

前文已确立的核心事实：
{relay_context}

请用 50-100 字输出本路径的核心动作流，必须包含：
1. 人物的关键动作（谁做了什么）
2. 涉及的关键物品或实体（名词必须完整）
3. 路径结束时的物理状态（人在哪里、拿着什么）

不需要文学修辞，不需要心理描写，只需要动作事实。
直接输出，不要加任何说明或前缀。
"""
```

---

### 六个自动监控雷达

**雷达一：记忆防爆雷达（Memory Bloat Monitor）**

```python
def radar_memory_bloat(state: dict, event_id: str) -> dict:
    """
    监控所有角色的 short_term_stream 和 long_term_stream 长度。
    确保记忆流不会随章节无限增长。
    （short_term 条数上限示例为 5；实现时请与 bible_merge / 补丁 I 实际裁剪上限一致，避免假阳性。）
    """
    results = {}
    entity_cards = state.get("confirmed_char_cards", {})
    
    for char_id, card in entity_cards.items():
        short_stream = card.get("short_term_stream", [])
        long_stream = card.get("long_term_stream", [])
        
        results[char_id] = {
            "short_term_length": len(short_stream),
            "long_term_length": len(long_stream),
        }
        
        # Assert：short_term 不超过 5 条
        assert len(short_stream) <= 5, (
            f"❌ MEMORY_BLOAT [{event_id}]: {char_id} 的 short_term_stream "
            f"长度为 {len(short_stream)}，超过上限5条！"
            f"最后一次合并触发时间：{card.get('last_consolidation', '未知')}"
        )
        
        # 警告：long_term 超过 10 条时提醒（不 assert，只警告）
        if len(long_stream) > 10:
            print(
                f"⚠️ MEMORY_WARN [{event_id}]: {char_id} 的 long_term_stream "
                f"已有 {len(long_stream)} 条，建议检查合并策略"
            )
    
    return results


def radar_memory_bloat_report(history: list) -> str:
    """生成记忆长度随事件数的变化曲线（文字版）"""
    lines = ["### 记忆防爆雷达报告"]
    for snapshot in history:
        event_id = snapshot["event_id"]
        for char_id, data in snapshot["memory_bloat"].items():
            lines.append(
                f"  {event_id} | {char_id}: "
                f"short={data['short_term_length']} "
                f"long={data['long_term_length']}"
            )
    return "\n".join(lines)
```

**雷达二：离线推演存活雷达（NPC Off-screen Liveness）**

> **重要（双轨记忆）**：  
> - **轨道 A（在场角色）**：正文路径内内心切片 → 先入 `short_term_stream`，章末合并进 `long_term_stream`。  
> - **轨道 B（离线 NPC）**：未出场，无微观短切片；**World Tick 后台推演** 写入的是 **`long_term_stream`（第一人称后台句）**，**不是** `short_term_stream`。  
> 若雷达二用 `short_term_stream` 判断离线 NPC 是否「还活着」，会 **永久误报 `NPC_DORMANT`**。

```python
def _latest_long_term_tail(card: dict):
    """long_term_stream 在代码中为 str 列表；取末尾一条原文。"""
    lt = card.get("long_term_stream") or []
    if not lt:
        return None, 0
    last = lt[-1]
    text = last if isinstance(last, str) else str(last.get("content", last))
    return text, len(lt)


def radar_npc_liveness(state: dict, event_id: str,
                       core_npcs: list,
                       last_seen_world_tick_event: dict) -> dict:
    """
    扫描未在本事件正文出场的核心 NPC。
    验证离线推演是否体现在 long_term_stream（或你实现的等价 Tick 标记）上。

    - 禁止用 short_term_stream 判定离线 NPC（对其几乎恒为空）。
    - 推荐：比较 long_term_stream 条数或最后一条文本是否含当前/最近 event_id；
      若 bible/entity_db 写入 `last_world_tick_seq` 等字段，可优先用该标记。
    """
    results = {}
    entity_cards = state.get("confirmed_char_cards", {})  # 实际工程可能是 bible.characters / DB，实现时对齐真 state
    # 在场名单：需从 stub 正文解析或 path_state / narrative_extract 结论收集，勿硬编码字段名
    characters_in_scene = state.get("characters_present_in_stub") or []

    for npc_id in core_npcs:
        if npc_id in characters_in_scene:
            results[npc_id] = {"status": "on_screen"}
            continue

        card = entity_cards.get(npc_id, {})
        _, long_len = _latest_long_term_tail(card)
        prev_len = (last_seen_world_tick_event.get(npc_id) or {}).get("long_term_len", 0)

        results[npc_id] = {
            "status": "off_screen",
            "long_term_len": long_len,
            "long_term_grew": long_len > prev_len,
        }
        last_seen_world_tick_event[npc_id] = {"long_term_len": long_len, "at": event_id}

        # 若本事件前后 long_term 未增长，且该 NPC 本应被 World Tick 覆盖，则警告（阈值可由连续事件数实现）
        if long_len == 0 or not results[npc_id]["long_term_grew"]:
            print(
                f"⚠️ NPC_DORMANT [{event_id}]: {npc_id} 已离线，"
                f"long_term_stream 未见本轮可检测增长（请核对 World Tick 是否写入该角色）。"
            )

    return results
```

**雷达三：伏笔闭环雷达（Karmic Ledger Resolution）**

```python
def radar_karmic_resolution(state: dict, event_id: str, 
                             arc_event_threshold: int = 30) -> dict:
    """
    监控 karmic_ledger 的状态。
    检查是否有超过 arc_event_threshold 个事件仍未引爆的死伏笔。
    """
    karmic_ledger = state.get("karmic_ledger", {})
    current_event_num = int(event_id.split("_ev")[-1]) \
        if "_ev" in event_id else 0
    
    pending_seeds = []
    dead_hooks = []
    
    for seed_id, seed in karmic_ledger.items():
        if seed.get("status") == "pending":
            planted_event_num = int(
                seed.get("planted_at", "ev_000").replace("ev_", "")
            ) if "ev_" in seed.get("planted_at", "") else 0
            
            age = current_event_num - planted_event_num
            pending_seeds.append({
                "seed_id": seed_id,
                "description": seed.get("description", ""),
                "age_events": age,
            })
            
            if age > arc_event_threshold:
                dead_hooks.append(seed_id)
    
    # Assert：没有"死伏笔"
    assert len(dead_hooks) == 0, (
        f"❌ DEAD_HOOKS [{event_id}]: 发现 {len(dead_hooks)} 条死伏笔！\n"
        + "\n".join([
            f"  - {s['seed_id']}: {s['description']} "
            f"（已挂起 {s['age_events']} 个事件）"
            for s in pending_seeds if s['seed_id'] in dead_hooks
        ])
        + f"\n伏笔回收率过低，请检查 event_chain_gen 的 hidden_seed 关联逻辑。"
    )
    
    print(
        f"✓ KARMIC [{event_id}]: "
        f"挂起伏笔 {len(pending_seeds)} 条，"
        f"无死伏笔"
    )
    
    return {
        "pending_count": len(pending_seeds),
        "dead_hook_count": len(dead_hooks),
        "pending_seeds": pending_seeds,
    }
```

**雷达四：里程碑与卷推进雷达（Arc Transition Monitor）**

```python
def radar_arc_transition(state: dict, event_id: str, 
                         arc_history: list) -> dict:
    """
    监控卷的推进状态。
    记录换卷触发时的事件号，验证换卷后状态正确重建。
    """
    anchor_progress = state.get("anchor_progress", {})
    current_arc = state.get("current_arc_id", "arc_1")
    
    completed_anchors = [
        aid for aid, status in anchor_progress.items() 
        if status == "completed"
    ]
    pending_anchors = [
        aid for aid, status in anchor_progress.items() 
        if status != "completed"
    ]
    
    result = {
        "current_arc": current_arc,
        "completed_anchors": completed_anchors,
        "pending_anchors": pending_anchors,
        "arc_terminated": False,
    }
    
    # 检查是否触发了换卷
    loop_control = state.get("loop_control", {})
    if loop_control.get("outer_loop_action") == "trigger_arc_end":
        result["arc_terminated"] = True
        arc_history.append({
            "arc_id": current_arc,
            "terminated_at_event": event_id,
            "total_completed_anchors": len(completed_anchors),
        })
        
        print(f"🎯 ARC_TRANSITION [{event_id}]: "
              f"第 {current_arc} 卷收束！"
              f"完成锚点：{completed_anchors}")
        
        # Assert：换卷时所有锚点应当完成
        assert len(pending_anchors) == 0, (
            f"❌ ARC_TRANSITION_ERROR [{event_id}]: "
            f"卷收束时仍有 {len(pending_anchors)} 个未完成锚点：{pending_anchors}\n"
            f"请检查 bible_update 的锚点完成检查逻辑！"
        )
        
        # Assert：换卷后新卷的 arc_anchors 应当被正确加载
        new_arc_anchors = state.get("arc_anchors", [])
        assert len(new_arc_anchors) > 0, (
            f"❌ ARC_RELOAD_ERROR [{event_id}]: "
            f"换卷后新卷的 arc_anchors 为空！"
            f"请检查 story_arc_plan 的卷切换逻辑！"
        )
    
    return result


def radar_arc_transition_report(arc_history: list) -> str:
    """生成换卷历史报告"""
    if not arc_history:
        return "### 卷推进雷达报告\n  测试期间未发生换卷。"
    
    lines = ["### 卷推进雷达报告"]
    for arc in arc_history:
        lines.append(
            f"  {arc['arc_id']}: "
            f"在 {arc['terminated_at_event']} 收束，"
            f"完成锚点 {arc['total_completed_anchors']} 个"
        )
    return "\n".join(lines)
```

**雷达五：实体连续性探针（Entity Continuity Probe）**

```python
def radar_entity_probe(state: dict, event_id: str,
                       probe_entities: list, 
                       probe_history: dict) -> dict:
    """
    主动探测植入的探针实体是否仍然存活于系统记忆中。
    扫描：short_term_stream、long_term_stream、world_lexicon
    输出：每个探针实体的存活状态曲线
    """
    entity_cards = state.get("confirmed_char_cards", {})
    world_lexicon = state.get("world_lexicon", {})
    
    results = {}
    
    for probe in probe_entities:
        probe_name = probe["name"]
        is_alive = False
        found_in = []
        
        # 扫描所有角色的记忆流
        for char_id, card in entity_cards.items():
            short_stream = card.get("short_term_stream", [])
            long_stream = card.get("long_term_stream", [])
            
            all_memories = (
                [m if isinstance(m, str) else m.get("content", "") 
                 for m in short_stream]
                + [m if isinstance(m, str) else m.get("content", "") 
                   for m in long_stream]
            )
            
            for memory in all_memories:
                if probe_name in memory:
                    is_alive = True
                    found_in.append(f"角色记忆:{char_id}")
                    break
        
        # 扫描 world_lexicon
        for lexicon_id, lexicon_item in world_lexicon.items():
            term = lexicon_item.get("term", "")
            if probe_name == term or probe_name in str(lexicon_item):
                is_alive = True
                found_in.append(f"world_lexicon:{lexicon_id}")
                break
        
        results[probe_name] = {
            "alive": is_alive,
            "found_in": found_in,
        }
        
        # 记录到历史曲线
        if probe_name not in probe_history:
            probe_history[probe_name] = []
        probe_history[probe_name].append({
            "event_id": event_id,
            "alive": is_alive,
        })
        
        if not is_alive:
            print(
                f"⚠️ PROBE_LOST [{event_id}]: "
                f"探针实体 '{probe_name}' 已从所有记忆系统中消失！\n"
                f"植入时间：{probe.get('planted_at', '未知')}\n"
                f"这是实体记忆第一次遗忘事件号，请记录。"
            )
    
    return results


def radar_entity_probe_report(probe_history: dict) -> str:
    """生成实体存活率曲线报告（文字版）"""
    lines = ["### 实体连续性探针报告"]
    lines.append("  格式：事件号 | 存活=✓ 遗忘=✗")
    
    for probe_name, history in probe_history.items():
        curve = " ".join([
            f"{h['event_id']}:{'✓' if h['alive'] else '✗'}"
            for h in history
        ])
        lines.append(f"  [{probe_name}]: {curve}")
        
        # 找到首次遗忘的事件号
        first_forgotten = next(
            (h["event_id"] for h in history if not h["alive"]), 
            None
        )
        if first_forgotten:
            lines.append(f"    首次遗忘：{first_forgotten}")
        else:
            lines.append(f"    全程存活 ✓")
    
    return "\n".join(lines)
```

**雷达六：主角能动性比例监控（Protagonist Agency Monitor）**

```python
def radar_protagonist_agency(state: dict, event_id: str,
                              agency_history: list) -> dict:
    """
    监控主角在事件中的能动性类型。
    A=主动委托，B=主动调查，C=被动应对（与 event_chain_gen 补丁 J 一致）。

    实现时须从 state['current_event']['protagonist_tick']['protagonist_tick_type'] 读取，
    勿使用不存在的 protagonist_tick_output 键名。
    """
    current_event = state.get("current_event", {})
    tick = current_event.get("protagonist_tick") or {}
    tick_type = tick.get("protagonist_tick_type", "") or "（缺省）"
    
    agency_history.append({
        "event_id": event_id,
        "tick_type": tick_type,
    })
    
    # 检查连续被动应对
    if len(agency_history) >= 3:
        last_three = [h["tick_type"] for h in agency_history[-3:]]
        if all("C" in t for t in last_three):
            print(
                f"⚠️ PASSIVE_TRAP [{event_id}]: "
                f"主角已连续 {len([h for h in agency_history if 'C' in h['tick_type']])} 个事件处于被动应对状态！\n"
                f"最近3个事件类型：{last_three}\n"
                f"请检查 event_chain_gen 的 Protagonist Tick 是否正确读取了 independent_agenda。"
            )
    
    # 统计总体比例
    total = len(agency_history)
    type_a = sum(1 for h in agency_history if "A" in h["tick_type"])
    type_b = sum(1 for h in agency_history if "B" in h["tick_type"])
    type_c = sum(1 for h in agency_history if "C" in h["tick_type"])
    
    c_ratio = type_c / total if total > 0 else 0
    
    return {
        "current_type": tick_type,
        "total_events": total,
        "type_a_count": type_a,
        "type_b_count": type_b,
        "type_c_count": type_c,
        "c_ratio": c_ratio,
    }


def radar_protagonist_agency_report(agency_history: list) -> str:
    """生成主角能动性比例报告"""
    total = len(agency_history)
    if total == 0:
        return "### 主角能动性报告\n  无数据"
    
    type_a = sum(1 for h in agency_history if "A" in h["tick_type"])
    type_b = sum(1 for h in agency_history if "B" in h["tick_type"])
    type_c = sum(1 for h in agency_history if "C" in h["tick_type"])
    
    lines = ["### 主角能动性比例报告"]
    lines.append(f"  总事件数：{total}")
    lines.append(f"  A主动委托：{type_a} ({type_a/total*100:.1f}%)")
    lines.append(f"  B主动调查：{type_b} ({type_b/total*100:.1f}%)")
    lines.append(f"  C被动应对：{type_c} ({type_c/total*100:.1f}%)")
    
    if type_c / total > 0.3:
        lines.append(
            f"  ❌ 警告：被动应对比例 {type_c/total*100:.1f}% 超过30%阈值！"
        )
    else:
        lines.append(f"  ✓ 能动性比例正常")
    
    return "\n".join(lines)
```

---

### 状态快照机制

```python
import json
import os
from datetime import datetime

SNAPSHOT_DIR = "logs/snapshots"

def save_snapshot(state: dict, event_id: str):
    """每5个事件保存一次完整 State 快照"""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    filename = f"{SNAPSHOT_DIR}/snapshot_{event_id}.json"
    
    # 序列化 state（处理不可序列化的对象）
    serializable_state = _make_serializable(state)
    
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(serializable_state, f, ensure_ascii=False, indent=2)
    
    print(f"💾 SNAPSHOT: 状态快照已保存至 {filename}")


def load_snapshot(snapshot_path: str) -> dict:
    """从快照文件恢复 State"""
    with open(snapshot_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    print(f"🔄 RESUME: 从快照 {snapshot_path} 恢复运行")
    return state


def _make_serializable(obj):
    """递归处理不可序列化的对象"""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(item) for item in obj]
    elif hasattr(obj, "__dict__"):
        return _make_serializable(obj.__dict__)
    else:
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)
```

---

### 主循环与最终报告（LangGraph 驱动 · 非顺序伪代码）

测试脚本的 **`run_sandbox_test` 不得** 采用「`while` + 手动 `run_event_chain_gen` / `run_path_gen` / `run_stub_write`」的过程式管道。以下给出**架构级**正确流程；具体 `stream` API 以仓库 `graph.creation.graph` 或 `__main__` 实际编译方式为准。

```python
def run_sandbox_test(
    project_id: str,
    genre: str,
    idea: str,
    max_events: int = 30,
    stub_model: str = "claude-haiku-4-5-20251001",
    probe_entities_str: str = "",
    resume_from: str = None,
):
    """
    1. 初始化或 load_snapshot 恢复 state。
    2. 可选：compile_graph_once() 得到 app（与正式创作同源）。
    3. 注册 Mock：with patch("…实际路径….call_llm_json", stub_llm_for_write): …
       仅在 write 相关调用链返回 STUB 梗概；其它节点真实调 LLM 或按需再 patch。
    4. 主驱动：for event in app.stream(state, config): 合并增量 state；
       - 依赖真实条件边完成 path 内多轮 write ↔ path_state_extract；
       - 在遇到 human_review 类节点时，测试应用 **自动批准** 的 stub interrupt 或测试专用 config（实现细节由仓库 interrupt 机制决定）。
    5. 停条件：len(state["completed_events_summary"]) >= max_events（或等价节点完成计数），
       且注意自动/人工分支与换卷后的 state 一致。
    6. 每完成「一个业务上闭合的监控点」（例如每个 event_chain_gen 落盘后），
       对当前 state 运行六个雷达；每 N 个事件 save_snapshot。
    7. 结束生成 _generate_final_report(...)。
    """

    # 以下为占位说明，非可运行的一行不落实现：
    # probe_entities / radar_history / arc_history 等同旧版初始化
    # with patch_write_llm(...):
    #     for chunk in app.stream(initial_state, {"recursion_limit": ...}):
    #         state = merge_stream_chunk(state, chunk)
    #         if should_run_radars(state, chunk):
    #             radar_memory_bloat(state, ...)
    #             radar_npc_liveness(state, ..., last_seen_world_tick_event)
    #             ...
    #         if snapshot_due(state):
    #             save_snapshot(state, ...)
    pass


def _generate_final_report(
    radar_history, arc_history, agency_history,
    probe_history, total_events, all_asserts_passed, project_id
):
    """生成最终测试报告（与旧版相同，从略）"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"logs/test_report_{project_id}_{timestamp}.md"

    os.makedirs("logs", exist_ok=True)

    sections = [
        f"# DeepNovel v4.3 长线抗压测试报告",
        f"**项目ID**: {project_id}",
        f"**测试时间**: {timestamp}",
        f"**总推演事件数**: {total_events}",
        f"**整体结果**: {'✅ 全部通过' if all_asserts_passed else '❌ 存在失败项'}",
        "",
        "---",
        "",
        radar_memory_bloat_report(radar_history["memory_bloat"]),
        "",
        radar_arc_transition_report(arc_history),
        "",
        radar_entity_probe_report(probe_history),
        "",
        radar_protagonist_agency_report(agency_history),
        "",
        "---",
        "",
        "### 伏笔回收统计",
    ]

    if radar_history["karmic_resolution"]:
        last_karmic = radar_history["karmic_resolution"][-1]
        sections.append(
            f"  最终挂起伏笔数：{last_karmic.get('pending_count', 'N/A')}"
        )
        sections.append(
            f"  死伏笔数：{last_karmic.get('dead_hook_count', 0)}"
        )

    report_content = "\n".join(sections)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"\n{'='*60}")
    print(f"📋 最终测试报告已生成：{report_path}")
    print(f"{'='*60}")
    print(report_content)
```

---

### 命令行入口

```python
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="DeepNovel v4.3 极速沙盒推演测试"
    )
    parser.add_argument("--project-id", default="sandbox_test_001")
    parser.add_argument("--genre", default="民间灵异")
    parser.add_argument("--idea", default="过阴师爷追查师父死因")
    parser.add_argument("--max-events", type=int, default=30)
    parser.add_argument(
        "--stub-model", 
        default="claude-haiku-4-5-20251001",
        help="用于生成 Stub 正文的轻量模型"
    )
    parser.add_argument(
        "--probe-entities",
        default="",
        help="探针实体名称，逗号分隔，如：'独臂傀儡师,铁令牌'"
    )
    parser.add_argument(
        "--resume-from",
        default=None,
        help="从指定快照恢复运行，如：logs/snapshots/snapshot_ev025.json"
    )
    
    args = parser.parse_args()
    
    run_sandbox_test(
        project_id=args.project_id,
        genre=args.genre,
        idea=args.idea,
        max_events=args.max_events,
        stub_model=args.stub_model,
        probe_entities_str=args.probe_entities,
        resume_from=args.resume_from,
    )
```

---

## 三、验收标准

Cursor 完成脚本后，以下所有测试必须通过才算验收：

```
【功能验收】
□ 测试主路径使用与生产一致的 **LangGraph 编译图**（`stream`/`invoke`），**禁止**仅用顺序 `run_*` 模拟
□ 脚本可以从零开始跑完30个事件不崩溃
□ 每5个事件在 logs/snapshots/ 下生成快照文件
□ --resume-from 参数可以从快照正确恢复继续运行
□ 最终在 logs/ 下生成 .md 格式的测试报告
□ 六个雷达全部运行并在控制台输出结果

【雷达验收】
□ 当某角色的 short_term_stream 超过工程约定上限时，脚本正确报错或告警（阈值须与 `bible_update`/合并策略一致）
□ 离线核心 NPC：雷达依据 **long_term_stream 增长或 Tick 标记** 判断是否沉寂；**不得**仅凭 short_term 判死
□ 当探针实体从记忆中消失时，控制台打印 ⚠️ PROBE_LOST 警告
□ 当主角连续3个事件为 C 类型时，控制台打印 ⚠️ PASSIVE_TRAP 警告
□ 换卷成功时，控制台打印 🎯 ARC_TRANSITION 并记录事件号
□ 测试报告包含实体存活率曲线和主角能动性比例

【鲁棒性验收】
□ 任何 KeyError 或状态机死锁时，脚本保存崩溃快照并打印完整堆栈后退出
□ 脚本可以在 --max-events=5 的情况下快速验证基本流程
```

---

## 四、典型测试场景

### 场景一：基本功能验证（5分钟快测）

```bash
python scripts/test_long_form_sandbox.py \
  --project-id quick_test \
  --genre "民间灵异" \
  --idea "过阴师爷追查师父死因" \
  --max-events 10 \
  --probe-entities "独臂傀儡师,铁令牌"
```

预期：10个事件内不崩溃，探针实体保持存活，雷达全绿。

### 场景二：长线稳定性验证（含换卷）

```bash
python scripts/test_long_form_sandbox.py \
  --project-id long_test \
  --genre "玄幻修仙" \
  --idea "底层散修靠词条逆天改命" \
  --max-events 50 \
  --probe-entities "钥匙碎片,荒芜道蕴,铜盘追踪法器"
```

预期：50个事件，至少触发一次换卷，探针实体存活率曲线完整输出。

### 场景三：从崩溃快照恢复

```bash
# 如果场景二在第28个事件崩溃，从第25个快照恢复
python scripts/test_long_form_sandbox.py \
  --resume-from logs/snapshots/snapshot_ev025.json \
  --max-events 50
```

---

> **文档版本**：DeepNovel v4.3 长线抗压测试开发指南
> **核心技术**：
>   真实 LangGraph 驱动 + **仅 Stub Write 的 LLM 层**（`unittest.mock.patch`，保留全图路由与 Path 内循环）
>   六个自动监控雷达（记忆防爆/离线存活【long_term】/伏笔闭环/卷推进/实体探针/主角能动性）
>   状态快照机制（每5个事件保存，支持从崩溃点恢复）
>   最终测试报告（Markdown格式，包含所有监控曲线）
> **测试目标**：
>   在30个事件内发现所有长线崩坏问题，
>   而不是在写完100章后才发现"这个人物已经忘记了"。