import json

import pytest

from gym.curator import curate, make_cards, parse_feed
from gym.llm import MockLLM
from gym.storage import Store

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>大模型推理成本下降</title>
<description>近一月多篇论文报告推理成本较去年下降一个量级。</description>
<pubDate>Wed, 10 Sep 2026 00:00:00 GMT</pubDate>
<link>https://arxiv.org/a</link></item>
<item><title>睡眠与记忆巩固研究</title>
<summary>新研究增强因果证据。</summary>
<pubDate>Mon, 15 Sep 2026 00:00:00 GMT</pubDate>
<link>https://nature.com/b</link></item>
</channel></rss>"""


def test_parse_feed_extracts_entries():
    entries = parse_feed(RSS)
    assert len(entries) == 2
    assert entries[0]["title"] == "大模型推理成本下降"
    assert entries[0]["date"] == "2026-09-10"
    assert entries[1]["link"] == "https://nature.com/b"


def test_parse_feed_rejects_entity_bombs():
    evil = RSS.replace('<?xml version="1.0"?>',
                       '<!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>')
    with pytest.raises(ValueError, match="ENTITY"):
        parse_feed(evil)


def test_parse_feed_rejects_late_doctype():
    """DOCTYPE 藏在 64KB 之外（超长前言）也必须拒绝——头部检查可被这样绕过。"""
    padding = "<!--" + "A" * 70000 + "-->"
    evil = ('<?xml version="1.0"?>' + padding
            + '<!DOCTYPE r [<!ENTITY a "x">]>' + RSS.split("?>", 1)[1])
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_feed(evil)


def test_curate_end_to_end(tmp_path):
    store = Store(tmp_path / "t.db")
    report = curate(store, RSS, MockLLM())
    assert report["fetched"] == 2 and report["added"] == 2
    assert curate(store, RSS, MockLLM())["added"] == 0  # 重复入库被 dedup
    assert store.field_freq() == {"计算机科学": 1, "神经科学": 1}


def test_make_cards_contract():
    cards = make_cards(parse_feed(RSS), MockLLM())
    assert all({"field", "topic", "mainstream_claim", "dedup_key"} <= set(c) for c in cards)
