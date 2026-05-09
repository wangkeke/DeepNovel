"""
数据库初始化：读取 schema.sql 建表（幂等）
伏笔 CRUD 函数。
"""
from __future__ import annotations
import hashlib
import math
import aiosqlite
from pathlib import Path
from config import DB_PATH, ROOT_DIR

SCHEMA_PATH = ROOT_DIR / "memory" / "schema.sql"


# ──────────────────────────────────────────────────────────────────────────────
# 伏笔 CRUD
# ──────────────────────────────────────────────────────────────────────────────

async def save_foreshadow(project_id: str, entry: dict) -> None:
    """
    新增或更新一条伏笔。
    表上同时存在 PRIMARY KEY(foreshadow_id) 与 UNIQUE(project_id, surface_meaning)；
    单次 INSERT … ON CONFLICT 只能对应其中一个目标。先按 id 或 (project, surface) 删除再插入，避免重复写入抖动。
    """
    surf = entry.get("surface_meaning", "").strip()
    if not surf:
        return
    fid = str(entry.get("foreshadow_id") or "").strip()
    if not fid:
        return
    params = {
        "foreshadow_id":       fid,
        "project_id":          project_id,
        "foreshadow_type":     entry.get("foreshadow_type", "event"),
        "surface_meaning":     entry.get("surface_meaning", ""),
        "true_meaning":        entry.get("true_meaning", ""),
        "planted_at_node":     entry.get("planted_at_node", 0),
        "collected_at_node":   entry.get("collected_at_node", 0),
        "misdirect_direction": entry.get("misdirect_direction", ""),
        "mentioned_by":       entry.get("mentioned_by", ""),
        "story_potential":    entry.get("story_potential", ""),
        "mystery_type":        entry.get("mystery_type", "normal"),
        "is_backbone":        entry.get("is_backbone", 0),
        "urgency":            entry.get("urgency", "latent"),
        "mention_count":      entry.get("mention_count", 1),
        "ready_threshold":    entry.get("ready_threshold", 3),
        "is_inferred":        entry.get("is_inferred", 0),
    }
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("BEGIN IMMEDIATE")
        await conn.execute(
            """
            DELETE FROM foreshadow_entries
            WHERE foreshadow_id = ?
               OR (project_id = ? AND surface_meaning = ?)
            """,
            (fid, project_id, surf),
        )
        await conn.execute(
            """
            INSERT INTO foreshadow_entries (
                foreshadow_id, project_id, foreshadow_type,
                surface_meaning, true_meaning,
                planted_at_node, collected_at_node,
                misdirect_direction, mentioned_by,
                story_potential, mystery_type, is_backbone,
                urgency, mention_count, ready_threshold, is_inferred
            ) VALUES (
                :foreshadow_id, :project_id, :foreshadow_type,
                :surface_meaning, :true_meaning,
                :planted_at_node, :collected_at_node,
                :misdirect_direction, :mentioned_by,
                :story_potential, :mystery_type, :is_backbone,
                :urgency, :mention_count, :ready_threshold, :is_inferred
            )
            """,
            params,
        )
        await conn.commit()


