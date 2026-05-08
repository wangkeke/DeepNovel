"""
统一 LLM 调用工具。

优先使用调用方传入的 max_tokens，否则用环境变量 LLM_MAX_TOKENS，最后回退到 config.LLM_MAX_TOKENS。

对外提供两个函数：
  call_llm(system, user)       → str   用于 write_node（正文，纯文本）
  call_llm_json(system, user)  → dict  用于所有需要 JSON 输出的节点

底层使用 LangChain 的 ChatOpenAI / ChatAnthropic，
LangGraph 的 astream_events 可自动捕获 token 级别的流式事件，
节点代码本身无需做任何流式处理。

模型切换：只改 .env，节点代码不变。
  LLM_PROVIDER=deepseek   → ChatOpenAI（兼容 DeepSeek API）
  LLM_PROVIDER=anthropic  → ChatAnthropic
  LLM_PROVIDER=openai     → ChatOpenAI（官方 OpenAI）

若输出**开头**含 <think>…</think>，call_llm / call_llm_json 会在进入正文或 JSON 解析前自动剥除。

OpenAI 兼容接口若需要非标准体参数（如部分网关的 enable_thinking / enable_think），请设置环境变量
  LLM_OPENAI_EXTRA_BODY='{"enable_thinking": true}'
  （JSON 对象；将传入 ChatOpenAI 的 extra_body。官方 api.openai.com 不接受此类字段。）
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re

from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger("deepnovel.llm")

# 部分思考模型会在正文/JSON 前输出占位思维链，需从输出**开头**剥离
_RE_LEADING_REDACTED_THINKING = re.compile(
    r"^\s*<think>.*?</think>\s*",
    flags=re.DOTALL,
)


def _message_content_to_str(content) -> str:
    """LangChain 消息 content 可能为 str 或 content block 列表，统一为 str。"""
    if isinstance(content, list):
        return "".join(
            (b.get("text", "") if isinstance(b, dict) else str(b)) for b in content
        )
    if not isinstance(content, str):
        return str(content)
    return content


def _strip_leading_redacted_thinking(text: str) -> str:
    """
    若模型输出**开头**存在 <think>…</think>，整段剥除（可连续多块）。
    使用非贪婪匹配，含换行。
    """
    t = text
    while True:
        m = _RE_LEADING_REDACTED_THINKING.match(t)
        if not m:
            return t
        t = t[m.end() :]


def _openai_extra_body_from_env() -> dict | None:
    """
    解析 LLM_OPENAI_EXTRA_BODY 为 extra_body 字典，供 OpenAI 兼容但扩展了请求体的网关使用。
    键名以各服务商文档为准（如 enable_thinking、enable_think 等）。
    """
    raw = os.getenv("LLM_OPENAI_EXTRA_BODY", "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("LLM_OPENAI_EXTRA_BODY 不是合法 JSON，已忽略: %s", e)
        return None
    if not isinstance(obj, dict) or not obj:
        if obj is not None:
            logger.warning("LLM_OPENAI_EXTRA_BODY 须为非空 JSON 对象，已忽略")
        return None
    return obj


def _default_max_tokens() -> int:
    """优先环境变量，否则用 config"""
    env_val = os.getenv("LLM_MAX_TOKENS")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    try:
        from config import LLM_MAX_TOKENS
        return int(LLM_MAX_TOKENS)
    except ImportError:
        return 8000


def get_llm(max_tokens: int = None):
    """
    返回 LangChain LLM 实例。
    根据 LLM_PROVIDER 环境变量选择底层实现。
    """
    provider = os.getenv("LLM_PROVIDER", "deepseek").lower()
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    effective = max_tokens or _default_max_tokens()
    if max_tokens is None:
        logger.debug(f"get_llm 使用默认 max_tokens={effective}（来自 env/config）")
    else:
        logger.debug(f"get_llm 使用调用方指定 max_tokens={effective}")
    max_tokens = effective

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            max_tokens=max_tokens,
        )
    else:
        # deepseek / openai 都走 ChatOpenAI，通过 base_url 区分
        from langchain_openai import ChatOpenAI
        # 优先读 LLM_API_KEY，回退到 DEEPSEEK_API_KEY（兼容旧配置）
        api_key = (
            os.getenv("LLM_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY", "")
        )
        base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/beta")
        extra = _openai_extra_body_from_env()
        kwargs: dict = {
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "max_tokens": max_tokens,
        }
        if extra is not None:
            kwargs["extra_body"] = extra
        return ChatOpenAI(**kwargs)


async def call_llm(system: str, user: str, retries: int = 3, max_tokens: int | None = None) -> str:
    """
    调用 LLM，返回原始文本字符串。

    适用场景：write_node（正文写作），输出是纯文本不是 JSON。
    max_tokens：可限制输出长度，write_node 用于控制字数上限。
    """
    llm = get_llm(max_tokens=max_tokens)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    for attempt in range(retries):
        try:
            response = await llm.ainvoke(messages)
            return _strip_leading_redacted_thinking(_message_content_to_str(response.content))
        except Exception as e:
            logger.warning(f"call_llm 第 {attempt + 1} 次失败: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)

    return ""


async def call_llm_json(
    system: str, user: str, retries: int = 3, max_tokens: int | None = None,
) -> dict | list:
    """
    调用 LLM，解析并返回 JSON（顶层 **对象** 或 **数组**）。

    适用场景：所有需要结构化输出的节点（pass1a/1b、expand1/2、
              bible_update、consistency、path_gen、synopsis、分卷规划数组等）。
    自动清理 markdown 代码块包装（```json ... ```）。
    失败时指数退避重试；支持 json_repair；数组与对象均支持。
    """
    effective_tokens = max_tokens or _default_max_tokens()
    logger.debug(f"call_llm_json max_tokens={effective_tokens} (传入={max_tokens})")
    llm = get_llm(max_tokens=effective_tokens)
    messages = [SystemMessage(content=system), HumanMessage(content=user)]

    last_err: Exception | None = None
    raw = ""
    for attempt in range(retries):
        try:
            response = await llm.ainvoke(messages)
            raw = _message_content_to_str(response.content)
            return _parse_json(raw)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            # 截断或解析失败时输出诊断信息
            usage_info = ""
            try:
                um = getattr(response, "usage_metadata", None) if "response" in dir() else None
                if um and isinstance(um, dict):
                    out_tok = um.get("output_tokens") or um.get("outputTokens")
                    if out_tok is not None:
                        usage_info = f", 实际 output_tokens≈{out_tok}"
            except Exception:
                pass
            logger.warning(
                f"call_llm_json JSON 解析失败（第 {attempt + 1} 次）: {e}\n"
                f"  [诊断] 输出长度={len(raw)} 字符, max_tokens={effective_tokens}{usage_info}"
            )
            if attempt == retries - 1:
                raise ValueError(
                    f"LLM JSON 解析失败（{retries} 次重试后）: {e}\n"
                    f"原始输出（前500字）:\n{locals().get('raw', '')[:500]}"
                )
            await asyncio.sleep(2 ** attempt)
        except Exception as e:
            last_err = e
            logger.warning(f"call_llm_json 调用失败（第 {attempt + 1} 次）: {e}")
            if attempt == retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)

    return {}


def _strip_markdown_json_fence(text: str) -> str:
    """去掉 ```json / ``` 围栏（含末行仅含围栏的情况）。"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    inner = lines[1:]
    while inner:
        last_stripped = inner[-1].strip()
        if last_stripped == "```" or last_stripped.startswith("```"):
            inner = inner[:-1]
            continue
        if last_stripped == "":
            inner = inner[:-1]
            continue
        break
    return "\n".join(inner).strip()


