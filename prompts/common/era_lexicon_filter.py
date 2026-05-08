"""
时代语料隔离（Lexicon Isolation）：抽象约束，依赖 narrative_era + 题材由模型自判词界，
不在代码里穷举禁词表。供 world_build / expand1 / expand2 / write 等节点拼接 System。
"""
from __future__ import annotations

from typing import Mapping

ERA_LEXICON_FILTER_MARKDOWN = r"""
======================================================================
🕰️ 【最高指令：时代语料隔离法则 (Lexicon Isolation Rule)】 🕰️

当前故事的叙事时代/背景设定为：【{narrative_era}】
当前核心题材为：【{genre_request}】

为了保证世界的真实感与沉浸感，你在构建设定、生成旁白、角色对话及心理活动时，必须强制开启「时代滤镜」，严格遵守以下用词法则：

1. 🚫 【绝对词汇隔离】：
   - 严禁出现超越该时代科技水平、行政体系、学术体系及文化认知的词汇。
   - (例如：前现代/古代背景下，绝对禁止出现“考古、勘探、研究所、体制内、科学、逻辑、基因、体制、行政”等近现代学术与政务词汇；禁止出现网络热梗或现代白话口癖)。

2. 🔄 【概念降维映射】：
   - 如果剧情必须表达某种“现代功能”（如：探险、鉴定、审批、组织），必须将其转化为符合【{narrative_era}】时代肌理的土语、行话、官制或民俗表达。
   - 映射示例逻辑：
     * 官方许可 -> 官府海捕文书、通关印信、宗门法令。
     * 学术研究 -> 倒斗行话、风水堪舆、古卷考证、秘术流传。
     * 组织机构 -> 堂口、宗门、牙行、暗舵、钦天监。

3. 🎭 【POV 认知局限】：
   - 叙述者和角色的认知不能开上帝视角。他们对未知事物的命名只能基于那个时代的认知图谱（例如：把未知的化学反应描述为“瘴气/妖风”，把机械结构描述为“奇巧淫技/偃甲机关”）。

如果系统检测到你在【{narrative_era}】语境中混入了违和的跨时代词汇，将被判定为严重的“设定穿帮”事故！
======================================================================
"""


def resolve_narrative_era_for_filter(state: Mapping[str, Any]) -> str:
    """从 state 解析用于语料滤镜的 narrative_era（与 world_build 锚点来源一致）。"""
    ne = str(state.get("narrative_era") or "").strip()
    if ne:
        return ne
    ws = state.get("world_setting")
    if isinstance(ws, dict):
        t = str(ws.get("narrative_era") or "").strip()
        if t:
            return t
    snap = state.get("iceberg_world_snapshot") or {}
    if isinstance(snap, dict):
        t = str(snap.get("narrative_era") or "").strip()
        if t:
            return t
    ua = state.get("user_anchors") or {}
    if isinstance(ua, dict):
        for rule in ua.get("world_rules") or []:
            s = str(rule).strip()
            if s.startswith("[叙事时代与语体锚点]"):
                return s.split("]", 1)[-1].strip()
    be = state.get("brainwave_engine") or {}
    if isinstance(be, dict):
        t = str(be.get("narrative_era") or "").strip()
        if t:
            return t
    return ""


def format_era_lexicon_block(*, narrative_era: str = "", genre_request: str = "") -> str:
    """格式化时代语料隔离块，供拼入各节点 System。"""
    ne = (narrative_era or "").strip() or (
        "（未单独给出：须根据 user 消息中的 synopsis/world 与题材自行推断时代肌理，并严格按上法则执行）"
    )
    gr = (genre_request or "").strip() or "通用网文"
    return ERA_LEXICON_FILTER_MARKDOWN.format(narrative_era=ne, genre_request=gr)


def era_lexicon_system_suffix(state: Mapping[str, Any]) -> str:
    """从 CreationState 取字段并返回可拼接的语料隔离 System 片段。"""
    return format_era_lexicon_block(
        narrative_era=resolve_narrative_era_for_filter(state),
        genre_request=str(state.get("genre_request") or "").strip(),
    )
