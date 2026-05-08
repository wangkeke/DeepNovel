"""
开篇种子：变量配方、题材宇宙（单字典整合金手指/变量约束/风味包）。
free-text genre_request → map_genre_bucket() → GENRE_CONSTRAINTS_AND_FLAVORS 的键。
与 knowledge/genre_dict.py 中题材名对齐；「家庭/婚礼/情侣日常」合并为「生活伦理」。
"""
from __future__ import annotations
import random
import re

# 外挂法则矩阵：每条为「独立金手指」canonical 名（display_name），六大类写在 gf_type；
# characteristic 为该金手指的「特点/爽法」，不是另一条金手指名称。
GOLDEN_FINGER_MATRIX: dict[str, dict] = {
    # ── 第一类：信息降维 ──
    "info_rebirth": {
        "display_name": "重生",
        "gf_type": "信息降维类",
        "characteristic": "先知先觉：凭前世亲历记忆预判死局与截胡机缘（记忆边界须自洽）。",
        "core_ability": "用「已发生过的未来」信息差改写当下决策。",
        "must_cost": "蝴蝶效应：大势被改则旧记忆失效；前世记忆必须截止死亡/昏迷前已知，禁止死后全知。",
        "forbidden_rules": ["不能死后补全信息", "不能无代价改命", "不能全知"],
        "aliases": ["重生", "前世记忆", "再来一世"],
    },
    "info_transmigration": {
        "display_name": "穿越",
        "gf_type": "信息降维类",
        "characteristic": "异界/异时空信息差：文化、规则、势力版图错位带来的认知红利。",
        "core_ability": "用现代或其他世界知识在新规则下卡位与套利。",
        "must_cost": "水土不服、规则惩罚、身份暴露与反噬；禁止开局全知本地隐秘。",
        "forbidden_rules": ["不能全图透视", "不能无学习成本碾压本土精英"],
        "aliases": ["穿越", "魂穿", "胎穿", "异世"],
    },
    "info_book_transmigration": {
        "display_name": "穿书",
        "gf_type": "信息降维类",
        "characteristic": "原著/剧本视角：熟知既定剧情与人物命运走向。",
        "core_ability": "用剧情锚点做局、截胡机缘、避开必死桥段。",
        "must_cost": "蝴蝶效应导致剧情失真；开篇禁止大段背诵全书，只许用眼前细节解谜。",
        "forbidden_rules": ["不能全书剧透式旁白", "不能无代价改剧情线"],
        "aliases": ["穿书", "炮灰逆袭", "剧本", "原著"],
    },
    "info_appraisal_tags": {
        "display_name": "万物隐藏词条",
        "gf_type": "信息降维类",
        "characteristic": "鉴定眼/提示框式隐藏信息条：只见线索，不直接给胜利。",
        "core_ability": "读取目标隐藏属性、弱点或机缘线索。",
        "must_cost": "只给信息不给战力；误判、解读成本与现场风险必须存在。",
        "forbidden_rules": ["不能变全图天眼", "不能直接给无条件必胜答案"],
        "aliases": ["万物隐藏词条", "鉴定眼", "提示框", "词条", "隐藏词条"],
    },
    "info_mind_read": {
        "display_name": "读心术",
        "gf_type": "信息降维类",
        "characteristic": "短时读取他者表层念头，制造信息差反制。",
        "core_ability": "获知对方当下真实意图片段以调整行动。",
        "must_cost": "次数/对象/场景受限；误读与精神污染风险。",
        "forbidden_rules": ["不能全场广播", "不能无次数上限", "不能无精神代价"],
        "aliases": ["读心术", "读心"],
    },
    "info_thought_wiretap": {
        "display_name": "窃听心声",
        "gf_type": "信息降维类",
        "characteristic": "持续或被动接收心声流，偏「听见」而非主动探查。",
        "core_ability": "在对话与伪装中捕捉隐秘动机。",
        "must_cost": "信息过载、精神污染、把噪音当真；需代价与误判。",
        "forbidden_rules": ["不能无差别监听众生", "不能无 San 值代价"],
        "aliases": ["窃听心声", "心声", "听见心声"],
    },
    "info_death_rollback": {
        "display_name": "死亡回档",
        "gf_type": "信息降维类",
        "characteristic": "时间循环式试错：失败回到锚点重来。",
        "core_ability": "用多轮死亡/失败拼凑唯一可行路线。",
        "must_cost": "每轮保留痛觉与创伤；不得回档后自带未经历线索全知。",
        "forbidden_rules": ["不能无代价无限回档", "不能零痛觉"],
        "aliases": ["死亡回档", "回档", "时间循环", "轮回试错"],
    },
    # ── 第二类：规则豁免 ──
    "rule_proficiency_panel": {
        "display_name": "熟练度面板",
        "gf_type": "规则豁免类",
        "characteristic": "天道酬勤：努力进度条可见，成长路径可预期。",
        "core_ability": "练习/修炼行为转化为稳定数值成长。",
        "must_cost": "时间与资源投入不可省略；瓶颈与失败仍会发生。",
        "forbidden_rules": ["不能睡一觉满级", "不能无投入成长"],
        "aliases": ["熟练度面板", "面板", "天道酬勤", "学霸面板系统"],
    },
    "rule_equivalent_exchange": {
        "display_name": "等价交换",
        "gf_type": "规则豁免类",
        "characteristic": "以明确代价换取力量或物品，契约感强。",
        "core_ability": "献祭寿元、情感、器官或他人筹码换取禁忌收益。",
        "must_cost": "代价必须真实扣减且可追溯；人性侵蚀与关系反噬。",
        "forbidden_rules": ["不能白嫖兑换", "不能代价不落地"],
        "aliases": ["等价交换", "献祭", "炼金式交换"],
    },
    "rule_sacrifice_system": {
        "display_name": "献祭系统",
        "gf_type": "规则豁免类",
        "characteristic": "系统化管理献祭与回报，偏任务/仪式驱动。",
        "core_ability": "完成献祭条件换取指定强化或道具。",
        "must_cost": "任务惩罚与冷却；献祭累积导致人格异化风险。",
        "forbidden_rules": ["不能无规则滥献祭", "不能零反噬"],
        "aliases": ["献祭系统"],
    },
    "rule_infinite_devour": {
        "display_name": "无限吞噬",
        "gf_type": "规则豁免类",
        "characteristic": "杀敌夺修为/血脉/天赋的掠夺式成长。",
        "core_ability": "吞噬目标力量快速增幅。",
        "must_cost": "驳杂反噬、怨念业力、追杀链升级。",
        "forbidden_rules": ["不能零副作用无限吞", "不能无上限叠加"],
        "aliases": ["无限吞噬", "吞噬"],
    },
    "rule_plunder": {
        "display_name": "掠夺",
        "gf_type": "规则豁免类",
        "characteristic": "偏「夺取」而非吞噬：机缘、气运、命格等可被掠走。",
        "core_ability": "从目标处夺取关键资源或命格碎片。",
        "must_cost": "因果反噬与被掠夺方的执念反弹。",
        "forbidden_rules": ["不能无反噬掠夺", "不能一次性榨干世界观"],
        "aliases": ["掠夺", "杀人放火受招安"],
    },
    # ── 第三类：绝对资源 ──
    "res_portable_space": {
        "display_name": "随身空间",
        "gf_type": "绝对资源类",
        "characteristic": "私人绝对域：囤货、隐蔽、紧急避险。",
        "core_ability": "独立储物或小世界后勤优势。",
        "must_cost": "怀璧其罪：暴露即追杀；转移与销赃需风险。",
        "forbidden_rules": ["不能公开无限取物无后果", "不能无风险暴露"],
        "aliases": ["随身空间", "无限物资空间", "储物空间"],
    },
    "res_spirit_field": {
        "display_name": "灵田",
        "gf_type": "绝对资源类",
        "characteristic": "时间流速/灵植培育：种田流核心资源引擎。",
        "core_ability": "培育高阶资源形成长期后勤壁垒。",
        "must_cost": "种子、灵肥、守护与暴露风险；收获周期与天灾。",
        "forbidden_rules": ["不能零成本一夜极品满仓库"],
        "aliases": ["灵田", "药田"],
    },
    "res_god_tycoon": {
        "display_name": "神豪提现",
        "gf_type": "绝对资源类",
        "characteristic": "现金流碾压：用财富改规则、买命、买舆论。",
        "core_ability": "任务或系统规则下获得可动用巨额资金。",
        "must_cost": "规则限制（只能花在别人/任务上）、税务与监管反噬。",
        "forbidden_rules": ["不能无监管常识", "不能无限印钞感"],
        "aliases": ["神豪提现", "神豪系统"],
    },
    "res_spendthrift_system": {
        "display_name": "败家系统",
        "gf_type": "绝对资源类",
        "characteristic": "花钱返利/花钱变强：资本行为即成长。",
        "core_ability": "通过挥霍或指定消费触发奖励。",
        "must_cost": "花钱条件苛刻；高调引绑架与黑吃黑。",
        "forbidden_rules": ["不能无规则挥霍必胜"],
        "aliases": ["败家系统"],
    },
    "res_check_in": {
        "display_name": "签到",
        "gf_type": "绝对资源类",
        "characteristic": "在险地/禁地打卡换重奖，高风险高收益。",
        "core_ability": "到达指定地点或完成签到条件获取资源。",
        "must_cost": "苟守险地、冒死潜入、长周期机会成本。",
        "forbidden_rules": ["不能随地无条件签到", "不能奖励无门槛爆表"],
        "aliases": ["签到", "签到系统"],
    },
    "res_punch_card": {
        "display_name": "打卡系统",
        "gf_type": "绝对资源类",
        "characteristic": "周期性任务打卡，偏日常积累型资源。",
        "core_ability": "完成打卡链获得阶梯奖励。",
        "must_cost": "断签惩罚；打卡任务强制冒险或社交暴露。",
        "forbidden_rules": ["不能无惩罚断签", "不能全自动化躺赢"],
        "aliases": ["打卡系统", "打卡"],
    },
    # ── 第四类：伴生外挂 ──
    "comp_grandpa": {
        "display_name": "随身老爷爷",
        "gf_type": "伴生外挂类",
        "characteristic": "高维导师：解说世界观+关键时刻有限代打。",
        "core_ability": "获得传承、功法与危机指点。",
        "must_cost": "残魂虚弱、出手耗命；继承其血仇与宿敌。",
        "forbidden_rules": ["不能无限代打", "不能无代价借力"],
        "aliases": ["随身老爷爷", "老爷爷残魂"],
    },
    "comp_ancient_soul": {
        "display_name": "上古残魂",
        "gf_type": "伴生外挂类",
        "characteristic": "偏残魂碎片：知识残缺、动机成谜。",
        "core_ability": "间歇性指引或借力量。",
        "must_cost": "夺舍风险、契约代价、信息不全导致误判。",
        "forbidden_rules": ["不能全知导师", "不能零风险附体"],
        "aliases": ["上古残魂", "残魂"],
    },
    "comp_sealed_demon": {
        "display_name": "体内封印大妖",
        "gf_type": "伴生外挂类",
        "characteristic": "借用大妖之力越级，失控线清晰。",
        "core_ability": "短时爆发式战力或天赋神通。",
        "must_cost": "失控、夺舍、侵蚀经脉；亲友线高危。",
        "forbidden_rules": ["不能无限借力无失控", "不能无后果秒杀"],
        "aliases": ["体内封印大妖", "封印大妖"],
    },
    "comp_sealed_evil_god": {
        "display_name": "邪神",
        "gf_type": "伴生外挂类",
        "characteristic": "规则级污染与契约：换力量的代价更极端。",
        "core_ability": "以契约为代价获得概念级干涉。",
        "must_cost": "精神污染、人格替换、阵营敌对。",
        "forbidden_rules": ["不能无契约白嫖", "不能零污染"],
        "aliases": ["邪神", "请神/借法体质"],
    },
    # ── 第五类：概念系 ──
    "concept_snatch": {
        "display_name": "概念摘取",
        "gf_type": "概念系类",
        "characteristic": "把抽象概念当物品剥夺/转移。",
        "core_ability": "对目标概念属性进行摘取与嫁接。",
        "must_cost": "精神力巨耗；前置条件苛刻；反噬明确。",
        "forbidden_rules": ["不能无条件改写一切", "不能无限次无损"],
        "aliases": ["概念摘取"],
    },
    "concept_rule_tamper": {
        "display_name": "规则篡改",
        "gf_type": "概念系类",
        "characteristic": "局部改写规则或因果接口（偏诡秘）。",
        "core_ability": "在限定条件下扭曲规则结果。",
        "must_cost": "规则反弹与世界修正；代价递增。",
        "forbidden_rules": ["不能一句话终结所有冲突", "不能无反噬"],
        "aliases": ["规则篡改"],
    },
    "concept_speak_law": {
        "display_name": "言出法随",
        "gf_type": "概念系类",
        "characteristic": "语言即因果武器，乌鸦嘴式应验。",
        "core_ability": "在逻辑自洽约束下让言语影响现实。",
        "must_cost": "因果反噬与代价对冲；越大改动越大反噬。",
        "forbidden_rules": ["不能无代价改因果", "不能言出即无敌"],
        "aliases": ["言出法随", "乌鸦嘴"],
    },
    "concept_great_prophecy": {
        "display_name": "大预言术",
        "gf_type": "概念系类",
        "characteristic": "预言/预演未来片段，偏仪式与材料。",
        "core_ability": "获得未来分支提示或概率云。",
        "must_cost": "预言模糊、代价材料、误读致命。",
        "forbidden_rules": ["不能无代价全知未来", "不能精确到身份证号式点杀"],
        "aliases": ["大预言术", "预言术"],
    },
    # ── 第六类：凡人流（人类特质极端化）──
    "mortal_absolute_reason": {
        "display_name": "绝对理智",
        "gf_type": "凡人流类",
        "characteristic": "极端冷静：免疫情绪操控，计算最优解。",
        "core_ability": "高压下保持判断与执行一致性。",
        "must_cost": "共情缺失、关系代价、被误解为冷血。",
        "forbidden_rules": ["不能无代价碾压一切心理战", "不能变机器人无弱点"],
        "aliases": ["绝对理智"],
    },
    "mortal_photographic_memory": {
        "display_name": "过目不忘",
        "gf_type": "凡人流类",
        "characteristic": "信息记忆优势：证据链与细节复盘。",
        "core_ability": "记住关键细节支撑推理与反杀。",
        "must_cost": "记忆过载、创伤闪回、被信息淹没。",
        "forbidden_rules": ["不能变全知图书馆"],
        "aliases": ["过目不忘"],
    },
    "mortal_micro_expression": {
        "display_name": "微表情大师",
        "gf_type": "凡人流类",
        "characteristic": "读人：从微表情与肢体语言拆谎。",
        "core_ability": "识破伪装与话术陷阱。",
        "must_cost": "误判成本；社交耗竭；被反侦察。",
        "forbidden_rules": ["不能读心", "不能百发百中无失误"],
        "aliases": ["微表情大师"],
    },
    "mortal_pain_insensitivity": {
        "display_name": "痛觉缺失",
        "gf_type": "凡人流类",
        "characteristic": "以伤换伤、极限换命；狠辣与自毁并存。",
        "core_ability": "承受非常规伤害换取近身优势。",
        "must_cost": "身体损毁不自知、预后恶化、精神异化。",
        "forbidden_rules": ["不能无伤势积累", "不能无敌不死"],
        "aliases": ["痛觉缺失", "天生疯狂"],
    },
}

