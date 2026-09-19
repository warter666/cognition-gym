"""SQLite 存储：错题本、答案卡（用户不可见）、知识库热度卡。

MVP 单文件库；错题本支撑两个个性化机制（PLAN.md §4）：
1. 弱项复现：percent<60 的类型进弱项池，出题时偏好注入生成节点
2. 间隔重复：弱项类型 3 天后到期复现，连续 2 次 ≥80% 移出弱项池
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at REAL, state_json TEXT);
CREATE TABLE IF NOT EXISTS answer_keys(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER, mode TEXT,
  article TEXT, key_json TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS mistake_book(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, topic TEXT,
  fallacy_type TEXT, percent INTEGER, date TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS kb_cards(
  id INTEGER PRIMARY KEY AUTOINCREMENT, field TEXT, topic TEXT,
  mainstream_claim TEXT, keywords TEXT, date TEXT, source TEXT,
  distortion_potential TEXT, dedup_key TEXT UNIQUE, ts REAL);
CREATE INDEX IF NOT EXISTS idx_mistake_user ON mistake_book(user_id, fallacy_type);
"""

REVIEW_INTERVAL_DAYS = 3
EXIT_WEAK_POOL_PERCENT = 80


class Store:
    def __init__(self, path: str | Path = "gym.db") -> None:
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ---- 错题本 ----

    def add_mistake(self, user_id: str, topic: str, fallacy_type: str,
                    percent: int, date: str) -> None:
        self.conn.execute(
            "INSERT INTO mistake_book(user_id, topic, fallacy_type, percent, date, ts)"
            " VALUES(?,?,?,?,?,?)", (user_id, topic, fallacy_type, percent, date, time.time()))
        self.conn.commit()

    def weak_types(self, user_id: str, below: int = 60) -> list[str]:
        """弱项池：类型最好成绩 <60 分。"""
        rows = self.conn.execute(
            "SELECT fallacy_type, MAX(percent) FROM mistake_book"
            " WHERE user_id=? GROUP BY fallacy_type", (user_id,)).fetchall()
        return [t for t, best in rows if best < below]

    def due_review_types(self, user_id: str, now: float | None = None) -> list[str]:
        """间隔重复：弱项类型距上次作答 ≥3 天后到期复现。"""
        now = now or time.time()
        rows = self.conn.execute(
            "SELECT fallacy_type, MAX(ts) FROM mistake_book WHERE user_id=?"
            " GROUP BY fallacy_type", (user_id,)).fetchall()
        due = []
        for ftype, last_ts in rows:
            best = self.conn.execute(
                "SELECT MAX(percent) FROM mistake_book WHERE user_id=? AND fallacy_type=?",
                (user_id, ftype)).fetchone()[0]
            if best is not None and best >= EXIT_WEAK_POOL_PERCENT:
                continue  # 连续达标移出弱项池
            if now - last_ts >= REVIEW_INTERVAL_DAYS * 86400:
                due.append(ftype)
        return due

    # ---- 答案卡（保密存库） ----

    def save_answer_key(self, session_id: int, key: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO answer_keys(session_id, mode, article, key_json, created_at)"
            " VALUES(?,?,?,?,?)",
            (session_id, key.get("mode", "M1"), key.get("article", ""),
             json.dumps(key, ensure_ascii=False), time.time()))
        self.conn.commit()

    # ---- 知识库热度卡 ----

    def upsert_cards(self, cards: list[dict[str, Any]]) -> int:
        """按 dedup_key 增量入库，返回新增条数。"""
        added = 0
        for c in cards:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO kb_cards(field, topic, mainstream_claim, keywords,"
                " date, source, distortion_potential, dedup_key, ts)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (c.get("field", ""), c.get("topic", ""), c.get("mainstream_claim", ""),
                 json.dumps(c.get("keywords", []), ensure_ascii=False), c.get("date", ""),
                 c.get("source", ""), c.get("distortion_potential", "low"),
                 c.get("dedup_key", ""), time.time()))
            added += cur.rowcount
        self.conn.commit()
        return added

    def search_cards(self, keywords: list[str], limit: int = 10) -> list[dict[str, Any]]:
        """关键词检索（grep 优先策略）；命中按时间衰减排序输出。"""
        hits: list[tuple[float, dict[str, Any]]] = []
        for field, topic, claim, kw_json, date, source, potential, dkey, ts in self.conn.execute(
                "SELECT field, topic, mainstream_claim, keywords, date, source,"
                " distortion_potential, dedup_key, ts FROM kb_cards"):
            text = f"{field} {topic} {claim} {kw_json}".lower()
            if any(k.lower() in text for k in keywords):
                days = max(0.0, (time.time() - ts) / 86400.0)
                hits.append((1.0 / (1.0 + days / 30.0), {
                    "field": field, "topic": topic, "mainstream_claim": claim,
                    "keywords": json.loads(kw_json), "date": date, "source": source,
                    "distortion_potential": potential, "dedup_key": dkey, "ts": ts}))
        hits.sort(key=lambda x: -x[0])
        return [h[1] for h in hits[:limit]]

    def field_freq(self) -> dict[str, int]:
        return dict(self.conn.execute(
            "SELECT field, COUNT(*) FROM kb_cards GROUP BY field").fetchall())
