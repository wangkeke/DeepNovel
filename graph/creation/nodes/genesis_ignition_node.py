"""
genesis_ignition_node：采样变量 → LLM 点燃开篇 → opening_review interrupt → v4.2 通过后进入 story_arc_plan（冰山与宏观已在先序完成）。
"""
from __future__ import annotations
import json
from langgraph.types import interrupt, Command
from schemas.state import CreationState
from utils.llm import call_llm_json
from utils.display import node_step, node_done
from knowledge.story_variables import (
    map_genre_bucket,
    sample_variables,
    variables_for_opening_regenerate,
    describe_targeting,
    describe_emotional,
    emotional_degree_opening_hint,
    format_genesis_flavor_block,
    VARIABLE_COMBINATIONS,
    build_fictional_hook_enforcement_block,
    resolve_fictional_hook_profile,
    merge_golden_finger_into_protagonist_dict,
)
from prompts.creation.genesis_iceberg import (
    GENESIS_OPENING_INSTRUCTIONS,
    GENESIS_OPENING_USER,
    platform_hint_for,
)
from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION
from prompts.creation.platform_styles import opening_platform_and_anti_ai_blocks
from utils.v42_flow import protagonist_archive_prompt_block


def _is_no_fictional_hook(fh: str) -> bool:
    """与 story_variables 里「无（…）」类档位一致：无挂时禁止重生/系统等叙事。"""
    t = (fh or "").strip()
    if not t or t in ("（无）", "无"):
        return True
    return t.startswith("无（")


