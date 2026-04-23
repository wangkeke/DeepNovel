"""
EBD（情感纽带度）教义：阈值行为摘要 + expand1 注入文本。

与设计文档 docs/DeepNovel_EBD（情感纽带度）系统设计文档.md v1.1 对齐。
数值存于 entity_cards.data_json；本模块无 DB 依赖。
"""
from __future__ import annotations

# 与文档 §2.4 一致，供 Prompt / 校验引用
EBD_BOND_KINDS = frozenset({
    "friendship",
    "romance",
    "family",
    "rivalry_jealousy",
    "benefactor_debt",
    "alliance_interest",
    "contempt_instrumental",
    "blood_feud",
})

SITUATIONAL_EBD_RULES = """
【EBD 与剧情情境绑定（铁律，禁止脸谱化）】
- 重大协助或敌对升级须有剧情接口：人物如何得知局面？在场还是传闻？是否付得起代价？
- 禁止未获知困境、未在场的角色「凭空」全力护主或下死手；允许焦虑、托人传话、拖延、装不知道等合法反应。
- 高正向：可写超理性庇护，但必须写出名誉/资源/关系等可感知代价。
- 高负向：可写阴忍、借刀、等窗口，不必每次当面发作。
"""


def normalize_ebd_int(raw) -> int:
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return 0
    if isinstance(raw, int):
        return max(-100, min(100, raw))
    try:
        s = str(raw).strip()
        if not s:
            return 0
        return max(-100, min(100, int(float(s))))
    except (TypeError, ValueError):
        return 0


def _rule_line_for_band(ebd: int) -> str:
    if ebd >= 80:
        return "可为核心关系做出超理性选择；须与 § 情境绑定一致，禁止无因极端"
    if ebd >= 60:
        return "深度信任或深度仇恨；高风险协助或主动打击须有因果与代价"
    if ebd >= 30:
        return "明显偏向；合作或作对须有利益/情义逻辑，禁止无因卖命"
    if ebd >= 0:
        return "中性偏正向；以利益与观感为主，可被动出手"
    if ebd >= -30:
        return "轻度排斥；不主动帮，可敷衍或观望"
    if ebd >= -60:
        return "明显敌视；日常为难与设障，表面合作须写暗算"
    if ebd >= -80:
        return "强烈敌意；主动寻机打击，行为服从恨意逻辑"
    return "执念级对立；可不计短期自利，仍须有叙事起因"


def _bond_hint(bond: str) -> str:
    if not bond:
        return "（未标注 ebd_bond_kind 时仅按数值挡位约束，避免写成恋爱独占除非正文已建立）"
    hints = {
        "friendship": "友情/同道：忌写成无理由恋爱独占或性意味束缚。",
        "romance": "爱情或单向爱慕：吃醋与牺牲须匹配关系阶段与信息来源。",
        "family": "亲情/拟亲属：可写庇护与绑架式关爱，须写家族反作用力。",
        "rivalry_jealousy": "竞争与嫉妒：可较早出现拆台与暗算，忌无铺垫升格为血仇。",
        "benefactor_debt": "恩情/师徒：动机以还债与道义为主，忌偷换为无因恋爱。",
        "alliance_interest": "利益同盟：随时可能反悔或加码条件，禁止写成无脑忠义。",
        "contempt_instrumental": "蔑视/工具化：克扣、羞辱、规则卡位，忌突然无偿倾囊。",
        "blood_feud": "血债/族恨：升级须与史因相连，禁止见人就咬。",
    }
    return hints.get(bond, f"关系大类 `{bond}`：行为须与文档 §2.4 力度边界一致。")


