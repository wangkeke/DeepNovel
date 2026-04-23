"""
文件读取工具
支持格式：txt / docx / pdf / 图片（jpg/png/bmp 等，调用 OCR）
"""
from __future__ import annotations
import asyncio
import os
import re
from pathlib import Path


def _read_txt(file_path: str) -> str:
    """读取 txt，自动检测编码"""
    try:
        import chardet
        with open(file_path, "rb") as f:
            raw = f.read()
        detected = chardet.detect(raw)
        encoding = detected.get("encoding") or "utf-8"
        return raw.decode(encoding, errors="replace")
    except ImportError:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def _read_docx(file_path: str) -> str:
    """读取 Word 文档"""
    try:
        from docx import Document
    except ImportError:
        raise ImportError("python-docx 未安装，请执行: uv add python-docx")
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)


def _read_pdf(file_path: str) -> str:
    """读取 PDF 文档"""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ImportError("pypdf 未安装，请执行: uv add pypdf")
    reader = PdfReader(file_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)


def _detect_chapter_hints(text: str) -> list[str]:
    """从文本中提取章节标题列表（用于提示切分器）"""
    pattern = re.compile(
        r'^第[零一二三四五六七八九十百千万\d]+[章节卷回篇部集][\s\S]*$',
        re.MULTILINE
    )
    return [m.group().strip() for m in pattern.finditer(text)][:50]


async def read_file(file_path: str) -> dict:
    """
    读取文件，返回结构化结果。

    Args:
        file_path: 文件路径

    Returns:
        {
          "text": str,
          "file_type": str,
          "char_count": int,
          "chapter_hints": list[str]
        }
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    suffix = path.suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

    if suffix == ".txt":
        text = await asyncio.to_thread(_read_txt, str(path))
        file_type = "txt"
    elif suffix == ".docx":
        text = await asyncio.to_thread(_read_docx, str(path))
        file_type = "docx"
    elif suffix == ".pdf":
        text = await asyncio.to_thread(_read_pdf, str(path))
        file_type = "pdf"
    elif suffix in image_exts:
        from tools.ocr_tool import ocr_image
        result = await ocr_image(str(path))
        return {
            "text": result["text"],
            "file_type": "image_ocr",
            "char_count": len(result["text"]),
            "chapter_hints": [],
        }
    else:
        raise ValueError(
            f"不支持的文件格式: {suffix}，"
            f"支持: .txt / .docx / .pdf / .jpg / .png / .bmp"
        )

    chapter_hints = _detect_chapter_hints(text)
    return {
        "text": text,
        "file_type": file_type,
        "char_count": len(text),
        "chapter_hints": chapter_hints,
    }


def read_file_sync(file_path: str) -> dict:
    """同步包装，兼容非 async 调用场景"""
    return asyncio.run(read_file(file_path))
