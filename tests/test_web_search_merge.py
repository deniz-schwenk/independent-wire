"""Tests for the `merge` search provider (registry + web arm, deterministic
Python-side dedup/merge — gate review 2026-07-13, D1).

Pure/unit: no network. The two arms are monkeypatched to return canned
plain-text blocks so the deterministic merge logic (parse → normalize → dedup
registry-wins → order → format) is exercised in isolation.
"""

from __future__ import annotations

import json

import pytest

from src.tools import web_search as ws
from src.tools.web_search import _format_results


def _block(query: str, items: list[dict]) -> str:
    """A provider result block exactly as any real provider emits it."""
    return _format_results(query, items, len(items))


# ── URL normalization (the documented dedup rule) ────────────────────────────
@pytest.mark.parametrize(
    "a,b",
    [
        # scheme dropped → http/https collide
        ("http://ex.com/a", "https://ex.com/a"),
        # leading www stripped
        ("https://www.ex.com/a", "https://ex.com/a"),
        # trailing slash on a non-root path stripped
        ("https://ex.com/a/", "https://ex.com/a"),
        # fragment dropped
        ("https://ex.com/a#section", "https://ex.com/a"),
        # tracking params dropped (utm_* + named)
        ("https://ex.com/a?utm_source=x&utm_medium=y", "https://ex.com/a"),
        ("https://ex.com/a?fbclid=123", "https://ex.com/a"),
        ("https://ex.com/a?gclid=z&ref=news", "https://ex.com/a"),
        # host case-insensitive
        ("https://EX.com/a", "https://ex.com/a"),
        # meaningful params kept but order-independent
        ("https://ex.com/a?p=2&q=1", "https://ex.com/a?q=1&p=2"),
    ],
)
def test_normalize_url_key_equal(a, b):
    assert ws._normalize_url_key(a) == ws._normalize_url_key(b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("https://ex.com/a", "https://ex.com/b"),          # different path
        ("https://ex.com/a", "https://other.com/a"),       # different host
        ("https://ex.com/a?id=1", "https://ex.com/a?id=2"),  # meaningful param
        ("https://ex.com/a/b", "https://ex.com/a"),        # sub-path is distinct
    ],
)
def test_normalize_url_key_distinct(a, b):
    assert ws._normalize_url_key(a) != ws._normalize_url_key(b)


# ── parse is the inverse of _format_results ──────────────────────────────────
def test_parse_result_block_roundtrip():
    items = [
        {"title": "First", "url": "https://a.example/x", "content": "snip one"},
        {"title": "Second", "url": "https://b.example/y", "content": "snip two"},
    ]
    parsed = ws._parse_result_block(_block("q", items))
    assert parsed == items


def test_parse_handles_snippetless_entry():
    text = "Results for: q\n\n1. Title A\n   https://a.example/x"
    parsed = ws._parse_result_block(text)
    assert parsed == [{"title": "Title A", "url": "https://a.example/x", "content": ""}]


def test_parse_no_results_and_error_blocks_yield_empty():
    assert ws._parse_result_block("No results for: q") == []
    assert ws._parse_result_block("Error: Ollama search failed: boom") == []
    assert ws._parse_result_block("") == []


# ── merge: registry-first, registry-wins-on-duplicate, deterministic order ───
def test_merge_registry_wins_on_duplicate():
    registry = [
        {"title": "R dated", "url": "https://ex.com/story", "content": "reg"},
    ]
    web = [
        # same article, tracking-decorated + www + http → dedups to the reg one
        {"title": "W same", "url": "http://www.ex.com/story?utm_source=t", "content": "web"},
        {"title": "W unique", "url": "https://other.com/z", "content": "web2"},
    ]
    merged, provenance = ws._merge_results(registry, web)
    urls = [it["url"] for it in merged]
    # registry copy kept (its title/url survive), web duplicate dropped
    assert urls == ["https://ex.com/story", "https://other.com/z"]
    assert merged[0]["title"] == "R dated"
    assert provenance == [
        ("https://ex.com/story", "registry"),
        ("https://other.com/z", "web_search"),
    ]


def test_merge_deterministic_order_registry_then_web():
    registry = [
        {"title": "r1", "url": "https://r.example/1", "content": "a"},
        {"title": "r2", "url": "https://r.example/2", "content": "b"},
    ]
    web = [
        {"title": "w1", "url": "https://w.example/1", "content": "c"},
    ]
    merged, prov = ws._merge_results(registry, web)
    assert [it["url"] for it in merged] == [
        "https://r.example/1",
        "https://r.example/2",
        "https://w.example/1",
    ]
    assert [c for _, c in prov] == ["registry", "registry", "web_search"]


