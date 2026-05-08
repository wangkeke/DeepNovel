"""
path_gen_node：故事路径规划（事件链 → 单章路径）

消费事件链批次（每条为约 2～6 章跨度的里程碑），优先通过 LLM 做 **1 拆 N**（分镜拆章 +
章末衔接/呼吸感线头），产出 `story_path` 单章节点；失败时回退为确定性 **里程碑 1:1** 转化。

`last_event_batch_size` 始终为本批 **里程碑条数**，与拆章后的节点数量无关；
`update_weight` 据此推进 `current_event_chain_pos`。
"""
from __future__ import annotations
import json
import logging
import aiosqlite
from langgraph.types import StreamWriter, Command
from schemas.state import CreationState
from memory.db import get_volumes, get_current_volume_index, get_event_chain_record
from config import DB_PATH
from prompts.creation.path_gen import PATH_GEN_SYSTEM, PATH_GEN_MILESTONE_USER_TEMPLATE
from prompts.creation.platform_styles import (
    RULE_PRECEDENCE_NOTICE,
    LIVING_COMPANION_RULES,
    platform_planning_bundle,
)
from prompts.common.high_tier_dynamic import FULL_OPPONENT_DOCTRINE
from utils.genre_lexicon import genre_lexicon_banner
from utils.llm import call_llm_json
from utils.volume_fields import format_dynamic_gray_factions_for_prompt
from utils.karmic_path import normalize_fruit_and_seed
from utils.path_relay import init_paths_status_from_paths

logger = logging.getLogger("deepnovel.path_gen")

# 每批从事件链切出的最大条数（与 update_weight 推进 delta 一致；适配次级剧情块粒度）
EVENT_CHAIN_BATCH_SLICE = 3


def _tension_to_pressure_resolution(tension: str) -> tuple[str, str, str]:
    t = (tension or "").strip()
    if "困境" in t:
        return "结构性困境型", "坚守与周旋型", "局中挣扎"
    if "反转" in t:
        return "认知颠覆型", "信息与局势再定型", "信息差反制"
    if "代价" in t:
        return "利益剥夺型", "取舍与交换型", "局中挣扎"
    if "悬念" in t:
        return "信息遮蔽型", "试探与验证型", "提前察觉"
    if "推波助澜" in t:
        return "多方博弈型", "借力破局型", "局中挣扎"
    if "信息差" in t:
        return "信息不对等型", "误导与反误导型", "信息差反制"
    return "情境压迫型", "临场应变型", "局中挣扎"


def _scene_result_from_event(e: dict) -> str:
    parts = []
    fp = (e.get("foreshadow_plant") or "").strip()
    fc = (e.get("foreshadow_collect") or "").strip()
    if fp:
        parts.append(f"埋下伏笔：{fp}")
    if fc:
        parts.append(f"回收/触及：{fc}")
    if e.get("has_reversal"):
        rh = (e.get("reversal_hint") or "").strip()
        parts.append(f"反转：{rh}" if rh else "局势/认知发生反转")
    return (
        "；".join(parts)
        if parts
        else "事件按动机推进至阶段性结果，须写出可见的后果与局面变化（禁止零后果过关）"
    )


def _batch_arc_stage(i: int, n: int, batch_index: int) -> str:
    if n <= 0:
        return "升级期"
    if batch_index == 0 and i == 0:
        return "建立期"
    if n == 1:
        return "升级期"
    pos = i / max(n - 1, 1)
    if pos < 0.2:
        return "建立期"
    if pos < 0.65:
        return "升级期"
    if pos < 0.85:
        return "高潮节点"
    if pos < 0.95:
        return "转折节点"
    return "落定期"


