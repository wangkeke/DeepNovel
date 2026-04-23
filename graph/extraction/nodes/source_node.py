"""
source_node：来源判断 + 文本获取
支持三种来源：
  file    - 本地文件（txt/docx/pdf/图片）
  url     - 网络爬取（Scrapling 两层策略）
  library - 从骨骼库直接加载已有原文（暂不支持，提示用户）
"""
from __future__ import annotations
from schemas.state import ExtractionState
from tools.file_reader import read_file


async def source_node(state: ExtractionState) -> dict:
    source_type = state.get("source_type", "file")
    source_path = state.get("source_path", "")

    if source_type == "file":
        result = await read_file(source_path)
        return {"raw_text": result["text"]}

    elif source_type == "url":
        from tools.scraper_tool import scrape_novel_url
        result = await scrape_novel_url(source_path)
        if result["fetch_mode"] == "partial" and not result["full_text"]:
            return {
                "raw_text": "",
                "error": f"URL 爬取失败：{result['partial_reason']}",
            }
        return {"raw_text": result["full_text"]}

    elif source_type == "library":
        # 暂不支持直接从骨骼库读取原文（骨骼库只存结构数据，不存原文）
        return {
            "raw_text": "",
            "error": "library 来源暂不支持，请使用 file 或 url 来源。",
        }

    return {"raw_text": "", "error": f"未知来源类型: {source_type}"}
