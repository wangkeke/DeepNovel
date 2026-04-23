"""
骨骼库存储工具
提供：save_blueprint / load_blueprint / search_blueprints / list_blueprints
"""
from __future__ import annotations
import json
import aiosqlite
from config import DB_PATH


async def save_blueprint(blueprint: dict, registry: dict) -> bool:
    """将 NovelBlueprint 和实体注册表写入数据库"""
    blueprint_id = blueprint.get("blueprint_id")
    if not blueprint_id:
        return False

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """INSERT OR REPLACE INTO blueprints
            (blueprint_id, source_title, genre_tags, source_type, world_rule_type,
             conflict_scale, protagonist_power, layer1_json, layer2_json, layer3_json,
             is_fragment, fragment_note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                blueprint_id,
                blueprint.get("source_title", ""),
                json.dumps(blueprint.get("genre_tags", []), ensure_ascii=False),
                blueprint.get("source_type", ""),
                blueprint.get("world_rule_type", "realistic"),
                blueprint.get("conflict_scale", "personal"),
                blueprint.get("protagonist_power", "balanced"),
                json.dumps(blueprint.get("layer1", {}), ensure_ascii=False),
                json.dumps(blueprint.get("layer2", {}), ensure_ascii=False),
                json.dumps(blueprint.get("layer3", {}), ensure_ascii=False),
                int(blueprint.get("is_fragment", False)),
                blueprint.get("fragment_note", ""),
            ),
        )

        for e in registry.get("entities", []):
            await conn.execute(
                """INSERT OR REPLACE INTO entity_registry
                (entity_id, blueprint_id, standard_name, entity_type, aliases,
                 role_tags, first_batch, relations_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    e.get("entity_id", ""),
                    blueprint_id,
                    e.get("standard_name", ""),
                    e.get("entity_type", ""),
                    json.dumps(e.get("aliases", []), ensure_ascii=False),
                    json.dumps(e.get("role_tags", []), ensure_ascii=False),
                    e.get("first_appeared_batch", 0),
                    json.dumps(e.get("related_entities", []), ensure_ascii=False),
                ),
            )

        await conn.commit()
    return True


async def load_blueprint(blueprint_id: str) -> dict:
    """加载指定 ID 的骨骼档案"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM blueprints WHERE blueprint_id = ?", (blueprint_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {}
            return _row_to_blueprint(row)


async def list_blueprints() -> list[dict]:
    """列出所有骨骼（摘要信息）"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT blueprint_id, source_title, genre_tags, world_rule_type, "
            "conflict_scale, protagonist_power, is_fragment, created_at "
            "FROM blueprints ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_summary(row) for row in rows]


async def search_blueprints(
    genre: str = "",
    chain_types: list[str] | None = None,
    world_rule: str = "",
    conflict_scale: str = "",
    protagonist_power: str = "",
) -> list[dict]:
    """
    搜索骨骼库。

    Args:
        genre:           题材关键词（模糊匹配 genre_tags）
        chain_types:     逻辑链类型列表（在 layer3_json 中模糊匹配）
        world_rule:      world_rule_type 精确匹配
        conflict_scale:  conflict_scale 精确匹配
        protagonist_power: protagonist_power 精确匹配

    Returns:
        匹配的骨骼摘要列表（按 created_at 倒序）
    """
    conditions = []
    params: list = []

    if genre:
        conditions.append("genre_tags LIKE ?")
        params.append(f"%{genre}%")

    if world_rule:
        conditions.append("world_rule_type = ?")
        params.append(world_rule)

    if conflict_scale:
        conditions.append("conflict_scale = ?")
        params.append(conflict_scale)

    if protagonist_power:
        conditions.append("protagonist_power = ?")
        params.append(protagonist_power)

    if chain_types:
        for ct in chain_types:
            conditions.append("layer3_json LIKE ?")
            params.append(f"%{ct}%")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        f"SELECT blueprint_id, source_title, genre_tags, world_rule_type, "
        f"conflict_scale, protagonist_power, is_fragment, created_at "
        f"FROM blueprints {where} ORDER BY created_at DESC"
    )

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_summary(row) for row in rows]


async def load_entity_registry(blueprint_id: str) -> dict:
    """加载实体注册表"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM entity_registry WHERE blueprint_id = ?", (blueprint_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            entities = []
            for row in rows:
                entities.append({
                    "entity_id": row["entity_id"],
                    "standard_name": row["standard_name"],
                    "entity_type": row["entity_type"],
                    "aliases": json.loads(row["aliases"]) if row["aliases"] else [],
                    "role_tags": json.loads(row["role_tags"]) if row["role_tags"] else [],
                    "first_appeared_batch": row["first_batch"],
                    "related_entities": json.loads(row["relations_json"]) if row["relations_json"] else [],
                })
            return {"blueprint_id": blueprint_id, "entities": entities}


# ─── 内部辅助 ─────────────────────────────────────────────────────────────────

def _row_to_blueprint(row) -> dict:
    return {
        "blueprint_id": row["blueprint_id"],
        "source_title": row["source_title"],
        "genre_tags": json.loads(row["genre_tags"]) if row["genre_tags"] else [],
        "source_type": row["source_type"],
        "world_rule_type": row["world_rule_type"],
        "conflict_scale": row["conflict_scale"],
        "protagonist_power": row["protagonist_power"],
        "layer1": json.loads(row["layer1_json"]) if row["layer1_json"] else {},
        "layer2": json.loads(row["layer2_json"]) if row["layer2_json"] else {},
        "layer3": json.loads(row["layer3_json"]) if row["layer3_json"] else {},
        "is_fragment": bool(row["is_fragment"]),
        "fragment_note": row["fragment_note"] if "fragment_note" in row.keys() else "",
    }


def _row_to_summary(row) -> dict:
    return {
        "blueprint_id": row["blueprint_id"],
        "source_title": row["source_title"],
        "genre_tags": json.loads(row["genre_tags"]) if row["genre_tags"] else [],
        "world_rule_type": row["world_rule_type"],
        "conflict_scale": row["conflict_scale"],
        "protagonist_power": row["protagonist_power"],
        "is_fragment": bool(row["is_fragment"]),
        "created_at": row["created_at"],
    }
