"""
DeepNovel CLI 入口

用法：
  uv run python __main__.py extract --source file --path novel.txt
  uv run python __main__.py extract --source url --path https://...
  uv run python __main__.py create --blueprint-id <id> --genre "民俗恐怖"
  uv run python __main__.py list
  uv run python __main__.py search --genre 悬疑 --world-rule realistic
  uv run python __main__.py show --blueprint-id <id>
  uv run python __main__.py resume --thread-id <thread_id>
"""
from __future__ import annotations

# 过滤第三方库的无关警告（必须在所有 import 之前）
import warnings
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*chardet.*")
warnings.filterwarnings("ignore", message=".*charset_normalizer.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="requests")

# 日志配置必须在所有其他 import 之前
from utils.logging_config import setup_logging
setup_logging()

import asyncio
import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich import box
from langgraph.types import Command

console = Console()

# ── 节点名称映射（key = 图中的节点函数名）──────────────────────────────────────
NODE_DISPLAY_NAMES = {
    "load":                   "加载骨骼 / 续传检查",
    "idea_forge":             "解析创意脑洞与用户锚点",
    "genesis_ignition":       "生成开篇种子正文",
    "iceberg_deduction":      "冰山反推（世界快照 + 宏观构思）",
    "human_review_iceberg":   "等待审核（冰山反推）",
    "framework_parse":        "解析框架文档",
    "human_review_framework": "等待审核（框架解析）",
    "synopsis":               "生成宏观构思",
    "human_review_synopsis":  "等待审核（宏观构思）",
    "world_build":            "生成世界设定卡",
    "human_review_world":     "等待审核（世界设定）",
    "protagonist_card":       "建立主角人物卡",
    "story_arc_plan":          "分卷规划",
    "human_review_story_arc":  "等待审核（分卷规划）",
    "event_chain_gen":           "生成单事件（命运编织）",
    "human_review_event":        "等待审核（单事件）",
    "human_review_event_chain":  "等待审核（事件链）",
    "mode_select":            "选择创作模式",
    "path_gen":               "规划故事路径",
    "path_gen_v43":           "拆解事件路径（v4.3）",
    "human_review_path":      "等待审核（故事路径）",
    "expand1":                "3W1H 分析",
    "expand1_v43":            "路径落地确认（v4.3）",
    "human_review_expand":    "等待审核（事件方向）",
    "expand2":                "场景设计 + 事件链",
    "world_tick":             "三步命运编织（World Tick）",
    "protagonist_collision":  "三步命运编织（主角碰撞）",
    "tension_check":          "张力与逻辑质检",
    "auto_review":            "自动审稿（验骨 + 品味）",
    "write":                  "正文写作",
    "human_review_write":       "等待审核（章节正文）",
    "bible_update":             "更新故事圣经",
    "human_review_role_shift":  "等待审核（角色立场变化）",
    "update_weight":          "调整权重",
    "human_review_batch":     "等待审核（批次完成）",
}

# ─── create 命令 ──────────────────────────────────────────────────────────────

async def _detect_genre_from_background(background: str) -> str:
    """从故事方向里提取最匹配的题材标签"""
    from utils.llm import call_llm_json

    result = await call_llm_json(
        "分析故事背景，提取最匹配的题材标签。只返回 JSON。",
        f"""
故事背景：
{background}

从以下题材中选择最匹配的一个，或自由生成一个简短题材标签：
玄幻修仙 / 重生穿越 / 都市职场 / 古代权谋 / 悬疑推理 /
末日科幻 / 民国年代 / 恐怖灵异 / 盗墓探险 / 民间灵异 /
校园 / 家庭 / 婚礼 / 情侣日常 / 霸总 / 现代重生

返回 JSON：
{{"genre": "题材标签"}}
""",
    )
    return (result or {}).get("genre", "现代都市")


async def _select_genre_from_list() -> str:
    """展示题材列表让用户选择"""
    genres = [
        "玄幻修仙", "重生穿越", "都市职场", "古代权谋",
        "悬疑推理", "末日科幻", "民国年代", "恐怖灵异",
        "盗墓探险", "民间灵异", "校园", "霸总",
    ]
    console.print("\n请选择题材：")
    for i, g in enumerate(genres):
        console.print(f"  [{i+1}] {g}")
    console.print("  [0] 手动输入")

    choice = input("\n请输入编号：").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(genres):
        return genres[int(choice) - 1]
    return input("请输入题材：").strip() or "现代都市"


def _load_background(user_input: str) -> str:
    """
    判断用户输入是文件路径还是直接文字。
    支持 .txt 和 .md 文件，其他格式提示不支持。
    """
    path = Path(user_input)

    if path.suffix.lower() in (".txt", ".md"):
        if not path.exists():
            console.print(f"[red]✗[/red]  文件不存在：{user_input}")
            console.print("请重新输入故事方向：")
            return _load_background(input("> ").strip())

        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                console.print(f"[red]✗[/red]  文件内容为空：{user_input}")
                console.print("请重新输入故事方向：")
                return _load_background(input("> ").strip())
            console.print(f"[dim]已读取文件：{path.name}（{len(content)} 字）[/dim]")
            return content
        except Exception as e:
            console.print(f"[red]✗[/red]  文件读取失败：{e}")
            console.print("请重新输入故事方向：")
            return _load_background(input("> ").strip())

    elif path.suffix.lower() in (".docx", ".pdf", ".xlsx", ".doc"):
        console.print(f"[yellow]⚠[/yellow]  不支持 {path.suffix} 格式，仅支持 .txt 和 .md")
        console.print("请重新输入故事方向或使用支持的文件格式：")
        return _load_background(input("> ").strip())

    else:
        return user_input


async def _detect_gender_and_platform(background: str) -> dict:
    """根据故事背景判断主角性别和推荐平台。"""
    from prompts.creation.story_direction import (
        DETECT_GENDER_PLATFORM_SYSTEM,
        DETECT_GENDER_PLATFORM_USER,
    )
    from utils.llm import call_llm_json

    result = await call_llm_json(
        DETECT_GENDER_PLATFORM_SYSTEM,
        DETECT_GENDER_PLATFORM_USER.format(background=background),
    )
    return result or {}


async def _extract_all_from_background(
    background: str, platform: str, genre: str
) -> dict:
    """根据故事方向创作生成全部设定（synopsis + world_setting + protagonist_card）。"""
    from prompts.creation.story_direction import (
        EXTRACT_ALL_SYSTEM,
        EXTRACT_ALL_USER,
    )
    from utils.llm import call_llm_json

    result = await call_llm_json(
        EXTRACT_ALL_SYSTEM,
        EXTRACT_ALL_USER.format(
            background=background,
            platform=platform,
            genre=genre,
        ),
    )
    return result or {}


async def create_command(args):
    from memory.db import init_db
    from memory.checkpointer import close_checkpointer
    from graph.creation.graph import build_creation_graph
    from config import DB_PATH

    await init_db()

    # 若只传 --project-id 不传 --genre，视为续传：从 DB 读取项目信息
    genre = args.genre
    blueprint_id = args.blueprint_id
    weight = args.weight
    project_id = args.project_id or f"proj_{uuid.uuid4().hex[:8]}"
    platform_style = ""  # 续传时从 DB 读取，新项目时用户选择
    background = None  # 用户输入的故事方向（仅故事方向模式使用）
    user_raw_seed = (getattr(args, "idea", None) or "").strip()  # CLI 脑洞，写入 state.user_raw_input
    creation_mode = "auto"
    framework_file_path = ""  # 框架导入时设为文件路径，三选一/二选一可能已设置

    if args.project_id and not genre:
        import aiosqlite
        try:
            async with aiosqlite.connect(str(DB_PATH)) as conn:
                conn.row_factory = aiosqlite.Row
                cursor = await conn.execute(
                    "SELECT genre_request, blueprint_id, platform_style FROM novel_projects WHERE project_id = ?",
                    (args.project_id,),
                )
                row = await cursor.fetchone()
                if row and row["genre_request"]:
                    genre = row["genre_request"]
                    blueprint_id = blueprint_id or (row["blueprint_id"] or "")
                    # 续传时若无 platform_style（老项目或 ALTER 后未回填），默认通用网文并跳过选择
                    platform_style = (row["platform_style"] or "").strip() or "通用网文"
                    console.print(f"[dim]续传项目，已读取题材：{genre}[/dim]")
                else:
                    console.print(
                        f"[red]未找到项目 {args.project_id}，请先创建新项目或使用 novels 命令查看已有项目。[/red]\n"
                        f"创建新项目示例：uv run python __main__.py create --genre 民俗恐怖"
                    )
                    return
        except Exception as e:
            console.print(f"[red]读取项目失败：{e}[/red]")
            return
    elif not genre:
        console.print("\n[bold]请选择创建方式：[/bold]")
        console.print("  [1] 自动生成（只需提供题材，全部由系统推演）")
        console.print("  [2] 提供脑洞/大纲（可输入设定片段或 .txt/.md 文件）")
        mode = input("\n请输入选项 [回车=1]：").strip() or "1"

        if mode == "2":
            console.print("\n[bold]请先输入故事脑洞、核心人设，或 .txt / .md 文档路径：[/bold]")
            console.print("[dim]（越详细越利于锚点解析；分析完题材后再进入创作流）[/dim]")
            user_input = input("> ").strip()
            if user_input:
                path = Path(user_input)
                if path.is_file() and path.suffix.lower() in (".txt", ".md"):
                    framework_file_path = str(path.resolve())
                    try:
                        doc_text = path.read_text(encoding="utf-8").strip()
                    except OSError:
                        doc_text = ""
                    if doc_text:
                        with console.status("[bold cyan]根据文档分析题材…[/bold cyan]"):
                            genre = await _detect_genre_from_background(doc_text)
                        console.print(f"[dim]推断题材：{genre}[/dim]")
                    else:
                        console.print("[yellow]文档为空或无法读取，请手动选择题材。[/yellow]")
                        genre = await _select_genre_from_list()
                else:
                    user_raw_seed = user_input
                    with console.status("[bold cyan]根据脑洞分析题材…[/bold cyan]"):
                        genre = await _detect_genre_from_background(user_raw_seed)
                    console.print(f"[dim]推断题材：{genre}[/dim]")
            else:
                console.print("[dim]未输入脑洞，请手动选择题材。[/dim]")
                genre = await _select_genre_from_list()
        else:
            genre = await _select_genre_from_list()

    # 新项目且 genre 来自 --genre 时，选择创建方式
    story_direction_result = {}
    if not args.project_id and args.genre and not user_raw_seed and not framework_file_path:
        console.print("\n[bold]请选择创建方式：[/bold]")
        console.print("  [1] 自动生成（全部由系统推演）")
        console.print("  [2] 提供脑洞/大纲（可输入设定片段或 .txt/.md 文件）")
        mode_choice = input("请输入选项 [回车=1]：").strip() or "1"
        if mode_choice == "2":
            console.print("\n[bold]请随意输入您的故事脑洞、核心人设，或者输入设定文件的路径：[/bold]")
            console.print(r"[dim]（支持 .txt / .md，越详细系统越忠于原意）：[/dim]")
            user_input = input("> ").strip()
            if user_input:
                path = Path(user_input)
                if path.exists() and path.suffix.lower() in (".txt", ".md"):
                    framework_file_path = str(path.resolve())
                else:
                    user_raw_seed = user_input

    creation_mode = "idea_forge"

    console.print(Panel(
        f"[bold magenta]小说创作流 · DeepNovel v4.3[/bold magenta]\n"
        f"题材需求：{genre}\n"
        f"骨骼 ID：{blueprint_id or '（自动匹配）'}\n"
        f"骨骼权重：{weight}\n\n"
        "[dim]初始化链：脑洞分拣 → 世界设定 → 主角人物卡 → 冰山反推 → 开篇种子 → "
        "核心班底（生成+审核）→ 分卷规划 → 单事件生成 → 事件审核 → 路径拆解 → "
        "路径落地确认 → 场景扩写/写作循环[/dim]",
        border_style="magenta",
    ))

    graph = await build_creation_graph()
    # 每项目独立 checkpoint：用 project_id 作 thread_id，避免同题材不同框架共享错误 state
    thread_id = args.thread_id or project_id
    console.print(f"[dim]Thread ID: {thread_id}  项目 ID: {project_id}[/dim]\n")

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 200,}

    # 创作启动时选择目标平台风格（未续传时）
    if not platform_style:
        console.print("\n[bold]请选择目标平台风格：[/bold]")
        console.print("  [1] 番茄男频")
        console.print("  [2] 番茄女频")
        console.print("  [3] 知乎男频")
        console.print("  [4] 知乎女频")
        console.print("  [回车] 通用网文（不限定风格）")
        platform_choice = input("请选择：").strip() or "0"
        platform_style_map = {
            "1": "番茄男频", "2": "番茄女频",
            "3": "知乎男频", "4": "知乎女频",
        }
        platform_style = platform_style_map.get(platform_choice, "通用网文")

    initial_state = {
        "project_id":    project_id,
        "genre_request": genre,
        "blueprint_id":  blueprint_id,
        "blueprint": {},
        "blueprint_weight": args.weight,
        "synopsis": {},
        "synopsis_approved": False,
        "story_path": [],
        "path_approved": False,
        "current_node_index": 0,
        "current_expand1": {},
        "current_expand2": {},
        "current_draft": "",
        "bible": {
            "characters":            {},
            "events":                [],
            "planted_foreshadows":   [],
            "collected_foreshadows": [],
            "world_state":           "",
        },
        "pivot_records": [],
        "post_pivot": False,
        "completed_chapters": [],
        "creation_complete": False,
        "free_creation":            False,
        "resume_from_db":           False,
        "expand1_event_draft":      [],
        "expand1_approved":         False,
        "pending_event_path_chain": [],
        "chapter_approved":         False,
        "world_setting":            {},
        "world_setting_confirmed":  False,
        "world_setting_feedback":   "",
        "protagonist_name":         "",
        "protagonist_card_feedback": "",
        "protagonist_user_input":   {},
        "last_action_intent":       "",
        "platform_style":           platform_style,
        "creation_mode":            creation_mode or "auto",
        "story_direction_result":   {},
        "auto_mode":                False,
        "max_chapters":             0,
        "auto_retry_count":         0,
        "auto_retry_count_path":   0,
        "auto_retry_count_expand":  0,
        "auto_retry_count_write":   0,
        "auto_total_retry_count":   0,
        "tension_retry_count":      0,
        "tension_minor_issues":     [],
        "pending_review_type":      "",
        "pending_char_cards":       [],
        "confirmed_char_cards":     [],
        "pending_role_shifts":      [],
        "pending_ability_checks":   [],
        "ability_decisions":        [],
        "pending_trait_interaction_update": [],
        "pending_noun_foreshadows":         [],
        "noun_foreshadow_story_potential_edits": {},
        "volume_name":              "",
        "volume_tagline":           "",
        "batch_index":              0,
        "matched_genres":           [],
        "genre_dicts":              [],
        "user_raw_input":           user_raw_seed,
        "user_anchors":             {},
        "framework_file_path":      framework_file_path,
        "framework_parsed":         {},
        "volumes_draft":            [],
        "user_write_rules":         "",
        "current_volume_index":     0,
        "protagonist_card":         {},
        "core_cast":                {},
        "core_cast_draft":          {},
        "story_arc_volumes_draft":  [],
        "story_arc_regen_feedback": "",
        "volumes":                  [],
        # v4.3 单事件流字段
        "current_event":            {},
        "current_event_paths":      {},
        "completed_events_summary": [],
        "recent_rhythm":            {},
        "anchor_progress":          {},
        "path_progress":            {},
        "loop_control":             {},
        "arc_completion_summary":   {},
        "current_event_chain":      [],
        "current_event_chain_pos":  0,
        "event_chain_draft":        [],
        "last_event_batch_size":    0,
        "genesis_variables":        {},
        "genesis_opening_text":      "",
        "genesis_opening_candidate": "",
        "genesis_opening_feedback":  "",
        "skip_world_build_regen":    False,
        "genesis_protagonist_card":  {},
        "iceberg_review_payload":    {},
        "iceberg_deduction_feedback": "",
        "iceberg_stage1_world_raw":  {},
        "iceberg_stage1_cast_raw":   {},
        "iceberg_synopsis_only":       False,
        "iceberg_world_snapshot":      {},
        "world_archive":               {},
        "protagonist_archive":         {},
        "karmic_ledger":               [],
        "creation_flow_version":       "v4.3",
        "current_world_tick":          {},
        "current_protagonist_collision": {},
        "error": None,
    }

    # ── 续传时：优先处理 checkpointer 中残留的 pending interrupt ────────────────
    # 当用户在 interrupt 节点（如事件链确认）退出后，用 --project-id 续传时，
    # LangGraph 可能把 initial_state dict 当成旧 interrupt 的 resume 值，导致
    # 确认步骤被静默跳过。在此处提前检测并以正常交互方式处理。
    input_data = initial_state
    if project_id:
        try:
            _pre_snapshot = await graph.aget_state(config)
            _pre_interrupts: list = []
            if _pre_snapshot and _pre_snapshot.tasks:
                for _t in _pre_snapshot.tasks:
                    _pre_interrupts.extend(_t.interrupts)
            if _pre_interrupts:
                console.print(
                    "[dim]检测到上次中断点，优先恢复确认步骤...[/dim]"
                )
                _interrupt_data = _pre_interrupts[0].value
                _user_response = await _handle_interrupt(_interrupt_data)
                input_data = Command(resume=_user_response)
        except Exception:
            pass  # checkpointer 读取失败时降级为正常 initial_state 流程

    try:
        # ── 主循环：处理 interrupt 和正常执行 ──────────────────────────────────
        while True:
            final_state = await _run_with_streaming(graph, input_data, config)

            # ★ 从 checkpointer 读取当前状态，判断是否有 interrupt
            state_snapshot = await graph.aget_state(config)
            
            # 收集所有 task 里的 interrupt
            pending_interrupts = []
            for task in state_snapshot.tasks:
                pending_interrupts.extend(task.interrupts)

            if not pending_interrupts:
                break  # 没有 interrupt，正常完成

            # 有 interrupt，取第一个处理
            interrupt_data = pending_interrupts[0].value
            user_response = await _handle_interrupt(interrupt_data)
            input_data = Command(resume=user_response)

        console.print("\n[bold green]✓ 创作完成！[/bold green]")
        _print_creation_result(final_state, args)

    except KeyboardInterrupt:
        console.print("\n[yellow]已中断，下次运行将自动从断点续传。[/yellow]")
    finally:
        await close_checkpointer()


