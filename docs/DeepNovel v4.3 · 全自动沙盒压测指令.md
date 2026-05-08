# DeepNovel v4.3 · 全自动沙盒压测指令
## Cursor Agent 自主执行版（含防死锁补丁）

> **使用说明**：将本文档完整复制到 Cursor 的 Composer/Agent 模式中，
> 授权其自主执行测试、修复 Bug、生成报告，中途无需人工干预。

---

## 前置说明：为什么需要防死锁补丁

在测试模式下，write_node 被 Stub 化（只输出 50-100 字梗概），
但原有的严格质检节点不知道这是测试环境，会按正文标准拦截 Stub 输出，
导致三类死锁：

```
死锁一：对话占比检测
  auto_review 要求对话占比 ≥ 35%
  50字梗概根本无法满足 → 无限打回重写

死锁二：正文为空导致一致性报错
  stub_write 输出的50字没有正确写入 all_paths_text
  下游 consistency_node 拿到空字符串 → 判定物理空间缺失 → 打回 event_chain_gen

死锁三：数据库主键冲突
  被打回重跑时，上次写入的伏笔ID没有回滚
  第二次写入相同ID → UNIQUE constraint failed → 报错
```

**铁律：测试宏观状态机时，必须关掉微观文笔的质检。**

---

## 🎯 全自动压测指令（直接投喂给 Cursor Agent）

