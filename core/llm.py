"""
LLM 调用核心
- call_llm_with_retry()  返回解析后的 JSON dict（用于所有需要结构化输出的节点）
- call_llm_text()        返回纯文本字符串（用于 write_node 等自由文本节点）
所有配置统一从 config.py 读取
"""
from __future__ import annotations
import os
import re
import json
import asyncio


def _get_client():
    """惰性创建 AsyncOpenAI 客户端，使用 config.py 中的配置"""
    from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL
    from openai import AsyncOpenAI
    return AsyncOpenAI(
        api_key=DEEPSEEK_API_KEY or os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=DEEPSEEK_BASE_URL,
    )


def _repair_json(raw: str) -> dict:
    """尝试修复 LLM 返回的不规范 JSON（5 级策略）"""
    text = raw.strip()

    # 1. 清理 markdown 代码块包裹
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # 2. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. 提取第一个完整 JSON 对象（花括号匹配）
    brace_depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if start is None:
                start = i
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0 and start is not None:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
                break

    # 4. 去除尾部逗号、行内注释后解析
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    cleaned = re.sub(r"//.*?\n", "\n", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 5. 补全被截断的括号
    if start is not None:
        truncated = text[start:]
        open_braces = truncated.count("{") - truncated.count("}")
        open_brackets = truncated.count("[") - truncated.count("]")
        if open_braces > 0 or open_brackets > 0:
            patched = truncated + ("]" * open_brackets) + ("}" * open_braces)
            try:
                return json.loads(patched)
            except json.JSONDecodeError:
                pass

    raise json.JSONDecodeError("无法修复的 JSON", text, 0)


async def call_llm_with_retry(
    system: str,
    user: str,
    max_retries: int | None = None,
    model: str | None = None,
) -> dict:
    """
    调用 LLM，期望返回 JSON，失败自动重试。

    Args:
        system:      系统 Prompt
        user:        用户 Prompt
        max_retries: 最大重试次数（默认读 config.LLM_MAX_RETRIES）
        model:       模型名称（默认读 config.LLM_MODEL）

    Returns:
        解析后的 JSON dict
    """
    from config import LLM_MAX_RETRIES, LLM_MAX_TOKENS, LLM_MODEL

    _max_retries = max_retries if max_retries is not None else LLM_MAX_RETRIES
    _model = model or LLM_MODEL
    client = _get_client()

    for attempt in range(_max_retries):
        try:
            response = await client.chat.completions.create(
                model=_model,
                max_tokens=LLM_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            raw = response.choices[0].message.content.strip()
            return _repair_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            if attempt == _max_retries - 1:
                raise ValueError(
                    f"LLM JSON 解析失败（{_max_retries} 次重试后）: {e}"
                )
            await asyncio.sleep(2**attempt)
        except Exception:
            if attempt == _max_retries - 1:
                raise
            await asyncio.sleep(2**attempt)

    return {}


async def call_llm_text(
    system: str,
    user: str,
    max_retries: int | None = None,
    model: str | None = None,
) -> str:
    """
    调用 LLM，返回纯文本字符串（不做 JSON 解析）。
    用于 write_node 等自由文本输出场景。

    Args:
        system:      系统 Prompt
        user:        用户 Prompt
        max_retries: 最大重试次数（默认读 config.LLM_MAX_RETRIES）
        model:       模型名称（默认读 config.LLM_MODEL_WRITE）

    Returns:
        清理后的纯文本字符串
    """
    from config import LLM_MAX_RETRIES, LLM_MAX_TOKENS, LLM_MODEL_WRITE

    _max_retries = max_retries if max_retries is not None else LLM_MAX_RETRIES
    _model = model or LLM_MODEL_WRITE
    client = _get_client()

    for attempt in range(_max_retries):
        try:
            response = await client.chat.completions.create(
                model=_model,
                max_tokens=LLM_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            raw = response.choices[0].message.content.strip()
            # 清理可能的 markdown 包装
            if raw.startswith("```"):
                parts = raw.split("```")
                if len(parts) >= 3:
                    raw = parts[1]
                    if raw.startswith("markdown"):
                        raw = raw[8:]
            return raw.strip()
        except Exception:
            if attempt == _max_retries - 1:
                raise
            await asyncio.sleep(2**attempt)

    return ""
