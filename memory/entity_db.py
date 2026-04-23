"""
entity_db.py — 实体知识库 CRUD 工具

提供基于 entity_cards 和 event_timeline 表的异步操作：
- 增量 upsert 实体卡片（character / location / item / faction）
- 追加事件时间线条目
- 按名字批量检索实体卡片
- 获取全部已知实体名（用于字符串匹配）
- 生成轻量 entity_summary 供 path_gen 等节点注入上下文
"""
from __future__ import annotations
import json
import aiosqlite
from config import DB_PATH


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _new_id(prefix: str = "E") -> str:
    try:
        from ulid import ULID
        return f"{prefix}_{ULID()}"
    except ImportError:
        import uuid
        return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _merge_data(existing_json: str | None, patch: dict) -> str:
    """深度合并 patch 到已有 JSON，列表字段执行追加去重，标量字段直接覆盖。"""
    base: dict = json.loads(existing_json) if existing_json else {}
    for key, val in patch.items():
        if val is None:
            continue
        if isinstance(val, list) and isinstance(base.get(key), list):
            # 列表去重追加
            seen = set(json.dumps(x, ensure_ascii=False) for x in base[key])
            for item in val:
                serialized = json.dumps(item, ensure_ascii=False)
                if serialized not in seen:
                    base[key].append(item)
                    seen.add(serialized)
        else:
            base[key] = val
    return json.dumps(base, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

async def upsert_entity_card(
    project_id: str,
    card_type: str,
    name: str,
    data_patch: dict,
    seq: int = 0,
    aliases: list[str] | None = None,
    *,
    appears_from_volume: int | None = None,
    is_female_lead: bool = False,
) -> str:
    """
    增量更新实体卡片。若不存在则创建，若已存在则深度合并 data_patch。

    参数：
        project_id  — 项目 ID
        card_type   — "character" | "location" | "item" | "faction"
        name        — 实体标准名
        data_patch  — 要更新/追加的字段（列表字段追加去重，标量覆盖）
        seq         — 当前全局节点序号
        aliases     — 别名列表（可选，会合并到已有别名）

    返回：entity_id
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cursor = await conn.execute(
            "SELECT entity_id, aliases, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = ? AND name = ?",
            (project_id, card_type, name),
        )
        row = await cursor.fetchone()

        if row:
            entity_id, existing_aliases_json, existing_data_json = row
            # 合并别名
            existing_aliases: list = json.loads(existing_aliases_json) if existing_aliases_json else []
            if aliases:
                for a in aliases:
                    if a not in existing_aliases:
                        existing_aliases.append(a)
            merged_data = _merge_data(existing_data_json, data_patch)
            # appears_from_volume / is_female_lead 可选更新
            upd_cols = ["aliases = ?", "data_json = ?", "last_updated = ?", "updated_at = datetime('now')"]
            upd_vals: list = [
                json.dumps(existing_aliases, ensure_ascii=False),
                merged_data,
                seq,
            ]
            if appears_from_volume is not None:
                upd_cols.append("appears_from_volume = ?")
                upd_vals.append(appears_from_volume)
            if is_female_lead:
                upd_cols.append("is_female_lead = 1")
            upd_vals.append(entity_id)
            await conn.execute(
                f"UPDATE entity_cards SET {', '.join(upd_cols)} WHERE entity_id = ?",
                tuple(upd_vals),
            )
        else:
            entity_id = _new_id("EC")
            app_vol = appears_from_volume if appears_from_volume is not None else 0
            fem_lead = 1 if is_female_lead else 0
            await conn.execute(
                """INSERT INTO entity_cards
                   (entity_id, project_id, card_type, name, aliases, data_json,
                    first_seen, last_updated, appears_from_volume, is_female_lead)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entity_id,
                    project_id,
                    card_type,
                    name,
                    json.dumps(aliases or [], ensure_ascii=False),
                    json.dumps(data_patch, ensure_ascii=False),
                    seq,
                    seq,
                    app_vol,
                    fem_lead,
                ),
            )
        await conn.commit()
    return entity_id


