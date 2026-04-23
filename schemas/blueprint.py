from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal
from ulid import ULID


class PressureSource(BaseModel):
    who: str                    # 施压者（具体人物/势力/结构性存在）
    method: str                 # 施压手段（具体动作描述，不是类型标签）
    why_unavoidable: str        # 主角为何无法正面化解


class ChainItem(BaseModel):
    chain_type: str             # 类型名（如"多源汇聚型"）
    direction: Literal["pressure", "resolution"]
    info_asymmetry: Literal["protagonist", "antagonist", "none"] = "none"
    description: str            # 本节点中该逻辑链的具体表现
    event_indices: list[int] = Field(default_factory=list)  # 对应 event_path_chain 中的事件编号


class NodeChainRecord(BaseModel):
    node_name: str
    node_index: int
    # ★ 最核心字段：事件路径链
    # 格式："N. {谁} {做了什么/发生了什么} → {直接结果}"
    # 要求：4-8条，具体到可被套用的情节动作，不是主题归纳
    event_path_chain: list[str] = Field(default_factory=list)
    pressure_sources: list[PressureSource] = Field(default_factory=list)
    protagonist_constraint: str = ""    # 主角整体制约
    turning_event: str = ""             # 临界事件
    pressure_chains: list[ChainItem] = Field(default_factory=list)
    resolution_chains: list[ChainItem] = Field(default_factory=list)
    input_state: str = ""
    output_state: str = ""
    foreshadow_ids: list[str] = Field(default_factory=list)


class ForeshadowEntry(BaseModel):
    foreshadow_id: str
    surface_meaning: str
    true_meaning: str = ""         # 词条型可为空，等后续节点确定真实含义
    planted_at_node: int
    collected_at_node: int
    misdirect_direction: str
    truth_node_ref: str
    is_inferred: bool = False       # 片段提取时标注为推断
    # 词条/行为型扩展字段
    foreshadow_type: str = "event"  # event | noun | behavior
    mentioned_by: str = ""          # 词条型：谁在哪个场景里提到了这个词条
    story_potential: str = ""       # 伏笔可能推动故事发展的方向
    urgency: str = "latent"        # latent | building | ready
    mention_count: int = 1         # 正文中被提及的总次数


class NodeConnection(BaseModel):
    from_node: int
    to_node: int
    connection_logic: str           # 输出状态如何触发下一节点
    connection_type: str


class StructureTemplate(BaseModel):   # 第一层
    macro_pacing: str = ""
    volume_count: int = 0
    nodes_per_volume: int = 0
    words_per_node: int = 0
    storyline_count: int = 0
    storyline_merge_pattern: str = ""
    character_network: str = ""
    scene_distribution: list[str] = Field(default_factory=list)
    foreshadow_density: str = ""


class LogicPattern(BaseModel):        # 第二层
    payoff_rhythm: str = ""
    conflict_escalation: str = ""
    emotional_curve: str = ""
    turning_point_style: str = ""
    reader_expectation: str = ""
    writing_style: str = ""
    writing_skills: str = ""


class LogicChainMap(BaseModel):       # 第三层
    nodes: list[NodeChainRecord] = Field(default_factory=list)
    chain_type_sequence: list[str] = Field(default_factory=list)
    foreshadow_map: list[ForeshadowEntry] = Field(default_factory=list)
    node_connections: list[NodeConnection] = Field(default_factory=list)


class NovelBlueprint(BaseModel):
    blueprint_id: str = Field(default_factory=lambda: str(ULID()))
    source_title: str = ""
    genre_tags: list[str] = Field(default_factory=list)
    source_type: str = ""
    world_rule_type: Literal["realistic", "supernatural", "mixed"] = "realistic"
    conflict_scale: Literal["personal", "organizational", "world"] = "personal"
    protagonist_power: Literal["weak", "strong", "balanced"] = "weak"
    layer1: StructureTemplate = Field(default_factory=StructureTemplate)
    layer2: LogicPattern = Field(default_factory=LogicPattern)
    layer3: LogicChainMap = Field(default_factory=LogicChainMap)
    is_fragment: bool = False
    fragment_note: str = ""
    created_at: str = ""

