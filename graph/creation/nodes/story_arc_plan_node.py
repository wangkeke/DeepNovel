"""
story_arc_plan_node：全书分卷规划

普通创作：按卷 **逐次** 调用 LLM 生成（每卷一个 JSON 对象），避免一次输出五卷导致截断。
框架导入：对已有 volumes **逐卷** 补全约束字段。
"""
from __future__ import annotations
import copy
import json
import logging
import re
from langgraph.types import Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from memory.db import get_volumes
from utils.genre_lexicon import genre_lexicon_banner
from prompts.common.high_tier_dynamic import FULL_OPPONENT_DOCTRINE
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from prompts.creation.platform_styles import ANTI_CLICHE_AND_TEXTURE_RULES, platform_planning_bundle
from utils.book_opposition_anchor import book_opposition_prompt_block
from utils.volume_fields import normalize_dynamic_gray_factions
from utils.v42_flow import protagonist_archive_prompt_block

logger = logging.getLogger("deepnovel.story_arc_plan")

# 全书分卷数量（与设计文档一致）
NUM_PLAN_VOLUMES = 5

# 各卷默认章节数、冲突烈度阶梯（可被模型在本卷对象内覆盖）
DEFAULT_ESTIMATED_CHAPTERS = [50, 60, 80, 100, 60]
DEFAULT_CONFLICT_INTENSITY = ["low", "low_medium", "medium", "high", "high"]

_ESTIMATED_CHAPTERS_SYSTEM_RULE = """
【动态篇幅与长篇节奏铁律（长线大作标准！）】
必须根据本卷的【剧情密度与世界观宏大程度】动态决定 `estimated_chapters`（合理区间：50～150章）。⚠️【绝对禁止任何一卷少于 50 章】！
1. 常规发展/过渡卷（如：解决开篇危机后，适应新环境、初步建立势力）：建议 50～90 章。必须用多段波折填满容量，绝不注水！
2. 宏大副本/核心冲突卷（如：大型秘境试炼、两军对垒、夺嫡宫变、朝堂大清洗）：出场人物多、战线极长，建议 80～150 章，写透权谋与细节！
绝对禁止所有卷都是一成不变的数字，在 50～150 的区间内按需分配！
"""

# 全书五卷阶段标签（与逐卷索引对齐；非 5 卷时用比例映射）
_PACING_PHASE_LABELS = [
    "起始（奠基立境）",
    "发展（矛盾延展）",
    "升级（压力加剧）",
    "高潮前奏（决战前夕）",
    "收尾（终局与余韵）",
]


def _pacing_phase_index(volume_index: int, total_volumes: int) -> int:
    """0..4，对应 _PACING_PHASE_LABELS。total=5 时与卷号一一对应。"""
    total = max(int(total_volumes), 1)
    i = max(0, min(int(volume_index), total - 1))
    if total == 1:
        return 4
    if total == 5:
        return min(i, 4)
    return min(4, int(round(i * 4 / max(total - 1, 1))))


def _global_pacing_anchor(volume_index: int, total_volumes: int) -> str:
    """
    防串行生成时的「进度失控 / Pacing Drift」：禁止在第 2～3 卷就把 synopsis 最高冲突写完。
    total_volumes：全书总卷数；volume_index：当前卷 0-based。
    """
    total = max(int(total_volumes), 1)
    i = max(0, min(int(volume_index), total - 1))
    phase = _PACING_PHASE_LABELS[_pacing_phase_index(i, total)]
    pct_even = min(100, round(100 * (i + 1) / total))
    remaining = total - 1 - i
    # 五卷制时与用户文档一致的「20% 阶梯」显性锚点（与 pct_even 在 total=5 时同为 20/40/…）
    pct_twenty_rule: str | None = None
    if total == 5:
        pct_twenty_rule = str(min(100, 20 * (i + 1)))

    if i < total - 1:
        block = [
            "## 进度铁律（极度重要 · 防局部短视 / Pacing Drift）\n",
            f"当前正在规划全书的 **第 {i + 1} 卷**（共 **{total}** 卷）。\n",
            f"本卷处于全书 **【{phase}】** 阶段。\n",
        ]
        if pct_twenty_rule is not None:
            block.append(
                f"**全书进度定位锚（五卷制）**：至本卷末，主线与核心矛盾的「显性推进度」"
                f"只允许走到约 **{pct_twenty_rule}%** 的总体进度（可略低、**不可**远超；"
                "禁止因急着兑现 `synopsis.direction` 里**最高层**目标而**提前终局**）。\n"
            )
        else:
            block.append(
                f"至本卷末，显性推进度建议约 **{pct_even}%**（分母为总卷数均摊；"
                "不得因急于呼应走向而一笔写穿终局）。\n"
            )
        block.extend(
            (
                "\n**严禁**在本卷：发动**最终决战**、**彻底消灭/扳倒最终宿敌**、"
                "**一次性完全瓦解** synopsis 中的**核心终极矛盾**；"
                "勿揭穿**全部**终局级悬念、勿把全书大结局写在本卷。\n\n"
                f"必须为后续 **{remaining}** 卷保留：上升空间、更强层级、未解之谜与情绪蓄力；"
                "本卷 `volume_direction` **只写本阶段可落地的一档目标**，不要写成全书尾声。\n"
            )
        )
        return "".join(block)

    final_pct = pct_twenty_rule if pct_twenty_rule is not None else str(pct_even)
    return (
        "## 进度铁律（终卷）\n\n"
        f"当前为 **第 {total} 卷（终卷）**，阶段 **【{phase}】**；"
        f"全书显性推进可收束至约 **{final_pct}%**。\n"
        "本卷**允许**终局对决与核心矛盾收束，但须承接前序伏笔，避免机械降神、"
        "禁止用无关大反转推翻前序已定事实。\n"
    )


