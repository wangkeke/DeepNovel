# DeepNovel 骨骼系统 — LangGraph 工程设计文档 v2.0

> **本文档为完整开发规格，可直接交付 AI 编码助手执行。**
> 技术栈：LangGraph 1.1.2 · LangChain 1.2.18 · Python 3.11+ · uv 包管理
> 当前工作目录即为项目根目录，uv 环境已配置，测试命令用 `uv run python xxx.py`

---

## 零、开发前必读

### 关键约束（违反则系统失效）

1. **Prompt 质量是系统成败的唯一决定因素**。Pass 1a 的 Prompt 必须输出可被套用的事件路径链，而不是主题归纳。本文档提供了完整的 Prompt 文本，**不得自行改写**。
2. **Checkpointer 在 Phase 1 搭图时就挂载**，不能晚接入。LangGraph State 中的 Pydantic 对象必须序列化为 dict 存储，不能直接放 Pydantic 实例。
3. **实体注册表对齐必须与 Pass 1 循环同期完成**，不能推迟到 Phase 2。
4. **Pass 1b 的类型标注必须在 Pass 1a 的事件路径基础上归纳**，不能跳过 Pass 1a 直接做类型分类。
5. **LangGraph 版本为 1.1.2**，interrupt 机制使用 `interrupt()` + `Command`，不用旧版 `NodeInterrupt`。

### 运行方式

```bash
# 安装依赖
uv sync

# 运行 Phase 0 验证脚本
uv run python scripts/phase0_test.py --input test_texts/sample.txt

# 运行提取流
uv run python -m deepnovel extract --source file --path novel.txt

# 运行创作流
uv run python -m deepnovel create --blueprint-id <id> --genre "民俗恐怖"
```

---

## 一、系统总览

### 1.1 两大工作流

```
工作流 A：骨骼提取流（BlueprintExtractionGraph）
  输入：范文来源（文件路径 / 网址 / 骨骼库ID）
  输出：NovelBlueprint 存入骨骼库
  触发时机：用户提供范文时执行一次，之后可复用

工作流 B：小说创作流（NovelCreationGraph）
  输入：用户题材需求 + 骨骼ID（来自骨骼库）
  输出：完整小说正文 + 故事圣经
  触发时机：每次创作
```

两条工作流通过 **骨骼库（SQLite）** 连接，提取流写入，创作流读取。

### 1.2 项目目录结构

```
（工作空间根目录 = 项目根目录）
├── pyproject.toml
├── __main__.py
├── __init__.py
├── config.py                    # 全局配置
│
├── schemas/
│   ├── blueprint.py             # NovelBlueprint 及子模型（Pydantic v2）
│   ├── story.py                 # 故事节点、路径、圣经
│   ├── state.py                 # LangGraph State TypedDict
│   └── entity.py                # 实体注册表模型
│
├── tools/
│   ├── file_reader.py
│   ├── ocr_tool.py
│   ├── scraper_tool.py
│   └── blueprint_store.py
│
├── graph/
│   ├── extraction/
│   │   ├── graph.py
│   │   └── nodes/
│   │       ├── source_node.py
│   │       ├── segmenter_node.py
│   │       ├── pass1a_node.py
│   │       ├── pass1b_node.py
│   │       ├── truth_node.py
│   │       ├── pass2_node.py
│   │       ├── pass3_node.py
│   │       └── blueprint_save_node.py
│   │
│   ├── creation/
│   │   ├── graph.py
│   │   └── nodes/
│   │       ├── blueprint_load_node.py
│   │       ├── synopsis_node.py
│   │       ├── human_review_node.py
│   │       ├── path_gen_node.py
│   │       ├── expand1_node.py
│   │       ├── expand2_node.py
│   │       ├── write_node.py
│   │       ├── bible_update_node.py
│   │       └── consistency_node.py
│   │
│   └── edges.py
│
├── memory/
│   ├── db.py
│   ├── checkpointer.py
│   └── schema.sql
│
├── prompts/                     # 提示词（完整文本，见第七章）
│   ├── extraction/
│   │   ├── pass1a.py
│   │   ├── pass1b.py
│   │   ├── truth.py
│   │   ├── pass2.py
│   │   ├── pass3.py
│   │   └── segmenter.py
│   └── creation/
│       ├── synopsis.py
│       ├── path_gen.py
│       ├── expand1.py
│       ├── expand2.py
│       ├── write.py
│       ├── bible_update.py
│       └── consistency.py
│
├── scripts/
│   └── phase0_test.py           # Phase 0 验证脚本（见第八章）
│
├── test_texts/                  # Phase 0 测试文本（手动放入）
│
└── workspace/
    ├── blueprints.db
    └── novels/
```

---

## 二、依赖配置（pyproject.toml）

```toml
[project]
name = "deepnovel"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    # LangGraph / LangChain（锁定版本）
    "langgraph==1.1.2",
    "langchain==1.2.18",
    "langchain-openai>=0.3",
    "langchain-anthropic>=0.3",
    "langgraph-checkpoint-sqlite>=2.0",

    # 数据库
    "aiosqlite>=0.20",
    "sqlalchemy>=2.0",

    # 文件处理
    "python-docx>=1.1",
    "pypdf>=4.0",
    "aiofiles>=23.0",
    "chardet>=5.0",

    # OCR
    "rapidocr-onnxruntime>=1.4",

    # 网页爬取
    "scrapling>=0.2",

    # 数据验证
    "pydantic>=2.0",

    # CLI
    "rich>=13.0",

    # 工具
    "python-ulid>=2.0",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
]
```

---

## 三、数据模型（完整 Pydantic v2 代码）

### 3.1 schemas/blueprint.py

```python
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
    true_meaning: str
    planted_at_node: int
    collected_at_node: int
    misdirect_direction: str
    truth_node_ref: str
    is_inferred: bool = False       # 片段提取时标注为推断


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
```

### 3.2 schemas/entity.py

```python
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal
from ulid import ULID


class RelationEntry(BaseModel):
    entity_id: str
    relation: str                # 关系描述（"师徒"/"父子"/"对立"）


class EntityRecord(BaseModel):
    entity_id: str = Field(default_factory=lambda: str(ULID()))
    standard_name: str           # 标准名（选取规则见下方注释）
    entity_type: Literal["character", "location", "object", "organization"]
    aliases: list[str] = Field(default_factory=list)   # 满足收录标准的别称
    role_tags: list[str] = Field(default_factory=list) # 身份标签（非别名）
    first_appeared_batch: int = 0
    related_entities: list[RelationEntry] = Field(default_factory=list)

# ─────────────────────────────────────────────
# 标准名选取规则（优先级从高到低）：
#   优先级1：其他角色稳定使用的称呼或绰号 → standard_name
#            示例："老核桃"（其他角色叫他老核桃）
#   优先级2：有历史来源的称号 → aliases
#            示例："土匪师爷"（旧时身份称号）
#   优先级3：关系称谓（师父/大哥/师傅）→ related_entities.relation，绝不做 standard_name
#   优先级4：叙述者口语化称呼（老头儿/那家伙）→ role_tags，不进 aliases
#
# 别名不收录：骂人话、一次性情绪表达、身份描述标签、关系称谓、叙述者口语称呼
# 第一人称"我"永远不进任何人的 aliases
#
# 第一人称叙述验证规则：
#   对每个具名人物 X，检查是否存在"我看见X…"/"我跟着X…"这类第三人称观察句
#   如果存在 → X 不是叙述者，不与"我"绑定
#   典型错误：《邪门儿》中高大头是委托人，被"我"观察，不是叙述者
# ─────────────────────────────────────────────


class EntityRegistry(BaseModel):
    blueprint_id: str = ""
    entities: list[EntityRecord] = Field(default_factory=list)

    def find_by_name(self, name: str) -> EntityRecord | None:
        """先做字符串匹配（标准名 + 别名），找到则返回，找不到返回 None"""
        for e in self.entities:
            if e.standard_name == name or name in e.aliases:
                return e
        return None
```

