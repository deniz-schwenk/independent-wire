"""Tests for src/url_canonical.py — the single canonical-URL dedup key shared
by ingestion dedup (fetch/collector) and the TP source-assembly safety net.

Motivating leak: tp-2026-07-14-001 shipped the same Al Jazeera article twice
(src-026 vs src-033) because one URL carried ``?traffic_source=rss``."""

from __future__ import annotations

from src.url_canonical import canonical_url


# --- tracking-param removal ------------------------------------------------


def test_traffic_source_stripped():
    assert canonical_url("https://h.example/a?traffic_source=rss") == "https://h.example/a"


def test_utm_prefix_all_variants_stripped():
    for p in ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"):
        assert canonical_url(f"https://h.example/a?{p}=x") == "https://h.example/a"
    # Uppercase prefix is matched case-insensitively.
    assert canonical_url("https://h.example/a?UTM_Source=x") == "https://h.example/a"


def test_named_trackers_stripped():
    for p in ("fbclid", "gclid", "mc_cid", "mc_eid", "ref", "cmpid"):
        assert canonical_url(f"https://h.example/a?{p}=x") == "https://h.example/a"


def test_mixed_tracking_and_real_params():
    # Real param survives; trackers around it drop; order of survivors preserved.
    got = canonical_url(
        "https://h.example/story?utm_source=x&id=42&fbclid=y&page=2&traffic_source=rss"
    )
    assert got == "https://h.example/story?id=42&page=2"


# --- preservation of real params -------------------------------------------


def test_non_blocklisted_params_preserved():
    # ?id= is the article key on many sites — must never be dropped.
    assert canonical_url("https://h.example/article?id=12345") == (
        "https://h.example/article?id=12345"
    )


def test_survivor_param_order_preserved():
    assert canonical_url("https://h.example/a?b=2&a=1&c=3") == (
        "https://h.example/a?b=2&a=1&c=3"
    )


def test_two_different_real_queries_stay_distinct():
    assert canonical_url("https://h.example/a?id=1") != canonical_url(
        "https://h.example/a?id=2"
    )


# --- casing / fragment / trailing slash ------------------------------------


def test_scheme_and_host_case_lowered():
    base = canonical_url("https://h.example/a/b")
    assert canonical_url("HTTPS://H.Example/a/b") == base


def test_fragment_stripped():
    assert canonical_url("https://h.example/a#section") == "https://h.example/a"


def test_single_trailing_slash_stripped():
    assert canonical_url("https://h.example/a/b/") == "https://h.example/a/b"


def test_www_preserved():
    # Not in scope to strip www. — a genuinely different host stays distinct.
    assert canonical_url("https://www.h.example/a") != canonical_url(
        "https://h.example/a"
    )


# --- unchanged plain URL / unusable inputs ---------------------------------


def test_plain_url_unchanged():
    url = "https://h.example/news/2026/07/16/story"
    assert canonical_url(url) == url


def test_unusable_inputs_return_none():
    assert canonical_url(None) is None
    assert canonical_url("") is None
    assert canonical_url("   ") is None
    assert canonical_url("/relative/path") is None
    assert canonical_url("just-text") is None
    assert canonical_url(12345) is None  # non-string


# --- the 2026-07-14 reproducer pair ----------------------------------------


REPRO_A = (
    "https://www.aljazeera.com/news/2026/7/13/trump-says-us-will-become-"
    "guardian-of-strait-of-hormuz-and-collect-tolls?traffic_source=rss"
)
REPRO_B = (
    "https://www.aljazeera.com/news/2026/7/13/trump-says-us-will-become-"
    "guardian-of-strait-of-hormuz-and-collect-tolls"
)


def test_reproducer_pair_collapses():
    """src-026 (?traffic_source=rss) and src-033 (clean) → one canonical key."""
    assert canonical_url(REPRO_A) == canonical_url(REPRO_B)
    assert canonical_url(REPRO_A) == REPRO_B  # clean form is the canonical key
