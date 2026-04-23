"""
节点执行状态展示工具。

所有函数只负责打印状态文字，不处理 LLM token 流。
token 流的展示在 __main__.py 的 astream_events 循环里处理。
"""
from __future__ import annotations
from rich.console import Console
from rich.panel import Panel

import json

from utils.volume_fields import format_dynamic_gray_factions_for_prompt
from utils.v42_flow import protagonist_capabilities_cli_block

console = Console()


def node_step(step_name: str) -> None:
    """节点内部子步骤开始（在节点函数里调用，可选）"""
    console.print(f"  [yellow]→[/yellow] {step_name}...", end="")


def node_done(result_summary: str = "") -> None:
    """步骤完成"""
    if result_summary:
        console.print(f"  [green]✓[/green]  [dim]{result_summary}[/dim]")
    else:
        console.print(f"  [green]✓[/green]")


def node_warn(msg: str) -> None:
    """节点警告（不中断流程）"""
    console.print(f"\n  [yellow]⚠[/yellow]  {msg}")


def node_error(msg: str) -> None:
    """节点错误"""
    console.print(f"\n  [red]✗[/red]  {msg}")


def print_blueprint_saved(blueprint_id: str, title: str) -> None:
    """骨骼存储完成提示"""
    console.print(Panel(
        f"[green]骨骼提取完成[/green]\n\n"
        f"ID：[bold]{blueprint_id}[/bold]\n"
        f"书名：{title}",
        border_style="green",
        expand=False,
    ))