def _events_batch_to_story_nodes(
    events: list[dict],
    chain_pos_base: int,
    last_batch_ending: dict | None,
    volume: dict,
    batch_index: int,
    opening_seed_bridge: str = "",
) -> list[dict]:
    nodes: list[dict] = []
    n = len(events)
    villain = volume.get("volume_villain") or {}
    vn = villain.get("name", "")
    lbe_status = (last_batch_ending or {}).get("protagonist_status", "").strip()

    for i, e in enumerate(events):
        if not isinstance(e, dict):
            e = {}
        eid = e.get("id", i + 1)
        raw_name = (e.get("milestone_name") or e.get("name") or "").strip()
        node_name = raw_name or f"事件{eid}"
        loc = (e.get("location") or "").strip()
        mot = (e.get("motivation") or "").strip()
        ttype = (e.get("tension_type") or "").strip()
        conn_prev = (e.get("connection_to_previous") or "").strip()
        main_chars = e.get("main_chars") or []
        if isinstance(main_chars, str):
            main_chars = [
                x.strip()
                for x in main_chars.replace("，", ",").replace("、", ",").split(",")
                if x.strip()
            ]
        if not isinstance(main_chars, list):
            main_chars = []

        next_e = events[i + 1] if i + 1 < n else None
        prev_e = events[i - 1] if i > 0 else None

        if i == 0:
            if conn_prev:
                scene_cause = conn_prev
            elif lbe_status:
                scene_cause = lbe_status
            elif opening_seed_bridge:
                scene_cause = (
                    "承接全书已锁定开篇正文的收束局面，进入本批首条事件链；"
                    "须与开篇已定事实一致，禁止另起炉灶。"
                )
            else:
                scene_cause = "本批首事件：须承接卷内当前处境（与事件链 connection_to_previous 一致）"
        else:
            scene_cause = conn_prev if conn_prev else (
                f"紧接上一节点「{(prev_e or {}).get('name', '') or '?'}」结束后的局面"
            )

        chars_join = "、".join(str(c) for c in main_chars if c)
        segs = []
        if loc:
            segs.append(f"地点「{loc}」")
        if mot:
            segs.append(mot)
        if chars_join:
            segs.append(f"主要人物：{chars_join}")
        scene_process = "｜".join(segs) if segs else node_name

        scene_result = _scene_result_from_event(e)

        if next_e:
            nn = (next_e.get("milestone_name") or next_e.get("name") or "").strip()
            nconn = (next_e.get("connection_to_previous") or "").strip()
            scene_momentum = f"导入下一事件「{nn}」"
            if nconn:
                scene_momentum += f"：{nconn}"
        else:
            scene_momentum = (
                "本批末事件；下一批继续消费事件链后续条目，首部 connection_to_previous 承接"
            )

        one_liner = (
            f"[{ttype}] {mot}"
            if (ttype and mot)
            else (f"[{ttype}]{node_name}" if ttype else mot or node_name)
        )
        if len(one_liner) > 200:
            one_liner = one_liner[:197] + "…"

        pct, rct, rm = _tension_to_pressure_resolution(ttype)
        villain_note = f"本卷主线对立参照：{vn}" if vn else "本卷未单列 volume_villain"

        node: dict = {
            "node_name": node_name,
            "pressure_chain_type": pct,
            "resolution_chain_type": rct,
            "resolution_method": rm,
            "karmic_resources": [],
            "mental_lever": "（1:1 回退：由 expand1 结合事件链与人物精神面板补全扣机说明）",
            "fruit_and_seed": normalize_fruit_and_seed({}),
            "character_growth_trigger": "无",
            "pressure_source_logic": (
                f"{villain_note}。施压须来自本事件 motivation / 场景逻辑，禁止编造事件链未出现的新主线对立。"
            ),
            "tension_type": ttype,
            "tension_design": (
                f"事件链给定动机：{mot}"
                + (f"；伏笔：{e.get('foreshadow_plant')}" if e.get("foreshadow_plant") else "")
            ),
            "cost_for_protagonist": (
                "须在本章体现可感知代价（物资/名誉/身心/关系/秘密/欠情等至少其一），与事件链一致，禁止零代价"
            ),
            "key_characters": main_chars,
            "one_liner": one_liner,
            "arc_stage": _batch_arc_stage(i, n, batch_index),
            "arc_note": (
                f"事件链第 {chain_pos_base + i + 1} 项，事件 id={eid}；与本事件 1:1 对应，勿跳过勿合并"
            ),
            "scene_cause": scene_cause,
            "scene_process": scene_process,
            "scene_result": scene_result,
            "scene_momentum": scene_momentum,
            "_event_chain_global_index": chain_pos_base + i,
            "_event_id": eid,
            "_milestone_slice_index": 1,
        }

        if i == 0 and lbe_status:
            node["input_state_hint"] = (lbe_status + (f"；{conn_prev}" if conn_prev else ""))[:800]
        elif i == 0 and opening_seed_bridge and not lbe_status:
            node["input_state_hint"] = opening_seed_bridge[:800]
        elif i == 0:
            node["input_state_hint"] = scene_cause[:800]
        else:
            prev_nm = (
                (prev_e.get("milestone_name") or prev_e.get("name") or "").strip()
                if prev_e
                else ""
            )
            if conn_prev:
                node["input_state_hint"] = (f"「{prev_nm}」后：{conn_prev}")[:800]
            else:
                node["input_state_hint"] = (f"承接「{prev_nm}」结束后的局面")[:800]

        node["output_state_hint"] = f"{scene_result[:220]}；{scene_momentum[:220]}"

        nodes.append(node)
    return nodes


