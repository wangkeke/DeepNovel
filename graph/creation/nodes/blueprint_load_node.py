"""
blueprint_load_node：加载骨骼 / 续传已有项目

骨骼加载（新项目）支持三种模式：
  模式1 - 指定 blueprint_id：直接加载，找不到则报错
  模式2 - 未指定，库里有匹配：按题材自动匹配最近的一份
  模式3 - 未指定，库里无匹配：自由创作（不注入任何骨骼，weight=0）

续传模式（已有 project_id）：
  - 从 DB 加载已有的 synopsis / bible / story_nodes
  - 找到第一个未完成的 story_node，直接跳到 expand1
  - 若当前批次全部完成，跳到 path_gen 规划下一批
"""
from __future__ import annotations
import json
import logging
import aiosqlite
from rich.console import Console
from langgraph.types import StreamWriter
from schemas.state import CreationState
from tools.blueprint_store import load_blueprint, search_blueprints
from knowledge.genre_matcher import match_genre
from knowledge.genre_dict import GENRE_DICT
from config import COMPATIBILITY_RULES, COMPATIBILITY_HIGH, COMPATIBILITY_MID, DB_PATH
from memory.db import load_chapters_count
from utils.v42_flow import shallow_world_archive

console = Console()
logger = logging.getLogger("deepnovel.blueprint_load")


def _infer_genre_attrs(genre_request: str) -> dict:
    """从用户题材需求文本中推断骨骼属性（关键词匹配）"""
    text = genre_request.lower()

    if any(k in text for k in ["玄幻", "修仙", "魔法", "超能", "灵异", "鬼", "妖", "神仙"]):
        world_rule = "supernatural"
    elif any(k in text for k in ["现实", "都市", "职场", "现代", "当代"]):
        world_rule = "realistic"
    else:
        world_rule = "mixed"

    if any(k in text for k in ["末世", "战争", "王国", "帝国", "世界", "宇宙"]):
        conflict = "world"
    elif any(k in text for k in ["门派", "家族", "组织", "公司", "势力"]):
        conflict = "organizational"
    else:
        conflict = "personal"

    if any(k in text for k in ["废柴", "弱者", "底层", "贫民", "普通人"]):
        power = "weak"
    elif any(k in text for k in ["天才", "强者", "至尊", "神级"]):
        power = "strong"
    else:
        power = "balanced"

    return {
        "world_rule_type": world_rule,
        "conflict_scale": conflict,
        "protagonist_power": power,
    }


def calculate_compatibility(blueprint: dict, genre_request: str) -> dict:
    """计算骨骼与用户需求的兼容性评分（满分100）"""
    req = _infer_genre_attrs(genre_request)
    bp_world    = blueprint.get("world_rule_type", "realistic")
    bp_conflict = blueprint.get("conflict_scale", "personal")
    bp_power    = blueprint.get("protagonist_power", "balanced")

    scores = {}
    total  = 0
    pairs  = [
        ("world_rule_type",   req["world_rule_type"],   bp_world),
        ("conflict_scale",    req["conflict_scale"],     bp_conflict),
        ("protagonist_power", req["protagonist_power"],  bp_power),
    ]
    for dim, req_val, bp_val in pairs:
        rules = COMPATIBILITY_RULES[dim]
        key   = f"{req_val}+{bp_val}"
        score = rules.get(key, rules.get(f"{bp_val}+{req_val}", 0))
        scores[dim] = score
        total += score

    if total >= COMPATIBILITY_HIGH:
        level      = "high"
        suggestion = "骨骼与题材高度契合，可直接创作。"
    elif total >= COMPATIBILITY_MID:
        level      = "mid"
        suggestion = "骨骼与题材中度契合，建议路径规划时加入过渡节点。"
    else:
        level      = "low"
        suggestion = (
            f"骨骼与题材兼容性较低（{total}/100），"
            "建议选择其他骨骼，或降低 blueprint_weight 以优先服从故事圣经。"
        )
        
    return {
        "score": total,
        "level": level,
        "details": scores,
        "request_attrs": req,
        "blueprint_attrs": {
            "world_rule_type": bp_world,
            "conflict_scale":  bp_conflict,
            "protagonist_power": bp_power,
        },
        "suggestion": suggestion,
    }


