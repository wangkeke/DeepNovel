"""
OCR 工具：使用 RapidOCR 识别图片文本
支持格式：jpg/jpeg/png/bmp/tiff/webp
使用 asyncio.to_thread 包装同步调用，避免阻塞事件循环
"""
from __future__ import annotations
import asyncio
from pathlib import Path


def _ocr_sync(image_path: str) -> dict:
    """同步执行 OCR，在线程池中调用"""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        raise ImportError(
            "rapidocr-onnxruntime 未安装，请执行: uv add rapidocr-onnxruntime"
        )

    ocr = RapidOCR()
    result, elapse = ocr(image_path)

    if not result:
        return {"text": "", "confidence": 0.0, "line_count": 0}

    lines = []
    total_conf = 0.0
    for item in result:
        # item 格式：[坐标框, 文本, 置信度]
        text_content = item[1] if len(item) > 1 else ""
        confidence = item[2] if len(item) > 2 else 0.0
        if text_content:
            lines.append(text_content)
            total_conf += confidence

    avg_conf = total_conf / len(lines) if lines else 0.0
    full_text = "\n".join(lines)

    return {
        "text": full_text,
        "confidence": round(avg_conf, 4),
        "line_count": len(lines),
    }


async def ocr_image(image_path: str) -> dict:
    """
    异步 OCR 接口

    Args:
        image_path: 图片文件路径（支持 jpg/png/bmp/tiff/webp）

    Returns:
        {
          "text": str,        # 识别出的文本（换行分隔）
          "confidence": float, # 平均置信度 [0, 1]
          "line_count": int   # 识别到的文本行数
        }

    Raises:
        FileNotFoundError: 图片文件不存在
        ValueError: 不支持的文件格式
    """
    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"图片文件不存在: {image_path}")

    supported = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
    if path.suffix.lower() not in supported:
        raise ValueError(
            f"不支持的图片格式: {path.suffix}，支持格式：{', '.join(supported)}"
        )

    return await asyncio.to_thread(_ocr_sync, str(path))