def _batch_event_ids(batch: list) -> set[int]:
    out: set[int] = set()
    for i, e in enumerate(batch):
        if isinstance(e, dict):
            try:
                out.add(int(e.get("id", i + 1)))
            except (TypeError, ValueError):
                out.add(i + 1)
        else:
            out.add(i + 1)
    return out


def _milestone_split_validation_ok(nodes: list, batch: list) -> bool:
    if not nodes or not isinstance(nodes, list):
        return False
    bid = _batch_event_ids(batch)
    seen: set[int] = set()
    for n in nodes:
        if not isinstance(n, dict):
            return False
        try:
            eid = int(n.get("_event_id"))
        except (TypeError, ValueError):
            return False
        if eid not in bid:
            return False
        seen.add(eid)
    if seen != bid:
        return False
    return len(nodes) >= len(batch)


def _ally_text(ally) -> str:
    if isinstance(ally, dict):
        nm = ally.get("name", "")
        mot = ally.get("motivation", "") or ally.get("role", "")
        return f"{nm}（{mot}）" if mot else (nm or "（无）")
    return str(ally or "（无）")


def _opening_seed_path_bridge(synopsis: dict, volume_index: int, chain_pos: int) -> str:
    """第 1 卷、事件链起始批：用开篇实录收束点衔接 path_gen，避免路径另起炉灶。"""
    if int(volume_index) != 0 or int(chain_pos) != 0:
        return ""
    text = ((synopsis or {}).get("opening_seed_text") or "").strip()
    if not text:
        return ""
    condensed = (
        text
        if len(text) <= 900
        else f"{text[:450]} ...（中略）... {text[-450:]}"
    )
    return (
        "【开篇正文结局状态·须无损承接】全书已锁定的序章/首章实录收束见下；"
        "本批路径（含首章节点）须从该收束点**直接**推入动作与因果，禁止另起炉灶、禁止重置开局、"
        "禁止「睡醒/大段回忆体」改写已定事实。\n\n"
        f"<opening_tail>\n{condensed}\n</opening_tail>"
    )


def _last_batch_section(
    last_batch_ending: dict | None,
    *,
    opening_fallback: str = "",
) -> str:
    if last_batch_ending:
        ps = (last_batch_ending.get("protagonist_status") or "").strip()
        hook = (
            last_batch_ending.get("last_hook")
            or last_batch_ending.get("hook")
            or ""
        ).strip()
        parts = []
        if ps:
            parts.append(f"上批结尾主角处境：{ps}")
        if hook:
            parts.append(f"上批收束钩：{hook}")
        if parts:
            return "；".join(parts)[:1200]
        return json.dumps(last_batch_ending, ensure_ascii=False)[:1200]
    if (opening_fallback or "").strip():
        return opening_fallback.strip()[:3500]
    return "（无；本批为当前卷路径起始段）"