### 3.3 schemas/state.py

```python
from __future__ import annotations
from typing import TypedDict, Annotated
import operator


# ─── 提取流 State ────────────────────────────────────────────────────────────
class ExtractionState(TypedDict):
    # 输入
    source_type: str                       # "file" | "url" | "library"
    source_path: str
    raw_text: str

    # 切分结果
    segments: list[dict]                   # {index, title, text, char_count, source_chapters}
    total_segments: int

    # Pass 1 累积
    # ⚠️ 用 Annotated + operator.add 让 LangGraph 自动合并列表，而不是覆盖
    current_batch_index: int
    batch_summaries: Annotated[list[dict], operator.add]  # 每批次摘要（含 event_path_chain）
    entity_registry: dict                  # 实体注册表 dict（不存 Pydantic 实例）
    pass1_context: dict                    # 延续上下文

    # 真相清单
    truth_manifest: dict

    # Pass 2 累积
    foreshadow_entries: Annotated[list[dict], operator.add]

    # Pass 3 输出
    blueprint: dict                        # 最终 NovelBlueprint dict

    # 控制
    is_fragment: bool
    extraction_complete: bool
    error: str | None


# ─── 创作流 State ────────────────────────────────────────────────────────────
class CreationState(TypedDict):
    project_id: str
    genre_request: str
    blueprint_id: str

    blueprint: dict
    blueprint_weight: float

    synopsis: dict
    synopsis_approved: bool

    story_path: list[dict]
    path_approved: bool
    current_node_index: int

    current_expand1: dict
    current_expand2: dict
    current_draft: str

    bible: dict

    consistency_result: dict
    has_violation: bool

    pivot_records: Annotated[list[dict], operator.add]
    post_pivot: bool

    completed_chapters: Annotated[list[str], operator.add]
    creation_complete: bool
    error: str | None
```

### 3.4 LLM 输出 JSON Schema（所有节点）

> 以下是每个节点期望 LLM 返回的 JSON 结构，用于 Prompt 构造和解析验证。

**Pass 1a 输出 Schema：**

```python
# prompts/extraction/pass1a_schema.py
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
```

**Pass 1b 输出 Schema：**

```python
PASS1B_OUTPUT_SCHEMA = {
    "pressure_chains": [
        {
            "chain_type": "str - 施压链类型名",
            "direction": "pressure",
            "info_asymmetry": "none|protagonist|antagonist",
            "description": "str - 本节点中的具体表现",
            "event_indices": [1, 2]  # 对应 event_path_chain 的编号
        }
    ],
    "resolution_chains": [
        {
            "chain_type": "str - 破局链类型名",
            "direction": "resolution",
            "info_asymmetry": "none|protagonist|antagonist",
            "description": "str",
            "event_indices": [4, 5]
        }
    ]
}
```

**逻辑链类型参考表（Pass 1b 使用）：**

```
施压链（6种）：
  间接施压型     - 第三方/结构/规矩作为施压载体，施压者不直接出面
  多源汇聚型     - 多个独立施压源同时作用，主角无法一次性应对
  资源争夺型     - 稀缺资源的争夺导致对立
  蝴蝶效应型     - 早期小事件蝴蝶效应演变为大压力
  自我实现困局型 - 主角的应对行为本身加剧了困境
  信任背叛链型   - 最信任的人成为致命威胁

破局链（6种）：
  信息差破局型   - 掌握对方不知道的信息完成逆转（标注方向：protagonist/antagonist）
  以弱胜强型     - 在明显劣势下完成逆转
  揭露反转型     - 已有信息的重新解读改变局势
  借力打力型     - 利用对方的力量/意图反将一军
  知识技能破局型 - 专业知识或技能成为胜负手
  纯推理型       - 纯逻辑推演找到出路
```

**Truth Node 输出 Schema：**

```python
TRUTH_OUTPUT_SCHEMA = {
    "incomplete": False,  # 片段文本时为 True
    "key_truths": [
        {
            "truth_id": "str - T001格式",
            "who": "str - 关键实体",
            "what": "str - 做了什么",
            "motive": "str - 动机",
            "method": "str - 手法",
            "when_revealed": 0,  # 在第几个节点揭露（0=全书末尾）
            "hints_to_find": "str - 前文应该找的早期暗示方向"
        }
    ]
}
```

**Pass 2 输出 Schema：**

```python
PASS2_OUTPUT_SCHEMA = {
    "foreshadows_found": [
        {
            "foreshadow_id": "str - F001格式",
            "surface_meaning": "str - 读者当时的理解",
            "true_meaning": "str - 回头看的真实含义",
            "truth_node_ref": "str - 对应的 truth_id",
            "misdirect_direction": "str - 误导读者注意到哪里",
            "planted_at_node": 0,  # 当前批次节点index
            "is_inferred": False   # 片段提取时为 True
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
```

**Pass 3 输出 Schema：**

```python
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
```

---

## 四、LangGraph 1.1.2 关键 API 用法

### 4.1 图定义标准模板

```python
# graph/extraction/graph.py
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite
from schemas.state import ExtractionState

async def build_extraction_graph(db_path: str):
    """构建提取流图，挂载 Checkpointer"""
    builder = StateGraph(ExtractionState)

    # 添加节点
    builder.add_node("source", source_node)
    builder.add_node("segmenter", segmenter_node)
    builder.add_node("pass1a", pass1a_batch_node)
    builder.add_node("pass1b", pass1b_batch_node)
    builder.add_node("truth", truth_node)
    builder.add_node("pass2", pass2_batch_node)
    builder.add_node("pass3", pass3_node)
    builder.add_node("save", blueprint_save_node)

    # 边定义
    builder.add_edge(START, "source")
    builder.add_edge("source", "segmenter")
    builder.add_edge("segmenter", "pass1a")
    builder.add_edge("pass1a", "pass1b")
    builder.add_conditional_edges(
        "pass1b",
        check_pass1_done,           # 路由函数
        {"continue": "pass1a", "done": "truth"}
    )
    builder.add_edge("truth", "pass2")
    builder.add_conditional_edges(
        "pass2",
        check_pass2_done,
        {"continue": "pass2", "done": "pass3"}
    )
    builder.add_edge("pass3", "save")
    builder.add_edge("save", END)

    # ★ Checkpointer 在此处挂载，不能晚接入
    async with aiosqlite.connect(db_path) as conn:
        checkpointer = AsyncSqliteSaver(conn)
        graph = builder.compile(checkpointer=checkpointer)
        return graph

def check_pass1_done(state: ExtractionState) -> str:
    if state["current_batch_index"] >= state["total_segments"]:
        return "done"
    return "continue"

def check_pass2_done(state: ExtractionState) -> str:
    # Pass 2 复用 current_batch_index，需要重置计数
    # 实现时注意 Pass 2 有独立的计数器 pass2_batch_index
    if state.get("pass2_batch_index", 0) >= state["total_segments"]:
        return "done"
    return "continue"
```

### 4.2 Checkpointer 使用模式

```python
# memory/checkpointer.py
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite

# ⚠️ AsyncSqliteSaver 需要在 async context manager 内使用
# 推荐封装为全局单例

_checkpointer: AsyncSqliteSaver | None = None
_conn: aiosqlite.Connection | None = None

async def get_checkpointer(db_path: str = "workspace/blueprints.db") -> AsyncSqliteSaver:
    global _checkpointer, _conn
    if _checkpointer is None:
        _conn = await aiosqlite.connect(db_path)
        _checkpointer = AsyncSqliteSaver(_conn)
        await _checkpointer.setup()  # 建表（幂等）
    return _checkpointer

# 调用时携带 thread_id 实现断点续传
async def run_extraction(graph, state: dict, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(state, config=config)
    return result

# 恢复时用相同 thread_id
async def resume_extraction(graph, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    result = await graph.ainvoke(None, config=config)  # None = 从断点恢复
    return result
```

