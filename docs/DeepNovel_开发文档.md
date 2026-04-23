# DeepNovel 开发文档
> 面向 Antigravity IDE / Gemini AI 的完整实现指南
> 从零开始搭建环境并完成全部代码

---

## 目录

1. 项目概述
2. 技术栈与版本要求
3. 环境搭建
4. 项目结构
5. 配置系统设计
6. 数据库设计（SQLite）
7. 数据模型设计（Pydantic）
8. LangGraph 状态机设计（核心）
9. 提示词模块设计
10. 智能体模块设计
11. 故事圣经系统设计
12. 写作风格系统设计
13. TUI 界面设计
14. 工作空间文件管理
15. 启动入口
16. 开发顺序与优先级

---

## 1. 项目概述

DeepNovel 是一个基于"故事路径驱动"的中长篇小说创作 AI 智能体。用户通过 TUI 界面与智能体**自然对话**，当用户明确表达创作意图并完成参数收集后，智能体自动进入严格的四阶段创作工作流。

### 1.1 两层架构设计（核心）

系统分为两层，两层之间通过用户意图判断进行切换：

```
┌─────────────────────────────────────────────────────┐
│              第一层：对话智能体（始终运行）              │
│                                                     │
│  用户可以：                                          │
│  · 自由聊天，询问创作相关问题                          │
│  · 描述故事想法，让智能体帮忙梳理                      │
│  · 以自然对话方式逐步提供创作参数                      │
│  · 管理已有项目（查看/继续/回滚）                      │
│  · 管理写作风格库（新增/覆盖/删除）                    │
│                                                     │
│  触发进入第二层的条件（满足其一）：                     │
│  · 用户明确说"开始吧"/"开始创作"/"可以了"等            │
│  · 智能体判断参数已足够，主动询问确认后用户同意          │
│                                                     │
└─────────────────┬───────────────────────────────────┘
                  │ 用户确认开始创作
                  ↓
┌─────────────────────────────────────────────────────┐
│           第二层：LangGraph 创作工作流                 │
│                                                     │
│  [路径生成] → [扩写×2] → [正文写作] → [继续/结束]    │
│  每个阶段用户逐一确认，支持随时修改和回滚              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 1.2 对话智能体的意图识别

对话智能体需要识别以下意图类型：

```
创作意图：
  "我想写一部小说" / "帮我创作" / "开始写" 等
  → 开始收集项目参数（自然对话方式，非表单）

项目管理意图：
  "继续上次的小说" / "我想看我的项目" 等
  → 展示已有项目列表，让用户选择

风格管理意图：
  "我想提取写作风格" / "帮我分析这个文件的风格" 等
  → 进入风格提取流程（见第12章）

回滚意图：
  "我想修改第3个节点" / "回到上一步" / "时光倒流" 等
  → 展示 checkpoint 列表，执行 Time Travel

闲聊/咨询意图：
  其他所有输入 → 正常对话回复
```

### 1.3 参数收集方式

参数通过**自然对话**逐步收集，不是一次性问完，不是弹出表单：

```
示例对话流程：

用户："我想写一部小说，主角是个被冤枉入狱的商人"
智能体："听起来很有意思！是复仇雪冤的故事吗？您打算走现实主义路线还是偏爽文的热血风格？"

用户："偏爽文，但不要太浮夸"
智能体："明白，节奏快但保持合理性。核心冲突是什么——是查清真相，还是同时要对付幕后黑手？"

用户："两个都有，而且我希望狱中那段戏份很精彩"
智能体："好的，狱中是重要的转折和成长阶段。我现在掌握的信息：
  · 题材：现代都市/商战
  · 主角：商人，被冤入狱，Avenger原型
  · 基调：Hot-blooded（偏爽但合理）
  · 节奏：Fast
  · 核心冲突：查清冤情+对抗幕后黑手
  还差主角的具体背景设定，您有想法吗？或者直接开始我来帮您生成？"

用户："就说他原本是个白手起家的科技公司老板吧，开始吧"
智能体："好！现在开始生成故事路径..."
  → 触发进入第二层 LangGraph 工作流
```

### 1.4 创作工作流（第二层）

```
[第一阶段] 生成故事路径（≤10条节点）→ 用户审阅确认
     ↓       ↑ 不满意则修改，直到满意
[第二阶段] 逐节点：第一轮扩写（3W1H结构）→ 用户确认
     ↓       ↑ 不满意则重写
[第三阶段] 逐节点：第二轮扩写（场景化大纲）→ 用户确认
     ↓       ↑ 不满意则重写
[第四阶段] 逐节点：正文写作（800~1200字）→ 用户确认
             ↓ 完成后：更新故事圣经（增量追加）
             ↓ 下一节点开始前：输出简洁故事索引
             ↓ 当前批次全部完成后：询问是否继续下一批
```

### 1.5 关键设计原则

- **对话优先**：系统始终以对话智能体作为入口，创作工作流是对话中的一个特殊状态
- **自然参数收集**：通过对话逐步收集参数，而非表单填写
- **绝不跳过阶段**：进入工作流后，四阶段严格顺序执行
- **逐节点推进**：每次只处理一个节点，等用户确认后才进行下一个
- **状态连贯**：通过 LangGraph Checkpoint 自动持久化
- **故事圣经**：两级结构（简洁索引 + 详细增量记录），防止长对话中信息丢失
- **时光倒流**：利用 LangGraph Time Travel，用户可以回滚到任意节点重新生成
- **风格系统**：支持从范文提取写作风格，创作时绑定并注入提示词

---

## 2. 技术栈与版本要求

### 必须使用最新版本，安装时不指定旧版本号

```
# 核心框架
langchain                   # 最新版
langchain-core              # 最新版
langchain-openai            # 最新版
langchain-community         # 最新版
langgraph                   # 最新版
langgraph-checkpoint-sqlite # 最新版（用于状态持久化）
langmem                     # 最新版（用于长期记忆/故事圣经）

# 数据层
pydantic                    # v2 最新版
pydantic-settings           # 最新版
sqlalchemy                  # v2 最新版
aiosqlite                   # 最新版

# 文件处理（风格提取用）
python-docx                 # 读取 .docx 文件
pypdf                       # 读取 .pdf 文件
rapidocr-onnxruntime        # OCR，从图片提取文字（中文识别效果好，体积小）

# TUI 界面
textual                     # 最新版

# 工具
python-dotenv               # 最新版
rich                        # 最新版（Textual 依赖，也可单独用于日志）
aiofiles                    # 异步文件读写
```

### Python 版本要求

```
Python >= 3.11
```

---

## 3. 环境搭建

### 3.1 创建项目目录

```bash
mkdir deepnovel
cd deepnovel
```

### 3.2 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# 或
.venv\Scripts\activate           # Windows
```

### 3.3 创建 pyproject.toml

```toml
[project]
name = "deepnovel"
version = "0.1.0"
description = "AI中长篇小说创作智能体"
requires-python = ">=3.11"
dependencies = [
    "langchain",
    "langchain-core",
    "langchain-openai",
    "langchain-community",
    "langgraph",
    "langgraph-checkpoint-sqlite",
    "langmem",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "sqlalchemy>=2.0",
    "aiosqlite",
    "python-docx",
    "pypdf",
    "rapidocr-onnxruntime",
    "textual",
    "python-dotenv",
    "rich",
    "aiofiles",
]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_backend"

[project.scripts]
deepnovel = "deepnovel.__main__:main"
```

### 3.4 安装依赖

```bash
pip install -e .
```

---

## 4. 项目结构