VARIABLE_COMBINATIONS = {
    "targeting_degree": {
        ">=95": "主角被直接消灭（重生/穿越/灵魂转移才能延续）",
        "70-94": "主角重创至绝境（家破/入狱/坠落），生死一线",
        "40-69": "主角被打落谷底但未死，从零开始",
        "10-39": "主角受打压但有喘息空间",
        "<=9": "无人针对，草根白手起家",
    },
    "emotional_degree": {
        "<-80": "不死不休的刻骨仇恨、惨烈的背叛（最信任的人举刀/死局谋害）",
        "-80~-50": "被深深伤害，积累的怨恨与屈辱",
        "-50~-20": "轻蔑、刁难、日常欺压与排挤",
        "-20~+20": "陌生、冷漠、纯粹的利益关系或阶级无视",
        "+20~+60": "明显的好感与偏袒（有人在暗中照顾、提供情绪价值或微小帮助）",
        ">+60": "生死相依的绝对信任与守护（如忠仆拼死挡刀、挚爱不离不弃、深渊中的患难与共）",
    },
    "logic_tone": {
        "马基雅维利逻辑": (
            "极致现实主义与利己：视人为棋子，精于算计、操控与情感绑架（PUA）。"
            "无道德负罪感，视背叛为常态，认为受害者输在天真。"
            "以冷静伪善包装最利的杀局，行动多经 ROI 权衡而非情绪驱动。"
        ),
        "复仇逻辑": "咬牙切齿，血债血偿是唯一目标",
        "野心家逻辑": "往上爬，踩着所有人的头",
        "设局逻辑": "让他们用自己的手毁掉自己",
        "忍辱逻辑": "现在忍，积蓄力量等时机",
        "执念逻辑": "只要一件事，为此放弃一切",
        "绝境逻辑": "没有退路，死也要拉着垫背",
        "推理逻辑": "找到规律和漏洞，用信息差破局",
        "受害者逻辑": "无辜卷入、寻求真相与公义、在制度或谎言下自证",
        "控制逻辑": "掌控局面与关系、拒绝失控、以规则或权势反制",
        "补偿逻辑": "填补亏欠、纠偏关系、以行动赎回或正名",
        "镜像逻辑": "从对照者身上看见自身、模仿或反向成长",
    },
    "mode_tone": {
        "极渊求生": "每一步都在生死边缘，高压到极致",
        "极渊坠落": "一切崩坏，没有轻易转机，走向沉重代价",
        "浮沉逆转": "从最低谷爆发，大起大落",
        "暗流涌动": "表面平静，危险在水面下积累",
        "极道横推": "无敌爽文，一路打穿，越战越猛",
    },
}