# dynamic_gray_factions：灰度利益实体（非「禁同框名单」），须写清资源垄断与对局态度，随卷递进；与 path_gen / event_chain 共用。
_VOLUME_JSON_SPEC = """
只输出 **一个** JSON 对象（不要数组、不要 markdown 代码围栏），字段如下：
{
  "volume_index": <整数，本卷索引>,
  "volume_name": "卷名（4-8字）",
  "volume_direction": "本卷核心目标（一句话）。⚠️【开篇破局铁律（需判断体量）】：1. 若开篇为微型危机（日常栽赃/失物/口角），必须在卷首的 1~3 章极速解决，绝不水文！随后立刻引出全新连锁反应；2. 若开篇本身即为宏大副本（如无限流副本/大型秘境/悬疑大案），则不适用极速破冰，应按波段切分贯穿本卷，但首个事件必须建立明确的生存规则认知。",
  "estimated_chapters": {
    "target_range": "50-80（参考区间，如需加减可标注理由）",
    "derivation_note": "实际章节数由 event_chain 两阶段混合推导自然决定，此处仅作战略参考"
  },
  "location_scope": "本卷主要活动地点范围。⚠️【空间闭环铁律】：对于宫斗/都市/修仙等具备社会生态的题材，绝不可将一整卷剧情完全锁死在单一荒郊野外，必须包含对应的【回城结算/社交区域】以供人际拉扯；但【无限流/密室推理/深渊探险】等以封闭空间为叙事核心的题材，享受此铁律豁免，可整卷处于封闭高压环境中。",
  "max_opponent_level": "本卷最高对手级别",
  "conflict_intensity": "low | low_medium | medium | high",
  "volume_villain": { "name": "...", "motivation": "..." },
  "volume_ally": { "name": "...", "role": "..." },
  "dynamic_gray_factions": [
    {
      "name": "势力或人物名",
      "resource_monopoly": "其掌握或争夺的核心稀缺资源（兵权/情报/灵脉/名分等）",
      "current_stance": "对当前局面的真实态度：观望/推波助澜/相互钳制/漠视余波等",
      "is_ultimate_boss": false
    }
  ],
  "ebd_targets": [
    { "char": "角色名", "ebd_bond_kind": "friendship/romance/rivalry等", "ebd_end": "+35~+45", "curve_logic": "情感演变逻辑（⚠️防无脑漂移铁律：绝对禁止没有剧情支撑的数值忽高忽低！如果本卷数值相比上卷【稳步上升】，必须说明经历了什么共患难；如果数值出现【停滞或剧烈回撤/下降】（如从+40掉到+5，或转为负数），必须明确指出是因为本卷发生了什么【利益冲突、理念分歧、阵营背叛或致命误会】导致的裂隙！用具体的事件来解释数值的波动！）"  "note": "本卷末对其情感坐标/关系目标（相对主角，EBD −100~+100）" }
  ],
  "protagonist_starting_position": {
    "tier": "本卷开始时主角所在圈层",
    "resources": "掌握的资源（情报/人脉/金钱/权柄等）",
    "maturity_score": "当前成熟度档位（如：保留幻想·内耗期 / 减少内耗·开始算计）",
    "emotional_capacity": "精神阈值剩余估算（百分比或描述）"
  },
  "protagonist_ending_position": {
    "tier": "本卷结束后主角跃迁到的圈层",
    "maturity_change": "成熟度变化描述（打破了哪种幻想，成长了哪个维度）",
    "key_illusion_shattered": "本卷终结的最核心幻想或认知错误"
  },
  "arc_anchors": [
    {
      "anchor_id": 1,
      "position": "early（约前 1-3 个事件）",
      "milestone_type": "开篇碰撞",
      "arrival_condition": "主角已被卷入冲突；触发条件与 opening_collision 一致",
      "content_source": "直接继承自 iceberg_deduction.opening_collision，不由 event_chain 重新推导",
      "completion_signal": "描述可客观判断此锚点已完成的标志（如：某人物死亡、某资源易手、某关系确立、某秘密揭露）"
    },
    {
      "anchor_id": 2,
      "position": "mid-early（约第 N 个事件，给出大致区间）",
      "milestone_type": "规则反转 | 暗流浮现 | 伏笔引爆（从枚举中选一）",
      "arrival_condition": "到达此锚点时，世界状态必须满足的条件（如某资源已消耗、某势力 current_status 已变化、某 karmic 伏笔已埋）",
      "content_constraint": "只约束里程碑类型，具体内容由 event_chain Phase 2 循环推导生成",
      "completion_signal": "描述可客观判断此锚点已完成的标志（如：某势力倒台、某伏笔被引爆、某角色立场发生转变）"
    },
    {
      "anchor_id": 99,
      "position": "late（约最后 2-3 个事件）",
      "milestone_type": "圈层跃迁",
      "arrival_condition": "主角已完成本卷核心目标，protagonist_ending_position 所描述的状态变化已基本发生",
      "content_constraint": "跃迁具体方式由循环推导生成，须对应 background_context.maturity_events 中的某触发事件",
      "completion_signal": "描述主角完成本卷圈层跃迁的客观标志（如：主角获得某一身份/权柄/能力、核心幻想被打破）"
    }
  ],
  "background_context": {
    "main_antagonist": "本卷核心对手及其资源诉求（来自 world_archive）",
    "new_factions_entering": ["新介入的势力（faction_id 或名称）"],
    "undercurrents_scheduled": ["本卷计划浮出水面的暗流（来自 iceberg_undercurrents）"],
    "foreshadows_to_plant": ["本卷须埋下的新伏笔方向"],
    "foreshadows_to_harvest": ["本卷计划引爆的前卷伏笔（来自 karmic_ledger）"],
    "maturity_events": ["主角/核心角色的成熟度跃迁触发事件"]
  },
  "plot_nodes": [],
  "has_detailed_plot": false,
  "arc_track": "字符串：仅 volume_index=3（第4卷）必填「路线A（灵魂黑夜）」或「路线B（极道横推，可含阳谋平推/降维打击）」；路线B下禁止为硬造曲折而强行吃瘪/降智/没收金手指，并须在 volume_direction 或本字段后用括号一句说明与 story_mode 等何以自洽；其余卷统一「不适用」。"
}

**arc_anchors 设计规则（核心）**：
- 锚点1 永远是开篇碰撞（第1卷直接继承 iceberg_deduction.opening_collision；后续卷由上卷末尾状态自然衔接）
- 锚点N 永远是圈层跃迁（对应 protagonist_ending_position）
- 中间锚点 2-3 个，对应本卷必然发生的关键转折
- **总数控制在 3-5 个**：超过 5 个即变成微观管控，压制循环推导的有机生长空间
- 锚点只定义**里程碑类型**和 **arrival_condition**，不定义具体内容

里程碑类型枚举：开篇碰撞 | 规则反转 | 结盟 | 破局 | 圈层跃迁 | 伏笔引爆 | 暗流浮现

⚠️ arc_anchors 是机器可读的执行契约，event_chain_gen 直接读取。
⚠️ background_context 是人类可读背景，供人工审核参考，不作为 event_chain_gen 直接输入。
⚠️ estimated_chapters.target_range 是参考区间，实际章节数由两阶段推导自然决定。

`ebd_targets`：本卷须有明显情感弧的 1～3 人即可，无则 `[]`；**优先呼应** synopsis 的 `family_emotion_line` / `romance_emotion_line`（及 core_cast 中 family/romance 角色），爱情线可多人分段上升。`ebd_bond_kind`：friendship | romance | family | …；`ebd_end` 可用区间如「+30~+50」。
**dynamic_gray_factions（白皮书·动力层）**：至少 3～5 条为宜（可随格局增多）；写**高于本卷主线叙事靶子的利益实体**，须遵守**非对称冲突法则**与价码⇄刻意针对度：可作降维波及、漠视、余波、结构性挤压，**禁止**无代价升格为「本卷主线私人追害主反派」除非价码已到位；**拒绝强行升塔**——名单随主角上桌逐卷收束复杂度，但最高掌权者若非私人终局宿敌，卷末仍可保持背景/裁判位。**禁止**把说明文字整句当 name 填入。
"""

