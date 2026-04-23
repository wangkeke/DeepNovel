"""
日志配置
- 只保留 deepnovel.* 的日志（INFO 及以上）
- 屏蔽 openai / httpx / langgraph 内部的 DEBUG 噪音
- 在 __main__.py 顶部调用 setup_logging()
"""
from __future__ import annotations
import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """
    初始化日志。

    Args:
        level: 根 logger 的级别，默认 WARNING（屏蔽第三方库的 INFO/DEBUG）
    """
    # 根 logger：强制清理已有 handler 后重新设置，避免第三方库在 import 时预先注册的
    # handler 绕过我们的级别过滤
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s - %(name)s:%(lineno)d - %(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(handler)

    # deepnovel 自身日志：INFO 及以上可见
    logging.getLogger("deepnovel").setLevel(logging.INFO)

    # 明确屏蔽高噪音库，并切断向 root 的传播
    # propagate=False 确保即使库自己加了 handler 也不会双重输出
    _noisy = (
        "openai", "openai._base_client",
        "httpx", "httpx._client",
        "httpcore",
        "langgraph", "langchain", "langchain_core",
        "langchain_openai", "langchain_anthropic",
    )
    for name in _noisy:
        lg = logging.getLogger(name)
        lg.setLevel(logging.ERROR)
        lg.propagate = False