# 与 GENRE_DICT 对齐的 13 类风味宇宙；「生活伦理」= 家庭 + 婚礼 + 情侣日常。
# flavor 仅写无挂基底；金手指的爽点/用法写在 fictional_hooks.options 全句内，避免与 survival_desc 冲突。
GENRE_CONSTRAINTS_AND_FLAVORS: dict[str, dict] = {
    "古代权谋": {
        "targeting_range": (15, 90),
        "logic_preferred": ["设局逻辑", "忍辱逻辑", "野心家逻辑", "马基雅维利逻辑"],
        "mode_preferred": ["暗流涌动", "浮沉逆转", "极渊求生"],
        "fictional_hooks": {
            "options": [
                "无（纯正统权谋，完全无外挂，纯靠智商、人脉与人心博弈破局）",
                "重生（带着前世惨死的记忆。⚠️铁律：前世的记忆必须严格截止于被杀的那一瞬间！绝对禁止出现‘前世死后我才知道……’这种逻辑悖论！核心是利用生前仅知的先知先觉来避开死局。）",
                "穿书（穿成必死炮灰。⚠️铁律：核心是利用熟知原著全书剧情的‘上帝视角’打信息差！但在开篇，绝对禁止在心里大段背诵原著大纲！必须像解谜一样，只利用眼前能看到的微小细节来撕裂死局。）",
                "读心（每天仅一次、指定对象的片刻念头。⚠️铁律：禁止读全场、禁止读穿皇权铁幕；一次所得须与当刻危局咬合）",
            ],
            "probability": [0.40, 0.25, 0.25, 0.10],
        },
        "flavor": {
            "core_aesthetic": "规矩森严、笑里藏刀、阶级压迫、帝王心术。",
            "taboos": "绝对禁止出现：黑衣刺客当众乱杀、飞镖弩箭、武侠打斗。朝堂和后宫杀人靠的是【借刀杀人】、【礼教规矩】和【构陷弹劾】。即便有先知能力也不能靠武力破局。",
            "survival_desc": "【极度注意阶级身份】：求生不仅是底层罪奴的专利！如果主角是低阶妃嫔（如秀女/答应）或基层官员/职场新人，TA们的求生是看破别人挖好的言语陷阱，是在极其森严的等级规矩下如履薄冰，是用智谋防备毒药和构陷。绝对禁止让有正规品级的主子去干劈柴、洗衣服的粗活来体现‘惨’！",
        },
    },
    "玄幻修仙": {
        "targeting_range": (0, 100),
        "logic_preferred": ["复仇逻辑", "野心家逻辑", "执念逻辑", "马基雅维利逻辑"],
        "mode_preferred": ["极渊求生", "极道横推", "浮沉逆转"],
        "fictional_hooks": {
            "options": [
                "无（纯古典凡人流，靠极致的努力和生死间的残酷算计争夺一丝天机）",
                "老爷爷残魂（见识指点机缘。⚠️铁律：不可瞬秒敌、不可无代价无限出手； combat须主角承担，残魂虚弱与时间限制须一致）",
                "熟练度面板（努力可见回报。⚠️铁律：数值须随真实修炼/练习递增，禁止睡一觉满级或无端爆破高两阶）",
                "万物隐藏词条（可见标注级线索非全知地图。⚠️铁律：捡漏必有现场风险与解读成本，禁止变天眼扫全秘境）",
            ],
            "probability": [0.15, 0.25, 0.35, 0.25],
        },
        "flavor": {
            "core_aesthetic": "伟力归于自身、天道无情、资源掠夺、逆天而行、长生执念。",
            "taboos": "禁止使用现代白话用词。禁止无脑杀伐导致战力崩坏。即使是底层，也是为了灵石、功法、寿元在挣扎，而非世俗金钱。",
            "survival_desc": "【极度注意阶级身份】：就算是外门弟子也有其修行体面，求生不仅是底层杂役的苦力活！玄幻的求生是灵气枯竭时的尔虞我诈，是面对高阶修士如看蝼蚁般的威压时，如何保全神魂不灭并寻找反噬之机。禁止用干世俗苦力来代替修仙界的真实资源残酷。",
        },
    },
    "都市职场": {
        "targeting_range": (0, 85),
        "logic_preferred": ["设局逻辑", "野心家逻辑", "忍辱逻辑", "马基雅维利逻辑"],
        "mode_preferred": ["暗流涌动", "浮沉逆转", "极道横推"],
        "fictional_hooks": {
            "options": [
                "无（纯现实商战/职场逆袭，靠专业能力、情商和人脉翻盘）",
                "重生（回到过去。⚠️铁律：商业/政策情报只能来自前世活着时亲历或可靠公开信息，截止于死亡/昏迷瞬间；禁止「死后三年并购案、股价、机密」等阴间新闻）",
                "神豪系统（花钱做任务返利。⚠️铁律：规则自洽，资金流与任务惩罚须可解释；禁止完全无视监管与税务常识的现代印钞感）",
            ],
            "probability": [0.45, 0.35, 0.20],
        },
        "flavor": {
            "core_aesthetic": "金钱权力、人情世故、阶层壁垒、信息差、资本碾压。",
            "taboos": "禁止出现超越现代法律框架的当街杀人。斗争必须围绕商战、职场排挤、资产掠夺、做空背锅和人脉碾压展开。",
            "survival_desc": "【极度注意环境底线】：不要把职场新人写成随时挨饿受冻的奴隶！都市的求生是面临破产清算、竞业协议封杀、社会性死亡、或是被夺走一切心血结晶时的背水一战。压力源于资本和人脉的碾压，绝大部分情况不来自物理上的饿肚子！",
        },
    },
    "重生穿越": {
        "targeting_range": (0, 95),
        "logic_preferred": ["复仇逻辑", "设局逻辑", "推理逻辑"],
        "mode_preferred": ["浮沉逆转", "暗流涌动", "极道横推"],
        "fictional_hooks": {
            "options": [
                "前世记忆（带着前世惨死的记忆。⚠️铁律：前世的记忆必须严格截止于被杀的那一瞬间！绝对禁止出现‘前世死后我才知道……’这种逻辑悖论！核心是利用生前仅知的先知先觉来弥补遗憾、逼敌入绝境。）",
                "穿书（穿成必死炮灰。⚠️铁律：核心是利用熟知原著全书剧情的‘上帝视角’打信息差！但在开篇，绝对禁止在心里大段背诵原著大纲！必须像解谜一样，只利用眼前能看到的微小细节来撕裂死局。）",
                "快穿任务系统（⚠️铁律：任务/提示可有盲区、误导或惩罚，禁止变剧透全本的上帝指南；须在规则夹缝中钻漏洞）",
            ],
            "probability": [0.40, 0.35, 0.25],
        },
        "flavor": {
            "core_aesthetic": "时间重置的从容、弥补遗憾、降维打击、因果重构。",
            "taboos": "禁止主角重生/穿越后依然降智被骗。必须体现出‘多活一世/全知视角’带来的心理压制感。",
            "survival_desc": "求生是在必死的宿命降临前，利用信息差提前斩断死局的源头，并承受命运改变后带来的未知蝴蝶效应。",
        },
    },
    "民间灵异": {
        "targeting_range": (20, 90),
        "logic_preferred": ["忍辱逻辑", "推理逻辑", "执念逻辑"],
        "mode_preferred": ["极渊求生", "暗流涌动", "极渊坠落"],
        "fictional_hooks": {
            "options": [
                "无（纯靠背诵的门派法术/符箓/风水堪舆破局）",
                "天生阴阳眼（见因果黑气或怨痕。⚠️铁律：非人肉全景雷达；多看多招祟须写代价与误判可能）",
                "请神/借法体质（绝境借阴神之力。⚠️铁律：每次须写时限、代价与反噬，禁止无CD满状态无限请神）",
            ],
            "probability": [0.50, 0.30, 0.20],
        },
        "flavor": {
            "core_aesthetic": "民俗禁忌、因果报应、阴阳失衡、宿命感、中式恐怖。",
            "taboos": "禁止将灵异写成西方魔法对轰。阴阳术法必须有严谨的逻辑（如五行、相生相克）。邪祟杀人必须有执念或因果铺垫。",
            "survival_desc": "面对看不见的阴寒之物和被打破的民俗禁忌，求生是用有限的法器、凡人的智慧，在因果报应的夹缝中搏命。",
        },
    },
    "盗墓探险": {
        "targeting_range": (30, 85),
        "logic_preferred": ["推理逻辑", "野心家逻辑", "设局逻辑"],
        "mode_preferred": ["极渊求生", "暗流涌动"],
        "fictional_hooks": {
            "options": [
                "无（纯靠扎实的分金定穴知识、土门倒斗技术和极致的警觉性求生）",
                "特殊血脉（驱部分毒虫邪祟。⚠️铁律：非万能护盾；易被同行当活体工具利用须体现）",
                "古物共鸣（触冥器得片段幻视。⚠️铁律：仅限与该冥器强相关片段，非墓主一生纪录片；解读错误须有代价）",
            ],
            "probability": [0.60, 0.25, 0.15],
        },
        "flavor": {
            "core_aesthetic": "未知恐惧、贪婪人性、风水秘术、地下幽闭感、黑吃黑。",
            "taboos": "禁止把古墓写成游戏副本。禁止过度玄幻导致写实感丧失。同行内鬼的背叛必须符合利益驱动，而非无脑使坏。",
            "survival_desc": "最可怕的往往不是墓里的粽子和机关，而是缺氧、黑暗、以及拿到明器后，同行在背后默默递来的刀子。",
        },
    },
    "悬疑推理": {
        "targeting_range": (0, 80),
        "logic_preferred": ["推理逻辑", "执念逻辑", "受害者逻辑", "马基雅维利逻辑"],
        "mode_preferred": ["暗流涌动", "极渊坠落"],
        "fictional_hooks": {
            "options": [
                "无（纯古典硬核推理/刑侦，用证据和严密的逻辑闭环击碎谎言）",
                "死亡回档（回退到固定锚点时刻。⚠️铁律：禁止死后凭空多出未经历世界线的全知记忆；线索须来自本轮亲身试错）",
                "犯罪心理侧写（推演还原现场。⚠️铁律：结论是推理非通灵；禁止无物证链直接写出真凶身份证号式信息）",
            ],
            "probability": [0.70, 0.15, 0.15],
        },
        "flavor": {
            "core_aesthetic": "迷雾重重、逻辑闭环、人性幽暗、时间赛跑、草蛇灰线。",
            "taboos": "绝对禁止超自然力量（金手指除外）直接作案。凶手动机必须经得起推敲。禁止关键线索刻意向读者隐瞒到最后一刻。",
            "survival_desc": "求生是在证据被伪造、时间即将耗尽、甚至被真凶诬陷为杀人魔的高压下，用纯粹的理智剥开迷雾。",
        },
    },
    "末日科幻": {
        "targeting_range": (30, 100),
        "logic_preferred": ["绝境逻辑", "野心家逻辑", "复仇逻辑"],
        "mode_preferred": ["极渊求生", "极道横推", "极渊坠落"],
        "fictional_hooks": {
            "options": [
                "无（纯硬核废土求生，靠火力、物资规划和极致的冷血存活）",
                "庇护所建造系统（种田与升级。⚠️铁律：建材、能源、技能须有废墟获取路径，禁止零成本跳科技树）",
                "无限物资空间（囤货求生。⚠️铁律：取用须有掩护、限量或风险；禁止万人围观下无解释凭空军火）",
            ],
            "probability": [0.40, 0.35, 0.25],
        },
        "flavor": {
            "core_aesthetic": "秩序崩塌、资源极度匮乏、废土生存、人性底线测试。",
            "taboos": "禁止末日环境太过安逸。丧尸/变异体必须保持持续的压迫感。资源获取必须具有极高的风险。",
            "survival_desc": "一块发霉的面包足以引发流血冲突。求生不仅要躲避城外的变异怪物，更要提防营地里人类同伴的背叛与背刺。",
        },
    },
    "恐怖灵异": {
        "targeting_range": (50, 95),
        "logic_preferred": ["绝境逻辑", "推理逻辑", "执念逻辑"],
        "mode_preferred": ["极渊求生", "极渊坠落"],
        "fictional_hooks": {
            "options": [
                "无（凡人误入诡局，没有任何反抗能力，只能靠智商寻找生路）",
                "看见隐藏规则（提示可被污染或残缺。⚠️铁律：禁止变绿字系统攻略；须推理甄别真伪，误导可致死）",
            ],
            "probability": [0.70, 0.30],
        },
        "flavor": {
            "core_aesthetic": "不可名状的恐惧、认知扭曲、规则杀、极度压抑、无法力敌。",
            "taboos": "禁止主角拥有直接打爆鬼怪的力量。恐怖氛围必须依靠心理压迫和未知，而非廉价的突然惊吓(Jump Scare)或单纯的血腥。",
            "survival_desc": "厉鬼不可被杀死，只能被规律规避。求生是在理智濒临崩溃的边缘，死死记住并遵守那些荒诞怪异的‘生存守则’。",
        },
    },
    "民国年代": {
        "targeting_range": (10, 85),
        "logic_preferred": ["忍辱逻辑", "野心家逻辑", "执念逻辑"],
        "mode_preferred": ["浮沉逆转", "暗流涌动", "极渊坠落"],
        "fictional_hooks": {
            "options": [
                "无（纯历史推演/谍战/军阀商战，靠信仰和手腕在乱世立足）",
                "重生（回到军阀混战前。⚠️铁律：情报止于前世死亡瞬间；禁止死后多年政局秘闻，除非魂观设定且开篇点明）",
            ],
            "probability": [0.80, 0.20],
        },
        "flavor": {
            "core_aesthetic": "军阀割据、新旧交替、纸醉金迷、风雨飘摇、信仰与背叛。",
            "taboos": "禁止政治背景虚化沦为单纯的恋爱布景。对历史事件和民族危亡的处理禁止儿戏化。",
            "survival_desc": "在这乱世，一粒子弹、一纸军令、乃至一船被查扣的货，都能让名门望族瞬间覆灭。求生是在各方势力的夹缝中长袖善舞。",
        },
    },
    "霸总": {
        "targeting_range": (0, 70),
        "logic_preferred": ["控制逻辑", "补偿逻辑", "设局逻辑"],
        "mode_preferred": ["浮沉逆转", "暗流涌动"],
        "fictional_hooks": {
            "options": [
                "无（纯正统甜虐/豪门恩怨/商业联姻拉扯）",
                "读心术（短时、指定对象或场景的片段心声。⚠️铁律：禁止全场广播；心声可与表情反差，但不可读穿所有人所有事）",
                "穿成虐文女主（已知套路、等价于读完全书。⚠️铁律：核心是用熟书的上帝视角打信息差；开篇禁止在心里大段背诵原著大纲，须像解谜一样用眼前细节撕开虐文死局；未发生场次勿用旁白灌设定）",
            ],
            "probability": [0.60, 0.20, 0.20],
        },
        "flavor": {
            "core_aesthetic": "极致的控制与拉扯、权势碾压带来的压迫感、豪门规矩、契约与利益交换。",
            "taboos": "禁止男主强行降智变无脑舔狗。禁止女主毫无主见只会哭泣等待救援。豪门商业博弈不能太过儿戏。",
            "survival_desc": "这里的生存压力来自于阶级和权势极不对等下的情感逼迫、长辈的棒打鸳鸯、以及豪门内部残酷的财产争夺。",
        },
    },
    "校园": {
        "targeting_range": (0, 50),
        "logic_preferred": ["镜像逻辑", "忍辱逻辑", "推理逻辑"],
        "mode_preferred": ["浮沉逆转", "暗流涌动"],
        "fictional_hooks": {
            "options": [
                "无（纯青春校园/成长阵痛/反抗校园暴力）",
                "学霸面板系统（刷题涨点。⚠️铁律：属性须绑定真实做题/训练过程，禁止睡一夜满数值）",
                "重生回高三（成年心智。⚠️铁律：记忆止于前世死亡或高考节点；禁止死后多年的真题泄题、政策文件全知）",
            ],
            "probability": [0.50, 0.25, 0.25],
        },
        "flavor": {
            "core_aesthetic": "青春悸动、成绩高压、圈子孤立、原生家庭刺痛、成长阵痛。",
            "taboos": "禁止将校园暴力轻描淡写。禁止主角太过完美毫无青春烦恼。老师和家长形象禁止极度脸谱化。",
            "survival_desc": "不用见血，被全班孤立、被老师当众扒出原生家庭的痛处、或是期末成绩的一落千丈，就是这个封闭小社会里最令人窒息的生存危机。",
        },
    },
    "生活伦理": {
        "targeting_range": (0, 40),
        "logic_preferred": ["受害者逻辑", "补偿逻辑", "控制逻辑"],
        "mode_preferred": ["暗流涌动", "浮沉逆转"],
        "fictional_hooks": {
            "options": [
                "无（纯现实伦理冲突，一地鸡毛中的清醒反击）",
                "重生（回到婚育/签债之前。⚠️铁律：前世信息止于死亡或决裂当场已知；禁止全知亲戚死后多年的密谋细枝末节）",
            ],
            "probability": [0.75, 0.25],
        },
        "flavor": {
            "core_aesthetic": "一地鸡毛、财产算计、婆媳/伦理矛盾、情绪勒索、代际剥削。",
            "taboos": "禁止杀人越货等极端暴力（必须在法制社会的框架内）。禁止深仇大恨一句话轻松化解。禁止无脑大团圆和强行原谅。",
            "survival_desc": "最深的刀子往往来自最亲近的人。饭桌上的含沙射影、重男轻女的隐性剥削、争夺房产时的撕破脸皮，构成了让人窒息的修罗场。",
        },
    },
    "通用": {
        "targeting_range": (0, 100),
        "logic_preferred": list(VARIABLE_COMBINATIONS["logic_tone"].keys()),
        "mode_preferred": list(VARIABLE_COMBINATIONS["mode_tone"].keys()),
        "fictional_hooks": {
            "options": ["无（由题材与骨骼自由发挥）"],
            "probability": [1.0],
        },
        "flavor": {
            "core_aesthetic": "与用户需求、骨骼与世界观自洽即可。",
            "taboos": "禁止与已选平台风格、主角设定明显串频（如无说明勿把写实职场写成修仙对波）。",
            "survival_desc": "在题材未精确命中时，以用户 genre_request 字面优先，保持开篇张力与可追溯动机。",
        },
    },
}