def _strip_control_chars(text: str) -> str:
    """移除会导致 json.loads 失败的控制字符（保留 \n \r \t）"""
    return "".join(
        ch for ch in text
        if ch in ("\n", "\r", "\t") or (ord(ch) >= 0x20 and ord(ch) != 0x7F)
    )


def _try_parse_json_string(text: str) -> dict | list | None:
    """对单段字符串尝试 json.loads / 去控制字符 / json_repair。成功返回 dict 或 list。"""
    if not text or not text.strip():
        return None
    for cand in (text.strip(), _strip_control_chars(text)):
        if not cand:
            continue
        try:
            out = json.loads(cand)
            if isinstance(out, (dict, list)):
                return out
        except json.JSONDecodeError:
            continue
    try:
        import json_repair  # type: ignore

        cand = _strip_control_chars(text.strip())
        out = json_repair.loads(cand)
        if isinstance(out, (dict, list)):
            return out
    except (ImportError, Exception):
        pass
    return None


def _parse_json(raw: str | list) -> dict | list:
    """
    解析 LLM 输出为 JSON 对象或数组。
    原实现仅支持顶层对象，且误把数组裁成 `{...},{...}` 导致解析失败；
    另：json_repair 成功后若为 list 曾被丢弃。
    """
    if isinstance(raw, list):
        raw = "".join(str(x) for x in raw)
    text = str(raw).strip().lstrip("\ufeff")
    text = _strip_leading_redacted_thinking(text)
    if not text:
        raise ValueError("LLM 返回空字符串")

    text = _strip_markdown_json_fence(text)

    parsed = _try_parse_json_string(text)
    if parsed is not None:
        return parsed

    # 前导说明文字：从第一个 '[' 或 '{' 起截取到匹配的末尾括号（粗粒度）
    stripped = text.lstrip()
    for opener, closer in (("[", "]"), ("{", "}")):
        start = stripped.find(opener)
        if start == -1:
            continue
        end = stripped.rfind(closer)
        if end == -1 or end <= start:
            continue
        sub = stripped[start : end + 1]
        parsed = _try_parse_json_string(sub)
        if parsed is not None:
            return parsed

    tail = text[-120:] if len(text) > 120 else text
    if stripped.startswith("["):
        raise ValueError(
            "JSON 数组解析失败或输出被截断（可适当增大 max_tokens；并避免在 JSON 外包裹说明）。"
            f" 末尾片段：{tail!r}"
        )
    if stripped.startswith("{"):
        raise ValueError(
            "JSON 对象解析失败或输出被截断（可适当增大 max_tokens）。"
            f" 末尾片段：{tail!r}"
        )
    raise ValueError(
        "无法从模型输出中解析 JSON（未以 [ 或 { 开头）。"
        f" 开头片段：{text[:120]!r}"
    )
