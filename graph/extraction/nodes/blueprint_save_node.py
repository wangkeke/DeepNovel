from schemas.state import ExtractionState
from tools.blueprint_store import save_blueprint

async def blueprint_save_node(state: ExtractionState) -> dict:
    blueprint_dict = state.get("blueprint", {})
    registry_dict = state.get("entity_registry", {})
    
    if blueprint_dict:
        await save_blueprint(blueprint_dict, registry_dict)
    
    return {}