### 4.3 Interrupt 机制（LangGraph 1.1.2）

```python
# graph/creation/nodes/human_review_node.py
from langgraph.types import interrupt, Command
from schemas.state import CreationState

async def human_review_synopsis_node(state: CreationState) -> Command:
    """
    LangGraph 1.1.2 的 interrupt 机制：
    1. 调用 interrupt() 暂停图执行，传入要展示给用户的数据
    2. 用户通过 graph.invoke(Command(resume=...)) 恢复执行
    3. interrupt() 的返回值就是用户传入的数据
    """
    synopsis = state["synopsis"]

    # 暂停，等待用户输入
    user_input = interrupt({
        "type": "synopsis_review",
        "content": synopsis,
        "prompt": "请确认宏观构思：\n[1] 满意，继续\n[2] 修改后重新生成"
    })

    # user_input 是用户 resume 时传入的值
    if user_input.get("action") == "approve":
        return Command(
            update={"synopsis_approved": True},
            goto="path_gen"
        )
    else:
        # 用户要求修改，更新 synopsis 后重新生成
        return Command(
            update={
                "synopsis_approved": False,
                "synopsis": {**synopsis, "user_feedback": user_input.get("feedback", "")}
            },
            goto="synopsis"
        )

# CLI 侧的调用方式
async def run_with_interrupt(graph, state, thread_id):
    config = {"configurable": {"thread_id": thread_id}}

    # 第一次运行，会在 interrupt 处暂停
    result = await graph.ainvoke(state, config=config)

    # 检查是否在等待 interrupt
    if "__interrupt__" in result:
        interrupt_data = result["__interrupt__"][0].value
        # 展示给用户
        user_response = await get_user_input(interrupt_data)
        # 恢复执行
        result = await graph.ainvoke(
            Command(resume=user_response),
            config=config
        )

    return result
```

### 4.4 State 中 Pydantic 对象的序列化

```python
# ⚠️ 重要：LangGraph Checkpointer 要求 State 中的所有值必须可 JSON 序列化
# Pydantic 对象不能直接放入 State，必须转为 dict

# 正确做法
blueprint = NovelBlueprint(...)
state["blueprint"] = blueprint.model_dump()  # 存 dict

# 读取时
blueprint = NovelBlueprint.model_validate(state["blueprint"])  # 从 dict 恢复

# EntityRegistry 同理
registry = EntityRegistry(...)
state["entity_registry"] = registry.model_dump()
```

---

## 五、工作流 A：骨骼提取流

### 5.1 图结构

```
START
  ↓
[source_node]          来源判断 + 文本获取
  ↓
[segmenter_node]       中观节点切分（含输出状态验证）
  ↓
[pass1a]  ← ──────────────────────────────────────────┐
  ↓                                                    │
[pass1b]                                               │ current_batch_index += 1
  ↓                                                    │
[check_pass1_done] ──── 未完成 ──────────────────────┘
  ↓ 全部完成
[truth_node]
  ↓
[pass2]  ← ──────────────────────────────────────────┐
  ↓                                                   │ pass2_batch_index += 1
[check_pass2_done] ──── 未完成 ───────────────────────┘
  ↓ 全部完成
[pass3_node]
  ↓
[blueprint_save_node]
  ↓
END
```

### 5.2 segmenter_node 详述

```python
# 切分策略（三步）

# Step 1：以章节标题做初步切分
# Step 2：字数粗筛（合并 <2000字，拆分 >20000字）
# Step 3：输出状态验证（★ 关键，防止切断逻辑链）

# Step 3 向 LLM 提问（轻量调用，只需 ~100 token 输出）：
SEGMENTER_BOUNDARY_PROMPT = """
片段结尾内容：
{segment_end_200_chars}

问题：这个片段结尾时，主角的身份/处境/关系与片段开头相比，
是否发生了本质性的改变（如：入门、离开、建立关系、完成任务、遭受打击等）？

只回答 JSON：{"changed": true/false, "reason": "一句话说明"}
"""

# 若 changed=false → 合并下一章，继续验证
# 若 changed=true  → 确认为节点边界

# 输出格式
# segments = [
#   {
#     "index": 0,
#     "title": "土匪师爷",
#     "text": "...",
#     "char_count": 8500,
#     "source_chapters": ["第1章 土匪师爷（上）", "第2章 土匪师爷（下）"]
#   },
#   ...
# ]
```

---

## 六、工作流 B：小说创作流

### 6.1 图结构

```
START
  ↓
[blueprint_load]
  ↓
[synopsis]
  ↓
[human_review_1]  ←─ interrupt ─── 用户确认宏观构思
  ├── 修改 → [synopsis]
  └── 通过 ↓
[path_gen]
  ↓
[human_review_2]  ←─ interrupt ─── 用户确认路径
  ├── 修改 → [path_gen]
  └── 通过 ↓
[expand1] ← ──────────────────────────────────────────────────────┐
  ↓                                                                │
[expand2]                                                          │
  ↓                                                                │
[write]   ←── 一致性违规时重写 ──┐                                 │
  ↓                              │                                 │
[bible_update]                   │                                 │
  ↓                              │                                 │
[consistency] ── 违规 ───────────┘                                 │
  ↓ 通过                                                           │
[update_weight]                                                    │
  ↓                                                                │
[check_done] ── 未完成 ─────────────────────────────────────────┘
  ├── 长篇续写 → [path_gen]
  └── 全部完成 → END
```

### 6.2 骨骼权重注入规则

```
blueprint_weight 的提示词表达：
  0.7-1.0 → "严格参考以下骨骼结构，尽量保持与范文相同的逻辑走向"
  0.4-0.7 → "适当参考以下骨骼结构，可以有所变化但保持整体节奏"
  0.0-0.4 → "以下骨骼仅供参考，创作优先服从故事圣经的逻辑"
```

---

## 七、完整 Prompt 文本

> **这是本文档最核心的部分。所有 Prompt 必须严格按照以下文本实现，不得自行改写。**

### 7.1 Pass 1a：叙事提取（SYSTEM PROMPT）

```python
# prompts/extraction/pass1a.py

PASS1A_SYSTEM = """你是一个专业的网络小说骨骼提取助手。你的任务是从小说文本中提取**事件路径链**，
用于构建可供其他作者套用的故事结构骨骼。

## 你的核心任务

从给定的小说片段中，提取这个故事节点的完整事件路径——具体到可以被另一个作者套用的情节动作。

## 最重要的原则：提取事件，不是归纳主题

你必须区分以下两种输出，只输出第一种：

❌ 错误（主题归纳，无法套用）：
  "施压类型：间接施压型。外部力量通过场景向主角施压，主角陷入两难困境。"

✅ 正确（事件路径，可以套用）：
  "3. 掌握权力的人以'礼节/规矩'为名，在公开场合制造情境 → 弱势方被迫表态"
  "4. 弱势方手里有一个高于对方的授权（师命），但这个授权无法明说 → 无法正面对抗"

判断标准：另一个作者看到你的输出，能否把人物和场景全部替换，
沿着相同的因果路径生长出完全不同的故事？如果能，你写的是事件路径（正确）。
如果不能，你写的是主题归纳（错误，重写）。

## 实体识别规则

### 标准名选取（优先级从高到低）
1. 其他角色稳定使用的称呼或绰号 → standard_name（如"老核桃"）
2. 有历史来源的称号 → aliases（如"土匪师爷"）
3. 关系称谓（师父/大哥/娘子）→ 进 related_entities，绝不做 standard_name
4. 叙述者口语化称呼（老头儿/那家伙）→ 进 role_tags，不进 aliases

### 第一人称叙述验证（★ 必须执行）
对文中每个具名人物 X：
- 如果文中存在"我看见X"/"我跟着X"/"我问X"这类句子 → X 是被叙述者观察的人，不是叙述者本人
- 不要把第一章最早出现的具名人物自动识别为叙述者/主角

## 输出要求

只返回 JSON 对象，不加任何前言、解释或 markdown 代码块。
直接从 { 开始，到 } 结束。

JSON 结构参考 USER PROMPT 中的 output_schema。"""


PASS1A_USER_TEMPLATE = """## 当前节点信息

节点序号：{batch_index}
节点文本（共 {char_count} 字）：
{text}

## 前批次延续上下文
{continuation_context}

## 当前实体注册表（用于对齐，避免重复创建）
{entity_registry_summary}

## 输出 Schema

返回以下 JSON 结构：
{output_schema_json}

## 再次提醒

event_path_chain 中的每一条必须是具体事件，格式：
"N. {谁} {做了什么/发生了什么} → {直接结果}"

不能出现类型标签（"施压型"/"破局型"/"汇聚"）。
类型归纳是 Pass 1b 的工作，不是你的工作。"""
```