# ── end-to-end merge provider (arms mocked, concurrency exercised) ───────────
@pytest.fixture(autouse=True)
def _clean_merge_state():
    ws.reset_merge_provenance()
    ws._LAST_MERGE_STATS.clear()
    yield
    ws.reset_merge_provenance()
    ws._LAST_MERGE_STATS.clear()


def _patch_arms(monkeypatch, registry_items, web_items):
    async def fake_registry(query, n):
        return _block(query, registry_items)

    async def fake_ollama(query, n):
        return _block(query, web_items)

    monkeypatch.setattr(ws, "_search_registry", fake_registry)
    monkeypatch.setattr(ws, "_search_ollama", fake_ollama)


@pytest.mark.asyncio
async def test_search_merge_contract_shape_and_stats(monkeypatch, caplog):
    registry_items = [
        {"title": "Reg dated", "url": "https://reg.example/a", "content": "one"},
    ]
    web_items = [
        {"title": "Web hit", "url": "https://web.example/b", "content": "two"},
        {"title": "Reg dup", "url": "http://www.reg.example/a", "content": "dup"},
    ]
    _patch_arms(monkeypatch, registry_items, web_items)

    with caplog.at_level("INFO"):
        out = await ws._search_merge("kyiv strike", 5)

    # contract shape: header + numbered N. title / <3sp>url / <3sp>snippet
    assert out.startswith("Results for: kyiv strike")
    assert "1. Reg dated\n   https://reg.example/a\n   one" in out
    assert "2. Web hit\n   https://web.example/b\n   two" in out
    # the web copy of the registry article was deduped away
    assert "Reg dup" not in out

    stats = ws._LAST_MERGE_STATS
    assert stats["search_provider_used"] == "merge"
    assert stats["registry_results"] == 1
    assert stats["web_results"] == 2
    assert stats["merged_results"] == 2
    assert stats["dedup_dropped"] == 1
    assert stats["cost_usd"] == 0.0
    # loud logging: all per-arm counts present in the emitted log line
    joined = "\n".join(r.getMessage() for r in caplog.records)
    for field in (
        "search_provider_used=merge",
        "registry_results=1",
        "web_results=2",
        "merged_results=2",
        "dedup_dropped=1",
    ):
        assert field in joined


@pytest.mark.asyncio
async def test_search_merge_deterministic_byte_identical(monkeypatch):
    registry_items = [{"title": "r", "url": "https://r.example/1", "content": "x"}]
    web_items = [{"title": "w", "url": "https://w.example/2", "content": "y"}]
    _patch_arms(monkeypatch, registry_items, web_items)

    ws.reset_merge_provenance()
    a = await ws._search_merge("same query", 5)
    ws.reset_merge_provenance()
    b = await ws._search_merge("same query", 5)
    assert a == b  # same input → byte-identical output


@pytest.mark.asyncio
async def test_search_merge_survives_one_arm_failing(monkeypatch):
    async def boom_registry(query, n):
        raise RuntimeError("registry down")

    async def ok_web(query, n):
        return _block(query, [{"title": "w", "url": "https://w.example/1", "content": "z"}])

    monkeypatch.setattr(ws, "_search_registry", boom_registry)
    monkeypatch.setattr(ws, "_search_ollama", ok_web)

    out = await ws._search_merge("q", 5)
    assert "https://w.example/1" in out
    assert ws._LAST_MERGE_STATS["registry_results"] == 0
    assert ws._LAST_MERGE_STATS["web_results"] == 1


@pytest.mark.asyncio
async def test_search_merge_records_provenance_registry_wins(monkeypatch):
    registry_items = [{"title": "r", "url": "https://ex.com/s", "content": "a"}]
    web_items = [
        {"title": "w", "url": "https://ex.com/s?utm_source=x", "content": "b"},
        {"title": "w2", "url": "https://w.example/u", "content": "c"},
    ]
    _patch_arms(monkeypatch, registry_items, web_items)

    ws.reset_merge_provenance()
    await ws._search_merge("q", 5)
    prov = ws.drain_merge_provenance()
    assert prov == {
        "https://ex.com/s": "registry",
        "https://w.example/u": "web_search",
    }
    # drained → cleared
    assert ws.drain_merge_provenance() == {}