```
Cursor，你已经完成了 test_long_form_sandbox.py 的代码编写。
现在授予你最高级别的自主运行权限，请按以下五个阶段自主执行，
中途遇到任何代码 Bug 请自行阅读堆栈、修改代码、重新运行，不要停下来问我。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段零：打防死锁补丁（必须先完成，否则测试会无限循环烧钱）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

在启动任何测试之前，先打以下三个补丁：

【补丁A：强制放行文笔类质检节点】

在 test_long_form_sandbox.py 的主循环启动前，
利用 unittest.mock.patch 拦截以下节点：

1. 拦截 auto_review_node：
   强制返回 approved=True，不检查对话占比和字数。
   原因：50字梗概永远无法满足对话占比要求，不拦截会无限重写。

2. 拦截 consistency_node：
   强制返回通过（路由到 narrative_extract），
   不检查物理空间连续性和资产连续性。
   原因：Stub正文中没有完整的场景描述，一致性检查没有意义。

示例代码结构：
   with mock.patch("graph.creation.nodes.auto_review_node.auto_review_node",
                   side_effect=lambda state: {**state, "verdict": "approve"}), \
        mock.patch("graph.creation.nodes.consistency_node.consistency_node",
                   side_effect=lambda state: Command(goto="narrative_extract")):
       run_event_loop(...)

注意：mock 的 import 路径必须与项目实际路径一致，
      请先 grep 确认节点函数的实际位置再写 patch 路径。

【补丁B：修复 Stub Write 文本拼装 Bug】

检查 run_stub_write 函数（或 stub write 的实现位置）：
必须确保 Stub 模型生成的 50-100 字梗概，
被正确追加到 state 的以下字段：
  - current_draft（当前路径草稿）
  - all_paths_text（章节合并正文）

绝对不能让 narrative_extract 和 consistency_node 拿到空字符串。
验证方法：在 run_stub_write 完成后，立即 assert len(state["current_draft"]) > 0

【补丁C：修复数据库重复主键 Bug】

找到 bible_update_node 中执行 foreshadow_entries 表 INSERT 的位置，
将写入逻辑改为幂等操作：

SQLite：
  INSERT OR REPLACE INTO foreshadow_entries (...) VALUES (...)
  或
  INSERT INTO foreshadow_entries (...) VALUES (...)
  ON CONFLICT(foreshadow_id) DO UPDATE SET ...

同样的修复应用于 world_lexicon 相关的 INSERT 语句。

三个补丁完成后，先运行一次单事件测试验证补丁有效：
  python scripts/test_long_form_sandbox.py \
    --project-id patch_verify \
    --max-events 1 \
    --probe-entities "测试探针"

确认无报错、无死锁后，进入阶段一。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段一：冒烟测试与自动排错
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

运行 5 事件冒烟测试：

  python scripts/test_long_form_sandbox.py \
    --project-id smoke_test_01 \
    --genre "民间灵异" \
    --idea "过阴师爷陈阎追查师父死因" \
    --max-events 5 \
    --stub-model claude-haiku-4-5-20251001 \
    --probe-entities "镇魂血钱,纸扎店,独臂傀儡师"

自主动作：
  - 监控六个雷达是否全部打印 ✓
  - 如果遇到 KeyError 或 LangGraph 路由断裂，
    自主阅读报错堆栈，修改代码，重新运行
  - 如果发现 mock 没有生效（auto_review 仍在输出长篇评价），
    立刻中止，检查 mock patch 路径，修复后重新运行
  - 目标：5个事件完美跑通，六个雷达全绿，
    logs/snapshots/ 下有 snapshot_ev005.json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段二：长线马拉松压测（含换卷）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

冒烟测试通过后，启动 35 事件长线压测：

  python scripts/test_long_form_sandbox.py \
    --project-id marathon_test_01 \
    --genre "民间灵异" \
    --idea "过阴师爷陈阎追查师父死因，凭厌胜术在都市黑市中以命博命" \
    --max-events 35 \
    --stub-model claude-haiku-4-5-20251001 \
    --probe-entities "镇魂血钱,纸扎店,独臂傀儡师,铜盘追踪法器"

重点监控：

  1. 记忆防爆雷达
     监控主角及核心反派的 long_term_stream 长度
     如果某角色的 long_term_stream 持续增长超过10条，
     立即检查 bible_update 的合并触发逻辑

  2. 卷推进雷达
     观察是否在满足锚点条件后触发了 trigger_arc_end
     记录触发时的事件号
     验证换卷后新卷的 arc_anchors 被正确加载

  3. 快照落盘
     验证每5个事件在 logs/snapshots/ 下生成快照文件
     35个事件应生成 snapshot_ev005 到 snapshot_ev035 共7个文件

  4. 主角能动性
     监控 protagonist_tick_type 的 A/B/C 比例
     如果 C 类（被动应对）超过 30%，记录告警

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段三：断点续传测试
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

长线测试完成后，从第15个事件的快照恢复运行：

  python scripts/test_long_form_sandbox.py \
    --resume-from logs/snapshots/snapshot_ev015.json \
    --max-events 20

验证：
  - 状态机从 ev_016 无缝衔接继续运行
  - 主角的 short_term_stream 和 long_term_stream 保持连续
  - 探针实体的存活状态曲线没有因为续传而重置
  - 六个雷达继续正常运作

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
阶段四：生成终极体检报告
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

三个阶段全部跑通后，读取以下内容：
  - 脚本自动生成的 Markdown 测试报告（logs/test_report_*.md）
  - 终端输出的所有雷达数据
  - 你在跑批过程中发现并修复的所有 Bug

生成一份 logs/DeepNovel_v4.3_架构体检报告.md，必须包含：

1. 测试用例覆盖情况
   - 冒烟测试是否通过（5事件）
   - 长线测试是否触发换卷（记录触发时的事件号）
   - 断点续传是否成功（从ev_016无缝衔接）

2. 六个雷达数据分析

   记忆防爆雷达：
   - 主角 long_term_stream 的最大长度是多少
   - 何时触发了合并（如有）
   - 是否有角色出现记忆防爆警告

   离线推演存活雷达：
   - 核心反派角色在未出场时，是否有 World Tick 后台更新
   - 如果有 NPC_DORMANT 警告，是哪些角色，在哪些事件

   伏笔闭环雷达：
   - 最终挂起伏笔数量
   - 是否有死伏笔（超过30个事件未引爆）
   - 伏笔回收率评估

   卷推进雷达：
   - 换卷是否成功触发
   - 触发时的事件号和已完成锚点数
   - 换卷后新卷是否正确初始化

   实体连续性探针：
   - 每个探针实体的存活率曲线
   - 首次遗忘事件号（如有）
   - 记忆系统的真实衰减曲线

   主角能动性比例：
   - A/B/C 三种类型的最终比例
   - 是否出现 PASSIVE_TRAP 警告
   - 主角能动性是否健康

3. 架构表现点评
   站在 AI 架构师视角，评价以下方面：
   - 双轨记忆系统（short_term + long_term）在 35 个事件推演中的稳定性
   - 里程碑引力场（arc_anchors）对故事方向的约束效果
   - 角色阅历系统（叙事流记忆）的实体保护效果
   - 单元剧结构（主角能动性）的执行情况

4. Bug 修复记录
   列出本次测试中发现并修复的所有 Bug，格式：
   - Bug 描述 → 根本原因 → 修复方案 → 修复后状态

5. 遗留问题与优化建议
   如果雷达发现了任何警告或异常，提出下一步的优化方向

请在所有测试完成后提交最终报告，中途不要停下来问我。
如果测试过程中遇到无法自主修复的根本性架构问题，
先记录到报告的"遗留问题"章节，继续推进其他测试阶段。
```

