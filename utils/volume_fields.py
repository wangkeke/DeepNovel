"""分卷规划字段：dynamic_gray_factions 等与下游 prompt 文本格式化。"""
from __future__ import annotations


def normalize_dynamic_gray_factions(raw: object) -> list[dict]:
    """
    将 LLM 输出的 dynamic_gray_factions 规范为对象列表。
    每项：name, resource_monopoly, current_stance, is_ultimate_boss
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(
                {
                    "name": item.strip(),
                    "resource_monopoly": "",
                    "current_stance": "",
                    "is_ultimate_boss": False,
                }
            )
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        boss = item.get("is_ultimate_boss")
        if isinstance(boss, str):
            boss = boss.lower() in ("true", "1", "yes")
        else:
            boss = bool(boss)
        out.append(
            {
                "name": name,
                "resource_monopoly": str(item.get("resource_monopoly") or "").strip(),
                "current_stance": str(item.get("current_stance") or "").strip(),
                "is_ultimate_boss": boss,
            }
        )
    return out


def format_dynamic_gray_factions_for_prompt(factions: list | None) -> str:
    """注入 path_gen / event_chain 等：人类可读的一小段说明。"""
    facs = normalize_dynamic_gray_factions(factions)
    if not facs:
        return "（无）"
    lines: list[str] = []
    for f in facs:
        nm = f.get("name") or ""
        res = f.get("resource_monopoly") or ""
        st = f.get("current_stance") or ""
        ub = f.get("is_ultimate_boss")
        tag = " [终局Boss候选]" if ub else ""
        extra = " | ".join(x for x in (res, st) if x)
        lines.append(f"{nm}{tag}" + (f"（{extra}）" if extra else ""))
    return "；".join(lines)