async def _run_with_streaming(graph, input_data, config: dict) -> dict:
    """
    使用最新 LangGraph multi-mode 流式 API 运行图：
      stream_mode=["updates", "messages", "custom"]

    - custom   → 节点启动通知（由节点内 StreamWriter 发出）
    - messages → LLM token 流（write 节点实时打字输出）
    - updates  → 节点完成通知（✓），用于跟踪状态更新
    遇到 interrupt 时 astream 迭代器自然终止。
    """
    from langchain_core.messages import AIMessageChunk

    accumulated_state: dict = {}  # 跨节点累积关键 state 字段（用于 write 完成后读事件链）

    async for event_type, payload in graph.astream(
        input_data,
        config=config,
        stream_mode=["updates", "messages", "custom"],
    ):
        # ── 自定义事件：节点启动通知 / 核心配角升级 ──────────────────────────
        if event_type == "custom":
            if payload.get("node_status") == "core_char_promoted":
                name   = payload.get("character_name", "")
                role   = payload.get("upgrade_role", "neutral")
                pos    = payload.get("pos_count", 0)
                neg    = payload.get("neg_count", 0)
                if role == "antagonist":
                    console.print(
                        Panel(
                            f"「{name}」已对主角造成 {neg} 次实质性伤害\n\n"
                            "建议确认为反派并完善人物卡\n"
                            "⚠️  true_motive（真实动机）为必填项",
                            title="⚔️  发现潜在反派",
                            border_style="red",
                            expand=False,
                        )
                    )
                elif role == "core_supporting":
                    console.print(
                        Panel(
                            f"「{name}」已与主角共同经历 {pos} 次关键事件\n\n"
                            "建议确认为核心配角并完善人物卡",
                            title="📌  发现潜在核心配角",
                            border_style="cyan",
                            expand=False,
                        )
                    )
                elif role == "neutral":
                    console.print(
                        Panel(
                            f"「{name}」与主角有多次接触但立场不明\n\n"
                            "建议确认为中立者并说明其利益立场",
                            title="⚖️  发现潜在中立者",
                            border_style="yellow",
                            expand=False,
                        )
                    )
                else:
                    console.print(
                        f"\n  [bold yellow]★ 角色升级[/bold yellow]  "
                        f"[cyan]{name}[/cyan] 已参与关键事件"
                    )
                continue

            if payload.get("node_status") == "started":
                node_key     = payload.get("node", "")
                display_name = NODE_DISPLAY_NAMES.get(node_key, "")
                if not display_name:
                    continue
                if node_key == "write":
                    console.print()
                    console.rule(
                        f"[bold white] {display_name} [/bold white]",
                        style="dim",
                    )
                    console.print()
                else:
                    console.print(
                        f"\n  [yellow]→[/yellow] {display_name}...",
                        end="",
                    )

        # ── Token 流：只将 write 节点的输出实时打印到控制台 ──────────────────
        elif event_type == "messages":
            chunk, metadata = payload
            if (
                isinstance(chunk, AIMessageChunk)
                and chunk.content
                and metadata.get("langgraph_node") == "write"
            ):
                console.print(chunk.content, end="", highlight=False)

        # ── 节点完成：状态更新 ────────────────────────────────────────────────
        elif event_type == "updates":
            for node_name, state_update in payload.items():
                if isinstance(state_update, dict):
                    accumulated_state.update(state_update)

                if node_name not in NODE_DISPLAY_NAMES:
                    continue

                if node_name == "write":
                    draft = state_update.get("current_draft", "") if isinstance(state_update, dict) else ""
                    # pending_event_path_chain 由 expand2 设置，从累积 state 中读取
                    chain = accumulated_state.get("pending_event_path_chain", [])
                    console.print()
                    console.print(f"  [green]✓[/green]  [dim]共 {len(draft)} 字[/dim]")
                    if chain:
                        console.print()
                        console.rule("[dim]本章事件路径链（审核时可作为修改参考）[/dim]", style="dim")
                        for i, step in enumerate(chain):
                            console.print(f"  [dim]{i + 1}.[/dim]  {step}")
                        console.print()
                else:
                    console.print(f"  [green]✓[/green]")

    # 从 checkpointer 读取完整 state（cumulative，包含 list 字段的合并值）
    snapshot = await graph.aget_state(config)
    return snapshot.values if snapshot and snapshot.values else {}


