"""
idea_forge_node.py：意图解析与脑洞熔炉节点（v4.3 补丁 E：脑洞引擎）

职责：
  1. 接收用户的无格式输入（零输入、一句话或万字大纲均可）。
  2. 调用脑洞引擎四阶情绪配方提示词，产出 brainwave_formula / downstream_instructions 等。
  3. 合并 genesis_variables（与旧流水线一致）与 operational_user_anchors（下游 world_build / 冰山滴灌）。
  4. 写入 state 后进入 human_review_brainwave；开篇 immediate 任务由 iceberg_deduction 在 PROMPT4 缺失时回退注入。
  文档第五节、第六节为流程/衔接说明，见《补丁文档 E》与 utils.brainwave_engine、各下游节点注入逻辑，不写入 LLM。
"""
from __future__ import annotations

import logging
from pathlib import Path

from langgraph.types import Command

from knowledge.story_variables import (
    map_genre_bucket,
    sample_variables,
    resolve_fictional_hook_profile,
    build_genre_constraints_prompt_for_brainwave,
)
from schemas.state import CreationState
from utils.display import node_done, node_step
from utils.llm import call_llm_json
from prompts.creation.synopsis import PLATFORM_MACRO_HINTS
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from prompts.creation.brainwave_engine import (
    BRAINWAVE_ENGINE_BODY,
    BRAINWAVE_IDEA_FORGE_GRAPH_BRIDGE,
)

logger = logging.getLogger("deepnovel.idea_forge")


def _merge_genesis_variables(genre_request: str, llm_gv: dict | None) -> dict:
    """以题材随机采样为底，用 LLM 推断值覆盖；始终校正 genre_bucket。"""
    base = sample_variables(genre_request)
    if not isinstance(llm_gv, dict):
        return base
    out = {**base}
    for key in ("human_logic", "story_mode", "fictional_hook"):
        v = llm_gv.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    fh = str(out.get("fictional_hook") or "").strip()
    spec = resolve_fictional_hook_profile(fh)
    if spec and spec.get("display_name"):
        out["fictional_hook"] = str(spec["display_name"]).strip()
    for key in ("targeting_degree", "emotional_degree"):
        if key not in llm_gv:
            continue
        try:
            out[key] = int(llm_gv[key])
        except (TypeError, ValueError):
            pass
    out["genre_bucket"] = map_genre_bucket(genre_request)
    return out


