"""Tests for the deterministic `registry` search backend (Phase A2).

Fixture-based, no network in the default suite. One optional integration smoke
sits behind ``IW_REGISTRY_SMOKE=1``.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from src.stages import coherence
from src.tools import registry_search as rs


# ── fixtures ─────────────────────────────────────────────────────────────────
def _od(name, langs, country, bucket, tags, host, **extra):
    """Build an on_demand catalog entry in the A1 shape."""
    e = {
        "name": name,
        "url": f"https://{host}/feed.xml",
        "type": "rss",
        "access": "on_demand",
        "access_type": "public",
        "outlet_hostname": host,
        "languages": langs,
        "country": country,
        "region_bucket": bucket,
        "tier_observed": 1,
        "proposed_beat_tags": tags,
        "evidence": {"appearance_count": 10},
        "seed_review": "pending",
    }
    e.update(extra)
    return e


@pytest.fixture
def catalog():
    return [
        _od("AraNet", ["ar"], "Qatar", "middle_east_north_africa",
            ["gaza", "strikes"], "aranet.example"),
        _od("RusWire", ["ru"], "Russia", "europe_central_asia",
            ["ukraine", "sanctions"], "ruswire.example"),
        _od("UkrPravda", ["uk", "ru"], "Ukraine", "europe_central_asia",
            ["kyiv", "front"], "ukrpravda.example"),
        _od("USDaily", ["en"], "United States", "north_america",
            ["pentagon", "congress"], "usdaily.example"),
        _od("TokyoPress", ["ja"], "Japan", "east_asia_pacific",
            ["economy", "yen"], "tokyopress.example"),
        _od("OffOutlet", ["en"], "Australia", "east_asia_pacific",
            ["sport", "weather"], "offoutlet.example",
            evidence={"appearance_count": 99}),
    ]


@pytest.fixture(autouse=True)
def _clean():
    rs._reset_caches()
    yield
    rs._reset_caches()


class StubEmbedder:
    """Deterministic offline embedder — length-based vectors, records calls."""

    model_name = "stub"

    def __init__(self):
        self.calls = 0

    def embed_batch(self, texts):
        self.calls += 1
        return np.array([[float(len(t)), 1.0, 0.0] for t in texts], dtype=np.float64)


# ── selection: daily never selected, signals, cap, fallback ──────────────────
def test_daily_entries_never_selected(catalog, tmp_path):
    """load_on_demand_catalog returns only on_demand; daily is invisible."""
    import json

    src = tmp_path / "sources.json"
    daily = {"name": "D", "url": "https://d.example/f", "type": "rss",
             "access": "daily", "region": "", "language": "en", "enabled": True}
    src.write_text(json.dumps({"feeds": [daily] + catalog}), encoding="utf-8")
    loaded = rs.load_on_demand_catalog(path=src)
    assert all(e["access"] == "on_demand" for e in loaded)
    assert "D" not in {e["name"] for e in loaded}
    assert len(loaded) == len(catalog)


def test_selection_language_signal_arabic(catalog):
    eps, basis = rs.select_endpoints("قصف غزة صواريخ", catalog)
    assert basis == "topic_signal"
    assert eps[0]["name"] == "AraNet"  # only ar-language outlet, ranked top


def test_selection_country_region_signal(catalog):
    eps, basis = rs.select_endpoints(
        "Russia Ukraine war sanctions escalation", catalog
    )
    names = [e["name"] for e in eps]
    assert basis == "topic_signal"
    # Russia + Ukraine countries + europe_central_asia region + tag overlap
    assert names[:2] == sorted(["RusWire", "UkrPravda"], key=names.index)[:2]
    assert "RusWire" in names and "UkrPravda" in names
    assert "TokyoPress" not in names[:3]


def test_selection_tag_overlap(catalog):
    eps, _ = rs.select_endpoints("Pentagon budget and Congress vote", catalog)
    assert eps[0]["name"] == "USDaily"  # matches pentagon+congress tags + country


def test_selection_respects_enabled_false(catalog, tmp_path):
    import json

    disabled = _od("Muted", ["en"], "United States", "north_america",
                   ["pentagon"], "muted.example", enabled=False)
    src = tmp_path / "sources.json"
    src.write_text(json.dumps({"feeds": catalog + [disabled]}), encoding="utf-8")
    loaded = rs.load_on_demand_catalog(path=src)
    assert "Muted" not in {e["name"] for e in loaded}


def test_selection_cap(catalog):
    eps, _ = rs.select_endpoints("news", catalog, max_endpoints=2)
    assert len(eps) == 2


def test_prior_fallback_when_no_signal(catalog):
    # No language script, no catalog country, no tag overlap → prior fallback,
    # ranked by observed newsworthiness (appearance_count).
    eps, basis = rs.select_endpoints("zzzqqq wibble", catalog)
    assert basis == "prior_fallback"
    assert eps  # still returns endpoints
    assert eps[0]["name"] == "OffOutlet"  # highest appearance_count (99)


def test_max_endpoints_env(monkeypatch, catalog):
    monkeypatch.setenv("IW_REGISTRY_MAX_ENDPOINTS", "3")
    eps, _ = rs.select_endpoints("news", catalog)
    assert len(eps) == 3


# ── language detection ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "query,expected",
    [
        ("قصف كييف صواريخ", {"ar", "fa", "ur"}),
        ("Россия Украина война", {"ru", "uk"}),
        ("東京の経済ニュース", {"ja"}),      # kana → ja, unambiguous
        ("한국 뉴스 속보", {"ko"}),
        ("NATO summit Ankara Turkey", set()),  # Latin → no signal
    ],
)
def test_detect_query_languages(query, expected):
    assert rs.detect_query_languages(query) == expected


# ── dated-only filter ────────────────────────────────────────────────────────
_RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Fix</title>
<item><title>Dated One</title><link>https://ex.com/a</link>
<description>hello &lt;b&gt;world&lt;/b&gt;</description>
<pubDate>Tue, 01 Jul 2026 10:00:00 GMT</pubDate></item>
<item><title>Dated Two</title><link>https://ex.com/b</link>
<pubDate>Wed, 02 Jul 2026 10:00:00 GMT</pubDate></item>
<item><title>No Date</title><link>https://ex.com/c</link>
<description>undated</description></item>
</channel></rss>"""


