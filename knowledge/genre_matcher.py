"""
genre_matcher.py — 题材关键词匹配函数

根据用户输入的 genre_request 字符串（可能模糊，如"玄幻逆袭"、"古代言情权谋"）
匹配到 genre_dict 中的标准题材名。

匹配策略：
  - 对每个标准题材计算关键词命中分数
  - 返回分数最高的 1-2 个题材（支持组合注入，如"古代权谋 + 情侣日常"）
  - 无命中时返回空列表（自由创作模式，不注入题材词典）
"""
from __future__ import annotations
from knowledge.genre_dict import GENRE_DICT

# 每个标准题材对应的匹配关键词
_GENRE_KEYWORDS: dict[str, list[str]] = {
    "玄幻修仙": ["玄幻", "修仙", "修真", "仙侠", "炼气", "筑基", "宗门", "灵根", "逆袭修仙", "武道"],
    "重生穿越": ["重生", "穿越", "系统", "前世", "重来", "穿书", "金手指", "回到", "重回", "转世"],
    "悬疑推理": ["悬疑", "推理", "侦探", "案件", "凶手", "密室", "破案", "侦查", "犯罪", "刑侦"],
    "民间灵异": ["风水", "术法", "灵异", "民俗", "术士", "阴阳", "驱鬼", "邪祟","符咒", "命格", "师门", "阴司", "鬼神", "诅咒"],
    "盗墓探险": ["盗墓", "倒斗", "古墓", "探险", "洛阳铲", "文物", "机关", "秘术", "北派", "南派"],
    "都市职场": ["都市", "职场", "创业", "现代商战", "打工", "公司", "办公室", "逆袭职场"],
    "霸总": ["霸总", "总裁", "商战", "豪门", "富二代", "女强男强"],
    "末日科幻": ["末日", "丧尸", "科幻", "异变", "求生", "废土", "病毒", "核战", "末世"],
    "民国年代": ["民国", "年代", "旧上海", "抗战", "解放前", "民初", "近代"],
    "恐怖灵异": ["恐怖", "灵异", "鬼怪", "民俗", "阴阳", "鬼屋", "降头", "阴间"],
    "古代权谋": ["古代", "权谋", "宫斗", "朝堂", "皇权", "宫廷", "后宫", "太子", "皇帝"],
    "校园": ["校园", "青春", "高中", "大学", "学生", "学校", "班级", "高考"],
    "家庭": ["家庭", "亲情", "婆媳", "家族", "父母", "兄弟", "姐妹", "亲子"],
    "婚礼": ["婚礼", "婚姻", "结婚", "婚变", "离婚"],
    "情侣日常": ["甜宠", "日常", "恋爱", "情侣", "甜文", "言情", "爱情"],
}


def match_genre(genre_request: str, top_k: int = 2) -> list[str]:
    """
    根据 genre_request 字符串匹配最相关的题材名。

    参数：
        genre_request  — 用户输入（如"玄幻逆袭"、"古代言情权谋"）
        top_k          — 最多返回几个题材（默认 2，允许组合）

    返回：
        匹配到的标准题材名列表（只保留在 GENRE_DICT 中存在的），
        无命中时返回空列表。
    """
    if not genre_request:
        return []

    scores: dict[str, int] = {}
    text = genre_request.lower()

    for genre, keywords in _GENRE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[genre] = score

    if not scores:
        return []

    # 按分数降序排列，取 top_k
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = [g for g, _ in ranked[:top_k] if g in GENRE_DICT]

    # 去重（理论上不会重复，但防御性处理）
    seen: set[str] = set()
    deduped = []
    for g in result:
        if g not in seen:
            seen.add(g)
            deduped.append(g)

    return deduped
