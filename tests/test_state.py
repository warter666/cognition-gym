from gym.schema import SessionState
from gym.state import DifficultyStateMachine


def test_full_correct_raises_difficulty():
    s = SessionState()
    sm = DifficultyStateMachine()
    fused = sm.update(s, 100)
    assert not fused and s.difficulty == 50 and s.streak_fail == 0


def test_pass_band_holds_difficulty():
    s = SessionState()
    fused = DifficultyStateMachine().update(s, 70)
    assert not fused and s.difficulty == 40 and s.streak_fail == 0


def test_failures_accumulate_and_clamp():
    s = SessionState()
    sm = DifficultyStateMachine()
    for _ in range(2):
        sm.update(s, 20)
    assert s.streak_fail == 2 and s.difficulty == 0  # 40-20-20，clamp 到 0


def test_fuse_resets_to_scaffold():
    s = SessionState()
    sm = DifficultyStateMachine()
    fused = False
    for _ in range(3):
        fused = sm.update(s, 10)
    assert fused and s.difficulty == 25 and s.streak_fail == 0 and s.fused_once


def test_generation_params_by_difficulty():
    s = SessionState()
    sm = DifficultyStateMachine()
    assert sm.generation_params(s, scaffold=False)["n_fallacies"] == 3  # 40 → 中档
    s.difficulty = 90
    assert sm.generation_params(s, scaffold=False)["n_distractors"] == 2
    assert sm.generation_params(s, scaffold=True)["single_type_only"] is True