```
deepnovel/                          # 项目根目录
├── pyproject.toml
├── deepnovel.json                  # 用户配置文件（自动生成）
├── .env                            # 环境变量（可选）
├── README.md
│
├── deepnovel/                      # 主包
│   ├── __init__.py
│   ├── __main__.py                 # 启动入口
│   │
│   ├── config.py                   # 配置管理
│   │
│   ├── schemas/                    # Pydantic 数据模型
│   │   ├── __init__.py
│   │   ├── project.py              # 项目相关模型
│   │   ├── story.py                # 故事路径/节点模型
│   │   ├── bible.py                # 故事圣经模型
│   │   ├── style.py                # 写作风格模型
│   │   └── state.py                # LangGraph 状态模型
│   │
│   ├── chat/                       # 第一层：对话智能体
│   │   ├── __init__.py
│   │   ├── agent.py                # 对话智能体主逻辑（意图识别 + 参数收集）
│   │   ├── intent.py               # 意图识别器
│   │   └── param_collector.py      # 项目参数对话式收集器
│   │
│   ├── graph/                      # 第二层：LangGraph 创作工作流
│   │   ├── __init__.py
│   │   ├── builder.py              # 图构建器
│   │   ├── nodes/                  # 图节点函数
│   │   │   ├── __init__.py
│   │   │   ├── path_node.py        # 路径生成节点
│   │   │   ├── validate_node.py    # 验证节点
│   │   │   ├── expand_v1_node.py   # 第一轮扩写节点
│   │   │   ├── expand_v2_node.py   # 第二轮扩写节点
│   │   │   ├── write_node.py       # 正文写作节点
│   │   │   └── bible_node.py       # 故事圣经更新节点
│   │   └── edges.py                # 条件边/路由逻辑
│   │
│   ├── agents/                     # 智能体（LLM 调用封装）
│   │   ├── __init__.py
│   │   ├── path_generator.py       # 路径生成智能体
│   │   ├── validator.py            # 验证智能体
│   │   ├── expander.py             # 扩写智能体
│   │   ├── writer.py               # 写作智能体
│   │   ├── bible_manager.py        # 故事圣经管理智能体
│   │   └── style_extractor.py      # 写作风格提取智能体
│   │
│   ├── prompts/                    # 提示词模板
│   │   ├── __init__.py
│   │   ├── chat.py                 # 对话智能体提示词（意图识别 + 参数收集）
│   │   ├── path_generation.py
│   │   ├── validation.py
│   │   ├── expansion.py
│   │   ├── writing.py
│   │   ├── bible.py
│   │   └── style.py                # 风格提取提示词
│   │
│   ├── style/                      # 风格系统
│   │   ├── __init__.py
│   │   ├── extractor.py            # 文件读取 + OCR + 文本预处理
│   │   └── store.py                # 风格数据库 CRUD
│   │
│   ├── memory/                     # 记忆与持久化
│   │   ├── __init__.py
│   │   ├── checkpointer.py         # LangGraph Checkpointer 初始化
│   │   └── bible_store.py          # 故事圣经 SQLite 存储
│   │
│   ├── storage/                    # 工作空间文件管理
│   │   ├── __init__.py
│   │   ├── novel_store.py          # 小说项目文件管理
│   │   └── session_store.py        # 会话文件管理
│   │
│   └── ui/                         # TUI 界面
│       ├── __init__.py
│       ├── app.py                  # Textual 主应用（单屏）
│       └── widgets/
│           ├── message_display.py  # 对话滚动区域
│           ├── user_input.py       # 用户输入框
│           └── status_bar.py       # 底部状态栏
│
└── workspace/                      # 工作目录（自动生成）
    ├── deepnovel.db                # 唯一 SQLite 数据库：LangGraph Checkpoint + 故事圣经 + 会话元数据 + 风格库
    └── novels/                     # 小说项目目录
        └── {小说标题}/
            ├── meta.json           # 项目元数据
            ├── story_path.json     # 已确认的故事路径
            ├── bible_index.json    # 故事圣经简洁索引快照
            └── chapters/
                ├── node_001.md     # 各节点正文
                ├── node_002.md
                └── ...
```

---

## 5. 配置系统设计

### 5.1 配置文件 deepnovel.json 结构

```json
{
  "llm": {
    "provider": "openai",
    "api_key": "sk-xxxx",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 4096
  },
  "workspace": {
    "path": "./workspace"
  },
  "ui": {
    "theme": "dark",
    "stream_output": true
  }
}
```

### 5.2 config.py 设计要点

- 使用 `pydantic-settings` 的 `BaseSettings`，支持环境变量覆盖
- 环境变量前缀：`DEEPNOVEL_`，嵌套用双下划线分隔
  - 例：`DEEPNOVEL_LLM__API_KEY=sk-xxx`
- 配置加载优先级：环境变量 > deepnovel.json > 默认值
- `ConfigManager` 类负责加载、保存、更新配置
- 通过界面修改的配置必须同步写入 deepnovel.json
- 配置文件不存在时自动创建默认配置

### 5.3 LLM 客户端初始化

```
LLM 客户端通过 langchain-openai 的 ChatOpenAI 初始化：
- 使用配置中的 api_key、base_url、model、temperature
- Ollama 兼容：将 base_url 设为 Ollama 地址（如 http://localhost:11434/v1），api_key 设为任意非空字符串
- 客户端应在每次需要时从配置动态创建，不要在启动时缓存，以便配置修改后立即生效
```

---

## 6. 数据库设计（SQLite）

项目使用**唯一一个** SQLite 数据库文件 `deepnovel.db`，所有数据集中存储。LangGraph 的 Checkpointer 只操作它自己创建的表，SQLAlchemy 只操作我们定义的表，两者共用同一个数据库文件不会产生任何冲突。

### 6.1 deepnovel.db — 统一数据库

**LangGraph Checkpoint 表（自动管理，无需手动建表）**

由 AsyncSqliteSaver 自动创建和维护，存储：
- LangGraph 的完整状态快照（支持 Time Travel 回滚）
- 每次图节点执行后的 checkpoint
- 线程（thread）管理，每个会话对应一个 thread_id

**初始化方式：**
```
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

checkpointer = await AsyncSqliteSaver.from_conn_string("workspace/deepnovel.db")
```

**故事圣经表 + 会话元数据表（手动管理，使用 SQLAlchemy 2.0 异步 API）**

**characters 表（人物节点）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
novel_id        TEXT     NOT NULL                    -- 关联的小说项目
name            TEXT     NOT NULL                    -- 人物名
role            TEXT                                 -- protagonist/antagonist/supporting
background      TEXT                                 -- 固定背景（静态）
created_at_node INTEGER                              -- 在第几个节点中首次出现
```

**character_states 表（人物动态状态——动态节点）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
character_id    INTEGER  FOREIGN KEY → characters.id
after_node_id   INTEGER                              -- 完成第几个节点后的状态
physical        TEXT                                 -- 身体状况
mental          TEXT                                 -- 心理状态
resources       TEXT                                 -- JSON 数组：当前持有的资源/道具
location        TEXT                                 -- 当前所在位置
threat          TEXT                                 -- 当前面临的主要威胁
updated_at      TEXT                                 -- ISO 时间戳
```

**events 表（事件节点——静态）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
novel_id        TEXT     NOT NULL
node_index      INTEGER  NOT NULL                    -- 对应故事路径的第几个节点
title           TEXT     NOT NULL                    -- 事件标题（5字以内）
time_desc       TEXT                                 -- 事件发生的时间描述
location        TEXT                                 -- 事件发生地点
environment     TEXT                                 -- 环境细节
summary         TEXT                                 -- 事件概要（3~5句话）
key_info        TEXT                                 -- 对后续情节有影响的关键信息点
```

**event_characters 表（事件与人物的关联关系）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
event_id        INTEGER  FOREIGN KEY → events.id
character_id    INTEGER  FOREIGN KEY → characters.id
role_in_event   TEXT                                 -- 在该事件中的角色/作用
```