_WEBNOVEL_STANCE_GATING = """
# 高位博弈与非对称擦伤：统一见 prompts.common.high_tier_dynamic.FULL_OPPONENT_DOCTRINE

# 社会学/群像质感：从具体题材升维为全类型可用的架构常识（禁止写死宫廷等设定词为唯一合法场景）
【世界观与真实质感约束（所有题材通用）】
1. **空间壁垒与代理人原则**：主角当前层级对应**物理、制度或权限上的隔离区**（权力中枢、军事禁区、企业核心层、上巢核心区、宗门内门禁地等——随世界观具体化）。
   **未获得足够权限或渠道前**，禁止「凭主角自由逛街就进入高层禁区并获知核心机密」式写法。
   跨层级、跨隔离区的信息获取须依赖**合理的中介或渗透渠道**：如后勤、采买、医务、物流与废料链、边缘勤务、仆役或外包运维、灰市打听等「代理人式」路径，而非全图乱跑撞剧情。

2. **反派生态化（派系与依附原则）**：每卷 `volume_villain` 不宜写成**孤岛式单人怪**；中低位对立面通常应体现为**上方结构之边缘触角**或**趋炎附势的利益链一环**。
   宜具备跟班、白手套、庇护关系或小型利益共同体，使冲突呈现**群体/派系碰撞**，避免单机 RPG 式「打一个换一个」且无社会厚度。

3. **硬资本积累原则**：主角从「棋子」迈向「棋手」**不能**仅靠一两次机智表演就自动升格；须在大纲中可见**艰难收编**的真实资本（可分卷递进，但不得无本升阶），至少在意图上体现三类硬通货：
   **死忠心腹**、**稳定情报源或信息网**、**与自身互补的弱势盟友**。

4. **主线前置（草蛇灰线原则）**：全书核心悬念或与**最终宿敌/终极矛盾**相关的线索，须在**第 1 卷**以**极度隐晦**的方式留下毛边（旧物、不相干闲聊中的一句、废弃记录、传言碎片等）；
   **严禁**书中期才**空降**全书主轴或终局级谜底，除非显式承接第 1 卷已埋下的同一缕线头。
"""

_WORLD_REALISM_CONSTRAINTS = _WEBNOVEL_STANCE_GATING

# 顶格存在「存在感 / Screen Time Pacing」：避免慢热与生硬空降（宫斗皇帝、修仙掌门、赛博巨头等具象由世界观落地）
def _is_nonempty(val) -> bool:
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, dict):
        return any(_is_nonempty(x) for x in val.values())
    return True