async def get_pending_foreshadows(project_id: str) -> list[dict]:
    """
    获取所有待推进伏笔（urgency=ready，未回收）。
    供 path_gen_node 注入使用。
    不包含主线伏笔和持续引力型。
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT * FROM foreshadow_entries
            WHERE project_id = ?
              AND urgency = 'ready'
              AND collected_at_node = 0
              AND (is_backbone = 0 OR is_backbone IS NULL)
              AND (mystery_type != 'permanent' OR mystery_type IS NULL)
            ORDER BY mention_count DESC
            LIMIT 5
            """,
            (project_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_framework_foreshadow_seeds(project_id: str) -> list[dict]:
    """
    获取框架导入的种子伏笔（planted_at_node=0）。
    这些伏笔不会出现在 bible.planted_foreshadows，需单独注入 expand2/path_gen。
    """
    if not project_id:
        return []
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT foreshadow_id, surface_meaning, story_potential, urgency
                FROM foreshadow_entries
                WHERE project_id = ? AND planted_at_node = 0 AND collected_at_node = 0
                ORDER BY created_at
                """,
                (project_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


async def get_node_foreshadows(project_id: str, planted_at_node: int) -> list[dict]:
    """获取某节点新增的伏笔（human_review 展示用）"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT * FROM foreshadow_entries
            WHERE project_id = ? AND planted_at_node = ?
            ORDER BY created_at
            """,
            (project_id, planted_at_node),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def foreshadow_exists_by_surface(project_id: str, surface_meaning: str) -> bool:
    """检查是否已有相同 surface_meaning 的伏笔（用于去重）"""
    if not surface_meaning:
        return False
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cursor = await conn.execute(
            "SELECT 1 FROM foreshadow_entries WHERE project_id = ? AND surface_meaning = ? LIMIT 1",
            (project_id, surface_meaning),
        )
        return await cursor.fetchone() is not None


async def get_noun_foreshadows(project_id: str) -> list[dict]:
    """获取项目中所有词条型伏笔（用于 mention_count 更新）"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT * FROM foreshadow_entries
            WHERE project_id = ? AND foreshadow_type = 'noun'
            """,
            (project_id,),
        )
        rows = await cursor.fetchall()
        # 显式转为 dict，避免 sqlite3.Row 在部分环境无 .get()
        return [{k: r[k] for k in r.keys()} for r in rows]


async def update_foreshadow_mention(project_id: str, surface_meaning: str) -> str:
    """
    正文中出现已有伏笔词条时调用，mention_count +1。
    根据类型决定是否升级 urgency，返回新的 urgency。
    v2 逻辑：主线/持续引力只计数；即收型(ready)只计数；积累型按 ready_threshold 升级。
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """
            SELECT foreshadow_id, mention_count,
                   mystery_type, is_backbone,
                   urgency, ready_threshold
            FROM foreshadow_entries
            WHERE project_id = ? AND surface_meaning = ?
            """,
            (project_id, surface_meaning),
        )
        row = await cursor.fetchone()
        if not row:
            return "latent"
        # sqlite3.Row 无 .get()，显式转 dict
        r = {k: row[k] for k in row.keys()}

        is_backbone = r.get("is_backbone") or 0
        mystery_type = r.get("mystery_type") or "normal"

        # 主线伏笔或持续引力型：只计数，不升级
        if is_backbone or mystery_type == "permanent":
            await conn.execute(
                """
                UPDATE foreshadow_entries
                SET mention_count = mention_count + 1,
                    updated_at = datetime('now')
                WHERE foreshadow_id = ?
                """,
                (r["foreshadow_id"],),
            )
            await conn.commit()
            return r["urgency"] or "latent"

        # 即收型（urgency 已是 ready）：只计数
        if r["urgency"] == "ready":
            await conn.execute(
                """
                UPDATE foreshadow_entries
                SET mention_count = mention_count + 1,
                    updated_at = datetime('now')
                WHERE foreshadow_id = ?
                """,
                (r["foreshadow_id"],),
            )
            await conn.commit()
            return "ready"

        # 积累型普通伏笔：按阈值升级
        new_count = r["mention_count"] + 1
        threshold = r["ready_threshold"] or 3
        building_threshold = math.ceil(threshold * 0.6)

        new_urgency = (
            "ready" if new_count >= threshold else
            "building" if new_count >= building_threshold else
            "latent"
        )

        await conn.execute(
            """
            UPDATE foreshadow_entries
            SET mention_count = ?,
                urgency = ?,
                updated_at = datetime('now')
            WHERE foreshadow_id = ?
            """,
            (new_count, new_urgency, r["foreshadow_id"]),
        )
        await conn.commit()
        return new_urgency


