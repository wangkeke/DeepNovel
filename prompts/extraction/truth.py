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