def _normalize_llm_path_nodes(
    nodes: list[dict],
    batch: list[dict],
    chain_pos_base: int,
    batch_index: int,
    volume: dict,
) -> list[dict]:
    id_to_idx: dict[int, int] = {}
    for i, e in enumerate(batch):
        if isinstance(e, dict):
            try:
                eid = int(e.get("id", i + 1))
            except (TypeError, ValueError):
                eid = i + 1
        else:
            eid = i + 1
        id_to_idx[eid] = i

    villain = volume.get("volume_villain") or {}
    vn = villain.get("name", "")
    villain_note = f"本卷主线对立参照：{vn}" if vn else "本卷未单列 volume_villain"
    n_total = len(nodes)

    for j, n in enumerate(nodes):
        if not isinstance(n, dict):
            continue
        try:
            eid = int(n.get("_event_id"))
        except (TypeError, ValueError):
            fe = batch[0] if batch else {}
            eid = int(fe.get("id", 1)) if isinstance(fe, dict) else 1
        n["_event_id"] = eid
        batch_i = id_to_idx.get(eid, 0)
        n["_event_chain_global_index"] = chain_pos_base + batch_i

        ms = n.get("_milestone_slice_index")
        if ms is None:
            mss = 1
        else:
            try:
                mss = int(ms)
            except (TypeError, ValueError):
                mss = 1
        n["_milestone_slice_index"] = mss

        kc = n.get("key_characters")
        if isinstance(kc, str):
            n["key_characters"] = [
                x.strip()
                for x in kc.replace("，", ",").replace("、", ",").split(",")
                if x.strip()
            ]
        elif not isinstance(kc, list):
            n["key_characters"] = []

        n.setdefault("arc_stage", _batch_arc_stage(j, n_total, batch_index))
        n.setdefault(
            "arc_note",
            f"里程碑 id={eid} 第 {mss} 章；事件链全局第 {chain_pos_base + batch_i + 1} 项派生",
        )
        n.setdefault(
            "pressure_source_logic",
            f"{villain_note}。施压须来自本里程碑与卷内逻辑，禁止编造事件链未出现的新主线对立。",
        )
        kr = n.get("karmic_resources")
        if isinstance(kr, str) and kr.strip():
            n["karmic_resources"] = [kr.strip()]
        elif isinstance(kr, list):
            n["karmic_resources"] = [str(x).strip() for x in kr if str(x).strip()]
        else:
            n.setdefault("karmic_resources", [])
        n.setdefault("mental_lever", "")
        n["fruit_and_seed"] = normalize_fruit_and_seed(n.get("fruit_and_seed"))
        _cg = n.get("character_growth_trigger")
        if isinstance(_cg, str) and _cg.strip():
            n["character_growth_trigger"] = _cg.strip()[:500]
        else:
            n["character_growth_trigger"] = "无"

        ol = str(n.get("one_liner", "")).strip()
        inp = str(n.get("input_state_hint", "")).strip()
        out_h = str(n.get("output_state_hint", "")).strip()
        if not str(n.get("scene_cause", "")).strip():
            n["scene_cause"] = inp or ol or "须承接 input_state_hint 与上一章收束"
        if not str(n.get("scene_process", "")).strip():
            n["scene_process"] = ol or str(n.get("node_name", ""))
        if not str(n.get("scene_result", "")).strip():
            n["scene_result"] = (
                str(n.get("node_result", "")).strip()
                or out_h
                or "写出可见后果与局面变化（禁止零后果）"
            )
        if not str(n.get("scene_momentum", "")).strip():
            n["scene_momentum"] = (
                str(n.get("next_node_trigger", "")).strip()
                or out_h
                or "自然过渡到下一节点，或留下符合日常/危机氛围的情绪余韵，拒绝生硬断章"
            )

        if not inp:
            n["input_state_hint"] = str(n["scene_cause"])[:800]
        if not out_h:
            n["output_state_hint"] = (
                f"{str(n['scene_result'])[:220]}；{str(n['scene_momentum'])[:220]}"
            )[:800]

    return nodes