async def _handle_interrupt(interrupt_data: dict) -> dict:
    """
    处理 interrupt 节点的用户交互。
    interrupt_data 由 human_review_node 决定结构。
    """
    from utils.display import print_interrupt_prompt
    from utils.protagonist_card_cli_edit import edit_protagonist_card_interactive

    prompt_type = interrupt_data.get("type", "")
    content     = interrupt_data.get("content", {})

    if prompt_type == "mode_select":
        console.print()
        console.print(interrupt_data.get("prompt", "请选择创作模式："))
        choice = input("\n请输入选项：").strip()
        if choice == "2":
            max_ch = input("最大章节数（直接回车=不限制）：").strip()
            max_chapters = int(max_ch) if max_ch.isdigit() else 0
            console.print(f"[dim]自动模式已启动，最大章节数：{max_chapters or '不限制'}[/dim]")
            return {"auto_mode": True, "max_chapters": max_chapters}
        return {"auto_mode": False, "max_chapters": 0}

    if prompt_type == "framework_review":
        content = interrupt_data.get("content", {})
        print_interrupt_prompt(prompt_type, content)
        platform_style = content.get("platform_style", "番茄男频")
        protagonist_name = content.get("protagonist_card", {}).get("standard_name", "主角")
        genre_request = content.get("genre_request", "")

        console.print("\n[green]检测到：[/green]" + platform_style, end="")
        if protagonist_name or genre_request:
            parts = [f"主角{protagonist_name}" if protagonist_name else "", genre_request or ""]
            console.print(f"（{', '.join(p for p in parts if p)}）", end="")
        console.print()
        console.print("[回车] 确认  [1-4] 切换平台：  [1]番茄男频  [2]番茄女频  [3]知乎男频  [4]知乎女频  [r] 重新解析")
        choice = input("\n请输入选项：").strip().lower()
        if choice == "r":
            return {"action": "reparse"}
        platform_style_map = {
            "1": "番茄男频", "2": "番茄女频",
            "3": "知乎男频", "4": "知乎女频",
        }
        if choice in platform_style_map:
            platform_style = platform_style_map[choice]
            console.print(f"[dim]已切换为 {platform_style}[/dim]")
        return {"action": "approve", "edits": {}, "platform_style": platform_style}

    if prompt_type == "event_review":
        event_name = content.get("event_name", "")
        event_id = content.get("event_id", "")
        event_summary = content.get("event_summary", "")
        collision = content.get("collision", {}) or {}
        anchor_check = content.get("anchor_check", {}) or {}
        global_check = content.get("global_context_check", {}) or {}

        console.print(Panel(
            f"[bold]事件：[/bold]{event_name}  [dim]({event_id})[/dim]\n\n"
            f"[bold]摘要：[/bold]{event_summary}\n\n"
            f"[bold]冲突面：[/bold]{collision.get('conflict_surface', '')}\n"
            f"[bold]反转点：[/bold]{collision.get('twist', '')}\n\n"
            f"[bold]锚点检查：[/bold]{anchor_check}\n"
            f"[bold]全局一致性：[/bold]{global_check}",
            title="📌 单事件审核（v4.3）",
            border_style="cyan",
            expand=False,
        ))

        console.print("\n[cyan][1][/cyan] 通过，进入路径拆解")
        console.print("[cyan][2][/cyan] 编辑事件（覆盖 full_event）")
        console.print("[cyan][3][/cyan] 重新生成本事件")
        choice = input("\n请输入选项：").strip()
        if choice == "3":
            return {"action": "regenerate"}
        if choice == "2":
            full_event = interrupt_data.get("full_event", {}) or {}
            edited = dict(full_event)
            new_name = input(f"event_name（回车保留）[{edited.get('event_name', '')}]：").strip()
            new_summary = input(f"event_summary（回车保留）[{edited.get('event_summary', '')}]：").strip()
            if new_name:
                edited["event_name"] = new_name
            if new_summary:
                edited["event_summary"] = new_summary
            return {"action": "edit", "edited_event": edited}
        return {"action": "approve"}

    if prompt_type == "path_review_v43":
        event_name = content.get("event_name", "")
        total_paths = content.get("total_paths", 0)
        paths = content.get("paths", []) or []
        console.print(Panel(
            f"[bold]事件：[/bold]{event_name}\n"
            f"[bold]路径数：[/bold]{total_paths}",
            title="🗺 路径审核（v4.3）",
            border_style="cyan",
            expand=False,
        ))
        for idx, p in enumerate(paths, 1):
            foreshadow = p.get("foreshadow_embedded", [])
            fcnt = len(foreshadow) if isinstance(foreshadow, list) else 0
            console.print(
                f"  [bold]{idx}.[/bold] [cyan]{p.get('path_name', '')}[/cyan] "
                f"[dim]{p.get('path_id', '')}[/dim]\n"
                f"      功能：{p.get('narrative_function', '')}  "
                f"伏笔：{fcnt} 条\n"
                f"      过渡：{p.get('path_to_next', '')}"
            )

        console.print("\n[cyan][1][/cyan] 通过，进入路径落地确认")
        console.print("[cyan][2][/cyan] 重新拆解路径（附反馈）")
        choice = input("\n请输入选项：").strip()
        if choice == "2":
            feedback = input("请输入修改意见：").strip()
            return {"action": "revise", "feedback": feedback}
        return {"action": "approve"}

    console.print()
    console.print("[bold]需要人工确认[/bold]")
    print_interrupt_prompt(prompt_type, content)

    if prompt_type == "story_direction_review":
        synopsis = content.get("synopsis", {})
        world_setting = content.get("world_setting", {})
        protagonist_card = content.get("protagonist_card", {})
        console.print("\n[cyan][1][/cyan] 满意，进入分卷规划")
        console.print("[cyan][2][/cyan] 修改某个字段（逐字段编辑）")
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        else:
            edits = {}
            console.print("\n[dim]直接回车保留原值[/dim]\n")
            # synopsis
            syn_edits = {}
            for key, label in [
                ("title", "标题"), ("world", "世界观"), ("protagonist", "主角"),
                ("core_conflict", "核心冲突"), ("direction", "走向"),
            ]:
                cur = synopsis.get(key, "")
                new_val = input(f"  synopsis.{label}（回车保留）：").strip()
                if new_val:
                    syn_edits[key] = new_val
            if syn_edits:
                edits["synopsis"] = syn_edits
            # protagonist_card 主要字段
            pc_edits = {}
            for key, label in [
                ("standard_name", "标准名"), ("appearance", "外貌"),
                ("background_summary", "背景经历"),
            ]:
                cur = protagonist_card.get(key, "")
                new_val = input(f"  protagonist.{label}（回车保留）：").strip()
                if new_val:
                    pc_edits[key] = new_val
            if pc_edits:
                edits["protagonist_card"] = pc_edits
            return {"action": "edit", "edits": edits}

    if prompt_type == "core_cast_review":
        console.print("\n[cyan][1][/cyan] 确认，进入分卷规划（核心班底已定稿）")
        console.print("[cyan][2][/cyan] 重新生成班底")
        choice = input("\n请输入选项：").strip()
        if choice == "2":
            return {"action": "regenerate"}
        return {"action": "approve"}

    if prompt_type == "story_arc_review":
        console.print("\n[cyan][1][/cyan] 确认分卷规划")
        console.print(
            "[cyan][2][/cyan] 调整章节数（格式：1=25，多个用空格分隔，表示第1卷改为25章）"
        )
        console.print("[cyan][3][/cyan] 重新生成分卷（可附修改意见）")
        choice = input("\n请输入选项：").strip()
        if choice == "2":
            adjustments_input = input("> ").strip()
            adjustments: dict = {}
            for item in adjustments_input.split():
                if "=" in item:
                    vol_str, ch_str = item.split("=", 1)
                    if vol_str.isdigit() and ch_str.isdigit():
                        adjustments[str(int(vol_str) - 1)] = int(ch_str)
            return {"action": "approve", "edits": {"chapter_adjustments": adjustments}}
        if choice == "3":
            console.print(
                "\n[dim]请输入希望如何调整分卷（卷名节奏、反派层级、地点闭环、情感线比重等；"
                "直接回车则仅整体重算）：[/dim]"
            )
            fb_arc = input("> ").strip()
            return {"action": "regenerate", "feedback": fb_arc}
        return {"action": "approve"}

    if prompt_type == "event_chain_review":
        console.print("\n[cyan][1][/cyan] 确认，生成本批故事路径")
        console.print("[cyan][2][/cyan] 重新生成事件链")
        choice = input("\n请输入选项：").strip()
        if choice == "2":
            return {"action": "regenerate"}
        return {"action": "approve"}

    if prompt_type == "opening_review":
        variables = content.get("variables") or {}
        console.print(
            "\n[cyan][1][/cyan] 确认开篇种子：下一步生成并审核「全书核心班底」（通过后再进入分卷规划；冰山与世界档案已在前序锁定）"
        )
        console.print("[cyan][2][/cyan] 重新生成开篇种子（可附意见，会重掷变量配方）")
        console.print("[cyan][3][/cyan] 手工修订开篇正文（多行输入，单独一行 END 结束）")
        if variables:
            console.print(
                f"\n[dim]变量桶：{variables.get('genre_bucket', '')}  "
                f"针对度 {variables.get('targeting_degree', '')}  "
                f"逻辑 {variables.get('human_logic', '')}[/dim]"
            )
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        if choice == "2":
            fb = input("修改意见（回车即整体重写）：").strip()
            return {"action": "regenerate", "feedback": fb}
        if choice == "3":
            console.print("[dim]粘贴新开篇，最后一行只输入 END 并回车结束[/dim]")
            lines: list[str] = []
            while True:
                line = input()
                if line.strip() == "END":
                    break
                lines.append(line)
            return {"action": "edit_opening", "opening_text": "\n".join(lines).strip()}
        return {"action": "approve"}

    if prompt_type == "iceberg_review":
        console.print(
            "\n[cyan][1][/cyan] 确认：下一步点燃开篇种子；通过后依次为「核心班底」审核、分卷规划（世界设定与主角卡已锁定）"
        )
        console.print("[cyan][2][/cyan] 重新冰山反推（可附意见）")
        choice = input("\n请输入选项：").strip()
        if choice == "2":
            fb = input("希望如何调整反推结果：").strip()
            return {"action": "regenerate", "feedback": fb}
        return {"action": "approve"}

    if prompt_type in ("synopsis_review", "synopsis"):
        synopsis = content if isinstance(content, dict) and "title" in content else {}
        console.print("\n[cyan][1][/cyan] 满意，下一步生成世界设定卡（确认后进入主角人物卡）")
        console.print("[cyan][2][/cyan] 修改某个字段（逐字段编辑）")
        console.print("[cyan][3][/cyan] 修改意见（重新生成）")
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        elif choice == "2":
            # 逐字段编辑，回车保留原值
            console.print("\n[dim]直接回车保留原值，输入新内容则替换[/dim]\n")
            edits = {}
            for key, label in [
                ("title", "标题"),
                ("world", "世界观"),
                ("protagonist", "主角"),
                ("core_conflict", "核心冲突"),
                ("direction", "走向"),
                ("family_emotion_line", "亲情主轴"),
                ("romance_emotion_line", "爱情/红颜"),
                ("core_hook", "核心钩子"),
                ("volume_1_goal", "第一卷目标"),
                ("escalation_path", "格局放大路径"),
                ("ultimate_goal", "全书终极目标"),
                ("opening_seed_text", "开篇种子正文"),
            ]:
                current = synopsis.get(key, "")
                console.print(f"[bold]{label}：[/bold]{current}")
                new_val = input(f"修改为（回车保留）：").strip()
                if new_val:
                    edits[key] = new_val
                console.print()
            return {"action": "edit", "edits": edits}
        else:
            feedback = input("请输入修改意见：").strip()
            return {"action": "revise", "feedback": feedback}

    elif prompt_type in ("path_review", "path"):
        story_path = content.get("nodes", []) if isinstance(content, dict) else content or []
        console.print("\n[cyan][1][/cyan] 满意，开始写作")
        console.print("[cyan][2][/cyan] 修改某个节点")
        console.print("[cyan][3][/cyan] 重新规划全部路径")
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        elif choice == "2":
            # 只修改指定节点
            console.print("\n请输入要修改的节点编号（1开始）：")
            node_num = input("编号：").strip()
            if node_num.isdigit():
                node_index = int(node_num) - 1
                target = story_path[node_index] if 0 <= node_index < len(story_path) else None
                if target:
                    console.print(f"\n当前第{node_num}节：")
                    console.print(f"  {target.get('node_name', '')}")
                    console.print(f"  {target.get('one_liner', '')}")
                    feedback = input("\n修改意见：").strip()
                    return {
                        "action":     "edit_node",
                        "node_index": node_index,
                        "feedback":   feedback,
                    }
            return {"action": "approve"}
        else:
            feedback = input("请输入重新规划的意见：").strip()
            return {"action": "regenerate_all", "feedback": feedback}

    elif prompt_type == "expand_review":
        console.print("\n[cyan][1][/cyan] 路径正确，继续写作")
        console.print("[cyan][2][/cyan] 修改路径 - 请附上修改意见（仅重跑 expand1，代价小）")
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        else:
            feedback = input("请输入修改意见：").strip()
            return {"action": "revise", "feedback": feedback}

    elif prompt_type == "role_shift_review":
        shifts    = content.get("shifts", [])
        responses = []

        for shift in shifts:
            name = shift.get("character_name", "?")
            console.print(f"\n[bold]「{name}」的立场处理：[/bold]")
            console.print("[cyan][1][/cyan] 确认转变，更新为对立关系")
            console.print("[cyan][2][/cyan] 这是误会或隐情，保持当前立场")
            console.print("[cyan][3][/cyan] 灰色地带（表面盟友/实为对立，模型知道真相）")
            choice = input(f"\n请输入选项（{name}）：").strip()

            resp: dict = {"character_name": name}

            if choice == "1":
                resp["decision"] = "confirm"
                true_motive = input("真实动机（留空则不填，可作为伏笔来源）：").strip()
                if true_motive:
                    resp["true_motive"] = true_motive

            elif choice == "3":
                resp["decision"] = "gray_area"
                surface_role = shift.get("current_role", "盟友")
                resp["surface_role"] = surface_role
                true_motive = input("真实动机（留空则不填）：").strip()
                if true_motive:
                    resp["true_motive"] = true_motive

            else:
                resp["decision"] = "misunderstanding"

            responses.append(resp)

        return {"responses": responses}

    elif prompt_type == "protagonist_input":
        # 说明已由 print_interrupt_prompt 展示，避免重复 Panel
        impression = input("\n请输入（可回车跳过）：").strip()
        return {"protagonist_impression": impression}

    elif prompt_type == "protagonist_review":
        card = content.get("card", {})
        if not isinstance(card, dict):
            card = {}
        console.print(
            "\n[cyan][1][/cyan] 确认并锁定主角人物卡（下一步：冰山反推 → 开篇种子 → 核心班底 → 分卷规划）"
        )
        console.print(
            "[cyan][2][/cyan] 逐字段编辑（PROMPT 3 全字段；见 docs 与 prompts/world_build 模板；回车保留）"
        )
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve", "confirmed_card": card}
        confirmed = edit_protagonist_card_interactive(card, console=console)
        return {"action": "approve", "confirmed_card": confirmed}

    elif prompt_type == "world_review":
        # print_interrupt_prompt 已在顶部调用，直接从 content 里的 world_setting 渲染
        console.print("\n[cyan][1][/cyan] 确认，锁定世界设定，进入主角人物卡")
        console.print("[cyan][2][/cyan] 修改 - 请附上修改意见（重新生成）")
        choice = input("\n请输入选项：").strip()
        if choice == "1":
            return {"action": "approve"}
        else:
            feedback = input("请输入修改意见：").strip()
            return {"action": "revise", "feedback": feedback}

    elif prompt_type == "write_review":
        has_new_chars       = content.get("has_new_characters", False)
        new_char_cards      = interrupt_data.get("new_character_cards", [])
        ability_checks      = content.get("pending_ability_checks", [])
        noun_foreshadows    = content.get("pending_noun_foreshadows", [])
        new_foreshadows     = content.get("new_foreshadows", [])
        trait_updates       = content.get("pending_trait_interaction_update", [])
        project_id          = interrupt_data.get("project_id", "")

        console.print("\n[cyan][1][/cyan] 满意，保存并继续下一章")
        console.print(
            "[cyan][2][/cyan] 改写文笔与节奏 [dim]（小修：剧情/expand1 不动，只重跑 expand2+write；"
            "意见写对话、画面、代价、节奏，勿在此改走向）[/dim]"
        )
        console.print(
            "[cyan][3][/cyan] 推翻剧情走向 [dim]（大修：回到 expand1 重排因果；"
            "可写「主角故意输」「留活口」等，大白话即可，系统会解析）[/dim]"
        )
        choice = input("\n请输入选项：").strip()

        if choice == "1":
            confirmed_cards = list(new_char_cards)  # 默认使用草稿
            if has_new_chars and new_char_cards:
                console.print("\n[yellow]检测到新人物首次出场，请确认人物卡草稿[/yellow]")
                console.print(
                    "[dim]💡 可编辑外貌/倾向：此处定稿会写入圣经，后续章节沿用你改的「面子」与习惯小动作。[/dim]"
                )
                for i, card in enumerate(new_char_cards):
                    console.print(
                        f"\n  [{i+1}] {card.get('standard_name', '?')}\n"
                        f"      外貌：{card.get('appearance', '')}\n"
                        f"      先天底色：\n" +
                        "\n".join(f"        • {t}" for t in (card.get("innate_traits") or []))
                    )
                edit_choice = input("\n是否修改人物卡？[y/n]：").strip().lower()
                if edit_choice == "y":
                    confirmed_cards = []
                    for card in new_char_cards:
                        console.print(f"\n编辑 [{card.get('standard_name', '')}]")
                        appearance = input(f"  外貌（回车保留）[{card.get('appearance', '')}]：").strip()
                        confirmed_cards.append({
                            **card,
                            "appearance": appearance or card.get("appearance", ""),
                        })

            # ── 未记录能力确认 ──────────────────────────────────────────────
            ability_decisions: list[dict] = []
            if ability_checks:
                console.print("\n[yellow]检测到未记录的能力，请逐一确认：[/yellow]")
                console.print(
                    "[dim]💡 若实为修辞（如「目光如电」），请选 [3] 笔误忽略，避免把比喻当功法入库。[/dim]"
                )
                for ab in ability_checks:
                    ab_name   = ab.get("ability_name", "?")
                    ab_char   = ab.get("char_name", "未知")
                    console.print(f"\n  能力「[bold]{ab_name}[/bold]」（{ab_char} 使用）")
                    console.print("  [cyan][1][/cyan] 这是新能力，现在添加到人物卡")
                    console.print("  [cyan][2][/cyan] 这是已有能力的自然延伸，不需要单独记录")
                    console.print("  [cyan][3][/cyan] 这是笔误，正文里不应该出现（忽略）")
                    ab_choice = input("  请选择：").strip()
                    decision  = {"1": "add", "2": "extend", "3": "ignore"}.get(ab_choice, "extend")
                    entry: dict = {"ability_name": ab_name, "char_name": ab_char, "decision": decision}
                    if decision == "add":
                        ab_type = input(
                            "  能力类型（功法/道具/身体素质/社会资源/知识/特异能力，回车跳过）："
                        ).strip() or "特异能力"
                        ab_desc = input("  简短描述（30字以内，回车跳过）：").strip()
                        ab_limit = input("  限制/代价（回车跳过）：").strip()
                        entry["ability_type"]    = ab_type
                        entry["ability_desc"]    = ab_desc
                        entry["ability_limit"]   = ab_limit
                    ability_decisions.append(entry)

            # ── 伏笔性质确认（首次提取时逐条询问）────────────────────────────────
            if new_foreshadows and project_id:
                from memory.db import update_foreshadow_nature
                for f in new_foreshadows:
                    surf = f.get("surface_meaning", "")
                    fid = f.get("foreshadow_id", "")
                    if not surf or not fid:
                        continue
                    console.print(f"\n[dim]确认伏笔性质：[/dim] {surf}")
                    console.print("  [cyan][1][/cyan] 普通伏笔（系统管理推进节奏）")
                    console.print("  [cyan][2][/cyan] 持续引力（贯穿全书，由我决定揭露时机）")
                    nature = input("  请选择 [1/2，回车默认1]：").strip() or "1"

                    if nature == "2":
                        await update_foreshadow_nature(fid, mystery_type="permanent", urgency="latent")
                    else:
                        console.print("  回收节奏：")
                        console.print("  [cyan][A][/cyan] 尽快回收（下1-2批安排）")
                        console.print("  [cyan][B][/cyan] 自定义阈值（出现N次后触发）")
                        rhythm = input("  请选择 [A/B，回车默认A]：").strip().upper() or "A"

                        if rhythm == "A":
                            await update_foreshadow_nature(fid, urgency="ready", ready_threshold=1)
                        else:
                            console.print("  阈值参考：3-5=普通伏笔  6+=贯穿多卷的重要线索")
                            t = input("  请输入阈值 [回车默认3]：").strip()
                            threshold = int(t) if t.isdigit() else 3
                            threshold = max(1, min(threshold, 20))
                            await update_foreshadow_nature(fid, ready_threshold=threshold, urgency="latent")

            # ── 词条伏笔展示及 story_potential 补充 ─────────────────────────────
            noun_foreshadow_story_potential_edits: dict = {}
            if noun_foreshadows:
                lines = []
                for f in noun_foreshadows:
                    surf = f.get("surface_meaning", "?")
                    mentioned = f.get("mentioned_by", "")
                    potential = f.get("story_potential", "")
                    lines.append(
                        f"  • [cyan]{surf}[/cyan]  [dim]由 {mentioned} 提及[/dim]\n"
                        f"    潜力方向：{potential or '（未填写）'}"
                    )
                console.print(Panel(
                    "\n".join(lines),
                    title="🔖 新增词条伏笔",
                    border_style="dim",
                    expand=False,
                ))
                edit_potential = input("\n[可选] 为以上词条补充故事方向？[y/n]：").strip().lower()
                if edit_potential == "y":
                    for f in noun_foreshadows:
                        surf = f.get("surface_meaning", "")
                        if not surf:
                            continue
                        suggested = f.get("story_potential", "")
                        new_val = input(
                            f"  「{surf}」故事方向（回车保留）[{suggested}]："
                        ).strip()
                        if new_val:
                            noun_foreshadow_story_potential_edits[surf] = new_val

            # ── 特质叠加变化确认（上节 bible_update 检测到）─────────────────────
            trait_interaction_confirmed = False
            if trait_updates:
                console.print("\n[yellow]检测到人物性格变化，是否追加新的特质叠加规则？[/yellow]")
                console.print("[Y] 确认并追加  [N] 暂时跳过")
                ti_choice = input("请选择：").strip().upper()
                trait_interaction_confirmed = ti_choice == "Y"

            result: dict = {
                "action":                  "approve",
                "confirmed_char_cards":     confirmed_cards,
                "ability_decisions":       ability_decisions,
                "trait_interaction_confirmed": trait_interaction_confirmed,
            }
            if noun_foreshadow_story_potential_edits:
                result["noun_foreshadow_story_potential_edits"] = noun_foreshadow_story_potential_edits
            return result
        elif choice == "2":
            console.print(
                "[dim]只改写法：对话阴阳气、打斗见伤、节奏松紧、环境细节等；勿写整条新剧情大纲。[/dim]"
            )
            feedback = input("请输入文笔修改意见：").strip()
            return {"action": "rewrite_prose", "feedback": feedback}
        else:
            console.print(
                "[dim]可改走向：谁赢谁输、留不留活口、伏笔人选等；可用【须保留】+【方向】分段，占位名如张三会被换。[/dim]"
            )
            feedback = input("请输入方向修改意见：").strip()
            return {"action": "rewrite_direction", "feedback": feedback}

    elif prompt_type == "batch_review":
        story_path = content.get("story_path", [])
        project_id = content.get("project_id", "")
        status = content.get("story_status", {})
        console.print()

        # 展示本批次完成情况
        from utils.display import print_interrupt_prompt
        print_interrupt_prompt("batch", content)

        # 故事状态面板
        lines = []
        if status.get("permanent"):
            lines.append("[dim]持续引力谜题：[/dim]")
            for f in status["permanent"]:
                lines.append(f"  • {f.get('surface_meaning', '')}  [dim][潜伏中][/dim]")
        if status.get("backbone"):
            lines.append("\n[dim]主线伏笔（未回收）：[/dim]")
            for f in status["backbone"]:
                lines.append(f"  • {f.get('surface_meaning', '')}  [dim][未揭露][/dim]")
        if status.get("pending"):
            lines.append("\n[dim]支线伏笔（待推进）：[/dim]")
            for f in status["pending"]:
                urgency_label = "[red]待引爆[/red]" if f.get("urgency") == "ready" else "[yellow]蓄力[/yellow]"
                lines.append(f"  • {f.get('surface_meaning', '')}  {urgency_label}")
        if lines:
            console.print(Panel(
                "\n".join(lines),
                title="故事状态",
                border_style="dim",
                expand=False,
            ))

        console.print("\n[cyan][1][/cyan] 继续规划下一批节点")
        console.print("[cyan][2][/cyan] 开始揭露核心谜题")
        console.print("[cyan][3][/cyan] 结束创作")

        choice = input("\n请输入选项：").strip()

        if choice == "1":
            return {"action": "continue"}
        elif choice == "2":
            permanent = status.get("permanent", [])
            if not permanent:
                console.print("[dim]当前没有持续引力谜题。[/dim]")
            else:
                for i, f in enumerate(permanent):
                    console.print(f"  [{i+1}] {f.get('surface_meaning', '')}")
                idx = input("选择要开始揭露的谜题编号：").strip()
                if idx.isdigit() and 1 <= int(idx) <= len(permanent):
                    target = permanent[int(idx) - 1]
                    fid = target.get("foreshadow_id", "")
                    if fid:
                        from memory.db import activate_permanent_foreshadow
                        await activate_permanent_foreshadow(fid)
                        console.print(f"[green]✓[/green] 已将「{target.get('surface_meaning', '')}」纳入推进计划")
            return {"action": "continue"}
        else:  # choice == "3" or invalid
            backbone = status.get("backbone", [])
            if backbone:
                names = "、".join(f.get("surface_meaning", "") for f in backbone)
                console.print(
                    f"\n[yellow]⚠[/yellow]  以下主线伏笔尚未回收：{names}\n"
                    "确认结束？[y/n]："
                )
                confirm = input().strip().lower()
                if confirm != "y":
                    # 重新展示选项，递归处理（简化：当作 continue）
                    return {"action": "continue"}
            return {"action": "done"}
    return {"action": "approve"}  # 默认通过


