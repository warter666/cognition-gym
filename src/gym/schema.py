"""数据契约：一次训练会话中流转的全部结构。"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class FallacyItem:
    """答案卡中的一处谬误记录。quote 必须能在正文中逐字找到。"""

    id: int
    type: str  # taxonomy.json 内的 code
    quote: str
    explanation: str
    severity: str  # L1 | L2 | L3
    paragraph: int


@dataclass
class AnswerKey:
    """与正文同源生成的标准答案，只存库，不给用户。"""

    mode: str  # M1 | M2 | M3
    topic: str
    article: str
    items: list[FallacyItem]
    distractors: list[str] = field(default_factory=list)
    genuine_bridges: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UserMark:
    """用户标注：摘句 + 理由。"""

    quote: str
    reason: str = ""


@dataclass
class Grading:
    """批改结果。位置分由代码判定，类型/解释分由 LLM 判定后填入。"""

    percent: int
    full_score: int
    per_item: list[dict[str, Any]]
    missed: list[int]
    false_positives: list[dict[str, Any]]
    arbitrated: list[dict[str, Any]]


@dataclass
class SessionState:
    """难度状态机会话级变量。"""

    difficulty: int = 40
    streak_fail: int = 0
    round_no: int = 0
    fused_once: bool = False
