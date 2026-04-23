import json
from schemas.state import ExtractionState
from prompts.extraction.truth import TRUTH_SYSTEM, TRUTH_USER_TEMPLATE
from utils.llm import call_llm_json

async def truth_node(state: ExtractionState) -> dict:
    summaries = state.get("batch_summaries", [])
    if not summaries:
        return {"truth_manifest": {}}
        
    all_batch_summaries_str = json.dumps(summaries, ensure_ascii=False, indent=2)
    is_fragment = str(state.get("is_fragment", False)).lower()
    
    user_prompt = TRUTH_USER_TEMPLATE.format(
        all_batch_summaries=all_batch_summaries_str,
        is_fragment=is_fragment
    )
    
    result = await call_llm_json(TRUTH_SYSTEM, user_prompt)
    
    return {
        "truth_manifest": result
    }
