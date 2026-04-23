import json
from schemas.state import ExtractionState
from prompts.extraction.pass3 import PASS3_SYSTEM, PASS3_USER_TEMPLATE
from schemas.blueprint import NovelBlueprint, PASS3_OUTPUT_SCHEMA, NodeConnection
from utils.llm import call_llm_json

async def pass3_node(state: ExtractionState) -> dict:
    summaries = state.get("batch_summaries", [])
    registry_dict = state.get("entity_registry", {})
    foreshadow_entries = state.get("foreshadow_entries", [])
    
    all_batch_summaries_condensed = json.dumps(summaries, ensure_ascii=False, indent=2)
    foreshadow_map_summary = json.dumps(foreshadow_entries, ensure_ascii=False, indent=2)
    entity_registry_summary = json.dumps(registry_dict, ensure_ascii=False, indent=2)
    
    user_prompt = PASS3_USER_TEMPLATE.format(
        all_batch_summaries_condensed=all_batch_summaries_condensed,
        foreshadow_map_summary=foreshadow_map_summary,
        entity_registry_summary=entity_registry_summary,
        pass3_output_schema_json=json.dumps(PASS3_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
    )
    
    result = await call_llm_json(PASS3_SYSTEM, user_prompt)
    
    blueprint = NovelBlueprint(
        source_title=state.get("source_path", "unknown"),
        genre_tags=result.get("genre_tags", []),
        source_type=state.get("source_type", "unknown"),
        world_rule_type=result.get("world_rule_type", "realistic"),
        conflict_scale=result.get("conflict_scale", "personal"),
        protagonist_power=result.get("protagonist_power", "weak"),
        is_fragment=state.get("is_fragment", False)
    )
    
    l1 = result.get("layer1", {})
    for k, v in l1.items():
        if hasattr(blueprint.layer1, k):
            setattr(blueprint.layer1, k, v)
            
    l2 = result.get("layer2", {})
    for k, v in l2.items():
        if hasattr(blueprint.layer2, k):
            setattr(blueprint.layer2, k, v)
            
    l3 = result.get("layer3", {})
    blueprint.layer3.chain_type_sequence = l3.get("chain_type_sequence", [])
    
    for conn in l3.get("node_connections", []):
        blueprint.layer3.node_connections.append(NodeConnection(**conn))
        
    result_blueprint = blueprint.model_dump()
    result_blueprint["layer3"]["nodes"] = summaries
    result_blueprint["layer3"]["foreshadow_map"] = foreshadow_entries
    
    return {
        "blueprint": result_blueprint,
        "extraction_complete": True
    }
