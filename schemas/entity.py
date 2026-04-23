from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal
from ulid import ULID


class MentalCore(BaseModel):
    """精神层面五维面板（0～100）。白皮书：资源决定上限，精神层面决定能否触及上限。"""

    intelligence: int = Field(default=50, ge=0, le=100, description="心智与社会阅历")
    eq: int = Field(default=50, ge=0, le=100, description="情商")
    meticulousness: int = Field(default=50, ge=0, le=100, description="思维缜密性")
    emotional_capacity: int = Field(
        default=60, ge=0, le=100, description="精神阈值容量（情绪控制力，可随剧情消耗）"
    )
    forbearance: int = Field(default=50, ge=0, le=100, description="隐忍度")


class HumanLogic(BaseModel):
    """人性逻辑：人物面对处境时的底层思维方式，可被模型直接执行的思维程序。"""
    logic_name: str
    core_essence: str
    trigger_conditions: list[str] = Field(default_factory=list)
    execution_steps: list[str] = Field(default_factory=list)
    termination: str = ""
    failure_risks: list[str] = Field(default_factory=list)
    origin: str = ""


class CharacterCard(BaseModel):
    """人物卡（data_json 中的结构）。"""
    model_config = {"extra": "allow"}

    role: Literal[
        "protagonist",      # 主角
        "core_supporting",  # 核心配角
        "antagonist",       # 反派
        "neutral",          # 中立者
        "minor",            # 过路角色
    ] = "minor"

    # 反派专用（role=antagonist 时必填）
    true_motive: str = ""

    # 中立者专用（role=neutral 时填写）
    neutral_stance: str = ""
    tipping_conditions: list[str] = Field(default_factory=list)

    background_summary: str = ""
    key_life_events: list[str] = Field(default_factory=list)
    dominant_logics: list[str] = Field(default_factory=list)
    logic_switch_conditions: list[dict] = Field(default_factory=list)

    innate_traits: list[str] = Field(
        default_factory=list,
        description="出厂性格底色（终生不改），如贪财、护短、多疑",
    )
    mental_core: MentalCore = Field(default_factory=MentalCore)
    maturity_level: str = Field(default="", description="成熟度阶段性描述（非道德审判）")
    current_emotional_drain: int = Field(
        default=0, ge=0, description="当前精神资源透支累计，触顶可与剧情联动爆发"
    )


class RelationEntry(BaseModel):
    entity_id: str
    relation: str                # 关系描述（"师徒"/"父子"/"对立"）


class EntityRecord(BaseModel):
    entity_id: str = Field(default_factory=lambda: str(ULID()))
    standard_name: str           # 标准名
    entity_type: Literal["character", "location", "object", "organization"]
    aliases: list[str] = Field(default_factory=list)   # 满足收录标准的别称
    role_tags: list[str] = Field(default_factory=list) # 身份标签（非别名）
    first_appeared_batch: int = 0
    related_entities: list[RelationEntry] = Field(default_factory=list)


class EntityRegistry(BaseModel):
    blueprint_id: str = ""
    entities: list[EntityRecord] = Field(default_factory=list)

    def find_by_name(self, name: str) -> EntityRecord | None:
        """先做字符串匹配（标准名 + 别名），找到则返回，找不到返回 None"""
        for e in self.entities:
            if e.standard_name == name or name in e.aliases:
                return e
        return None
