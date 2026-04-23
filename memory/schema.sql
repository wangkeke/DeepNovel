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
    synopsis_json     TEXT,    -- 宏观构思 JSON（用户确认后写入）
    entity_summary    TEXT,    -- 实体快照摘要（由 bible_update_node 生成，供 path_gen 等节点快速获取上下文）
    last_batch_ending TEXT,    -- 上批结尾衔接状态 JSON（主角处境/未解决线索/下批情感基调）
    world_setting_json TEXT,   -- 世界设定卡 JSON（静态，synopsis 确认后锁定，全书不变）
    protagonist_name   TEXT,   -- 主角标准名（主角人物卡建立时写入，用于排除首次出场检测）
    last_action_intent TEXT,   -- 上一章结尾的行动意图（bible_update 提取，expand1 硬约束承接）
    platform_style     TEXT DEFAULT '通用网文',  -- 目标平台风格（创作启动时选择，全书固定）
    volumes_json       TEXT,   -- 卷章结构 JSON，数组：[{volume_index, volume_name, volume_tagline, start_seq, end_seq}]
    -- 以下列在 init_db() 中通过 ALTER 补全（旧库迁移）：core_cast_json、event_chain_json
    status            TEXT DEFAULT 'drafting',  -- drafting|done
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);

-- 故事路径节点表（每部小说 seq 从 1 开始）
CREATE TABLE IF NOT EXISTS story_nodes (
    node_id               TEXT PRIMARY KEY,
    project_id            TEXT NOT NULL,
    seq                   INTEGER NOT NULL,       -- 每部小说内从 1 开始
    node_name             TEXT,
    one_liner             TEXT,                   -- 一句话概括
    pressure_chain_type   TEXT,
    resolution_chain_type TEXT,
    input_state_hint      TEXT,
    output_state_hint     TEXT,
    -- 章节写完后填充
    event_path_chain      TEXT,                   -- 事件路径链 JSON 数组（章节摘要）
    status                TEXT DEFAULT 'planned', -- planned|writing|done
    created_at            TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id),
    UNIQUE (project_id, seq)
);

-- 已完成章节表
CREATE TABLE IF NOT EXISTS chapters (
    chapter_id        TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL,
    node_id           TEXT,                       -- 关联 story_nodes
    seq               INTEGER,                   -- 冗余存储，方便直接排序
    node_name         TEXT,
    content           TEXT,
    word_count        INTEGER,
    created_at        TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id),
    FOREIGN KEY (node_id)    REFERENCES story_nodes(node_id)
);

-- 实体知识库：人物/地点/道具卡片
CREATE TABLE IF NOT EXISTS entity_cards (
    entity_id    TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    card_type    TEXT NOT NULL,  -- character|location|item
    name         TEXT NOT NULL,
    aliases      TEXT,           -- JSON 数组
    data_json    TEXT NOT NULL,  -- 完整卡片详情 JSON
    first_seen   INTEGER DEFAULT 0,   -- 首次出现的全局 seq
    last_updated INTEGER DEFAULT 0,   -- 最后更新的全局 seq
    appears_from_volume INTEGER DEFAULT 0,  -- 浮动配角：哪卷开始出场，0=开篇即出场
    is_female_lead INTEGER DEFAULT 0,       -- 女主标识
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now')),
    UNIQUE (project_id, card_type, name),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id)
);

-- 势力卡片表（与 entity_cards 分离，便于人物-势力关联）
CREATE TABLE IF NOT EXISTS faction_cards (
    faction_id   TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    name         TEXT NOT NULL,
    faction_type TEXT DEFAULT 'neutral',  -- protagonist_side|antagonist|neutral|hidden
    description  TEXT,
    core_members  TEXT,   -- JSON：关联人物名列表
    goals         TEXT,
    stance_to_protagonist TEXT,
    appears_from_volume INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id)
);

-- 事件时间线（按节点 seq 排列）
CREATE TABLE IF NOT EXISTS event_timeline (
    event_id      TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,   -- 对应 story_nodes.seq
    description   TEXT,
    characters    TEXT,  -- JSON 数组：涉及人物名
    locations     TEXT,  -- JSON 数组：涉及地点名
    items         TEXT,  -- JSON 数组：涉及道具名
    is_foreshadow INTEGER DEFAULT 0,
    foreshadow_id TEXT,  -- 伏笔 ID（planted_foreshadows 中的 foreshadow_id）
    created_at    TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id)
);

-- 伏笔独立表（与 state.bible 冗余，以独立表为主）
CREATE TABLE IF NOT EXISTS foreshadow_entries (
    foreshadow_id       TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL,
    foreshadow_type     TEXT DEFAULT 'event',
    surface_meaning     TEXT NOT NULL,
    true_meaning        TEXT DEFAULT '',
    planted_at_node     INTEGER DEFAULT 0,
    collected_at_node   INTEGER DEFAULT 0,
    misdirect_direction TEXT DEFAULT '',
    mentioned_by        TEXT DEFAULT '',
    story_potential     TEXT DEFAULT '',
    mystery_type        TEXT DEFAULT 'normal',
    is_backbone         INTEGER DEFAULT 0,
    urgency             TEXT DEFAULT 'latent',
    mention_count       INTEGER DEFAULT 1,
    ready_threshold     INTEGER DEFAULT 3,
    is_inferred         INTEGER DEFAULT 0,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_foreshadow_project_urgency
    ON foreshadow_entries(project_id, urgency, collected_at_node);

CREATE UNIQUE INDEX IF NOT EXISTS idx_foreshadow_unique
    ON foreshadow_entries(project_id, surface_meaning);

-- 世界词条库（World Lexicon — 补丁 C）
CREATE TABLE IF NOT EXISTS world_lexicon (
    lexicon_id              TEXT NOT NULL,
    project_id              TEXT NOT NULL,
    term                    TEXT NOT NULL,
    term_type               TEXT DEFAULT 'A',   -- A|B|C
    category                TEXT DEFAULT '其他', -- 地名/药物/器具/毒素/功法/法则/组织/其他
    static_profile_json     TEXT DEFAULT '{}',  -- {definition, inherent_attributes, hard_constraints, world_physics_basis}
    dynamic_associations_json TEXT DEFAULT '[]', -- [{chapter_id,event_id,association_type,holder,context_note,is_active}]
    incomplete_clue_json    TEXT DEFAULT '{}',  -- {has_incomplete_clue,clue_fragment,trigger_condition,completion_status,karmic_ledger_ref}
    first_appearance_json   TEXT DEFAULT '{}',  -- {chapter_id,appearance_mode,was_noticed_by_protagonist}
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (lexicon_id, project_id),
    UNIQUE (project_id, term),
    FOREIGN KEY (project_id) REFERENCES novel_projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_world_lexicon_project
    ON world_lexicon(project_id, term_type);

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