def _print_creation_result(state: dict, args):
    chapters = state.get("completed_chapters", [])
    console.print(Panel(
        f"[green]✓ 创作完成[/green]\n\n"
        f"完成章节：{len(chapters)} 节\n"
        f"总字数：{sum(len(c) for c in chapters)} 字",
        title="创作结果",
        border_style="green",
    ))

    if chapters:
        from config import NOVELS_DIR
        bp_prefix = (args.blueprint_id or "deepnovel")[:8] or "deepnovel"
        out_path = NOVELS_DIR / f"{bp_prefix}_{uuid.uuid4().hex[:6]}.txt"
        out_path.write_text("\n\n---\n\n".join(chapters), encoding="utf-8")
        console.print(f"\n[cyan]正文已保存到：[/cyan]{out_path}")

        console.print("\n[bold cyan]第一章预览：[/bold cyan]")
        console.print(chapters[0][:500] + ("..." if len(chapters[0]) > 500 else ""))


# ─── extract 命令 ─────────────────────────────────────────────────────────────

async def extract_command(args):
    console.print(Panel(
        f"[bold cyan]骨骼提取流[/bold cyan]\n"
        f"来源类型：{args.source}\n"
        f"路径/URL：{args.path}",
        border_style="cyan",
    ))

    from memory.db import init_db
    from memory.checkpointer import run_extraction, close_checkpointer
    from graph.extraction.graph import build_extraction_graph

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("初始化数据库...", total=None)
        await init_db()
        progress.update(task, description="构建图状态机...")
        graph = await build_extraction_graph()
        progress.update(task, description="准备初始状态...")

    state = {
        "source_type": args.source,
        "source_path": args.path,
        "raw_text": "",
        "segments": [],
        "total_segments": 0,
        "current_batch_index": 0,
        "current_pass1a_result": {},
        "batch_summaries": [],
        "entity_registry": {"blueprint_id": "", "entities": []},
        "pass1_context": {},
        "pass2_batch_index": 0,
        "foreshadow_entries": [],
        "is_fragment": args.fragment,
        "extraction_complete": False,
        "error": None,
    }

    thread_id = args.thread_id or hashlib.md5(args.path.encode()).hexdigest()
    console.print(f"[dim]Thread ID: {thread_id}  （断点续传：重新运行相同命令即可）[/dim]\n")

    try:
        final_state = await run_extraction(graph, state, thread_id)
    except KeyboardInterrupt:
        console.print("\n[yellow]已中断，下次运行将自动从断点续传。[/yellow]")
        await close_checkpointer()
        return

    _print_extraction_result(final_state)
    await close_checkpointer()