**event_relations 表（事件之间的因果关系）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
cause_event_id  INTEGER  FOREIGN KEY → events.id    -- 因
effect_event_id INTEGER  FOREIGN KEY → events.id    -- 果
relation_desc   TEXT                                 -- 关系描述
```

**foreshadowing 表（伏笔管理）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
novel_id        TEXT     NOT NULL
description     TEXT     NOT NULL                    -- 伏笔描述
planted_node    INTEGER                              -- 在第几个节点埋下
collected_node  INTEGER  NULLABLE                    -- 在第几个节点回收（NULL表示未回收）
status          TEXT     DEFAULT 'open'              -- open / collected
```

**relationship_changes 表（人物关系演变）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
novel_id        TEXT     NOT NULL
character_a_id  INTEGER  FOREIGN KEY → characters.id
character_b_id  INTEGER  FOREIGN KEY → characters.id
after_node_id   INTEGER                              -- 完成第几个节点后的关系
relation_type   TEXT                                 -- ally/enemy/neutral/unknown
description     TEXT                                 -- 关系详细描述
```

**writing_styles 表（写作风格库）**
```
id              INTEGER  PRIMARY KEY AUTOINCREMENT
style_id        TEXT     NOT NULL UNIQUE             -- 风格唯一标识（用户命名）
name            TEXT     NOT NULL                    -- 风格显示名称
description     TEXT                                 -- 风格简介（用户可读）
source_files    TEXT                                 -- JSON 数组：提取来源文件路径列表
writing_style   TEXT                                 -- 写作风格描述（语言特点/句式/用词）
writing_skills  TEXT                                 -- 写作技巧描述
plot_skills     TEXT                                 -- 剧情技巧描述
created_at      TEXT                                 -- ISO 时间戳
updated_at      TEXT                                 -- ISO 时间戳（覆盖时更新）
```

**session_meta 表（会话元数据）**
```
thread_id       TEXT     PRIMARY KEY                 -- LangGraph 的 thread_id
novel_id        TEXT                                 -- 关联的小说项目
title           TEXT                                 -- 会话显示标题
created_at      TEXT
updated_at      TEXT
current_stage   TEXT                                 -- 最后所在阶段
```

---

## 7. 数据模型设计（Pydantic）

### 7.1 schemas/project.py

```
ProjectSettings
  title: str                   # 小说标题
  genre: str                   # 题材
  archetype: Enum              # Survivor / Dominator / Investigator / Avenger
  tone: Enum                   # Dark / Hot-blooded / Humorous / Realistic
  pacing: Enum                 # Fast / Standard / Slow
  core_conflict: str           # 核心冲突（一句话）
  protagonist_background: str  # 主角背景
  target_words: int = 50000    # 目标字数
  novel_id: str                # 由标题生成的唯一ID
  style_id: Optional[str]      # 绑定的写作风格ID（可为空，表示不使用风格）

NovelMeta（存入 meta.json）
  novel_id: str
  title: str
  created_at: datetime
  updated_at: datetime
  current_node_index: int      # 当前正在处理的节点索引
  total_nodes: int
  current_words: int
  stage: str                   # 当前所在的工作流阶段
  style_id: Optional[str]      # 绑定的写作风格ID
```

### 7.2 schemas/style.py

```
WritingStyle
  style_id: str                # 唯一标识
  name: str                    # 显示名称
  description: str             # 风格简介
  source_files: list[str]      # 提取来源文件路径列表
  writing_style: str           # 写作风格：语言特点、句式偏好、用词习惯、叙事视角
  writing_skills: str          # 写作技巧：Show Don't Tell运用、节奏控制、场景转换
  plot_skills: str             # 剧情技巧：冲突设计、转折方式、铺垫与回收节奏
  created_at: datetime
  updated_at: datetime

StyleSummary（列表展示用，不含完整内容）
  style_id: str
  name: str
  description: str
  source_files: list[str]
  updated_at: datetime
```

### 7.2 schemas/story.py

```
StoryPathNode
  id: int                      # 节点编号，从1开始
  content: str                 # 一句话事件描述
  status: Enum
    draft                      # 仅有路径，未扩写
    expanded_v1                # 完成第一轮扩写
    expanded_v2                # 完成第二轮扩写
    written                    # 正文已完成
  expanded_v1: Optional[str]   # 第一轮扩写内容
  expanded_v2: Optional[str]   # 第二轮扩写内容（场景大纲）
  final_text: Optional[str]    # 最终正文
  state_after: Optional[dict]  # 本节点完成后的状态快照
    protagonist_physical: str
    protagonist_mental: str
    protagonist_resources: list[str]
    current_location: str
    current_threat: str

StoryPath
  arc_id: str                  # 固定为 "main"，不使用多Arc概念
  nodes: list[StoryPathNode]
  confirmed: bool              # 用户是否已确认路径
```

### 7.3 schemas/bible.py

```
BibleIndex（简洁索引，每次新节点开始前输出）
  novel_id: str
  as_of_node: int              # 基于第几个节点完成后的状态
  character_snapshots: list[CharacterSnapshot]
  event_titles: list[str]      # 已发生事件标题列表
  open_foreshadowing: list[str] # 未回收伏笔
  relationship_summary: str    # 当前势力/关系格局一句话概括

CharacterSnapshot
  name: str
  physical: str
  mental: str
  location: str
  key_resources: list[str]

BibleUpdate（每个节点完成后的增量更新）
  node_index: int
  character_state_changes: list[CharacterStateChange]
  new_event: EventRecord
  new_foreshadowing: list[str]
  collected_foreshadowing: list[str]
  relationship_changes: list[str]

EventRecord
  title: str
  time_desc: str
  location: str
  environment: str
  summary: str
  key_info: str
  participating_characters: list[str]
```

### 7.4 schemas/state.py — LangGraph 图状态（最重要）

```
DeepNovelState（TypedDict，用于 LangGraph StateGraph）

字段说明：

  # ---- 模式标识 ----
  mode: str                             # "chat"（对话模式）/ "workflow"（创作工作流模式）

  # ---- 项目信息 ----
  novel_id: Optional[str]               # 进入工作流后才有值
  project_settings: Optional[ProjectSettings]

  # ---- 写作风格 ----
  style_id: Optional[str]              # 绑定的风格ID（创作开始时确定，全程不变）
  style_content: Optional[WritingStyle] # 完整风格内容（从DB加载，注入提示词用）

  # ---- 故事路径 ----
  story_path: list[StoryPathNode]       # 完整路径节点列表
  path_confirmed: bool                  # 路径是否已被用户确认

  # ---- 当前处理进度 ----
  current_node_index: int               # 当前正在处理的节点（0-based）
  current_stage: str                    # 当前所在阶段
    可选值：
      # 对话模式阶段：
      "chat"               → 普通对话，意图识别中
      "collecting_params"  → 正在通过对话收集项目参数
      "confirm_start"      → 参数收集完毕，等待用户确认开始创作

      # 工作流阶段：
      "path_generation"    → 生成/修改路径
      "path_review"        → 等待用户确认路径
      "expand_v1"          → 第一轮扩写
      "expand_v1_review"   → 等待用户确认第一轮扩写
      "expand_v2"          → 第二轮扩写
      "expand_v2_review"   → 等待用户确认第二轮扩写
      "writing"            → 正文写作
      "writing_review"     → 等待用户确认正文
      "bible_update"       → 更新故事圣经
      "node_complete"      → 当前节点完成，准备下一节点
      "batch_complete"     → 当前批次完成，询问是否继续

  # ---- 对话模式专用字段 ----
  collected_params: dict               # 已通过对话收集到的参数（逐步积累）
    可包含：title, genre, archetype, tone, pacing, core_conflict, protagonist_background
  chat_history: list[dict]             # 完整对话历史（对话模式用）
    每条：{role: "user"/"assistant", content: str}

  # ---- 用户交互 ----
  user_input: str                       # 用户最新输入
  user_satisfied: Optional[bool]        # 用户是否满意当前输出
  user_feedback: Optional[str]          # 用户反馈内容（不满意时）

  # ---- 当前节点的输出 ----
  current_output: Optional[str]         # 当前阶段的生成输出，展示给用户

  # ---- 验证结果 ----
  validation_issues: list[dict]         # 路径验证发现的问题列表
    每个 dict 包含：
      type: str            # "因果断裂" / "动机不足" / "能力不匹配"
      position: str        # 问题位置描述
      suggestion: str      # 修改建议

  # ---- 故事圣经 ----
  bible_index: Optional[BibleIndex]     # 最新的简洁索引（每次新节点开始前刷新）

  # ---- 错误信息 ----
  error: Optional[str]