def _three_act_five_volume_block(volume_index: int, total_volumes: int) -> str:
    """
    全书宏观三幕进度：与五卷规划一体；非五卷时压缩为按比例映射，避免框架导入卷数不一致时失联。
    volume_index：0-based；total_volumes：全书总卷数。
    """
    total = max(int(total_volumes), 1)
    vol_num = max(1, min(int(volume_index) + 1, total))

    if total != NUM_PLAN_VOLUMES:
        return (
            "## 【全书宏观进度控制】（非标准五卷 · 仍须兼容双轨精神）\n\n"
            "将全书按 **三幕** 理解：**破冰极渊求生 → 棋面破壳与代理人对抗 → "
            "核心转折（正剧倾向灵魂黑夜极限反转 / 爽文倾向极道横推层层打穿）→ 终局清算**。\n"
            f"当前共 **{total}** 卷：不得在前约 **30%** 卷进度内就把**私人终极宿敌**打成**终局收束型决战**或写穿 synopsis 核心矛盾；"
            "与 synopsis **私人恩怨轴**的终局收束应落在**末段卷**；**不强制**最高掌权者本人与主角拼命对砍。\n\n"
            f"**硬性指令：** 补全/校验 **第 {vol_num}/{total}** 卷时，须自检对手层级、`max_opponent_level`、`volume_villain` 是否**越级**；"
            "禁止把应留在终幕的清算提前消费。\n"
        )

    return f"""
## 【三幕五卷双轨结构】（`DeepNovel_开篇种子系统_v2`）

规划各卷时须遵守下文，并与 system 中的**价码 ⇄ 刻意针对度**、**猫鼠倒挂**一致：五卷内须**大起大落、非单调爬阶**（威胁度可暴跌再暴涨 **或** 爽文向持续高压飙升——见卷 4 **路线 B**）。须与 **synopsis**、`opening_seed_text`（若有）及 **创世变量配方**（`story_mode` / `human_logic` / `targeting_degree` 等）自洽。

**【第一幕 · 卷 1：破冰与极渊求生期】**  
开局四种模式（择一，与开篇自洽）：  
- **A. 极寒底层**：身份极其卑微（如罪奴、杂役、流民），面临物理生存极限，在最严酷的规则夹缝中求生。  
- **B. 新手入阵（常态中低位）**：拥有合法且相对体面的基础身份（如选秀入宫的低阶妃嫔、刚入门的外门弟子、职场新人）。压力不来自物理饥寒，而是错综复杂的派系倾轧、潜规则绞杀或沦为炮灰。  
- **C. 高位压力**：怀璧其罪或身份敏感，一入局就遭遇降维打击。  
- **D. 高位跌落**：起点高位，遭构陷后坠入极渊重建。  

无论哪种，本卷主角须**持续处于结构性高压**。若为模式 B，请着重描写“规矩杀”和“借刀杀人”，禁止强行让有体面身份的主角去干粗活苦役！
【⚠️ 黄金开局与篇幅保底铁律】：因为本卷【绝对禁止少于50章】，主角在解决开篇的初始危机后，中后期主体剧情必须是：利用破局带来的微小资源或新身份，去应对由此引发的【更大连锁反应、新势力介入或新环境博弈】（如进入新部门遭遇贪腐案、被卷入更高级别的派系斗争），并建立初步的生存基本盘。严禁把开局的一件微小琐事硬拖一整卷！

**【第二幕 · 卷 2～3：棋面破壳与代理人战争】**  
主角建立基本盘，拔除高位者的核心羽翼；引起高位者实质重视，进入**系统性代理人对抗**。  
卷 2～3 **严禁**与全书终极宿敌完成**终局收束型、王对王拼命式**对决。  
卷 3 结尾须是明确的**阶段性高点**（为卷 4 提供落差 **或** 为横推路线提供「大胜后撞更硬壁垒」的势能）。

**【第三幕 · 卷 4：核心转折节点（双轨 · 必须择一）】**  

★ **路线 A：灵魂黑夜与极限反转**（偏虐主/正剧/悬疑/重压逆袭）  
前期过猛终触核心命脉，可惨烈滑铁卢（底牌曝光、羽翼剪除、死牢/废功/流放等，随题材落地）。反派可重入**傲慢猫鼠**心态（叙事上针对度可**阶段性回落**）；主角利用**傲慢盲区**完成最关键质变与翻盘伏笔。  

★ **路线 B：极道横推与降维打击**（偏无敌流/系统爽文/极速大男主大女主）  
【**叙事核心：拒绝强行吃瘪**】不只是无脑武力爽：当主角在卷 3 已积累**难以撼动**的综合优势（武力、资本、情报网、民意或规则内筹码）后，可用**阳谋**或**降维打击**碾平反派最后防线，不必为「制造挫折」而让人设崩盘。  
【**严禁剧毒**】禁止为硬造曲折而让主角**降智**、**无理由没收金手指/核心资源**、或**莫名其妙被打落谷底**（网文高爽向的大忌）。  
【**张力来源**】本卷压力**不来自主角变弱收束**，而来自：反派绝境下的**疯狂反扑**（玉石俱焚）、更大尺度/更严规则的**外部高压**、或能力/系统触及**更恐怖的上限**所需代价。主角**不低头、不明显减速**，以摧枯拉朽之势推进至决战层，越战越承压越要赢。针对度可升至 **80～90**（敌方倾剿），须有**高强度对抗**，不是「无事可做」。  

两条路线均须承接卷 3 高点，产生清晰**拐点感**（A：**落差**；B：**升维/打穿或阳谋平推**）；**禁止平淡过桥**。规划 **第 4 卷（volume_index=3）** 时须在 JSON 的 `arc_track` 标明 **路线A（灵魂黑夜）** 或 **路线B（极道横推）**（路线 B 可括注阳谋/降维），并用一句说明其与开篇变量配方（尤其 `story_mode`）如何匹配（可写在该字段括号内）。

**【第四幕 · 卷 5：王车易位与终局清算】**  
全盘解禁；承接卷 4 拐点后的新格局，与【终极宿敌】在同一棋局上进行生杀兑子。  
⚠️【私欲结算与可选被动升华】：本卷必须优先且彻底地收束围绕主角【私心、爱恨与核心利益】的矛盾（如手刃仇人、大权在握）。【绝对不强制】主角升华为拯救苍生的圣人！如果（且仅如果）前面的剧情中主角被整个大局的谎言欺骗或被逼到死角，才【允许】出现为了自保/护短而被迫颠覆大局的「被动大义」。否则，请安安分分地完成一场极致的、自私的私人恩怨清算！

**【硬性指令 · 当前正规划第 {vol_num} 卷】**  
- 禁止单调「每卷稳升一级」流水账。  
- 禁止在第 2～3 卷提前消费终局对决。  
- `story_mode` 偏 **极道横推** 时**优先倾向路线 B**；偏 **极渊坠落/暗流涌动** 等正剧基调时**优先倾向路线 A**——**不强制**，但总转折须与全书调性一致。  
- 与 **猫鼠倒挂**、**高位动态法则** 自检一致。
""".strip()