### 7.2 Pass 1b：结构标注（SYSTEM PROMPT）

```python
# prompts/extraction/pass1b.py

PASS1B_SYSTEM = """你是一个逻辑链分类专家。你的任务是根据已有的事件路径链，
归纳该故事节点使用的施压链类型和破局链类型。

## 可用的逻辑链类型

施压链（6种）：
- 间接施压型：第三方/结构/规矩作为施压载体，施压者不直接出面
- 多源汇聚型：多个独立施压源同时作用，主角无法一次性应对
- 资源争夺型：稀缺资源的争夺导致对立
- 蝴蝶效应型：早期小事件演变为大压力
- 自我实现困局型：主角的应对行为本身加剧困境
- 信任背叛链型：最信任的人成为致命威胁

破局链（6种）：
- 信息差破局型：掌握对方不知道的信息完成逆转（需标注方向：protagonist=主角掌握优势，antagonist=对手掌握优势）
- 以弱胜强型：在明显劣势下完成逆转
- 揭露反转型：已有信息的重新解读改变局势
- 借力打力型：利用对方的力量/意图反将一军
- 知识技能破局型：专业知识或技能成为胜负手
- 纯推理型：纯逻辑推演找到出路

## 规则

1. 类型标注必须基于 Pass 1a 的事件路径，不能凭空归纳
2. event_indices 必须标注该类型对应的是哪几条事件（从1开始编号）
3. 一个节点可以同时有施压链和破局链（分别标注）
4. 只返回 JSON，不加任何前言"""


PASS1B_USER_TEMPLATE = """## Pass 1a 的提取结果

节点名称：{node_name}

事件路径链：
{event_path_chain_text}

施压源分解：
{pressure_sources_text}

## 请归纳逻辑链类型

返回 JSON：
{{
  "pressure_chains": [
    {{
      "chain_type": "类型名",
      "direction": "pressure",
      "info_asymmetry": "none|protagonist|antagonist",
      "description": "本节点中的具体表现（1-2句）",
      "event_indices": [对应的事件编号]
    }}
  ],
  "resolution_chains": [
    {{
      "chain_type": "类型名",
      "direction": "resolution",
      "info_asymmetry": "none|protagonist|antagonist",
      "description": "本节点中的具体表现",
      "event_indices": [对应的事件编号]
    }}
  ]
}}"""
```

### 7.3 segmenter_node 边界判断 Prompt

```python
# prompts/extraction/segmenter.py

SEGMENTER_BOUNDARY_SYSTEM = "你是一个故事结构分析助手。只返回 JSON，不加任何解释。"

SEGMENTER_BOUNDARY_USER = """以下是一个小说章节的最后200字：

{segment_tail}

问题：这个章节结束时，主角的身份/处境/核心关系，与章节开头相比，
是否发生了本质性的改变？

本质性改变的例子：完成入门仪式、正式建立师徒关系、离开原有环境、遭受重大打击、
获得关键信息导致认知改变、完成一次完整的对抗并有明确胜负。

不算本质性改变：仍在进行中的对话、仍在旅途中、冲突还未解决。

返回：{{"changed": true或false, "reason": "一句话"}}"""
```

### 7.4 truth_node Prompt

```python
# prompts/extraction/truth.py

TRUTH_SYSTEM = """你是一个悬疑小说分析专家。
你的任务是从已提取的故事节点摘要中，归纳出全书的核心真相清单。

真相清单用于 Pass 2 的逆向扫描——我们需要知道"哪些事情是伏笔"，
才能找到前文中对应的暗示。

只返回 JSON，不加任何前言或解释。"""

TRUTH_USER_TEMPLATE = """## 所有批次的 Pass 1a 摘要

{all_batch_summaries}

## 任务

生成结构化真相清单。真相清单记录：
- 读者最后才知道的关键信息（隐藏的身份、动机、事件真相）
- 这些信息在前文中应该以什么形式出现过（暗示方向）

注意：如果这是片段文本（incomplete=true），真相清单也标注 incomplete=true，
但仍然尽力推断可能的真相。

返回 JSON：
{{
  "incomplete": {is_fragment},
  "key_truths": [
    {{
      "truth_id": "T001",
      "who": "关键实体标准名",
      "what": "这个真相的内容（做了什么/是什么）",
      "motive": "动机",
      "method": "手法",
      "when_revealed": 节点序号（0表示全书末尾或未知）,
      "hints_to_find": "前文应该找什么样的暗示（具体方向）"
    }}
  ]
}}"""
```

### 7.5 pass2_node Prompt

```python
# prompts/extraction/pass2.py

PASS2_SYSTEM = """你是一个伏笔分析专家。
你已经知道了这部小说的核心真相（由真相清单提供）。
你的任务是：带着这份知识，重新阅读每个批次的文本，
找出那些"表面上看起来无关紧要，但回头看是暗示"的内容。

只返回 JSON，不加任何前言。"""

PASS2_USER_TEMPLATE = """## 已知真相清单

{truth_manifest_text}

## 当前批次文本（节点 {batch_index}）

{text}

## 任务

找出本批次文本中，能作为上述任何一条真相的早期暗示的内容。

一个好的伏笔特征：
- 表面含义：读者第一次看到时觉得是普通描写或无关紧要的细节
- 真实含义：结合真相清单，它其实在暗示某条真相
- 误导方向：它让读者的注意力偏向了错误的地方

如果这是片段文本，所有伏笔标注 is_inferred: true。

返回 JSON：
{{
  "foreshadows_found": [
    {{
      "foreshadow_id": "F{batch_index:03d}_{序号:02d}",
      "surface_meaning": "读者当时的理解",
      "true_meaning": "结合真相后的真实含义",
      "truth_node_ref": "对应的 truth_id",
      "misdirect_direction": "这条伏笔让读者注意到了什么错误方向",
      "planted_at_node": {batch_index},
      "is_inferred": {is_fragment}
    }}
  ],
  "foreshadows_collected": [
    {{
      "foreshadow_id": "已有伏笔ID",
      "collected_at_node": {batch_index},
      "collection_method": "如何回收（揭示/间接提及/正面解答）"
    }}
  ]
}}

如果没有找到任何伏笔，返回：{{"foreshadows_found": [], "foreshadows_collected": []}}"""
```

### 7.6 pass3_node Prompt

```python
# prompts/extraction/pass3.py

PASS3_SYSTEM = """你是一个小说骨骼归纳专家。
你已经拿到了一部小说所有批次的 Pass 1a/1b 提取结果和完整伏笔地图。
你的任务是把这些分散的信息合并成一份完整的骨骼档案，
提炼出这部小说在结构、逻辑、风格上的可复用规律。

提炼的目标：另一个作者拿到这份骨骼，能以不同的人物和场景，
写出具有相同结构骨感和情绪节奏的作品。

只返回 JSON，不加任何前言。"""

PASS3_USER_TEMPLATE = """## 所有批次摘要（Pass 1a/1b 结果）

{all_batch_summaries_condensed}

## 伏笔地图

{foreshadow_map_summary}

## 实体注册表摘要

{entity_registry_summary}

## 任务

生成完整的三层骨骼档案。

第一层（结构模板）：宏观节奏、卷章结构、故事线分布
第二层（逻辑规律）：爽点节奏、冲突升级方式、情绪曲线、转折手法、写作风格
第三层（逻辑链图谱）：全书逻辑链类型序列、节点连接映射

同时归纳：world_rule_type / conflict_scale / protagonist_power / genre_tags

返回以下 JSON 结构（严格按此格式）：
{pass3_output_schema_json}"""
```

