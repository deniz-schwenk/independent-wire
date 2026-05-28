"""Tests for ``propagate_outlet_metadata`` topic-stage.

Post 2026-05-29 migration: the stage reads outlet metadata from
``config/outlet_registry.json`` keyed by hostname (via
:func:`src.outlet_registry.lookup_outlet`), not from
``config/sources.json`` by outlet display name. Tests pin the new
URL-based contract.

Contract:

- Source whose ``url`` resolves to a registry entry with non-empty
  tier/editorial_independence/bias_note: those three fields are copied
  onto the source record.
- Source whose ``url`` resolves to a registry entry carrying only
  country/language/type (no Phase 2 web-search classifications applied):
  the three fields default to ``None``.
- Source whose hostname is unknown to the registry: the three fields
  default to ``None``.
- Source missing or with non-string ``url``: safe, fields default to
  ``None``.
"""

from __future__ import annotations

import asyncio

import pytest

from src.bus import RunBus, TopicBus
from src import outlet_registry
from src.stage import get_stage_meta
from src.stages.topic_stages import propagate_outlet_metadata


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


@pytest.fixture(autouse=True)
def _reset_registry_cache():
    # Force a fresh registry load per test so a test that patches
    # `_load_registry` cannot leak into the next.
    outlet_registry._load_registry.cache_clear()
    outlet_registry.reset_miss_cache()
    yield
    outlet_registry._load_registry.cache_clear()
    outlet_registry.reset_miss_cache()


def _patch_registry(monkeypatch, entries: dict[str, dict]) -> None:
    """Replace the cached registry with the supplied hostname → entry dict.

    Uses ``_load_registry.cache_clear`` + a monkey patch of the underlying
    function so ``lookup_outlet`` consults our fixture instead of disk.
    """
    outlet_registry._load_registry.cache_clear()
    monkeypatch.setattr(outlet_registry, "_load_registry", lambda: entries)


def test_propagate_outlet_metadata_metadata():
    meta = get_stage_meta(propagate_outlet_metadata)
    assert meta.kind == "topic"
    assert meta.reads == ("final_sources",)
    assert meta.writes == ("final_sources",)