def _normalize_user_anchors(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    ua = dict(raw)
    for key, default in (
        ("world_rules", []),
        ("characters", []),
        ("emotional_lines", []),
        ("plot_events", []),
    ):
        if not isinstance(ua.get(key), list):
            ua[key] = list(default) if default else []
    if ua.get("opening_scene") is not None and not isinstance(ua.get("opening_scene"), str):
        ua["opening_scene"] = str(ua["opening_scene"])
    prot = ua.get("protagonist")
    if prot is not None and not isinstance(prot, dict):
        ua["protagonist"] = {}
    elif isinstance(prot, dict):
        ua["protagonist"] = {
            "name": str(prot.get("name") or "").strip(),
            "setting": str(prot.get("setting") or "").strip(),
        }
    rc = ua.get("reader_catharsis_note")
    if rc is None:
        ua["reader_catharsis_note"] = ""
    elif not isinstance(rc, str):
        ua["reader_catharsis_note"] = str(rc).strip()
    else:
        ua["reader_catharsis_note"] = rc.strip()
    return ua


def _operational_from_patch_e_doc(result: dict) -> dict:
    """
    若模型未输出 operational_user_anchors，则从补丁 E 的 user_anchors（immutable_*）
    与 brainwave_formula 粗映射为下游旧结构。
    """
    doc_ua = result.get("user_anchors")
    if not isinstance(doc_ua, dict):
        doc_ua = {}
    imm_c = doc_ua.get("immutable_characters")
    if not isinstance(imm_c, list):
        imm_c = []
    imm_p = doc_ua.get("immutable_plot_beats")
    if not isinstance(imm_p, list):
        imm_p = []
    imm_r = doc_ua.get("immutable_relationships")
    if not isinstance(imm_r, list):
        imm_r = []
    tone = doc_ua.get("immutable_tone")
    bf = result.get("brainwave_formula")
    if not isinstance(bf, dict):
        bf = {}
    oc = bf.get("opening_crisis")
    if not isinstance(oc, dict):
        oc = {}
    hook = str(bf.get("hook_sentence") or bf.get("core_hook") or "").strip()

    chars = [{"name": str(x).strip(), "role": "用户锚定", "traits": ""} for x in imm_c if str(x).strip()]
    plot_events = [
        {"event_description": str(x).strip(), "expected_stage": "开篇"}
        for x in imm_p
        if str(x).strip()
    ]
    emotional_lines = [str(x).strip() for x in imm_r if str(x).strip()]
    opening_scene = str(oc.get("scene") or "").strip() or None
    reader_note = hook
    if isinstance(tone, str) and tone.strip():
        reader_note = f"{tone.strip()}；{reader_note}".strip("；") if reader_note else tone.strip()

    return {
        "protagonist": {"name": "", "setting": ""},
        "opening_scene": opening_scene,
        "world_rules": [],
        "characters": chars,
        "emotional_lines": emotional_lines,
        "plot_events": plot_events,
        "reader_catharsis_note": reader_note[:800] if reader_note else "",
    }


def _prepend_narrative_era_into_anchors(ua: dict, narrative_era: str) -> dict:
    """将根级 narrative_era 同步进 user_anchors.world_rules，便于下游与人工审阅一致看见。"""
    ne = (narrative_era or "").strip()
    if not ne:
        return ua
    ua = dict(ua)
    wr = [str(x) for x in (ua.get("world_rules") or [])]
    prefix = f"[叙事时代与语体锚点] {ne}"
    filtered = [w for w in wr if not w.strip().startswith("[叙事时代与语体锚点]")]
    ua["world_rules"] = [prefix] + filtered
    return ua


def _brainwave_engine_payload(result: dict) -> dict:
    out: dict = {
        "user_anchors": result.get("user_anchors"),
        "open_space": result.get("open_space"),
        "brainwave_formula": result.get("brainwave_formula"),
        "inferred_world_seeds": result.get("inferred_world_seeds"),
        "downstream_instructions": result.get("downstream_instructions"),
    }
    ne = str(result.get("narrative_era") or "").strip()
    if ne:
        out["narrative_era"] = ne
    return {k: v for k, v in out.items() if v is not None}


async def idea_forge_node(state: CreationState) -> Command:
    node_step("启动脑洞熔炉：脑洞引擎（补丁 E）解析用户锚点与情绪配方…")

    raw_input = (state.get("user_raw_input") or "").strip()
    file_path = (state.get("framework_file_path") or "").strip()
    genre = (state.get("genre_request") or "通用网文").strip() or "通用网文"
    platform_style = (state.get("platform_style") or "").strip() or "通用网文"
    platform_macro_hint = PLATFORM_MACRO_HINTS.get(
        platform_style, PLATFORM_MACRO_HINTS["通用网文"]
    )

    parts: list[str] = []
    if raw_input:
        parts.append(raw_input)
    regen_fb = (state.get("brainwave_regen_feedback") or "").strip()
    if regen_fb:
        parts.append(
            "## 【用户要求调整脑洞/叙事锚点（须在不违背题材铁律的前提下整体自洽重写）】\n"
            + regen_fb
        )
    if file_path:
        path = Path(file_path)
        if path.is_file():
            try:
                parts.append(path.read_text(encoding="utf-8").strip())
            except OSError as e:
                logger.warning("无法读取框架/脑洞文件 %s: %s", file_path, e)

    content = "\n\n".join(p for p in parts if p)

    if not content.strip():
        content = (
            "（本次为**零输入**：用户未提供文本锚点。请在「第零步」将用户侧视为全部开放空间，"
            f"仅依据下列题材与平台风格，自主完成第一至四阶推理并输出规定 JSON。题材：{genre}。）"
        )
        logger.info("用户无文本锚点输入：以零输入模式调用脑洞引擎。")

    genre_iron = build_genre_constraints_prompt_for_brainwave(genre)
    brainwave_system = (
        DEEPNOVEL_CONSTITUTION + "\n\n" + genre_iron + "\n\n" + BRAINWAVE_ENGINE_BODY
    )
    user_prompt = (
        "**节点职责**：接收任意形式的用户输入，结合题材和平台风格，\n"
        "通过四阶情绪配方系统生成具备商业爆款潜力的完整脑洞配方。\n\n"
        f"## 用户指定题材：{genre}\n"
        f"{genre_iron}"
        f"## 目标平台与读者定位（必须严格遵守）\n"
        f"{platform_macro_hint}\n\n"
        f"## 用户的脑洞/原始输入：\n{content}\n\n"
        f"{BRAINWAVE_IDEA_FORGE_GRAPH_BRIDGE}"
    )

    try:
        result = await call_llm_json(brainwave_system, user_prompt, max_tokens=8000)
    except Exception as e:
        logger.warning("idea_forge LLM 失败，回退采样：%s", e)
        return Command(
            update={
                "genesis_variables": sample_variables(genre),
                "user_anchors": {},
                "brainwave_engine": {},
                "narrative_era": "",
                "brainwave_regen_feedback": "",
                "brainwave_approved": False,
            },
            goto="human_review_brainwave",
        )

    if not isinstance(result, dict):
        return Command(
            update={
                "genesis_variables": sample_variables(genre),
                "user_anchors": {},
                "brainwave_engine": {},
                "narrative_era": "",
                "brainwave_regen_feedback": "",
                "brainwave_approved": False,
            },
            goto="human_review_brainwave",
        )

    gv = _merge_genesis_variables(genre, result.get("genesis_variables"))
    op = result.get("operational_user_anchors")
    if isinstance(op, dict) and (op.get("protagonist") is not None or op.get("characters") is not None):
        ua = _normalize_user_anchors(op)
    else:
        ua = _normalize_user_anchors(_operational_from_patch_e_doc(result))

    ne = str(result.get("narrative_era") or "").strip()
    ua = _prepend_narrative_era_into_anchors(ua, ne)
    be = _brainwave_engine_payload(result)

    update_payload = {
        "genesis_variables": gv,
        "user_anchors": ua,
        "brainwave_engine": be,
        "narrative_era": ne,
        "brainwave_regen_feedback": "",
        "brainwave_approved": False,
    }

    node_done("脑洞炼化完成！脑洞引擎输出已写入 state。")
    return Command(
        update=update_payload,
        goto="human_review_brainwave",
    )
