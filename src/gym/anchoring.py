"""有界锚定代理（agentic RAG）：全项目唯一的 agent 环，工具只有检索，出口只有两个。

设计原则（与"批改公平性代码化"同源：模型负责理解，代码负责控制与兜底）：
- 模型只承担四类理解职责——改写查询 / 判断充分性 / 抽取声明 / 核对判定；
  循环轮次、检索执行、出口裁决全部在代码里。有界性：检索 ≤max_rounds 轮、
  声明抽取 ≤max_claims 条、核查结论只核不判（unverified ≠ false）。
- 两个调用点共用同一个环：出题前锚定事实框架（anchor），出题后核查事实声明
  （fact_check）——工具同一（Store.search_cards）、模式同一（改写→检索→判定）。
- 事实核查只对 M1 生效：M2 的"失真"是刻意产物且有用户原文对照，其风险由
  答案卡与原文约束覆盖；M1 的失真才是模型幻觉风险。
- 绝不因"库内无据"定罪：错误锚定比无锚定更危险，unverified 放行但留痕。
"""

from __future__ import annotations

import json
from typing import Any

from . import prompts

MAX_CLAIMS = 6
UNANCHORED_NOTE = (
    "（知识库锚定未达成：检索无命中或共识卡不足以支撑命题，"
    "本轮主流共识为模型自带知识，未锚定知识库，事实性陈述需人工复核）"
)

_VERDICTS = {"consistent", "contradicted", "unverified"}


def _json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def _normalize_terms(terms) -> list[str]:
    """机械形状约束：去空白、去重（大小写不敏感）、截断。所有 LLM 产出的检索词
    （parser 的 keywords / 改写器的 query_terms / 核查员的 terms）统一过这里——
    模型负责语义，代码负责形状；检索词是外部输入，绝不进入 SQL。"""
    out: list[str] = []
    seen: set[str] = set()
    for t in terms or []:
        t = str(t).strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:10]


def anchor(topic: str, keywords: list[str], store, llm,
           *, kb_context: str = "", max_rounds: int = 2) -> tuple[str, bool, list[dict]]:
    """出题前的知识锚定环。返回 (context, anchored, trace)。

    trace 记录每轮的检索词/命中数/充分性判定，随答案卡入库——锚定过程可解释、可评测。
    改写器若返回与已试过的检索词相同的集合（模型没招了），提前终止，不烧剩余轮次。
    """
    if store is None:
        return (kb_context or UNANCHORED_NOTE), False, [
            {"round": 0, "terms": [], "hits": 0, "note": "无知识库，跳过锚定"}]

    trace: list[dict] = []
    tried: list[frozenset] = []
    terms = _normalize_terms(keywords)
    for rnd in range(1, max_rounds + 1):
        tried.append(frozenset(t.lower() for t in terms))
        hits = store.search_cards(terms)
        entry: dict[str, Any] = {"round": rnd, "terms": terms, "hits": len(hits)}
        if hits:
            verdict = _judge_sufficiency(topic, hits, llm)
            entry["sufficient"] = verdict["sufficient"]
            entry["reason"] = verdict["reason"]
            trace.append(entry)
            if verdict["sufficient"]:
                lines = [f"- [{h['date']}] {h['topic']}：{h['mainstream_claim']}（{h['source']}）"
                         for h in hits]
                return "主流共识检索结果：\n" + "\n".join(lines), True, trace
        else:
            trace.append(entry)
        if rnd < max_rounds:
            terms = _normalize_terms(_rewrite_query(topic, keywords, trace, llm))
            if frozenset(t.lower() for t in terms) in tried:
                trace.append({"round": rnd, "terms": terms, "hits": 0,
                              "note": "改写无新词，终止而非空转"})
                break
    return UNANCHORED_NOTE, False, trace


def fact_check(article: str, store, llm, *, max_claims: int = MAX_CLAIMS) -> dict[str, Any]:
    """M1 事实核查门：谬误是故意的，事实是无辜的。

    结论三值：consistent（与共识一致）/ contradicted（与共识冲突，验收门拦截）/
    unverified（库内无据，放行但留痕）。无据不定罪。
    """
    extract = _json(llm.complete(
        prompts.load("factcheck_extract.md").format(article=article, max_claims=max_claims),
        "", tier="small"))
    claims = [c for c in extract.get("claims", []) if c.get("text")][:max_claims]

    verdicts: dict[str, dict[str, Any]] = {}
    to_verify: list[dict] = []
    for c in claims:
        terms = _normalize_terms(c.get("terms"))[:8]
        hits = store.search_cards(terms) if terms else []
        if hits:
            to_verify.append({"id": str(c["id"]), "text": c["text"],
                              "cards": [{"claim": h["mainstream_claim"], "date": h["date"]}
                                        for h in hits[:3]]})
        else:
            verdicts[str(c["id"])] = {"text": c["text"], "verdict": "unverified",
                                      "note": "知识库无相关依据"}

    if to_verify:
        out = _json(llm.complete(
            prompts.load("factcheck_verify.md").format(claims=json.dumps(to_verify, ensure_ascii=False)),
            "", tier="small"))
        raw = out.get("verdicts", {})
        notes = out.get("notes", {})
        for item in to_verify:
            v = raw.get(item["id"], "unverified")
            if v not in _VERDICTS:
                v = "unverified"
            verdicts[item["id"]] = {"text": item["text"], "verdict": v,
                                    "note": notes.get(item["id"], "")}

    return {
        "checked": len(verdicts),
        "consistent": sorted(k for k, v in verdicts.items() if v["verdict"] == "consistent"),
        "contradicted": [v for v in verdicts.values() if v["verdict"] == "contradicted"],
        "unverified": sorted(k for k, v in verdicts.items() if v["verdict"] == "unverified"),
    }


def _rewrite_query(topic: str, keywords: list[str], trace: list[dict], llm) -> list[str]:
    """观察（检索轨迹）→ 改写（下一步动作）：agent 环里模型唯一的行动决策点之一。"""
    out = _json(llm.complete(
        prompts.load("query_rewriter.md").format(
            topic=topic, keywords=json.dumps(keywords, ensure_ascii=False),
            trace=json.dumps(trace, ensure_ascii=False)),
        "", tier="small"))
    return [str(t) for t in (out.get("query_terms") or [])] or list(keywords)


def _judge_sufficiency(topic: str, hits: list[dict], llm) -> dict[str, Any]:
    out = _json(llm.complete(
        prompts.load("anchor_judge.md").format(
            topic=topic,
            cards=json.dumps([{"topic": h["topic"], "claim": h["mainstream_claim"],
                               "date": h["date"]} for h in hits], ensure_ascii=False)),
        "", tier="small"))
    return {"sufficient": bool(out.get("sufficient")), "reason": str(out.get("reason", ""))}