def _arc_anchors_default(index: int) -> list:
    """当 LLM 未输出 arc_anchors 时，生成最小占位锚点列表。"""
    return [
        {
            "anchor_id": 1,
            "position": "early（约前 1-3 个事件）",
            "milestone_type": "开篇碰撞",
            "arrival_condition": "主角已被卷入本卷核心冲突",
            "content_source": "继承自 iceberg_deduction.opening_collision（第1卷）或上卷末尾状态",
            "completion_signal": "主角与本卷核心对手或冲突核心完成首次正面碰撞",
        },
        {
            "anchor_id": 2,
            "position": "mid（约中间事件区）",
            "milestone_type": "规则反转",
            "arrival_condition": "主角发现表面规则之下的真实博弈逻辑",
            "content_constraint": "具体内容由 event_chain Phase 2 循环推导生成",
            "completion_signal": "某关键信息被揭露或某势力关系发生实质性转变",
        },
        {
            "anchor_id": 3,
            "position": "late（约最后 2-3 个事件）",
            "milestone_type": "圈层跃迁",
            "arrival_condition": "主角完成本卷核心目标，进入更高圈层，旧麻烦解决，新维度麻烦开始",
            "content_constraint": "跃迁方式由循环推导生成",
            "completion_signal": "主角完成圈层跃迁，获得新身份/资源/权柄或打破核心幻想",
        },
    ]


def _norm_estimated_chapters(raw, index: int) -> int:
    """兼容新（对象）与旧（整数）格式，返回整数供下游使用。"""
    default = DEFAULT_ESTIMATED_CHAPTERS[min(index, len(DEFAULT_ESTIMATED_CHAPTERS) - 1)]
    if isinstance(raw, int):
        return max(50, raw)
    if isinstance(raw, float):
        return max(50, int(raw))
    if isinstance(raw, dict):
        tr = raw.get("target_range", "")
        if isinstance(tr, str):
            import re
            nums = re.findall(r"\d+", tr)
            if nums:
                return max(50, int(nums[0]))
        return default
    if isinstance(raw, str):
        import re
        nums = re.findall(r"\d+", raw)
        if nums:
            return max(50, int(nums[0]))
    return default


def _norm_one_volume(data: dict, index: int) -> dict:
    """保证单卷 dict 结构完整，并强制 volume_index。"""
    base = {
        "volume_index": index,
        "volume_name": "",
        "volume_direction": "",
        "estimated_chapters": DEFAULT_ESTIMATED_CHAPTERS[
            min(index, len(DEFAULT_ESTIMATED_CHAPTERS) - 1)
        ],
        "location_scope": "",
        "max_opponent_level": "",
        "conflict_intensity": DEFAULT_CONFLICT_INTENSITY[
            min(index, len(DEFAULT_CONFLICT_INTENSITY) - 1)
        ],
        "volume_villain": {"name": "", "motivation": ""},
        "volume_ally": {"name": "", "role": ""},
        "dynamic_gray_factions": [],
        "plot_nodes": [],
        "ebd_targets": [],
        "has_detailed_plot": False,
        "arc_track": "",
        "arc_anchors": [],
        "protagonist_starting_position": {},
        "protagonist_ending_position": {},
        "background_context": {},
    }
    if not isinstance(data, dict):
        return base
    out = {**base, **{k: v for k, v in data.items() if v is not None}}
    out["volume_index"] = index
    if not isinstance(out.get("volume_villain"), dict):
        out["volume_villain"] = base["volume_villain"]
    if not isinstance(out.get("volume_ally"), dict):
        out["volume_ally"] = base["volume_ally"]
    out["dynamic_gray_factions"] = normalize_dynamic_gray_factions(
        out.get("dynamic_gray_factions")
    )
    out.pop("untouchable_characters", None)
    if not isinstance(out.get("plot_nodes"), list):
        out["plot_nodes"] = []
    if not isinstance(out.get("ebd_targets"), list):
        out["ebd_targets"] = []
    # estimated_chapters：兼容新（对象）与旧（整数）格式
    raw_ec = out.get("estimated_chapters")
    out["estimated_chapters"] = _norm_estimated_chapters(raw_ec, index)
    out["has_detailed_plot"] = bool(out.get("has_detailed_plot"))
    at_raw = out.get("arc_track")
    at = at_raw.strip() if isinstance(at_raw, str) else ""
    if index != 3:
        out["arc_track"] = at if at else "不适用"
    else:
        out["arc_track"] = at
    # arc_anchors：LLM 未输出时生成默认锚点列表
    raw_aa = out.get("arc_anchors")
    if not isinstance(raw_aa, list) or not raw_aa:
        out["arc_anchors"] = _arc_anchors_default(index)
    else:
        # 确保 anchor_id 存在且递增，completion_signal 有占位值
        for idx_a, a in enumerate(raw_aa):
            if not isinstance(a, dict):
                raw_aa[idx_a] = {}
            if not raw_aa[idx_a].get("anchor_id"):
                raw_aa[idx_a]["anchor_id"] = idx_a + 1
            if not raw_aa[idx_a].get("completion_signal"):
                raw_aa[idx_a]["completion_signal"] = "（待补充：此锚点完成的客观可观测标志）"
        out["arc_anchors"] = raw_aa
    if not isinstance(out.get("protagonist_starting_position"), dict):
        out["protagonist_starting_position"] = {}
    if not isinstance(out.get("protagonist_ending_position"), dict):
        out["protagonist_ending_position"] = {}
    if not isinstance(out.get("background_context"), dict):
        out["background_context"] = {}
    return out


