"""Tests for scripts/fetch_feeds.py — published_at persistence on RSS and
GDELT findings (activates source-cap recency-tiebreak per
TASK-FETCH-FEEDS-PUBLISHED-AT)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def fetch_feeds_module():
    """Load scripts/fetch_feeds.py as a module (it's a script, not a package)."""
    spec = importlib.util.spec_from_file_location(
        "fetch_feeds", ROOT / "scripts" / "fetch_feeds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_feeds"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# RSS path
# ---------------------------------------------------------------------------


def _rss_xml(pub_date: str | None = "Mon, 11 May 2026 10:00:00 GMT") -> str:
    """Build a minimal RSS feed with one entry. pub_date=None omits the
    <pubDate> tag entirely."""
    pub_line = f"<pubDate>{pub_date}</pubDate>" if pub_date else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>India and New Zealand sign free trade agreement</title>
      <link>https://reuters.example/india-nz</link>
      <description>Trade deal coverage.</description>
      {pub_line}
    </item>
  </channel>
</rss>"""


def test_parse_rss_entries_persists_published_at_iso(fetch_feeds_module):
    """RSS entry with a <pubDate> → output dict carries published_at as
    ISO-8601 string with timezone."""
    feed = feedparser.parse(_rss_xml("Mon, 11 May 2026 10:00:00 GMT"))
    cutoff = datetime(2026, 5, 1, tzinfo=timezone.utc)
    source = {"name": "Reuters", "language": "en", "region": "Global"}

    entries = fetch_feeds_module.parse_rss_entries(feed, source, cutoff)

    assert len(entries) == 1
    pub = entries[0]["published_at"]
    assert pub is not None
    # ISO-8601 with timezone offset.
    assert pub.startswith("2026-05-11T10:00:00")
    assert pub.endswith("+00:00") or pub.endswith("Z")
    # Round-trips back to a datetime.
    parsed = datetime.fromisoformat(pub.replace("Z", "+00:00"))
    assert parsed == datetime(2026, 5, 11, 10, 0, 0, tzinfo=timezone.utc)


def test_parse_rss_entries_emits_null_when_pubdate_missing(fetch_feeds_module):
    """RSS entry without a <pubDate> → published_at is explicit None,
    not a missing key (selector contract: null, not omit)."""
    feed = feedparser.parse(_rss_xml(pub_date=None))
    # Cutoff far in the past so the no-date entry isn't filtered.
    cutoff = datetime(2000, 1, 1, tzinfo=timezone.utc)
    source = {"name": "Reuters", "language": "en", "region": "Global"}

    entries = fetch_feeds_module.parse_rss_entries(feed, source, cutoff)

    assert len(entries) == 1
    assert "published_at" in entries[0]  # explicit key
    assert entries[0]["published_at"] is None


# ---------------------------------------------------------------------------
# GDELT path (seendate parser, the unit underneath fetch_gdelt)
# ---------------------------------------------------------------------------


def test_parse_gdelt_seendate_valid(fetch_feeds_module):
    """GDELT's compact YYYYMMDDTHHMMSSZ → ISO-8601 UTC string."""
    out = fetch_feeds_module._parse_gdelt_seendate("20260511T103000Z")
    assert out is not None
    parsed = datetime.fromisoformat(out)
    assert parsed == datetime(2026, 5, 11, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_gdelt_seendate_empty_or_malformed(fetch_feeds_module):
    """Empty / unparseable seendate → None (selector contract)."""
    assert fetch_feeds_module._parse_gdelt_seendate("") is None
    assert fetch_feeds_module._parse_gdelt_seendate("not-a-date") is None
    assert fetch_feeds_module._parse_gdelt_seendate(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Canonical-URL dedup + merge policy (TASK-SOURCE-URL-DEDUP)
# ---------------------------------------------------------------------------


def _finding(title: str, url: str, **extra) -> dict:
    return {"title": title, "source_url": url, "source_name": "Al Jazeera", **extra}


# The published tp-2026-07-14-001 leak: same article, one URL carries
# ?traffic_source=rss (src-026) and the other does not (src-033).
_REPRO_TRACKING = (
    "https://www.aljazeera.com/news/2026/7/13/trump-says-us-will-become-"
    "guardian-of-strait-of-hormuz-and-collect-tolls?traffic_source=rss"
)
_REPRO_CLEAN = (
    "https://www.aljazeera.com/news/2026/7/13/trump-says-us-will-become-"
    "guardian-of-strait-of-hormuz-and-collect-tolls"
)


def test_deduplicate_collapses_reproducer_pair(fetch_feeds_module):
    """The 2026-07-14 reproducer pair collapses to one record through the
    in-run dedup function; the first in ingestion order survives."""
    findings = [
        _finding("Trump on Hormuz", _REPRO_TRACKING),
        _finding("Trump on Hormuz", _REPRO_CLEAN),
    ]
    out = fetch_feeds_module.deduplicate(findings)
    assert len(out) == 1
    # First in ingestion order wins → original (tracking) URL retained verbatim.
    assert out[0]["source_url"] == _REPRO_TRACKING


def test_deduplicate_keeps_distinct_articles(fetch_feeds_module):
    """No behavior change for genuinely different URLs (different article key)."""
    findings = [
        _finding("A", "https://h.example/story?id=1"),
        _finding("B", "https://h.example/story?id=2"),
    ]
    assert len(fetch_feeds_module.deduplicate(findings)) == 2


def test_deduplicate_keeps_urlless_findings(fetch_feeds_module):
    """URL-less findings are never deduped (each kept)."""
    findings = [_finding("A", ""), _finding("B", "")]
    assert len(fetch_feeds_module.deduplicate(findings)) == 2


def test_merge_append_earliest_first_seen_wins_original_url_retained(fetch_feeds_module):
    """Merge policy: the clean URL enters first (earliest first_seen); a later
    collector window carrying the tracking-param variant collapses onto it —
    the earliest record survives with its ORIGINAL url and first_seen."""
    iso1 = "2026-07-14T06:00:00+00:00"
    iso2 = "2026-07-14T10:00:00+00:00"
    existing, _ = fetch_feeds_module.merge_append(
        [], [_finding("Trump on Hormuz", _REPRO_CLEAN)], iso1
    )
    assert existing[0]["first_seen"] == iso1

    merged, appended = fetch_feeds_module.merge_append(
        existing, [_finding("Trump on Hormuz", _REPRO_TRACKING)], iso2
    )
    assert appended == 0  # tracking variant recognized as a duplicate
    assert len(merged) == 1
    assert merged[0]["source_url"] == _REPRO_CLEAN  # original of the survivor
    assert merged[0]["first_seen"] == iso1  # earliest stamp preserved


def test_store_identity_matches_across_tracking_variants(fetch_feeds_module):
    """The store dedup identity is stable across a tracking-param variant."""
    a = fetch_feeds_module._store_identity(_finding("x", _REPRO_TRACKING))
    b = fetch_feeds_module._store_identity(_finding("x", _REPRO_CLEAN))
    assert a == b