async def append_event(
    project_id: str,
    seq: int,
    description: str,
    characters: list[str] | None = None,
    locations: list[str] | None = None,
    items: list[str] | None = None,
    is_foreshadow: bool = False,
    foreshadow_id: str | None = None,
) -> str:
    """向事件时间线追加一条事件记录，返回 event_id。"""
    event_id = _new_id("EV")
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """INSERT INTO event_timeline
               (event_id, project_id, seq, description, characters, locations, items,
                is_foreshadow, foreshadow_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                project_id,
                seq,
                description,
                json.dumps(characters or [], ensure_ascii=False),
                json.dumps(locations or [], ensure_ascii=False),
                json.dumps(items or [], ensure_ascii=False),
                1 if is_foreshadow else 0,
                foreshadow_id,
            ),
        )
        await conn.commit()
    return event_id


async def get_entities_by_names(project_id: str, names: list[str]) -> list[dict]:
    """
    按名字列表批量检索实体卡片（同时检索 name 和 aliases）。
    返回去重后的卡片列表，每张卡片包含 card_type / name / aliases / data / first_seen / last_updated。
    """
    if not names:
        return []

    results: list[dict] = []
    seen_ids: set[str] = set()

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        for name in names:
            # 精确匹配 name
            cursor = await conn.execute(
                "SELECT entity_id, card_type, name, aliases, data_json, first_seen, last_updated "
                "FROM entity_cards WHERE project_id = ? AND name = ?",
                (project_id, name),
            )
            rows = await cursor.fetchall()
            # 模糊匹配 aliases（JSON 数组中包含该名字）
            cursor2 = await conn.execute(
                "SELECT entity_id, card_type, name, aliases, data_json, first_seen, last_updated "
                "FROM entity_cards WHERE project_id = ? AND aliases LIKE ?",
                (project_id, f"%{name}%"),
            )
            rows2 = await cursor2.fetchall()

            for row in list(rows) + list(rows2):
                eid = row[0]
                if eid in seen_ids:
                    continue
                seen_ids.add(eid)
                results.append({
                    "entity_id":   eid,
                    "card_type":   row[1],
                    "name":        row[2],
                    "aliases":     json.loads(row[3]) if row[3] else [],
                    "data":        json.loads(row[4]) if row[4] else {},
                    "first_seen":  row[5],
                    "last_updated": row[6],
                })
    return results


async def get_all_entity_names(project_id: str) -> list[str]:
    """
    返回项目下所有已知实体名（标准名 + 别名展开），用于字符串匹配。
    """
    names: list[str] = []
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cursor = await conn.execute(
            "SELECT name, aliases FROM entity_cards WHERE project_id = ?",
            (project_id,),
        )
        rows = await cursor.fetchall()
    for name, aliases_json in rows:
        names.append(name)
        if aliases_json:
            try:
                names.extend(json.loads(aliases_json))
            except json.JSONDecodeError:
                pass
    return list(set(names))  # 去重


async def build_entity_summary(project_id: str, max_chars: int = 1500) -> str:
    """
    生成轻量实体摘要文本，供 path_gen / synopsis 等节点快速获取当前故事状态。

    格式：
        [人物]
        张三（主角）：当前状态 / 位置
        ...
        [近期事件]（最近 10 条）
        seq1: 事件描述
        ...
    """
    lines: list[str] = []

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        # 人物卡
        cursor = await conn.execute(
            "SELECT name, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'character' "
            "ORDER BY first_seen",
            (project_id,),
        )
        char_rows = await cursor.fetchall()
        if char_rows:
            lines.append("[人物]")
            for name, data_json in char_rows:
                d = json.loads(data_json) if data_json else {}
                status = d.get("status_change") or d.get("status", "")
                location = d.get("location_change") or d.get("location", "")
                cr = (d.get("current_role") or "").strip()
                st = (d.get("stance_to_protagonist") or "").strip()
                chn = (d.get("chapter_behavior_note") or "").strip()
                ebd_v = d.get("ebd_to_protagonist")
                td_v = d.get("targeting_degree", d.get("threat_level"))
                axis = []
                if ebd_v is not None and str(ebd_v).strip() != "":
                    try:
                        axis.append(f"EBD{int(float(ebd_v))}")
                    except (TypeError, ValueError):
                        pass
                if td_v is not None and str(td_v).strip() != "":
                    try:
                        axis.append(f"针对{max(0, min(100, int(round(float(td_v)))))}")
                    except (TypeError, ValueError):
                        pass
                summary = f"{name}"
                if axis:
                    summary += f" [{'·'.join(axis)}]"
                if cr or st:
                    summary += f" [本章角色:{cr or '?'}·对主角:{st or '?'}]"
                if status:
                    summary += f"：{status}"
                if location:
                    summary += f"（{location}）"
                if chn:
                    summary += f" ｜动态：{chn[:120]}"
                lines.append(f"  {summary}")

        # 地点卡（避免同一地点在不同章节被“重新发明”）
        cursor_loc = await conn.execute(
            "SELECT name, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'location' ORDER BY first_seen",
            (project_id,),
        )
        loc_rows = await cursor_loc.fetchall()
        if loc_rows:
            lines.append("[地点]")
            for name, data_json in loc_rows:
                d = json.loads(data_json) if data_json else {}
                desc = d.get("description") or d.get("status_change") or ""
                lines.append(f"  {name}" + (f"：{desc}" if desc else ""))

        # 道具卡（主角已持有道具，避免消失或重复获得）
        cursor_item = await conn.execute(
            "SELECT name, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'item' ORDER BY first_seen",
            (project_id,),
        )
        item_rows = await cursor_item.fetchall()
        if item_rows:
            lines.append("[道具]")
            for name, data_json in item_rows:
                d = json.loads(data_json) if data_json else {}
                holder = d.get("holder") or d.get("status_change") or ""
                lines.append(f"  {name}" + (f"（{holder}）" if holder else ""))

        # 近期事件（最近 10 条）
        cursor2 = await conn.execute(
            "SELECT seq, description FROM event_timeline "
            "WHERE project_id = ? ORDER BY seq DESC LIMIT 10",
            (project_id,),
        )
        event_rows = await cursor2.fetchall()
        if event_rows:
            lines.append("[近期事件]")
            for seq, desc in reversed(event_rows):
                lines.append(f"  第{seq}节: {desc}")

    result = "\n".join(lines)
    # 超长则截断
    if len(result) > max_chars:
        result = result[:max_chars] + "\n…（已截断）"
    return result or "（暂无实体记录）"


async def save_confirmed_char_cards(
    project_id: str,
    cards: list[dict],
    seq: int = 0,
) -> None:
    """
    将用户在 human_review_write 中确认的人物卡草稿写入 entity_cards。
    每张卡包含：standard_name、aliases、appearance、innate_traits、mental_core 等。
    这些字段存入 data_json，供 expand1 注入、write 注入外貌描述。
    """
    for card in cards:
        name = card.get("standard_name", "")
        if not name:
            continue
        mc = card.get("mental_core") if isinstance(card.get("mental_core"), dict) else {}
        data_patch = {
            "appearance":            card.get("appearance", ""),
            "first_appearance_seq":  seq,
            "innate_traits":         card.get("innate_traits", []),
            "mental_core":           mc,
            "micro_reactions":       card.get("micro_reactions", []),
            "maturity_level":        card.get("maturity_level", ""),
            "current_emotional_drain": card.get("current_emotional_drain", 0),
        }
        if card.get("traits"):
            data_patch["traits"] = card["traits"]
        ti = card.get("trait_interactions")
        if ti and isinstance(ti, dict):
            preset = ti.get("preset") or []
            data_patch["trait_interactions"] = {
                "preset":  preset,
                "learned": ti.get("learned", []),
            }
        await upsert_entity_card(
            project_id=project_id,
            card_type="character",
            name=name,
            data_patch=data_patch,
            seq=seq,
            aliases=card.get("aliases", []),
        )


async def increment_key_event_count(
    project_id: str,
    char_name: str,
    event_type: str = "neutral",
    amount: int = 1,
) -> int:
    """
    给指定人物增加关键事件计数。event_type: positive=帮助主角 / negative=伤害主角 / neutral=无明确倾向。
    计数存在 data_json 的 key_event_count、key_event_positive_count、key_event_negative_count。
    若人物卡不存在则静默跳过（返回 0）。
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT entity_id, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'character' AND name = ?",
            (project_id, char_name),
        )
        row = await cursor.fetchone()
        if not row:
            return 0
        data: dict = json.loads(row["data_json"]) if row["data_json"] else {}
        total = data.get("key_event_count", 0) + amount
        data["key_event_count"] = total
        if event_type == "positive":
            data["key_event_positive_count"] = data.get("key_event_positive_count", 0) + amount
        elif event_type == "negative":
            data["key_event_negative_count"] = data.get("key_event_negative_count", 0) + amount
        await conn.execute(
            "UPDATE entity_cards SET data_json = ?, updated_at = datetime('now') WHERE entity_id = ?",
            (json.dumps(data, ensure_ascii=False), row["entity_id"]),
        )
        await conn.commit()
    return total