def test_dated_only_filter_drops_and_counts():
    entry = {"name": "Fix", "outlet_hostname": "ex.com"}
    items, undated = rs.parse_feed_dated_items(_RSS, entry)
    assert undated == 1
    assert [it["title"] for it in items] == ["Dated One", "Dated Two"]
    assert all(it["published_at"] for it in items)
    assert items[0]["content"] == "hello world"  # HTML stripped


# ── parity shape ─────────────────────────────────────────────────────────────
def test_output_matches_execute_contract_shape():
    """Registry emits the documented ``execute`` contract: a ``Results for:``
    header then ``N. title / <3sp>url / <3sp>snippet`` blocks — byte-identical
    in structure to what brave/ollama/ddg emit via _format_results."""
    items = [
        {"title": "First Headline", "url": "https://a.example/x",
         "content": "summary one"},
        {"title": "Second Headline", "url": "https://b.example/y",
         "content": "summary two"},
    ]
    out = rs._format_registry_results("my query", items, 5)
    assert out.startswith("Results for: my query")
    assert "1. First Headline\n   https://a.example/x\n   summary one" in out
    assert "2. Second Headline\n   https://b.example/y\n   summary two" in out


def test_output_survives_researcher_consumption_path():
    """The real parity guarantee: a registry block fed through the researcher's
    OWN ``_deduplicate_search_results`` + ``_enrich_url_dates`` is consumed
    exactly like a Sonar block — both URLs preserved, no crash — so the
    researcher stages cannot tell which provider served them."""
    from src.stages.topic_stages import (
        _deduplicate_search_results,
        _enrich_url_dates,
    )

    items = [
        {"title": "Kyiv strike", "url": "https://a.example/2026/07/01/kyiv",
         "content": "summary one"},
        {"title": "NATO reaction", "url": "https://b.example/y",
         "content": "summary two"},
    ]
    out = rs._format_registry_results("kyiv nato", items, 5)
    sr = [{"query": "kyiv nato", "language": "en", "results": out}]
    deduped = _deduplicate_search_results(sr)
    _enrich_url_dates(deduped)
    joined = deduped[0]["results"]
    assert "https://a.example/2026/07/01/kyiv" in joined
    assert "https://b.example/y" in joined
    # date-in-URL enrichment fires exactly as it does for Sonar numbered blocks
    dates = deduped[0].get("url_dates") or []
    assert any(d["estimated_date"] == "2026-07-01" for d in dates)