```

---

## 8. LangGraph 状态机设计（核心）

### 8.1 图结构总览

```
                          ┌──────────────────────────────────────────────────┐
                          │                                                  │
           START → [chat_node] ←──────────────────────────────────────────┐ │
                       │    ↑                                              │ │
                       │    └── 工作流完成/用户结束后回到对话模式            │ │
                       │                                                   │ │
              意图识别路由                                                  │ │
           ↙      ↓        ↘                                               │ │
    普通对话   收集参数   风格管理                                           │ │
       ↓         ↓                                                         │ │
    回复用户  [param_collect_node]                                          │ │
               ↓ 参数收集完毕，用户确认开始                                  │ │
          [workflow_start_node]                                            │ │
               ↓ 初始化项目、加载风格                                        │ │
          [path_gen_node] → [validate_node]                                │ │
                  ↑                  ↓                                     │ │
         用户修改路径    [human_review_path]                                │ │
                  └──── 不满意 ───────┘                                    │ │
                                  ↓ 满意                                   │ │
                        [expand_v1_node]                                   │ │
                                  ↓                                        │ │
                        [human_review_v1]                                  │ │
                                  ↓ 满意                                   │ │
                        [expand_v2_node]                                   │ │
                                  ↓                                        │ │
                        [human_review_v2]                                  │ │
                                  ↓ 满意                                   │ │
                         [write_node]                                      │ │
                                  ↓                                        │ │
                        [human_review_write]                               │ │
                                  ↓ 满意                                   │ │
                         [bible_update_node]                               │ │
                                  ↓                                        │ │
                        [node_complete_router]                             │ │
                            ↙           ↘                                  │ │
                      还有节点      当前批次全部完成                         │ │
                          ↓               ↓                                │ │
                 [expand_v1_node]  [human_review_continue]                 │ │
                  （下一节点）       询问是否继续创作                         │ │
                                      ↙        ↘                           │ │
                                 继续创作      明确结束                     │ │
                                     ↓              ↓                      │ │
                            [path_gen_node]    回到 chat_node ─────────────┘ │
                             （续写模式）                                      │
                                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Human-in-the-loop 实现方式

使用 LangGraph 的 **interrupt** 机制实现用户确认节点。

每个 `human_review_*` 节点的实现逻辑：

```
1. 节点执行时调用 interrupt()，图执行暂停
2. 将当前输出展示给用户（通过 TUI）
3. 用户输入响应后，通过 Command(resume=user_response) 恢复图执行
4. 节点根据用户响应决定路由方向：
   - 用户满意 → 进入下一阶段节点
   - 用户不满意且有反馈 → 回到上一个生成节点，携带反馈重新生成
   - 用户不满意无反馈 → 智能体主动提供2~3个方向选项
```

### 8.3 Time Travel（时光倒流）实现

```
用户随时可以指定回滚到某个 checkpoint：

1. 列出当前 thread 的所有 checkpoint（即每个节点完成后的状态快照）
2. 用户选择要回滚的节点
3. 使用 LangGraph 的 update_state 或从指定 checkpoint_id 重新 invoke
4. 图从该节点重新开始执行，覆盖之后的所有内容

Time Travel 的 checkpoint 粒度：
每个节点（包括 human_review 节点）完成后都创建 checkpoint
这样用户可以精确回滚到任意确认点
```

### 8.4 节点函数详细说明

#### chat_node（图的真正入口，始终运行）
```
职责：对话智能体，处理所有用户输入，识别意图并路由
触发条件：START 后以及工作流结束后回到对话模式
实现：使用 interrupt() 等待用户输入，收到输入后根据意图路由

意图路由逻辑：
  普通对话/闲聊      → 生成回复后再次 interrupt() 等待下一条输入
  创作意图           → 进入 param_collect_node
  继续已有项目意图   → 展示项目列表 → 用户选择后恢复对应 thread → 进入工作流
  风格管理意图       → 进入风格管理流程（见第12章）
  回滚/时光倒流意图  → 展示 checkpoint 列表 → 执行 Time Travel

注意：
  - chat_node 使用独立的对话历史（chat_history），与工作流的状态分开管理
  - 对话历史存入 LangGraph state 的 chat_history 字段
  - 使用 LangChain 的 ConversationChain 或直接维护消息列表
```

#### param_collect_node
```
职责：通过自然对话收集项目参数，直到参数足够后提示用户确认开始
触发条件：chat_node 识别到创作意图后
实现：使用 interrupt() 持续与用户对话收集参数

收集逻辑：
  - 每轮对话后检查 collected_params 中已有哪些参数
  - 优先收集缺失的关键参数（core_conflict 和 genre 最关键）
  - 非关键参数（pacing/tone）可以根据上下文推断，不必强制询问
  - 参数收集完毕后主动询问：
      1. 是否使用写作风格（展示已有风格列表供选择）
      2. 确认开始创作

路由逻辑：
  - 用户确认开始 → workflow_start_node
  - 用户改变主意 → 回到 chat_node
```

#### workflow_start_node
```
职责：创作工作流的初始化节点，在进入路径生成前完成所有准备工作
触发条件：用户在 param_collect_node 中确认开始创作
输入：collected_params, style_id（可为空）

处理内容：
  1. 从 collected_params 构建 ProjectSettings 对象
  2. 生成 novel_id，创建小说项目目录和数据库记录
  3. 如果 style_id 非空，从数据库加载完整 WritingStyle 内容存入 state
  4. 初始化 story_path 为空列表，current_node_index 为 0
  5. 切换 mode 为 "workflow"

输出：state 更新 novel_id, project_settings, style_content, mode="workflow"
→ 进入 path_gen_node
```

#### path_gen_node
```
职责：调用 PathGenerator 智能体生成故事路径
触发条件：current_stage == "path_generation"
输入：project_settings, user_input（有反馈时携带修改意见）
输出：state 更新 story_path, current_output（格式化的路径文本）
注意：
  - 如果 user_input 包含修改意见，则基于现有路径修改而非重新生成
  - 生成后立即调用 validate_node
```

#### validate_node
```
职责：对故事路径进行三重验证
触发条件：path_gen_node 完成后
输入：story_path
输出：state 更新 validation_issues
注意：
  - 验证结果附加到 current_output（路径展示内容的末尾）
  - 验证有问题时显示建议，但不阻断流程，用户有最终决定权
  - 验证完成后进入 human_review_path
```

#### human_review_path
```
职责：等待用户审阅路径并给出确认/修改意见
触发条件：validate_node 完成后
实现：使用 interrupt() 暂停
路由逻辑：
  - 用户满意 → path_confirmed=True → expand_v1_node（第一个节点）
  - 用户有修改意见 → path_confirmed=False → path_gen_node（携带反馈）
```

#### expand_v1_node
```
职责：对 current_node_index 指向的节点进行第一轮扩写
触发条件：current_stage == "expand_v1"
输入：
  - story_path[current_node_index]（当前节点）
  - story_path[current_node_index-1].state_after（上一节点状态，第一节点为空）
  - bible_index（当前故事圣经简洁索引）
输出：
  - story_path[current_node_index].expanded_v1 更新
  - current_output（格式化的第一轮扩写文本）
注意：必须在提示词中注入 bible_index，确保上下文一致性
```

