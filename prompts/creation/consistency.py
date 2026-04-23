from prompts.common.deepnovel_constitution import DEEPNOVEL_CONSTITUTION

CONSISTENCY_SYSTEM = DEEPNOVEL_CONSTITUTION + "\n\n" + """你是一个故事一致性审核员。
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
5. Show, Don't Tell：若大段内心独白宣称「我成熟了」「我下次不能大意」，或空洞写「他极度愤怒」而无视听载体，判为风险并写入 violations

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