async def _llm_milestone_path(
    *,
    current_batch: list[dict],
    chain_pos: int,
    slice_end: int,
    event_chain: list,
    last_batch_ending: dict | None,
    batch_vol: dict,
    batch_index: int,
    state: CreationState,
    opening_fallback: str = "",
    last_batch_section_override: str | None = None,
) -> list[dict] | None:
    villain = batch_vol.get("volume_villain") or {}
    ally = batch_vol.get("volume_ally") or {}
    forbidden_text = format_dynamic_gray_factions_for_prompt(
        batch_vol.get("dynamic_gray_factions")
    )

    synopsis = state.get("synopsis", {}) or {}
    genre_banner = genre_lexicon_banner(synopsis, state.get("matched_genres") or [])
    # 平台+题材+受众定位宏观约束（只注入 macro hints，防拆章节奏跑偏平台调性）
    _platform_macro = platform_planning_bundle(state, skin_max_chars=0)
    system = (
        RULE_PRECEDENCE_NOTICE.strip()
        + "\n\n"
        + PATH_GEN_SYSTEM
        + "\n\n"
        + FULL_OPPONENT_DOCTRINE
        + f"\n\n{LIVING_COMPANION_RULES}\n"
        + "【单章出场(key_characters)铁律】：切分单章路径时，务必将主角的常驻配角（盟友/心腹/宿敌）排入关键人物名单。不要让主角孤狼单刷，让配角参与到信息交汇、掩护或基于保护的摩擦中来！"
    )
    if genre_banner.strip():
        system += "\n\n" + genre_banner
    if _platform_macro.strip():
        system += "\n\n" + _platform_macro

    vd = (batch_vol.get("volume_direction", "") or "").strip()
    synopsis_snip = (
        ((synopsis.get("direction", "") or "") + "；" + (synopsis.get("core_conflict", "") or ""))
        .strip()[:600]
    )

    if slice_end < len(event_chain):
        ne = event_chain[slice_end]
        next_teaser = json.dumps(ne if isinstance(ne, dict) else {}, ensure_ascii=False)[
            :900
        ]
    else:
        next_teaser = "（尚未读入下一里程碑：末章可收束本批或自然延续卷内弧）"

    mc = len(current_batch)
    lb_sec = (
        (last_batch_section_override or "").strip()
        if (last_batch_section_override or "").strip()
        else _last_batch_section(
            last_batch_ending,
            opening_fallback=opening_fallback,
        )
    )
    user = PATH_GEN_MILESTONE_USER_TEMPLATE.format(
        last_batch_section=lb_sec,
        volume_name=(batch_vol.get("volume_name", "") or "").strip() or "本卷",
        volume_direction=vd or "（见卷规划）",
        location_scope=(batch_vol.get("location_scope", "") or "").strip() or "（见卷规划）",
        conflict_intensity=str(batch_vol.get("conflict_intensity", "low") or "low"),
        villain_name=villain.get("name", ""),
        villain_motivation=villain.get("motivation", ""),
        ally_text=_ally_text(ally),
        forbidden_text=forbidden_text,
        synopsis_snip=synopsis_snip or "（无全书摘要字段）",
        events_json=json.dumps(current_batch, ensure_ascii=False),
        next_event_teaser=next_teaser,
        milestone_count=mc,
        min_nodes=max(mc * 2, 2),
        max_nodes=max(mc * 3, 3),
    )

    try:
        raw = await call_llm_json(system, user, max_tokens=12000)
    except Exception as e:
        logger.warning("path_gen：LLM 拆章失败，将回退 1:1：%s", e)
        return None

    nodes_raw: list | None = None
    if isinstance(raw, dict):
        nodes_raw = raw.get("nodes")
    elif isinstance(raw, list):
        nodes_raw = raw

    if not isinstance(nodes_raw, list) or not nodes_raw:
        return None

    nodes_norm = _normalize_llm_path_nodes(
        [dict(x) for x in nodes_raw if isinstance(x, dict)],
        current_batch,
        chain_pos,
        batch_index,
        batch_vol,
    )

    if not _milestone_split_validation_ok(nodes_norm, current_batch):
        logger.warning("path_gen：LLM 输出未通过里程碑溯源校验，回退 1:1")
        return None

    id_order: list[int] = []
    for i, e in enumerate(current_batch):
        if isinstance(e, dict):
            try:
                id_order.append(int(e.get("id", i + 1)))
            except (TypeError, ValueError):
                id_order.append(i + 1)
        else:
            id_order.append(i + 1)

    def sort_key(n: dict) -> tuple[int, int]:
        eid = int(n.get("_event_id", 0))
        try:
            bi = id_order.index(eid)
        except ValueError:
            bi = 999
        return (bi, int(n.get("_milestone_slice_index", 0)))

    nodes_norm.sort(key=sort_key)
    return nodes_norm


async def _load_last_batch_ending(project_id: str) -> dict | None:
    if not project_id:
        return None
    try:
        async with aiosqlite.connect(str(DB_PATH)) as conn:
            cursor = await conn.execute(
                "SELECT last_batch_ending FROM novel_projects WHERE project_id = ?",
                (project_id,),
            )
            row = await cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
    except Exception:
        pass
    return None