---

## 参考：六个雷达的预期输出格式

测试过程中，每个事件结束后控制台应输出类似以下内容：

```
────────────────────────────────────────
📍 事件 ev_005 开始推演...
✅ 事件 ev_005 推演完成

📊 运行监控雷达...
  ✓ 记忆防爆雷达：通过（主角 short=3 long=1，反派A short=2 long=0）
  ✓ 离线推演存活雷达：已扫描 2 个核心NPC（反派A已离线但有后台更新）
  ✓ 伏笔闭环雷达：挂起伏笔 3 条，无死伏笔
  ✓ 卷推进雷达：当前卷 arc_1，已完成锚点 1/4
  ✓ 实体探针：镇魂血钱✓ 纸扎店✓ 独臂傀儡师✓ 铜盘追踪法器✓
  ✓ 主角能动性：当前 A类（主动委托），累计 A=3 B=1 C=1，被动比例20%

💾 SNAPSHOT: 状态快照已保存至 logs/snapshots/snapshot_ev005.json
```

如果某个雷达触发警告，应输出：

```
⚠️ PASSIVE_TRAP [ev_008]: 主角已连续 3 个事件处于被动应对状态！
   最近3个事件类型：['C被动应对', 'C被动应对', 'C被动应对']
   请检查 event_chain_gen 的 Protagonist Tick 是否正确读取了 independent_agenda。

⚠️ PROBE_LOST [ev_012]: 探针实体 '独臂傀儡师' 已从所有记忆系统中消失！
   植入时间：ev_001
   这是实体记忆第一次遗忘事件号，请记录。

❌ MEMORY_BLOAT [ev_015]: 主角的 short_term_stream 长度为 7，超过上限5条！
   最后一次合并触发时间：ev_010
```

如果触发换卷：

```
🎯 ARC_TRANSITION [ev_022]: 第 arc_1 卷收束！
   完成锚点：['anchor_1', 'anchor_2', 'anchor_3', 'anchor_4']
   实际章节数：22
   下一卷 arc_2 的 arc_anchors 已正确加载（4个锚点）
```

---

## 快速排错指南

Cursor 在自主修复时可参考以下常见问题：

| 报错 | 根本原因 | 修复方向 |
|------|---------|---------|
| `对话占比不足` | auto_review mock 未生效 | 检查 patch 路径是否与实际函数位置一致 |
| `本章无正文` | stub_write 未写入 current_draft | 在 run_stub_write 末尾强制赋值 state["current_draft"] |
| `UNIQUE constraint failed` | bible_update INSERT 不幂等 | 改为 INSERT OR REPLACE 或 ON CONFLICT DO UPDATE |
| `物理空间断裂` | consistency_node mock 未生效 | 检查 consistency_node 的实际函数名和 import 路径 |
| `KeyError: protagonist_tick_type` | event_chain_gen 输出格式变化 | 在雷达函数中加 .get() 防御性取值 |
| `snapshot_ev005.json 未生成` | 快照保存逻辑的路径问题 | 检查 SNAPSHOT_DIR 是否被正确创建（os.makedirs） |

---

> **文档版本**：DeepNovel v4.3 全自动沙盒压测指令（含防死锁补丁）
> **核心思路**：
>   测试宏观状态机时，必须关掉微观文笔的质检；
>   三个防死锁补丁（Mock质检/修复Stub写入/修复DB幂等）必须在测试前打好；
>   六个雷达覆盖所有长线崩坏风险点；
>   四个阶段（冒烟→马拉松→续传→报告）由 Cursor 自主完成，无需人工干预。