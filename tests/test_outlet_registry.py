"""Tests for src/outlet_registry.py — hostname normalisation + lookup."""

from __future__ import annotations

from src.outlet_registry import _normalise_hostname, lookup_outlet, reset_miss_cache


def setup_function(_func) -> None:
    # Each test starts with a clean miss cache so log-once semantics
    # don't leak between tests.
    reset_miss_cache()


def test_normalise_hostname_strips_www_and_lowercases():
    assert _normalise_hostname("https://WWW.AlJazeera.com/news/path") == "aljazeera.com"


def test_normalise_hostname_handles_bare_host_without_scheme():
    assert _normalise_hostname("aljazeera.com/news/path") == "aljazeera.com"


def test_normalise_hostname_returns_empty_on_falsy_input():
    assert _normalise_hostname("") == ""
    assert _normalise_hostname(None) == ""  # type: ignore[arg-type]


def test_lookup_outlet_exact_hostname_hit():
    entry = lookup_outlet("https://www.aljazeera.com/news/2026/05/04/some-story")
    assert entry is not None
    assert entry["outlet"] == "Al Jazeera"
    assert entry["country"] == "Qatar"


def test_lookup_outlet_parent_domain_fallback():
    # `feeds.bbci.co.uk` is not in the registry, but `bbci.co.uk` is.
    entry = lookup_outlet("https://feeds.bbci.co.uk/news/world/rss.xml")
    assert entry is not None
    assert entry["outlet"] == "BBC"
    assert entry["country"] == "United Kingdom"


def test_lookup_outlet_returns_none_on_unknown_hostname():
    entry = lookup_outlet("https://www.example-unknown-outlet-12345.invalid/article")
    assert entry is None


def test_lookup_outlet_logs_miss_only_once_per_hostname(caplog):
    import logging

    caplog.set_level(logging.WARNING, logger="src.outlet_registry")

    lookup_outlet("https://example-unknown-outlet-12345.invalid/a")
    lookup_outlet("https://example-unknown-outlet-12345.invalid/b")
    lookup_outlet("https://example-unknown-outlet-12345.invalid/c")

    miss_records = [
        r for r in caplog.records
        if "no entry for hostname" in r.getMessage()
        and "example-unknown-outlet-12345" in r.getMessage()
    ]
    assert len(miss_records) == 1, (
        f"expected single WARNING per unknown host; got {len(miss_records)}"
    )