async def is_core_character(project_id: str, name: str, threshold: int = 2) -> bool:
    """检查角色是否已达到核心配角阈值（key_event_count >= threshold）。"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'character' AND name = ?",
            (project_id, name),
        )
        row = await cursor.fetchone()
    if not row:
        return False
    data = json.loads(row["data_json"]) if row["data_json"] else {}
    return data.get("key_event_count", 0) >= threshold


async def update_character_role(
    project_id: str,
    name: str,
    new_role: str,            # "盟友" | "对立" | "中立" | "灰色地带"
    seq: int = 0,
    trigger_description: str = "",
    true_motive: str = "",
    surface_role: str = "",   # 灰色地带时的表面立场
) -> None:
    """
    更新角色的当前立场，追加到 role_history，可选写入 true_motive。
    灰色地带时额外记录 surface_role（表面立场）和 true_role（真实立场）。
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT entity_id, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'character' AND name = ?",
            (project_id, name),
        )
        row = await cursor.fetchone()
        if not row:
            return

        data: dict = json.loads(row["data_json"]) if row["data_json"] else {}
        old_role = data.get("current_role", "中立")

        # 追加 role_history
        history_entry: dict = {
            "seq":     seq,
            "from":    old_role,
            "to":      new_role,
            "trigger": trigger_description,
        }
        history: list = data.get("role_history", [])
        history.append(history_entry)
        data["role_history"]  = history
        data["current_role"]  = new_role

        if new_role == "灰色地带" and surface_role:
            data["surface_role"] = surface_role
            data["true_role"]    = "对立"   # 灰色地带实质是对立

        if true_motive:
            data["true_motive"] = true_motive

        await conn.execute(
            "UPDATE entity_cards SET data_json = ?, updated_at = datetime('now') WHERE entity_id = ?",
            (json.dumps(data, ensure_ascii=False), row["entity_id"]),
        )
        await conn.commit()