#### human_review_v1
```
职责：等待用户确认第一轮扩写
路由逻辑：
  - 满意 → expand_v2_node
  - 不满意且有反馈 → expand_v1_node（携带反馈重写）
  - 不满意无反馈 → 智能体提供2~3个方向 → 等待用户选择 → expand_v1_node
```

#### expand_v2_node
```
职责：对当前节点进行第二轮场景化扩写
输入：
  - story_path[current_node_index].expanded_v1
  - bible_index
输出：
  - story_path[current_node_index].expanded_v2 更新
  - current_output（格式化的场景大纲文本）
```

#### human_review_v2
```
路由逻辑：同 human_review_v1，满意则进入 write_node
```

#### write_node
```
职责：根据场景大纲写作正文
输入：
  - story_path[current_node_index].expanded_v2（场景大纲）
  - story_path[current_node_index-1].final_text 的最后200字（衔接用）
  - bible_index（故事圣经简洁索引）
  - style_content（写作风格，可为空）
输出：
  - story_path[current_node_index].final_text 更新
  - current_output（正文内容）
注意：
  - 正文写作必须注入 bible_index 到提示词
  - 如果 style_content 非空，必须将风格内容注入提示词（见第9章写作提示词）
  - 写作完成后自动将正文保存到 workspace/novels/{title}/chapters/node_XXX.md
```

#### human_review_write
```
路由逻辑：同上，满意则进入 bible_update_node
```

#### bible_update_node
```
职责：提取本节点完成后的新增/变更信息，更新故事圣经数据库，输出增量更新内容
输入：
  - story_path[current_node_index]（完整节点数据）
  - project_settings
输出：
  - 写入 deepnovel.db（characters/events/foreshadowing 等表）
  - current_output（格式化的增量更新内容，展示给用户）
  - 更新 state 中的 bible_index（重新从数据库构建简洁索引）
注意：这是唯一写入 deepnovel.db 故事圣经表的节点，确保数据一致性
```

#### node_complete_router
```
职责：判断当前批次是否还有未处理的节点
逻辑：
  if current_node_index + 1 < len(story_path):
      current_node_index += 1
      current_stage = "expand_v1"
      → 输出新节点开始前的 bible_index 简洁索引
      → 进入 expand_v1_node（下一节点）
  else:
      → 进入 human_review_continue（当前批次已全部完成）
```

#### human_review_continue
```
职责：当前批次全部节点完成后，询问用户是否继续创作下一批故事路径
触发条件：node_complete_router 判断当前批次已全部完成
实现：使用 interrupt() 暂停

展示内容：
  - 本批次完成总结（完成节点数、新增字数、累计总字数）
  - 当前故事圣经简洁索引（让用户回顾故事进展）
  - 询问："是否继续创作下一批故事路径？"
  - 提示用户可以给出方向提示（如："接下来我想写主角复仇的部分"）

路由逻辑：
  - 用户明确说结束（"结束"/"完成"/"不了"等）→ 回到 chat_node（对话模式）
  - 其他任何输入（包括有方向提示或仅说"继续"）→ 进入 path_gen_node（续写模式）

续写模式下 path_gen_node 的变化：
  - is_continuation = True（标记为续写而非首次创作）
  - 提示词中注入：
      1. 当前故事圣经完整简洁索引（已发生的所有事件、人物状态、未回收伏笔）
      2. 上一批最后一个节点的 state_after（确保新路径从正确状态起步）
      3. 用户给出的方向提示（如有）
  - 生成的新路径必须与已完成内容连贯，不能与已发生事件矛盾
  - 新路径确认后，story_path 追加新节点（不替换，累积增长）
  - current_node_index 从新批次的第一个新节点开始
```

---

## 9. 提示词模块设计

所有提示词使用 LangChain 的 `ChatPromptTemplate`，通过 LCEL（`|` 管道）连接 LLM 和 OutputParser。

### 9.0 prompts/chat.py — 对话智能体提示词

**对话主提示词要点：**
```
- 角色：DeepNovel 创作助手，专注中长篇网文创作
- 能力：自然对话、创作咨询、参数收集、项目管理、风格管理
- 意图识别：输出 JSON 标识意图类型
    {"intent": "chat" / "create" / "continue_project" / "manage_style" / "rollback"}
- 对话风格：自然、有温度，像一个懂创作的朋友
- 注入变量：chat_history（对话历史），user_input，available_styles（已有风格列表），existing_novels（已有项目列表）
```

**参数收集提示词要点：**
```
- 任务：根据已收集的参数和对话历史，判断还缺什么参数，生成下一个问题
- 不要一次问多个问题，每轮只问最重要的一个缺失参数
- 如果上下文中能推断出参数值，直接推断并告知用户，不必再问
- 输出 JSON：
    {
      "response": str,              // 要说的话
      "extracted_params": dict,     // 从本轮对话中新提取到的参数
      "params_complete": bool,      // 参数是否已足够开始创作
      "suggested_style": str        // 根据用户描述推荐的风格ID（可为空）
    }
- 注入变量：chat_history，user_input，collected_params（已有参数），available_styles
```

### 9.1 prompts/path_generation.py

**系统提示词要点：**
```
- 角色：专业小说策划师
- 任务：根据项目参数生成 ≤10 条故事路径节点
- 注入变量：genre, archetype, tone, pacing, core_conflict, protagonist_background
- 主角原型影响规则（必须写入系统提示词）：
    Survivor → 被动应对、以弱胜强、靠智谋和地利
    Dominator → 主动出击、掌控局面
    Investigator → 信息获取、推理揭秘
    Avenger → 积累力量、清算旧账
- 节奏影响规则：
    Fast → 信息密度高，无废节点
    Slow → 可有更多铺垫
- 修改模式变量：has_feedback（bool），user_feedback（str）
    有反馈时：在现有路径基础上修改，而非重新生成
- 输出格式：JSON → {"nodes": [{"id": 1, "content": "..."}, ...]}
- 使用 JsonOutputParser
```

**验证提示词（独立）：**
```
- 输入：前一节点内容，当前节点内容
- 输出：{"is_natural": bool, "gap_score": 1-10, "suggestion": str}
- 输入：前N个节点摘要，当前节点行为
- 输出：{"motivation": str, "strength": 1-10, "sufficient": bool, "suggestion": str}
```

### 9.2 prompts/expansion.py

**第一轮扩写提示词要点：**
```
- 注入变量：
    node_content（当前节点一句话）
    previous_state（上一节点的 state_after，JSON 格式）
    bible_index_text（故事圣经简洁索引的文本格式）
    has_feedback（bool），user_feedback（str）
- 输出格式：JSON
    {
      "what": str,
      "why": str,
      "how": str,
      "state_after": {
        "protagonist_physical": str,
        "protagonist_mental": str,
        "protagonist_resources": [str],
        "current_location": str,
        "current_threat": str
      }
    }
- 重要：提示词中明确要求 state_after 必须与 previous_state 在位置上连续
```

**第二轮扩写提示词要点：**
```
- 注入变量：expanded_v1_text, bible_index_text, has_feedback, user_feedback
- 输出格式：JSON
    {
      "scene_setting": {"time": str, "location": str, "environment": str, "protagonist_status": str},
      "key_actions": [str, str, str, str, str],   // 5~7个
      "dialogue_or_thoughts": str,                 // 100~150字，有潜台词
      "emotional_rhythm": str,                     // 用→串联
      "foreshadowing": [str]                       // 可为空数组
    }
```

### 9.3 prompts/writing.py

**正文写作提示词要点（这是最关键的提示词，需要最详细）：**

系统提示词必须包含以下所有约束，**如果 style_content 非空，在约束之前先注入风格块**：

