"""谬误分类表：唯一事实源为 data/taxonomy.json。"""

from __future__ import annotations

import json
from pathlib import Path

_DATA = Path(__file__).parent / "data" / "taxonomy.json"

with open(_DATA, encoding="utf-8") as f:
    TAXONOMY: dict = json.load(f)

CODES: set[str] = {c["code"] for c in TAXONOMY["categories"]}
NAME_BY_CODE: dict[str, str] = {c["code"]: c["name_zh"] for c in TAXONOMY["categories"]}
FORBIDDEN: list[str] = TAXONOMY["forbidden"]
WATERMARK_TEMPLATE: str = TAXONOMY["watermark_template"]


def validate_answer_key(answer_key_json: dict) -> list[str]:
    """生成物断言。返回问题列表，空列表 = 通过。

    断言是批改公平性的前提：quote 对不上正文的答案卡会让代码化批改失效。
    """
    problems: list[str] = []
    article = answer_key_json.get("article", "")
    for item in answer_key_json.get("answer_key", []):
        code = item.get("type", "")
        if code not in CODES:
            problems.append(f"谬误类型 {code!r} 不在分类表内")
        quote = item.get("quote", "")
        if quote and quote not in article:
            problems.append(f"答案卡#{item.get('id')} 的 quote 不在正文中：{quote[:30]}…")
        if item.get("severity") not in {"L1", "L2", "L3"}:
            problems.append(f"答案卡#{item.get('id')} severity 非法")
    if not answer_key_json.get("answer_key"):
        problems.append("答案卡为空")
    return problems