def _print_extraction_result(state: dict):
    blueprint = state.get("blueprint", {})
    blueprint_id = blueprint.get("blueprint_id", "N/A")
    entity_count = len(state.get("entity_registry", {}).get("entities", []))
    foreshadow_count = len(state.get("foreshadow_entries", []))
    batch_count = state.get("total_segments", 0)

    console.print(Panel(
        f"[green]✓ 提取完成[/green]\n\n"
        f"骨骼 ID：[bold cyan]{blueprint_id}[/bold cyan]\n"
        f"处理批次：{batch_count}\n"
        f"实体数量：{entity_count}\n"
        f"伏笔条目：{foreshadow_count}",
        title="提取结果",
        border_style="green",
    ))

    layer1 = blueprint.get("layer1", {})
    if layer1.get("macro_pacing"):
        console.print(f"\n[cyan]宏观节奏：[/cyan]{layer1.get('macro_pacing', '')}")
    if layer1.get("volume_count"):
        console.print(f"[cyan]卷章结构：[/cyan]{layer1.get('volume_count')} 卷 × {layer1.get('nodes_per_volume')} 节")

    chain_seq = blueprint.get("layer3", {}).get("chain_type_sequence", [])
    if chain_seq:
        console.print(f"\n[cyan]逻辑链序列：[/cyan]{' → '.join(chain_seq[:6])}" + ("..." if len(chain_seq) > 6 else ""))