# 脑洞引擎专用：与 GENRE_CONSTRAINTS_AND_FLAVORS 的键一一对应，供 build_genre_constraints_prompt_for_brainwave 注入。
# 约束「高于」引擎内泛化示例；inferred_world_seeds / downstream 须与此自洽，禁止跨题材挪用。
GENRE_BRAINWAVE_IRON: dict[str, dict] = {
    "玄幻修仙": {
        "core_elements": ["灵气修炼", "境界突破", "宗门势力", "法宝丹药", "道途竞争"],
        "forbidden_crossover": ["现代科技主导", "现实主义职场", "考古学/盗墓"],
        "flavor_note": "超自然力量是世界物理规则，不是异常",
        "golden_finger_bias": "规则豁免类/信息降维类均适合",
    },
    "盗墓探险": {
        "core_elements": ["古墓机关", "文物/宝藏", "民俗禁忌", "地下空间", "人性博弈", "历史谜题"],
        "forbidden_crossover": [
            "修仙境界体系",
            "宗门/门派势力",
            "灵气/道蕴等修炼资源",
            "丹药/法宝等修仙道具",
            "天道/天劫等超自然修炼概念",
        ],
        "flavor_note": "超自然元素必须根植于民俗/历史/考古，而非修仙体系",
        "golden_finger_bias": "信息降维类（古籍知识/特殊感知）或凡人流类（极致胆识/专业技能）",
        "hard_rule": "禁止引入任何修仙类设定。古墓中的机关是物理/化学机关，不是修仙阵法",
    },
    "重生穿越": {
        "core_elements": ["先知优势", "历史/未来知识差", "身份落差", "蝴蝶效应"],
        "forbidden_crossover": ["无明确时代背景的纯玄幻"],
        "flavor_note": "先知信息是最大金手指，但必须有蝴蝶效应限制",
        "golden_finger_bias": "信息降维类（重生先知）为主",
    },
    "都市职场": {
        "core_elements": ["阶级壁垒", "职场规则", "资本博弈", "人际网络", "现代社会"],
        "forbidden_crossover": ["修仙体系", "异能超能力（除非是特定超能都市设定）"],
        "flavor_note": "爽点来自社会规则的精准利用，不来自超自然力量",
        "golden_finger_bias": "凡人流类/信息降维类",
    },
    "古代权谋": {
        "core_elements": ["宫廷倾轧", "派系博弈", "历史背景", "人性算计", "制度约束"],
        "forbidden_crossover": ["现代价值观直接移植", "超自然修仙元素（除非是特定仙侠设定）"],
        "flavor_note": "爽点来自在严苛规则下的精准博弈",
        "golden_finger_bias": "凡人流类/人性博弈型",
    },
    "悬疑推理": {
        "core_elements": ["信息不对称", "真相层层剥离", "心理博弈", "证据链"],
        "forbidden_crossover": ["超自然力量直接解决谜题（除非是特定灵异悬疑设定）"],
        "flavor_note": "每个谜底必须有逻辑支撑，不能靠金手指直接揭示",
        "golden_finger_bias": "信息降维类（有限度）或纯凡人推理",
    },
    "末日科幻": {
        "core_elements": ["生存资源争夺", "文明崩塌", "人性极限", "科技/变异"],
        "forbidden_crossover": ["纯修仙体系"],
        "flavor_note": "超自然元素必须有科学或伪科学解释框架",
        "golden_finger_bias": "绝对资源类/规则豁免类",
    },
    "民国年代": {
        "core_elements": ["历史背景", "时代洪流", "家国情怀", "文化碰撞"],
        "forbidden_crossover": ["纯玄幻修仙体系"],
        "flavor_note": "超自然元素若有，必须是民俗/传说层面，不是修仙体系",
        "golden_finger_bias": "凡人流类/信息降维类",
    },
    "恐怖灵异": {
        "core_elements": ["超自然威胁", "民俗禁忌", "心理恐惧", "规则破局"],
        "forbidden_crossover": ["修仙境界体系"],
        "flavor_note": "恐惧感来自未知和无力感，不是来自修炼变强",
        "golden_finger_bias": "凡人流类或特定灵异感知能力",
    },
    "民间灵异": {
        "core_elements": ["民间传说", "风俗禁忌", "地方志怪", "人情世故"],
        "forbidden_crossover": ["系统化修仙体系", "宗门势力"],
        "flavor_note": "灵异元素根植于具体地域文化，而非通用修仙规则",
        "golden_finger_bias": "凡人流类/特定民俗传承",
    },
    "校园": {
        "core_elements": ["青春成长", "校园规则", "同伴关系", "学业压力"],
        "forbidden_crossover": ["成人职场规则直接移植", "修仙体系"],
        "flavor_note": "爽点来自青春期特有的情感张力和成长突破",
        "golden_finger_bias": "凡人流类",
    },
    "霸总": {
        "core_elements": ["财富权力", "身份落差", "商业博弈", "情感拉扯"],
        "forbidden_crossover": ["修仙体系", "末日设定"],
        "flavor_note": "核心爽点是被强大且专情的人选择",
        "golden_finger_bias": "绝对资源类/身份差型",
    },
    "生活伦理": {
        "core_elements": ["当代家庭与伦理", "财产与代际矛盾", "情绪勒索", "一地鸡毛中的清醒反击"],
        "forbidden_crossover": ["修仙体系", "玄幻宗门", "末日废土主导"],
        "flavor_note": "张力来自关系与伦理、法制框架内的博弈，不靠超自然战力",
        "golden_finger_bias": "信息降维类（重生/先知）须窄域，禁止死后全知式亲戚密谋",
    },
    "通用": {
        "core_elements": ["以用户 genre_request 字面与已确认 synopsis 为先"],
        "forbidden_crossover": ["无说明时套用另一题材的完整升级/宗门/盗墓或职场模板"],
        "flavor_note": "未命中精确 bucket 时，禁止为爽感擅自换题材底盘。",
        "golden_finger_bias": "与 fictional_hook 及用户锚点自洽即可",
    },
}