# ── provenance channel-map writer (pure, deterministic) ──────────────────────
def test_write_provenance_channel_map(tmp_path):
    provenance = {
        "https://reg.example/a": "registry",
        "https://web.example/b": "web_search",
        "https://reg.example/c": "registry",
    }
    path = ws.write_provenance_channel_map(
        "2026-07-13", "run-abc", "topic-001", provenance, output_root=tmp_path
    )
    assert path is not None
    assert path == tmp_path / "2026-07-13" / "_state" / "run-abc" / (
        "provenance_channel_map.topic-001.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["provider"] == "merge"
    assert payload["topic_key"] == "topic-001"
    assert payload["channel_map"] == dict(sorted(provenance.items()))
    assert payload["counts"] == {"registry": 2, "web_search": 1, "total": 3}


def test_write_provenance_channel_map_skips_when_no_run_ids(tmp_path):
    assert ws.write_provenance_channel_map("", "", "t", {"u": "registry"}, tmp_path) is None
    assert ws.write_provenance_channel_map("d", "r", "t", {}, tmp_path) is None
    assert not list(tmp_path.rglob("*.json"))


def test_write_provenance_channel_map_deterministic_bytes(tmp_path):
    prov = {"https://b/2": "web_search", "https://a/1": "registry"}
    p1 = ws.write_provenance_channel_map("d", "r", "t", prov, tmp_path)
    b1 = p1.read_bytes()
    p2 = ws.write_provenance_channel_map("d", "r", "t", prov, tmp_path)
    assert p2.read_bytes() == b1  # stable, sorted output


# ── regression: merge is purely additive — existing providers untouched ──────
def test_existing_providers_unchanged():
    from src.tools import web_search as w

    assert w.PROVIDERS["ollama"] is w._search_ollama
    assert w.PROVIDERS["perplexity"] is w._search_perplexity
    assert w.PROVIDERS["duckduckgo"] is w._search_duckduckgo
    assert w.PROVIDERS["registry"] is w._search_registry
    # merge is present and distinct
    assert w.PROVIDERS["merge"] is w._search_merge


@pytest.mark.asyncio
async def test_non_merge_provider_never_calls_merge(monkeypatch):
    """Selecting an existing provider must not touch the merge path."""
    called = {"merge": False}

    async def spy_merge(query, n):
        called["merge"] = True
        return "Results for: x"

    async def fake_ollama(query, n):
        return _block(query, [{"title": "o", "url": "https://o/1", "content": "s"}])

    monkeypatch.setattr(ws, "_search_merge", spy_merge)
    monkeypatch.setattr(ws, "_search_ollama", fake_ollama)
    monkeypatch.setitem(ws.PROVIDERS, "ollama", fake_ollama)

    out = await ws.web_search_handler("q", provider="ollama")
    assert "https://o/1" in out
    assert called["merge"] is False


# ── researcher_search stage in merge mode writes the per-topic artifact ──────
def test_researcher_search_merge_writes_provenance_artifact(monkeypatch, tmp_path):
    """End-to-end at the stage seam: in merge mode the stage drains the
    accumulated url→channel map and writes it next to the per-topic run
    artifacts, without changing what it hands the assembler."""
    import asyncio

    from src.bus import EditorAssignment, RunBus
    from src.stages.run_stages import make_topic_bus
    from src.stages.topic_stages import make_researcher_search

    # merge provider is effective; provenance writer targets tmp, not real output/
    monkeypatch.setattr(ws, "effective_search_provider", lambda provider=None: "merge")
    monkeypatch.setattr(ws, "_REPO_ROOT", tmp_path)

    async def fake_registry(query, n):
        return _block(query, [{"title": "R", "url": "https://reg.example/a", "content": "one"}])

    async def fake_ollama(query, n):
        return _block(
            query,
            [
                {"title": "W", "url": "https://web.example/b", "content": "two"},
                {"title": "Rdup", "url": "http://www.reg.example/a", "content": "dup"},
            ],
        )

    monkeypatch.setattr(ws, "_search_registry", fake_registry)
    monkeypatch.setattr(ws, "_search_ollama", fake_ollama)

    class MergeTool:
        async def execute(self, query: str) -> str:
            return await ws._search_merge(query, 5)

    stage = make_researcher_search(MergeTool())
    rb = RunBus(run_id="run-test", run_date="2026-07-13")
    ea = EditorAssignment(id="tp-2026-07-13-001", topic_slug="hormuz")
    tb = make_topic_bus(ea, rb)
    tb.researcher_plan_queries = [
        {"query": "hormuz strikes", "language": "en"},
        {"query": "detroit ormuz", "language": "fr"},
    ]

    tb_after = asyncio.run(stage(tb, rb.as_readonly()))

    # contract untouched: assembler still gets plain-text result blocks
    assert tb_after.researcher_search_results
    assert all("results" in r for r in tb_after.researcher_search_results)

    # writer targets _REPO_ROOT/output/{date}/_state/{run_id}/ — the real
    # per-topic-artifact location (_REPO_ROOT patched to tmp_path here).
    art = (
        tmp_path / "output" / "2026-07-13" / "_state" / "run-test"
        / "provenance_channel_map.tp-2026-07-13-001.json"
    )
    assert art.exists()
    payload = json.loads(art.read_text(encoding="utf-8"))
    assert payload["channel_map"] == {
        "https://reg.example/a": "registry",
        "https://web.example/b": "web_search",
    }
    assert payload["counts"] == {"registry": 1, "web_search": 1, "total": 2}
