"""Tests for ``propagate_outlet_metadata`` topic-stage.

Covers TASK-RENDER-RESTRUCTURE-V2 Commit 0 contract:

- Outlet match copies tier / editorial_independence / bias_note onto
  the source record.
- No match leaves the three fields at ``None``.
- Mixed batch handles both correctly per source.
- Missing or non-string ``outlet`` field is defensively handled.
"""

from __future__ import annotations

import asyncio

import pytest

from src.bus import RunBus, TopicBus
from src.stage import get_stage_meta
from src.stages import topic_stages
from src.stages.topic_stages import propagate_outlet_metadata


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


@pytest.fixture(autouse=True)
def _reset_lookup_cache():
    # Force a fresh load of config/sources.json per test so a test that
    # monkeypatches the cache cannot leak into the next.
    topic_stages._OUTLET_LOOKUP_CACHE = None
    yield
    topic_stages._OUTLET_LOOKUP_CACHE = None


def test_propagate_outlet_metadata_metadata():
    meta = get_stage_meta(propagate_outlet_metadata)
    assert meta.kind == "topic"
    assert meta.reads == ("final_sources",)
    assert meta.writes == ("final_sources",)


def test_match_populates_three_fields(monkeypatch):
    """A source whose outlet matches a feed in the lookup gets all
    three fields copied onto its record."""
    monkeypatch.setattr(
        topic_stages,
        "_OUTLET_LOOKUP_CACHE",
        {
            "Al Jazeera": {
                "tier": 2,
                "editorial_independence": "publicly_funded_autonomous",
                "bias_note": "Qatar-funded, strong Global South coverage",
            },
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "Al Jazeera", "title": "T", "country": "Qatar"},
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    s = tb_after.final_sources[0]
    assert s["tier"] == 2
    assert s["editorial_independence"] == "publicly_funded_autonomous"
    assert s["bias_note"] == "Qatar-funded, strong Global South coverage"


def test_no_match_leaves_fields_none(monkeypatch):
    """An outlet absent from the lookup produces the three fields at
    None — explicitly set, not omitted, so the rendered TP shape is
    consistent."""
    monkeypatch.setattr(
        topic_stages,
        "_OUTLET_LOOKUP_CACHE",
        {"Al Jazeera": {"tier": 2, "editorial_independence": "x", "bias_note": "y"}},
    )
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "Some Researcher Hydrated Site", "title": "T"},
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    s = tb_after.final_sources[0]
    assert s["tier"] is None
    assert s["editorial_independence"] is None
    assert s["bias_note"] is None


def test_source_without_outlet_field_is_safe(monkeypatch):
    """A source dict missing the `outlet` field (or carrying a non-
    string outlet) should not crash the stage — fields default to
    None."""
    monkeypatch.setattr(
        topic_stages,
        "_OUTLET_LOOKUP_CACHE",
        {"Al Jazeera": {"tier": 2, "editorial_independence": "x", "bias_note": "y"}},
    )
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "title": "no outlet field"},
        {"id": "src-002", "outlet": None, "title": "non-string outlet"},
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    for s in tb_after.final_sources:
        assert s["editorial_independence"] is None
        assert s["bias_note"] is None
        assert s["tier"] is None


def test_mixed_batch_some_match_some_not(monkeypatch):
    """A batch where some outlets match and some do not — the matched
    sources carry meta, the unmatched stay at None. Tally count
    correct."""
    monkeypatch.setattr(
        topic_stages,
        "_OUTLET_LOOKUP_CACHE",
        {
            "Al Jazeera": {"tier": 2, "editorial_independence": "publicly_funded_autonomous",
                           "bias_note": "Qatar-funded"},
            "Anadolu Agency": {"tier": 2, "editorial_independence": "state_influenced",
                               "bias_note": "Turkish state news agency"},
        },
    )
    tb = TopicBus()
    tb.final_sources = [
        {"id": "src-001", "outlet": "Al Jazeera"},
        {"id": "src-002", "outlet": "Le Figaro"},
        {"id": "src-003", "outlet": "Anadolu Agency"},
        {"id": "src-004", "outlet": "Yeni Şafak"},
    ]
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    by_id = {s["id"]: s for s in tb_after.final_sources}
    assert by_id["src-001"]["editorial_independence"] == "publicly_funded_autonomous"
    assert by_id["src-002"]["editorial_independence"] is None
    assert by_id["src-003"]["editorial_independence"] == "state_influenced"
    assert by_id["src-004"]["editorial_independence"] is None


def test_empty_final_sources_is_no_op(monkeypatch):
    monkeypatch.setattr(topic_stages, "_OUTLET_LOOKUP_CACHE", {})
    tb = TopicBus()
    tb.final_sources = []
    tb_after = _run(propagate_outlet_metadata, tb, _ro())
    assert tb_after.final_sources == []


def test_lookup_cache_hits_real_config():
    """Smoke against the real config/sources.json: at least Al Jazeera
    is present and yields the documented vocabulary."""
    lookup = topic_stages._load_outlet_lookup()
    assert "Al Jazeera" in lookup
    assert lookup["Al Jazeera"]["editorial_independence"] in {
        "independent", "publicly_funded_autonomous",
        "state_directed", "state_influenced",
    }
