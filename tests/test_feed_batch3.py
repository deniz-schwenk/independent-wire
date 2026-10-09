"""Feed batch 3 (curated) — owner decisions of 2026-10-08, pinned.

Eleven on_demand entries for fa/hi/hu/ko/ro/uk pass fresh verification
(scratch/audit/feed-batch3/) and are converted IN PLACE to the daily feed
shape: their own ``language`` and ``region``, because the fetcher reads
``source["language"]`` (default "en") and a bare access flip would tag every
item English. Same change: GDELT disabled, the BBC on_demand duplicate
(same URL, host bbc.co.uk) removed.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.fetch_feeds import load_sources

ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
FEEDS = CATALOG["feeds"]
BY_NAME = {f["name"]: f for f in FEEDS if f.get("access") == "daily"}

DAILY_SHAPE = ("name", "url", "type", "region", "language", "access", "enabled")

PICKS = {
    "Iran International": ("https://www.iranintl.com/feed", "fa", "Middle East"),
    "Donya-e-Eqtesad": ("https://donya-e-eqtesad.com/feeds", "fa", "Middle East"),
    "Tabnak": ("https://www.tabnak.ir/fa/rss/allnews", "fa", "Middle East"),
    "Aaj Tak": ("https://www.aajtak.in/rssfeeds?id=home", "hi", "South Asia"),
    "Telex": ("https://telex.hu/rss", "hu", "Europe"),
    "Maeil Business Newspaper (MK)": ("https://www.mk.co.kr/rss/30000001/", "ko", "East Asia"),
    "The Korea Economic Daily": ("https://www.hankyung.com/feed/all-news", "ko", "East Asia"),
    "HotNews": ("https://hotnews.ro/feed", "ro", "Europe"),
    "Ukrainska Pravda": ("https://www.pravda.com.ua/rss", "uk", "Europe"),
    "Radio Svoboda": ("https://www.radiosvoboda.org/api/", "uk", "Europe"),
    "ZN.UA": ("https://zn.ua/ukr/rss/full/", "uk", "Europe"),
}


def test_schema_v03_and_slice_shapes():
    assert CATALOG["version"] == "0.3"
    for f in FEEDS:
        assert f.get("access") in ("daily", "on_demand"), f["name"]
        if f["access"] == "daily":
            assert tuple(f) == DAILY_SHAPE, f["name"]       # exact mechanics shape
            assert isinstance(f["enabled"], bool) and f["language"], f["name"]


def test_no_duplicate_urls_anywhere_in_the_catalog():
    dupes = [u for u, n in Counter(f["url"] for f in FEEDS).items() if n > 1]
    assert dupes == []


def test_batch3_picks_are_daily_with_their_own_language_and_region():
    for name, (url, lang, region) in PICKS.items():
        f = BY_NAME[name]
        assert (f["url"], f["language"], f["region"]) == (url, lang, region), name
        assert f["enabled"] is True
    assert not [f for f in FEEDS if f.get("access") == "on_demand" and f["name"] in PICKS]


def test_daily_fetch_set_gains_the_six_languages_and_loses_gdelt():
    fetched = load_sources()
    names = {s["name"] for s in fetched}
    assert set(PICKS) <= names
    assert "GDELT" not in names
    langs = {s["language"] for s in fetched}
    assert {"fa", "hi", "hu", "ko", "ro", "uk"} <= langs
    assert "multi" not in langs                     # GDELT was the only "multi"
    assert all(s.get("language") for s in fetched)  # nothing falls back to "en"


def test_gdelt_disabled_not_removed():
    gdelt = [f for f in FEEDS if f["name"] == "GDELT"]
    assert len(gdelt) == 1
    assert gdelt[0]["enabled"] is False and gdelt[0]["type"] == "api"


def test_one_bbc_on_demand_entry_remains():
    bbc = [f for f in FEEDS if f["name"] == "BBC" and f.get("access") == "on_demand"]
    assert len(bbc) == 1 and bbc[0]["outlet_hostname"] == "bbc.com"
