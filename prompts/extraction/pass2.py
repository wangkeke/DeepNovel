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
      "foreshadow_id": "F{batch_index:03d}_{{序号:02d}}",
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
