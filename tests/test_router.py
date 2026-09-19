import time

from gym.router import route


def _hit(topic="t", field="神经科学", age_days=0.0):
    return {"field": field, "keywords_str": "多巴胺 成瘾 dopamine", "topic": topic,
            "date": "2026-09-01", "ts": time.time() - age_days * 86400}


def test_hot_route_with_recent_hits():
    out = route(["多巴胺"], [_hit() for _ in range(12)])
    assert out["route"] == "hot" and out["mode"] == "M1" and out["evidence"]


def test_cold_route_with_no_hits():
    out = route(["量子引力"], [_hit()], field_freq={})
    assert out["route"] == "cold" and out["mode"] == "M3" and out["heat_score"] == 0.0


def test_time_decay_lowers_heat():
    fresh = route(["多巴胺"], [_hit() for _ in range(6)], field_freq={})
    stale = route(["多巴胺"], [_hit(age_days=120) for _ in range(6)], field_freq={})
    assert fresh["heat_score"] > stale["heat_score"]


def test_same_input_same_route():
    hits = [_hit() for _ in range(8)]
    assert route(["多巴胺"], hits) == route(["多巴胺"], hits)