def _determine_upgrade_role(pos_count: int, neg_count: int) -> str:
    """根据关键事件性质判断角色类型。"""
    if neg_count >= 2:
        return "antagonist"
    if pos_count >= 2:
        return "core_supporting"
    return "neutral"


async def get_newly_promoted_chars(
    project_id: str,
    names: list[str],
    threshold: int = 2,
) -> list[dict]:
    """
    返回列表中 key_event_count 刚好等于阈值的人物及其升级类型。
    返回 [{"name": str, "upgrade_role": str, "pos_count": int, "neg_count": int}, ...]
    """
    if not names:
        return []
    promoted: list[dict] = []
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        for name in names:
            cursor = await conn.execute(
                "SELECT data_json FROM entity_cards "
                "WHERE project_id = ? AND card_type = 'character' AND name = ?",
                (project_id, name),
            )
            row = await cursor.fetchone()
            if row:
                data = json.loads(row["data_json"]) if row["data_json"] else {}
                total = data.get("key_event_count", 0)
                if total == threshold:
                    pos = data.get("key_event_positive_count", 0)
                    neg = data.get("key_event_negative_count", 0)
                    promoted.append({
                        "name":         name,
                        "upgrade_role": _determine_upgrade_role(pos, neg),
                        "pos_count":    pos,
                        "neg_count":    neg,
                    })
    return promoted