async def path_gen_node(state: CreationState, writer: StreamWriter) -> dict | Command:
    writer({"node_status": "started", "node": "path_gen"})

    project_id = state.get("project_id", "")
    last_batch_ending = await _load_last_batch_ending(project_id)

    volumes = list(state.get("volumes") or [])
    if not volumes and project_id:
        volumes = await get_volumes(project_id)

    if not volumes:
        logger.warning("path_gen：缺少 volumes，回到分卷规划")
        return Command(goto="human_review_story_arc")

    current_vol_index = (
        await get_current_volume_index(project_id)
        if project_id
        else int(state.get("current_volume_index", 0) or 0)
    )
    if not project_id:
        current_vol_index = int(state.get("current_volume_index", 0) or 0)

    event_chain = list(state.get("current_event_chain") or [])
    chain_pos = int(state.get("current_event_chain_pos", 0) or 0)
    if not event_chain and project_id:
        rec = await get_event_chain_record(project_id)
        if (
            rec is not None
            and int(rec.get("volume_index", -1)) == int(current_vol_index)
        ):
            event_chain = list(rec.get("events") or [])
            chain_pos = int(rec.get("chain_pos", 0) or 0)

    if not event_chain:
        logger.warning("path_gen：当前卷无事件链，回到事件链生成")
        return Command(
            update={
                "event_chain_draft": [],          # 清空旧草稿，强制 event_chain_gen 重新生成
                "current_event_chain": [],
                "current_event_chain_pos": 0,
                "last_event_batch_size": 0,
            },
            goto="event_chain_gen",
        )

    if current_vol_index >= len(volumes):
        logger.warning("path_gen：卷索引越界，结束批次审核")
        return Command(goto="human_review_batch")

    if chain_pos >= len(event_chain):
        if current_vol_index + 1 < len(volumes):
            return Command(
                update={
                    "current_volume_index": current_vol_index + 1,
                    "current_event_chain": [],
                    "current_event_chain_pos": 0,
                    "last_event_batch_size": 0,
                },
                goto="event_chain_gen",
            )
        return Command(
            update={
                "current_event_chain": event_chain,
                "current_event_chain_pos": chain_pos,
                "last_event_batch_size": 0,
            },
            goto="human_review_batch",
        )

    slice_end = min(len(event_chain), chain_pos + EVENT_CHAIN_BATCH_SLICE)
    current_batch = event_chain[chain_pos:slice_end]
    last_event_batch_size = len(current_batch)
    batch_vol = volumes[current_vol_index]
    batch_index = int(state.get("batch_index", 0) or 0)

    opening_bridge = _opening_seed_path_bridge(
        state.get("synopsis") or {},
        current_vol_index,
        chain_pos,
    )
    synopsis_pg = state.get("synopsis", {}) or {}
    opening_seed_pg = (synopsis_pg.get("opening_seed_text") or "").strip()
    opening_genesis_pg = (state.get("genesis_opening_text") or "").strip()
    opening_text_pg = opening_seed_pg or opening_genesis_pg
    if current_vol_index == 0 and chain_pos == 0 and opening_text_pg:
        tail_pg = (
            opening_text_pg[-300:]
            if len(opening_text_pg) > 300
            else opening_text_pg
        )
        last_batch_section_override = (
            "【⚠️ 极度重要：承接开篇种子结尾】\n"
            "（本批次为全书最开端首章派生）首个里程碑对应章节的 input_state_hint 须与下述开篇收束**无缝衔接**，"
            "禁止时光倒流、无故换视角或空话搭桥：\n"
            f"“...{tail_pg}”\n"
        )
    else:
        last_batch_section_override = None
    nodes = await _llm_milestone_path(
        current_batch=current_batch,
        chain_pos=chain_pos,
        slice_end=slice_end,
        event_chain=event_chain,
        last_batch_ending=last_batch_ending,
        batch_vol=batch_vol,
        batch_index=batch_index,
        state=state,
        opening_fallback=opening_bridge,
        last_batch_section_override=last_batch_section_override,
    )
    if not nodes:
        nodes = _events_batch_to_story_nodes(
            current_batch,
            chain_pos,
            last_batch_ending,
            batch_vol,
            batch_index,
            opening_bridge,
        )

    if current_batch and not nodes:
        logger.error(
            "path_gen：本批 %s 条事件但节点仍为空，请检查事件链字段 id/name",
            len(current_batch),
        )

    vol_meta = volumes[current_vol_index]
    volume_name = (vol_meta.get("volume_name", "") or "").strip() or "本卷"
    vd = (vol_meta.get("volume_direction", "") or "").strip()
    volume_tagline = (vd[:40] + "…") if len(vd) > 40 else (vd or volume_name)

    if last_batch_ending and nodes:
        first_node = nodes[0]
        first_input = first_node.get("input_state_hint", "")
        protagonist_status = last_batch_ending.get("protagonist_status", "")
        has_continuity = any(
            word in first_input
            for word in protagonist_status.split()
            if len(word) >= 2
        )
        if not has_continuity and protagonist_status:
            try:
                fix_prompt = (
                    f"上批结尾主角处境：{protagonist_status}\n"
                    f"下批第一节点当前 input_state_hint：{first_input}\n\n"
                    "请将 input_state_hint 修改为自然承接上批结尾的版本（保持事件链因果不变，"
                    "不超过80字）。只返回修改后的文字，不加任何解释。"
                )
                from utils.llm import call_llm
                fixed = await call_llm("你是一个故事连贯性编辑。", fix_prompt, max_tokens=120)
                nodes[0] = {**first_node, "input_state_hint": fixed.strip()}
            except Exception:
                pass

    out: dict = {
        "story_path":            nodes,
        "volume_name":           volume_name,
        "volume_tagline":        volume_tagline,
        "path_approved":         False,
        "current_node_index":    0,
        "last_event_batch_size": last_event_batch_size,
        "current_event_chain":   event_chain,
        "current_event_chain_pos": chain_pos,
        "pending_review_type":   "path",
    }
    # 必须用 Command(goto=…) 出队，勿仅 return dict：图侧若仍挂 conditional_edges(path_gen→…)，
    # LangGraph 会与 Command(goto=event_chain_gen) 并行调度路径审核，出现「事件链已生成却弹出空路径」。
    if state.get("auto_mode"):
        return Command(update=out, goto="auto_review")
    return Command(update=out, goto="human_review_path")


