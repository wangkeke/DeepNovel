"""
idea_forge_node.py：意图解析与脑洞熔炉节点

职责：
  1. 接收用户的无格式输入（哪怕只有一句话，或长达万字的大纲）。
  2. 提取出系统必需的【创世变量】（用于启动 Genesis）。
  3. 将用户提到的具体情节、人物、设定分拣为【用户强制锚点 user_anchors】。
  4. 写入 state，供下游 world_build / 冰山 / 分卷 / 事件链 嵌合（下游按需注入 prompt）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from langgraph.types import Command

from knowledge.story_variables import (
    map_genre_bucket,
    sample_variables,
    resolve_fictional_hook_profile,
)
from schemas.state import CreationState
from utils.display import node_done, node_step
from utils.llm import call_llm_json
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from prompts.creation.synopsis import PLATFORM_MACRO_HINTS

logger = logging.getLogger("deepnovel.idea_forge")

_IDEA_FORGE_SYSTEM = (DEEPNOVEL_CONSTITUTION + "\n\n" + """
你是一位顶级网文主编、数据结构化专家，也是深谙读者心理的责任编辑。

用户的每一个字（一句话脑洞或万字大纲）都是**创世奇点**：你只「翻译」、不替用户改稿。
【表层】题材、人物出厂设定、必发桥段、感情线、用户锚定的爽点；【深层】识别精神代偿（逆袭、被偏爱、掌控感、手撕伪善、清醒独立、证道等）——可在 `reader_catharsis_note` 用一句话写出，不得编造与用户锚点无关的爽点。

你的任务是充当“全维度锚点分拣机”：
1. 【绝对忠实】：只要用户明确提出了人物名、特定事件、感情线要求、特定设定，你必须【原封不动】地提取到对应的 `user_anchors` 结构中。绝不可删改用户的私货！
2. 【智能补全】：如果用户没提到某些方面（比如只给了个结尾，没给人物），对应的 anchor 数组请保持为空[]，让下游系统自行推演。
3. 【系统变量翻译】：你必须根据用户的描述氛围，为其推断出最合适的 5 大 `genesis_variables` 字段（targeting_degree、emotional_degree、human_logic、story_mode、fictional_hook）。

只返回符合格式的 JSON，不加任何前言。
""").strip()

_IDEA_FORGE_JSON_TASK = """
## 任务：请解析并分拣为以下 JSON 结构

{
  "genesis_variables": {
    "targeting_degree": 整数0-100(根据用户脑洞中主角开局面临的危机烈度推断，灭门填90+，平淡开局填10+),
    "emotional_degree": 整数-100到100(开局核心矛盾方对主角的情感：血海深仇<-80，漠视0左右，病态深爱>80),
    "human_logic": "从【马基雅维利逻辑/设局逻辑/野心家逻辑/复仇逻辑/忍辱逻辑/执念逻辑/舔狗逻辑/推理逻辑】中选一个最契合反派或整体基调的",
    "story_mode": "从【极渊求生/极渊坠落/浮沉逆转/暗流涌动/极道横推】中选一个",
    "fictional_hook": "用户指定的金手指（如‘读心术’、‘系统’）。若用户未指定，请结合题材为其量身定制一个，若用户明确要求无外挂，必须填‘无’"
  },

  "user_anchors": {
    "protagonist": {
      "name": "主角的姓名（未提及则填空字符串）",
      "setting": "主角的身份背景、性格特征、外貌、执念等核心设定（无则填空）"
    },
    "opening_scene": "如果用户描述了开局画面，请提取。若无填 null",
    "world_rules":[
      "用户明确设定的世界观/功法/阶级/禁忌等（无则空数组）"
    ],
    "characters":[
      {
        "name": "人物名",
        "role": "如：女主/反派/炮灰/白月光",
        "traits": "用户赋予的性格或命运设定"
      }
    ],
    "emotional_lines":[
      "用户要求的感情线（如：被渣男背叛后断情绝爱、大女主驾驭群臣、先婚后爱等。无则空数组）"
    ],
    "plot_events":[
      {
        "event_description": "用户要求必须发生的具体桥段（如：暴雨中女配背叛跌落悬崖、宴会上当众打脸退婚女）",
        "expected_stage": "推断该事件应放在：开篇 / 中期 / 后期 / 结局"
      }
    ],
    "reader_catharsis_note": "一句话：用户潜意识想要的精神代偿（可为空字符串）"
  }
}
""".strip()


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
    # 金手指名称归一：若用户/LLM 给出别名，统一为矩阵 display_name，便于后续索引注入。
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


async def idea_forge_node(state: CreationState) -> Command:
    node_step("启动脑洞熔炉：全维度解析用户创作锚点…")

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
    if file_path:
        path = Path(file_path)
        if path.is_file():
            try:
                parts.append(path.read_text(encoding="utf-8").strip())
            except OSError as e:
                logger.warning("无法读取框架/脑洞文件 %s: %s", file_path, e)

    content = "\n\n".join(p for p in parts if p)

    if not content.strip():
        logger.info("用户无文本锚点输入：采样创世变量后进入世界设定。")
        return Command(
            update={"genesis_variables": sample_variables(genre)},
            goto="world_build",
        )

    user_prompt = (
        f"## 用户指定题材：{genre}\n"
        f"## 目标平台与读者定位（必须严格遵守；影响主角性别、感情线与故事舞台）\n"
        f"{platform_macro_hint}\n\n"
        f"## 用户的脑洞/原始输入：\n{content}\n\n"
        f"{_IDEA_FORGE_JSON_TASK}"
    )

    try:
        result = await call_llm_json(_IDEA_FORGE_SYSTEM, user_prompt)
    except Exception as e:
        logger.warning("idea_forge LLM 失败，跳过锚点解析：%s", e)
        return Command(
            update={"genesis_variables": sample_variables(genre)},
            goto="world_build",
        )

    if not isinstance(result, dict):
        return Command(
            update={"genesis_variables": sample_variables(genre)},
            goto="world_build",
        )

    gv = _merge_genesis_variables(genre, result.get("genesis_variables"))
    ua = _normalize_user_anchors(result.get("user_anchors"))

    # 不在此写入 protagonist_name：该字段表示「主角卡已确认」后的标准名。
    # 锚点里的主角名仅放在 user_anchors.protagonist，供 genesis / 开篇滴灌；
    # 若此处预填 protagonist_name，会与 graph 中「有 protagonist_name 即进分卷」冲突，直接跳过主角卡流程。

    update_payload = {
        "genesis_variables": gv,
        "user_anchors": ua,
    }

    node_done("脑洞炼化完成！用户锚点已锁定。")
    return Command(
        update=update_payload,
        goto="world_build",
    )