async def _try_resume_from_db(project_id: str) -> dict | None:
    """
    尝试从数据库加载已有项目。
    返回 dict（含 resume_from_db=True 的 state 补丁），或 None（项目不存在）。
    """
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """SELECT synopsis_json, entity_summary, world_setting_json,
                      protagonist_name, platform_style, last_action_intent,
                      auto_mode, max_chapters, user_write_rules, current_volume_index,
                      volumes_json, core_cast_json, event_chain_json
               FROM novel_projects WHERE project_id = ?""",
            (project_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        synopsis      = json.loads(row["synopsis_json"] or "{}")
        # entity_summary 是纯文本摘要，包装成 bible dict 格式以兼容后续节点
        bible         = {"entity_summary": row["entity_summary"] or ""}
        world_setting = json.loads(row["world_setting_json"] or "{}")
        try:
            protagonist_name = row["protagonist_name"] or ""
        except (KeyError, IndexError):
            protagonist_name = ""
        try:
            platform_style = row["platform_style"] or "通用网文"
        except (KeyError, IndexError):
            platform_style = "通用网文"
        try:
            last_action_intent = (row["last_action_intent"] or "").strip()
        except (KeyError, IndexError):
            last_action_intent = ""
        try:
            auto_mode = bool(int(row["auto_mode"] or 0))
        except (KeyError, IndexError, TypeError, ValueError):
            auto_mode = False
        try:
            max_auto_events = int(row["max_chapters"] or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            max_auto_events = 0
        try:
            user_write_rules = (row["user_write_rules"] or "").strip()
        except (KeyError, IndexError, AttributeError):
            user_write_rules = ""
        try:
            current_volume_index = int(row["current_volume_index"] or 0)
        except (KeyError, IndexError, TypeError, ValueError):
            current_volume_index = 0
        try:
            vj = row["volumes_json"]
            volumes = json.loads(vj or "[]") if vj else []
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            volumes = []

        core_cast: dict = {}
        try:
            core_cast = json.loads(row["core_cast_json"] or "{}")
        except (KeyError, TypeError, json.JSONDecodeError):
            core_cast = {}

        current_event_chain: list = []
        current_event_chain_pos = 0
        try:
            ec_raw = row["event_chain_json"]
            if ec_raw:
                ec = json.loads(ec_raw)
                if isinstance(ec, dict):
                    vi = int(ec.get("volume_index", 0))
                    if vi == current_volume_index:
                        ev = ec.get("events")
                        current_event_chain = ev if isinstance(ev, list) else []
                        current_event_chain_pos = int(ec.get("chain_pos", 0) or 0)
        except (KeyError, TypeError, json.JSONDecodeError):
            pass

        ne_from_ws = ""
        wa_resume: dict = {}
        if isinstance(world_setting, dict):
            ne_from_ws = str(world_setting.get("narrative_era") or "").strip()
            wa_resume = shallow_world_archive(world_setting)

        # 取当前批次未完成的节点（按 seq 升序）
        cursor2 = await conn.execute(
            """SELECT seq, node_name, one_liner, pressure_chain_type,
                      resolution_chain_type, input_state_hint, output_state_hint
               FROM story_nodes
               WHERE project_id = ? AND status != 'done'
               ORDER BY seq""",
            (project_id,),
        )
        rows = await cursor2.fetchall()

    # 仅从 DB 显式写入事件链游标，避免用「空链」覆盖 checkpointer 里未落库的记忆；
    # 绝不续传时强行写入 event_chain_draft（否则会冲掉待审核草稿）。
    chain_patch: dict = {}
    if current_event_chain:
        chain_patch["current_event_chain"] = current_event_chain
        chain_patch["current_event_chain_pos"] = current_event_chain_pos
        chain_patch["last_event_batch_size"] = 0

    if rows:
        story_path = [
            {
                "_seq":                 r["seq"],
                "node_name":             r["node_name"],
                "one_liner":             r["one_liner"],
                "pressure_chain_type":   r["pressure_chain_type"],
                "resolution_chain_type": r["resolution_chain_type"],
                "input_state_hint":      r["input_state_hint"],
                "output_state_hint":     r["output_state_hint"],
            }
            for r in rows
        ]
        console.print(
            f"\n  [bold green]✓ 续传项目[/bold green]  "
            f"[dim]从第 {rows[0]['seq']} 个节点继续（当前批次剩余 {len(rows)} 个）[/dim]"
        )
        return {
            "resume_from_db":          True,
            "synopsis":                synopsis,
            "synopsis_approved":       True,
            "path_approved":           True,
            "bible":                   bible,
            "world_setting":           world_setting,
            "world_setting_confirmed": bool(world_setting),
            "world_archive":           wa_resume,
            "narrative_era":            ne_from_ws,
            "protagonist_name":        protagonist_name,
            "platform_style":          platform_style,
            "last_action_intent":       last_action_intent,
            "auto_mode":               auto_mode,
            "max_auto_events":         max_auto_events,
            "story_path":              story_path,
            "current_node_index":      0,
            "auto_retry_count":        0,
            "auto_retry_count_path":   0,
            "auto_retry_count_expand": 0,
            "auto_retry_count_write":  0,
            "auto_total_retry_count":  0,
            "tension_retry_count":     0,
            "tension_minor_issues":    [],
            "user_write_rules":         user_write_rules,
            "current_volume_index":     current_volume_index,
            "volumes":                 volumes,
            "core_cast":               core_cast,
            "core_cast_draft":        {},
            "story_arc_volumes_draft": [],
            "story_arc_regen_feedback": "",
            **chain_patch,
        }
    else:
        # 当前批次全部完成，需要继续 path_gen 规划下一批
        console.print(
            "\n  [bold green]✓ 续传项目[/bold green]  "
            "[dim]当前批次已全部完成，准备规划下一批路径[/dim]"
        )
        return {
            "resume_from_db":          True,
            "synopsis":                synopsis,
            "synopsis_approved":       True,
            "bible":                   bible,
            "world_setting":           world_setting,
            "world_setting_confirmed": bool(world_setting),
            "world_archive":           wa_resume,
            "narrative_era":            ne_from_ws,
            "protagonist_name":        protagonist_name,
            "platform_style":          platform_style,
            "last_action_intent":       last_action_intent,
            "auto_mode":               auto_mode,
            "max_auto_events":         max_auto_events,
            "story_path":              [],
            "current_node_index":      0,
            "auto_retry_count":        0,
            "auto_retry_count_path":   0,
            "auto_retry_count_expand": 0,
            "auto_retry_count_write":  0,
            "auto_total_retry_count":  0,
            "tension_retry_count":     0,
            "tension_minor_issues":    [],
            "user_write_rules":         user_write_rules,
            "current_volume_index":     current_volume_index,
            "volumes":                 volumes,
            "core_cast":               core_cast,
            "core_cast_draft":        {},
            "story_arc_volumes_draft": [],
            "story_arc_regen_feedback": "",
            **chain_patch,
        }


async def blueprint_load_node(state: CreationState, writer: StreamWriter) -> dict:
    writer({"node_status": "started", "node": "load"})
    project_id    = state.get("project_id", "")
    blueprint_id  = state.get("blueprint_id", "")
    genre_request = state.get("genre_request", "")

    # ── 框架导入模式：直接透传，跳过骨骼加载 ────────────────────────────────────
    if state.get("creation_mode") == "framework":
        matched_genres = match_genre(genre_request)
        genre_dicts    = [GENRE_DICT[g] for g in matched_genres if g in GENRE_DICT]
        if matched_genres:
            console.print(f"\n  [dim]题材匹配：{'、'.join(matched_genres)}[/dim]")
        return {
            "creation_mode":   "framework",
            "framework_file_path": state.get("framework_file_path", ""),
            "blueprint":       {},
            "blueprint_weight": 0.0,
            "free_creation":   True,
            "resume_from_db":  False,
            "matched_genres":  matched_genres,
            "genre_dicts":     genre_dicts,
        }

    # ── 续传模式：项目已存在于 DB ──────────────────────────────────────────────
    # 沙盒/压测可设 _sandbox_skip_db_resume，避免复用 project_id 时把章节行数误写入
    # global_settled_event_count，导致 max_events 与雷达尚未运行就提前退出。
    if project_id and not state.get("_sandbox_skip_db_resume"):
        resume_patch = await _try_resume_from_db(project_id)
        if resume_patch is not None:
            # 续传：仅用 DB 正文行数粗估已产出规模；精确事件数以 checkpoint 为准
            resume_patch["global_settled_event_count"] = await load_chapters_count(project_id)
            resume_patch.setdefault("volume_start_event_count", 0)
            resume_patch.setdefault("completed_events_summary", [])
            resume_patch.setdefault("auto_target", "book")
            resume_patch.setdefault("max_auto_events", 0)
            # 续传时也做题材匹配，确保 path_gen 有词典可用
            matched_genres = match_genre(genre_request)
            genre_dicts    = [GENRE_DICT[g] for g in matched_genres if g in GENRE_DICT]
            resume_patch["matched_genres"] = matched_genres
            resume_patch["genre_dicts"]    = genre_dicts
            return resume_patch

        # project_id 有值但 DB 里没记录 → 正常走新建流程（下面继续）

    blueprint     = None
    free_creation = False

    # ── 模式1：指定了 ID，直接加载 ────────────────────────────────────────────
    if blueprint_id:
        blueprint = await load_blueprint(blueprint_id)
        if not blueprint:
            raise ValueError(f"找不到骨骼档案：{blueprint_id}")
        console.print(
            f"\n  [dim]使用指定骨骼：{blueprint.get('source_title', blueprint_id[:12])}[/dim]"
        )
    else:
        # ── 模式2：按题材自动匹配 ─────────────────────────────────────────────
        candidates = await search_blueprints(genre=genre_request)
        if candidates:
            best = candidates[0]
            blueprint = await load_blueprint(best["blueprint_id"])
            console.print(
                f"\n  [dim]自动匹配骨骼：{best.get('source_title', '未知')} "
                f"({best['blueprint_id'][:12]})[/dim]"
            )
        else:
            # ── 模式3：无匹配，自由创作 ────────────────────────────────────────
            free_creation = True
            console.print(
                "\n  [dim]骨骼库中无匹配档案，进入自由创作模式[/dim]"
            )

    # 自由创作：权重 0；有骨骼：默认 0.8（兼容性低时下调为 0.3）
    blueprint_weight = 0.0 if free_creation else 0.8

    bible: dict = dict(state.get("bible") or {})

    if not free_creation and blueprint:
        compat = calculate_compatibility(blueprint, genre_request)
        bible["compatibility_check"] = compat
        if compat["level"] == "low":
            blueprint_weight = 0.3

    # ── 题材匹配（新项目 + 续传均执行）──────────────────────────────────────
    matched_genres = match_genre(genre_request)
    genre_dicts    = [GENRE_DICT[g] for g in matched_genres if g in GENRE_DICT]
    if matched_genres:
        console.print(
            f"\n  [dim]题材匹配：{'、'.join(matched_genres)}[/dim]"
        )
    else:
        console.print("\n  [dim]题材库无匹配，将使用通用节点规划[/dim]")
        
    out = {
        "blueprint":        blueprint or {},
        "blueprint_id":     (blueprint or {}).get("blueprint_id", ""),
        "blueprint_weight": blueprint_weight,
        "free_creation":    free_creation,
        "resume_from_db":   False,
        "bible":            bible,
        "matched_genres":   matched_genres,
        "genre_dicts":      genre_dicts,
    }
    # 显式透传 creation_mode / framework_file_path，确保 _route_after_load 能正确路由到 framework_parse
    if state.get("creation_mode"):
        out["creation_mode"] = state["creation_mode"]
    if state.get("framework_file_path"):
        out["framework_file_path"] = state["framework_file_path"]
    return out