def _iceberg_prompt4_section(state: CreationState) -> str:
    """冰山 PROMPT4 结构化结果（写入 synopsis.iceberg_prompt4）；genesis 须据此落笔。"""
    syn = state.get("synopsis") if isinstance(state.get("synopsis"), dict) else {}
    p4 = syn.get("iceberg_prompt4")
    if not isinstance(p4, dict) or not p4:
        return ""
    try:
        blob = json.dumps(p4, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        blob = str(p4)
    lim = 14000
    if len(blob) > lim:
        blob = blob[: lim - 20] + "\n…（截断）"
    return (
        "## 【冰山 PROMPT4 · 已推导开篇结构（须落实；禁止与 JSON 矛盾）】\n"
        + blob
    )


def _locked_protagonist_section(state: CreationState) -> str:
    """
    v4.2：注入 **PROMPT 3 全量主角卡**（与 `protagonist_archive_prompt_block` 一致），
    而非仅假面/外貌；开篇 LLM 须据此写同一人，不得换人/改名/性转。
    """
    card = state.get("protagonist_card")
    if not isinstance(card, dict):
        card = {}
    syn = state.get("synopsis") if isinstance(state.get("synopsis"), dict) else {}
    name_state = (state.get("protagonist_name") or "").strip()
    std = (card.get("standard_name") or card.get("name") or "").strip()
    canon = name_state or std
    if not canon:
        return ""

    header: list[str] = [
        "## 【已锁定主角档案 · 开篇必须与此为同一人（最高优先级）】",
        "以下为 **PROMPT 3 全量主角卡**（先天/精神面板/成熟度/逆鳞/议程/人性逻辑/特质等），须整体遵守，禁止只取外貌或假面后另造人格。",
        f"- **叙事主视角姓名（正文须全程使用；禁止改名、禁止另造主角）**：{canon}",
    ]
    if std and name_state and std != name_state:
        header.append(
            f"- 档案用名：{std}（须与上为同一人，行文统一为「{canon}」）"
        )
    pl = (syn.get("protagonist") or "").strip()
    if pl:
        cap = 1200
        header.append(
            f"- 宏观构思「主角」字段摘要（须与档案为同一人）：{pl[:cap]}"
            + ("…" if len(pl) > cap else "")
        )

    # 与 event_chain / story_arc 同源的全量档案块（max_chars 放宽供开篇消化）
    archive_body = protagonist_archive_prompt_block(card, max_chars=12000)

    footer = (
        "---\n"
        "**铁律（开篇种子）**：叙事主视角必须是上述档案中的主角本人；禁止换人顶替、禁止性转；"
        "场景所处阶层/官职/性别与 **世界位置、外貌、假面** 须一致；"
        "禁止舍弃档案中的逆鳞、精神面板基调、人性逻辑与核心欲求/恐惧，另写一套人格。"
    )
    return "\n".join(header) + "\n\n" + archive_body + "\n\n" + footer + "\n"


def _genesis_opening_anchor_section(state: CreationState) -> str:
    """开篇仅注入主角锚点 + 开局画面，避免 plot_events / 全书设定污染首章。"""
    ua = state.get("user_anchors") or {}
    if not isinstance(ua, dict):
        return ""
    protagonist_anchor = ua.get("protagonist")
    if not isinstance(protagonist_anchor, dict):
        protagonist_anchor = {}
    if not (str(protagonist_anchor.get("name") or "").strip()):
        for ch in ua.get("characters") or []:
            if not isinstance(ch, dict):
                continue
            role = (ch.get("role") or "").strip()
            if "主" in role and "角" in role:
                protagonist_anchor = {
                    "name": (ch.get("name") or "").strip(),
                    "setting": (ch.get("traits") or "").strip(),
                }
                break
    opening_raw = ua.get("opening_scene")
    opening_s = ""
    if opening_raw is not None:
        opening_s = str(opening_raw).strip()
        if opening_s.lower() in ("null", "none"):
            opening_s = ""
    anchor_section = ""
    if protagonist_anchor or opening_s:
        anchor_section = "\n## 【用户强制开局锚点（绝对遵循）】\n"
        pn = (protagonist_anchor.get("name") or "").strip()
        ps = (protagonist_anchor.get("setting") or "").strip()
        if pn:
            anchor_section += f"- 主角设定：姓名【{pn}】，核心人设：{ps}\n"
        if opening_s:
            anchor_section += f"- 开局场景指令：必须以此画面为起点进行切入引爆：{opening_s}\n"
    # 脑洞阶段 user_anchors 的主角名可能与 protagonist_card 确认名不一致；开篇以锁定名为准
    pn_final = (
        (protagonist_anchor.get("name") or "").strip()
        if isinstance(protagonist_anchor, dict) else ""
    )
    locked_pn = (state.get("protagonist_name") or "").strip()
    if anchor_section and locked_pn and pn_final and pn_final != locked_pn:
        anchor_section += (
            f"\n- ⚠️ 全书锁定主角为「{locked_pn}」，与上述脑洞锚点名「{pn_final}」不一致："
            f"**正文必须以锁定名为准**，不得用锚点名作为叙事主角。\n"
        )
    return anchor_section


def _state_with_merged_golden_finger(state: CreationState, fh: str) -> CreationState:
    """开篇 LLM 与落库：在有无挂配方下把矩阵金手指写入主角卡/档案，供 archive 与下游读取。"""
    out: dict = dict(state)
    if _is_no_fictional_hook((fh or "").strip()):
        return out  # type: ignore[return-value]
    for key in ("protagonist_card", "protagonist_archive"):
        c = state.get(key)
        if not isinstance(c, dict):
            continue
        merged = merge_golden_finger_into_protagonist_dict(c, fh)
        if merged is not c:
            out[key] = merged
    return out  # type: ignore[return-value]


def _variables_block(genre_request: str, v: dict) -> str:
    td = int(v.get("targeting_degree") or 0)
    ed = int(v.get("emotional_degree") or 0)
    bucket = v.get("genre_bucket") or map_genre_bucket(genre_request)
    ed_hint = emotional_degree_opening_hint(ed)
    block = (
        f"题材桶：{bucket}\n"
        f"针对度：{td} — {describe_targeting(td)}\n"
        f"情感度：{ed} — {describe_emotional(ed)}\n"
        f"人性逻辑腔调：{v.get('human_logic', '')}\n"
        f"故事模式：{v.get('story_mode', '')}\n"
        f"金手指/虚构钩子：{v.get('fictional_hook', '')}\n"
    )
    if ed_hint:
        block += f"\n{ed_hint}\n"
    return block


async def genesis_ignition_node(state: CreationState) -> Command:
    genre_request = state.get("genre_request", "")
    platform_style = (state.get("platform_style") or "").strip() or "通用网文"
    blueprint = state.get("blueprint", {})
    free_creation = state.get("free_creation", False)

    if not state.get("genesis_variables"):
        variables = sample_variables(genre_request)
        return Command(
            update={"genesis_variables": variables},
            goto="genesis_ignition",
        )

    variables = state.get("genesis_variables") or {}
    cand = (state.get("genesis_opening_candidate") or "").strip()
    feedback = (state.get("genesis_opening_feedback") or "").strip()

    if not cand or feedback:
        node_step("根据变量配方点燃开篇")
        bp_section = ""
        if not free_creation and blueprint:
            bp_section = json.dumps(
                {
                    "world_rule_type": blueprint.get("world_rule_type", ""),
                    "conflict_scale": blueprint.get("conflict_scale", ""),
                    "protagonist_power": blueprint.get("protagonist_power", ""),
                },
                ensure_ascii=False,
            )
        fb_section = ""
        if feedback:
            fh0 = (variables.get("fictional_hook") or "").strip()
            want_cheat_line = ""
            if fh0 and not fh0.startswith("无（"):
                want_cheat_line = (
                    "【重要】用户意见要求有挂：正文必须落实下文「金手指」条目（开篇内可见初次显效或与绝境咬合），"
                    "禁止仍按无挂纯权谋写完开篇。\n"
                )
            plain_line = ""
            if _is_no_fictional_hook(fh0):
                plain_line = (
                    "若配方中金手指为「无（…）」，禁止写重生/穿越记忆/系统/先知等任何外挂，只能用在场信息破局。\n"
                )
            fb_section = (
                f"【用户调整意见】{feedback}\n"
                + want_cheat_line
                + "以下为**本次生效**的变量配方（含针对度、情感度、逻辑、模式、金手指），正文必须与之完全一致。\n"
                + plain_line
            )
        cfg_key = variables.get("genre_bucket") or map_genre_bucket(genre_request)
        flavor_section = format_genesis_flavor_block(cfg_key, genre_request)
        fh = (variables.get("fictional_hook") or "").strip()
        # 金手指名称归一，确保后续根据名称索引到矩阵规则
        spec = resolve_fictional_hook_profile(fh)
        if spec and spec.get("display_name"):
            fh = str(spec["display_name"]).strip()
            variables["fictional_hook"] = fh
        no_hook_constraint = ""
        if _is_no_fictional_hook(fh):
            no_hook_constraint = (
                "【金手指铁律·当前为无挂配方】禁止：重生/前世记忆/再来一次、穿越先知、系统面板与任务、"
                "读心、全知剧透、签到抽奖等一切超规格信息外挂。主角只能依当场可见信息、合理推理与人性博弈破局；"
                "禁止出现「前世」「上一世」「我死过一次才明白」「记得那一世」等叙事（无挂不得以回忆另一段人生偷渡情报）。\n\n"
            )
        hook_extra = ""
        if fh and not _is_no_fictional_hook(fh):
            hook_extra = (
                f"【虚构元素融入】本卷金手指设定：{fh}\n"
                "须自然出现在绝境或关键认知转折中，禁止系统廉价弹窗式描写。\n"
            )
        hook_struct_block = ""
        if fh and not _is_no_fictional_hook(fh):
            hook_struct_block = build_fictional_hook_enforcement_block(fh) + "\n"
        state_for_locked = _state_with_merged_golden_finger(state, fh)
        merge_gf_patch: dict = {}
        for key in ("protagonist_card", "protagonist_archive"):
            if state_for_locked.get(key) is not state.get(key):
                merge_gf_patch[key] = state_for_locked.get(key)
        logic_n = variables.get("human_logic", "")
        mode_n = variables.get("story_mode", "")
        logic_desc = VARIABLE_COMBINATIONS["logic_tone"].get(logic_n, "")
        mode_desc = VARIABLE_COMBINATIONS["mode_tone"].get(mode_n, "")
        vb_extra = (
            no_hook_constraint
            + _variables_block(genre_request, variables)
            + f"\n人性逻辑释义：{logic_n} — {logic_desc}\n故事模式释义：{mode_n} — {mode_desc}\n"
            + hook_extra
            + hook_struct_block
        )
        user_anchors_section = _genesis_opening_anchor_section(state)
        locked_protagonist_section = _locked_protagonist_section(state_for_locked)
        locked_full = _locked_protagonist_section(state_for_locked)
        p4_blk = _iceberg_prompt4_section(state)
        if locked_full or p4_blk:
            locked_for_user = (
                "## 【与 system 对齐】\n"
                "完整「已锁定主角档案」与「冰山 PROMPT4」JSON 在 **system** 消息中（紧接宪法之后）；"
                "opening_text 须落实 PROMPT4 的 opening_collision / protagonist_tick / opening_tone，"
                "叙事主视角姓名、性别、职衔须与主角档案一致；"
                "禁止另造主视角、禁止改名、禁止性转；禁止引入档案与 PROMPT4 未出现的**有名有姓**角色顶替已定主角。\n"
            )
            sys_top = ""
            if locked_full:
                sys_top += locked_full + "\n\n"
            if p4_blk:
                sys_top += p4_blk + "\n\n"
        else:
            locked_for_user = locked_full
            sys_top = ""
        user_prompt = GENESIS_OPENING_USER.format(
            genre_request=genre_request,
            platform_style=platform_style,
            platform_hint=platform_hint_for(platform_style),
            locked_protagonist_section=locked_for_user,
            iceberg_prompt4_user_note="",
            user_anchors_section=user_anchors_section,
            flavor_section=flavor_section,
            variables_block=vb_extra,
            fictional_hook=fh or "（无）",
            blueprint_section=bp_section or "（无）",
            feedback_section=fb_section or "（无）",
        )
        system_prompt = (
            DEEPNOVEL_CONSTITUTION + "\n\n"
            + sys_top
            + GENESIS_OPENING_INSTRUCTIONS.rstrip()
            + "\n\n"
            + opening_platform_and_anti_ai_blocks(platform_style)
        )
        raw = await call_llm_json(system_prompt, user_prompt)
        opening = ""
        if isinstance(raw, dict):
            opening = (raw.get("opening_text") or "").strip()
        node_done("开篇草稿已生成")
        return Command(
            update={
                **merge_gf_patch,
                "genesis_opening_candidate": opening,
                "genesis_opening_feedback": "",
            },
            # candidate 为空时仍进入 interrupt，让用户选择重生或粘贴
            goto="genesis_ignition",
        )

    user_input = interrupt({
        "type": "opening_review",
        "content": {
            "opening_text": cand,
            "variables": variables,
            "genre_bucket": variables.get("genre_bucket", ""),
        },
        "prompt": "确认开篇种子（通过后进入核心班底→分卷规划），或重生成/手工改稿",
    })

    action = user_input.get("action", "approve")
    if action == "regenerate":
        fb = (user_input.get("feedback") or "").strip()
        new_vars = variables_for_opening_regenerate(genre_request, fb)
        return Command(
            update={
                "genesis_variables": new_vars,
                "genesis_opening_candidate": "",
                "genesis_opening_feedback": fb or "整体重写，保持张力",
                # 不在此写入 iceberg_*，避免与静态调度叠加时同一步重复更新（见 graph 开篇链仅用 Command）
                "genesis_opening_text": "",
            },
            goto="genesis_ignition",
        )
    if action == "edit_opening":
        new_text = (user_input.get("opening_text") or "").strip()
        if not new_text:
            new_text = cand
        return Command(
            update={
                "genesis_opening_text": new_text,
                "genesis_opening_candidate": "",
                "genesis_opening_feedback": "",
                "iceberg_review_payload": {},
                "iceberg_deduction_feedback": "",
                "iceberg_stage1_world_raw": {},
                "iceberg_stage1_cast_raw": {},
                "iceberg_synopsis_only": False,
            },
            goto="iceberg_deduction",
        )

    # approve → v4.2：开篇种子已点燃，进入 core_cast_gen → human_review_core_cast → story_arc_plan
    fh_ap = (variables.get("fictional_hook") or "").strip()
    spec_ap = resolve_fictional_hook_profile(fh_ap)
    if spec_ap and spec_ap.get("display_name"):
        fh_ap = str(spec_ap["display_name"]).strip()
    state_ap = _state_with_merged_golden_finger(state, fh_ap)
    merge_gf_approve: dict = {}
    for key in ("protagonist_card", "protagonist_archive"):
        if state_ap.get(key) is not state.get(key):
            merge_gf_approve[key] = state_ap.get(key)
    syn = dict(state.get("synopsis") or {})
    syn["opening_seed_text"] = cand
    return Command(
        update={
            **merge_gf_approve,
            "synopsis": syn,
            "genesis_opening_text": cand,
            "genesis_opening_candidate": "",
            "genesis_opening_feedback": "",
            "iceberg_review_payload": {},
            "iceberg_deduction_feedback": "",
            "iceberg_stage1_world_raw": {},
            "iceberg_stage1_cast_raw": {},
            "iceberg_synopsis_only": False,
        },
        goto="core_cast_gen",
    )
