"""有界锚定代理：锚定环（改写→检索→充分性判定）与 M1 事实核查验收门。

覆盖四条关键性质：
1. 命中且充分 → 锚定成功，共识卡进入生成上下文
2. 无命中/不充分 → 显式"未锚定"降级（绝不静默 fallback），trace 留痕
3. 事实与库内共识矛盾 → 验收门拦截，重试后仍矛盾则丢弃（永不带病入库）
4. 库内无据 ≠ 错误 → unverified 放行但留痕（错误锚定比无锚定更危险）
"""

import json

import pytest

from gym.llm import MockLLM
from gym.session import TrainingSession
from gym.storage import Store

CARDS = [
    {"field": "神经科学", "topic": "多巴胺与奖赏回路",
     "mainstream_claim": "多巴胺参与奖赏与动机回路，但并非'快乐分子'，成瘾涉及多重神经机制",
     "keywords": ["多巴胺", "成瘾", "奖赏"], "date": "2026-09-01",
     "source": "Nature Reviews Neuroscience", "distortion_potential": "high",
     "dedup_key": "多巴胺与奖赏回路"},
    {"field": "神经科学", "topic": "戒断反应的时程",
     "mainstream_claim": "戒断症状的时程因物质与个体而异，从数日到数周不等",
     "keywords": ["戒断症状", "停用"], "date": "2026-08-20",
     "source": "WHO", "distortion_potential": "medium",
     "dedup_key": "戒断反应的时程"},
]


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "anchor.db")
    s.upsert_cards(CARDS)
    return s


def test_anchor_sufficient_returns_cards(store):
    from gym import anchoring
    ctx, anchored, trace = anchoring.anchor("多巴胺与成瘾", ["多巴胺"], store, MockLLM())
    assert anchored and "多巴胺参与奖赏" in ctx
    assert trace[-1]["sufficient"] is True
    assert trace[-1]["hits"] >= 1


def test_anchor_unanchored_when_empty_db(tmp_path):
    from gym import anchoring
    ctx, anchored, trace = anchoring.anchor(
        "量子计算", ["量子计算"], Store(tmp_path / "empty.db"), MockLLM())
    assert not anchored and "未锚定" in ctx
    assert len(trace) == 2  # 两轮检索均无命中后显式降级


def test_anchor_insufficient_after_rounds(store):
    """命中但充分性评审不通过 → 改写重试，仍不充分则显式未锚定。"""
    from gym import anchoring
    llm = MockLLM()
    original = llm.complete

    def not_enough(system, user, *, tier="small"):
        if "锚定充分性评审" in system:
            return json.dumps({"sufficient": False, "reason": "共识卡与命题偏离"}, ensure_ascii=False)
        return original(system, user, tier=tier)

    llm.complete = not_enough
    ctx, anchored, trace = anchoring.anchor("多巴胺与成瘾", ["多巴胺"], store, llm)
    assert not anchored and "未锚定" in ctx
    assert trace[0]["sufficient"] is False
    assert trace[1]["terms"] == ["多巴胺", "成瘾", "快乐分子"]  # 第二轮用了改写后的检索词


def test_anchor_stops_when_rewriter_echoes_same_terms(tmp_path):
    """改写器返回与已试过的相同检索词（模型没招了）→ 提前终止，不烧剩余轮次空转。"""
    from gym import anchoring
    llm = MockLLM()
    original = llm.complete

    def lazy_rewriter(system, user, *, tier="small"):
        if "检索查询改写器" in system:
            return json.dumps({"query_terms": [" 量子计算 ", "量子计算"]}, ensure_ascii=False)
        return original(system, user, tier=tier)

    llm.complete = lazy_rewriter
    ctx, anchored, trace = anchoring.anchor(
        "量子计算", ["量子计算"], Store(tmp_path / "empty.db"), llm)
    assert not anchored and "未锚定" in ctx
    assert trace[-1]["note"] == "改写无新词，终止而非空转"


def test_normalize_terms_strips_and_dedupes():
    """LLM 产出的检索词统一过机械形状约束：去空白、去重（大小写不敏感）、截断。"""
    from gym.anchoring import _normalize_terms
    out = _normalize_terms(["  多巴胺 ", "多巴胺", "", "Dopamine", "dopamine", "成瘾", "x" * 99])
    assert out == ["多巴胺", "Dopamine", "成瘾", "x" * 99]
    assert len(_normalize_terms([str(i) for i in range(50)])) == 10  # 截断上限
    assert _normalize_terms(None) == []


def test_full_round_with_anchor_and_factcheck(store):
    """有库 + M1：出题走锚定环，验收门含事实核查，审计随答案卡入库。"""
    session = TrainingSession(MockLLM(), store=store)
    presented = session.start("成瘾行为的多巴胺机制")
    assert "多巴胺" in presented
    row = store.conn.execute(
        "SELECT key_json FROM answer_keys ORDER BY id DESC LIMIT 1").fetchone()
    saved = json.loads(row[0])
    assert saved["anchored"] is True
    assert saved["anchor_trace"][0]["sufficient"] is True
    assert saved["fact_audit"]["checked"] == 2
    assert saved["fact_audit"]["contradicted"] == []


def test_factcheck_contradiction_discards_generation(store):
    """事实与库内共识矛盾 → 验收门拦截，重试仍矛盾则丢弃。"""
    llm = MockLLM()
    original = llm.complete

    def lying_facts(system, user, *, tier="small"):
        if "核对判定" in system:
            return json.dumps({"verdicts": {"1": "contradicted", "2": "unverified"},
                               "notes": {"1": "与 WHO 戒断时程共识冲突"}}, ensure_ascii=False)
        return original(system, user, tier=tier)

    llm.complete = lying_facts
    with pytest.raises(RuntimeError, match="事实核查矛盾"):
        TrainingSession(llm, store=store).start("成瘾行为的多巴胺机制")


def test_factcheck_unverified_is_not_a_crime(store):
    """库内无据 → 放行但留痕：无据不定罪，矛盾才拦截。"""
    llm = MockLLM()
    original = llm.complete

    def no_evidence(system, user, *, tier="small"):
        if "声明抽取" in system:
            return json.dumps({"claims": [{"id": 1, "text": "某康复项目位于加利福尼亚州",
                                           "terms": ["康复项目"]}]}, ensure_ascii=False)
        return original(system, user, tier=tier)

    llm.complete = no_evidence
    session = TrainingSession(llm, store=store)
    session.start("成瘾行为的多巴胺机制")
    row = store.conn.execute(
        "SELECT key_json FROM answer_keys ORDER BY id DESC LIMIT 1").fetchone()
    audit = json.loads(row[0])["fact_audit"]
    assert audit["unverified"] == ["1"]
    assert audit["contradicted"] == []


def test_m2_skips_anchor_and_factcheck(store):
    """M2 源文本由用户提供：不走锚定环，也不做事实核查（失真本身是刻意产物）。"""
    session = TrainingSession(MockLLM(), store=store)
    session.start("药物 X 的抗肿瘤效果", mode="M2",
                  source_text="雄性小鼠模型中缩小 40%，尚未在临床试验中重复。")
    row = store.conn.execute(
        "SELECT key_json FROM answer_keys ORDER BY id DESC LIMIT 1").fetchone()
    saved = json.loads(row[0])
    assert saved["anchored"] is True
    assert saved["anchor_trace"] == []
    assert saved["fact_audit"] is None