def build_genre_constraints_prompt_for_brainwave(genre_request: str) -> str:
    """
    脑洞引擎 / world_build 滴灌用：按 map_genre_bucket 输出题材铁律块（中文）。
    与 GENRE_CONSTRAINTS_AND_FLAVORS 同键；细节来自 GENRE_BRAINWAVE_IRON。
    """
    bucket = map_genre_bucket(genre_request or "")
    iron = GENRE_BRAINWAVE_IRON.get(bucket) or GENRE_BRAINWAVE_IRON.get("通用") or {}
    if not isinstance(iron, dict) or not iron:
        gr = (genre_request or "").strip() or "（未指定）"
        return f"## 【题材铁律：{gr}】\n（无扩展铁律表；请以用户题材字面常识约束，禁止跨题材挪用。）\n"

    lines: list[str] = [f"## 【题材铁律：{bucket}】（以下约束高于引擎内泛化示例与脑洞自由发挥）\n"]
    ce = iron.get("core_elements")
    if isinstance(ce, list) and ce:
        lines.append(f"[必须/尊重] 核心元素：{' / '.join(str(x) for x in ce if str(x).strip())}\n")
    fc = iron.get("forbidden_crossover")
    if isinstance(fc, list) and fc:
        lines.append("[严禁] 跨题材混入：")
        for item in fc:
            s = str(item).strip()
            if s:
                lines.append(f"  - {s}")
        lines.append("")
    hr = iron.get("hard_rule")
    if isinstance(hr, str) and hr.strip():
        lines.append(f"[铁律] {hr.strip()}\n")
    fn = iron.get("flavor_note")
    if isinstance(fn, str) and fn.strip():
        lines.append(f"[气质] {fn.strip()}\n")
    gf = iron.get("golden_finger_bias")
    if isinstance(gf, str) and gf.strip():
        lines.append(f"[金手指倾向] {gf.strip()}\n")
    cfg = get_genre_config(bucket)
    flav = (cfg.get("flavor") or {}) if isinstance(cfg, dict) else {}
    tab = str(flav.get("taboos") or "").strip()
    if tab:
        lines.append(f"[同档 taboos] {tab}\n")
    return "\n".join(lines).rstrip() + "\n"