def _genesis_arc_user_block(state: dict) -> str:
    """v2：分卷 user prompt 注入开篇种子与变量配方。"""
    synopsis = state.get("synopsis") or {}
    gv = state.get("genesis_variables") or {}
    opening = (synopsis.get("opening_seed_text") or "").strip()
    if not opening and not gv:
        return ""
    lines = [
        "## 开篇种子与创世变量（逻辑起点；分卷须与之自洽，见 system 三幕五卷双轨）",
    ]
    if opening:
        cap = 1200
        lines.append(
            "### 开篇种子正文（摘录）\n"
            + (opening[:cap] + ("…" if len(opening) > cap else ""))
        )
    if gv:
        lines.append(
            "### 变量配方\n"
            f"- 故事模式：{gv.get('story_mode', '')}\n"
            f"- 人性逻辑：{gv.get('human_logic', '')}\n"
            f"- 针对度：{gv.get('targeting_degree', '')}\n"
            f"- 情感度：{gv.get('emotional_degree', '')}\n"
            f"- 金手指/虚构钩子：{gv.get('fictional_hook', '')}\n"
        )
    lines.append(
        "### 战略字段（synopsis）\n"
        f"- 核心冲突：{synopsis.get('core_conflict', '')}\n"
        f"- 格局放大路径：{synopsis.get('escalation_path', '')}\n"
        f"- 第一卷目标：{synopsis.get('volume_1_goal', '')}\n"
        f"- 终极目标：{synopsis.get('ultimate_goal', '')}\n"
    )
    return "\n".join(lines)


def _fill_missing_from_llm(original: dict, from_llm: dict) -> dict:
    """补全：original 中已有实质内容的字段优先保留；否则用 from_llm。"""
    if not isinstance(from_llm, dict):
        return copy.deepcopy(original)
    out = copy.deepcopy(original)
    for k, v in from_llm.items():
        if k == "volume_villain" and isinstance(v, dict):
            cur = out.get("volume_villain") or {}
            if not isinstance(cur, dict):
                cur = {}
            merged = dict(cur)
            for sk, sv in v.items():
                if not _is_nonempty(cur.get(sk)):
                    merged[sk] = sv
            out["volume_villain"] = merged
            continue
        if k == "volume_ally" and isinstance(v, dict):
            cur = out.get("volume_ally") or {}
            if not isinstance(cur, dict):
                cur = {}
            merged = dict(cur)
            for sk, sv in v.items():
                if not _is_nonempty(cur.get(sk)):
                    merged[sk] = sv
            out["volume_ally"] = merged
            continue
        cur = out.get(k)
        if not _is_nonempty(cur):
            out[k] = v
    out["volume_index"] = original.get("volume_index", out.get("volume_index", 0))
    return out


def _volume_snapshot_for_chain(v: dict) -> dict:
    """下一卷 planning 用的紧凑快照（控制动机/列表长度）。"""
    vv = v.get("volume_villain") if isinstance(v.get("volume_villain"), dict) else {}
    va = v.get("volume_ally") if isinstance(v.get("volume_ally"), dict) else {}
    dgf = normalize_dynamic_gray_factions(v.get("dynamic_gray_factions"))
    if len(dgf) > 10:
        dgf = dgf[:10] + [{"name": "…（余略）", "resource_monopoly": "", "current_stance": "", "is_ultimate_boss": False}]
    mot = (vv.get("motivation") or "") if vv else ""
    if len(mot) > 200:
        mot = mot[:200] + "…"
    role = (va.get("role") or "") if va else ""
    if len(role) > 200:
        role = role[:200] + "…"
    return {
        "volume_index": v.get("volume_index", 0),
        "volume_name": v.get("volume_name", ""),
        "volume_direction": v.get("volume_direction") or "",
        "location_scope": v.get("location_scope") or "",
        "max_opponent_level": v.get("max_opponent_level") or "",
        "conflict_intensity": v.get("conflict_intensity") or "",
        "volume_villain": {
            "name": (vv or {}).get("name", ""),
            "motivation": mot,
        },
        "volume_ally": {
            "name": (va or {}).get("name", ""),
            "role": role,
        },
        "dynamic_gray_factions": dgf,
        "ebd_targets": v.get("ebd_targets") if isinstance(v.get("ebd_targets"), list) else [],
        "arc_track": (v.get("arc_track") or "") if isinstance(v.get("arc_track"), str) else "",
    }




def _previous_volumes_rich_context(accumulated: list[dict]) -> str:
    """
    前序卷完整衔接上下文（逐卷 JSON），避免只给一行摘要导致后卷与前卷脱节。
    """
    if not accumulated:
        return (
            "（尚无。本卷为第 1 卷：须严格对应宏观构思中的主角起点、最低冲突烈度与底层对手，"
            "勿提前抬到终局层级。）"
        )
    blocks = []
    for v in accumulated:
        if not isinstance(v, dict):
            continue
        snap = _volume_snapshot_for_chain(v)
        blocks.append(json.dumps(snap, ensure_ascii=False, indent=2))
    return (
        "下列为**已生成的全部前序卷**（结构化快照）。\n"
        "你必须在本卷中形成**自然递进**：主角处境/活动范围/对手上限/冲突烈度应随卷推进；\n"
        "地点与人物层级的变化要有因果，不得与前几卷的 villain、ally、**dynamic_gray_factions（灰度利益实体）** 递进语义矛盾；\n"
        "不得与前序卷在**高位博弈价码与非对称冲突**上的约定矛盾；\n"
        "前序卷快照：\n"
        + "\n---\n".join(blocks)
    )


