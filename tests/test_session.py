"""全链路（MockLLM）：出题断言 → 作答 → 批改 → 状态机 → 错题本。"""

import pytest

from gym.llm import MockLLM
from gym.schema import UserMark
from gym.session import TrainingSession


@pytest.fixture()
def session():
    return TrainingSession(MockLLM())


def test_start_returns_article_with_validated_key(session):
    presented = session.start("成瘾行为的多巴胺机制")
    assert "多巴胺" in presented and "请勿外传" in presented
    assert len(session.answer_key.items) == 2
    assert session.state.round_no == 1


def test_full_correct_round(session):
    session.start("成瘾行为的多巴胺机制")
    marks = [UserMark("因此所有成瘾行为都源于多巴胺", "把相关说成因果"),
             UserMark("可见运动足以戒除任何成瘾", "幸存者样本，过度概括")]
    grading, coach, review = session.submit(marks)
    assert grading.percent == 100
    assert session.state.difficulty == 50
    assert coach and review
    assert session.mistake_book[-1]["percent"] == 100


def test_answer_key_secrecy_not_required_in_output(session):
    presented = session.start("成瘾行为的多巴胺机制")
    assert "answer_key" not in presented


def test_safety_flag_rejects(session):
    llm = MockLLM()
    original = llm.complete

    def unsafe(system, user, *, tier="small"):
        if "命题解析器" in system:
            return '{"topic":"x","field":[],"keywords":[],"safety_flag":true,"safety_reason":"金融操作建议"}'
        return original(system, user, tier=tier)

    llm.complete = unsafe
    with pytest.raises(ValueError, match="安全边界"):
        TrainingSession(llm).start("教我炒股稳赚")


def test_generation_assertion_discards_bad_output():
    """答案卡 quote 不在正文中 → 断言失败，两次重试后抛错（批改公平性硬门）。"""
    llm = MockLLM()
    original = llm.complete

    def bad_generation(system, user, *, tier="small"):
        if "对抗性知识生成器" in system:
            import json
            out = dict(original(system, user, tier=tier) and json.loads(json.dumps(_good())))
            out["article"] = out["article"].replace("因此所有成瘾行为都源于多巴胺", "（这句被改掉了）")
            return json.dumps(out, ensure_ascii=False)
        return original(system, user, tier=tier)

    llm.complete = bad_generation
    with pytest.raises(RuntimeError, match="答案卡断言"):
        TrainingSession(llm).start("成瘾行为的多巴胺机制")


def _good():
    from gym.llm import _FIXTURE_GENERATION
    import copy
    return copy.deepcopy(_FIXTURE_GENERATION)


def test_m2_full_round(tmp_path):
    from gym.storage import Store
    store = Store(tmp_path / "t.db")
    session = TrainingSession(MockLLM(), store=store)
    presented = session.start("药物 X 的抗肿瘤效果", mode="M2",
                              source_text="雄性小鼠模型中缩小 40%，尚未在临床试验中重复。")
    assert "小鼠" in presented and "请以原文为准" in presented
    assert all("原意" in it.explanation for it in session.answer_key.items)
    marks = [UserMark("由此可见，药物 X 能使人类的肿瘤体积缩小 40", "小鼠结果外推到了人类"),
             UserMark("药物 X 对人类肿瘤的疗效已经确证", "原文说尚未重复")]
    grading, _, _ = session.submit(marks)
    assert grading.percent == 100
    assert store.conn.execute("SELECT COUNT(*) FROM answer_keys").fetchone()[0] == 1
    assert store.weak_types("local") == []


def test_m2_requires_source_text():
    with pytest.raises(ValueError, match="source_text"):
        TrainingSession(MockLLM()).start("x", mode="M2")


def test_m3_deferred_to_r2():
    with pytest.raises(NotImplementedError):
        TrainingSession(MockLLM()).start("x", mode="M3")
