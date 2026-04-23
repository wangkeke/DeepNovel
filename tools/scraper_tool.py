"""
网页爬取工具：使用 Scrapling 实现两层爬取策略
  第一层：Scrapling Fetcher（静态页面 + 轻度反爬）
  第二层：Scrapling StealthyFetcher（JS渲染 + 强反爬）
  降级：返回 partial 状态

支持 URL 类型：
  - 目录页（自动识别）→ 获取章节列表 → 逐章抓取正文
  - 阅读页（单章）→ 直接抓取正文
  - 小说首页 → 跳转目录页
"""
from __future__ import annotations
import asyncio
import random
import re
from config import (
    SCRAPER_DELAY_MIN, SCRAPER_DELAY_MAX,
    SCRAPER_MAX_RETRIES, SCRAPER_RETRY_BACKOFF, SCRAPER_MAX_CHAPTERS
)


# ─── URL 类型识别 ─────────────────────────────────────────────────────────────
def _detect_url_type(url: str) -> str:
    """返回 'catalog' | 'reader' | 'homepage'"""
    patterns = {
        "catalog": [r"/catalog", r"/chapter", r"bid=\w+(?!.*cid=)", r"/directory"],
        "reader":  [r"/reader", r"bid=\w+.*cid=\w+", r"/chapter/\d+", r"/read/\d+"],
    }
    for url_type, pats in patterns.items():
        for p in pats:
            if re.search(p, url, re.IGNORECASE):
                return url_type
    return "homepage"


# ─── 章节正文提取辅助 ─────────────────────────────────────────────────────────
def _extract_text_from_page(page) -> str:
    """
    用 Scrapling AI 语义提取正文区域，
    过滤导航/广告/评论等干扰内容
    """
    try:
        # 尝试通过常见正文容器语义检索
        content_elem = page.find("div", {"role": "main"})
        if not content_elem:
            content_elem = page.find("article")
        if not content_elem:
            content_elem = page.find("div", {"class": re.compile(r"content|chapter|text|novel", re.I)})
        if content_elem:
            return content_elem.get_text(separator="\n", strip=True)
        # 降级：拿 body 全文本
        body = page.find("body")
        return body.get_text(separator="\n", strip=True) if body else ""
    except Exception:
        return ""


def _clean_novel_text(raw_text: str) -> str:
    """清理正文：去广告行、多余空白"""
    lines = raw_text.split("\n")
    cleaned = []
    ad_keywords = ["本章节来自", "手机用户", "加入书架", "记住本站", "最新章节", "www.", "http"]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(kw in line for kw in ad_keywords):
            continue
        if len(line) < 3 and not re.search(r"[\u4e00-\u9fff]", line):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


# ─── 单章节获取 ───────────────────────────────────────────────────────────────
async def _fetch_chapter(url: str, use_stealthy: bool = False) -> str:
    """获取单章正文，失败返回空字符串"""
    try:
        from scrapling import Fetcher, StealthyFetcher
    except ImportError:
        raise ImportError("scrapling 未安装，请执行: uv add scrapling")

    await asyncio.sleep(random.uniform(SCRAPER_DELAY_MIN, SCRAPER_DELAY_MAX))

    for attempt in range(SCRAPER_MAX_RETRIES):
        try:
            if use_stealthy:
                fetcher = StealthyFetcher()
                page = await fetcher.async_fetch(url)
            else:
                fetcher = Fetcher()
                page = await fetcher.async_fetch(url)

            text = _extract_text_from_page(page)
            text = _clean_novel_text(text)
            if text and len(text) > 100:
                return text
            # 正文为空，升级到 stealthy
            if not use_stealthy:
                return await _fetch_chapter(url, use_stealthy=True)
            return ""
        except Exception:
            if attempt < SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(SCRAPER_RETRY_BACKOFF ** attempt)
            else:
                return ""
    return ""


# ─── 目录页解析 ───────────────────────────────────────────────────────────────
async def _fetch_catalog(url: str) -> dict:
    """
    抓取目录页，返回：
    {
        "title": str,
        "author": str,
        "intro": str,
        "cover_url": str,
        "chapters": [{"index": int, "name": str, "url": str, "is_paid": bool}]
    }
    """
    try:
        from scrapling import Fetcher, StealthyFetcher
    except ImportError:
        raise ImportError("scrapling 未安装，请执行: uv add scrapling")

    page = None
    for attempt in range(SCRAPER_MAX_RETRIES):
        try:
            fetcher = Fetcher()
            page = await fetcher.async_fetch(url)
            break
        except Exception:
            if attempt < SCRAPER_MAX_RETRIES - 1:
                await asyncio.sleep(SCRAPER_RETRY_BACKOFF ** attempt)

    if page is None:
        # 第一层失败，升级
        try:
            fetcher = StealthyFetcher()
            page = await fetcher.async_fetch(url)
        except Exception:
            return {"title": "", "author": "", "intro": "", "cover_url": "", "chapters": []}

    # 提取元数据
    def safe_text(elements) -> str:
        try:
            return elements[0].text.strip() if elements else ""
        except Exception:
            return ""

    def safe_attr(elements, attr: str) -> str:
        try:
            return (elements[0].get(attr) or "").strip() if elements else ""
        except Exception:
            return ""

    # 书名：h1 > og:title > <title>
    title = (
        safe_text(page.find_all("h1"))
        or safe_attr(page.find_all("meta", {"property": "og:title"}), "content")
        or safe_text(page.find_all("title"))
    )

    # 作者：常见 class 关键词 / meta
    author = (
        safe_text(page.find_all(attrs={"class": re.compile(r"author|writer", re.I)}))
        or safe_attr(page.find_all("meta", {"name": re.compile(r"author", re.I)}), "content")
    )

    # 简介：og:description > meta description > class 关键词
    intro = (
        safe_attr(page.find_all("meta", {"property": "og:description"}), "content")
        or safe_attr(page.find_all("meta", {"name": "description"}), "content")
        or safe_text(page.find_all(attrs={"class": re.compile(r"intro|desc|summary|synopsis", re.I)}))
    )

    # 封面：og:image > 首个 <img> src
    cover_url = (
        safe_attr(page.find_all("meta", {"property": "og:image"}), "content")
        or safe_attr(page.find_all("img", {"class": re.compile(r"cover|thumb|book", re.I)}), "src")
    )

    # 提取章节列表
    chapters = []
    chapter_links = page.find_all("a", {"href": re.compile(r"/chapter|/read|/\d+")})
    paid_markers = {"vip", "付费", "锁", "🔒"}

    for idx, link in enumerate(chapter_links[:SCRAPER_MAX_CHAPTERS]):
        href = link.get("href", "")
        name = link.text.strip() if link.text else f"第{idx+1}章"
        # 补全相对 URL
        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        # 判断付费标记
        link_text = (link.text or "").lower()
        parent_text = ""
        try:
            parent_text = (link.parent.text or "").lower()
        except Exception:
            pass
        is_paid = any(m in link_text or m in parent_text for m in paid_markers)
        if href:
            chapters.append({"index": idx, "name": name, "url": href, "is_paid": is_paid})

    return {
        "title": title,
        "author": author,
        "intro": intro,
        "cover_url": cover_url,
        "chapters": chapters,
    }


