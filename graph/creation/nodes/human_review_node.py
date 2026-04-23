"""
human_review_node：人工审核节点
使用 LangGraph 1.1.2 的 interrupt() + Command 机制实现人工介入。

两个审核点：
  1. synopsis_review  - 确认宏观构思，通过后 INSERT novel_projects
  2. path_review      - 确认故事路径，通过后 INSERT story_nodes（本批次节点）

用户通过 CLI 传入 Command(resume=...) 恢复执行：
  - action="approve" → 继续
  - action="revise"  → 修改并重新生成（feedback 字段会注入下一轮 Prompt）
"""
from __future__ import annotations
import json
import aiosqlite
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from config import DB_PATH


async def _upsert_project(
    project_id: str,
    blueprint_id: str,
    genre_request: str,
    synopsis: dict,
    platform_style: str = "通用网文",
    auto_mode: bool = False,
    max_chapters: int = 0,
) -> None:
    """synopsis 确认后，在 novel_projects 表中创建或更新项目记录"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        await conn.execute(
            """INSERT INTO novel_projects
               (project_id, blueprint_id, genre_request, synopsis_json, platform_style,
                auto_mode, max_chapters, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'drafting')
               ON CONFLICT(project_id) DO UPDATE SET
                   synopsis_json   = excluded.synopsis_json,
                   platform_style  = excluded.platform_style,
                   auto_mode       = excluded.auto_mode,
                   max_chapters    = excluded.max_chapters,
                   updated_at      = datetime('now')""",
            (
                project_id,
                blueprint_id,
                genre_request,
                json.dumps(synopsis, ensure_ascii=False),
                platform_style,
                1 if auto_mode else 0,
                max_chapters,
            ),
        )
        await conn.commit()


async def _get_done_node_count(project_id: str) -> int:
    """从 DB 查询当前项目已完成（status=done）的节点数，作为新批次的 seq_offset。"""
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM story_nodes WHERE project_id = ? AND status = 'done'",
            (project_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def _insert_story_nodes(
    project_id: str,
    story_path: list[dict],
    seq_offset: int = 0,
) -> list[dict]:
    """
    路径确认后，将本批次节点写入 story_nodes 表。
    返回带有 _seq 字段的 story_path 副本，供后续节点定位 DB 行。
    seq_offset：当前批次之前已完成的节点数量，用于计算全局 seq。
    """
    try:
        from ulid import ULID
        make_id = lambda: str(ULID())
    except ImportError:
        import uuid
        make_id = lambda: str(uuid.uuid4())

    updated: list[dict] = []
    async with aiosqlite.connect(str(DB_PATH)) as conn:
        for i, node in enumerate(story_path):
            seq = seq_offset + i + 1
            await conn.execute(
                """INSERT INTO story_nodes
                   (node_id, project_id, seq, node_name, one_liner,
                    pressure_chain_type, resolution_chain_type,
                    input_state_hint, output_state_hint, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'planned')
                   ON CONFLICT(project_id, seq) DO UPDATE SET
                       node_name             = excluded.node_name,
                       one_liner             = excluded.one_liner,
                       pressure_chain_type   = excluded.pressure_chain_type,
                       resolution_chain_type = excluded.resolution_chain_type,
                       input_state_hint      = excluded.input_state_hint,
                       output_state_hint     = excluded.output_state_hint""",
                (
                    make_id(),
                    project_id,
                    seq,
                    node.get("node_name", ""),
                    node.get("one_liner", ""),
                    node.get("pressure_chain_type", ""),
                    node.get("resolution_chain_type", ""),
                    node.get("input_state_hint", ""),
                    node.get("output_state_hint", ""),
                ),
            )
            updated.append({**node, "_seq": seq})
        await conn.commit()
    return updated


async def human_review_synopsis_node(state: CreationState) -> Command:
    """
    宏观构思审核节点：
      - 暂停执行，将 synopsis 展示给用户
      - 用户 approve → INSERT novel_projects，跳转 path_gen
      - 用户 revise  → 将 feedback 注入 synopsis，重新生成
    """
    synopsis = state.get("synopsis") or {}
    title_s = str(synopsis.get("title") or "").strip()
    conflict_s = str(synopsis.get("core_conflict") or "").strip()
    if not title_s and not conflict_s:
        # 勿展示空的「宏观构思」假菜单：创世线回开篇/冰山；传统 synopsis 线重跑 synopsis 节点
        if (state.get("genesis_opening_text") or "").strip():
            return Command(goto="iceberg_deduction")
        if state.get("genesis_variables"):
            return Command(goto="world_build")
        return Command(goto="synopsis")

    user_input = interrupt({
        "type": "synopsis_review",
        "content": synopsis,
        "prompt": (
            "[1] 满意，下一步生成世界设定卡（随后主角卡 → 冰山 → 开篇 → 分卷）\n"
            "[2] 修改某个字段（逐字段编辑）\n"
            "[3] 修改意见（重新生成）"
        ),
    })

    if user_input.get("action") == "approve":
        # 持久化：创建项目记录（模式选择在 mode_select_node 统一询问）
        try:
            await _upsert_project(
                project_id   = state.get("project_id", ""),
                blueprint_id = state.get("blueprint_id", ""),
                genre_request= state.get("genre_request", ""),
                synopsis     = synopsis,
                platform_style= state.get("platform_style", "通用网文"),
            )
        except Exception:
            pass  # 不中断流程

        return Command(
            update={"synopsis_approved": True},
            goto="world_build",  # synopsis 确认后先生成世界设定卡
        )
    elif user_input.get("action") == "edit":
        # 逐字段编辑：只更新用户明确修改的字段
        edits = user_input.get("edits", {})
        updated_synopsis = {**synopsis}
        for fid in (
            "title", "world", "protagonist", "core_conflict", "direction",
            "family_emotion_line", "romance_emotion_line",
            "core_hook", "volume_1_goal", "escalation_path", "ultimate_goal",
            "opening_seed_text",
        ):
            v = edits.get(fid)
            if v is not None and str(v).strip():
                updated_synopsis[fid] = v
        glk = edits.get("genre_lexicon_keys")
        if glk is not None:
            updated_synopsis["genre_lexicon_keys"] = glk
        return Command(
            update={
                "synopsis":         updated_synopsis,
                "synopsis_approved": False,
            },
            goto="human_review_synopsis",  # 重新展示修改后的结果
        )
    else:
        # 修改意见整体重生成
        feedback = (user_input.get("feedback") or "").strip()
        opening_ok = (state.get("genesis_opening_text") or "").strip()
        genesis_line = bool(state.get("genesis_variables"))
        # 创世+冰山链路：禁止退回 synopsis_node（会无视开篇与已定世界/班底）；改走冰山阶段2或与开篇对齐的全流程
        if opening_ok and genesis_line:
            syn_clean = {k: v for k, v in synopsis.items() if k != "user_feedback"}
            has_snap = (state.get("iceberg_stage1_world_raw") or {}) and (
                state.get("iceberg_stage1_cast_raw") or {}
            )
            return Command(
                update={
                    "synopsis_approved": False,
                    "synopsis": syn_clean,
                    "iceberg_deduction_feedback": feedback
                    or "请按用户意见重写宏观构思，须与已锁定的开篇正文、世界规则与核心班底一致，禁止设定漂移。",
                    "iceberg_synopsis_only": bool(has_snap),
                },
                goto="iceberg_deduction",
            )
        # 传统骨架 / 无创世变量：仍走 synopsis_node
        return Command(
            update={
                "synopsis_approved": False,
                "synopsis": {**synopsis, "user_feedback": feedback},
            },
            goto="synopsis",
        )


async def _save_volume_to_db(
    project_id: str,
    volume_index: int,
    volume_name: str,
    volume_tagline: str,
    start_seq: int,
    end_seq: int,
) -> None:
    """将本卷信息追加到 novel_projects.volumes_json 数组。"""
    if not project_id:
        return
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT volumes_json FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            volumes: list = json.loads(row["volumes_json"] or "[]") if row and row["volumes_json"] else []

            # 同一卷更新而非重复追加
            existing = next((v for v in volumes if v.get("volume_index") == volume_index), None)
            entry = {
                "volume_index":   volume_index,
                "volume_name":    volume_name,
                "volume_tagline": volume_tagline,
                "start_seq":      start_seq,
                "end_seq":        end_seq,
            }
            if existing:
                volumes[volumes.index(existing)] = entry
            else:
                volumes.append(entry)

            await conn.execute(
                "UPDATE novel_projects SET volumes_json = ?, updated_at = datetime('now') WHERE project_id = ?",
                (json.dumps(volumes, ensure_ascii=False), project_id),
            )
            await conn.commit()
    except Exception:
        pass  # 写卷信息失败不阻断主流程


async def _regenerate_single_node(
    story_path: list,
    target_index: int,
    feedback: str,
    state: dict,
) -> dict:
    """
    只重新生成路径中的某一个节点。
    注入上下文：前一个节点的 output_state 和后一个节点的 input_state（如有）。
    """
    from utils.llm import call_llm_json
    from prompts.creation.path_gen import SINGLE_NODE_REGEN_SYSTEM

    prev_node = story_path[target_index - 1] if target_index > 0 else None
    next_node = story_path[target_index + 1] if target_index < len(story_path) - 1 else None
    current_node = story_path[target_index]

    import json
    user_prompt = f"""