async def get_advanced_foreshadows(project_id: str, draft: str) -> list[dict]:
    """
    获取本节正文中提及的已有词条型伏笔，预计算 mention_count+1 后的 urgency 变化。
    用于 human_review 展示「本节推进的已有伏笔」。
    v2：主线/持续引力不升级；即收型(ready)不变；积累型按 ready_threshold。
    """
    nouns = await get_noun_foreshadows(project_id)
    result = []
    for f in nouns:
        surf = f.get("surface_meaning", "")
        if not surf or surf not in draft:
            continue
        if f.get("is_backbone") or f.get("mystery_type") == "permanent":
            continue  # 不展示升级（只计数）
        old_u = f.get("urgency", "latent")
        if old_u == "ready":
            new_u = "ready"  # 即收型不变
        else:
            old_count = f.get("mention_count", 1)
            new_count = old_count + 1
            threshold = f.get("ready_threshold", 3)
            building_threshold = math.ceil(threshold * 0.6)
            new_u = (
                "ready" if new_count >= threshold else
                "building" if new_count >= building_threshold else
                "latent"
            )
        result.append({
            "foreshadow_id":   f.get("foreshadow_id", ""),
            "surface_meaning": surf,
            "old_urgency":     old_u,
            "new_urgency":     new_u,
        })
    return result


async def collect_foreshadow(foreshadow_id: str, collected_at_node: int) -> None:
    """标记伏笔为已回收"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """
            UPDATE foreshadow_entries
            SET collected_at_node = ?, updated_at = datetime('now')
            WHERE foreshadow_id = ?
            """,
            (collected_at_node, foreshadow_id),
        )
        await conn.commit()


async def get_story_status(project_id: str) -> dict:
    """获取故事状态面板数据，供 human_review_batch 展示。"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row

        cursor = await conn.execute(
            """
            SELECT foreshadow_id, surface_meaning, mention_count
            FROM foreshadow_entries
            WHERE project_id = ? AND mystery_type = 'permanent'
            ORDER BY created_at
            """,
            (project_id,),
        )
        permanent = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            """
            SELECT surface_meaning, mention_count
            FROM foreshadow_entries
            WHERE project_id = ? AND is_backbone = 1
              AND collected_at_node = 0
            ORDER BY planted_at_node
            """,
            (project_id,),
        )
        backbone = [dict(r) for r in await cursor.fetchall()]

        cursor = await conn.execute(
            """
            SELECT surface_meaning, urgency, mention_count
            FROM foreshadow_entries
            WHERE project_id = ?
              AND (is_backbone = 0 OR is_backbone IS NULL)
              AND (mystery_type != 'permanent' OR mystery_type IS NULL)
              AND urgency IN ('building', 'ready')
              AND collected_at_node = 0
            ORDER BY
                CASE urgency WHEN 'ready' THEN 0 ELSE 1 END,
                mention_count DESC
            """,
            (project_id,),
        )
        pending = [dict(r) for r in await cursor.fetchall()]

        return {
            "permanent": permanent,
            "backbone": backbone,
            "pending": pending,
        }


async def activate_permanent_foreshadow(foreshadow_id: str) -> None:
    """
    用户选择开始揭露某条持续引力谜题时调用。
    将 permanent 转为 normal + urgency=ready。
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """
            UPDATE foreshadow_entries
            SET mystery_type = 'normal',
                urgency = 'ready',
                updated_at = datetime('now')
            WHERE foreshadow_id = ?
            """,
            (foreshadow_id,),
        )
        await conn.commit()


async def update_foreshadow_nature(
    foreshadow_id: str,
    *,
    mystery_type: str | None = None,
    urgency: str | None = None,
    ready_threshold: int | None = None,
) -> None:
    """更新伏笔性质（human_review_write 性质确认时调用）"""
    if not any([mystery_type is not None, urgency is not None, ready_threshold is not None]):
        return
    updates: list[str] = []
    params: list = []
    if mystery_type is not None:
        updates.append("mystery_type = ?")
        params.append(mystery_type)
    if urgency is not None:
        updates.append("urgency = ?")
        params.append(urgency)
    if ready_threshold is not None:
        updates.append("ready_threshold = ?")
        params.append(ready_threshold)
    updates.append("updated_at = datetime('now')")
    params.append(foreshadow_id)
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            f"UPDATE foreshadow_entries SET {', '.join(updates)} WHERE foreshadow_id = ?",
            params,
        )
        await conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# 章节加载（续传等）
# ──────────────────────────────────────────────────────────────────────────────

async def load_chapters(project_id: str) -> list[dict]:
    """按 seq 升序加载项目的已完成章节，用于续传时注入 prev_chapter_section。"""
    if not project_id:
        return []
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT seq, node_name, content
                FROM chapters
                WHERE project_id = ?
                ORDER BY seq ASC
                """,
                (project_id,),
            )
            rows = await cursor.fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]
    except Exception:
        return []


