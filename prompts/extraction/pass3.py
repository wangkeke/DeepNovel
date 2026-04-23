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