async def story_arc_plan_node(state: CreationState) -> Command:
    synopsis = state.get("synopsis", {}) or {}
    core_cast = state.get("core_cast") or {}
    project_id = state.get("project_id", "")

    existing_volumes = list(state.get("volumes") or [])
    if not existing_volumes and project_id:
        existing_volumes = await get_volumes(project_id)
    has_existing = bool(existing_volumes)

    pending = list(state.get("story_arc_volumes_draft") or [])
    if pending:
        return Command(goto="human_review_story_arc")

    node_step("生成分卷规划" if not has_existing else "补全分卷约束字段")
    genre_lex = genre_lexicon_banner(synopsis, state.get("matched_genres") or [])
    if has_existing:
        volumes = await _enrich_existing_volumes(
            existing_volumes,
            synopsis,
            core_cast,
            genre_lex,
            regen_feedback=(state.get("story_arc_regen_feedback") or "").strip(),
            state=state,
        )
    else:
        volumes = await _generate_volumes(state, synopsis, core_cast, genre_lex)
    if not volumes:
        logger.warning("分卷规划为空，使用占位一卷")
        volumes = [_norm_one_volume({}, 0)]
        volumes[0]["volume_name"] = "开篇"
        volumes[0]["volume_direction"] = synopsis.get("direction", "推进主线") or "推进主线"
    node_done("分卷规划就绪")

    return Command(
        update={
            "story_arc_volumes_draft": volumes,
            "story_arc_regen_feedback": "",
        },
        goto="human_review_story_arc",
    )


async def _generate_volumes(
    state: CreationState,
    synopsis: dict,
    core_cast: dict,
    genre_lexicon: str = "",
) -> list:
    opposition_user = book_opposition_prompt_block(synopsis, core_cast)
    accumulated: list[dict] = []
    pc = state.get("protagonist_card") if isinstance(state.get("protagonist_card"), dict) else {}
    prot_archive_section = (
        "\n" + protagonist_archive_prompt_block(pc) + "\n"
    ) if pc else ""
    platform_section = "\n" + platform_planning_bundle(state) + "\n"
    genre_lexicon_block = (genre_lexicon + "\n") if (genre_lexicon or "").strip() else ""

    ua_arc = state.get("user_anchors") or {}
    pe_arc = ua_arc.get("plot_events") if isinstance(ua_arc, dict) else []
    if not isinstance(pe_arc, list):
        pe_arc = []
    plot_events_anchor = ""
    if pe_arc:
        plot_events_anchor = (
            "\n## 【用户指定的核心桥段（跨卷排布铁律）】\n"
            f"用户要求在全书中必须出现以下桥段：{json.dumps(pe_arc, ensure_ascii=False)}。\n"
            "请根据各卷进度，极其自然地将这些桥段分配到对应卷的 volume_direction 或本卷叙事目标中，确保伏笔不丢。\n"
        )

    fb_arc = (state.get("story_arc_regen_feedback") or "").strip()
    regen_block = ""
    if fb_arc:
        regen_block = (
            "\n## 【用户重新规划分卷的意见（须贯穿各卷、优先落实）】\n"
            f"{fb_arc}\n"
        )

    core_cast_lock = ""
    if isinstance(core_cast, dict) and core_cast:
        core_cast_lock = (
            "\n## 全书核心班底 JSON（专名锁定；各卷 dynamic_gray_factions / 地点叙事中的机构、衙门、势力名须与此逐字一致）\n"
            + json.dumps(core_cast, ensure_ascii=False, indent=2)
            + "\n"
        )

    for i in range(NUM_PLAN_VOLUMES):
        node_step(f"生成分卷规划 {i + 1}/{NUM_PLAN_VOLUMES}")
        default_ch = DEFAULT_ESTIMATED_CHAPTERS[min(i, len(DEFAULT_ESTIMATED_CHAPTERS) - 1)]
        default_ci = DEFAULT_CONFLICT_INTENSITY[min(i, len(DEFAULT_CONFLICT_INTENSITY) - 1)]
        prev_ci = (
            accumulated[-1].get("conflict_intensity", "low")
            if accumulated
            else "low"
        )

        arc_direction = (synopsis.get("direction") or "").strip()

        result = await call_llm_json(
            system=DEEPNOVEL_CONSTITUTION + "\n\n" + f"""
你是资深网文策划编辑。当前只规划全书 **第 {i + 1}/{NUM_PLAN_VOLUMES} 卷**（volume_index={i}）。
须遵守用户消息中的 **进度铁律**：非终卷不得透支终局、不得提前打完 synopsis 里最高层冲突。

**卷间衔接（硬性）**
{_three_act_five_volume_block(i, NUM_PLAN_VOLUMES)}

- 若存在前序卷：本卷的 volume_direction / location_scope / max_opponent_level / conflict_intensity
  必须能接在前序卷「收束后的局面」之后，呈阶梯上升，禁止平铺重复第一卷叙事。
- conflict_intensity 不得低于前一卷（第 1 卷例外）；第 1 卷主角须处全书阶梯「起点侧」，本卷 `volume_villain`
  不得越级为全书终局级/顶格主轴对立（须与本卷 `max_opponent_level` 及烈度匹配，禁止开局即终局 Boss）。
- **dynamic_gray_factions**：列出本卷须交手的**灰度利益网络**（≥3 条为宜）：各方垄断何种资源、当前站队与态度；**高于本卷主线叙事靶子**的实体须遵守**非对称冲突**与价码法则，可降维波及、漠视、余波，勿无因升格为主线私人追害。**【拒绝强行升塔】**随主角上桌逐卷收束复杂度；最高掌权者非私人终局宿敌时卷末仍可保持背景/裁判位。**禁止**为凑终局逼其本人当最终 Boss。已与主角**实质终局对弈**者勿再写成「只可被漠视的灰尘」。
- 最终宿敌与高位者 **可随时出场、同框、发生碰撞**；须符合 **价码 ⇄ 刻意针对度**（见下文）。非终卷**禁止**写成本卷已走完「押上核心资源、本人倾注智商」的**终局级对决收束**。
- **称谓一致性**：机构/势力/衙门等专名须与用户消息中的**全书核心班底、宏观构思**已出现的写法逐字一致，禁止同一实体在各卷换用易混别称（笔误级前后漂移）。

{FULL_OPPONENT_DOCTRINE}
{_WORLD_REALISM_CONSTRAINTS}
{genre_lexicon_block}
{_VOLUME_JSON_SPEC}
{_ESTIMATED_CHAPTERS_SYSTEM_RULE}
{ANTI_CLICHE_AND_TEXTURE_RULES}
数值参考（起评，须服从上文动态铁律）：estimated_chapters 可从 **{default_ch}** 章起评；conflict_intensity 建议 ≥「{prev_ci}」（本卷推荐「{default_ci}」）。
只返回一个 JSON 对象，不要 markdown 围栏，不要其它说明文字。
""",
            max_tokens=4096,
            user=f"""
## 小说设定（全文）
{json.dumps(synopsis, ensure_ascii=False)}

{platform_section}
{_genesis_arc_user_block(state)}
{prot_archive_section}
## 全书走向（规划各卷时不得偏离）
{arc_direction or "（见 synopsis.direction）"}
{plot_events_anchor}
{regen_block}
{_global_pacing_anchor(i, NUM_PLAN_VOLUMES)}
## 全书核心阻碍与压迫锚点（须与高位法则作用对象一致）
{opposition_user}
{core_cast_lock}
{_previous_volumes_rich_context(accumulated)}

## 任务
输出 **第 {i + 1} 卷** 的单一 JSON 对象；字段 volume_index 必须为整数 {i}。
""",
        )

        one = result if isinstance(result, dict) else {}
        if not one and isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
            one = result[0]
        vol = _norm_one_volume(one, i)
        accumulated.append(vol)
        # 勿用 INFO：node_step 使用 end=""，与 stderr 上的日志会挤在同一视觉行里
        logger.debug(
            "分卷 %s/%s 完成：%s",
            i + 1,
            NUM_PLAN_VOLUMES,
            vol.get("volume_name", ""),
        )

    return accumulated