### 7.7 synopsis_node Prompt

```python
# prompts/creation/synopsis.py

SYNOPSIS_SYSTEM = """你是一个专业的商业网文策划师。
你将根据用户的题材需求和提供的骨骼参考，生成一个简洁的宏观构思。
宏观构思必须在 300 字以内，要有商业吸引力，不要写成学术摘要。
只返回 JSON，不加任何前言。"""

SYNOPSIS_USER_TEMPLATE = """## 用户需求

题材：{genre_request}

## 骨骼参考（{weight_description}）

世界规则类型：{world_rule_type}
冲突规模：{conflict_scale}
主角力量定位：{protagonist_power}

宏观节奏参考：{macro_pacing}
情绪曲线参考：{emotional_curve}
爽点节奏参考：{payoff_rhythm}

{user_feedback_section}

## 任务

生成宏观构思，字数控制在 300 字以内。

返回 JSON：
{{
  "title": "标题（有吸引力，2-8字）",
  "world": "世界观（50字以内）",
  "protagonist": "主角设定（50字以内，含力量定位）",
  "core_conflict": "核心冲突（100字以内）",
  "direction": "大致走向（100字以内）"
}}"""
```

### 7.8 path_gen_node Prompt

```python
# prompts/creation/path_gen.py

PATH_GEN_SYSTEM = """你是一个商业网文故事路径规划师。
你的任务是根据宏观构思和骨骼参考，规划一批故事节点（中观节点）。
每个节点对应约 1000-2000 字的正文，是一个有完整逻辑链的故事单元。
只返回 JSON，不加任何前言。"""

PATH_GEN_USER_TEMPLATE = """## 宏观构思

{synopsis_text}

## 骨骼逻辑链类型序列参考（{weight_description}）

{chain_type_sequence}

## 节点连接规律参考

{node_connections_summary}

## 当前故事状态

已完成节点数：{completed_nodes}
当前故事圣经摘要：{bible_summary}
是否处于扭转后状态：{post_pivot}

{post_pivot_instruction}

## 任务

规划接下来 {node_count} 个中观节点（8-12个）。
节点逻辑链类型尽量参考骨骼的类型序列，但要符合当前故事的实际状态。

返回 JSON：
{{
  "nodes": [
    {{
      "node_name": "节点标题",
      "pressure_chain_type": "施压链类型",
      "resolution_chain_type": "破局链类型",
      "key_characters": ["人物名"],
      "input_state_hint": "进入节点时的状态提示",
      "output_state_hint": "离开节点时的状态提示",
      "one_liner": "一句话描述（用于用户确认展示）"
    }}
  ]
}}"""

# 扭转后模式的附加说明
POST_PIVOT_INSTRUCTION = """
⚠️ 当前处于扭转后状态。
扭转记录：{pivot_records}
请只参考骨骼的逻辑链类型序列（不参考具体内容），
以故事圣经中的当前状态为准继续规划。"""
```

### 7.9 expand1_node Prompt（3W1H 分析）

```python
# prompts/creation/expand1.py

EXPAND1_SYSTEM = """你是一个故事结构分析师。
你的任务是对一个故事节点做 3W1H 结构化分析，
为后续的场景设计和正文写作做准备。
不需要写正文，只需要做结构分析。
只返回 JSON，不加任何前言。"""

EXPAND1_USER_TEMPLATE = """## 当前节点

节点名称：{node_name}
施压链类型：{pressure_chain_type}
破局链类型：{resolution_chain_type}
输入状态：{input_state_hint}
输出状态：{output_state_hint}

## 故事圣经（人物当前状态）

{bible_summary}

## 上一节点输出状态

{prev_output_state}

## 3W1H 分析

返回 JSON：
{{
  "who": {{
    "characters": [
      {{
        "name": "人物名",
        "current_state": "当前状态",
        "motivation": "在本节点的动机",
        "role": "protagonist|antagonist|bystander"
      }}
    ]
  }},
  "what": {{
    "core_event": "本节点的核心事件（一句话）",
    "event_sequence": ["事件1", "事件2", "事件3"],
    "cause_chain": "因果链说明"
  }},
  "where_when": {{
    "scene": "场景选择",
    "scene_reason": "为什么选这个场景",
    "timing": "时机",
    "timing_reason": "为什么选这个时机"
  }},
  "how": {{
    "pressure_mechanism": "施压链如何运作",
    "resolution_trigger": "破局链如何触发",
    "protagonist_constraint": "主角面临的制约"
  }}
}}"""
```

### 7.10 expand2_node Prompt（场景设计）

```python
# prompts/creation/expand2.py

EXPAND2_SYSTEM = """你是一个场景设计师。
根据 3W1H 分析结果和骨骼的冲突升级规律，
设计具体的场景序列，并规划伏笔的植入和回收。
只返回 JSON，不加任何前言。"""

EXPAND2_USER_TEMPLATE = """## 3W1H 分析结果

{expand1_result}

## 骨骼参考（{weight_description}）

冲突升级方式：{conflict_escalation}
转折手法：{turning_point_style}

## 伏笔任务

需要在本节点植入的伏笔：
{foreshadows_to_plant}

需要在本节点回收的伏笔：
{foreshadows_to_collect}

## 任务

设计 3-5 个场景序列，规划伏笔处理方式。

返回 JSON：
{{
  "scenes": [
    {{
      "scene_name": "场景名",
      "opening_state": "场景开场状态",
      "core_conflict": "场景核心冲突",
      "closing_state": "场景结束状态",
      "mood": "场景情绪基调",
      "key_dialogue_hint": "关键对话方向提示（可选）"
    }}
  ],
  "foreshadow_plan": [
    {{
      "foreshadow_id": "新伏笔ID或待回收ID",
      "action": "plant|collect",
      "surface_expression": "在正文中的表面表达方式",
      "target_scene": "植入/回收发生在哪个场景"
    }}
  ],
  "emotional_arc": "本节点的情绪弧线（紧张程度变化）"
}}"""
```

### 7.11 write_node Prompt

```python
# prompts/creation/write.py

WRITE_SYSTEM = """你是一个专业的商业网文写手。
根据场景设计方案写作正文。
写作要求：
- 语言流畅，符合中文网络小说阅读习惯
- 对话要有个性，不同人物说话风格要区分
- 场景描写要有画面感，不要堆砌形容词
- 伏笔要织入得自然，不能太明显
- 目标字数：800-2000字

只返回正文，不加任何 JSON 包装或解释。"""

WRITE_USER_TEMPLATE = """## 写作参考

节点名称：{node_name}

场景设计方案：
{expand2_scenes}

## 风格参考（{weight_description}）

写作风格：{writing_style}
写作技巧：{writing_skills}

## 伏笔植入要求

{foreshadow_plant_instructions}

## 一致性检查发现的违规（重写时）

{violations_if_rewrite}

## 人物当前状态（必须严格遵守）

{character_states}

## 开始写作

直接输出正文，不加标题，不加任何说明。字数范围：800-2000字。"""
```

### 7.12 bible_update_node Prompt

