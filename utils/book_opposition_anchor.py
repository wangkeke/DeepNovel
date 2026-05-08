"""全书级压迫锚点：优先 synopsis（冰山/宏观），core_cast 仅作具名补充。"""

from __future__ import annotations


def book_opposition_prompt_block(
    synopsis: dict | None,
    core_cast: dict | None = None,
) -> str:
    """
    供分卷规划、事件链等用户提示使用。
    不依赖 ultimate_villain 姓名；以 ultimate_goal / core_conflict 为宏观锚点。
    """
    syn = synopsis or {}
    cc = core_cast or {}
    uv = cc.get("ultimate_villain") or {}
    uv_name = (uv.get("name") or "").strip()

    ultimate_goal = (syn.get("ultimate_goal") or "").strip()
    core_conflict = (syn.get("core_conflict") or "").strip()

    anchor = ultimate_goal or core_conflict
    if not anchor:
        anchor = (
            "（见小说设定全文中的核心矛盾与走向；勿凭空捏造与大纲无关的灭世级宿敌或无名顶格魔王）"
        )

    lines: list[str] = [f"【全书核心阻碍/终极目标】：{anchor}"]
    if ultimate_goal and core_conflict and ultimate_goal != core_conflict:
        lines.append(f"【核心冲突（补充）】：{core_conflict}")

    if uv_name:
        agenda = (uv.get("independent_agenda") or "").strip()
        trig = (uv.get("action_trigger") or "").strip()
        if agenda or trig:
            tail = []
            if agenda:
                tail.append(f"独立议程：{agenda}")
            if trig:
                tail.append(f"下场/碰撞触发：{trig}")
            lines.append(
                "具名顶格对手（班底卡，可选用）："
                + uv_name
                + "（"
                + "；".join(tail)
                + "；早同框须符价码⇄刻意针对度）"
            )
        else:
            lines.append(
                f"具名顶格对手（班底卡，可选用）：{uv_name}"
                "（碰撞时机由价码⇄刻意针对度与世界时钟驱动，勿写死出场卷）"
            )

    return "\n".join(lines)