## 当前节点（需要修改）
{json.dumps(current_node, ensure_ascii=False, indent=2)}

## 用户修改意见
{feedback}

## 上下文约束
前一个节点结尾状态：{prev_node.get('output_state_hint', '') if prev_node else '无（这是第一个节点）'}
下一节点标题（事件链既定接续；线头/next_node_trigger 只可过渡到该节点，禁止虚构链外新事件顶替）：{next_node.get('node_name', '') if next_node else '无（这是本批最后一个节点）'}
后一个节点开始状态：{next_node.get('input_state_hint', '') if next_node else '无（这是最后一个节点）'}

## 要求
只重新生成这一个节点，保持与前后节点的连续性。
返回单个节点的 JSON，格式与原节点完全一致。只返回 JSON，不加任何前言。
"""
    result = await call_llm_json(SINGLE_NODE_REGEN_SYSTEM, user_prompt)
    return result if isinstance(result, dict) else {}


async def human_review_path_node(state: CreationState) -> Command:
    """
    故事路径审核节点：
      - 旧流程：暂停执行，展示 story_path 给用户
      - v4.3 流程：展示 current_event_paths 中的 paths[]，含 narrative_function、
                  foreshadow_embedded、path_to_next 等新字段
      - 用户 approve → 进入写作循环（旧：expand1；v4.3：expand1_v43，由 graph 路由决定）
      - 用户 revise  → 重新规划路径（旧：path_gen；v4.3：path_gen_v43）
    """
    # ── v4.3 流程分支 ──────────────────────────────────────────────────────────
    current_event_paths: dict = state.get("current_event_paths") or {}
    if current_event_paths:
        paths = current_event_paths.get("paths") or []
        event_id   = current_event_paths.get("event_id", "")
        event_name = current_event_paths.get("event_name", "")
        total_paths = current_event_paths.get("total_paths", len(paths))
        rhythm_note = current_event_paths.get("rhythm_note", "")

        # 格式化路径列表，突出 v4.3 新字段
        def _fmt_path(p: dict) -> dict:
            return {
                "path_id":           p.get("path_id", ""),
                "path_name":         p.get("path_name", ""),
                "narrative_function": p.get("narrative_function", ""),
                "scene_core":        p.get("scene_core", ""),
                "foreshadow_embedded": p.get("foreshadow_embedded") or [],
                "path_to_next":      p.get("path_to_next", ""),
                "estimated_chapters": p.get("estimated_chapters", 1),
            }

        user_input = interrupt({
            "type": "path_review_v43",
            "content": {
                "event_id":    event_id,
                "event_name":  event_name,
                "total_paths": total_paths,
                "rhythm_note": rhythm_note,
                "paths":       [_fmt_path(p) for p in paths],
            },
            "prompt": (
                "请确认本事件的路径拆解（v4.3）：\n"
                "[1] 满意，开始逐路径落地\n"
                "[2] 修改意见（重新拆解路径）\n"
                "每个路径包含：narrative_function（叙事功能）、"
                "foreshadow_embedded（嵌入伏笔）、path_to_next（过渡勾子）"
            ),
        })

        if not isinstance(user_input, dict):
            return Command(
                update={"path_approved": False},
                goto="path_gen_v43",
            )

        action = user_input.get("action", "approve")

        if action in ("revise", "regenerate"):
            feedback = user_input.get("feedback", "")
            current_event = dict(state.get("current_event") or {})
            if feedback:
                current_event["path_gen_feedback"] = feedback
            return Command(
                update={
                    "path_approved":   False,
                    "current_event":   current_event,
                },
                goto="path_gen_v43",
            )

        if action == "edit" and user_input.get("edited_paths"):
            edited = dict(current_event_paths)
            edited["paths"] = list(user_input["edited_paths"])
            return Command(
                update={
                    "path_approved":       True,
                    "current_event_paths": edited,
                },
                goto="expand1_v43",
            )

        # approve
        return Command(
            update={"path_approved": True},
            goto="expand1_v43",
        )

    # ── 旧流程 ─────────────────────────────────────────────────────────────────
    story_path     = state.get("story_path", [])
    volume_name    = state.get("volume_name", "")
    volume_tagline = state.get("volume_tagline", "")
    batch_index    = state.get("batch_index", 0)

    user_input = interrupt({
        "type": "path_review",
        "content": {
            "nodes":          story_path,
            "volume_name":    volume_name,
            "volume_tagline": volume_tagline,
            "volume_index":   batch_index + 1,
        },
        "prompt": (
            "[1] 满意，开始写作\n"
            "[2] 修改某个节点\n"
            "[3] 重新规划全部路径"
        ),
    })

    if user_input.get("action") == "approve":
        project_id = state.get("project_id", "")
        try:
            seq_offset   = await _get_done_node_count(project_id)
            updated_path = await _insert_story_nodes(project_id, story_path, seq_offset)
        except Exception:
            seq_offset   = 0
            updated_path = story_path

        # 保存卷信息到 DB
        await _save_volume_to_db(
            project_id    = project_id,
            volume_index  = batch_index + 1,
            volume_name   = volume_name,
            volume_tagline= volume_tagline,
            start_seq     = seq_offset + 1,
            end_seq       = seq_offset + len(story_path),
        )

        return Command(
            update={
                "path_approved":      True,
                "current_node_index": 0,
                "story_path":         updated_path,
            },
            goto="expand1",
        )
    elif user_input.get("action") == "edit_node":
        # 只重新生成用户指定的某个节点
        target_index = user_input.get("node_index", 0)
        feedback = user_input.get("feedback", "")

        updated_node = await _regenerate_single_node(
            story_path, target_index, feedback, state
        )
        new_path = [n for n in story_path]
        if 0 <= target_index < len(new_path) and updated_node:
            new_path[target_index] = {**story_path[target_index], **updated_node}

        return Command(
            update={
                "story_path":     new_path,
                "path_approved":  False,
            },
            goto="human_review_path",  # 重新展示修改后的路径
        )
    else:
        # 重新规划全部
        feedback = user_input.get("feedback", "")
        synopsis = state.get("synopsis", {})
        return Command(
            update={
                "path_approved": False,
                "synopsis": {**synopsis, "path_feedback": feedback},
            },
            goto="path_gen",
        )
