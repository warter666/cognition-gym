"""评测（W3）：边界合规检查 + 批改一致性 kappa + 评测运行器。

自动化优先（PLAN.md §5）：
- 答案卡可批改性：taxonomy.validate_answer_key（代码断言，生成路径已强制）
- 边界合规：先规则启发（水印/医疗金融词表），live 模式再叠加 LLM judge
- 批改一致性：cohen_kappa(engine, human)，≥0.7 才允许提示词上线
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from . import prompts

# 医疗/金融可操作建议的启发词表（误报可接受，漏报由 LLM judge 兜底）
RISKY_TERMS = ["买入", "卖出", "加仓", "清仓", "停药", "加药", "剂量", "确诊", "处方", "稳赚"]


def check_boundary(output_text: str) -> list[str]:
    """规则启发检查，返回问题列表（空=通过）。"""
    problems = []
    if not any(m in output_text for m in ("请勿外传", "请以原文为准")):
        problems.append("缺少训练水印")
    hits = [t for t in RISKY_TERMS if t in output_text]
    if hits:
        problems.append(f"疑似高风险可操作建议词汇：{hits}")
    return problems


def cohen_kappa(ratings_a: list, ratings_b: list) -> float:
    """Cohen's kappa，支持任意离散标签。"""
    if len(ratings_a) != len(ratings_b) or not ratings_a:
        raise ValueError("两组标注必须等长且非空")
    labels = set(ratings_a) | set(ratings_b)
    n = len(ratings_a)
    po = sum(1 for a, b in zip(ratings_a, ratings_b) if a == b) / n
    ca, cb = Counter(ratings_a), Counter(ratings_b)
    pe = sum(ca[l] * cb[l] for l in labels) / (n * n)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def eval_generation(llm, topics: list[dict[str, str]], mode: str = "M1") -> dict[str, Any]:
    """live 评测：逐题生成 → 答案卡断言 → 边界合规。输出报告。"""
    from .session import TrainingSession  # 延迟导入避免环

    results = []
    for t in topics:
        session = TrainingSession(llm)
        try:
            presented = session.start(t["topic"], mode=mode, source_text=t.get("source_text"))
            results.append({"topic": t["topic"], "ok": True,
                            "boundary": check_boundary(presented)})
        except Exception as e:  # 评测要收集失败而非中断
            results.append({"topic": t["topic"], "ok": False, "error": str(e)})
    passed = sum(1 for r in results if r["ok"] and not r["boundary"])
    return {"mode": mode, "total": len(results), "passed": passed,
            "pass_rate": round(passed / len(results), 3) if results else 0.0,
            "results": results}


def eval_retrieval(store, golden: dict, k: int | None = None) -> dict[str, Any]:
    """检索质量回归：黄金集上算 recall@k 与 MRR（RAG失效与工业落地.md §五）。

    golden = {"k": 5, "cases": [{"keywords": [...], "relevant": ["dedup_key", ...]}]}
    门禁：recall@k < 0.8 禁止替换检索组件上线。
    """
    k = k or golden.get("k", 5)
    recalls, rrs = [], []
    for case in golden["cases"]:
        hits = store.search_cards(case["keywords"], limit=k)
        relevant = set(case["relevant"])
        got = [h["dedup_key"] for h in hits if h.get("dedup_key") in relevant]
        recalls.append(len(got) / len(relevant) if relevant else 1.0)
        rr = 0.0
        for i, h in enumerate(hits, 1):
            if h.get("dedup_key") in relevant:
                rr = 1.0 / i
                break
        rrs.append(rr)
    n = len(golden["cases"])
    recall_at_k = sum(recalls) / n if n else 0.0
    return {"k": k, "n_cases": n,
            "recall_at_k": round(recall_at_k, 3),
            "mrr": round(sum(rrs) / n, 3) if n else 0.0,
            "gate_pass": recall_at_k >= 0.8}


def eval_grading_agreement(llm, labeled: list[dict[str, Any]]) -> dict[str, Any]:
    """批改一致性：labeled = [{marks:[...], human_percent:int, article_key: {...}}]。

    用引擎批改与人工百分分各自离散为档（0-59/60-89/90-100）后算 kappa。
    """
    from .grading import assemble_grading, match_positions
    from .schema import AnswerKey, FallacyItem, UserMark

    engine, human = [], []
    for case in labeled:
        key = AnswerKey(
            mode=case.get("mode", "M1"), topic=case.get("topic", ""), article="",
            items=[FallacyItem(**it) for it in case["answer_key"]],
            distractors=case.get("distractors", []))
        marks = [UserMark(**m) for m in case["marks"]]
        matched = match_positions(key, marks)
        hit_items = [it for it in key.items if it.id in matched["key_hits"]]
        out = json.loads(llm.complete(
            prompts.load("grader.md").format(
                items=json.dumps([{"id": it.id, "type": it.type, "explanation": it.explanation}
                                  for it in hit_items], ensure_ascii=False),
                marks=json.dumps([{"quote": m.quote, "reason": m.reason} for m in
                                  [marks[matched["key_hits"][it.id][0]] for it in hit_items]],
                                 ensure_ascii=False)),
            "", tier="small"))
        judgements = {int(k): v for k, v in out.get("judgements", {}).items()}
        g = assemble_grading(key, marks, judgements)
        engine.append(_bucket(g.percent))
        human.append(_bucket(case["human_percent"]))
    return {"n": len(labeled), "kappa": round(cohen_kappa(engine, human), 3)}


def _bucket(percent: int) -> str:
    return "fail" if percent < 60 else ("partial" if percent < 90 else "full")
