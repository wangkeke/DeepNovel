import json
from schemas.state import ExtractionState
from schemas.entity import EntityRegistry, EntityRecord
from schemas.blueprint import PASS1A_OUTPUT_SCHEMA
from prompts.extraction.pass1a import PASS1A_SYSTEM, PASS1A_USER_TEMPLATE
from utils.llm import call_llm_json

async def pass1a_batch_node(state: ExtractionState) -> dict:
    idx = state.get("current_batch_index", 0)
    segments = state.get("segments", [])
    if idx >= len(segments):
        return {}
        
    current_segment = segments[idx]
    
    # 准备上下文
    context = state.get("pass1_context", {})
    if not context:
        continuation_context_str = "无（首批次）"
    else:
        continuation_context_str = json.dumps(context, ensure_ascii=False)
        
    registry_dict = state.get("entity_registry", {})
    if not registry_dict.get("entities"):
        entity_registry_summary_str = "空（首批次）"
    else:
        # 只传标准名和别名，不要全量丢进去占 token
        summary = []
        for e in registry_dict.get("entities", []):
            summary.append(f"{e.get('standard_name')} ({e.get('entity_type')}): aliases={e.get('aliases', [])}")
        entity_registry_summary_str = "\n".join(summary)
        
    user_prompt = PASS1A_USER_TEMPLATE.format(
        batch_index=idx,
        char_count=current_segment["char_count"],
        text=current_segment["text"],
        continuation_context=continuation_context_str,
        entity_registry_summary=entity_registry_summary_str,
        output_schema_json=json.dumps(PASS1A_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
    )
    
    result = await call_llm_json(PASS1A_SYSTEM, user_prompt)
    
    # 更新上下游 Context
    new_context = result.get("continuation_context", {})
    
    # 处理实体更新，合并到 registry_dict
    registry = EntityRegistry.model_validate(registry_dict)
    
    # 新增实体
    for n_e in result.get("new_entities", []):
        existing = registry.find_by_name(n_e.get("standard_name"))
        if not existing:
            new_record = EntityRecord(
                standard_name=n_e.get("standard_name"),
                entity_type=n_e.get("entity_type", "character"),
                aliases=n_e.get("aliases", []),
                role_tags=n_e.get("role_tags", []),
                first_appeared_batch=idx
            )
            registry.entities.append(new_record)
            
    # 更新别名
    for u_e in result.get("updated_aliases", []):
        target = registry.find_by_name(u_e.get("entity_id_or_standard_name", ""))
        if target:
            new_alias = u_e.get("new_alias")
            if new_alias and new_alias not in target.aliases and new_alias != target.standard_name:
                target.aliases.append(new_alias)
                
    # 返回本次汇总数据到 Annotated List (Batch Summaries)
    summary_record = {
        "batch_index": idx,
        "node_name": result.get("node_name", f"节点_{idx}"),
        "event_path_chain": result.get("event_path_chain", []),
        "pressure_sources": result.get("pressure_sources", []),
        "protagonist_constraint": result.get("protagonist_constraint", ""),
        "turning_event": result.get("turning_event", ""),
        "input_state": result.get("input_state", ""),
        "output_state": result.get("output_state", "")
    }

    return {
        "pass1_context": new_context,
        "entity_registry": registry.model_dump(),
        "current_pass1a_result": summary_record
    }
