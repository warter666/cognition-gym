"""难度状态机：确定性，判分公平性的一部分，必须有单测。"""

from __future__ import annotations

from .schema import SessionState


class DifficultyStateMachine:
    """更新规则（与 PLAN.md §6 一致）：

    percent >= 90 → 难度 +10，失败连击清零
    percent >= 60 → 维持，连击清零（及格但不涨）
    percent >= 30 → 难度 -10，连击 +1
    percent <  30 → 难度 -20，连击 +1
    连击达到 3    → 熔断：难度重置 25，进入脚手架模式一轮
    """

    FUSE_THRESHOLD = 3
    SCAFFOLD_DIFFICULTY = 25

    def update(self, state: SessionState, percent: int) -> bool:
        if percent >= 90:
            state.difficulty += 10
            state.streak_fail = 0
        elif percent >= 60:
            state.streak_fail = 0
        elif percent >= 30:
            state.difficulty -= 10
            state.streak_fail += 1
        else:
            state.difficulty -= 20
            state.streak_fail += 1

        state.difficulty = max(0, min(100, state.difficulty))
        fused = state.streak_fail >= self.FUSE_THRESHOLD
        if fused:
            state.difficulty = self.SCAFFOLD_DIFFICULTY
            state.streak_fail = 0
            state.fused_once = True
        return fused

    def generation_params(self, state: SessionState, scaffold: bool) -> dict:
        """难度 → 出题参数映射（生成节点内执行）。"""
        if scaffold:
            return {"n_fallacies": 1, "severity_pool": ["L1"], "n_distractors": 0,
                    "max_chars": 400, "single_type_only": True}
        d = state.difficulty
        if d <= 30:
            return {"n_fallacies": 1, "severity_pool": ["L1"], "n_distractors": 0, "max_chars": 500}
        if d <= 70:
            return {"n_fallacies": 3, "severity_pool": ["L1", "L2"], "n_distractors": 1, "max_chars": 900}
        return {"n_fallacies": 4, "severity_pool": ["L1", "L2", "L3"], "n_distractors": 2, "max_chars": 1100}