def test_match_populates_three_fields(monkeypatch):
    """A source whose URL resolves to a registry entry with the three
    classification fields gets all three copied onto its record."""
    _patch_registry(
        monkeypatch,
        {
            "aljazeera.com": {
                "outlet": "Al Jazeera",
                "country": "Qatar",
                "language": "en",
                "type": "broadcaster",
                "tier": 2,
                "editorial_independence": "publicly_funded_autonomous",
                "bias_note": "Qatar-funded, strong Global South coverage",
            },
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "url": "https://www.aljazeera.com/news/2026/5/28/article.html",
            "outlet": "Al Jazeera",
            "title": "T",
            "country": "Qatar",
        },
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    s = tb_after.final_sources[0]
    assert s["tier"] == 2
    assert s["editorial_independence"] == "publicly_funded_autonomous"
    assert s["bias_note"] == "Qatar-funded, strong Global South coverage"


def test_no_match_leaves_fields_none(monkeypatch):
    """A URL whose hostname is unknown to the registry produces the
    three fields at None — explicitly set, not omitted, so the rendered
    TP shape is consistent."""
    _patch_registry(
        monkeypatch,
        {
            "aljazeera.com": {
                "outlet": "Al Jazeera",
                "tier": 2,
                "editorial_independence": "publicly_funded_autonomous",
                "bias_note": "Qatar-funded",
            },
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "url": "https://some-researcher-hydrated-site.example/article",
            "outlet": "Some Researcher Hydrated Site",
            "title": "T",
        },
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    s = tb_after.final_sources[0]
    assert s["tier"] is None
    assert s["editorial_independence"] is None
    assert s["bias_note"] is None


def test_registry_hit_without_classification_fields_yields_none(monkeypatch):
    """A registry entry carrying only outlet/country/language/type (no
    Phase 2 classification yet) does NOT populate tier/independence/
    bias_note — they stay None. This pins the contract that an entry
    must opt in to the classification fields explicitly."""
    _patch_registry(
        monkeypatch,
        {
            "cnn.com": {
                "outlet": "CNN",
                "country": "United States",
                "language": "en",
                "type": "broadcaster",
            },
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "url": "https://www.cnn.com/2026/05/28/news.html",
            "outlet": "CNN",
        },
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    s = tb_after.final_sources[0]
    assert s["tier"] is None
    assert s["editorial_independence"] is None
    assert s["bias_note"] is None


def test_source_without_url_field_is_safe(monkeypatch):
    """A source dict missing the `url` field (or carrying a non-string
    url) should not crash the stage — fields default to None."""
    _patch_registry(
        monkeypatch,
        {
            "aljazeera.com": {
                "tier": 2,
                "editorial_independence": "x",
                "bias_note": "y",
            },
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "title": "no url field"},
        {"id": "src-002", "url": None, "title": "non-string url"},
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    for s in tb_after.final_sources:
        assert s["editorial_independence"] is None
        assert s["bias_note"] is None
        assert s["tier"] is None


def test_mixed_batch_some_match_some_not(monkeypatch):
    """Mixed batch: matched sources carry registry meta, unmatched stay
    at None, regardless of how the per-source ``outlet`` field reads."""
    _patch_registry(
        monkeypatch,
        {
            "aljazeera.com": {
                "outlet": "Al Jazeera",
                "tier": 2,
                "editorial_independence": "publicly_funded_autonomous",
                "bias_note": "Qatar-funded",
            },
            "aa.com.tr": {
                "outlet": "Anadolu Agency",
                "tier": 2,
                "editorial_independence": "state_influenced",
                "bias_note": "Turkish state news agency",
            },
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "url": "https://aljazeera.com/x", "outlet": "Al Jazeera"},
        {"id": "src-002", "url": "https://www.lefigaro.fr/y", "outlet": "Le Figaro"},
        {"id": "src-003", "url": "https://aa.com.tr/z", "outlet": "Anadolu Agency"},
        {"id": "src-004", "url": "https://yenisafak.com/k", "outlet": "Yeni Şafak"},
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    by_id = {s["id"]: s for s in tb_after.final_sources}
    assert by_id["src-001"]["editorial_independence"] == "publicly_funded_autonomous"
    assert by_id["src-002"]["editorial_independence"] is None
    assert by_id["src-003"]["editorial_independence"] == "state_influenced"
    assert by_id["src-004"]["editorial_independence"] is None


def test_empty_final_sources_is_no_op(monkeypatch):
    _patch_registry(monkeypatch, {})
    tb = TopicBus()
    tb.final_sources = []
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    assert tb_after.final_sources == []


def test_parent_domain_fallback_picks_up_subdomain_url(monkeypatch):
    """lookup_outlet falls back from a subdomain to the parent. A
    source URL on a subdomain (e.g., world.huanqiu.com) inherits the
    parent-domain registry entry (huanqiu.com)."""
    _patch_registry(
        monkeypatch,
        {
            "huanqiu.com": {
                "outlet": "Huanqiu",
                "tier": 3,
                "editorial_independence": "state_directed",
                "bias_note": "Chinese state media",
            },
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "url": "https://world.huanqiu.com/article/123", "outlet": "Huanqiu"},
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    s = tb_after.final_sources[0]
    assert s["editorial_independence"] == "state_directed"
    assert s["bias_note"] == "Chinese state media"


def test_lookup_hits_real_registry():
    """Smoke against the real config/outlet_registry.json: at least
    Al Jazeera (aljazeera.com) has the migrated classification fields
    and yields the documented vocabulary."""
    from src.outlet_registry import lookup_outlet
    entry = lookup_outlet("https://www.aljazeera.com/news/x")
    assert entry is not None
    assert entry.get("editorial_independence") in {
        "independent", "publicly_funded_autonomous",
        "state_directed", "state_influenced",
    }
    assert entry.get("tier") in {1, 2, 3, 4}