async def get_character_cards_with_tendencies(
    project_id: str,
    char_names: list[str],
) -> list[dict]:
    """
    按人物名列表查询实体卡，返回含 innate_traits/mental_core 与 appearance 的完整卡片。
    用于 expand1 注入行为倾向，write 注入外貌（首次出场时）。
    """
    if not char_names:
        return []
    results: list[dict] = []
    seen_ids: set[str] = set()

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        for name in char_names:
            cursor = await conn.execute(
                "SELECT entity_id, name, aliases, data_json, first_seen FROM entity_cards "
                "WHERE project_id = ? AND card_type = 'character' AND name = ?",
                (project_id, name),
            )
            row = await cursor.fetchone()
            if row and row["entity_id"] not in seen_ids:
                seen_ids.add(row["entity_id"])
                data = json.loads(row["data_json"]) if row["data_json"] else {}
                _td = data.get("targeting_degree", data.get("threat_level"))
                _td_out = None
                if _td is not None and str(_td).strip() != "":
                    try:
                        _td_out = max(0, min(100, int(round(float(_td)))))
                    except (TypeError, ValueError):
                        _td_out = None
                results.append({
                    "name":                    row["name"],
                    "aliases":                 json.loads(row["aliases"] or "[]"),
                    "first_seen":              row["first_seen"],
                    "appearance":              data.get("appearance", ""),
                    "core_motif":              data.get("core_motif", ""),
                    "persona":                 data.get("persona", ""),
                    "signature_habits":        data.get("signature_habits", []),
                    "innate_traits":           data.get("innate_traits", []),
                    "mental_core":             data.get("mental_core", {}),
                    "maturity_level":          data.get("maturity_level", ""),
                    "current_emotional_drain": data.get("current_emotional_drain", 0),
                    "micro_reactions":         data.get("micro_reactions", []),
                    "current_status":          data.get("status_change") or data.get("status", ""),
                    "dominant_logics":         data.get("dominant_logics", []),
                    "logic_switch_conditions": data.get("logic_switch_conditions", []),
                    "role":                    data.get("role", "minor"),
                    "true_motive":             data.get("true_motive", ""),
                    "neutral_stance":          data.get("neutral_stance", ""),
                    "tipping_conditions":       data.get("tipping_conditions", []),
                    # EBD（情感纽带度，存 data_json，-expand1 / bible 演算）
                    "ebd_to_protagonist":     int(data.get("ebd_to_protagonist", 0) or 0),
                    "ebd_bond_kind":           (data.get("ebd_bond_kind") or "").strip(),
                    "ebd_type":               (data.get("ebd_type") or "").strip(),
                    "ebd_note":                (data.get("ebd_note") or "").strip(),
                    "ebd_crack":               bool(data.get("ebd_crack", 0)),
                    # 客观针对度（bible Pass1），0～100；与 EBD 主观轴分离
                    "targeting_degree":        _td_out,
                    "current_mental_state":    (data.get("current_mental_state") or "").strip(),
                    "mental_growth_path":      (data.get("mental_growth_path") or "").strip(),
                    "reverse_scale":           (data.get("reverse_scale") or "").strip(),
                    # 补丁 v4.3：与主角卡同构，供 event_chain / 暗流推导使用
                    "capabilities":            data.get("capabilities") if isinstance(data.get("capabilities"), dict) else {},
                })
    return results