_EXACT_ALIAS_TO_CONFIG: dict[str, str] = {
    "家庭": "生活伦理",
    "婚礼": "生活伦理",
    "情侣日常": "生活伦理",
    "宫斗权谋": "古代权谋",
    "都市现代": "都市职场",
    "修仙玄幻": "玄幻修仙",
}

# 顺序：先长词/易混词，避免「恐怖灵异」被「灵异」抢走
_PATTERN_TO_CONFIG: list[tuple[re.Pattern, str]] = [
    (re.compile(r"恐怖灵异|规则怪谈|怪谈"), "恐怖灵异"),
    (re.compile(r"盗墓|摸金|古墓|探险.*墓"), "盗墓探险"),
    (re.compile(r"修仙|玄幻|修真|仙侠"), "玄幻修仙"),
    (re.compile(r"末日|废土|丧尸"), "末日科幻"),
    (re.compile(r"民国|军阀|谍战"), "民国年代"),
    (re.compile(r"悬疑|推理|刑侦"), "悬疑推理"),
    (re.compile(r"霸总|总裁|言情|甜宠"), "霸总"),
    (re.compile(r"校园|高三|青春"), "校园"),
    (re.compile(r"古代|权谋|宫斗|宫廷|后宫|宅斗|朝堂"), "古代权谋"),
    (re.compile(r"重生|穿越|穿书|魂穿|胎穿"), "重生穿越"),
    (re.compile(r"职场|商战|都市"), "都市职场"),
    (re.compile(r"灵异|鬼|阴间|邪祟|道士|符箓|阴阳"), "民间灵异"),
    (re.compile(r"家庭|婚礼|婆媳|情侣日常|伦理"), "生活伦理"),
]


