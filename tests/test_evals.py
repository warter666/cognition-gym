import json
from pathlib import Path

import pytest

from gym.evals import (check_boundary, cohen_kappa, eval_generation,
                       eval_grading_agreement, eval_retrieval)
from gym.llm import MockLLM

EVALS = Path(__file__).resolve().parents[1] / "evals"


def test_kappa_perfect_and_known():
    assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == 1.0
    # po=3/5, pe=13/25 → (0.6-0.52)/0.48 = 1/6
    assert cohen_kappa(["a", "a", "b", "b", "a"], ["a", "a", "a", "b", "b"]) == pytest.approx(1 / 6)
    with pytest.raises(ValueError):
        cohen_kappa([], [])


def test_boundary_checks():
    assert check_boundary("……含训练水印，请勿外传。") == []
    assert any("水印" in p for p in check_boundary("没有水印的文本"))
    assert any("高风险" in p for p in check_boundary("请勿外传，明天加仓稳赚"))


def test_grading_agreement_mock_full_agreement():
    labeled = json.loads((EVALS / "agreement_sample.json").read_text(encoding="utf-8"))
    report = eval_grading_agreement(MockLLM(), labeled)
    assert report["n"] == 3 and report["kappa"] == 1.0


def test_generation_eval_mock_all_pass():
    topics = [{"topic": "成瘾行为的多巴胺机制", "mode": "M1"}]
    report = eval_generation(MockLLM(), topics)
    assert report["pass_rate"] == 1.0
    topics_m2 = [{"topic": "药物 X 的抗肿瘤效果", "mode": "M2", "source_text": "雄性小鼠模型中缩小 40%，尚未重复。"}]
    report_m2 = eval_generation(MockLLM(), topics_m2, mode="M2")
    assert report_m2["pass_rate"] == 1.0


def test_eval_retrieval_recall_and_mrr(tmp_path):
    from gym.llm import _FIXTURE_CARDS
    from gym.storage import Store
    store = Store(tmp_path / "t.db")
    store.upsert_cards(_FIXTURE_CARDS)
    golden = json.loads((EVALS / "retrieval_golden.json").read_text(encoding="utf-8"))
    report = eval_retrieval(store, golden)
    # 前两例全中，第三例关键词只命中 2 个相关中的 1 个 → (1+1+0.5)/3
    assert report["recall_at_k"] == pytest.approx(0.833)
    assert report["mrr"] == 1.0 and report["gate_pass"] is True


def test_eval_retrieval_empty_db_fails_gate(tmp_path):
    from gym.storage import Store
    golden = json.loads((EVALS / "retrieval_golden.json").read_text(encoding="utf-8"))
    report = eval_retrieval(Store(tmp_path / "t.db"), golden)
    assert report["recall_at_k"] == 0.0 and report["gate_pass"] is False
