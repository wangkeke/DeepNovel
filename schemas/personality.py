"""
人物性格系统类型定义（供文档与校验用）。
实体存储仍以 dict 存于 entity_cards.data_json。
"""
from __future__ import annotations
from typing import TypedDict


class Trait(TypedDict, total=False):
    """性格特质（原材料）"""
    name: str
    trigger: str
    expression: str
    suppressed_by: list[str]


class TraitInteraction(TypedDict, total=False):
    """特质叠加规则（preset=天生, learned=习得）"""
    combo: list[str]
    condition: str
    result: str
    reader_expectation: str
    actual: str
    interaction_type: str  # "contrast" | "amplify" | "both"
    learned_from_seq: int
    trigger_event: str