async def apply_ebd_delta(
    project_id: str,
    character_name: str,
    delta: int,
    reason: str,
    seq: int,
    *,
    ebd_type_after: str | None = None,
) -> None:
    """
    在已有 character 卡上应用 EBD 增量，写入 ebd_history，夹紧 −100～100。
    ebd_crack=1 时正向不超过 +50（与设计文档一致）。
    """
    if not project_id or not character_name.strip():
        return
    name = character_name.strip()
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        return
    if delta == 0 and not (ebd_type_after or "").strip():
        return

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute(
            "SELECT entity_id, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'character' AND name = ?",
            (project_id, name),
        )
        row = await cur.fetchone()
        if not row:
            return
        data = json.loads(row["data_json"] or "{}")
        old = int(data.get("ebd_to_protagonist", 0) or 0)
        raw_new = old + delta
        if data.get("ebd_crack"):
            raw_new = min(raw_new, 50)
        new_ebd = max(-100, min(100, raw_new))
        hist = data.get("ebd_history")
        if not isinstance(hist, list):
            hist = []
        entry = {"seq": seq, "from": old, "to": new_ebd, "delta": delta, "reason": (reason or "")[:500]}
        hist.append(entry)
        if len(hist) > 80:
            hist = hist[-80:]
        data["ebd_to_protagonist"] = new_ebd
        data["ebd_history"] = hist
        if ebd_type_after and str(ebd_type_after).strip():
            data["ebd_type"] = str(ebd_type_after).strip()
        await conn.execute(
            "UPDATE entity_cards SET data_json = ?, last_updated = ?, updated_at = datetime('now') "
            "WHERE entity_id = ?",
            (json.dumps(data, ensure_ascii=False), seq, row["entity_id"]),
        )
        await conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Personality system: traits + trait_interactions
# ──────────────────────────────────────────────────────────────────────────────

async def get_character_traits_and_interactions(
    project_id: str,
    char_names: list[str],
) -> dict[str, dict]:
    """
    批量获取 traits 和 trait_interactions。
    返回 {char_name: {traits: [...], trait_interactions: {preset: [...], learned: [...]}}}。
    若 traits 为空，调用方可用 innate_traits 做 fallback。
    """
    if not char_names:
        return {}
    result: dict[str, dict] = {}
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        for name in char_names:
            cursor = await conn.execute(
                "SELECT data_json FROM entity_cards "
                "WHERE project_id = ? AND card_type = 'character' AND name = ?",
                (project_id, name),
            )
            row = await cursor.fetchone()
            if row:
                data = json.loads(row["data_json"]) if row["data_json"] else {}
                traits = data.get("traits", [])
                interactions = data.get("trait_interactions", {})
                if not isinstance(interactions, dict):
                    interactions = {"preset": [], "learned": []}
                result[name] = {
                    "traits":             traits,
                    "trait_interactions": interactions,
                }
    return result


