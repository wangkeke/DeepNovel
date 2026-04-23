"""章节正文给 LLM 时的摘录：优先全文，过长则保留头尾以免漏掉章末高潮/收束。"""
from __future__ import annotations


def excerpt_head_tail(
    text: str,
    *,
    head_chars: int,
    tail_chars: int,
    min_gap: int = 80,
) -> str:
    """
    head_chars / tail_chars：中文字符尺度下的截段长度（与用户习惯一致）。
    若全文不长于 head+tail+min_gap，返回全文，不截断。
    """
    t = (text or "").strip()
    if not t:
        return ""
    limit = head_chars + tail_chars + min_gap
    if len(t) <= limit:
        return t
    return (
        f"{t[:head_chars]}\n\n"
        f"……（中略：正文共 {len(t)} 字；以下为收束段）……\n\n"
        f"{t[-tail_chars:]}"
    )