# ─── resume 命令 ──────────────────────────────────────────────────────────────

async def resume_command(args):
    """
    resume 命令支持两种模式：
      --mode extraction  恢复提取流（默认）
      --mode creation    恢复创作流（断点续传 或 续写下一批）
      --next-batch       续写下一批时加这个 flag，跳转到 path_gen
    """
    from memory.db import init_db
    from memory.checkpointer import close_checkpointer

    await init_db()

    mode = getattr(args, "mode", "extraction")

    if mode == "extraction":
        # ── 提取流断点续传（原有逻辑）──────────────────────────
        from memory.checkpointer import resume_extraction
        from graph.extraction.graph import build_extraction_graph

        console.print(f"[cyan]提取流断点续传，Thread ID: {args.thread_id}[/cyan]")
        graph = await build_extraction_graph()
        result = await resume_extraction(graph, args.thread_id)
        if result:
            console.print("[green]续传完成。[/green]")

    elif mode == "creation":
        from graph.creation.graph import build_creation_graph
        from langgraph.types import Command

        graph = await build_creation_graph()
        config = {
            "configurable": {"thread_id": args.thread_id},
            "recursion_limit": 200,
        }

        # 检查当前 State
        snapshot = await graph.aget_state(config)
        if not snapshot or not snapshot.values:
            console.print("[red]找不到对应的创作记录，请检查 thread_id[/red]")
            await close_checkpointer()
            return

        current_state = snapshot.values
        completed = len(current_state.get("completed_chapters", []))
        console.print(
            f"[cyan]恢复创作流，Thread ID: {args.thread_id}[/cyan]\n"
            f"[dim]已完成章节：{completed} 节[/dim]"
        )

        if getattr(args, "next_batch", False):
            # ── 续写下一批：重置状态，跳转到 path_gen ──────────
            console.print("[dim]续写下一批，跳转到路径规划...[/dim]")
            input_data = Command(
                update={
                    "creation_complete": False,
                    "current_node_index": 0,
                    "story_path": [],
                    "path_approved": False,
                },
                goto="path_gen",
            )
        else:
            # ── 断点续传：从上次中断处继续 ──────────────────────
            console.print("[dim]从断点处继续...[/dim]")
            
            # 检查是否有 pending interrupt
            pending_interrupts = []
            for task in snapshot.tasks:
                pending_interrupts.extend(task.interrupts)

            if pending_interrupts:
                # 上次停在 interrupt 节点，先处理用户确认
                interrupt_data = pending_interrupts[0].value
                user_response = await _handle_interrupt(interrupt_data)
                input_data = Command(resume=user_response)
            else:
                # 普通断点，直接恢复
                input_data = None  # None = 从 checkpointer 恢复

        # 跑创作流
        try:
            while True:
                final_state = await _run_with_streaming(graph, input_data, config)

                snapshot = await graph.aget_state(config)
                pending_interrupts = []
                for task in snapshot.tasks:
                    pending_interrupts.extend(task.interrupts)

                if not pending_interrupts:
                    break

                interrupt_data = pending_interrupts[0].value
                user_response = await _handle_interrupt(interrupt_data)
                input_data = Command(resume=user_response)

            console.print("\n[bold green]✓ 创作完成！[/bold green]")
            _print_creation_result(final_state, args)

        except KeyboardInterrupt:
            console.print("\n[yellow]已中断，下次运行将自动从断点续传。[/yellow]")
        
    await close_checkpointer()


