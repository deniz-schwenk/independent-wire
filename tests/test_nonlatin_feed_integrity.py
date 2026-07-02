"""Non-Latin feed-integrity regressions — docs/CODE-REVIEW-2026-07-02.md.

Four defects that silently corrupt exactly the batch-1 non-Latin streams
(ar/bn/ne/th/zu/sw/uz), each with a real-encoding fixture:

  H6         hydration decode: <meta>-only windows-1256 (Arabic) / TIS-620 (Thai)
             pages must extract as legible text through the real fetch path.
  M-P4       feedparser must read the XML-prolog encoding (parse bytes).
  M-P5       an undated feed entry must not reach the Curator on consecutive days.
  Tokenizer  a non-Latin cluster title must yield a non-empty token set and
             match its own findings (else it loses every hydration URL).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import feedparser

from src.hydration import _decode, _hydrate_one, _sniff_html_charset
from src.stages.run_stages import _hydration_tokens, _match_cluster
from scripts.fetch_feeds import (
    _load_undated_seen,
    _save_undated_seen,
    _undated_fingerprint,
    fetch_rss,
    suppress_repeat_undated,
)


# --- real-encoding page fixtures (charset declared ONLY in <meta>) -----------

def _arabic_page() -> bytes:
    html = (
        '<html><head><meta charset="windows-1256"></head><body><article><p>'
        + "الأخبار العاجلة من مصر اليوم " * 10
        + "</p></article></body></html>"
    )
    return html.encode("windows-1256")


def _thai_page() -> bytes:
    html = (
        '<html><head><meta http-equiv="Content-Type" '
        'content="text/html; charset=TIS-620"></head><body><article><p>'
        + "ข่าวด่วนจากประเทศไทยวันนี้ " * 10
        + "</p></article></body></html>"
    )
    return html.encode("tis-620")


# ===========================================================================
# H6 — hydration byte-level encoding detection
# ===========================================================================

class _FakeResp:
    def __init__(self, raw: bytes, status: int = 200, charset=None, headers=None):
        self._raw = raw
        self.status = status
        self.charset = charset  # None == server sent no header charset (the bug trigger)
        self.headers = headers or {}

    async def read(self) -> bytes:
        return self._raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    """Minimal aiohttp.ClientSession stand-in: .get() -> async-CM response."""

    def __init__(self, raw: bytes, **resp_kw):
        self._raw = raw
        self._resp_kw = resp_kw

    def get(self, url, **kw):
        return _FakeResp(self._raw, **self._resp_kw)


class _FakeLimiter:
    async def acquire(self, domain):
        return None


class _FakeRobots:
    async def is_allowed(self, session, url, limiter, domain):
        return True


def _run_hydrate_one(raw: bytes, *, charset=None) -> dict:
    entry = {"url": "http://almasryalyoum.com/a", "outlet": "o",
             "language": "ar", "country": "Egypt"}
    return asyncio.run(
        _hydrate_one(
            _FakeSession(raw, charset=charset),
            entry,
            _FakeLimiter(),
            _FakeRobots(),
            partial_word_threshold=3,
        )
    )


def test_h6_arabic_meta_only_charset_decodes_through_real_path():
    """windows-1256 Arabic, charset only in <meta>, no HTTP header charset."""
    out = _run_hydrate_one(_arabic_page(), charset=None)
    assert out["status"] == "success", out
    assert "الأخبار" in out["extracted_text"]
    assert "Ç" not in out["extracted_text"]  # no latin-1 mojibake


def test_h6_thai_meta_only_charset_decodes_through_real_path():
    """TIS-620 Thai, charset only in an http-equiv <meta>."""
    out = _run_hydrate_one(_thai_page(), charset=None)
    assert out["status"] == "success", out
    assert "ข่าว" in out["extracted_text"]
    assert "¢" not in out["extracted_text"]  # no latin-1 mojibake


def test_h6_decode_sniffs_meta_charset_and_bom():
    assert _sniff_html_charset(_arabic_page()) == "windows-1256"
    assert _sniff_html_charset(_thai_page()) == "tis-620"
    assert "الأخبار" in _decode(_arabic_page(), None)
    assert "ข่าว" in _decode(_thai_page(), None)
    # BOM detection
    assert _sniff_html_charset("café".encode("utf-8-sig")) == "utf-8-sig"


def test_h6_decode_latin_unchanged():
    """Latin/utf-8 bodies decode exactly as before — no behaviour change."""
    assert _decode("Egypt votes today".encode("utf-8"), None) == "Egypt votes today"
    # An explicit HTTP header charset still wins.
    assert _decode("café".encode("latin-1"), "latin-1") == "café"


# ===========================================================================
# M-P4 — feedparser must see the XML-prolog encoding
# ===========================================================================

def _prolog_only_feed() -> bytes:
    xml = (
        '<?xml version="1.0" encoding="windows-1256"?>'
        "<rss version=\"2.0\"><channel><title>t</title>"
        "<item><title>الأخبار العاجلة</title><link>http://x/1</link></item>"
        "</channel></rss>"
    )
    return xml.encode("windows-1256")


class _FakeHttpxResp:
    def __init__(self, content: bytes):
        self.content = content
        self.text = content.decode("latin-1")  # what resp.text would (wrongly) give

    def raise_for_status(self):
        return None


class _FakeHttpxClient:
    def __init__(self, content: bytes):
        self._content = content

    async def get(self, url, **kw):
        return _FakeHttpxResp(self._content)


def test_mp4_feedparser_reads_xml_prolog_encoding_via_bytes():
    """Parsing bytes (resp.content) honours the prolog encoding; the old
    resp.text (str) path mojibakes the title."""
    raw = _prolog_only_feed()
    assert "الأخبار" not in feedparser.parse(raw.decode("latin-1")).entries[0].title
    assert "الأخبار" in feedparser.parse(raw).entries[0].title


def test_mp4_fetch_rss_decodes_prolog_only_feed():
    """Through the real fetch_rss path (which now parses resp.content)."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    source = {"name": "T", "url": "http://x", "language": "ar", "region": "Middle East"}
    entries = asyncio.run(fetch_rss(_FakeHttpxClient(_prolog_only_feed()), source, cutoff))
    assert len(entries) == 1
    assert entries[0]["title"] == "الأخبار العاجلة"


