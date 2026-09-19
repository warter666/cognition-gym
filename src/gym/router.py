"""热度路由：不用 LLM——可解释、零延迟、同命题结果可复现。"""

from __future__ import annotations

import math
import time
from typing import Any

T_HOT = 10.0
T_COLD = 2.0
HALF_LIFE_DAYS = 30.0


def route(
    keywords: list[str],
    kb_hits: list[dict[str, Any]],
    field_freq: dict[str, int] | None = None,
) -> dict[str, Any]:
    """kb_hits 每条含 {field, keywords_str, topic, date, ts}。

    heat = Σ 命中条目 × exp(-Δ天/半衰期)；库内无命中时退化为领域频率兜底。
    evidence 透传给前端展示"判定依据"，是可解释性的加分项。
    """
    field_freq = field_freq or {}
    kws = [k.lower() for k in keywords]
    heat = 0.0
    evidence: list[dict[str, Any]] = []
    for hit in kb_hits:
        text = f"{hit.get('field', '')} {hit.get('keywords_str', '')}".lower()
        if any(k in text for k in kws):
            days = max(0.0, (time.time() - hit["ts"]) / 86400.0)
            heat += math.exp(-days / HALF_LIFE_DAYS)
            evidence.append({"topic": hit.get("topic", ""), "date": hit.get("date", "")})

    if not evidence:
        heat = float(sum(field_freq.get(f, 0) for f in {h.get("field", "") for h in kb_hits})) * 0.3

    if heat >= T_HOT:
        r, mode = "hot", "M1"
    elif heat <= T_COLD:
        r, mode = "cold", "M3"
    else:
        r, mode = "gray", None  # 走一次 LLM 兜底，结论回写 kb_cards 供下次直接路由

    return {"route": r, "mode": mode, "heat_score": round(heat, 2), "evidence": evidence[:5]}