async def _enrich_existing_volumes(
    volumes: list,
    synopsis: dict,
    core_cast: dict,
    genre_lexicon: str = "",
    regen_feedback: str = "",
    state: CreationState | None = None,
) -> list:
    out_list: list[dict] = []
    n = len(volumes)
    platform_section = (
        "\n" + platform_planning_bundle(state) + "\n"
        if state is not None
        else ""
    )
    genre_lexicon_block = (genre_lexicon + "\n") if (genre_lexicon or "").strip() else ""
    regen_block = ""
    if (regen_feedback or "").strip():
        regen_block = (
            "\n## 【用户重新规划分卷的意见（补全时须优先落实）】\n"
            f"{regen_feedback.strip()}\n"
        )

    for i, orig in enumerate(volumes):
        if not isinstance(orig, dict):
            continue
        idx = int(orig.get("volume_index", i))
        node_step(f"补全分卷约束 {i + 1}/{n}（卷索引 {idx}）")

        others_brief = [
            {
                "volume_index": v.get("volume_index", j),
                "volume_name": v.get("volume_name", ""),
            }
            for j, v in enumerate(volumes)
            if j != i and isinstance(v, dict)
        ]

        enriched_chain_ctx = (
            _previous_volumes_rich_context(out_list)
            if out_list
            else "（本卷之前尚无已补全输出，可只参考其它卷目录与 synopsis。）"
        )
        cast_tail = ""
        if core_cast:
            cast_tail = (
                "\n## 核心班底 JSON（补充参考）\n"
                + json.dumps(core_cast, ensure_ascii=False)
            )

        result = await call_llm_json(
            system=DEEPNOVEL_CONSTITUTION + "\n\n" + f"""
根据小说设定与核心班底，为 **单卷** 补全约束字段：volume_villain、volume_ally、
dynamic_gray_factions、location_scope、max_opponent_level、conflict_intensity。
已有非空字段必须保留，不要改用户已写好的卷名、volume_direction、plot_nodes、has_detailed_plot。
补全时须遵守用户消息中的 **进度铁律**：非终卷勿把补全写成终局收束；须与**已补全的前序卷**
在层级与 **dynamic_gray_factions（灰度利益实体）** 递进语义上衔接，勿与同书其它卷冲突。
随卷收束高位博弈复杂度；**不强制**终局卷清空灰度表——仅当某实体已与主角终局对弈时须调整其 stance；最高掌权者非私人宿敌时可保留为背景位，勿与同书其它卷矛盾。

{_three_act_five_volume_block(idx, n)}

{FULL_OPPONENT_DOCTRINE}
{_WORLD_REALISM_CONSTRAINTS}
输出 **一个** JSON 对象，volume_index={idx}。
{_VOLUME_JSON_SPEC}
{_ESTIMATED_CHAPTERS_SYSTEM_RULE}
{ANTI_CLICHE_AND_TEXTURE_RULES}
只返回 JSON 对象。
""",
            max_tokens=4096,
            user=f"""
{platform_section}
## 当前卷（完整原文，请在此基础上补全空字段）
{json.dumps(orig, ensure_ascii=False)}

## 其它卷（索引与卷名，防矛盾）
{json.dumps(others_brief, ensure_ascii=False)}

## 本批已补全的前序卷（衔接参考，勿破坏其已定层级）
{enriched_chain_ctx}

{_global_pacing_anchor(idx, n)}
{regen_block}
## 小说设定
{json.dumps(synopsis, ensure_ascii=False)}

## 全书走向
{(synopsis.get("direction") or "").strip() or "（见 synopsis）"}

## 全书核心阻碍与压迫锚点（须与高位法则作用对象一致）
{book_opposition_prompt_block(synopsis, core_cast)}{cast_tail}
"""
        )

        patch = result if isinstance(result, dict) else {}
        if not patch and isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
            patch = result[0]
        merged = _fill_missing_from_llm(orig, patch)
        out_list.append(_norm_one_volume(merged, idx))

    return out_list if out_list else copy.deepcopy(volumes)