# ===========================================================================
# M-P5 — undated entries must not re-enter on consecutive days
# ===========================================================================

def _undated(url: str, title: str = "No date") -> dict:
    return {"title": title, "source_url": url, "source_name": "S", "published_at": None}


def _dated(url: str) -> dict:
    return {"title": "Dated", "source_url": url, "source_name": "S",
            "published_at": "2026-07-02T10:00:00+00:00"}


def test_mp5_same_undated_entry_reaches_curator_at_most_once():
    seen: dict[str, str] = {}
    d1_keep, d1_drop = suppress_repeat_undated([_undated("http://x/u1"), _dated("http://x/d1")],
                                               seen, "2026-07-02")
    assert {f["title"] for f in d1_keep} == {"No date", "Dated"}  # first day: undated enters
    assert d1_drop == 0

    d2_keep, d2_drop = suppress_repeat_undated([_undated("http://x/u1"), _dated("http://x/d1")],
                                               seen, "2026-07-03")
    assert [f["title"] for f in d2_keep] == ["Dated"]  # day 2: undated suppressed, dated stays
    assert d2_drop == 1


def test_mp5_new_undated_entry_may_enter_once():
    seen = {_undated_fingerprint(_undated("http://x/old")): "2026-07-02"}
    keep, drop = suppress_repeat_undated([_undated("http://x/new", "Fresh")], seen, "2026-07-03")
    assert [f["title"] for f in keep] == ["Fresh"]
    assert drop == 0


def test_mp5_retention_prunes_and_roundtrips(tmp_path):
    seen = {"stale_key": "2026-05-01", "recent_key": "2026-06-30"}
    # today 2026-07-02, retention 30d -> prune anything older than 2026-06-02
    _, _ = suppress_repeat_undated([], seen, "2026-07-02", retention_days=30)
    assert "stale_key" not in seen and "recent_key" in seen
    # persistence round-trip
    p = tmp_path / "undated_seen.json"
    _save_undated_seen(p, seen)
    assert _load_undated_seen(p) == seen
    assert _load_undated_seen(tmp_path / "missing.json") == {}


# ===========================================================================
# Tokenizer — non-Latin cluster titles yield tokens and self-match
# ===========================================================================

def test_tokenizer_arabic_title_matches_its_own_finding():
    title = "الأخبار العاجلة من مصر"
    assert len(_hydration_tokens(title)) >= 2
    best, _ = _match_cluster(title, [{"title": title, "source_ids": ["finding-0"]}])
    assert best is not None


def test_tokenizer_thai_title_matches_its_own_finding():
    title = "ข่าวด่วนจากประเทศไทย"  # unspaced script — bigrams give the >=2 overlap
    assert len(_hydration_tokens(title)) >= 2
    best, _ = _match_cluster(title, [{"title": title, "source_ids": ["finding-0"]}])
    assert best is not None


def test_tokenizer_latin_behaviour_unchanged():
    """Latin titles produce exactly the pre-fix word tokens — no bigrams,
    stopwords still dropped."""
    assert _hydration_tokens("The attack on the city") == {"attack", "city"}
    assert _hydration_tokens("Egypt election results today") == {
        "egypt", "election", "results", "today"
    }
