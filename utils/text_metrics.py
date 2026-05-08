"""正文统计：用于 UI 展示的「字数」不计标点符号（仅汉字/CJK扩展与英数字）。"""
from __future__ import annotations

import re

# 计入：中日韩统一表意、扩展A、ASCII 英数字、全角英数字；不计：标点、空白、分隔符等
_PROSE_CHARS = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff"
    r"A-Za-z0-9"
    r"\uff10-\uff19"
    r"\uff21-\uff3a"
    r"\uff41-\uff5a]"
)


def prose_char_count(text: str | None) -> int:
    """正文字符数（不含标点符号与中英文标点、空格、换行等分隔符）。"""
    if not text:
        return 0
    return len(_PROSE_CHARS.findall(text))