async def load_chapters_count(project_id: str) -> int:
    """获取已完成章节数量（自动模式用）"""
    if not project_id:
        return 0
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) as cnt FROM chapters WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    except Exception:
        return 0


async def get_project_max_auto_events(project_id: str) -> int:
    """自动停笔上限（读 novel_projects.max_chapters 列，语义为 max_auto_events）。"""
    if not project_id:
        return 0
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT max_chapters FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            return int(row["max_chapters"] or 0) if row else 0
    except Exception:
        return 0


async def update_project_mode(
    project_id: str, *, auto_mode: bool = False, max_auto_events: int = 0
) -> None:
    """更新项目的创作模式；max_auto_events 持久化在 max_chapters 列。"""
    if not project_id:
        return
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            await conn.execute(
                """UPDATE novel_projects
                   SET auto_mode = ?, max_chapters = ?, updated_at = datetime('now')
                   WHERE project_id = ?""",
                (1 if auto_mode else 0, max_auto_events, project_id),
            )
            await conn.commit()
    except Exception:
        pass


async def get_entity_cards_by_names(
    project_id: str, names: list[str]
) -> list[dict]:
    """根据名字列表查询人物卡，返回 standard_name、traits_display 与心智三字段（自动审稿用）。"""
    if not names or not project_id:
        return []
    import json
    placeholders = ",".join("?" * len(names))
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                f"""
                SELECT name, data_json FROM entity_cards
                WHERE project_id = ? AND card_type = 'character' AND name IN ({placeholders})
                """,
                [project_id] + names,
            )
            rows = await cursor.fetchall()
        result = []
        for r in rows:
            data = json.loads(r["data_json"]) if r.get("data_json") else {}
            traits = data.get("traits", []) or data.get("innate_traits", [])
            if isinstance(traits, str):
                traits = [traits] if traits else []
            result.append({
                "standard_name": r["name"],
                "traits_display": traits[:5] if isinstance(traits, list) else [],
                "current_mental_state": (data.get("current_mental_state") or "").strip(),
                "mental_growth_path": (data.get("mental_growth_path") or "").strip(),
                "reverse_scale": (data.get("reverse_scale") or "").strip(),
            })
        return result
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 框架导入（volumes / user_write_rules）
# ──────────────────────────────────────────────────────────────────────────────

async def save_framework_to_project(
    project_id: str,
    synopsis: dict,
    world_setting: dict,
    volumes: list,
    write_rules: str,
    *,
    blueprint_id: str = "",
    genre_request: str = "",
    platform_style: str = "通用网文",
    protagonist_name: str = "",
) -> None:
    """将框架解析结果写入 novel_projects 表。若项目不存在则先创建。"""
    import json
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        # 确保项目行存在（框架流程可能未经过 human_review_synopsis）
        await conn.execute(
            """INSERT INTO novel_projects (project_id, blueprint_id, genre_request, synopsis_json,
               platform_style, auto_mode, max_chapters, status)
               VALUES (?, ?, ?, '{}', ?, 0, 0, 'drafting')
               ON CONFLICT(project_id) DO NOTHING""",
            (project_id, blueprint_id or "", genre_request or "", platform_style or "通用网文"),
        )
        await conn.execute(
            """UPDATE novel_projects SET
                synopsis_json      = ?,
                world_setting_json = ?,
                volumes_json       = ?,
                user_write_rules   = ?,
                protagonist_name   = ?,
                current_volume_index = 0,
                updated_at         = datetime('now')
            WHERE project_id = ?""",
            (
                json.dumps(synopsis, ensure_ascii=False),
                json.dumps(world_setting, ensure_ascii=False),
                json.dumps(volumes, ensure_ascii=False),
                write_rules or "",
                protagonist_name or "",
                project_id,
            ),
        )
        await conn.commit()


async def get_volumes(project_id: str) -> list[dict]:
    """获取小说的卷信息列表"""
    import json
    if not project_id:
        return []
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT volumes_json FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            if not row or not row[0]:
                return []
            return json.loads(row[0])
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 故事弧：全书班底 & 当前卷事件链（event_chain_json）
# ──────────────────────────────────────────────────────────────────────────────

