"""全局配置文件"""
from __future__ import annotations
import os
import logging
from pathlib import Path

# 自动加载项目根目录下的 .env 文件
# 必须在所有 os.environ.get() 之前执行
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv 未安装时跳过，依赖系统环境变量

# ─── 项目路径 ────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
WORKSPACE_DIR = ROOT_DIR / "workspace"
NOVELS_DIR = WORKSPACE_DIR / "novels"
DB_PATH = WORKSPACE_DIR / "blueprints.db"

# 确保目录存在
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
NOVELS_DIR.mkdir(parents=True, exist_ok=True)

# ─── LLM 配置 ────────────────────────────────────────────────────────────────
# 供旧代码（core/llm.py）向后兼容使用
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/beta"
LLM_MODEL = "deepseek-chat"
LLM_MODEL_WRITE = "deepseek-chat"
LLM_MAX_TOKENS: int = int(os.environ.get("LLM_MAX_TOKENS", "8000"))
LLM_MAX_RETRIES: int = int(os.environ.get("LLM_MAX_RETRIES", "3"))

# ─── utils/llm.py 使用的统一 LLM 环境变量 ────────────────────────────────────
# 切换模型只需修改 .env，节点代码不变
#
# 用法示例（.env）：
#   LLM_PROVIDER=deepseek
#   LLM_MODEL=deepseek-chat
#   LLM_API_KEY=sk-...           # 若未设置则回退到 DEEPSEEK_API_KEY
#   LLM_BASE_URL=https://api.deepseek.com      # 标准 API，max_tokens 上限 4K
#   LLM_BASE_URL=https://api.deepseek.com/beta # Beta API，max_tokens 可达 8K（默认）
#   LLM_MAX_TOKENS=4000
#   # 仅 OpenAI 兼容 Chat 接口：把网关扩展参数放进 extra_body（官方 OpenAI 不支持）
#   # LLM_OPENAI_EXTRA_BODY={"enable_thinking": true}
#
# 切换到 Anthropic：
#   LLM_PROVIDER=anthropic
#   LLM_MODEL=claude-sonnet-4-20250514
#   ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "deepseek")   # deepseek | openai | anthropic
LLM_API_KEY = (
    os.environ.get("LLM_API_KEY")
    or os.environ.get("DEEPSEEK_API_KEY", "")
)
# 默认用 Beta API 以支持 8K max_tokens；标准 API 仅支持 4K
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/beta")

# ─── 切分配置 ────────────────────────────────────────────────────────────────
SEGMENT_TARGET_CHARS = 5000     # 目标每段字数
SEGMENT_MIN_CHARS = 2000        # 合并阈值：小于此值则并入前段
SEGMENT_MAX_CHARS = 20000       # 拆分阈值：大于此值则强制拆分

# ─── 爬虫配置 ────────────────────────────────────────────────────────────────
SCRAPER_DELAY_MIN = 1.5         # 请求间最小延迟（秒）
SCRAPER_DELAY_MAX = 3.0         # 请求间最大延迟（秒）
SCRAPER_MAX_RETRIES = 3
SCRAPER_RETRY_BACKOFF = 2       # 退避基数（指数退避）
SCRAPER_MAX_CHAPTERS = 500      # 单次爬取最大章节数

# ─── 批次节点数范围 ──────────────────────────────────────────────────────────
# path_gen_node 用于告知 LLM 每批应规划多少个节点（开放范围，模型根据弧度完整性决定具体数量）
# 使用 DeepSeek Beta API 时 max_tokens 可达 8K，默认 6-12 节点可放下
BATCH_NODE_COUNT_MIN: int = int(os.environ.get("BATCH_NODE_COUNT_MIN", "6"))
BATCH_NODE_COUNT_MAX: int = int(os.environ.get("BATCH_NODE_COUNT_MAX", "12"))

# ─── 骨骼兼容性评分 ──────────────────────────────────────────────────────────
# 评分矩阵（满分100），用于 blueprint_load_node 中判断骨骼是否适合当前创作需求
COMPATIBILITY_RULES = {
    "world_rule_type": {    # 权重 40 分
        "realistic+realistic": 40,
        "supernatural+supernatural": 40,
        "mixed+mixed": 40,
        "mixed+realistic": 30,
        "mixed+supernatural": 30,
        "realistic+supernatural": 0,
    },
    "conflict_scale": {     # 权重 30 分
        "personal+personal": 30,
        "organizational+organizational": 30,
        "world+world": 30,
        "personal+organizational": 15,
        "organizational+world": 15,
        "personal+world": 0,
    },
    "protagonist_power": {  # 权重 30 分
        "weak+weak": 30,
        "strong+strong": 30,
        "balanced+balanced": 30,
        "weak+balanced": 20,
        "strong+balanced": 20,
        "weak+strong": 10,
    },
}

# 兼容性阈值
COMPATIBILITY_HIGH = 70     # ≥70：可直接使用
COMPATIBILITY_MID = 40      # 40-70：需要设计过渡节点
# <40：不建议，提示用户选择其他骨骼

# ─── 骨骼权重描述 ────────────────────────────────────────────────────────────
def get_weight_description(weight: float) -> str:
    """根据权重值返回对应的文字描述，用于注入 Prompt"""
    if weight >= 0.7:
        return "严格参考以下骨骼结构，尽量保持与范文相同的逻辑走向"
    elif weight >= 0.4:
        return "适当参考以下骨骼结构，可以有所变化但保持整体节奏"
    else:
        return "以下骨骼仅供参考，创作优先服从故事圣经的逻辑"


def setup_logging():
    """配置日志级别，屏蔽第三方库的 DEBUG 噪音"""
    
    # 全局默认 INFO
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S"
    )
    
    # 屏蔽这些库的 DEBUG 日志
    for noisy_logger in [
        "openai._base_client",
        "openai",
        "httpx",
        "httpcore",
        "anthropic._base_client",
        "anthropic",
        "urllib3",
        "langgraph",
    ]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    
    # 只保留自己项目的日志
    logging.getLogger("deepnovel").setLevel(logging.DEBUG)