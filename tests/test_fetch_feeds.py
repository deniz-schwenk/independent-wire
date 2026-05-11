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
