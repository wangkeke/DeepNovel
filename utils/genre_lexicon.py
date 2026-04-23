"""按 synopsis / 题材匹配加载 prompts/genres/*.md，供动态注入系统提示。"""
from __future__ import annotations

from pathlib import Path

_GENRES_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "genres"

# 中文题材名或俗称 → lexicon 文件名（不含 .md）
_SLUG_ALIASES: dict[str, str] = {
    "玄幻": "xianxia",
    "修仙": "xianxia",
    "仙侠": "xianxia",
    "宫斗": "palace",
    "宫廷": "palace",
    "后宫": "palace",
    "权谋": "palace",
    "赛博": "cyberpunk",
    "赛博朋克": "cyberpunk",
    "科幻": "scifi",
    "都市": "urban_business",
    "商战": "urban_business",
    "言情": "romance",
    "武侠": "wuxia",
    "历史": "historical",
    "系统流": "game_system",
    "无限流": "game_system",
}


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def resolve_genre_lexicon_slugs(
    synopsis: dict | None,
    matched_genres: list[str] | None = None,
) -> list[str]:
    """优先 synopsis.genre_lexicon_keys；否则尝试 matched_genres 映射；再否则 generic。"""
    syn = synopsis or {}
    keys = syn.get("genre_lexicon_keys")
    if isinstance(keys, str):
        keys = [keys]
    if isinstance(keys, list) and keys:
        out: list[str] = []
        for k in keys:
            slug = str(k).strip().lower().replace(" ", "_").replace("-", "_")
            if slug:
                out.append(slug)
        return _dedupe_preserve(out) if out else ["generic"]

    out = []
    for g in matched_genres or []:
        g = (g or "").strip()
        if not g:
            continue
        if g in _SLUG_ALIASES:
            out.append(_SLUG_ALIASES[g])
            continue
        slug = g.lower().replace(" ", "_").replace("-", "_")
        if (_GENRES_ROOT / f"{slug}.md").is_file():
            out.append(slug)
    return _dedupe_preserve(out) if out else ["generic"]


def load_genre_lexicon_section(
    synopsis: dict | None,
    matched_genres: list[str] | None = None,
) -> str:
    """
    读取若干 md 并拼接；若均不存在则尝试 generic.md。
    返回纯文本（不含外层标题）；调用方可包 【本世界运行铁律】。
    """
    slugs = resolve_genre_lexicon_slugs(synopsis, matched_genres)
    chunks: list[str] = []
    loaded: set[str] = set()
    for slug in slugs:
        if slug in loaded:
            continue
        path = _GENRES_ROOT / f"{slug}.md"
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8").strip())
            loaded.add(slug)
    if not chunks:
        generic = _GENRES_ROOT / "generic.md"
        if generic.is_file():
            chunks.append(generic.read_text(encoding="utf-8").strip())
    if not chunks:
        return ""
    return "\n\n---\n\n".join(chunks)


def genre_lexicon_banner(synopsis: dict | None, matched_genres: list[str] | None = None) -> str:
    body = load_genre_lexicon_section(synopsis, matched_genres)
    if not body.strip():
        return ""
    return f"【本世界运行铁律（题材常识 · 动态注入）】\n\n{body}"