def map_genre_to_config(genre_name: str) -> str:
    """细分名 / 旧桶名 → GENRE_CONSTRAINTS_AND_FLAVORS 的键。"""
    t = (genre_name or "").strip()
    if not t:
        return "通用"
    if t in _EXACT_ALIAS_TO_CONFIG:
        return _EXACT_ALIAS_TO_CONFIG[t]
    if t in GENRE_CONSTRAINTS_AND_FLAVORS:
        return t
    return map_genre_bucket(t)


def map_genre_bucket(genre_request: str) -> str:
    """用户自由文本 → 配置键（与 map_genre_to_config 在模糊匹配上一致）。"""
    t = (genre_request or "").strip()
    if not t:
        return "通用"
    if t in _EXACT_ALIAS_TO_CONFIG:
        return _EXACT_ALIAS_TO_CONFIG[t]
    if t in GENRE_CONSTRAINTS_AND_FLAVORS:
        return t
    for pat, key in _PATTERN_TO_CONFIG:
        if pat.search(t):
            return key
    return "通用"


def get_genre_config(config_key: str) -> dict:
    return GENRE_CONSTRAINTS_AND_FLAVORS.get(config_key) or GENRE_CONSTRAINTS_AND_FLAVORS["通用"]


def _normalize_logic_choice(candidates: list[str]) -> str:
    valid = set(VARIABLE_COMBINATIONS["logic_tone"].keys())
    pool = [x for x in candidates if x in valid]
    if not pool:
        pool = list(valid)
    return random.choice(pool)


def _normalize_mode_choice(candidates: list[str]) -> str:
    valid = set(VARIABLE_COMBINATIONS["mode_tone"].keys())
    pool = [x for x in candidates if x in valid]
    if not pool:
        pool = list(valid)
    return random.choice(pool)


def _sample_hook_from_config(c: dict) -> str:
    fh = c.get("fictional_hooks") or {}
    opts = fh.get("options") or ["无"]
    weights = fh.get("probability")
    if not weights or len(weights) != len(opts):
        weights = [1.0 / len(opts)] * len(opts)
    return random.choices(opts, weights=weights, k=1)[0]


def _sample_hook_from_config_skip_plain(c: dict) -> str:
    """仅在非「无（…）」选项中按原 probability 比例抽样（用于用户明确要求有挂时）。"""
    fh = c.get("fictional_hooks") or {}
    opts = fh.get("options") or ["无"]
    weights = fh.get("probability")
    if not weights or len(weights) != len(opts):
        weights = [1.0 / len(opts)] * len(opts)
    pairs: list[tuple[str, float]] = []
    for o, w in zip(opts, weights):
        if not isinstance(o, str) or not o.strip():
            continue
        if o.strip().startswith("无（"):
            continue
        try:
            wf = float(w)
        except (TypeError, ValueError):
            wf = 0.0
        pairs.append((o, max(wf, 0.0)))
    if not pairs:
        return _sample_hook_from_config(c)
    o2 = [p[0] for p in pairs]
    w2 = [p[1] for p in pairs]
    if sum(w2) <= 0:
        return random.choice(o2)
    return random.choices(o2, weights=w2, k=1)[0]


def _extract_hook_name(raw_hook: str) -> str:
    """从「名称（说明）」里抽取名称段。"""
    t = (raw_hook or "").strip()
    if not t:
        return ""
    m = re.match(r"^([^（(]+)[（(].*?[）)]\s*$", t)
    if m:
        return m.group(1).strip()
    return t


def _iter_golden_finger_alias_specs():
    """按别名长度降序，优先匹配长词，避免短词误命中。"""
    pairs: list[tuple[int, str, dict]] = []
    for spec in GOLDEN_FINGER_MATRIX.values():
        names = [spec.get("display_name", "")] + list(spec.get("aliases") or [])
        for a in names:
            a = str(a or "").strip()
            if not a:
                continue
            pairs.append((len(a), a, spec))
    pairs.sort(key=lambda x: -x[0])
    return [(a, sp) for _, a, sp in pairs]


def resolve_fictional_hook_profile(raw_hook: str) -> dict | None:
    """根据名称/别名匹配金手指索引，返回结构化能力档（每条金手指独立，特点在 characteristic）。"""
    hook_name = _extract_hook_name(raw_hook)
    hook_name = (hook_name or "").strip()
    if not hook_name or hook_name.startswith("无"):
        return None
    alias_specs = _iter_golden_finger_alias_specs()
    # 1) 完全相等
    for alias, spec in alias_specs:
        if hook_name == alias:
            return spec
    # 2) 前缀：如「重生（带着…」
    for alias, spec in alias_specs:
        if hook_name.startswith(alias):
            rest = hook_name[len(alias) :]
            if not rest or rest[0] in "（(：:·、，, \t":
                return spec
    # 3) 子串（别名长度≥2，减少单字误触）
    for alias, spec in alias_specs:
        if len(alias) >= 2 and alias in hook_name:
            return spec
    return None


def is_no_fictional_hook_string(raw_hook: str) -> bool:
    """与开篇节点「无挂配方」判断对齐：无文本、纯「无」、或「无（…）」前缀。"""
    t = (raw_hook or "").strip()
    if not t or t in ("（无）", "无"):
        return True
    return t.startswith("无（")


def golden_finger_capabilities_from_spec(spec: dict) -> dict:
    """由矩阵 spec 生成 protagonist_card.capabilities.golden_finger（与 genesis_iceberg 模板字段对齐）。"""
    return {
        "has_golden_finger": True,
        "gf_type": spec.get("gf_type"),
        "core_ability": (spec.get("core_ability") or "").strip(),
        "activation_condition": "绝境或与认知强咬合的当场触发；禁止系统弹窗式声明",
        "cost_and_limit": (spec.get("must_cost") or "").strip(),
        "exposure_risk": "暴露后引发觊觎、追杀或规则反噬（须随剧情落地）",
        "current_state": "未完全掌握；存在解读与误判风险（开篇可随文细化）",
    }


