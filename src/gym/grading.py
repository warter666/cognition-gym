"""代码化批改：位置分确定性判定（difflib），LLM 只判模糊的类型/解释分。

设计要点（PLAN.md §3）：
- 用户摘句 ↔ 答案卡 quote 的匹配不经过 LLM，规则可单测、零成本、防幻觉；
- 漏报/误伤/仲裁三类由代码分类，LLM 无法越权改分。
"""

from __future__ import annotations

from difflib import SequenceMatcher

from .schema import AnswerKey, Grading, UserMark

MATCH_THRESHOLD = 0.72


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0  # 摘句常是答案卡 quote 的子串
    return SequenceMatcher(None, a, b).ratio()


def match_positions(key: AnswerKey, marks: list[UserMark]) -> dict:
    """返回：{key_id: (mark_index, ratio)}、误伤、仲裁 三类分类结果。"""
    key_hits: dict[int, tuple[int, float]] = {}
    false_positives: list[dict] = []
    arbitrated: list[dict] = []

    for i, mark in enumerate(marks):
        best_id, best_r = None, 0.0
        for item in key.items:
            r = _ratio(mark.quote, item.quote)
            if r > best_r:
                best_id, best_r = item.id, r
        if best_r >= MATCH_THRESHOLD:
            # 同一处被多条标注命中时取相似度最高的一条
            if best_id not in key_hits or key_hits[best_id][1] < best_r:
                key_hits[best_id] = (i, best_r)
            continue
        best_d = max((_ratio(mark.quote, d) for d in key.distractors), default=0.0)
        if best_d >= MATCH_THRESHOLD:
            false_positives.append({"mark_index": i, "quote": mark.quote})
        else:
            arbitrated.append({"mark_index": i, "quote": mark.quote, "reason": mark.reason})

    missed = [item.id for item in key.items if item.id not in key_hits]
    return {"key_hits": key_hits, "false_positives": false_positives, "arbitrated": arbitrated, "missed": missed}


def assemble_grading(
    key: AnswerKey,
    marks: list[UserMark],
    semantic_judgements: dict[int, dict[str, bool]],
) -> Grading:
    """semantic_judgements: {key_id: {"type": bool, "explanation": bool}}，来自小模型，仅对命中条目。"""
    matched = match_positions(key, marks)
    per_item, total = [], 0
    full = len(key.items) * 4
    for item in key.items:
        hit = matched["key_hits"].get(item.id)
        if hit is None:
            per_item.append({"key_id": item.id, "position": False, "type": False,
                             "explanation": False, "score": 0})
            continue
        j = semantic_judgements.get(item.id, {"type": False, "explanation": False})
        score = 1 + int(j.get("type", False)) + (2 if j.get("explanation", False) else 0)
        total += score
        per_item.append({"key_id": item.id, "position": True,
                         "type": j.get("type", False), "explanation": j.get("explanation", False),
                         "score": score, "mark_index": hit[0]})
    percent = round(total / full * 100) if full else 0
    return Grading(
        percent=percent,
        full_score=full,
        per_item=per_item,
        missed=matched["missed"],
        false_positives=[{"quote": m["quote"]} for m in matched["false_positives"]],
        arbitrated=matched["arbitrated"],
    )
