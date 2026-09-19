"""策展管线（W5）：RSS/Atom 抓取 → 热度卡抽取（小模型）→ 去重入库。

解析用 stdlib xml.etree，不引入 feedparser 依赖；入库走 Store.upsert_cards 的 dedup_key。
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from . import prompts

MAX_FEED_BYTES = 2 * 1024 * 1024  # 2MB 上限，防资源耗尽


def _parse_date(text: str) -> str:
    """RSS 的 RFC822 与 Atom 的 ISO8601 日期统一为 YYYY-MM-DD。"""
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return text[:10]


def parse_feed(xml_text: str) -> list[dict[str, str]]:
    """RSS 2.0 / Atom 最小解析。字段：title/summary/date/link。"""
    if len(xml_text.encode()) > MAX_FEED_BYTES:
        raise ValueError("feed 超过 2MB 上限，拒绝解析")
    # stdlib ElementTree 不禁用内部 DTD 实体，先拒绝（防实体扩展炸弹）
    head = xml_text[:65536]
    if re.search(r"<!DOCTYPE|<!ENTITY", head, re.IGNORECASE):
        raise ValueError("feed 含 DOCTYPE/ENTITY 声明，拒绝解析")
    root = ET.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for item in root.iter():
        tag = item.tag.rsplit("}", 1)[-1]
        if tag not in {"item", "entry"}:
            continue
        entry: dict[str, str] = {}
        for child in item:
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "title" and child.text:
                entry["title"] = child.text.strip()
            elif ctag in {"description", "summary"} and child.text and "summary" not in entry:
                entry["summary"] = re.sub(r"<[^>]+>", "", child.text).strip()[:500]
            elif ctag in {"pubDate", "published", "updated"} and child.text:
                entry["date"] = _parse_date(child.text.strip())
            elif ctag == "link":
                entry.setdefault("link", child.attrib.get("href") or (child.text or "").strip())
        if entry.get("title"):
            entry.setdefault("summary", "")
            entry.setdefault("date", "")
            entry.setdefault("link", "")
            items.append(entry)
    return items


def make_cards(entries: list[dict[str, str]], llm) -> list[dict[str, Any]]:
    """热度卡抽取（小模型）。LLM 只压缩不发挥；卡片契约见 prompts/curator.md。"""
    system = prompts.load("curator.md").format(entries=json.dumps(entries, ensure_ascii=False))
    out = json.loads(llm.complete(system, "", tier="small").strip())
    return out if isinstance(out, list) else out.get("cards", [])


def curate(store, xml_text: str, llm) -> dict[str, int]:
    entries = parse_feed(xml_text)
    cards = make_cards(entries, llm)
    added = store.upsert_cards(cards)
    return {"fetched": len(entries), "cards": len(cards), "added": added}