```
[风格注入块——仅在 style_content 非空时注入]
===== 写作风格参考 =====
以下是本作品的写作风格要求，请在写作时优先遵循：

【写作风格】
{style_content.writing_style}

【写作技巧】
{style_content.writing_skills}

【剧情技巧】
{style_content.plot_skills}

注意：风格参考是方向性指导，不是逐字模仿。在保持上述风格特征的同时，
内容必须完全原创，不得复制范文中的任何句子或段落。
========================

[约束一：禁词表]
以下词汇禁止出现：
情绪直述类：缓缓、蓦然、刹那间、霎时、不由得、不禁、心中一紧、心头一震、心跳加速、不禁动容
比喻滥用类：宛如、仿佛（用于比喻开头时）、犹如、好似、恍若
眼睛滥用类：眼眸、眸子、眼眸深处、眼底、目光深邃
命运感叹类：命运的齿轮、历史的车轮、冥冥之中、天意如此
网文烂俗类：逆天、无敌、碾压（作叙述词时）、颤抖吧

判断原则：
如果某个词是在【直接告诉读者应该感受什么】→ 换掉
如果某个词是在【呈现画面让读者自己感受】→ 可以保留

[约束二：Show Don't Tell]
用动作/细节/对话替代情绪描述
✗ "他非常愤怒"
✓ "他捏碎了手里的茶杯，瓷片划破手心，他没有低头看。"

[约束三：具体名词]
✗ "他拿起武器"
✓ "他拿起那把锈迹斑斑的杀猪刀"

[约束四：五感描写]
每个场景段落至少3处不同感官细节
视觉/听觉/嗅觉或触觉或味觉

[约束五：微动作心理法]
用细微身体动作暗示心理
紧张→食指无声敲桌沿三下又停住
犹豫→手放门把停顿了几秒才转动
愤怒→说话时声音反而变轻了

注入变量：
  scene_outline（场景大纲文本）
  previous_ending（上节正文最后200字，可为空）
  bible_index_text（故事圣经简洁索引）
  style_content（WritingStyle 对象，可为空，为空时不注入风格块）
输出：纯文本正文，使用 StrOutputParser
字数目标：800~1200字
```

**第二轮扩写提示词的风格注入（较简化版本）：**
```
如果 style_content 非空，在系统提示词中追加：
"在设计场景大纲时，请参考以下剧情技巧风格：{style_content.plot_skills}"
注入位置：expand_v2 的系统提示词末尾
```

### 9.4 prompts/bible.py

**故事圣经提取提示词：**
```
- 输入：当前节点的完整数据（expanded_v1/v2/final_text）
- 任务：提取本节点的新增/变更信息
- 输出格式：BibleUpdate 的 JSON 结构
- 注意：只提取本节点的增量，不重复已有信息
```

### 9.5 prompts/style.py — 风格提取提示词

**风格提取提示词要点：**
```
- 角色：专业文学评论家和写作教练
- 任务：从提供的范文文本中提取写作风格体系，形成可复用的写作指南
- 输入：范文文本（可能来自多个文件，拼接后传入）
- 强调：提取的是【规律和技巧】，不是内容摘要，不是情节复述

输出格式（JSON）：
{
  "writing_style": str,     // 语言特点、句式偏好、用词习惯、叙事视角
                            // 示例："句式短促有力，多用主动语态；偏好用具体细节替代
                            //        抽象描述；叙事视角贴近主角内心但保持克制..."
  "writing_skills": str,    // Show Don't Tell 的具体运用方式、节奏控制手法、
                            // 场景转换方式、对话设计特点
                            // 示例："情绪通过动作传递而非直接陈述；高潮前用细节铺垫
                            //        放慢节奏；对话精简，潜台词密度高..."
  "plot_skills": str        // 冲突设计方式、转折手法、伏笔与回收的节奏特点、
                            // 人物关系推进方式
                            // 示例："每章结尾留钩，以信息差驱动读者继续阅读；
                            //        冲突不靠巧合，靠人物性格必然导致的碰撞..."
}

注意事项：
- 每个字段500~800字，具体且可操作，避免空洞的形容词
- 必须给出具体的写作模式描述，而不是"文笔优美"这类无法执行的评价
- 如果范文样本不足（少于3000字），在每个字段末尾注明"样本较少，建议补充更多范文"
```

---

## 10. 智能体模块设计

每个智能体是一个独立的类，封装对应的 LLM 调用链。

### 10.0 agents/chat_agent.py — ChatAgent（对话层核心）

```
属性：
  llm: BaseChatModel
  intent_chain: prompt | llm | JsonOutputParser()
  param_chain: prompt | llm | JsonOutputParser()

方法：
  async chat(user_input, chat_history, available_styles, existing_novels) -> dict
    返回：{intent, response, extracted_params, params_complete}
    - intent 决定后续路由
    - response 是展示给用户的回复文本

  async collect_params(user_input, chat_history, collected_params, available_styles) -> dict
    返回：{response, extracted_params, params_complete, suggested_style}
    - 每次调用只询问一个最重要的缺失参数
    - extracted_params 与 collected_params 合并后得到新的完整参数集
```

### 10.1 agents/path_generator.py — PathGenerator

```
属性：
  llm: BaseChatModel
  chain: prompt | llm | JsonOutputParser()

方法：
  async generate(project_settings, user_input, existing_path=None, feedback=None) -> list[StoryPathNode]
    - existing_path 非空时进入修改模式
    - feedback 为用户的修改意见

  async suggest_alternatives(node_index, node_content, reason) -> list[str]
    - 用户不满意但没有具体意见时，生成2~3个替代方案
```

### 10.2 agents/validator.py — Validator

```
方法：
  async validate_causal_chain(node_prev, node_current) -> dict
    返回：{is_natural, gap_score, suggestion}

  async validate_motivation(context_nodes, current_action) -> dict
    返回：{motivation, strength, sufficient, suggestion}
    注意：context_nodes 是前面所有节点的内容列表，用于分析演变
    重要：提示词中强调"人设是动态演变的，不检查性格标签冲突"

  async validate_full_path(story_path) -> list[dict]
    批量验证整条路径，返回 issues 列表
```

### 10.3 agents/expander.py — PathExpander

```
方法：
  async expand_v1(node, previous_state, bible_index, feedback=None) -> tuple[str, dict]
    返回：(格式化文本, state_after 字典)

  async expand_v2(expanded_v1_text, bible_index, feedback=None) -> str
    返回：格式化的场景大纲文本

  async suggest_alternatives_v1(node, reason) -> list[str]
  async suggest_alternatives_v2(expanded_v1, reason) -> list[str]
    - 用于用户不满意无反馈时提供方向选择
```

### 10.4 agents/writer.py — Writer

```
方法：
  async write(scene_outline, previous_ending, bible_index, feedback=None) -> str
    返回：正文纯文本

  async rewrite(original_text, scene_outline, feedback, bible_index) -> str
    - 专门用于重写场景，保留用户认可的部分，修改不满意的部分
```

### 10.5 agents/bible_manager.py — BibleManager

```
方法：
  async extract_updates(node_data, project_settings) -> BibleUpdate
    - 调用 LLM 提取本节点的增量信息
    - 返回结构化的 BibleUpdate 对象

  async save_updates(novel_id, bible_update, db_session) -> None
    - 将 BibleUpdate 写入 deepnovel.db

  async build_index(novel_id, db_session) -> BibleIndex
    - 从 deepnovel.db 查询构建最新的 BibleIndex（简洁索引）

  async format_index_for_prompt(bible_index) -> str
    - 将 BibleIndex 格式化为适合注入提示词的文本
```

### 10.6 agents/style_extractor.py — StyleExtractor

