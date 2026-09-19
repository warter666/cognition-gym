import time

from gym.storage import Store


def test_mistake_book_weak_pool_and_review(tmp_path):
    s = Store(tmp_path / "t.db")
    now = time.time()
    s.add_mistake("u1", "t1", "false_cause", 50, "d1")
    s.add_mistake("u1", "t2", "scope_shift", 30, "d2")
    s.add_mistake("u1", "t3", "survivorship", 85, "d3")  # 达标，永不进弱项池
    assert set(s.weak_types("u1")) == {"false_cause", "scope_shift"}

    # 刚作答不到 3 天 → 无到期
    assert s.due_review_types("u1", now=now) == []
    # 手工把时间戳拨回 4 天前 → 弱项到期，达标类型仍被排除
    s.conn.execute("UPDATE mistake_book SET ts=? WHERE user_id='u1'", (now - 4 * 86400,))
    s.conn.commit()
    assert set(s.due_review_types("u1", now=now)) == {"false_cause", "scope_shift"}


def test_weak_pool_exits_after_two_good_scores(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_mistake("u1", "t", "false_cause", 50, "d1")
    s.add_mistake("u1", "t", "false_cause", 85, "d2")  # best=85 ≥80 → 出池
    assert s.weak_types("u1") == []
    assert s.due_review_types("u1") == []


def test_answer_key_store_roundtrip(tmp_path):
    s = Store(tmp_path / "t.db")
    s.save_answer_key(1, {"mode": "M1", "article": "正文", "answer_key": []})
    row = s.conn.execute("SELECT mode, key_json FROM answer_keys WHERE session_id=1").fetchone()
    assert row[0] == "M1"


def test_kb_cards_dedup_and_search(tmp_path):
    s = Store(tmp_path / "t.db")
    card = {"field": "神经科学", "topic": "睡眠与记忆", "mainstream_claim": "因果证据增强",
            "keywords": ["睡眠"], "date": "2026-09-15", "source": "Nature",
            "distortion_potential": "high", "dedup_key": "k1"}
    assert s.upsert_cards([card, dict(card)]) == 1  # dedup_key 相同只入一条
    hits = s.search_cards(["睡眠"])
    assert hits and hits[0]["source"] == "Nature"
    assert s.search_cards(["量子引力"]) == []
    assert s.field_freq() == {"神经科学": 1}