async def save_event_chain(
    project_id: str,
    volume_index: int,
    events: list,
    *,
    chain_pos: int = 0,
) -> None:
    """保存当前卷的完整事件链与游标（单卷一份，切换卷时覆盖）。"""
    import json
    if not project_id:
        return
    payload = json.dumps(
        {
            "volume_index": volume_index,
            "events": events,
            "chain_pos": chain_pos,
        },
        ensure_ascii=False,
    )
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """
            UPDATE novel_projects
            SET event_chain_json = ?, updated_at = datetime('now')
            WHERE project_id = ?
            """,
            (payload, project_id),
        )
        await conn.commit()


async def get_event_chain_record(project_id: str) -> dict | None:
    """
    读取 event_chain_json。
    返回 {"volume_index", "events", "chain_pos"}，缺省或解析失败返回 None。
    """
    import json
    if not project_id:
        return None
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT event_chain_json FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            if not row or not row[0]:
                return None
            data = json.loads(row[0])
        if not isinstance(data, dict):
            return None
        events = data.get("events") or []
        return {
            "volume_index": int(data.get("volume_index", 0)),
            "events": events if isinstance(events, list) else [],
            "chain_pos": int(data.get("chain_pos", 0)),
        }
    except Exception:
        return None


async def update_event_chain_pos(project_id: str, chain_pos: int) -> None:
    """本批路径写完后推进事件链游标（仅改 chain_pos，不改 events）。"""
    import json
    if not project_id:
        return
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT event_chain_json FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            if not row or not row[0]:
                return
            data = json.loads(row[0])
            if not isinstance(data, dict):
                return
            data["chain_pos"] = int(chain_pos)
            await conn.execute(
                """
                UPDATE novel_projects
                SET event_chain_json = ?, updated_at = datetime('now')
                WHERE project_id = ?
                """,
                (json.dumps(data, ensure_ascii=False), project_id),
            )
            await conn.commit()
    except Exception:
        pass


async def update_project_core_cast(project_id: str, core_cast: dict) -> None:
    """保存全书核心角色班底。"""
    import json
    if not project_id:
        return
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """
            UPDATE novel_projects
            SET core_cast_json = ?, updated_at = datetime('now')
            WHERE project_id = ?
            """,
            (json.dumps(core_cast or {}, ensure_ascii=False), project_id),
        )
        await conn.commit()


async def get_core_cast(project_id: str) -> dict:
    """读取全书核心角色班底。"""
    import json
    if not project_id:
        return {}
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT core_cast_json FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            if not row or not row[0]:
                return {}
            return json.loads(row[0])
    except Exception:
        return {}


async def get_project_synopsis(project_id: str) -> dict:
    """从 DB 获取项目 synopsis（框架导入时 path_gen 回退用）"""
    import json
    if not project_id:
        return {}
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT synopsis_json FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            if not row or not row[0]:
                return {}
            return json.loads(row[0])
    except Exception:
        return {}


async def get_current_volume_index(project_id: str) -> int:
    """从 DB 获取当前卷索引（框架导入时 path_gen 使用）"""
    if not project_id:
        return 0
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT current_volume_index FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


async def update_volume_progress(
    project_id: str,
    volume_index: int,
    completed_node_count: int,
    is_completed: bool = False,
) -> None:
    """更新指定卷的完成进度，完成时切换到下一卷"""
    import json
    volumes = await get_volumes(project_id)
    if volume_index >= len(volumes):
        return
    volumes[volume_index]["completed_node_count"] = completed_node_count
    volumes[volume_index]["is_completed"] = is_completed
    next_index = volume_index + 1 if is_completed else volume_index
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """UPDATE novel_projects SET
                volumes_json = ?,
                current_volume_index = ?,
                updated_at = datetime('now')
            WHERE project_id = ?""",
            (
                json.dumps(volumes, ensure_ascii=False),
                next_index,
                project_id,
            ),
        )
        await conn.commit()