```python
# prompts/creation/bible_update.py

BIBLE_UPDATE_SYSTEM = """你是一个故事档案管理员。
从刚写完的正文中提取关键信息，更新故事圣经。
只返回 JSON，不加任何前言。"""

BIBLE_UPDATE_USER_TEMPLATE = """## 刚完成的正文

{current_draft}

## 当前故事圣经

{current_bible}

## 任务

从正文中提取并更新故事圣经。

返回 JSON（只返回有变化的字段）：
{{
  "characters": {{
    "人物名": {{
      "status": "当前状态变化",
      "location": "当前位置（如有变化）",
      "relationship_changes": "关系变化（如有）",
      "knowledge_gains": "获得了什么新信息（如有）"
    }}
  }},
  "events": [
    "本节点发生的关键事件（一句话描述）"
  ],
  "planted_foreshadows": [
    {{
      "foreshadow_id": "F编号",
      "surface_expression": "正文中的具体文字（5-20字）",
      "planned_collection_node": 计划回收的节点序号
    }}
  ],
  "collected_foreshadows": ["已回收的伏笔ID"],
  "world_state_changes": "世界状态的变化（如有）"
}}"""
```

### 7.13 consistency_node Prompt

```python
# prompts/creation/consistency.py

CONSISTENCY_SYSTEM = """你是一个故事一致性审核员。
检查刚写完的正文是否与故事圣经、骨骼结构序列和扭转记录保持一致。
只返回 JSON，不加任何前言。"""

CONSISTENCY_USER_TEMPLATE = """## 刚写完的正文

{current_draft}

## 依据1：故事圣经（人物状态/动机/已发生事件）

{bible_summary}

## 依据2：当前节点应有的骨骼逻辑链类型

施压链类型：{expected_pressure_type}
破局链类型：{expected_resolution_type}
骨骼权重：{blueprint_weight}（{weight_description}）

## 依据3：扭转记录

{pivot_records_if_any}

## 检查项

1. 人物动机是否与故事圣经自洽（前后行为是否有逻辑）
2. 新增行为是否能从上一节点输出状态自然推导
3. 已埋伏笔是否有对应回收计划或已回收
4. 逻辑链类型是否与骨骼期望匹配（按权重决定检查严格度：权重高则严格，权重低则宽松）

## 扭转检测

如果正文的逻辑走向与骨骼期望不符，但有充分的人物/剧情内部逻辑支撑，
这不是违规，而是一次合理扭转，需要标记。

返回 JSON：
{{
  "passed": true或false,
  "violations": ["具体违规描述"],
  "suggestions": ["如何修正"],
  "is_pivot": false,
  "pivot_reason": "如果 is_pivot=true，说明扭转的内部逻辑支撑"
}}"""
```

---

## 八、Phase 0 验证脚本（完整可运行代码）

```python
# scripts/phase0_test.py
"""
Phase 0 验证脚本：测试 Pass 1a Prompt 的输出质量
运行：uv run python scripts/phase0_test.py --input test_texts/sample.txt

完成标准：
  ✓ event_path_chain 每条是具体事件，不是类型标签
  ✓ pressure_sources 包含具体手段，不是类型名
  ✓ 第一人称叙述者识别正确
  ✓ 标准名选取正确（关系称谓不做标准名）
  ✓ 连续测试 3 段不同文本，输出稳定
"""

import asyncio
import json
import argparse
from pathlib import Path
import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from anthropic import AsyncAnthropic
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from prompts.extraction.pass1a import PASS1A_SYSTEM, PASS1A_USER_TEMPLATE
from schemas.blueprint import PASS1A_OUTPUT_SCHEMA
import json as json_module

console = Console()
client = AsyncAnthropic()


def load_text(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def split_into_test_segments(text: str, segment_size: int = 5000) -> list[str]:
    """简单按字数切分，仅用于 Phase 0 测试，不用 segmenter_node 的完整逻辑"""
    segments = []
    for i in range(0, len(text), segment_size):
        seg = text[i:i + segment_size]
        if len(seg) > 1000:  # 过滤过短片段
            segments.append(seg)
    return segments[:3]  # 最多测试 3 段


async def test_pass1a(text: str, segment_index: int) -> dict:
    """对单个片段运行 Pass 1a，返回结果和质量评估"""

    user_prompt = PASS1A_USER_TEMPLATE.format(
        batch_index=segment_index,
        char_count=len(text),
        text=text,
        continuation_context="无（首批次）" if segment_index == 0 else "见前批次输出",
        entity_registry_summary="空（首批次）",
        output_schema_json=json_module.dumps(PASS1A_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)
    )

    response = await client.messages.create(
        model="claude-opus-4-5",  # Phase 0 用最强模型验证 Prompt
        max_tokens=4000,
        system=PASS1A_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw_output = response.content[0].text.strip()

    # 解析 JSON
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"JSON 解析失败: {e}",
            "raw_output": raw_output[:500]
        }

    # 质量检查
    issues = []
    warnings = []

    # 检查1：event_path_chain 是否存在且有内容
    epc = parsed.get("event_path_chain", [])
    if not epc:
        issues.append("❌ event_path_chain 为空")
    elif len(epc) < 3:
        warnings.append(f"⚠️  event_path_chain 只有 {len(epc)} 条（期望 4-8 条）")

    # 检查2：event_path_chain 是否包含类型标签（最关键的检查）
    type_keywords = ["施压型", "破局型", "汇聚型", "背叛型", "逻辑链", "施压链", "破局链",
                     "多源", "间接施压", "信息差", "以弱胜强"]
    for i, event in enumerate(epc):
        for kw in type_keywords:
            if kw in event:
                issues.append(f"❌ event_path_chain[{i}] 包含类型标签关键词 '{kw}'：{event[:80]}")
                break

    # 检查3：event_path_chain 格式是否正确（含"→"）
    for i, event in enumerate(epc):
        if "→" not in event and "->" not in event:
            warnings.append(f"⚠️  event_path_chain[{i}] 缺少因果箭头（→）：{event[:60]}")

    # 检查4：pressure_sources 是否有具体手段
    ps = parsed.get("pressure_sources", [])
    for i, src in enumerate(ps):
        if len(src.get("method", "")) < 10:
            warnings.append(f"⚠️  pressure_sources[{i}].method 过短，可能是类型标签而非具体描述")

    # 检查5：标准名不应是关系称谓
    relation_keywords = ["师父", "师傅", "大哥", "大姐", "老大", "娘子", "夫人", "先生", "老师"]
    for entity in parsed.get("new_entities", []):
        sn = entity.get("standard_name", "")
        for rk in relation_keywords:
            if sn == rk:
                issues.append(f"❌ new_entities 中 standard_name='{sn}' 是关系称谓，不应做标准名")

    return {
        "success": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "event_path_chain": epc,
        "pressure_sources": ps,
        "node_name": parsed.get("node_name", ""),
        "new_entities": parsed.get("new_entities", []),
        "raw_output": raw_output
    }


def print_result(result: dict, segment_index: int):
    """打印测试结果"""
    if result.get("success") is False and "error" in result:
        console.print(Panel(
            f"[red]JSON 解析失败[/red]\n{result['error']}\n\n原始输出：\n{result['raw_output']}",
            title=f"片段 {segment_index} - 失败",
            border_style="red"
        ))
        return

    issues = result.get("issues", [])
    warnings = result.get("warnings", [])
    success = result["success"]

    status = "[green]通过[/green]" if success else "[red]失败[/red]"
    console.print(f"\n[bold]片段 {segment_index}[/bold] - {status}")

    if result.get("node_name"):
        console.print(f"  节点名称：{result['node_name']}")

    console.print(f"\n  [cyan]事件路径链（{len(result.get('event_path_chain', []))} 条）：[/cyan]")
    for event in result.get("event_path_chain", []):
        console.print(f"    {event}")

    if result.get("new_entities"):
        console.print(f"\n  [cyan]识别到的实体：[/cyan]")
        for e in result.get("new_entities", []):
            console.print(f"    {e.get('standard_name')} ({e.get('entity_type')}) "
                          f"别名={e.get('aliases', [])}")

    if issues:
        console.print("\n  [red]问题：[/red]")
        for issue in issues:
            console.print(f"    {issue}")

    if warnings:
        console.print("\n  [yellow]警告：[/yellow]")
        for w in warnings:
            console.print(f"    {w}")


async def main():
    parser = argparse.ArgumentParser(description="Phase 0：Pass 1a Prompt 验证脚本")
    parser.add_argument("--input", required=True, help="测试文本文件路径（.txt）")
    parser.add_argument("--segments", type=int, default=3, help="测试片段数（默认3）")
    parser.add_argument("--segment-size", type=int, default=5000, help="每段字数（默认5000）")
    parser.add_argument("--save-output", help="保存完整 JSON 输出到文件")
    args = parser.parse_args()

    console.print(Panel(
        "[bold]DeepNovel Phase 0 验证脚本[/bold]\n"
        "测试 Pass 1a Prompt 的事件路径链提取质量",
        border_style="blue"
    ))

    # 加载文本
    text = load_text(args.input)
    console.print(f"\n已加载文本：{args.input}（{len(text)} 字）")

    # 切分片段
    segments = split_into_test_segments(text, args.segment_size)
    segments = segments[:args.segments]
    console.print(f"切分为 {len(segments)} 个测试片段（每段约 {args.segment_size} 字）\n")

    # 运行测试
    all_results = []
    for i, seg in enumerate(segments):
        console.print(f"[bold]测试片段 {i}...[/bold]")
        result = await test_pass1a(seg, i)
        all_results.append(result)
        print_result(result, i)

    # 总结
    passed = sum(1 for r in all_results if r.get("success"))
    console.print(f"\n{'='*50}")
    console.print(f"[bold]总结：{passed}/{len(all_results)} 片段通过[/bold]")

    if passed == len(all_results):
        console.print("[green]✓ Phase 0 通过！可以进入 Phase 1 开发。[/green]")
        console.print("将验证通过的最终 Prompt 保存到 prompts/extraction/pass1a.py")
    else:
        console.print("[red]✗ 仍有问题，需要继续调整 Prompt。[/red]")
        console.print("检查失败片段的具体问题，修改 PASS1A_SYSTEM 或 PASS1A_USER_TEMPLATE 后重新测试。")

    # 保存输出
    if args.save_output:
        with open(args.save_output, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
        console.print(f"\n完整输出已保存到：{args.save_output}")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 九、数据库设计（SQLite）

### 9.1 schema.sql

```sql
-- 骨骼档案主表
CREATE TABLE IF NOT EXISTS blueprints (
    blueprint_id      TEXT PRIMARY KEY,
    source_title      TEXT,
    genre_tags        TEXT,     -- JSON 数组
    source_type       TEXT,
    world_rule_type   TEXT,
    conflict_scale    TEXT,
    protagonist_power TEXT,
    layer1_json       TEXT,
    layer2_json       TEXT,
    layer3_json       TEXT,
    is_fragment       INTEGER DEFAULT 0,
    fragment_note     TEXT,
    created_at        TEXT DEFAULT (datetime('now'))
);