# ════════════════════════════════════════════════════════════════════════════════
# v4.3 单事件叙事拆解节点
# ════════════════════════════════════════════════════════════════════════════════

from prompts.creation.path_gen import (  # noqa: E402
    PATH_GEN_V43_SYSTEM,
    PATH_GEN_V43_USER_TEMPLATE,
    format_event_for_path_gen,
    format_recent_rhythm,
)
from utils.display import node_step, node_done  # noqa: E402


async def path_gen_v43_node(state: CreationState) -> Command:
    """
    v4.3 叙事拆解节点：
    1. 从 state 读取 current_event（event_chain_gen 输出的单事件）
    2. 从 state 读取 recent_rhythm（注入全局节奏约束）
    3. 从 state 读取角色档案和 karmic_ledger
    4. 调用新提示词，输出路径列表
    5. 将路径节奏信息追加到 recent_rhythm
    6. 写入 current_event_paths（供 expand1 逐路径消费）
    7. 初始化 path_progress.remaining_paths
    """
    current_event = state.get("current_event") or {}
    if not isinstance(current_event, dict) or not current_event:
        logger.warning("path_gen_v43：current_event 为空，无法拆解")
        return Command(goto="event_chain_gen")

    event_id = current_event.get("event_id", "unknown")
    event_name = current_event.get("event_name", "（未命名）")

    node_step(f"叙事拆解：{event_name}（{event_id}）→ 路径拆解")

    # 准备 prompt 输入
    event_output_text = format_event_for_path_gen(current_event)

    protagonist = state.get("protagonist_archive") or state.get("protagonist_card") or {}
    from utils.v42_flow import protagonist_archive_prompt_block as _pab
    character_archive_text = _pab(protagonist) if protagonist else "（无角色档案）"

    karmic_ledger = state.get("karmic_ledger") or []
    if isinstance(karmic_ledger, list) and karmic_ledger:
        try:
            karmic_text = json.dumps(karmic_ledger[-20:], ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            karmic_text = str(karmic_ledger)[:3000]
    else:
        karmic_text = "（无因果账本记录）"

    recent_rhythm = state.get("recent_rhythm") or {}
    recent_rhythm_text = format_recent_rhythm(recent_rhythm)

    from prompts.creation.platform_styles import platform_planning_bundle
    platform_style_block = platform_planning_bundle(state, skin_max_chars=0)

    # 开篇种子注入：全书首个事件且章节尚未写过时，告知编剧开篇已写完的内容边界
    opening_seed_section = ""
    _seed_text = ((state.get("synopsis") or {}).get("opening_seed_text") or "").strip()
    _gsec = int(state.get("global_settled_event_count", 0) or 0)
    _vol0 = int(state.get("current_volume_index", 0) or 0) == 0
    _is_first_event = _gsec == 0 and _vol0 and event_id.endswith("_001")
    if _seed_text and _is_first_event:
        opening_seed_section = (
            "## 【已写完的开篇正文（硬性边界，禁止重写）】\n\n"
            + _seed_text
            + "\n\n【路径拆解铁律】上述文本是本书第一章的**已定固定开端**，"
            "这段内容所覆盖的事件**不得再次出现在任何路径中**。"
            "路径规划必须从上述文本**末段情境结束之后**开始描述后续发生的事情，"
            "即：主角此刻已经完成了上述所有行动，接下来会发生什么？\n\n"
        )

    user_prompt = PATH_GEN_V43_USER_TEMPLATE.format(
        opening_seed_section=opening_seed_section,
        event_output=event_output_text,
        character_archive=character_archive_text,
        karmic_ledger=karmic_text,
        recent_rhythm=recent_rhythm_text,
        platform_style_block=platform_style_block,
        event_id=event_id,
        event_name=event_name,
    )

    raw = await call_llm_json(PATH_GEN_V43_SYSTEM, user_prompt, max_tokens=8000)

    # 处理 LLM 输出
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        raw = raw[0]
    if not isinstance(raw, dict):
        logger.warning("path_gen_v43：LLM 返回非 dict，使用最小占位")
        raw = {}

    # 确保关键字段存在
    raw.setdefault("event_id", event_id)
    raw.setdefault("event_name", event_name)
    raw.setdefault("total_paths", 0)
    paths = raw.get("paths") or []
    if not isinstance(paths, list):
        paths = []
    raw["paths"] = paths
    raw["total_paths"] = len(paths)
    raw.setdefault("scene_exit", "")

    # 更新 recent_rhythm：追加本次拆解的路径节奏信息
    existing_rhythm = dict(recent_rhythm) if isinstance(recent_rhythm, dict) else {}
    last_n_paths = list(existing_rhythm.get("last_n_paths") or [])
    for path in paths:
        if isinstance(path, dict):
            last_n_paths.append({
                "path_id": path.get("path_id", ""),
                "narrative_function": path.get("narrative_function", ""),
            })
    # 保留最近 20 个路径的节奏记录
    last_n_paths = last_n_paths[-20:]
    updated_recent_rhythm = {
        "last_n_paths": last_n_paths,
        "rhythm_note": raw.get("rhythm_note", ""),
        "global_rhythm_adjustment": raw.get("global_rhythm_adjustment", ""),
    }

    # 初始化 path_progress（补丁 G/H：paths_status + 合并稿占位 + 接力上下文）
    path_ids = [str(p.get("path_id", "")).strip() for p in paths if isinstance(p, dict)]
    path_ids = [x for x in path_ids if x]
    paths_status = init_paths_status_from_paths(paths)
    if paths_status:
        paths_status[0]["status"] = "in_progress"
    updated_path_progress = {
        "current_event_id": event_id,
        "completed_paths": [],
        "remaining_paths": path_ids,
        "paths_status": paths_status,
        "all_paths_text": "",
        "write_relay_context": "",
        "last_path_state_extract": {},
        "pending_inner_stream_chunks": [],
    }

    node_done(f"叙事拆解完成：{event_name} → {len(paths)} 个路径")

    next_goto = "auto_review" if state.get("auto_mode") else "human_review_path"
    return Command(
        update={
            "current_event_paths": raw,
            "recent_rhythm": updated_recent_rhythm,
            "path_progress": updated_path_progress,
            "pending_review_type": "path",
        },
        goto=next_goto,
    )