# ─── 主接口 ───────────────────────────────────────────────────────────────────
async def scrape_novel_url(url: str, progress_callback=None) -> dict:
    """
    爬取小说 URL，返回结构化数据。

    Args:
        url: 小说 URL（支持目录页/阅读页/首页）
        progress_callback: 可选，每章完成时回调 callback(current, total)

    Returns:
        {
          "title": str,
          "author": str,
          "intro": str,
          "cover_url": str,
          "total_chapters": int,
          "free_chapter_count": int,
          "paid_chapter_count": int,
          "free_chapters": [{"index": int, "name": str, "content": str, "word_count": int}],
          "paid_chapters": [{"index": int, "name": str}],
          "full_text": str,
          "fetch_mode": "fetcher" | "stealthy" | "partial",
          "partial_reason": str
        }
    """
    url_type = _detect_url_type(url)

    # 如果是阅读页（单章），直接抓取
    if url_type == "reader":
        text = await _fetch_chapter(url)
        if text:
            return {
                "title": "",
                "author": "",
                "intro": "",
                "cover_url": "",
                "total_chapters": 1,
                "free_chapter_count": 1,
                "paid_chapter_count": 0,
                "free_chapters": [{"index": 0, "name": "单章", "content": text, "word_count": len(text)}],
                "paid_chapters": [],
                "full_text": text,
                "fetch_mode": "fetcher",
                "partial_reason": "",
            }
        return _partial_result("单章抓取失败")

    # 目录页/首页：先获取章节列表
    catalog = await _fetch_catalog(url)
    if not catalog["chapters"]:
        return _partial_result("目录页解析失败，未找到章节列表")

    free_chapters_meta = [c for c in catalog["chapters"] if not c["is_paid"]]
    paid_chapters_meta = [c for c in catalog["chapters"] if c["is_paid"]]

    # 逐章抓取免费正文
    free_chapters = []
    fetch_mode = "fetcher"
    failed_count = 0

    for i, ch_meta in enumerate(free_chapters_meta):
        if progress_callback:
            progress_callback(i + 1, len(free_chapters_meta))

        text = await _fetch_chapter(ch_meta["url"])
        if not text:
            failed_count += 1
            fetch_mode = "stealthy"
            # 二次尝试（StealthyFetcher）
            text = await _fetch_chapter(ch_meta["url"], use_stealthy=True)

        if text:
            free_chapters.append({
                "index": ch_meta["index"],
                "name": ch_meta["name"],
                "content": text,
                "word_count": len(text),
            })

    if not free_chapters:
        return _partial_result(
            "所有章节正文抓取失败，可能需要登录或平台反爬过强。"
            "建议手动下载后上传 txt 文件。"
        )

    if failed_count > len(free_chapters_meta) * 0.5:
        fetch_mode = "partial"

    full_text = "\n\n".join(
        f"## {ch['name']}\n\n{ch['content']}" for ch in free_chapters
    )

    return {
        "title": catalog["title"],
        "author": catalog["author"],
        "intro": catalog["intro"],
        "cover_url": catalog["cover_url"],
        "total_chapters": len(catalog["chapters"]),
        "free_chapter_count": len(free_chapters),
        "paid_chapter_count": len(paid_chapters_meta),
        "free_chapters": free_chapters,
        "paid_chapters": [{"index": c["index"], "name": c["name"]} for c in paid_chapters_meta],
        "full_text": full_text,
        "fetch_mode": fetch_mode,
        "partial_reason": "",
    }


def _partial_result(reason: str) -> dict:
    return {
        "title": "",
        "author": "",
        "intro": "",
        "cover_url": "",
        "total_chapters": 0,
        "free_chapter_count": 0,
        "paid_chapter_count": 0,
        "free_chapters": [],
        "paid_chapters": [],
        "full_text": "",
        "fetch_mode": "partial",
        "partial_reason": reason,
    }
