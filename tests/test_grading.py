from gym.grading import _ratio, match_positions
from gym.schema import AnswerKey, FallacyItem, UserMark


def _key(distractors=None):
    return AnswerKey(mode="M1", topic="t", article="正文",
                     items=[FallacyItem(1, "false_cause", "因此所有成瘾行为都源于多巴胺", "相关非因果", "L1", 2),
                            FallacyItem(2, "hasty_generalization", "可见运动足以戒除任何成瘾", "幸存者样本", "L1", 4)],
                     distractors=distractors or [])


def test_exact_quote_matches():
    out = match_positions(_key(), [UserMark("因此所有成瘾行为都源于多巴胺", "相关说成因果")])
    assert 1 in out["key_hits"] and out["missed"] == [2]


def test_partial_quote_matches_by_containment():
    out = match_positions(_key(), [UserMark("成瘾行为都源于多巴胺", "")])
    assert 1 in out["key_hits"]


def test_distractor_mark_is_false_positive():
    key = _key(distractors=["戒断症状在停止使用后数日内出现"])
    out = match_positions(key, [UserMark("戒断症状在停止使用后数日内出现", "这个数据可疑")])
    assert out["false_positives"] and not out["arbitrated"]


def test_unrelated_mark_is_arbitrated():
    out = match_positions(_key(), [UserMark("成瘾不过是意志力问题", "这句太绝对")])
    assert out["arbitrated"] and not out["false_positives"]


def test_ratio_containment_rule():
    assert _ratio("运动足以戒除任何成瘾", "可见运动足以戒除任何成瘾") == 1.0
    assert _ratio("", "abc") == 0.0
