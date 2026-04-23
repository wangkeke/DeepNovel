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
        appears = uv.get("appears_from_volume", 3)
        lines.append(
            f"具名顶格对手（班底卡，可选用）：{uv_name}（约从第 {appears} 卷起加重戏份；可早出场须符价码⇄刻意针对度）"
        )

    return "\n".join(lines)