# ─── list 命令 ────────────────────────────────────────────────────────────────

async def list_command(args):
    from memory.db import init_db
    from tools.blueprint_store import list_blueprints

    await init_db()
    blueprints = await list_blueprints()

    if not blueprints:
        console.print("[yellow]骨骼库为空，请先执行 extract 命令。[/yellow]")
        return

    table = Table(title="骨骼库", box=box.ROUNDED, show_lines=True)
    table.add_column("ID（前12位）", style="cyan", no_wrap=True)
    table.add_column("书名", style="white")
    table.add_column("题材", style="green")
    table.add_column("世界规则", style="blue")
    table.add_column("冲突规模", style="yellow")
    table.add_column("主角定位", style="magenta")
    table.add_column("创建时间", style="dim")

    for bp in blueprints:
        table.add_row(
            bp["blueprint_id"][:12],
            bp["source_title"] or "-",
            ", ".join(bp["genre_tags"][:2]) if bp["genre_tags"] else "-",
            bp["world_rule_type"],
            bp["conflict_scale"],
            bp["protagonist_power"],
            (bp["created_at"] or "")[:16],
        )

    console.print(table)
    console.print(f"\n共 [bold]{len(blueprints)}[/bold] 份骨骼档案")


# ─── novels 命令 ──────────────────────────────────────────────────────────────

