"""
LangGraph Checkpointer 单例封装
使用 config.DB_PATH（绝对路径），不依赖运行时工作目录。
"""
from __future__ import annotations
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite
from config import DB_PATH

_checkpointer: AsyncSqliteSaver | None = None
_conn: aiosqlite.Connection | None = None


async def get_checkpointer(db_path: str | None = None) -> AsyncSqliteSaver:
    """
    获取全局单例 Checkpointer。
    db_path 默认使用 config.DB_PATH，传入自定义路径时使用传入值。
    """
    global _checkpointer, _conn
    if _checkpointer is None:
        _path = db_path or str(DB_PATH)
        _conn = await aiosqlite.connect(_path)
        _checkpointer = AsyncSqliteSaver(_conn)
        await _checkpointer.setup()  # 建表（幂等）
    return _checkpointer


async def close_checkpointer() -> None:
    """关闭 Checkpointer，释放数据库连接"""
    global _checkpointer, _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
        _checkpointer = None


async def run_extraction(graph, state: dict, thread_id: str):
    """运行图，携带 thread_id 实现断点续传"""
    config = {"configurable": {"thread_id": thread_id}}
    return await graph.ainvoke(state, config=config)


async def resume_extraction(graph, thread_id: str):
    """用相同 thread_id 从断点恢复"""
    config = {"configurable": {"thread_id": thread_id}}
    return await graph.ainvoke(None, config=config)
