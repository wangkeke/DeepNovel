from langgraph.graph import StateGraph, END, START
from schemas.state import ExtractionState
from memory.checkpointer import get_checkpointer
from graph.extraction.nodes.source_node import source_node
from graph.extraction.nodes.segmenter_node import segmenter_node
from graph.extraction.nodes.pass1a_node import pass1a_batch_node
from graph.extraction.nodes.pass1b_node import pass1b_batch_node
from graph.extraction.nodes.truth_node import truth_node
from graph.extraction.nodes.pass2_node import pass2_batch_node
from graph.extraction.nodes.pass3_node import pass3_node
from graph.extraction.nodes.blueprint_save_node import blueprint_save_node

def check_pass1_done(state: ExtractionState) -> str:
    if state["current_batch_index"] >= state["total_segments"]:
        return "done"
    return "continue"

def check_pass2_done(state: ExtractionState) -> str:
    if state.get("pass2_batch_index", 0) >= state["total_segments"]:
        return "done"
    return "continue"

async def build_extraction_graph(db_path: str = "workspace/blueprints.db"):
    """构建 Phase 2 完整提取流图"""
    builder = StateGraph(ExtractionState)

    # 添加节点
    builder.add_node("source", source_node)
    builder.add_node("segmenter", segmenter_node)
    builder.add_node("pass1a", pass1a_batch_node)
    builder.add_node("pass1b", pass1b_batch_node)
    builder.add_node("truth", truth_node)
    builder.add_node("pass2", pass2_batch_node)
    builder.add_node("pass3", pass3_node)
    builder.add_node("save", blueprint_save_node)

    # 边定义
    builder.add_edge(START, "source")
    builder.add_edge("source", "segmenter")
    builder.add_edge("segmenter", "pass1a")
    builder.add_edge("pass1a", "pass1b")
    
    # 条件路由
    builder.add_conditional_edges(
        "pass1b",
        check_pass1_done,
        {"continue": "pass1a", "done": "truth"}
    )
    
    builder.add_edge("truth", "pass2")
    
    builder.add_conditional_edges(
        "pass2",
        check_pass2_done,
        {"continue": "pass2", "done": "pass3"}
    )
    
    builder.add_edge("pass3", "save")
    builder.add_edge("save", END)

    # 挂载 Checkpointer
    checkpointer = await get_checkpointer(db_path)
    graph = builder.compile(checkpointer=checkpointer)
    return graph
