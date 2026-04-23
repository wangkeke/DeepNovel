import json
from schemas.state import ExtractionState
from prompts.extraction.pass2 import PASS2_SYSTEM, PASS2_USER_TEMPLATE
from utils.llm import call_llm_json

async def pass2_batch_node(state: ExtractionState) -> dict:
    idx = state.get("pass2_batch_index", 0)
    segments = state.get("segments", [])
    
    if idx >= len(segments):
        return {}
        
    current_segment = segments[idx]
    truth_manifest = state.get("truth_manifest", {})
    is_fragment = str(state.get("is_fragment", False)).lower()
    
    truth_manifest_text = json.dumps(truth_manifest, ensure_ascii=False, indent=2)
    
    user_prompt = PASS2_USER_TEMPLATE.format(
        truth_manifest_text=truth_manifest_text,
        batch_index=idx,
        text=current_segment["text"],
        is_fragment=is_fragment
    )
    
    result = await call_llm_json(PASS2_SYSTEM, user_prompt)
    
    foreshadows_found = result.get("foreshadows_found", [])
    foreshadows_collected = result.get("foreshadows_collected", [])
    
    new_entries = []
    if foreshadows_found or foreshadows_collected:
        new_entries.append({
            "batch_index": idx,
            "foreshadows_found": foreshadows_found,
            "foreshadows_collected": foreshadows_collected
        })
    
    return {
        "foreshadow_entries": new_entries,
        "pass2_batch_index": idx + 1
    }