# ── embedder singleton reuse ─────────────────────────────────────────────────
def test_embedder_singleton_reused(monkeypatch):
    stub = StubEmbedder()
    monkeypatch.setattr(coherence, "_default_embedder", stub)

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("registry instantiated a SECOND embedder")

    monkeypatch.setattr(coherence, "FastembedEmbedder", Boom)

    items = [
        {"title": "short", "content": ""},
        {"title": "a much longer headline about things", "content": "x"},
    ]
    ranked = rs.rank_items("query text", items, 2)  # embedder=None → singleton
    assert stub.calls == 1  # one batched embed call, no re-instantiation
    assert len(ranked) == 2


def test_rank_items_orders_by_similarity():
    stub = StubEmbedder()
    items = [{"title": "aaaa", "content": ""}, {"title": "aa", "content": ""}]
    # StubEmbedder vector = [len, 1, 0]; cosine to a longer query favors longer.
    ranked = rs.rank_items("aaaaaaaa", items, 1, embedder=stub)
    assert len(ranked) == 1


# ── full flow (mocked fetch + embedder) ──────────────────────────────────────
@pytest.mark.asyncio
async def test_search_registry_end_to_end(monkeypatch, catalog):
    monkeypatch.setattr(rs, "load_on_demand_catalog", lambda: catalog)
    monkeypatch.setattr(coherence, "_default_embedder", StubEmbedder())

    per_host = {
        "ruswire.example": [
            {"title": "Russia strikes Kyiv", "url": "https://ruswire.example/1",
             "content": "moscow", "published_at": "2026-07-01T00:00:00+00:00"},
        ],
        "ukrpravda.example": [
            {"title": "Kyiv under fire", "url": "https://ukrpravda.example/1",
             "content": "front", "published_at": "2026-07-02T00:00:00+00:00"},
        ],
    }

    async def fake_fetch(client, entry):
        host = entry["outlet_hostname"]
        return per_host.get(host, []), 2  # each endpoint also drops 2 undated

    monkeypatch.setattr(rs, "fetch_endpoint", fake_fetch)

    out = await rs._search_registry("Russia Ukraine Kyiv strikes", 5)
    assert "Results for: Russia Ukraine Kyiv strikes" in out
    assert "ruswire.example" in out or "ukrpravda.example" in out

    stats = rs._LAST_STATS
    assert stats["provider_used"] == "registry"
    assert stats["cost_usd"] == 0.0
    assert stats["n_endpoints_selected"] > 0
    assert stats["n_undated_dropped"] == 2 * stats["n_endpoints_selected"]
    assert stats["n_returned"] == stats["n_items_fetched"] <= 5
    assert "wall_ms" in stats


# ── optional integration smoke (real network; opt-in) ────────────────────────
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("IW_REGISTRY_SMOKE") != "1",
    reason="integration smoke — set IW_REGISTRY_SMOKE=1 to run (real network)",
)
async def test_integration_smoke_real_fetch():
    monkeypatch_max = os.environ.get("IW_REGISTRY_MAX_ENDPOINTS")
    os.environ["IW_REGISTRY_MAX_ENDPOINTS"] = "3"
    try:
        out = await rs._search_registry("Russia Ukraine war", 5)
    finally:
        if monkeypatch_max is None:
            os.environ.pop("IW_REGISTRY_MAX_ENDPOINTS", None)
        else:
            os.environ["IW_REGISTRY_MAX_ENDPOINTS"] = monkeypatch_max
    stats = rs._LAST_STATS
    assert stats["provider_used"] == "registry"
    assert stats["cost_usd"] == 0.0
    print("SMOKE stats:", stats)