```
属性：
  llm: BaseChatModel
  extract_chain: prompt | llm | JsonOutputParser()

方法：
  async extract_from_files(file_paths: list[str]) -> WritingStyle
    - 协调文件读取、OCR、文本预处理、LLM 提取的完整流程
    - 返回完整的 WritingStyle 对象（不含 style_id/name，由调用方设置）

  async _read_file(file_path: str) -> str
    - 根据文件扩展名选择读取方式：
        .txt / .md  → 直接读取
        .docx       → python-docx 提取文本
        .pdf        → pypdf 提取文本
        .png / .jpg / .jpeg / .webp → RapidOCR 提取文字
    - 返回纯文本字符串

  async _preprocess(texts: list[str]) -> str
    - 合并多个文件的文本
    - 清理乱码、多余空白、页码等噪音
    - 如果总文本超过 LLM 上下文限制，截取最具代表性的段落
      （截取策略：均匀采样，保留开头/中间/结尾各若干段）
    - 返回处理后的合并文本

  注意：
    - RapidOCR 是同步库，需要用 asyncio.to_thread() 包装为异步调用
    - 文件读取失败时记录警告并跳过，不中断整体流程
    - 预处理后文本建议控制在 8000 字以内，避免超出常见模型的上下文窗口
```

---

## 12. 写作风格系统设计

### 12.1 整体流程

```
用户指定文件或目录
        ↓
[StyleExtractor] 读取文件（支持txt/md/docx/pdf/png/jpg）
        ↓
图片文件 → RapidOCR 提取文字
文档文件 → 直接提取文本
        ↓
文本预处理（合并、清洗、采样控制长度）
        ↓
[LLM] 提取三类风格（writing_style / writing_skills / plot_skills）
        ↓
用户命名并确认 → 保存到 deepnovel.db（writing_styles 表）
        ↓
创作时选择绑定 → 注入到第二轮扩写和正文写作提示词
```

### 12.2 style/extractor.py — 文件读取与预处理

```
职责：处理所有文件类型的文本提取，屏蔽底层差异

支持的文件类型及处理方式：
  .txt / .md          → aiofiles 异步读取，自动检测编码
  .docx               → python-docx 提取所有段落文本
  .pdf                → pypdf 逐页提取文本
  .png / .jpg / .jpeg / .webp → RapidOCR（同步，用 asyncio.to_thread 包装）

目录处理：
  递归扫描目录下所有支持格式的文件
  忽略隐藏文件和系统文件

文本预处理规则：
  1. 去除页眉页脚（常见格式：纯数字行、重复出现的短行）
  2. 合并连续空白行为单个空行
  3. 去除乱码字符（非中文/英文/标点的异常字符）
  4. 总文本超过 8000 字时均匀采样：
     保留前 2000 字 + 中间均匀抽取 4000 字 + 后 2000 字
     采样时以段落为单位，不截断段落
```

### 12.3 style/store.py — 风格数据库 CRUD

```
方法：
  async save_style(style: WritingStyle) -> None
    - 新增或覆盖（按 style_id）
    - 覆盖时更新 updated_at

  async get_style(style_id: str) -> Optional[WritingStyle]
    - 返回完整 WritingStyle 对象

  async list_styles() -> list[StyleSummary]
    - 返回所有风格的摘要列表（不含完整内容）
    - 按 updated_at 倒序

  async delete_style(style_id: str) -> bool
    - 删除指定风格，返回是否成功

  async style_exists(style_id: str) -> bool
```

### 12.4 风格管理的对话交互流程

用户在对话层触发风格管理后，以下流程在 chat_node 内通过 interrupt() 完成：

**新增/覆盖风格：**
```
用户："帮我提取写作风格，文件在 /Users/xxx/novels/范文/"
  ↓
智能体："好的，我来分析这个目录下的文件。发现以下文件：
        · 天道图书馆.txt（约8.2万字）
        · 剧情片段.docx（约1.2万字）
        · 手稿截图.jpg（3张）
        正在提取中，请稍候..."
  ↓
[StyleExtractor 执行文件读取和 LLM 提取]
  ↓
智能体："提取完成！以下是提取到的风格概要：
        · 写作风格：句式简短有力，叙事视角贴近主角...
        · 写作技巧：情绪通过动作细节传递...
        · 剧情技巧：章节末尾必留钩子...
        请给这套风格起个名字（如：天道图书馆风格）："
  ↓
用户："就叫天道风格"
  ↓
智能体："已保存'天道风格'。（如果已存在同名风格，本次将覆盖原有内容）"
```

**列出/删除风格：**
```
用户："我有哪些风格？"
智能体：展示 StyleSummary 列表，显示名称、来源文件、更新时间

用户："删除天道风格"
智能体："确认删除'天道风格'吗？（已绑定此风格的小说不受影响）"
用户确认后执行删除
```

### 12.5 风格在提示词中的注入规则

```
注入时机：
  - expand_v2_node（第二轮扩写）：注入 plot_skills 部分
  - write_node（正文写作）：注入完整三类风格

注入格式：见 9.3 prompts/writing.py 中的风格注入块

不注入的情况：
  - project_settings.style_id 为空
  - 数据库中找不到对应 style_id 的风格记录（降级处理，记录警告，不中断写作）

风格内容在 workflow_start_node 时一次性从数据库加载到 state.style_content
全程复用同一份内容，不重复查询数据库
```

---

## 13. TUI 界面设计

使用 **Textual** 框架实现。整个应用只有**一个主界面**，没有多屏切换，所有交互都在对话区完成。

### 13.1 整体布局

```
╔══════════════════════════════════════════════════════════╗
║ DeepNovel                                    [ESC]退出   ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║  [对话滚动区域]                                           ║
║                                                          ║
║  DeepNovel: 欢迎回来！您有以下小说项目：                  ║
║  1. 冤狱商战（进行中，节点4/8，共3200字）                  ║
║  2. 赛博修仙（已完成，共52000字）                          ║
║  输入序号继续创作，或者告诉我您想做什么。                   ║
║                                                          ║
║  用户: 继续第1个                                          ║
║                                                          ║
║  DeepNovel: 好的，继续《冤狱商战》...                      ║
║  ...                                                     ║
║                                                          ║
╠══════════════════════════════════════════════════════════╣
║  > [用户输入框]                              [Enter发送]  ║
╠══════════════════════════════════════════════════════════╣
║  模式：创作中 | 《冤狱商战》节点4/8 | 累计3200字           ║
╚══════════════════════════════════════════════════════════╝
```

### 13.2 启动流程

**第一步：检查配置**

启动时立即检查 `api_key`、`base_url`、`provider` 是否完整。如果缺失，在对话区内联提示，用户直接在输入框中填写，无需跳转界面：

```
DeepNovel: 检测到尚未配置 API Key，请输入后继续：
           Provider（openai/ollama）：▌

用户输入后逐项确认，全部填写完毕后自动保存到 deepnovel.json 并继续启动。
```

**第二步：展示小说列表**

配置完整后，在对话区顶部内嵌展示当前所有小说项目（纯文本列表），并附上欢迎语。如果没有任何项目，直接说"还没有小说项目，告诉我您想写什么吧"。

**无需任何按钮或额外面板，用户直接用自然语言回应。**

### 13.3 配置更新

用户随时可以在对话中更新配置，无需重启：

```
用户："更新一下 api key"
DeepNovel："好的，请输入新的 API Key："
用户：输入新值
DeepNovel："已更新并保存。"
```

配置更新后立即写入 `deepnovel.json`，下一次 LLM 调用自动使用新配置。

### 13.4 风格列表的展示时机

风格列表**不常驻显示**，只在以下时机由智能体主动内联展示：

- 用户说"新建小说"/"我想写"等创作意图被识别时
- 参数收集完毕、即将进入创作流程前的确认环节

展示格式（内嵌在对话区）：
```
DeepNovel: 在开始之前，您是否要使用某种写作风格？
           现有风格：
           1. 天道风格（来源：天道图书馆.txt，更新于2025-03）
           2. 诛仙风格（来源：诛仙节选.docx，更新于2025-01）
           输入序号选择，输入"新建"提取新风格，或直接回车跳过。
```