-- 实体注册表（按骨骼ID隔离）
CREATE TABLE IF NOT EXISTS entity_registry (
    entity_id         TEXT PRIMARY KEY,
    blueprint_id      TEXT,
    standard_name     TEXT,
    entity_type       TEXT,
    aliases           TEXT,    -- JSON 数组
    role_tags         TEXT,    -- JSON 数组
    first_batch       INTEGER,
    relations_json    TEXT,
    FOREIGN KEY (blueprint_id) REFERENCES blueprints(blueprint_id)
);

-- 小说项目表
CREATE TABLE IF NOT EXISTS novel_projects (
    project_id        TEXT PRIMARY KEY,
    blueprint_id      TEXT,
    genre_request     TEXT,
    synopsis_json     TEXT,
    path_json         TEXT,
    bible_json        TEXT,
    status            TEXT DEFAULT 'drafting',
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- 已完成章节表
CREATE TABLE IF NOT EXISTS chapters (
    chapter_id        TEXT PRIMARY KEY,
    project_id        TEXT,
    node_index        INTEGER,
    node_name         TEXT,
    content           TEXT,
    word_count        INTEGER,
    created_at        TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id)
);

-- 提取流断点续传表
CREATE TABLE IF NOT EXISTS extraction_progress (
    extraction_id     TEXT PRIMARY KEY,
    blueprint_id      TEXT,
    source_path       TEXT,
    pass_stage        TEXT DEFAULT 'pass1',  -- pass1|pass2|pass3|done
    current_batch     INTEGER DEFAULT 0,
    total_batches     INTEGER DEFAULT 0,
    accumulated_json  TEXT,
    updated_at        TEXT DEFAULT (datetime('now'))
);
```

### 9.2 Checkpointer 初始化

```python
# memory/db.py
import aiosqlite
from pathlib import Path

DB_PATH = Path("workspace/blueprints.db")

