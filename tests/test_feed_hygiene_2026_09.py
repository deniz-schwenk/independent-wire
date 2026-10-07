"""Feed hygiene 2026-09 — owner decisions of 2026-09-24, pinned.

RT (DNS fails 30/30), Morocco World News (403 30/30), WHO (feed abandoned,
newest item ~211 days old) and Press TV (https chain broken; http items undated)
are disabled. IAEA (alive, low cadence) and Indian Express (healthy 30/30)
stay daily. Disabling is `enabled: false` only — the entry stays in the
catalog, matching the existing Al Arabiya precedent.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from scripts.fetch_feeds import load_sources

ROOT = Path(__file__).resolve().parent.parent
FEEDS = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["feeds"]
BY_NAME = {f["name"]: f for f in FEEDS}

DISABLED = ("RT", "Morocco World News", "WHO", "Press TV")
KEPT_DAILY = ("IAEA", "Indian Express")


def test_the_four_are_disabled_but_stay_in_the_catalog():
    for name in DISABLED:
        f = BY_NAME[name]
        assert f["enabled"] is False, name
        assert f["access"] == "daily", name   # not reclassified, only switched off


def test_iaea_and_indian_express_stay_enabled_daily():
    for name in KEPT_DAILY:
        f = BY_NAME[name]
        assert f["enabled"] is True, name
        assert f["access"] == "daily", name


def test_daily_fetch_set_drops_exactly_the_four():
    fetched = {s["name"] for s in load_sources()}
    assert fetched.isdisjoint(DISABLED)
    assert set(KEPT_DAILY) <= fetched


def test_no_duplicate_urls_or_names_in_the_daily_slice():
    # Scoped to `daily`, the slice this hygiene pass edits and the 06:00 run
    # fetches. The on_demand seed slice carries a pre-existing duplicate (two
    # "BBC" entries with one URL) that belongs to the registry seed review.
    daily = [f for f in FEEDS if f.get("access") == "daily"]
    urls = Counter(f["url"] for f in daily)
    names = Counter(f["name"] for f in daily)
    assert [u for u, n in urls.items() if n > 1] == []
    assert [n for n, c in names.items() if c > 1] == []


def test_daily_entries_keep_the_feed_mechanics_shape():
    required = {"name", "url", "type", "region", "language", "access", "enabled"}
    for f in FEEDS:
        if f.get("access") == "daily":
            assert required <= set(f), f["name"]
            assert isinstance(f["enabled"], bool), f["name"]