async def novels_command(args):
    """列出所有已创建的小说项目，显示续写所需信息。"""
    from memory.db import init_db
    import aiosqlite
    from config import DB_PATH

    await init_db()

    async with aiosqlite.connect(str(DB_PATH)) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            """SELECT p.project_id, p.genre_request, p.entity_summary,
                      p.last_batch_ending, p.world_setting_json,
                      p.created_at, p.updated_at,
                      COUNT(CASE WHEN s.status = 'done'    THEN 1 END) AS done_count,
                      COUNT(CASE WHEN s.status = 'planned' THEN 1 END) AS planned_count,
                      COUNT(CASE WHEN s.status = 'writing' THEN 1 END) AS writing_count,
                      MAX(s.seq) AS max_seq
               FROM novel_projects p
               LEFT JOIN story_nodes s ON s.project_id = p.project_id
               GROUP BY p.project_id
               ORDER BY p.updated_at DESC"""
        )
        rows = await cursor.fetchall()

        # 为每个项目查一下章节数
        chapter_counts: dict[str, int] = {}
        cursor2 = await conn.execute(
            "SELECT project_id, COUNT(*) AS cnt FROM chapters GROUP BY project_id"
        )
        for r in await cursor2.fetchall():
            chapter_counts[r["project_id"]] = r["cnt"]

    if not rows:
        console.print("[yellow]尚无已创建的小说项目。[/yellow]")
        console.print("[dim]使用 deepnovel create --genre <题材> 开始新项目。[/dim]")
        return

    table = Table(
        title="我的小说项目（DeepNovel v4.3 · CLI）",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("项目 ID", style="cyan", no_wrap=True)
    table.add_column("题材", style="white", max_width=20)
    table.add_column("已完成节点", justify="center", style="green")
    table.add_column("已写章节", justify="center", style="green")
    table.add_column("未完成节点", justify="center", style="yellow")
    table.add_column("最新更新", style="dim", no_wrap=True)

    for row in rows:
        pid = row["project_id"]
        done    = row["done_count"] or 0
        planned = row["planned_count"] or 0
        writing = row["writing_count"] or 0
        pending = planned + writing
        chapters = chapter_counts.get(pid, 0)
        updated = (row["updated_at"] or row["created_at"] or "")[:16]

        table.add_row(
            pid,
            row["genre_request"] or "-",
            str(done),
            str(chapters),
            str(pending),
            updated,
        )

    console.print(table)
    console.print(f"\n共 [bold]{len(rows)}[/bold] 个项目")
    console.print(
        "[dim]v4.3 新稿从「脑洞→世界→主角→冰山→开篇→分卷→单事件→路径拆解」进入写作循环；"
        "续传会按断点自动回到对应审核或写作节点。[/dim]"
    )
    console.print(
        "\n[dim]续写命令：[/dim]"
        "[bold cyan]deepnovel create --genre <题材> --project-id <项目ID>[/bold cyan]"
    )

    # 若有项目，展示最近一个的世界设定摘要
    if rows and not getattr(args, "quiet", False):
        latest = rows[0]
        ws_json = latest["world_setting_json"]
        if ws_json:
            import json
            ws = json.loads(ws_json)
            lines = []
            if ws.get("basic_rules"):
                lines.append(f"基础规则：{ws['basic_rules'][:80]}")
            if ws.get("world_taboos"):
                lines.append("禁忌：" + "；".join(ws["world_taboos"][:2]))
            if lines:
                console.print(
                    f"\n[dim]最近项目世界设定：[/dim]" + " | ".join(lines)
                )


# ─── search 命令 ──────────────────────────────────────────────────────────────

async def search_command(args):
    from memory.db import init_db
    from tools.blueprint_store import search_blueprints

    await init_db()
    results = await search_blueprints(
        genre=args.genre or "",
        world_rule=args.world_rule or "",
        conflict_scale=args.conflict_scale or "",
        protagonist_power=args.protagonist_power or "",
    )

    if not results:
        console.print("[yellow]未找到匹配的骨骼。[/yellow]")
        return

    console.print(f"[green]找到 {len(results)} 份匹配骨骼：[/green]\n")
    for bp in results:
        console.print(
            f"  [cyan]{bp['blueprint_id'][:16]}[/cyan]  "
            f"[white]{bp['source_title'] or '(无标题)'}[/white]  "
            f"[dim]{', '.join(bp['genre_tags'][:3])}[/dim]"
        )


# ─── show 命令 ────────────────────────────────────────────────────────────────

async def show_command(args):
    from memory.db import init_db
    from tools.blueprint_store import load_blueprint, load_entity_registry

    await init_db()
    bp = await load_blueprint(args.blueprint_id)

    if not bp:
        console.print(f"[red]未找到骨骼 ID: {args.blueprint_id}[/red]")
        return

    console.print(Panel(
        f"[bold]骨骼档案[/bold]\n\n"
        f"ID：{bp['blueprint_id']}\n"
        f"书名：{bp.get('source_title', '-')}\n"
        f"题材：{', '.join(bp.get('genre_tags', []))}\n"
        f"世界规则：{bp.get('world_rule_type')}\n"
        f"冲突规模：{bp.get('conflict_scale')}\n"
        f"主角定位：{bp.get('protagonist_power')}\n"
        f"是否片段：{'是' if bp.get('is_fragment') else '否'}",
        title="基本信息",
        border_style="cyan",
    ))

    layer1 = bp.get("layer1", {})
    if layer1:
        console.print("\n[bold cyan]第一层（结构模板）[/bold cyan]")
        console.print(f"  宏观节奏：{layer1.get('macro_pacing', '-')}")
        console.print(f"  卷章结构：{layer1.get('volume_count')} 卷 × {layer1.get('nodes_per_volume')} 节")
        console.print(f"  每节字数：{layer1.get('words_per_node')} 字")

    layer2 = bp.get("layer2", {})
    if layer2:
        console.print("\n[bold cyan]第二层（逻辑规律）[/bold cyan]")
        console.print(f"  写作风格：{layer2.get('writing_style', '-')}")
        console.print(f"  情绪曲线：{layer2.get('emotional_curve', '-')}")
        console.print(f"  爽点节奏：{layer2.get('payoff_rhythm', '-')}")

    layer3 = bp.get("layer3", {})
    chain_seq = layer3.get("chain_type_sequence", [])
    if chain_seq:
        console.print("\n[bold cyan]第三层（逻辑链序列）[/bold cyan]")
        console.print("  " + " → ".join(chain_seq))

    registry = await load_entity_registry(bp["blueprint_id"])
    entities = registry.get("entities", [])
    if entities:
        console.print(f"\n[bold cyan]实体注册表（共 {len(entities)} 个）[/bold cyan]")
        for e in entities[:10]:
            console.print(
                f"  [{e['entity_type']}] {e['standard_name']}"
                + (f"  别名：{', '.join(e['aliases'][:3])}" if e.get("aliases") else "")
            )
        if len(entities) > 10:
            console.print(f"  ...（共 {len(entities)} 个实体，仅显示前10个）")


# ─── 主函数 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="deepnovel",
        description="DeepNovel 骨骼系统 CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # extract
    ep = subparsers.add_parser("extract", help="从小说文本提取骨骼档案")
    ep.add_argument("--source", required=True, choices=["file", "url"], help="来源类型")
    ep.add_argument("--path", required=True, help="文件路径或 URL")
    ep.add_argument("--fragment", action="store_true", help="标记为片段（非完整小说）")
    ep.add_argument("--thread-id", default="", help="指定 Thread ID（断点续传）")

    # create
    cp = subparsers.add_parser("create", help="根据骨骼创作小说")
    cp.add_argument("--genre", required=False, default=None,
                    help="题材需求（可选）；不传时进入交互选择")
    cp.add_argument("--blueprint-id", default="", dest="blueprint_id",
                    help="骨骼档案 ID（可选；未指定时自动匹配或自由创作）")
    cp.add_argument("--weight", type=float, default=0.5, help="骨骼权重 [0.0-1.0]，默认 0.5")
    cp.add_argument("--project-id", default="", dest="project_id", help="项目 ID（断点续传）")
    cp.add_argument("--thread-id", default="", help="指定 Thread ID（断点续传）")
    cp.add_argument(
        "--idea",
        default="",
        help="可选：原始脑洞/设定碎片文本，经 idea_forge 解析为 user_anchors 与 genesis_variables 初值",
    )

    # resume
    rp = subparsers.add_parser("resume", help="从断点续传提取流")
    rp.add_argument("--thread-id", required=True, dest="thread_id", help="Thread ID")
    rp.add_argument(
        "--mode",
        choices=["extraction", "creation"],
        default="extraction",
        help="续传模式：extraction=提取流，creation=创作流"
    )
    rp.add_argument(
        "--next-batch",
        action="store_true",
        default=False,
        help="续写下一批节点（创作流专用）"
    )

    # list
    subparsers.add_parser("list", help="列出骨骼库中的所有骨骼")

    # novels
    nvp = subparsers.add_parser("novels", help="列出所有已创建的小说项目（续写时查项目 ID）")
    nvp.add_argument("--quiet", "-q", action="store_true", help="只显示表格，不展示详情")

    # search
    sp = subparsers.add_parser("search", help="搜索骨骼库")
    sp.add_argument("--genre", default="", help="题材关键词")
    sp.add_argument("--world-rule", default="", dest="world_rule", help="world_rule_type")
    sp.add_argument("--conflict-scale", default="", dest="conflict_scale", help="conflict_scale")
    sp.add_argument("--protagonist-power", default="", dest="protagonist_power", help="protagonist_power")

    # show
    shp = subparsers.add_parser("show", help="查看骨骼档案详情")
    shp.add_argument("--blueprint-id", required=True, dest="blueprint_id", help="骨骼档案 ID")

    args = parser.parse_args()

    command_map = {
        "extract": extract_command,
        "create":  create_command,
        "resume":  resume_command,
        "list":    list_command,
        "novels":  novels_command,
        "search":  search_command,
        "show":    show_command,
    }

    try:
        asyncio.run(command_map[args.command](args))
    except KeyboardInterrupt:
        console.print("\n[dim]已通过 Ctrl+C 退出[/dim]")
        sys.exit(0)


if __name__ == "__main__":
    main()
