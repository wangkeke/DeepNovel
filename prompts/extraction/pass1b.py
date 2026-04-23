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