async def append_learned_trait_interaction(
    project_id: str,
    char_name: str,
    interaction: dict,
) -> None:
    """
    将 learned 叠加规则追加到 trait_interactions.learned，不覆盖 preset。
    interaction 应包含 combo, condition, result, learned_from_seq?, trigger_event? 等。
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT entity_id, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'character' AND name = ?",
            (project_id, char_name),
        )
        row = await cursor.fetchone()
        if not row:
            return

        data: dict = json.loads(row["data_json"]) if row["data_json"] else {}
        interactions = data.get("trait_interactions", {})
        if not isinstance(interactions, dict):
            interactions = {"preset": [], "learned": []}
        learned = interactions.get("learned", [])
        if not isinstance(learned, list):
            learned = []
        learned.append(interaction)
        interactions["learned"] = learned
        data["trait_interactions"] = interactions

        await conn.execute(
            "UPDATE entity_cards SET data_json = ?, updated_at = datetime('now') "
            "WHERE entity_id = ?",
            (json.dumps(data, ensure_ascii=False), row["entity_id"]),
        )
        await conn.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Ability system
# ──────────────────────────────────────────────────────────────────────────────

async def upsert_character_ability(
    project_id: str,
    char_name: str,
    operation: str,   # "add" | "upgrade" | "deactivate"
    ability: dict,
) -> None:
    """
    更新角色的能力列表：
    - add：追加新能力（若同名已存在则 upgrade）
    - upgrade：找到同名能力，更新 level / description / limitation
    - deactivate：找到同名能力，标记 active=False，记录原因
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT entity_id, data_json FROM entity_cards "
            "WHERE project_id = ? AND card_type = 'character' AND name = ?",
            (project_id, char_name),
        )
        row = await cursor.fetchone()
        if not row:
            return

        data: dict = json.loads(row["data_json"]) if row["data_json"] else {}
        abilities: list[dict] = data.get("abilities", [])
        ability_name = ability.get("name", "")

        if operation == "add":
            existing = next((a for a in abilities if a.get("name") == ability_name), None)
            if existing:
                # 同名则视为升级
                existing.update({k: v for k, v in ability.items() if v})
                existing["active"] = True
            else:
                ability.setdefault("active", True)
                abilities.append(ability)

        elif operation == "upgrade":
            existing = next((a for a in abilities if a.get("name") == ability_name), None)
            if existing:
                for k, v in ability.items():
                    if v:
                        existing[k] = v
                existing["active"] = True
            else:
                ability.setdefault("active", True)
                abilities.append(ability)

        elif operation == "deactivate":
            existing = next((a for a in abilities if a.get("name") == ability_name), None)
            if existing:
                existing["active"] = False
                existing["deactivate_reason"] = ability.get("source", "")

        data["abilities"] = abilities
        await conn.execute(
            "UPDATE entity_cards SET data_json = ?, updated_at = datetime('now') "
            "WHERE entity_id = ?",
            (json.dumps(data, ensure_ascii=False), row["entity_id"]),
        )
        await conn.commit()


async def get_character_abilities(
    project_id: str,
    char_names: list[str],
) -> dict[str, list[dict]]:
    """
    批量获取角色的能力列表。
    返回 {char_name: [ability_dict, ...]}，只包含 active=True 的能力。
    """
    if not char_names:
        return {}
    result: dict[str, list[dict]] = {}
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        for name in char_names:
            cursor = await conn.execute(
                "SELECT data_json FROM entity_cards "
                "WHERE project_id = ? AND card_type = 'character' AND name = ?",
                (project_id, name),
            )
            row = await cursor.fetchone()
            if row:
                data = json.loads(row["data_json"]) if row["data_json"] else {}
                abilities = [a for a in data.get("abilities", []) if a.get("active", True)]
                if abilities:
                    result[name] = abilities
    return result


async def get_all_ability_names(
    project_id: str,
    char_names: list[str],
) -> set[str]:
    """返回指定角色的所有已记录能力名称集合（active 和 inactive 都包含）。"""
    if not char_names:
        return set()
    names: set[str] = set()
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        for char_name in char_names:
            cursor = await conn.execute(
                "SELECT data_json FROM entity_cards "
                "WHERE project_id = ? AND card_type = 'character' AND name = ?",
                (project_id, char_name),
            )
            row = await cursor.fetchone()
            if row:
                data = json.loads(row["data_json"]) if row["data_json"] else {}
                for ab in data.get("abilities", []):
                    if ab.get("name"):
                        names.add(ab["name"])
    return names