def build_ebd_constraint(char_ebd_list: list[dict]) -> str:
    """
    生成注入 expand1 的 EBD 行为约束段落。
    char_ebd_list 每项建议含：name, ebd_to_protagonist（或 ebd）, ebd_type, ebd_bond_kind（可选）, ebd_note（可选）
    """
    if not char_ebd_list:
        return ""
    lines = ["【角色情感纽带度 · EBD 行为约束（铁律）】", ""]
    for c in char_ebd_list:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        ebd = normalize_ebd_int(c.get("ebd_to_protagonist", c.get("ebd", 0)))
        ebd_type = (c.get("ebd_type") or "").strip() or "（未标注）"
        bond = (c.get("ebd_bond_kind") or "").strip()
        note = (c.get("ebd_note") or "").strip()
        crack = bool(c.get("ebd_crack"))
        rule = _rule_line_for_band(ebd)
        bond_hint = _bond_hint(bond)
        lines.append(f"▶ {name}  EBD {ebd:+d}（{ebd_type}）" + (f"  [bond={bond}]" if bond else ""))
        if note:
            lines.append(f"  备忘：{note}")
        lines.append(f"  行为档：{rule}")
        lines.append(f"  关系种类：{bond_hint}")
        if crack:
            lines.append("  特殊：ebd_crack=爱生恨等裂痕后，正向恢复受限，禁止写成无条件既往不咎。")
        lines.append("")
    lines.append(SITUATIONAL_EBD_RULES.strip())
    lines.append("")
    lines.append(
        "[EBD 全局铁律] 情绪、对话、行动须与上表及情境绑定一致；"
        "禁止与当前 EBD 矛盾的大幅倒戈或无条件神降，除非正文写明可信触发与代价。"
    )
    return "\n".join(lines)


def core_cast_ebd_seed_for_name(core_cast: dict | None, name: str) -> dict:
    """
    从已确认的全书班底中为某名抽取初始 EBD 字段，用于首次写入 entity_cards。
    不匹配则返回空 dict。
    """
    if not core_cast or not name or not isinstance(core_cast, dict):
        return {}
    nm = name.strip()
    if not nm:
        return {}

    def pick(d: dict, default_bond: str) -> dict:
        if not isinstance(d, dict) or (d.get("name") or "").strip() != nm:
            return {}
        out = {
            "ebd_to_protagonist": normalize_ebd_int(d.get("ebd_to_protagonist", 0)),
            "ebd_bond_kind": (d.get("ebd_bond_kind") or default_bond or "").strip(),
            "ebd_type": (d.get("ebd_type") or "").strip(),
            "ebd_note": (d.get("ebd_note") or "").strip(),
            "ebd_crack": 1 if d.get("ebd_crack") else 0,
        }
        for key in ("current_mental_state", "mental_growth_path", "reverse_scale"):
            raw = d.get(key)
            if raw is None:
                continue
            s = str(raw).strip()
            if s:
                out[key] = s
        return out

    uv = core_cast.get("ultimate_villain") or {}
    got = pick(uv, "blood_feud")
    if got:
        return got
    sp = core_cast.get("supreme_power") or {}
    got = pick(sp, "contempt_instrumental")
    if got:
        return got
    for a in core_cast.get("lifelong_allies") or []:
        if not isinstance(a, dict):
            continue
        got = pick(a, "friendship")
        if got:
            return got
    return {}


def merge_ebd_entries_for_expand1(
    char_cards: list[dict],
    key_order: list[str],
    core_cast: dict | None,
) -> list[dict]:
    """按 key_order 合并 DB 卡与 core_cast 缺省，供 build_ebd_constraint。"""
    by_name = {c.get("name"): c for c in char_cards if c.get("name")}
    out: list[dict] = []
    for nm in key_order:
        if not nm:
            continue
        card = by_name.get(nm) or {}
        seed = core_cast_ebd_seed_for_name(core_cast, nm)
        ebd = card.get("ebd_to_protagonist")
        if ebd is None or ebd == "":
            ebd = seed.get("ebd_to_protagonist", 0)
        bond = (card.get("ebd_bond_kind") or seed.get("ebd_bond_kind") or "").strip()
        et = (card.get("ebd_type") or seed.get("ebd_type") or "").strip()
        note = (card.get("ebd_note") or seed.get("ebd_note") or "").strip()
        crack = bool(card.get("ebd_crack")) or bool(seed.get("ebd_crack"))
        out.append({
            "name": nm,
            "ebd_to_protagonist": normalize_ebd_int(ebd),
            "ebd_bond_kind": bond,
            "ebd_type": et or "（未标注）",
            "ebd_note": note,
            "ebd_crack": crack,
        })
    return out