PASS1A_OUTPUT_SCHEMA = {
    "node_name": "str - 本节点名称（取首章标题或自动命名）",
    "event_path_chain": [
        "str - 格式：'N. {谁} {做了什么/发生了什么} → {直接结果}' - 4到8条"
    ],
    "pressure_sources": [
        {
            "who": "str - 施压者（具体人物/势力/结构性存在，不是类型标签）",
            "method": "str - 具体施压手段（动作描述）",
            "why_unavoidable": "str - 主角为何无法正面化解"
        }
    ],
    "protagonist_constraint": "str - 主角整体制约条件（跨多施压源的）",
    "turning_event": "str - 哪一条具体事件触发了力量对比改变",
    "input_state": "str - 主角进入本节点时的处境和状态",
    "output_state": "str - 节点结束时主角的处境和状态改变",
    "new_entities": [
        {
            "standard_name": "str - 按优先级规则选取",
            "entity_type": "character|location|object|organization",
            "aliases": ["str"],
            "role_tags": ["str"],
            "is_narrator": False  # 第一人称叙述者标记
        }
    ],
    "updated_aliases": [
        {
            "entity_id_or_standard_name": "str - 已有实体",
            "new_alias": "str - 本批次新出现的别称"
        }
    ],
    "continuation_context": {
        "character_states": "str - 各主要人物当前状态",
        "unresolved_threads": "str - 悬而未决的线索",
        "last_output_state": "str - 尾部输出状态（供下批次使用）"
    }
}

TRUTH_OUTPUT_SCHEMA = {
    "incomplete": False,
    "key_truths": [
        {
            "truth_id": "str - T001格式",
            "who": "str - 关键实体",
            "what": "str - 做了什么",
            "motive": "str - 动机",
            "method": "str - 手法",
            "when_revealed": 0,
            "hints_to_find": "str - 前文应该找的早期暗示方向"
        }
    ]
}

PASS2_OUTPUT_SCHEMA = {
    "foreshadows_found": [
        {
            "foreshadow_id": "str - F001格式",
            "surface_meaning": "str - 读者当时的理解",
            "true_meaning": "str - 回头看的真实含义",
            "truth_node_ref": "str - 对应的 truth_id",
            "misdirect_direction": "str - 误导读者注意到哪里",
            "planted_at_node": 0,
            "is_inferred": False
        }
    ],
    "foreshadows_collected": [
        {
            "foreshadow_id": "str - 已有伏笔ID",
            "collected_at_node": 0,
            "collection_method": "str - 如何回收"
        }
    ]
}

PASS3_OUTPUT_SCHEMA = {
    "layer1": {
        "macro_pacing": "str",
        "volume_count": 0,
        "nodes_per_volume": 0,
        "words_per_node": 0,
        "storyline_count": 0,
        "storyline_merge_pattern": "str",
        "character_network": "str",
        "scene_distribution": ["str"],
        "foreshadow_density": "str"
    },
    "layer2": {
        "payoff_rhythm": "str",
        "conflict_escalation": "str",
        "emotional_curve": "str",
        "turning_point_style": "str",
        "reader_expectation": "str",
        "writing_style": "str",
        "writing_skills": "str"
    },
    "layer3": {
        "chain_type_sequence": ["str"],
        "node_connections": [
            {
                "from_node": 0,
                "to_node": 1,
                "connection_logic": "str",
                "connection_type": "str"
            }
        ]
    },
    "world_rule_type": "realistic|supernatural|mixed",
    "conflict_scale": "personal|organizational|world",
    "protagonist_power": "weak|strong|balanced",
    "genre_tags": ["str"]
}