def merge_golden_finger_into_protagonist_dict(card: dict, fictional_hook: str) -> dict:
    """
    若角色卡缺少可用的 golden_finger（无 core_ability），则从 GOLDEN_FINGER_MATRIX 注入。
    已存在完整 golden_finger 时返回原 dict 引用，避免无意义拷贝。
    """
    if not isinstance(card, dict) or not card:
        return card
    fh = (fictional_hook or "").strip()
    if is_no_fictional_hook_string(fh):
        return card
    spec = resolve_fictional_hook_profile(fh)
    if not spec:
        return card
    caps = card.get("capabilities")
    if not isinstance(caps, dict):
        caps = {}
    gf = caps.get("golden_finger")
    if isinstance(gf, dict) and gf.get("has_golden_finger") and (str(gf.get("core_ability") or "").strip()):
        return card
    new_caps = dict(caps)
    new_caps["golden_finger"] = golden_finger_capabilities_from_spec(spec)
    out = dict(card)
    out["capabilities"] = new_caps
    return out


def build_fictional_hook_enforcement_block(raw_hook: str) -> str:
    """
    供提示词注入：
    输出金手指名称、类型、核心能力、必写代价、禁止事项，便于下游落地到角色卡字段。
    """
    spec = resolve_fictional_hook_profile(raw_hook)
    if not spec:
        return ""
    forbidden = "；".join(str(x) for x in (spec.get("forbidden_rules") or []) if str(x).strip())
    ch = str(spec.get("characteristic") or "").strip()
    ch_line = f"- 特点(characteristic): {ch}\n" if ch else ""
    return (
        "【金手指结构化约束（必须落地到角色卡 capabilities.golden_finger）】\n"
        f"- 名称(display_name，与 genesis_variables.fictional_hook 一致): {spec.get('display_name', '')}\n"
        f"- 类型(gf_type): {spec.get('gf_type', '')}\n"
        + ch_line
        + f"- 核心能力(core_ability): {spec.get('core_ability', '')}\n"
        f"- 必写代价(cost_and_limit): {spec.get('must_cost', '')}\n"
        f"- 禁止事项: {forbidden or '不能全知；不能无代价'}\n"
    )


def sample_variables(genre_request: str) -> dict:
    """一次采样：约束 + 金手指 + genre_bucket（配置键）。"""
    bucket = map_genre_bucket(genre_request)
    c = get_genre_config(bucket)
    td_lo, td_hi = c.get("targeting_range", (0, 100))
    targeting_degree = random.randint(int(td_lo), int(td_hi))
    emotional_degree = random.randint(-100, 100)
    logics = c.get("logic_preferred") or list(VARIABLE_COMBINATIONS["logic_tone"].keys())
    modes = c.get("mode_preferred") or list(VARIABLE_COMBINATIONS["mode_tone"].keys())
    return {
        "targeting_degree": targeting_degree,
        "emotional_degree": emotional_degree,
        "human_logic": _normalize_logic_choice(logics),
        "story_mode": _normalize_mode_choice(modes),
        "fictional_hook": _sample_hook_from_config(c),
        "genre_bucket": bucket,
    }


# 开篇「重新生成」时用户意见：不要金手指 / 不要重生 等 → 强制选用本题材「无（…）」档位
_REGENERATE_PLAIN_HOOK_PATTERN = re.compile(
    r"没有金手指|无金手指|不要金手指|不用金手指|别写金手指|不写金手指|去掉金手指|"
    r"不要外挂|无外挂|不要系统|无系统|"
    r"纯正统|纯无挂|没有外挂|不要重生|无重生|不写重生|不要穿越|别写先知|"
    r"纯权谋|无挂|不要挂",
    re.IGNORECASE,
)

# 须先判「无挂」再判「有挂」，避免「不要金手指」误触下列模式
_REGENERATE_WANT_HOOK_PATTERN = re.compile(
    r"开启外挂|开外挂|要外挂|写上挂|加外挂|"
    r"开启金手指|开金手指|要金手指|加金手指|有金手指|来.?金手指|给个挂|"
    r"要重生|写重生|来.?重生|要读心|要先知|要穿书|要系统|加点|面板|系统文|"
    r"随身|老爷爷|词条|回档|穿书|读心",
    re.IGNORECASE,
)


def variables_for_opening_regenerate(genre_request: str, feedback: str) -> dict:
    """
    用户选「重新生成开篇」时：整表重新采样。
    - 意见明确要求无金手指 → 锁定为本题材「无（…）」档。
    - 意见明确要求有外挂 → 在配置中排除「无（…）」后按原概率比例抽样，避免仍显示无挂。
    """
    v = sample_variables(genre_request)
    fb = feedback or ""
    bucket = v.get("genre_bucket") or map_genre_bucket(genre_request)
    c = get_genre_config(bucket)

    if _REGENERATE_PLAIN_HOOK_PATTERN.search(fb):
        opts = (c.get("fictional_hooks") or {}).get("options") or []
        for opt in opts:
            if isinstance(opt, str) and opt.strip().startswith("无（"):
                v["fictional_hook"] = opt
                break
        return v

    if _REGENERATE_WANT_HOOK_PATTERN.search(fb):
        v["fictional_hook"] = _sample_hook_from_config_skip_plain(c)

    return v


def format_genesis_flavor_block(config_key: str, original_genre_label: str) -> str:
    """注入开篇 LLM：风味/禁忌/生存描述。"""
    c = get_genre_config(config_key)
    flavor = c.get("flavor") or {}
    ca = (flavor.get("core_aesthetic") or "").strip()
    tb = (flavor.get("taboos") or "").strip()
    sv = (flavor.get("survival_desc") or "").strip()
    return (
        "【题材核心风味与禁忌（铁律）】\n"
        f"用户题材表述：{original_genre_label or config_key}\n"
        f"配置桶：{config_key}\n"
        f"核心美学：{ca}\n"
        f"绝对禁忌：{tb}\n"
        f"压迫与求生感：{sv}\n"
    )


def describe_targeting(td: int) -> str:
    if td >= 95:
        return VARIABLE_COMBINATIONS["targeting_degree"][">=95"]
    if td >= 70:
        return VARIABLE_COMBINATIONS["targeting_degree"]["70-94"]
    if td >= 40:
        return VARIABLE_COMBINATIONS["targeting_degree"]["40-69"]
    if td >= 10:
        return VARIABLE_COMBINATIONS["targeting_degree"]["10-39"]
    return VARIABLE_COMBINATIONS["targeting_degree"]["<=9"]


def describe_emotional(ed: int) -> str:
    if ed < -80:
        return VARIABLE_COMBINATIONS["emotional_degree"]["<-80"]
    if ed < -50:
        return VARIABLE_COMBINATIONS["emotional_degree"]["-80~-50"]
    if ed < -20:
        return VARIABLE_COMBINATIONS["emotional_degree"]["-50~-20"]
    if ed <= 20:
        return VARIABLE_COMBINATIONS["emotional_degree"]["-20~+20"]
    if ed <= 60:
        return VARIABLE_COMBINATIONS["emotional_degree"]["+20~+60"]
    return VARIABLE_COMBINATIONS["emotional_degree"][">+60"]


def emotional_degree_opening_hint(ed: int) -> str:
    """
    创世开篇：情感度为 -100～+100 坐标轴；仅在高正/高负两端追加硬性落地点，与 VARIABLE_COMBINATIONS 一致。
    正数＝温情与忠诚向，负数＝背叛与仇恨向；中段仅靠「情感度：数值 — 释义」即可。
    """
    if ed > 60:
        return (
            "【情感度落地铁律】：当前情感度极高！正文中【必须】出现一个对主角极度忠诚、散发温情、"
            "甚至愿意为主角牺牲的角色（如死忠仆人、患难挚友）。即使环境再残酷，也必须写出两人患难与共的温暖羁绊！"
        )
    if ed < -60:
        return (
            "【情感度落地铁律】：当前情感度极低！正文中【必须】体现出极致的背叛感或不死不休的仇恨，"
            "对手的冷酷必须令人发指。"
        )
    return ""