def print_interrupt_prompt(prompt_type: str, content: dict) -> None:
    """
    interrupt 节点的统一展示格式。

    Args:
        prompt_type: "synopsis_review" | "path_review"
        content:     interrupt 传入的内容 dict
    """
    if prompt_type == "story_direction_review":
        synopsis = content.get("synopsis", {})
        world_setting = content.get("world_setting", {})
        protagonist_card = content.get("protagonist_card", {})
        console.print(Panel(
            f"[bold]标题：[/bold]{synopsis.get('title', '')}\n\n"
            f"[bold]世界观：[/bold]{synopsis.get('world', '')}\n\n"
            f"[bold]主角：[/bold]{synopsis.get('protagonist', '')}\n\n"
            f"[bold]核心冲突：[/bold]{synopsis.get('core_conflict', '')}\n\n"
            f"[bold]走向：[/bold]{synopsis.get('direction', '')}",
            title="📖 根据您的故事方向生成的设定 - 宏观构思",
            border_style="cyan",
            expand=False,
        ))
        ws = world_setting or {}
        ws_lines = []
        if ws.get("basic_rules"):
            ws_lines.append(f"[bold]基础规则[/bold]\n{ws['basic_rules']}")
        for label, key in [
            ("权力结构", "power_structure"),
            ("地理框架", "geography"),
            ("世界禁忌", "world_taboos"),
            ("独特设定", "unique_settings"),
        ]:
            items = ws.get(key) or []
            if not isinstance(items, list):
                items = [str(items)] if items else []
            if items:
                ws_lines.append(f"[bold]{label}[/bold]\n" + "\n".join(f"  • {x}" for x in items))
        console.print(Panel(
            "\n\n".join(ws_lines) if ws_lines else "（无）",
            title="🌍 世界设定",
            border_style="magenta",
            expand=False,
        ))
        pc = protagonist_card or {}
        traits = pc.get("traits_display") or []
        pc_text = f"[bold]标准名：[/bold]{pc.get('standard_name', '')}\n\n"
        pc_text += f"[bold]外貌：[/bold]{pc.get('appearance', '')}\n\n"
        if pc.get("current_mental_state"):
            pc_text += f"[bold]当前心智：[/bold]{pc.get('current_mental_state', '')}\n\n"
        if pc.get("mental_growth_path"):
            pc_text += f"[bold]精神成长轨迹：[/bold]{pc.get('mental_growth_path', '')}\n\n"
        if pc.get("reverse_scale"):
            pc_text += f"[bold]逆鳞：[/bold]{pc.get('reverse_scale', '')}\n\n"
        pc_text += f"[bold]背景经历：[/bold]{pc.get('background_summary', '')}\n\n"
        if traits:
            pc_text += "[bold]行为倾向：[/bold]\n" + "\n".join(f"  • {t}" for t in traits)
        console.print(Panel(
            pc_text,
            title="👤 主角人物卡",
            border_style="cyan",
            expand=False,
        ))
    elif prompt_type == "framework_review":
        content = content or {}
        synopsis = content.get("synopsis", {})
        console.print(Panel(
            f"[bold]标题：[/bold]{synopsis.get('title', '')}\n\n"
            f"[bold]世界观：[/bold]{synopsis.get('world', '')}\n\n"
            f"[bold]主角：[/bold]{synopsis.get('protagonist', '')}\n\n"
            f"[bold]核心冲突：[/bold]{synopsis.get('core_conflict', '')}\n\n"
            f"[bold]走向：[/bold]{synopsis.get('direction', '')}",
            title="📖 宏观构思",
            border_style="cyan",
            expand=False,
        ))
        factions = content.get("factions", [])
        if factions:
            console.print(f"\n[bold]共 {len(factions)} 个势力：[/bold]")
            for fa in factions:
                console.print(
                    f"  • {fa.get('name', '')}（{fa.get('faction_type', 'neutral')}）"
                    f" [dim]第{fa.get('appears_from_volume', 0)+1}卷出场[/dim]"
                )
        volumes = content.get("volumes", [])
        if volumes:
            console.print(f"\n[bold]共 {len(volumes)} 卷：[/bold]")
            for v in volumes:
                detail = "有详细情节" if v.get("has_detailed_plot") else "只有方向"
                console.print(
                    f"  第{v.get('volume_index', 0)+1}卷：{v.get('volume_name', '')}  "
                    f"[dim]（{detail}，约{v.get('estimated_chapters', '?')}章）[/dim]"
                )
        write_rules = content.get("write_rules", "")
        if write_rules:
            preview = write_rules[:300] + ("..." if len(write_rules) > 300 else "")
            console.print(Panel(preview, title="📋 创作铁则", border_style="dim", expand=False))
        char_count = len(content.get("character_cards", []))
        foreshadow_count = len(content.get("foreshadow_seeds", []))
        console.print(f"\n[dim]解析到 {char_count} 个配角，{foreshadow_count} 条前置伏笔[/dim]")
    elif prompt_type == "opening_review":
        ot = content.get("opening_text") or ""
        preview = (ot[:1200] + "…") if len(ot) > 1200 else ot
        vars_ = content.get("variables") or {}
        vline = ""
        if vars_:
            vline = (
                f"[bold]题材桶：[/bold]{vars_.get('genre_bucket', '')}  "
                f"[bold]针对度：[/bold]{vars_.get('targeting_degree', '')}  "
                f"[bold]情感度：[/bold]{vars_.get('emotional_degree', '')}\n"
                f"[bold]逻辑：[/bold]{vars_.get('human_logic', '')}  "
                f"[bold]模式：[/bold]{vars_.get('story_mode', '')}\n"
                f"[bold]金手指：[/bold]{vars_.get('fictional_hook', '')}\n\n"
            )
        console.print(Panel(
            vline + f"[bold]开篇草案：[/bold]\n{preview}"
            + "\n\n[dim]（v4.2：确认后下一步为「全书核心班底」生成与审核，通过后再进入分卷规划。）[/dim]",
            title="🌱 开篇种子确认",
            border_style="green",
            expand=False,
        ))
    elif prompt_type == "iceberg_review":
        syn = content.get("synopsis") or {}
        fam = (syn.get("family_emotion_line") or "").strip()
        rom = (syn.get("romance_emotion_line") or "").strip()
        emo = ""
        if fam or rom:
            emo = (
                f"\n\n[bold]亲情主轴：[/bold]{fam or '（未填）'}\n"
                f"[bold]爱情/红颜：[/bold]{rom or '（未填）'}"
            )
        ext = ""
        xh = syn.get("core_hook") or ""
        v1 = syn.get("volume_1_goal") or ""
        esc = syn.get("escalation_path") or ""
        ult = syn.get("ultimate_goal") or ""
        if xh or v1 or esc or ult:
            ext = (
                f"\n\n[bold]核心钩子：[/bold]{xh}\n"
                f"[bold]第一卷目标：[/bold]{v1}\n"
                f"[bold]格局放大路径：[/bold]{esc}\n"
                f"[bold]全书终极使命：[/bold]{ult}"
            )
        opener = (content.get("opening_text") or "").strip()
        op_prev = (opener[:400] + "…") if len(opener) > 400 else opener
        p4 = syn.get("iceberg_prompt4") if isinstance(syn.get("iceberg_prompt4"), dict) else {}
        p4_block = ""
        if p4:
            uc = p4.get("iceberg_undercurrents")
            p4_block = "\n\n[bold]── iceberg_prompt4 · 暗流与 capability_source（补丁检查点）──[/bold]\n"
            if isinstance(uc, list) and uc:
                for idx, item in enumerate(uc[:15], 1):
                    if not isinstance(item, dict):
                        continue
                    src = str(item.get("source") or "").strip()
                    st = str(item.get("surface_trace") or "").strip()
                    emg = str(item.get("estimated_emergence") or "").strip()
                    cs = item.get("capability_source") if isinstance(
                        item.get("capability_source"), dict
                    ) else {}
                    tt = str(cs.get("tension_type") or "").strip() or "—"
                    cf = str(cs.get("capability_field") or "").strip() or "—"
                    cid = str(cs.get("character_id") or "").strip() or "—"
                    p4_block += (
                        f"\n[dim]{idx}.[/dim] [bold]source[/bold]：{src}\n"
                        f"    [bold]capability_source[/bold]：tension_type={tt} | "
                        f"field={cf} | character_id={cid}\n"
                    )
                    if st:
                        p4_block += f"    surface_trace：{st[:220]}{'…' if len(st) > 220 else ''}\n"
                    if emg:
                        p4_block += f"    estimated_emergence：{emg}\n"
            else:
                p4_block += (
                    "\n[dim]（iceberg_undercurrents 为空：若刚跑完 PROMPT4，请检查模型是否按 schema 输出）[/dim]\n"
                )
            oc = p4.get("opening_collision") if isinstance(p4.get("opening_collision"), dict) else {}
            if oc:
                qc = str(oc.get("quality_check") or "").strip()
                fe = str(oc.get("forced_entry") or "").strip()
                if qc or fe:
                    p4_block += "\n[bold]opening_collision（摘录）[/bold]\n"
                    if fe:
                        p4_block += f"  forced_entry：{fe[:300]}\n"
                    if qc:
                        p4_block += f"  quality_check：{qc[:300]}\n"
            if not (isinstance(uc, list) and uc):
                raw_p4 = json.dumps(p4, ensure_ascii=False, indent=2)
                cap = 6000
                p4_block += f"\n[dim]iceberg_prompt4 JSON（暗流为空时的全量回显）：\n{raw_p4[:cap]}{'…' if len(raw_p4) > cap else ''}[/dim]"
            else:
                p4_block += "\n[dim]（完整 iceberg_prompt4 已写入 synopsis，事件链与开篇节点可读 state）[/dim]"
        else:
            p4_block = (
                "\n\n[dim]（尚无 synopsis.iceberg_prompt4：多为 PROMPT4 未写入或 synopsis 合并异常）[/dim]"
            )
        console.print(Panel(
            f"[dim]开篇摘要：[/dim]{op_prev}\n\n"
            f"[bold]标题：[/bold]{syn.get('title', '')}\n\n"
            f"[bold]世界观：[/bold]{syn.get('world', '')}\n\n"
            f"[bold]主角：[/bold]{syn.get('protagonist', '')}\n\n"
            f"[bold]核心冲突：[/bold]{syn.get('core_conflict', '')}\n\n"
            f"[bold]走向：[/bold]{syn.get('direction', '')}"
            + emo + ext
            + p4_block
            + "\n\n[dim]（v4.2：确认后依次点燃开篇种子 → 审核全书核心班底 → 分卷规划；不再回到世界设定卡；正文期配角由 bible 生长。）[/dim]",
            title="🧊 冰山反推 · 宏观构思（一屏合成）",
            border_style="cyan",
            expand=False,
        ))
        cc = content.get("core_cast_draft") or {}
        uv = cc.get("ultimate_villain") or {}
        sp = cc.get("supreme_power") or {}
        la = cc.get("lifelong_allies") or []
        has_cc = bool(
            (uv.get("name") or "").strip()
            or (sp.get("name") or "").strip()
            or any((a.get("name") or "").strip() for a in la if isinstance(a, dict))
        )
        if has_cc:
            ally_names = ", ".join(
                str(a.get("name", "")) for a in la[:4] if isinstance(a, dict)
            )
            console.print(Panel(
                f"[bold]终局宿敌：[/bold]{uv.get('name', '')}（{uv.get('identity', '')}）\n"
                f"[bold]最高掌权：[/bold]{sp.get('name', '')}\n"
                f"[bold]羁绊锚点：[/bold]{ally_names or '（待补）'}",
                title="👥 核心班底草案",
                border_style="yellow",
                expand=False,
            ))
    elif prompt_type == "synopsis_review":
        fam = (content.get("family_emotion_line") or "").strip()
        rom = (content.get("romance_emotion_line") or "").strip()
        emo = ""
        if fam or rom:
            emo = (
                f"\n\n[bold]亲情主轴：[/bold]{fam or '（未填）'}\n"
                f"[bold]爱情/红颜：[/bold]{rom or '（未填）'}"
            )
        ext = ""
        xh = content.get("core_hook") or ""
        v1 = content.get("volume_1_goal") or ""
        esc = content.get("escalation_path") or ""
        ult = content.get("ultimate_goal") or ""
        if xh or v1 or esc or ult:
            ext = (
                f"\n\n[bold]核心钩子：[/bold]{xh}\n"
                f"[bold]第一卷目标：[/bold]{v1}\n"
                f"[bold]格局放大路径：[/bold]{esc}\n"
                f"[bold]全书终极使命：[/bold]{ult}"
            )
        seed = (content.get("opening_seed_text") or "").strip()
        seed_line = f"\n\n[dim]开篇种子摘要：[/dim]{seed[:350]}{'…' if len(seed) > 350 else ''}" if seed else ""
        console.print(Panel(
            f"[bold]标题：[/bold]{content.get('title', '')}\n\n"
            f"[bold]世界观：[/bold]{content.get('world', '')}\n\n"
            f"[bold]主角：[/bold]{content.get('protagonist', '')}\n\n"
            f"[bold]核心冲突：[/bold]{content.get('core_conflict', '')}\n\n"
            f"[bold]走向：[/bold]{content.get('direction', '')}"
            + emo + ext + seed_line,
            title="📖 宏观构思",
            border_style="cyan",
            expand=False,
        ))
    elif prompt_type == "path_review":
        nodes       = content if isinstance(content, list) else content.get("nodes", [])
        vol_name    = content.get("volume_name", "") if isinstance(content, dict) else ""
        vol_tagline = content.get("volume_tagline", "") if isinstance(content, dict) else ""

        title = (
            f"🗺  第{content.get('volume_index', 1)}卷《{vol_name}》（共 {len(nodes)} 个节点）"
            if vol_name else
            f"🗺  故事路径（共 {len(nodes)} 个节点）"
        )

        lines = []
        if vol_tagline:
            lines.append(f"  [dim italic]{vol_tagline}[/dim italic]\n")
        for i, node in enumerate(nodes):
            arc = node.get("arc_stage", "")
            method = node.get("resolution_method", "")
            arc_tag = f"  [dim][{arc}][/dim]" if arc else ""
            method_tag = f"  [yellow]{method}[/yellow]" if method else ""
            lines.append(
                f"  [bold]{i + 1}.[/bold]  "
                f"[cyan]{node.get('node_name', '')}[/cyan]{arc_tag}  {method_tag}\n"
                f"      {node.get('one_liner', '')}"
            )
        console.print(Panel(
            "\n".join(lines) if lines else "（路径为空）",
            title=title,
            border_style="cyan",
            expand=False,
        ))

    elif prompt_type == "protagonist_input":
        hint = content.get("hint") or (
            "请用一句话或几个关键词描述主角；回车则交给模型根据大纲发挥。"
        )
        console.print(Panel(hint, title="📝 主角印象（自由输入）", border_style="cyan", expand=False))

    elif prompt_type == "expand_review":
        node_name = content.get("node_name", "")
        node_idx  = content.get("node_index", 0)
        is_v43    = content.get("is_v43", False)

        if is_v43:
            # v4.3 路径落地确认结果展示
            lines: list[str] = []
            chapter_tone = content.get("chapter_tone", "")
            function_confirmed = content.get("function_confirmed", "")
            chapter_driver = content.get("chapter_driver", "")
            key_factors = content.get("key_state_factors") or []
            causal_input = content.get("causal_input", "")
            causal_output = content.get("causal_output_direction", "")
            hidden_seed = content.get("hidden_seed", "")
            state_audit = content.get("state_audit_note", "")
            path_id = content.get("path_id", "")

            if path_id:
                lines.append(f"[dim]路径 ID：{path_id}[/dim]")
            if chapter_tone:
                lines.append(f"[bold]情绪基调：[/bold]{chapter_tone}")
            if function_confirmed:
                lines.append(f"[bold]功能落地：[/bold]{function_confirmed}")
            if chapter_driver:
                lines.append(f"[bold]叙事驱动：[/bold]{chapter_driver}")
            if key_factors:
                lines.append("[bold]关键状态因子：[/bold]")
                for f in key_factors:
                    lines.append(f"  • {f}")
            if causal_input:
                lines.append(f"[bold]因果输入：[/bold]{causal_input}")
            if causal_output:
                lines.append(f"[bold]因果输出方向：[/bold]{causal_output}")
            if hidden_seed and hidden_seed != "无":
                lines.append(f"[bold]隐性种子：[/bold]{hidden_seed}")
            if state_audit:
                lines.append(f"[dim]状态确认：{state_audit}[/dim]")
            body = "\n".join(lines) if lines else "（expand1_v43 未返回有效内容，请检查日志）"
        else:
            # 旧版展示：草稿路径链 + 施压/破局
            chain      = content.get("event_path_draft", [])
            core_event = content.get("core_event", "")
            pressure   = content.get("pressure_mechanism", "")
            resolution = content.get("resolution_trigger", "")
            chain_lines = "\n".join(
                f"  [dim]{i + 1}.[/dim]  {step}" for i, step in enumerate(chain)
            )
            detail = ""
            if core_event:
                detail += f"\n[bold]核心事件：[/bold]{core_event}"
            if pressure:
                detail += f"\n[bold]施压机制：[/bold]{pressure}"
            if resolution:
                detail += f"\n[bold]破局触发：[/bold]{resolution}"
            body = f"[bold]草稿事件路径链：[/bold]\n{chain_lines}" + (f"\n{detail}" if detail else "")

        console.print(Panel(
            body,
            title=f"🔍  第 {node_idx + 1} 章方向确认：{node_name}",
            border_style="blue",
            expand=False,
        ))

    elif prompt_type == "write_review":
        node_name    = content.get("node_name", "")
        node_idx     = content.get("node_index", 0)
        chain        = content.get("event_path_chain", [])
        preview      = content.get("draft_preview", "")
        word_count   = content.get("word_count", 0)
        ability_checks = content.get("pending_ability_checks", [])
        chain_lines = "\n".join(
            f"  [dim]{i + 1}.[/dim]  {step}" for i, step in enumerate(chain)
        )
        # 先展示正文预览，再展示事件链，方便用户对照给修改意见
        console.print(Panel(
            f"[bold]正文预览（{word_count} 字）：[/bold]\n{preview}\n\n"
            f"[bold]事件路径链（修改参考）：[/bold]\n{chain_lines}",
            title=f"✍  第 {node_idx + 1} 章正文审核：{node_name}",
            border_style="yellow",
            expand=False,
        ))
        # 张力参考提示（tension_check 发现的轻微不足，不影响保存）
        tension_minor = content.get("tension_minor_issues", [])
        if tension_minor:
            console.print(Panel(
                "\n".join(f"  • {i}" for i in tension_minor),
                title="💡 张力参考提示（不影响保存，仅供参考）",
                border_style="dim",
                expand=False,
            ))
        # 能力使用记录（已知 ✓，未记录 ⚠）
        if ability_checks:
            lines = [
                f"  • {ab.get('ability_name', '?')} "
                f"（{ab.get('char_name', '未知')} 使用）  [yellow]⚠️ 首次出现，尚未记录[/yellow]"
                for ab in ability_checks
            ]
            console.print(Panel(
                "\n".join(lines),
                title="🔮  本节能力使用 — 检测到未记录能力",
                border_style="yellow",
                expand=False,
            ))
        # 本节新增伏笔
        new_foreshadows = content.get("new_foreshadows", [])
        if new_foreshadows:
            type_labels = {"event": "事件型", "noun": "词条型", "behavior": "行为型"}
            lines = []
            for f in new_foreshadows:
                t = type_labels.get(f.get("foreshadow_type", ""), "未知")
                backbone_label = "【主线】" if f.get("is_backbone") else ""
                lines.append(
                    f"  • {backbone_label}[{f.get('foreshadow_id', '?')[:8]}] "
                    f"{f.get('surface_meaning', '')}  {t}\n"
                    f"    潜力方向：{f.get('story_potential', '') or '待确认'}"
                )
            console.print(Panel(
                "\n".join(lines),
                title="🔖  本节伏笔记录",
                border_style="dim",
                expand=False,
            ))
        # 本节推进的已有伏笔
        advanced = content.get("advanced_foreshadows", [])
        if advanced:
            lines = []
            for f in advanced:
                lines.append(
                    f"  • [{f.get('foreshadow_id', '?')}] {f.get('surface_meaning', '')}\n"
                    f"    状态变化：{f.get('old_urgency', '')} → {f.get('new_urgency', '')}"
                )
            console.print(Panel(
                "\n\n".join(lines),
                title="📌  已有伏笔推进",
                border_style="dim",
                expand=False,
            ))
        # 人物性格变化（上节 bible_update 检测到的特质叠加方式变化）
        trait_updates = content.get("pending_trait_interaction_update", [])
        if trait_updates:
            for ti in trait_updates:
                name   = ti.get("character_name", "?")
                event  = ti.get("trigger_event", "")
                seq    = ti.get("seq", 0)
                sugg   = ti.get("suggested_interaction", {})
                combo  = "+".join(sugg.get("combo", []))
                result = sugg.get("result", "")
                console.print(Panel(
                    f"[bold]人物：[/bold]{name}\n"
                    f"[bold]触发事件：[/bold]{event}（第{seq}节）\n"
                    f"[bold]建议追加叠加规则：[/bold]{combo}\n"
                    f"  {result}",
                    title="📌  人物性格变化 — 特质叠加方式可能已发生变化",
                    border_style="magenta",
                    expand=False,
                ))
        console.print(Panel(
            "[bold]选项 [2] 改写文笔/节奏[/bold]（小修 · 省 Token）：expand1 剧情分析[bold]不变[/bold]，"
            "只重跑 expand2+write。意见写氛围、对话、动作细节、代价与节奏；"
            "[bold]不要[/bold]在这里推翻因果或换人设走向。\n"
            "      例：打斗太草了多写拳肉相接；反派台词再阴阳一点；进房间的过程拉长。\n\n"
            "[bold]选项 [3] 推翻走向[/bold]（大修）：回到 expand1，重排张力与因果。"
            "意见可用大白话；系统会拆成「须保留的事实」与「走向」，占位名（如张三挡刀）会提示模型换符合世界观的龙套名。\n"
            "      例：主角这里必须故意输；刺客不杀留活口；某某其实是自己人并在关键时刻递暗示。\n\n"
            "[bold]涌现资产[/bold]：通过后若有新人物卡草稿，可在入库前改外貌/倾向——会写进圣经，长跑连载仍一致。"
            "能力面板里把修辞误检当功法时，选「笔误忽略」以免污染库。",
            title="💡 导演级打回 · 边界说明",
            border_style="dim",
            expand=False,
        ))
    elif prompt_type == "role_shift_review":
        shifts = content.get("shifts", [])
        for shift in shifts:
            name    = shift.get("character_name", "?")
            t_type  = shift.get("trigger_type", "")
            t_desc  = shift.get("trigger_description", "")
            evidence= shift.get("evidence", "")
            cur     = shift.get("current_role", "盟友")
            est_seq = shift.get("established_at_seq", 0)
            cur_seq = shift.get("current_seq", 0)

            type_label = {
                "betrayal":     "主动伤害/出卖主角",
                "opposition":   "站到对立势力",
                "concealment":  "隐瞒关键信息",
            }.get(t_type, t_type)

            est_info = f"自第 {est_seq} 节建立" if est_seq else "（立场建立时机未知）"
            console.print(Panel(
                f"[bold]触发特征：[/bold]{type_label}\n"
                f"[bold]本节行为：[/bold]{t_desc}\n"
                f"[bold]正文依据：[/bold][dim]{evidence}[/dim]\n\n"
                f"[bold]当前立场：[/bold]{cur}（{est_info}）",
                title=f"⚠️  核心角色立场变化：[bold cyan]{name}[/bold cyan]（第 {cur_seq} 节）",
                border_style="yellow",
                expand=False,
            ))

    elif prompt_type == "protagonist_review":
        card = content.get("card", {}) if isinstance(content, dict) else {}
        standard_name = (
            card.get("standard_name")
            or card.get("name")
            or content.get("protagonist_name", "主角")
        )
        cid = (card.get("character_id") or "").strip()
        appearance = card.get("appearance", "")
        persona = card.get("persona", "")
        wp = (card.get("world_position") or "").strip()
        agenda = (card.get("independent_agenda") or "").strip()
        maturity = (
            card.get("current_maturity")
            or card.get("maturity_level")
            or card.get("maturity_note")
            or "（未设定）"
        )
        reverse_scale = (card.get("reverse_scale") or "").strip() or "（无）"
        innate_traits = card.get("innate_traits", [])
        if isinstance(innate_traits, list):
            innate_traits_str = "、".join(str(x) for x in innate_traits if str(x).strip())
        else:
            innate_traits_str = str(innate_traits or "")
        inn_d = card.get("innate_traits_detail") if isinstance(
            card.get("innate_traits_detail"), dict
        ) else {}
        innate_extra = ""
        if inn_d:
            cd = str(inn_d.get("core_desire") or "").strip()
            cf = str(inn_d.get("core_fear") or "").strip()
            if cd or cf:
                innate_extra = f"\n[dim]欲求/恐惧：[/dim]{cd}" + (f" / {cf}" if cf else "")
        mental_core = card.get("mental_core", {})
        if not isinstance(mental_core, dict):
            mental_core = {}
        mental_panel_str = (
            f"心{mental_core.get('intelligence', '?')} | "
            f"情{mental_core.get('eq', '?')} | "
            f"缜{mental_core.get('meticulousness', '?')} | "
            f"阈{mental_core.get('emotional_capacity', '?')} | "
            f"忍{mental_core.get('forbearance', '?')} | "
            f"透支{card.get('current_emotional_drain', 0)}"
        )
        mcl = card.get("mental_core_literary") if isinstance(
            card.get("mental_core_literary"), dict
        ) else {}

        def _threshold_narrative_block(mc_lit: dict) -> str:
            """与「阈」对应：精神阈值叙述（崩溃行为 + 消耗触发），与 intelligence 五维第 4 维一致。"""
            if not isinstance(mc_lit, dict):
                return ""
            parts: list[str] = []
            cb = str(mc_lit.get("emotional_collapse_behavior") or "").strip()
            if cb:
                parts.append(cb)
            tr = mc_lit.get("emotional_drain_triggers")
            if isinstance(tr, list) and tr:
                tail = "；".join(str(x).strip() for x in tr[:6] if str(x).strip())
                if tail:
                    parts.append(f"消耗触发：{tail}")
            ecn = mc_lit.get("emotional_capacity_narrative")
            if isinstance(ecn, str) and ecn.strip():
                parts.insert(0, ecn.strip())
            return " ".join(parts) if parts else ""

        # 与上行「心|情|缜|阈|忍」顺序、含义一一对应（勿少「阈」）
        lit_lines: list[str] = []
        if mcl:
            for k, lab in (
                ("intellect", "心·心智"),
                ("emotional_intelligence", "情·情商"),
                ("strategic_thinking", "缜·缜密"),
            ):
                v = str(mcl.get(k) or "").strip()
                if v:
                    lit_lines.append(
                        f"  [dim]{lab}：{v[:140]}{'…' if len(v) > 140 else ''}[/dim]"
                    )
            thr = _threshold_narrative_block(mcl)
            if thr:
                lit_lines.append(
                    f"  [dim]阈·精神阈值："
                    f"{thr[:200]}{'…' if len(thr) > 200 else ''}[/dim]"
                )
            elif lit_lines:
                lit_lines.append(
                    "  [dim]阈·精神阈值：（暂无文档叙述；数值见上行「阈」）[/dim]"
                )
            end_v = str(mcl.get("endurance") or "").strip()
            if end_v:
                lit_lines.append(
                    f"  [dim]忍·隐忍："
                    f"{end_v[:140]}{'…' if len(end_v) > 140 else ''}[/dim]"
                )
        lit_block = "\n".join(lit_lines) if lit_lines else ""
        habits = card.get("signature_habits", [])
        if not isinstance(habits, list):
            habits = [str(habits)] if habits else []
        habits_block = "\n".join(f"  • {str(t)}" for t in habits if str(t).strip()) or "  （暂无）"
        core_motif = (card.get("core_motif") or "").strip()
        cap_cli = protagonist_capabilities_cli_block(card)
        display_text = (
            f"[bold]标识：[/bold]{cid or '—'}  [bold]标准名：[/bold]{standard_name}\n\n"
            f"[bold]外貌：[/bold]{appearance or '（待补充）'}\n\n"
            f"[bold]先天（列表）：[/bold]{innate_traits_str or '（待补充）'}{innate_extra}\n\n"
            f"[bold]外在假面(Persona)：[/bold]{persona or '（待补充）'}\n\n"
            f"[bold]世界位置：[/bold]{wp or '（待补充）'}\n\n"
            f"[bold]独立议程：[/bold]{agenda or '（待补充）'}\n\n"
            + (f"[bold]核心底色：[/bold]{core_motif}\n\n" if core_motif else "")
            + f"[bold]成熟度：[/bold]{maturity}\n\n"
            + f"[bold]绝对逆鳞：[/bold]{reverse_scale}\n\n"
            + f"[bold]精神面板(0-100)：[/bold]{mental_panel_str}\n\n"
            + (
                f"[bold]精神面板（文档叙述，与上行心·情·缜·阈·忍一一对应）[/bold]\n{lit_block}\n\n"
                if lit_block else ""
            )
            + f"[bold]capabilities（能力档案 · 金手指/武功/特质）[/bold]\n{cap_cli}\n\n"
            + f"[bold]标志性微动作：[/bold]\n{habits_block}"
        )
        console.print(Panel(
            display_text,
            title="主角人物卡（创作核心，锁定后不再触发首次出场检测）",
            border_style="cyan",
            expand=False,
        ))

    elif prompt_type == "world_review":
        ws = content.get("world_setting", {})
        if not ws:
            return
        lines = []
        if br := ws.get("basic_rules", ""):
            lines.append(f"[bold]基础规则[/bold]\n{br}")
        for label, key in [
            ("权力结构", "power_structure"),
            ("地理框架", "geography"),
            ("世界禁忌", "world_taboos"),
            ("独特设定", "unique_settings"),
        ]:
            items = ws.get(key) or []
            if not isinstance(items, list):
                items = [str(items)]
            if items:
                bullet = "\n".join(f"  • {it}" for it in items)
                lines.append(f"[bold]{label}[/bold]\n{bullet}")
        console.print(Panel(
            "\n\n".join(lines) if lines else "（世界设定为空）",
            title="🌍  世界设定卡（确认后全书锁定）",
            border_style="magenta",
            expand=False,
        ))

    elif prompt_type == "core_cast_review":
        c = content if isinstance(content, dict) else {}
        uv = c.get("ultimate_villain") or {}
        allies = c.get("lifelong_allies") or []
        sp = c.get("supreme_power") or {}
        ally_names = "、".join(
            (a.get("name") or "") for a in allies if isinstance(a, dict)
        )

        def _ebd_line(d: dict) -> str:
            if not isinstance(d, dict):
                return ""
            e = d.get("ebd_to_protagonist", "")
            bk = d.get("ebd_bond_kind", "") or ""
            et = d.get("ebd_type", "") or ""
            if e == "" and not et:
                return ""
            return f"  EBD：{e}  bond={bk}  {et}"

        uv_ebd = _ebd_line(uv)
        sp_ebd = _ebd_line(sp)
        ally_ebd_lines = []
        for a in allies:
            if isinstance(a, dict) and a.get("name"):
                le = _ebd_line(a)
                if le:
                    ally_ebd_lines.append(f"  • {a.get('name')}：{le.strip()}")

        body = (
            f"[bold]最终宿敌：[/bold]{uv.get('name', '')}（{uv.get('identity', '')}）\n"
            f"  动机：{uv.get('core_motivation', '')}\n"
            f"  约从第 {uv.get('appears_from_volume', '?')} 卷露头角"
            + (f"\n{uv_ebd}" if uv_ebd else "")
            + f"\n\n[bold]一生挚友：[/bold]{ally_names or '（无）'}"
            + (
                "\n" + "\n".join(ally_ebd_lines)
                if ally_ebd_lines
                else ""
            )
            + f"\n\n[bold]最高掌权：[/bold]{sp.get('name', '')}（{sp.get('identity', '')}）\n"
            f"  立场：{sp.get('stance_to_protagonist', '')}\n"
            f"  备注：{sp.get('note', '')}"
            + (f"\n{sp_ebd}" if sp_ebd else "")
        )
        console.print(Panel(
            body,
            title="👥 全书核心班底",
            border_style="cyan",
            expand=False,
        ))

    elif prompt_type == "story_arc_review":
        vols = content if isinstance(content, list) else []
        lines = []
        for v in vols:
            if not isinstance(v, dict):
                continue
            vi = v.get("volume_index", 0)
            vv = v.get("volume_villain") or {}
            dgf_s = format_dynamic_gray_factions_for_prompt(v.get("dynamic_gray_factions"))
            et = v.get("ebd_targets") or []
            et_s = ""
            if isinstance(et, list) and et:
                parts = []
                for t in et[:5]:
                    if not isinstance(t, dict):
                        continue
                    parts.append(
                        f"{t.get('char', '')}→{t.get('ebd_end', '')}"
                        f"({t.get('ebd_bond_kind', '')})"
                    )
                et_s = "\n    EBD 目标：" + "；".join(parts) if parts else ""
            aa_lines: list[str] = []
            arc_anchors = v.get("arc_anchors")
            if isinstance(arc_anchors, list) and arc_anchors:
                aa_lines.append("    [bold]arc_anchors（本卷事件锚点 · event_chain_gen 读取）[/bold]")
                for a in arc_anchors[:20]:
                    if not isinstance(a, dict):
                        continue
                    aid = a.get("anchor_id", "?")
                    mt = str(a.get("milestone_type") or "").strip()
                    arr = str(a.get("arrival_condition") or "").strip()
                    comp = str(a.get("completion_signal") or "").strip()
                    pos = str(a.get("position") or "").strip()
                    aa_lines.append(
                        f"      · 锚点 {aid} [{mt}] position={pos}\n"
                        f"        arrival：{arr[:200]}{'…' if len(arr) > 200 else ''}\n"
                        f"        completion_signal：{comp[:200]}{'…' if len(comp) > 200 else ''}"
                    )
            aa_block = ("\n" + "\n".join(aa_lines)) if aa_lines else ""
            lines.append(
                f"  第{int(vi) + 1}卷「{v.get('volume_name', '')}」"
                f"  约{v.get('estimated_chapters', 0)}章  "
                f"烈度：{v.get('conflict_intensity', '')}\n"
                f"    方向：{v.get('volume_direction', '')}\n"
                f"    地点：{v.get('location_scope', '')}\n"
                f"    反派：{vv.get('name', '')}\n"
                f"    灰度利益实体 dynamic_gray_factions：{dgf_s}"
                f"{et_s}"
                f"{aa_block}"
            )
        console.print(Panel(
            "\n\n".join(lines) if lines else "（无分卷数据）",
            title="📚 全书分卷规划",
            border_style="cyan",
            expand=False,
        ))

    elif prompt_type == "event_chain_review":
        data = content if isinstance(content, dict) else {}
        events = data.get("events") or []
        vol_name = data.get("volume_name", "")
        lines = []
        for e in events:
            if not isinstance(e, dict):
                continue
            eid = e.get("id", "")
            prefix = "📌" if e.get("event_type") == "protagonist_line" else "🌍"
            tt = (e.get("tension_type") or "")[:4]
            span = (e.get("chapter_span_estimate") or "").strip()
            title = (e.get("milestone_name") or e.get("name") or "")
            span_bit = f"{span} " if span else ""
            lines.append(
                f"  {prefix} {eid}. {span_bit}{title}  [{tt}]"
            )
        protagonist_n = sum(
            1 for e in events
            if isinstance(e, dict) and e.get("event_type") == "protagonist_line"
        )
        world_n = sum(
            1 for e in events
            if isinstance(e, dict) and e.get("event_type") == "world_line"
        )
        n_milestones = len(
            [e for e in events if isinstance(e, dict)]
        )
        try:
            from graph.creation.nodes.path_gen_node import EVENT_CHAIN_BATCH_SLICE as _batch_slice
        except Exception:
            _batch_slice = 5
        batch_note = (
            f"[dim]本卷共 {n_milestones} 个里程碑；确认后路径将分批生成（每批最多 "
            f"{_batch_slice} 个里程碑，单章数依拆章而定，常见约 6～9 章）；"
            f"其余里程碑会在后续写作批次中继续转化为路径。[/dim]"
        )
        body = "\n".join(lines) if lines else "（无事件）"
        console.print(Panel(
            f"{batch_note}\n\n{body}",
            title=f"📋 「{vol_name}」事件链（主角线 {protagonist_n} + 世界线 {world_n}）",
            border_style="cyan",
            expand=False,
        ))

    elif prompt_type == "batch":
        nodes    = content.get("story_path", [])
        chapters = content.get("completed_chapters", [])
        lines    = []
        for i, node in enumerate(nodes):
            word_count = len(chapters[i]) if i < len(chapters) else 0
            lines.append(
                f"  [bold]{i+1}.[/bold]  "
                f"[cyan]{node.get('node_name', '')}[/cyan]  "
                f"[dim]{word_count} 字[/dim]"
            )
        console.print(Panel(
            "\n".join(lines) if lines else "（暂无章节）",
            title=f"📝 本批次完成（共 {len(nodes)} 节）",
            border_style="green",
            expand=False,
        ))