### 13.5 创作流程中的输出方式

创作流程中所有内容（故事路径、扩写、正文、故事圣经更新）全部在对话区顺序输出，不使用任何侧边面板。故事圣经的简洁索引和增量更新作为对话消息直接出现在对话流中。

### 13.6 状态栏

底部状态栏始终显示当前关键状态，内容根据模式切换：

```
对话模式：  模式：对话中
创作模式：  模式：创作中 | 《小说标题》节点X/Y | 累计N字 | 风格：天道风格
配置录入：  模式：配置设置中
```

### 13.7 流式输出实现

```
- 使用 LangChain 的 astream() 获取流式 token
- 通过 Textual 的 reactive 机制实时更新对话区
- LangGraph 的 astream_events() 提供节点级别的流式事件
- 风格提取过程中在对话区实时输出进度：
    "正在读取文件（1/3）..."
    "正在分析风格..."
    "提取完成！"
```

---

## 14. 工作空间文件管理

### 14.1 storage/novel_store.py

```
职责：管理 workspace/novels/{title}/ 目录下的文件

方法：
  create_novel_dir(novel_id, title) -> Path
    创建小说目录结构

  save_meta(novel_id, meta: NovelMeta) -> None
    保存/更新 meta.json

  save_story_path(novel_id, story_path: list[StoryPathNode]) -> None
    保存 story_path.json（整个路径的当前状态）

  save_chapter(novel_id, node_index, content) -> None
    保存 chapters/node_XXX.md

  save_bible_index_snapshot(novel_id, bible_index: BibleIndex) -> None
    保存 bible_index.json（最新简洁索引的快照，便于查看）

  load_meta(novel_id) -> Optional[NovelMeta]
  load_story_path(novel_id) -> Optional[list[StoryPathNode]]
  list_novels() -> list[NovelMeta]
```

### 14.2 storage/session_store.py

```
职责：管理会话元数据（LangGraph Checkpoint 自动管理状态，这里只管元数据）

会话元数据存储在 deepnovel.db 的 session_meta 表中（见第6章）

方法：
  create_session(thread_id, novel_id, title) -> None
  update_session(thread_id, stage) -> None
  list_sessions() -> list[dict]
    按 updated_at 倒序排列
  get_session(thread_id) -> Optional[dict]
```

---

## 15. 启动入口

### 15.1 deepnovel/__main__.py

```
功能：
1. 解析命令行参数（可选：--config 指定配置文件路径）
2. 加载配置（ConfigManager）
3. 确保工作目录和数据库存在（初始化）
4. 启动 Textual App

main() 函数：
  app = DeepNovelApp()
  app.run()
```

### 15.2 应用初始化顺序

```
1. 读取 deepnovel.json（不存在则创建默认配置）
2. 创建 workspace/ 目录结构（不存在则创建）
3. 初始化 deepnovel.db：
   a. 使用 SQLAlchemy create_all 创建故事圣经表和会话元数据表
   b. 初始化 AsyncSqliteSaver（LangGraph 自动创建其 checkpoint 表）
   两者连接同一个 deepnovel.db，互不干扰
4. 启动 TUI
```

---

## 16. 开发顺序与优先级

### Phase 1：核心骨架（能跑通对话→创作完整流程）

```
P0（必须先完成）：

1. config.py
   - ConfigManager 类，deepnovel.json 读写，环境变量支持

2. schemas/ 全部模型
   - ProjectSettings（含 style_id）, StoryPathNode, StoryPath
   - WritingStyle, StyleSummary
   - DeepNovelState（含 mode / chat_history / collected_params）
   - BibleIndex, BibleUpdate

3. memory/checkpointer.py
   - AsyncSqliteSaver 初始化封装

4. 数据库初始化
   - SQLAlchemy 建表（含 writing_styles 表）

5. chat/ 对话层最简版本
   - ChatAgent 只实现意图识别 + 参数收集
   - 验证对话→参数收集→确认开始的流程

6. graph/builder.py 最简版本
   - 只实现 chat_node → param_collect_node → workflow_start_node → path_gen_node → human_review_path → END
   - 验证从对话进入工作流的切换是否正常

7. prompts/path_generation.py + agents/path_generator.py
   - 实现路径生成，验证 LLM 调用

8. TUI 最简版本
   - 只有 ChatScreen，能输入输出，能流式渲染
```

### Phase 2：完整工作流

```
P1：

9.  agents/validator.py + 验证提示词
10. 完整 LangGraph 图（所有节点和边，含 human_review_continue）
11. prompts/expansion.py + agents/expander.py
12. prompts/writing.py + agents/writer.py（暂不含风格注入）
13. memory/bible_store.py + prompts/bible.py + agents/bible_manager.py
14. graph/nodes/bible_node.py
15. storage/novel_store.py（文件保存）
```

### Phase 3：风格系统

```
P2：

16. style/extractor.py（文件读取 + RapidOCR + 预处理）
17. prompts/style.py + agents/style_extractor.py
18. style/store.py（风格 CRUD）
19. 在 write_node 和 expand_v2_node 中接入风格注入
20. 在 chat_node 中接入风格管理意图处理
```

### Phase 4：完整 TUI 和用户体验

```
P3：

21. ui/app.py 完整版本
    - 启动时配置检查与内联录入流程
    - 小说列表内嵌展示
    - 状态栏根据模式动态切换
22. 流式输出优化（风格提取进度实时反馈）
23. storage/session_store.py（会话元数据管理）
24. Time Travel 内联交互（在对话区展示 checkpoint 列表，用户输入序号回滚）
```

### Phase 5：细节完善

```
P4：

27. 错误处理（LLM 调用失败重试、JSON 解析失败、文件读取失败）
28. 配置验证（API Key 有效性检查）
29. 导出功能（所有章节合并导出为完整 txt/md 文件）
30. 风格提取进度显示（文件数量多时的进度反馈）
```

---

## 附录：关键注意事项

### LangGraph 版本 API 注意

```
- 使用最新版 LangGraph，interrupt() 的 API 在不同版本有差异，开发时参考最新官方文档
- Human-in-the-loop 推荐使用 interrupt() + Command(resume=...) 模式
- Checkpointer 初始化使用异步方式：await AsyncSqliteSaver.from_conn_string(...)
- StateGraph 的状态定义使用 TypedDict，不使用 Pydantic BaseModel（LangGraph 原生支持 TypedDict）
- 图中节点函数返回 dict（只包含需要更新的字段），不返回完整 state
- chat_node 是图的长期运行节点，通过反复 interrupt() 实现持续对话
```

### LangChain 最新版 API 注意

```
- 使用 ChatPromptTemplate.from_messages() 构建提示词
- LCEL 管道：prompt | llm | parser
- 异步调用使用 .ainvoke() 和 .astream()
- JsonOutputParser 可直接解析 LLM 输出的 JSON 文本
- StrOutputParser 用于正文写作，提取纯文本
- 消息类型：HumanMessage / AIMessage / SystemMessage
```

### 并发与异步

```
- 全程使用 asyncio，所有 LLM 调用和数据库操作均为异步
- Textual 框架原生支持 asyncio，可以直接在 App 中使用 async def
- SQLAlchemy 使用 async_engine + AsyncSession
- RapidOCR 是同步库，必须用 asyncio.to_thread() 包装
- 避免在 async 函数中使用同步 IO 操作
```

### 配置安全

```
- API Key 不得打印到日志
- deepnovel.json 中的 api_key 字段在界面显示时应脱敏（显示为 sk-****）
- 建议将 deepnovel.json 加入 .gitignore
```

---

*DeepNovel 开发文档 v1.2*
*技术栈：LangChain（最新版）+ LangGraph（最新版）+ LangMem（最新版）+ Textual + SQLite + RapidOCR*
