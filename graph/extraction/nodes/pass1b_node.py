from schemas.state import ExtractionState
from prompts.extraction.pass1b import PASS1B_SYSTEM, PASS1B_USER_TEMPLATE
from utils.llm import call_llm_json

async def pass1b_batch_node(state: ExtractionState) -> dict:
    idx = state.get("current_batch_index", 0)
    current_result = state.get("current_pass1a_result")
    
    if not current_result:
        return {}
        
    # 构建提取上下文以便进行类型标注
    event_path_chain_text = "\n".join(current_result.get("event_path_chain", []))
    pressure_sources_text = "\n".join(
        [f"{ps.get('who')}: {ps.get('method')} ({ps.get('why_unavoidable')})" 
         for ps in current_result.get("pressure_sources", [])]
    )
    
    user_prompt = PASS1B_USER_TEMPLATE.format(
        node_name=current_result.get("node_name", f"节点_{idx}"),
        event_path_chain_text=event_path_chain_text,
        pressure_sources_text=pressure_sources_text
    )
    
    classification_res = await call_llm_json(PASS1B_SYSTEM, user_prompt)
    
    # 丰富 current_result，把施压链与破局链加进去
    current_result["pressure_chains"] = classification_res.get("pressure_chains", [])
    current_result["resolution_chains"] = classification_res.get("resolution_chains", [])
    
    # 最后统一 append 到 batch_summaries 列表中
    # 并递增 current_batch_index
    return {
        "batch_summaries": [current_result],
        "current_batch_index": idx + 1
    }
