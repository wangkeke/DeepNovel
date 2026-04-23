"""
segmenter_node：中观节点切分
三步策略：
  Step 1 - 章节标题识别：按章回标题做初步切分
  Step 2 - 字数粗筛：合并 <SEGMENT_MIN_CHARS 的短段，拆分 >SEGMENT_MAX_CHARS 的超长段
  Step 3 - 输出状态验证：LLM 判断段落结尾是否完成本质性改变，未改变则与下一章合并
"""
from __future__ import annotations
import re
from schemas.state import ExtractionState
from prompts.extraction.segmenter import SEGMENTER_BOUNDARY_SYSTEM, SEGMENTER_BOUNDARY_USER
from utils.llm import call_llm_json
from config import SEGMENT_TARGET_CHARS, SEGMENT_MIN_CHARS, SEGMENT_MAX_CHARS


# ─── Step 1：章节标题正则 ─────────────────────────────────────────────────────
CHAPTER_TITLE_PATTERNS = [
    r'^第[零一二三四五六七八九十百千万\d]+[章节卷回篇部集][\s\S]*$',
    r'^Chapter\s+\d+',
    r'^\d+[\.、。]\s*\S',
    r'^【.{1,20}】',
    r'^［.{1,20}］',
]
CHAPTER_RE = re.compile(
    '|'.join(CHAPTER_TITLE_PATTERNS),
    re.MULTILINE | re.IGNORECASE
)


def _detect_chapter_splits(text: str) -> list[int]:
    """返回所有章节标题在 text 中的起始位置列表（含 0）"""
    positions = [0]
    for m in CHAPTER_RE.finditer(text):
        if m.start() > 0:
            positions.append(m.start())
    return sorted(set(positions))


def _split_by_chapters(text: str) -> list[dict]:
    """Step 1：按章节标题做初步切分，每段含 title/text/char_count"""
    positions = _detect_chapter_splits(text)
    if len(positions) <= 1:
        # 未检测到章节标题，直接整篇作为一个段落
        return [{"title": "全文", "text": text, "char_count": len(text), "source_chapters": []}]

    chapters = []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            continue
        # 取第一行作为标题
        first_line = chunk.split('\n', 1)[0].strip()
        chapters.append({
            "title": first_line or f"第{i+1}章",
            "text": chunk,
            "char_count": len(chunk),
            "source_chapters": [first_line] if first_line else [],
        })
    return chapters


def _merge_and_split(chapters: list[dict]) -> list[dict]:
    """Step 2：合并过短段，拆分超长段，使每段字数在合理范围内"""
    result: list[dict] = []
    buffer_text = ""
    buffer_titles: list[str] = []

    def flush_buffer():
        if buffer_text.strip():
            result.append({
                "title": buffer_titles[0] if buffer_titles else "合并段",
                "text": buffer_text.strip(),
                "char_count": len(buffer_text.strip()),
                "source_chapters": list(buffer_titles),
            })

    for ch in chapters:
        text = ch["text"]
        title = ch["title"]

        # 超长段：强制按字数拆分
        if len(text) > SEGMENT_MAX_CHARS:
            # 先把缓冲区冲掉
            flush_buffer()
            buffer_text = ""
            buffer_titles = []
            # 再按目标字数切
            pos = 0
            sub_idx = 0
            while pos < len(text):
                target = min(pos + SEGMENT_TARGET_CHARS, len(text))
                # 找最近换行
                if target < len(text):
                    nl = text.rfind('\n', pos, target)
                    end = nl if nl > pos + 1000 else target
                else:
                    end = len(text)
                chunk = text[pos:end].strip()
                if chunk:
                    result.append({
                        "title": f"{title}（{sub_idx + 1}）",
                        "text": chunk,
                        "char_count": len(chunk),
                        "source_chapters": [title],
                    })
                    sub_idx += 1
                pos = end
            continue

        # 短段：合并进缓冲区
        if len(text) < SEGMENT_MIN_CHARS:
            buffer_text += "\n\n" + text
            buffer_titles.append(title)
            # 若合并后超过目标字数，先冲掉
            if len(buffer_text) >= SEGMENT_TARGET_CHARS:
                flush_buffer()
                buffer_text = ""
                buffer_titles = []
            continue

        # 正常段：先冲缓冲，再添加
        flush_buffer()
        buffer_text = ""
        buffer_titles = []
        result.append({
            "title": title,
            "text": text,
            "char_count": len(text),
            "source_chapters": ch.get("source_chapters", [title]),
        })

    flush_buffer()
    return result


async def _validate_boundaries(segments: list[dict]) -> list[dict]:
    """
    Step 3：输出状态验证
    对每段结尾调用 LLM 判断是否发生了本质性改变。
    若 changed=false，则将当前段与下一段合并后再次验证，直到 changed=true 或到末段。
    """
    if not segments:
        return segments

    validated: list[dict] = []
    i = 0
    while i < len(segments):
        current = segments[i]
        # 取末尾 200 字做边界验证
        tail = current["text"][-200:]
        user_prompt = SEGMENTER_BOUNDARY_USER.format(segment_tail=tail)

        try:
            res = await call_llm_json(SEGMENTER_BOUNDARY_SYSTEM, user_prompt)
            changed = res.get("changed", True)
        except Exception:
            # LLM 调用失败时保守处理：视为已改变，不合并
            changed = True

        if not changed and i + 1 < len(segments):
            # 未发生本质改变：与下一段合并
            next_seg = segments[i + 1]
            merged_text = current["text"] + "\n\n" + next_seg["text"]
            merged = {
                "title": current["title"],
                "text": merged_text,
                "char_count": len(merged_text),
                "source_chapters": current.get("source_chapters", []) + next_seg.get("source_chapters", []),
            }
            # 用合并后的段替代两段，继续验证
            segments = segments[:i] + [merged] + segments[i + 2:]
            # 不移动 i，重新验证合并后的段
        else:
            validated.append(current)
            i += 1

    return validated


async def segmenter_node(state: ExtractionState) -> dict:
    """
    三步切分节点：
      Step 1 - 章节标题识别
      Step 2 - 字数粗筛（合并/拆分）
      Step 3 - LLM 输出状态验证（changed=false 则合并下一章）
    """
    raw_text = state.get("raw_text", "")

    # Step 1
    chapters = _split_by_chapters(raw_text)

    # Step 2
    segments_raw = _merge_and_split(chapters)

    # Step 3
    segments_validated = await _validate_boundaries(segments_raw)

    # 编号
    segments = []
    for idx, seg in enumerate(segments_validated):
        segments.append({
            "index": idx,
            "title": seg["title"],
            "text": seg["text"],
            "char_count": seg["char_count"],
            "source_chapters": seg.get("source_chapters", []),
        })

    return {
        "segments": segments,
        "total_segments": len(segments),
        "current_batch_index": 0,
        "batch_summaries": [],
        "entity_registry": {"blueprint_id": "", "entities": []},
        "pass1_context": {},
        "pass2_batch_index": 0,
        "foreshadow_entries": [],
    }