async def save_faction_card(
    project_id: str,
    name: str,
    *,
    faction_type: str = "neutral",
    description: str = "",
    core_members: list[str] | None = None,
    goals: str = "",
    stance_to_protagonist: str = "",
    appears_from_volume: int = 0,
) -> str:
    """新增或更新势力卡。返回 faction_id。"""
    import json
    try:
        from ulid import ULID
        faction_id = f"F_{ULID()}"
    except ImportError:
        import uuid
        faction_id = f"F_{uuid.uuid4().hex[:16]}"
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cursor = await conn.execute(
            "SELECT faction_id FROM faction_cards WHERE project_id = ? AND name = ?",
            (project_id, name),
        )
        row = await cursor.fetchone()
        if row:
            faction_id = row[0]
            await conn.execute(
                """UPDATE faction_cards SET
                    faction_type = ?, description = ?, core_members = ?,
                    goals = ?, stance_to_protagonist = ?, appears_from_volume = ?
                WHERE faction_id = ?""",
                (
                    faction_type,
                    description,
                    json.dumps(core_members or [], ensure_ascii=False),
                    goals,
                    stance_to_protagonist,
                    appears_from_volume,
                    faction_id,
                ),
            )
        else:
            await conn.execute(
                """INSERT INTO faction_cards
                    (faction_id, project_id, name, faction_type, description,
                     core_members, goals, stance_to_protagonist, appears_from_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    faction_id,
                    project_id,
                    name,
                    faction_type,
                    description,
                    json.dumps(core_members or [], ensure_ascii=False),
                    goals,
                    stance_to_protagonist,
                    appears_from_volume,
                ),
            )
        await conn.commit()
    return faction_id


async def get_faction_cards_for_volume(
    project_id: str,
    current_volume_index: int,
) -> list[dict]:
    """获取当前卷及之前已出场的势力卡片。"""
    if not project_id:
        return []
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """SELECT faction_id, name, faction_type, description,
                          core_members, goals, stance_to_protagonist
                   FROM faction_cards
                   WHERE project_id = ? AND appears_from_volume <= ?""",
                (project_id, current_volume_index),
            )
            rows = await cursor.fetchall()
        import json
        result = []
        for r in rows:
            result.append({
                "faction_id": r["faction_id"],
                "name": r["name"],
                "faction_type": r["faction_type"],
                "description": r["description"] or "",
                "core_members": json.loads(r["core_members"]) if r["core_members"] else [],
                "goals": r["goals"] or "",
                "stance_to_protagonist": r["stance_to_protagonist"] or "",
            })
        return result
    except Exception:
        return []


async def get_faction_cards_by_names(
    project_id: str,
    names: list[str],
    current_volume_index: int = 0,
) -> list[dict]:
    """按势力名列表获取势力卡，仅返回当前卷已出场的。"""
    if not names or not project_id:
        return []
    all_factions = await get_faction_cards_for_volume(project_id, current_volume_index)
    name_set = set(n.strip() for n in names if n.strip())
    return [f for f in all_factions if f.get("name") in name_set]


async def get_available_character_names_for_volume(
    project_id: str,
    current_volume_index: int,
) -> set[str]:
    """获取当前卷已出场的配角名（主角始终包含）。用于 expand1 过滤浮动配角。"""
    if not project_id:
        return set()
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                """SELECT name FROM entity_cards
                   WHERE project_id = ? AND card_type = 'character'
                     AND (appears_from_volume IS NULL OR appears_from_volume <= ?)""",
                (project_id, current_volume_index),
            )
            rows = await cursor.fetchall()
        return {r[0] for r in rows}
    except Exception:
        return set()


# ──────────────────────────────────────────────────────────────────────────────
# 世界词条库 CRUD（World Lexicon — 补丁 C）
# ──────────────────────────────────────────────────────────────────────────────

import json as _json


async def upsert_lexicon_entry(project_id: str, entry: dict) -> None:
    """
    新增或更新一条世界词条。
    - action="new"：首次写入，static_profile 完整写入，dynamic_associations 初始化
    - action="update_static"：追加静态属性（只追加不覆盖）
    - action="update_dynamic"：追加动态关联，将旧 is_active=true 改为 false
    """
    term = (entry.get("term") or "").strip()
    if not term or not project_id:
        return

    # 主键 (lexicon_id, project_id) 必须稳定且按 term 唯一；勿采用 LLM 给的 lexicon_id，易与
    # 前缀截断或其它词条撞车导致 UNIQUE(lexicon_id, project_id) 失败。
    h = hashlib.sha256(f"{project_id}\0{term}".encode("utf-8")).hexdigest()[:24]
    lexicon_id = f"LEX_{h}"
    term_type   = (entry.get("term_type") or "A").strip()
    category    = (entry.get("category") or "其他").strip()
    action      = (entry.get("action") or "new").strip()

    new_static_profile     = entry.get("static_profile") or {}
    new_dynamic_assoc      = entry.get("dynamic_association") or {}
    incomplete_clue        = entry.get("incomplete_clue") or {}
    first_appearance       = entry.get("first_appearance") or {}

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row

        # 查询是否已存在
        cursor = await conn.execute(
            "SELECT static_profile_json, dynamic_associations_json, lexicon_id "
            "FROM world_lexicon WHERE project_id=? AND term=?",
            (project_id, term),
        )
        row = await cursor.fetchone()

        if row is None or action == "new":
            # 新增
            dyn_list = [new_dynamic_assoc] if new_dynamic_assoc else []
            await conn.execute(
                """
                INSERT INTO world_lexicon
                  (lexicon_id, project_id, term, term_type, category,
                   static_profile_json, dynamic_associations_json,
                   incomplete_clue_json, first_appearance_json)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(project_id, term) DO UPDATE SET
                  lexicon_id                = excluded.lexicon_id,
                  term_type               = excluded.term_type,
                  category                = excluded.category,
                  static_profile_json     = excluded.static_profile_json,
                  dynamic_associations_json = excluded.dynamic_associations_json,
                  incomplete_clue_json    = excluded.incomplete_clue_json,
                  updated_at              = datetime('now')
                """,
                (
                    lexicon_id, project_id, term, term_type, category,
                    _json.dumps(new_static_profile, ensure_ascii=False),
                    _json.dumps(dyn_list, ensure_ascii=False),
                    _json.dumps(incomplete_clue, ensure_ascii=False),
                    _json.dumps(first_appearance, ensure_ascii=False),
                ),
            )

        elif action == "update_static":
            # 追加静态属性
            try:
                existing_static = _json.loads(row["static_profile_json"] or "{}")
            except (TypeError, ValueError):
                existing_static = {}
            merged = dict(existing_static)
            if isinstance(new_static_profile, dict):
                # 追加 inherent_attributes 和 hard_constraints
                for list_key in ("inherent_attributes", "hard_constraints"):
                    existing_list = list(merged.get(list_key) or [])
                    new_list = new_static_profile.get(list_key) or []
                    for item in new_list:
                        if item and item not in existing_list:
                            existing_list.append(item)
                    merged[list_key] = existing_list
                # 若 definition 为空则补充
                if not merged.get("definition") and new_static_profile.get("definition"):
                    merged["definition"] = new_static_profile["definition"]
            await conn.execute(
                "UPDATE world_lexicon SET static_profile_json=?, updated_at=datetime('now') "
                "WHERE project_id=? AND term=?",
                (_json.dumps(merged, ensure_ascii=False), project_id, term),
            )

        elif action == "update_dynamic":
            # 将旧 is_active 置为 false，追加新关联
            try:
                dyn_list = _json.loads(row["dynamic_associations_json"] or "[]")
            except (TypeError, ValueError):
                dyn_list = []
            if not isinstance(dyn_list, list):
                dyn_list = []
            for d in dyn_list:
                if isinstance(d, dict):
                    d["is_active"] = False
            if new_dynamic_assoc:
                dyn_list.append({**new_dynamic_assoc, "is_active": True})
            await conn.execute(
                "UPDATE world_lexicon SET dynamic_associations_json=?, updated_at=datetime('now') "
                "WHERE project_id=? AND term=?",
                (_json.dumps(dyn_list, ensure_ascii=False), project_id, term),
            )

        await conn.commit()


async def get_active_lexicon_entries(
    project_id: str,
    priority_types: list[str] | None = None,
    limit: int = 30,
) -> list[dict]:
    """
    读取世界词条库中有 active 动态关联的词条，按优先级排序：
    priority_types 示例：["C", "B", "A"]（对应补丁 C 文档中的三级优先）
    """
    if not project_id:
        return []
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """SELECT lexicon_id, term, term_type, category,
                          static_profile_json, dynamic_associations_json,
                          incomplete_clue_json
                   FROM world_lexicon
                   WHERE project_id=?
                   ORDER BY CASE term_type WHEN 'C' THEN 1 WHEN 'B' THEN 2 ELSE 3 END, updated_at DESC
                   LIMIT ?""",
                (project_id, limit),
            )
            rows = await cursor.fetchall()
    except Exception:
        return []

    results = []
    for row in rows:
        try:
            dyn_list = _json.loads(row["dynamic_associations_json"] or "[]")
        except (TypeError, ValueError):
            dyn_list = []
        has_active = any(
            isinstance(d, dict) and d.get("is_active", False)
            for d in (dyn_list or [])
        )
        if not has_active and row["term_type"] != "C":
            continue
        try:
            static_p = _json.loads(row["static_profile_json"] or "{}")
        except (TypeError, ValueError):
            static_p = {}
        try:
            clue = _json.loads(row["incomplete_clue_json"] or "{}")
        except (TypeError, ValueError):
            clue = {}
        results.append({
            "lexicon_id":     row["lexicon_id"],
            "term":           row["term"],
            "term_type":      row["term_type"],
            "category":       row["category"],
            "static_profile": static_p,
            "dynamic_associations": dyn_list,
            "incomplete_clue": clue,
            "has_active":     has_active,
        })
        if priority_types:
            pass  # 已经通过 SQL ORDER 处理
    return results[:limit]


async def get_lexicon_entry_by_term(project_id: str, term: str) -> dict | None:
    """按词条名精确查找一条词条。"""
    if not project_id or not term:
        return None
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT * FROM world_lexicon WHERE project_id=? AND term=?",
                (project_id, term),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return dict(row)
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 初始化
# ──────────────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    """初始化数据库，创建所有表（幂等）"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.executescript(schema)
        for col in ("protagonist_name", "last_action_intent", "platform_style"):
            try:
                await conn.execute(
                    f"ALTER TABLE novel_projects ADD COLUMN {col} TEXT"
                )
                await conn.commit()
            except Exception:
                pass  # 列已存在时忽略
        # 自动模式字段
        for col_def in [
            ("novel_projects", "auto_mode", "INTEGER DEFAULT 0"),
            ("novel_projects", "max_chapters", "INTEGER DEFAULT 0"),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}"
                )
                await conn.commit()
            except Exception:
                pass  # 列已存在时忽略
        # novel_projects 框架导入字段
        for col_def in [
            ("novel_projects", "current_volume_index", "INTEGER DEFAULT 0"),
            ("novel_projects", "user_write_rules", "TEXT DEFAULT ''"),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}"
                )
                await conn.commit()
            except Exception:
                pass  # 列已存在时忽略
        # entity_cards 框架导入字段（浮动配角、女主）
        for col_def in [
            ("entity_cards", "appears_from_volume", "INTEGER DEFAULT 0"),
            ("entity_cards", "is_female_lead", "INTEGER DEFAULT 0"),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}"
                )
                await conn.commit()
            except Exception:
                pass  # 列已存在时忽略
        # 伏笔表 v2 迁移
        for col_def in [
            ("foreshadow_entries", "mystery_type", "TEXT DEFAULT 'normal'"),
            ("foreshadow_entries", "is_backbone", "INTEGER DEFAULT 0"),
            ("foreshadow_entries", "ready_threshold", "INTEGER DEFAULT 3"),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}"
                )
                await conn.commit()
            except Exception:
                pass  # 列已存在时忽略
        # 故事弧：班底 + 当前卷事件链（JSON 内含 volume_index / events / chain_pos）
        for col_def in [
            ("novel_projects", "core_cast_json", "TEXT DEFAULT '{}'"),
            ("novel_projects", "event_chain_json", "TEXT DEFAULT '{}'"),
        ]:
            try:
                await conn.execute(
                    f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}"
                )
                await conn.commit()
            except Exception:
                pass  # 列已存在时忽略
