"""LLM 单次调用内的结构化思考流（CoT）：把 __step_3_产出 展平为顶层键，兼容下游节点。"""

COT_STEP3_KEY = "__step_3_产出"


def flatten_cot_output(result: dict | None) -> dict:
    """
    若模型按 CoT 返回 { __step_1_*, __step_2_*, __step_3_产出: {...} }，
    将 step3 字典合并到顶层（step3 键覆盖同名键），便于 tension_check / write 等读取。
    若缺少 __step_3_产出，则原样返回副本（兼容旧版平面 JSON）。
    """
    if not isinstance(result, dict):
        return {}
    step3 = result.get(COT_STEP3_KEY)
    if isinstance(step3, dict):
        rest = {k: v for k, v in result.items() if k != COT_STEP3_KEY}
        return {**rest, **step3}
    return dict(result)