async def init_db():
    """初始化数据库，创建表结构"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = Path("memory/schema.sql").read_text(encoding="utf-8")
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(schema)
        await conn.commit()
```

---

## 十、工具层

### 10.1 工具签名速查

```
read_file(file_path: str) → {text, file_type, char_count, chapter_hints}
ocr_image(image_path: str) → {text, confidence, line_count}
scrape_novel_url(url: str) → {title, author, free_chapters, full_text, fetch_mode, ...}
save_blueprint(blueprint: dict) → {blueprint_id, success}
load_blueprint(blueprint_id: str) → NovelBlueprint dict
search_blueprints(genre: str, chain_types: list, world_rule: str) → list[摘要]
list_blueprints() → list[摘要]
```

### 10.2 scraper_tool 两层策略

**技术选型**：[Scrapling](https://github.com/D4Vinci/Scrapling)

Scrapling 同时解决了两个核心问题：反爬检测绕过，以及内容区的智能提取。后者尤为重要——不同小说平台的页面结构各不相同，硬编码 CSS 选择器无法跨平台复用，Scrapling 内置的 AI 辅助提取（`auto_match` 和语义 `find()`）能在不预知页面结构的情况下自动定位正文区域。

**爬取策略：两层**

```
第一层：Scrapling Fetcher（静态页面 + 轻度反爬）
  适用：大多数小说平台的目录页和章节页
  速度快，资源消耗低

第二层：Scrapling StealthyFetcher（JS渲染 + 强反爬）
  触发条件：第一层返回空内容 / 触发登录墙 / 内容由前端JS渲染
  模拟完整浏览器环境，绕过主流反爬策略

降级：返回 partial 状态
  两层均失败 → 返回已获取的部分内容
  提供章节 URL 列表，提示用户手动下载后上传 txt
```

**工具签名**：

```
tool: scrape_novel_url
输入：url: str        # 支持目录页 / 阅读页 / 小说首页，自动识别

输出：{
  title: str,               # 书名
  author: str,              # 作者
  intro: str,               # 简介（可能为空）
  cover_url: str,           # 封面 URL
  total_chapters: int,      # 总章数
  free_chapter_count: int,
  paid_chapter_count: int,

  free_chapters: [
    {
      index: int,
      name: str,
      content: str,         # 正文
      word_count: int
    }
  ],

  paid_chapters: [
    {
      index: int,
      name: str             # 只有标题，无正文
    }
  ],

  full_text: str,           # 所有免费章节正文拼接（含章节标题分隔符）
  fetch_mode: str,          # "fetcher" | "stealthy" | "partial"
  partial_reason: str       # fetch_mode="partial" 时说明具体原因
}
```

**完整处理流程**：

```
Step 1：URL 类型识别
  目录页（/chapter / /catalog / bid= 无 cid=）
  阅读页（/reader / bid= + cid=）
  小说首页（/book/ / /novel/）
  → 三种类型处理入口不同，但最终都拿到章节列表

Step 2：获取目录页 + 提取书籍元数据
  用 Scrapling Fetcher 请求目录页
  Scrapling AI 提取：书名、作者、简介、封面
  提取章节列表：章节名、章节 URL、免费/付费标记

  免费章节识别策略（按优先级）：
    a. DOM 标记（章节列表里的锁图标 / "VIP" / "付费" 文字）
       → Scrapling AI find() 识别付费标记元素
    b. 尝试访问章节页：能正常加载正文 = 免费，跳转登录 = 付费

Step 3：逐章获取免费正文
  对每个 free_chapter：
    先尝试 Fetcher（快速）
    正文区为空 → 切换 StealthyFetcher（JS渲染）
    Scrapling AI find() 定位正文容器
    提取纯文本，过滤导航栏/广告/评论

  限速配置（config.py）：
    SCRAPER_DELAY_MIN = 1.5 秒
    SCRAPER_DELAY_MAX = 3.0 秒
    SCRAPER_MAX_RETRIES = 3
    RETRY_BACKOFF = 指数退避

Step 4：拼接输出
  full_text = "

".join(f"## {ch.name}

{ch.content}" for ch in free_chapters)
```

**平台差异处理**：

不同平台的内容结构不同，Scrapling 的 AI 提取在大多数情况下能自动适配。已验证的平台特征作为参考（不作为硬编码依赖）：

```
番茄（fanqienovel.com）：
  章节正文由 JS 渲染
  需要 StealthyFetcher

起点（qidian.com）：
  目录页静态，正文页半动态
  Fetcher 可获取目录，正文需 StealthyFetcher

通用策略：
  遇到未知平台 → 两层均尝试 → AI 提取正文区
  提取失败 → partial 降级
```

**注意事项**：
- Scrapling StealthyFetcher 启动较慢（约 2-5 秒初始化），仅在第一层失败时启动
- 付费章节只记录标题不获取内容，不尝试绕过付费机制
- 爬取超过 50 章时，向用户显示进度（Rich 进度条）

---

## 十一、开发优先级（分阶段指令）

### Phase 0（概念验证期）—— 脱离 LangGraph，纯脚本验证

**目标：Pass 1a 的 Prompt 能稳定输出可用的事件路径链**

```
完成标准：
  连续测试 3 段不同题材的小说文本（每段 5000-8000 字）
  所有片段满足：
    ✓ event_path_chain 每条具体到情节动作，不含类型标签关键词
    ✓ pressure_sources 的 method 字段是具体手段描述，不是类型名
    ✓ 第一人称叙述者识别正确（验证脚本自动检查）
    ✓ 标准名选取正确（关系称谓不做标准名）
    ✓ JSON 格式稳定，无需人工修正

执行步骤：
  1. 准备 test_texts/ 目录，放入 2-3 部不同题材的小说片段
  2. uv run python scripts/phase0_test.py --input test_texts/sample1.txt
  3. 根据失败项调整 prompts/extraction/pass1a.py 中的 Prompt
  4. 重新测试直到全部通过
```

### Phase 1（基础骨架）—— 可运行的提取流最小版本

**目标：Pass 1a/1b 在 LangGraph 图中跑通，含 Checkpointer 和实体对齐**

```
完成标准：
  输入一部 10 万字以内的小说文本
  能完整跑完 Pass 1a → Pass 1b 的所有批次
  Checkpointer 正常：中断后 resume 从断点继续
  实体注册表跨批次对齐正确
  最终输出包含完整的 event_path_chain + 实体注册表

执行顺序：
  1. schemas/ 全部模型（blueprint.py, entity.py, state.py）
  2. memory/schema.sql + memory/db.py + memory/checkpointer.py
     ★ Checkpointer 在此处建立，后续所有图必须挂载
  3. tools/file_reader.py
  4. graph/extraction/graph.py（只含 Pass 1a/1b 循环的最小图）
     ★ 实体注册表对齐逻辑在此同期完成，不推迟
  5. 基础 CLI（uv run python -m deepnovel extract --source file --path xxx.txt）
```

### Phase 2（提取流完整）

```
执行顺序：
  6. Pass 2（pass2_node + truth_node）
  7. Pass 3（pass3_node + blueprint_save_node）
  8. tools/ocr_tool.py（RapidOCR + asyncio.to_thread 包装）
  9. tools/scraper_tool.py（Scrapling 两层策略）
  10. tools/blueprint_store.py

完成标准：
  端到端跑通：txt文件输入 → 完整 NovelBlueprint 存入 SQLite → 可用 ID 读取
```

### Phase 3a（创作流 · 宏观规划层）

```
执行顺序：
  11. blueprint_load_node（加载 + 兼容性检查）
  12. synopsis_node
  13. human_review_node（interrupt 机制，参考 4.3 节的实现）
  14. path_gen_node

完成标准：
  给定 blueprint_id，能生成宏观构思
  用户通过 interrupt 确认后，能生成 8-12 个节点的故事路径
  路径写入 State，准备进入创作循环
```

### Phase 3b（创作流 · 微观执行层）

```
执行顺序：
  15. expand1_node
  16. expand2_node
  17. write_node
  18. bible_update_node
  19. consistency_node（含扭转检测）
  20. update_weight_node

完成标准：
  对一个节点跑通完整循环：expand1 → expand2 → write → bible → consistency
  一致性检查能检出违规并触发重写
  扭转检测能识别合理扭转（不标记为违规）
```

### Phase 4（完善）

```
  21. 骨骼库匹配和多骨骼兼容性检查（见第十二章）
  22. 长篇续写循环（批次完成后自动生成下一批节点）
  23. Rich CLI 完整界面（进度条/骨骼预览/圣经查看）
  24. 多骨骼组合功能
```

---

## 十二、骨骼兼容性检查

三个维度的兼容性评分，用于 blueprint_load_node 中判断骨骼是否适合当前创作需求：

```python
# 兼容性评分矩阵（满分100）
COMPATIBILITY_RULES = {
    "world_rule_type": {  # 权重 40 分
        "realistic+realistic": 40,
        "supernatural+supernatural": 40,
        "mixed+mixed": 40,
        "mixed+realistic": 30,
        "mixed+supernatural": 30,
        "realistic+supernatural": 0,  # 不建议
    },
    "conflict_scale": {  # 权重 30 分
        # 同级满分，跨一级减半，跨两级不建议
        "personal+personal": 30,
        "organizational+organizational": 30,
        "world+world": 30,
        "personal+organizational": 15,
        "organizational+world": 15,
        "personal+world": 0,
    },
    "protagonist_power": {  # 权重 30 分
        "weak+weak": 30,
        "strong+strong": 30,
        "balanced+balanced": 30,
        # 跨类型需要在路径中设计力量转折点
        "weak+balanced": 20,
        "strong+balanced": 20,
        "weak+strong": 10,
    }
}

# 评分阈值
# ≥70：可直接组合
# 40-70：需要在路径生成时设计过渡节点
# <40：不建议，提示用户选择其他骨骼
```

---

## 十三、异常处理规范

```python
# 所有 LLM 调用的标准包装
async def call_llm_with_retry(
    system: str,
    user: str,
    max_retries: int = 3,
    model: str = "claude-sonnet-4-20250514"
) -> dict:
    """调用 LLM，失败自动重试，返回解析后的 JSON dict"""
    from anthropic import AsyncAnthropic
    import json, asyncio

    client = AsyncAnthropic()

    for attempt in range(max_retries):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=4000,
                system=system,
                messages=[{"role": "user", "content": user}]
            )
            raw = response.content[0].text.strip()
            # 清理可能的 markdown 包装
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except json.JSONDecodeError as e:
            if attempt == max_retries - 1:
                raise ValueError(f"LLM JSON 解析失败（{max_retries}次重试后）: {e}")
            await asyncio.sleep(2 ** attempt)  # 指数退避
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

---

*DeepNovel 骨骼系统 LangGraph 工程设计文档 v2.0*
*技术栈：LangGraph 1.1.2 · LangChain 1.2.18 · Python 3.11+ · uv 包管理*
