"""Tests for src/stages/run_stages.py — init_run, fetch_findings,
finalize_run, mirror_stage helper, attach_hydration_urls_to_assignments.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest

from src.bus import RunBus, TopicBus, WriterArticle
from src.stage import StageError, StageInputError, get_stage_meta
from src.stages.run_stages import (
    HYDRATION_URL_CAP,
    MAX_PER_OUTLET,
    MirrorMismatchError,
    RunInitConfig,
    TopicManifestEntry,
    make_attach_hydration_urls_to_assignments,
    make_fetch_findings,
    make_finalize_run,
    make_init_run,
    mirror_stage,
    select_diverse_hydration_urls,
)


# ---------------------------------------------------------------------------
# init_run
# ---------------------------------------------------------------------------


def test_init_run_happy_path(tmp_path: Path):
    """Default config, fresh tmp output dir → all five writes populated;
    previous_coverage is an empty list."""
    cfg = RunInitConfig(output_dir=tmp_path)
    init_run = make_init_run(cfg)

    rb = asyncio.run(init_run(RunBus()))

    assert isinstance(rb.run_id, str) and rb.run_id.startswith("run-")
    assert rb.run_date and len(rb.run_date) == 10
    assert rb.run_variant == "production"
    assert rb.max_produce == 3  # default; cfg.max_produce is None so no override
    assert rb.previous_coverage == []

    meta = get_stage_meta(init_run)
    assert meta.kind == "run"
    assert "run_id" in meta.writes
    assert "previous_coverage" in meta.writes


def test_init_run_with_overrides(tmp_path: Path):
    cfg = RunInitConfig(
        run_id_override="run-2026-04-30-deadbeef",
        run_date_override="2026-04-30",
        run_variant="hydrated",
        max_produce=5,
        output_dir=tmp_path,
    )
    init_run = make_init_run(cfg)

    rb = asyncio.run(init_run(RunBus()))

    assert rb.run_id == "run-2026-04-30-deadbeef"
    assert rb.run_date == "2026-04-30"
    assert rb.run_variant == "hydrated"
    assert rb.max_produce == 5


def test_init_run_loads_previous_coverage(tmp_path: Path):
    """Set up a fake prior TP in `output_dir/2026-04-29/tp-001.json`; assert
    init_run picks it up and projects to the documented coverage shape."""
    prior_dir = tmp_path / "2026-04-29"
    prior_dir.mkdir()
    prior_tp = {
        "id": "tp-2026-04-29-001",
        "metadata": {"date": "2026-04-29", "topic_slug": "test-topic"},
        "article": {
            "headline": "Test headline",
            "summary": "Test summary",
        },
    }
    (prior_dir / "tp-001.json").write_text(json.dumps(prior_tp), encoding="utf-8")

    # An entry without headline must be skipped.
    (prior_dir / "tp-002.json").write_text(
        json.dumps(
            {
                "id": "tp-2026-04-29-002",
                "metadata": {"date": "2026-04-29"},
                "article": {"headline": "", "summary": "no headline"},
            }
        ),
        encoding="utf-8",
    )

    cfg = RunInitConfig(
        run_date_override="2026-04-30",
        output_dir=tmp_path,
    )
    init_run = make_init_run(cfg)

    rb = asyncio.run(init_run(RunBus()))

    assert len(rb.previous_coverage) == 1
    record = rb.previous_coverage[0]
    assert record == {
        "tp_id": "tp-2026-04-29-001",
        "date": "2026-04-29",
        "headline": "Test headline",
        "slug": "test-topic",
        "summary": "Test summary",
    }


def test_init_run_skips_current_date_directory(tmp_path: Path):
    """A TP in today's directory must not appear in previous_coverage."""
    today = "2026-04-30"
    today_dir = tmp_path / today
    today_dir.mkdir()
    (today_dir / "tp-001.json").write_text(
        json.dumps(
            {
                "id": "tp-2026-04-30-001",
                "metadata": {"date": today, "topic_slug": "today"},
                "article": {"headline": "Today", "summary": "today"},
            }
        ),
        encoding="utf-8",
    )

    cfg = RunInitConfig(run_date_override=today, output_dir=tmp_path)
    init_run = make_init_run(cfg)

    rb = asyncio.run(init_run(RunBus()))
    assert rb.previous_coverage == []


# ---------------------------------------------------------------------------
# fetch_findings
# ---------------------------------------------------------------------------


def test_fetch_findings_happy_path(tmp_path: Path):
    raw_dir = tmp_path
    (raw_dir / "2026-04-30").mkdir()
    findings = [
        {"title": "Finding A", "source_url": "https://a.example/1"},
        {"title": "Finding B", "source_url": "https://b.example/1"},
    ]
    (raw_dir / "2026-04-30" / "feeds.json").write_text(
        json.dumps(findings), encoding="utf-8"
    )

    fetch = make_fetch_findings(raw_dir=raw_dir)

    rb = RunBus()
    rb.run_date = "2026-04-30"
    rb = asyncio.run(fetch(rb))

    assert rb.curator_findings == findings


def test_fetch_findings_missing_file_raises(tmp_path: Path):
    fetch = make_fetch_findings(raw_dir=tmp_path)
    rb = RunBus()
    rb.run_date = "2099-01-01"

    with pytest.raises(StageInputError, match="no feeds file"):
        asyncio.run(fetch(rb))


def test_fetch_findings_malformed_json_raises(tmp_path: Path):
    raw_dir = tmp_path
    (raw_dir / "2026-04-30").mkdir()
    (raw_dir / "2026-04-30" / "feeds.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    fetch = make_fetch_findings(raw_dir=raw_dir)
    rb = RunBus()
    rb.run_date = "2026-04-30"

    with pytest.raises(StageInputError, match="could not read"):
        asyncio.run(fetch(rb))


def test_fetch_findings_non_list_raises(tmp_path: Path):
    raw_dir = tmp_path
    (raw_dir / "2026-04-30").mkdir()
    (raw_dir / "2026-04-30" / "feeds.json").write_text(
        json.dumps({"not": "a list"}), encoding="utf-8"
    )

    fetch = make_fetch_findings(raw_dir=raw_dir)
    rb = RunBus()
    rb.run_date = "2026-04-30"

    with pytest.raises(StageInputError, match="must contain a JSON array"):
        asyncio.run(fetch(rb))


# ---------------------------------------------------------------------------
# mirror_stage — slot granularity
# ---------------------------------------------------------------------------


def test_mirror_stage_slot_fills_empty_target():
    tb = TopicBus()
    tb.writer_article = WriterArticle(
        headline="H", subheadline="S", body="B", summary="Sm"
    )
    # qa_corrected_article starts at WriterArticle() (empty)

    mirror_stage("qa_corrected_article", "writer_article", tb, granularity="slot")

    assert tb.qa_corrected_article == tb.writer_article
    # Deep-copy: mutating the result must not aliase to writer_article
    tb.qa_corrected_article.headline = "Tampered"
    assert tb.writer_article.headline == "H"


def test_mirror_stage_slot_no_op_when_target_populated():
    tb = TopicBus()
    tb.writer_article = WriterArticle(
        headline="Writer's headline", body="Writer's body"
    )
    tb.qa_corrected_article = WriterArticle(
        headline="QA-corrected headline", body="QA-corrected body"
    )

    mirror_stage("qa_corrected_article", "writer_article", tb, granularity="slot")

    # Target preserved, not overwritten
    assert tb.qa_corrected_article.headline == "QA-corrected headline"
    assert tb.qa_corrected_article.body == "QA-corrected body"


# ---------------------------------------------------------------------------
# mirror_stage — element granularity
# ---------------------------------------------------------------------------


def test_mirror_stage_element_merges_deltas_with_source():
    tb = TopicBus()
    # Source: full cluster list (3 clusters)
    tb.perspective_clusters = [
        {"id": "pc-001", "position_label": "Pro-X", "position_summary": "supports X"},
        {"id": "pc-002", "position_label": "Anti-X", "position_summary": "opposes X"},
        {"id": "pc-003", "position_label": "Neutral", "position_summary": "no view"},
    ]
    # Target: deltas from perspective_sync — only pc-001 and pc-002 changed
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "position_label": "Strongly Pro-X"},
        {"id": "pc-002", "position_summary": "actively opposes X"},
    ]

    mirror_stage(
        "perspective_clusters_synced",
        "perspective_clusters",
        tb,
        granularity="element",
    )

    result = tb.perspective_clusters_synced
    assert len(result) == 3
    # pc-001: delta's position_label wins, source's position_summary preserved
    assert result[0] == {
        "id": "pc-001",
        "position_label": "Strongly Pro-X",
        "position_summary": "supports X",
    }
    # pc-002: source's position_label preserved, delta's position_summary wins
    assert result[1] == {
        "id": "pc-002",
        "position_label": "Anti-X",
        "position_summary": "actively opposes X",
    }
    # pc-003: no delta, source verbatim
    assert result[2] == {
        "id": "pc-003",
        "position_label": "Neutral",
        "position_summary": "no view",
    }


def test_mirror_stage_element_handles_empty_target():
    """No deltas at all → target becomes a 1:1 copy of source (production
    variant where perspective_sync does not run)."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"id": "pc-001", "position_label": "A"},
        {"id": "pc-002", "position_label": "B"},
    ]
    # perspective_clusters_synced starts as []

    mirror_stage(
        "perspective_clusters_synced",
        "perspective_clusters",
        tb,
        granularity="element",
    )

    assert tb.perspective_clusters_synced == [
        {"id": "pc-001", "position_label": "A"},
        {"id": "pc-002", "position_label": "B"},
    ]


# ---------------------------------------------------------------------------
# mirror_stage — mismatch validation
# ---------------------------------------------------------------------------


def test_mirror_stage_rejects_undeclared_pair():
    rb = RunBus()
    with pytest.raises(MirrorMismatchError, match="not a field"):
        mirror_stage("not_a_real_slot", "run_id", rb)


def test_mirror_stage_rejects_unrelated_slots():
    """run_id and writer_article are real slots but on different buses, and
    run_id has no mirrors_from. Must raise."""
    rb = RunBus()
    with pytest.raises(MirrorMismatchError, match="not a field on RunBus"):
        mirror_stage("run_id", "writer_article", rb)


def test_mirror_stage_rejects_target_without_mirrors_from():
    """run_id and run_date are both on RunBus but neither declares
    mirrors_from → mismatch."""
    rb = RunBus()
    with pytest.raises(MirrorMismatchError, match="declares mirrors_from"):
        mirror_stage("run_id", "run_date", rb)


def test_mirror_stage_rejects_wrong_source_for_correct_target():
    """qa_corrected_article declares mirrors_from=writer_article. Asking
    it to mirror from perspective_clusters → mismatch."""
    tb = TopicBus()
    with pytest.raises(MirrorMismatchError, match="declares mirrors_from"):
        mirror_stage("qa_corrected_article", "perspective_clusters", tb)


# ---------------------------------------------------------------------------
# finalize_run
# ---------------------------------------------------------------------------


def test_finalize_run_aggregates_manifest_entries():
    entries = [
        TopicManifestEntry(
            topic_id="tp-2026-04-30-001",
            topic_slug="topic-one",
            status="success",
            stages_completed=["init_run", "curator", "editor", "writer", "qa"],
        ),
        {
            "topic_id": "tp-2026-04-30-002",
            "topic_slug": "topic-two",
            "status": "failed",
            "stages_completed": ["init_run", "curator"],
        },
    ]
    finalize = make_finalize_run(entries)

    rb = RunBus()
    rb.run_id = "run-2026-04-30-abc"
    rb.run_date = "2026-04-30"
    rb.run_variant = "production"

    rb = asyncio.run(finalize(rb))

    assert len(rb.run_topic_manifest) == 2
    assert rb.run_topic_manifest[0]["topic_id"] == "tp-2026-04-30-001"
    assert rb.run_topic_manifest[0]["status"] == "success"
    assert rb.run_topic_manifest[1]["status"] == "failed"
    # All entries are dicts (model_dump'd) for downstream consumption
    assert all(isinstance(e, dict) for e in rb.run_topic_manifest)


def test_finalize_run_validates_dict_entries():
    """A dict that doesn't match TopicManifestEntry's shape must raise."""
    finalize = make_finalize_run(
        [{"topic_id": "x", "topic_slug": "y", "status": "bogus"}]
    )
    rb = RunBus()
    with pytest.raises(Exception):  # pydantic.ValidationError
        asyncio.run(finalize(rb))


def test_finalize_run_metadata():
    finalize = make_finalize_run(())
    meta = get_stage_meta(finalize)
    assert meta.kind == "run"
    assert meta.reads == ("run_id", "run_date", "run_variant")
    assert meta.writes == ("run_topic_manifest",)


# ---------------------------------------------------------------------------
# attach_hydration_urls_to_assignments
# ---------------------------------------------------------------------------


def _hyd_layout(tmp_path: Path):
    """Return ``(raw_dir, sources_path)`` rooted under ``tmp_path``."""
    raw_dir = tmp_path / "raw"
    sources_path = tmp_path / "config" / "sources.json"
    return raw_dir, sources_path


def _seed_feeds_and_sources(
    tmp_path: Path,
    run_date: str,
    feeds: list[dict],
    countries: dict[str, str | None] | None = None,
) -> None:
    raw_dir = tmp_path / "raw" / run_date
    raw_dir.mkdir(parents=True)
    (raw_dir / "feeds.json").write_text(json.dumps(feeds), encoding="utf-8")
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    feed_entries = [
        {"name": name, "country": country}
        for name, country in (countries or {}).items()
    ]
    (cfg_dir / "sources.json").write_text(
        json.dumps({"feeds": feed_entries}), encoding="utf-8"
    )


def _hydrated_run_bus(run_date: str = "2026-04-30") -> RunBus:
    rb = RunBus()
    rb.run_id = "run-2026-04-30-test"
    rb.run_date = run_date
    rb.run_variant = "hydrated"
    return rb


def test_attach_hydration_urls_to_assignments_happy_path(tmp_path: Path):
    """3 assignments, raw findings cover 2/3 → first two get URLs, third
    falls through to empty list (no token overlap with any cluster)."""
    feeds = [
        {"source_name": "Reuters", "source_url": "https://reuters.example/india", "language": "en", "title": "Reuters India"},
        {"source_name": "BBC", "source_url": "https://bbc.example/india", "language": "en", "title": "BBC India"},
        {"source_name": "AFP", "source_url": "https://afp.example/storm", "language": "en", "title": "AFP storm"},
    ]
    _seed_feeds_and_sources(
        tmp_path, "2026-04-30", feeds,
        countries={"Reuters": "GB", "BBC": "GB", "AFP": "FR"},
    )
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )

    rb = _hydrated_run_bus()
    rb.curator_topics_unsliced = [
        {"title": "India and New Zealand sign comprehensive free trade agreement",
         "source_ids": ["finding-0", "finding-1"]},
        {"title": "Tropical storm hits Philippines coast",
         "source_ids": ["finding-2"]},
    ]
    rb.editor_assignments = [
        {"id": "tp-1", "title": "India New Zealand Free Trade Agreement Signed",
         "topic_slug": "ind-nz", "priority": 5, "selection_reason": "r"},
        {"id": "tp-2", "title": "Philippines tropical storm casualties",
         "topic_slug": "ph-storm", "priority": 4, "selection_reason": "r"},
        {"id": "tp-3", "title": "Completely unrelated lemur migration update",
         "topic_slug": "lemur", "priority": 3, "selection_reason": "r"},
    ]

    out = asyncio.run(stage(rb))
    a1, a2, a3 = out.editor_assignments
    urls1 = a1["raw_data"]["hydration_urls"]
    assert {u["outlet"] for u in urls1} == {"Reuters", "BBC"}
    assert {u["country"] for u in urls1} == {"GB"}
    urls2 = a2["raw_data"]["hydration_urls"]
    assert len(urls2) == 1 and urls2[0]["outlet"] == "AFP"
    # Third assignment had no token-overlap match → empty URLs (web-search only)
    assert a3["raw_data"]["hydration_urls"] == []


def test_attach_hydration_urls_to_assignments_missing_feeds_raises(tmp_path: Path):
    """No feeds.json on disk → StageInputError, mirroring fetch_findings."""
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )
    rb = _hydrated_run_bus()
    rb.editor_assignments = [
        {"id": "tp-1", "title": "x", "topic_slug": "x", "priority": 1, "selection_reason": "r"},
    ]
    rb.curator_topics_unsliced = [{"title": "x x x x", "source_ids": []}]
    with pytest.raises(StageInputError):
        asyncio.run(stage(rb))


def test_attach_hydration_urls_to_assignments_empty_assignments_passes_through(
    tmp_path: Path,
):
    """Empty editor_assignments → stage returns RunBus with empty list
    unchanged. The runner-level post-validator decides whether that's
    a pipeline error; this stage is empty-safe."""
    feeds: list[dict] = []
    _seed_feeds_and_sources(tmp_path, "2026-04-30", feeds, countries={})
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )
    rb = _hydrated_run_bus()
    rb.editor_assignments = []
    rb.curator_topics_unsliced = []

    out = asyncio.run(stage(rb))
    assert out.editor_assignments == []


def test_attach_hydration_urls_to_assignments_logs_tied_clusters(
    tmp_path: Path, caplog
):
    """When two clusters tie at the highest token-overlap score, the
    first-occurrence wins and a WARNING is logged."""
    feeds = [
        {"source_name": "Reuters", "source_url": "https://reuters.example/x", "language": "en"},
        {"source_name": "BBC", "source_url": "https://bbc.example/x", "language": "en"},
    ]
    _seed_feeds_and_sources(
        tmp_path, "2026-04-30", feeds,
        countries={"Reuters": "GB", "BBC": "GB"},
    )
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )
    rb = _hydrated_run_bus()
    # Two clusters tie on token-overlap with the assignment title.
    rb.curator_topics_unsliced = [
        {"title": "India trade deal signed", "source_ids": ["finding-0"]},
        {"title": "India trade deal signed", "source_ids": ["finding-1"]},
    ]
    rb.editor_assignments = [
        {"id": "tp-1", "title": "India trade deal signed",
         "topic_slug": "x", "priority": 5, "selection_reason": "r"},
    ]

    with caplog.at_level(logging.WARNING):
        out = asyncio.run(stage(rb))
    # First match wins → cluster 0 → finding-0 → Reuters
    urls = out.editor_assignments[0]["raw_data"]["hydration_urls"]
    assert len(urls) == 1
    assert urls[0]["outlet"] == "Reuters"
    assert any("tied for best match" in m for m in caplog.messages)


def test_attach_hydration_urls_to_assignments_overwrites_existing_urls(
    tmp_path: Path,
):
    """Re-running over assignments that already carry hydration_urls in
    raw_data overwrites cleanly (idempotent)."""
    feeds = [
        {"source_name": "Reuters", "source_url": "https://reuters.example/india", "language": "en"},
    ]
    _seed_feeds_and_sources(
        tmp_path, "2026-04-30", feeds, countries={"Reuters": "GB"},
    )
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )
    rb = _hydrated_run_bus()
    rb.curator_topics_unsliced = [
        {"title": "India trade deal", "source_ids": ["finding-0"]},
    ]
    rb.editor_assignments = [
        {
            "id": "tp-1",
            "title": "India trade deal",
            "topic_slug": "x",
            "priority": 5,
            "selection_reason": "r",
            "raw_data": {"hydration_urls": [{"url": "stale.example", "outlet": "Stale"}]},
        },
    ]

    out = asyncio.run(stage(rb))
    urls = out.editor_assignments[0]["raw_data"]["hydration_urls"]
    assert len(urls) == 1
    assert urls[0]["outlet"] == "Reuters"
    assert urls[0]["url"] == "https://reuters.example/india"


def test_attach_hydration_urls_to_assignments_no_run_date_raises(tmp_path: Path):
    """Stage requires run_date — refuses to guess; runner runs init_run first."""
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )
    rb = RunBus()  # no run_date
    rb.editor_assignments = [{"id": "tp-1", "title": "x", "topic_slug": "x",
                              "priority": 1, "selection_reason": "r"}]
    rb.curator_topics_unsliced = [{"title": "x x x x", "source_ids": []}]
    with pytest.raises(StageError, match="run_date"):
        asyncio.run(stage(rb))


def test_attach_hydration_urls_to_assignments_metadata():
    stage = make_attach_hydration_urls_to_assignments()
    meta = get_stage_meta(stage)
    assert meta.kind == "run"
    assert meta.name == "attach_hydration_urls_to_assignments"
    assert meta.reads == (
        "editor_assignments", "run_date", "curator_topics_unsliced"
    )
    assert meta.writes == ("editor_assignments",)


# ---------------------------------------------------------------------------
# select_diverse_hydration_urls
# ---------------------------------------------------------------------------


def _cand(url: str, outlet: str, published_at: str | None = None, **extra) -> dict:
    """Build a hydration-URL candidate dict for selector tests."""
    return {"url": url, "outlet": outlet, "published_at": published_at, **extra}


def test_select_diverse_hydration_urls_empty():
    """Empty input → empty output, no crash."""
    assert select_diverse_hydration_urls([]) == []


def test_select_diverse_hydration_urls_under_cap_round_robin():
    """4 candidates across 3 outlets, cap=40 → all returned, ordered
    round-robin by outlet alphabetically (BBC → AFP no — alphabetic:
    AFP, BBC, Reuters then back to AFP for outlet AFP's 2nd)."""
    candidates = [
        _cand("https://reuters.example/1", "Reuters", "2026-05-11T10:00Z"),
        _cand("https://afp.example/1", "AFP", "2026-05-11T09:00Z"),
        _cand("https://afp.example/2", "AFP", "2026-05-11T11:00Z"),
        _cand("https://bbc.example/1", "BBC", "2026-05-11T08:00Z"),
    ]
    out = select_diverse_hydration_urls(candidates, cap=40, max_per_outlet=3)
    assert len(out) == 4
    # Pass 1: AFP (newest=11:00), BBC, Reuters; Pass 2: AFP (9:00)
    assert [c["url"] for c in out] == [
        "https://afp.example/2",
        "https://bbc.example/1",
        "https://reuters.example/1",
        "https://afp.example/1",
    ]


def test_select_diverse_hydration_urls_distinct_outlets_above_cap():
    """60 outlets × 1 URL each, cap=40 → 40 distinct outlets, picked in
    alphabetic order of outlet name."""
    candidates = [
        _cand(f"https://o{i:02d}.example/1", f"Outlet-{i:02d}")
        for i in range(60)
    ]
    out = select_diverse_hydration_urls(candidates, cap=40, max_per_outlet=3)
    assert len(out) == 40
    outlets = [c["outlet"] for c in out]
    assert outlets == sorted(outlets)  # alphabetic pick order
    assert len(set(outlets)) == 40  # all distinct


def test_select_diverse_hydration_urls_max_per_outlet_hard_ceiling():
    """5 outlets × 100 URLs each, cap=40 → returns 5×3=15 (max_per_outlet
    binds before cap). Validates that the per-outlet ceiling applies
    regardless of cap headroom."""
    candidates = []
    for outlet_idx in range(5):
        outlet = f"Outlet-{outlet_idx}"
        for url_idx in range(100):
            candidates.append(_cand(
                f"https://o{outlet_idx}.example/{url_idx}",
                outlet,
                f"2026-05-11T{url_idx:02d}:00Z" if url_idx < 24 else None,
            ))
    out = select_diverse_hydration_urls(candidates, cap=40, max_per_outlet=3)
    assert len(out) == 15  # 5 outlets × 3 per outlet
    by_outlet: dict[str, int] = {}
    for c in out:
        by_outlet[c["outlet"]] = by_outlet.get(c["outlet"], 0) + 1
    assert all(n == 3 for n in by_outlet.values())
    assert len(by_outlet) == 5


def test_select_diverse_hydration_urls_partial_missing_published_at():
    """Some candidates within an outlet have published_at=None → they
    sort last within that outlet; selector does not crash."""
    candidates = [
        _cand("https://reuters.example/3", "Reuters", None),
        _cand("https://reuters.example/1", "Reuters", "2026-05-11T10:00Z"),
        _cand("https://reuters.example/2", "Reuters", "2026-05-11T11:00Z"),
    ]
    out = select_diverse_hydration_urls(candidates, cap=40, max_per_outlet=3)
    assert len(out) == 3
    # Within Reuters: 11:00 first (newest), 10:00 second, None last.
    assert [c["url"] for c in out] == [
        "https://reuters.example/2",
        "https://reuters.example/1",
        "https://reuters.example/3",
    ]


def test_select_diverse_hydration_urls_all_missing_published_at():
    """All candidates within an outlet have published_at=None →
    preserves input order (current operational state pre-
    TASK-FETCH-FEEDS-PUBLISHED-AT); selector does not crash."""
    candidates = [
        _cand("https://reuters.example/3", "Reuters", None),
        _cand("https://reuters.example/1", "Reuters", None),
        _cand("https://reuters.example/2", "Reuters", None),
    ]
    out = select_diverse_hydration_urls(candidates, cap=40, max_per_outlet=3)
    assert len(out) == 3
    # Input order preserved → /3, /1, /2.
    assert [c["url"] for c in out] == [
        "https://reuters.example/3",
        "https://reuters.example/1",
        "https://reuters.example/2",
    ]


def test_select_diverse_hydration_urls_deterministic_outlet_order():
    """Identical input shape across two outlets → alphabetic outlet
    pick order is deterministic (does not depend on insertion order)."""
    cand_a = [
        _cand("https://bbc.example/1", "BBC"),
        _cand("https://afp.example/1", "AFP"),
    ]
    cand_b = [
        _cand("https://afp.example/1", "AFP"),
        _cand("https://bbc.example/1", "BBC"),
    ]
    out_a = select_diverse_hydration_urls(cand_a, cap=40, max_per_outlet=3)
    out_b = select_diverse_hydration_urls(cand_b, cap=40, max_per_outlet=3)
    assert [c["outlet"] for c in out_a] == ["AFP", "BBC"]
    assert [c["outlet"] for c in out_b] == ["AFP", "BBC"]


def test_select_diverse_hydration_urls_single_outlet_cap_clipped():
    """40 candidates all from one outlet, cap=40, max_per_outlet=3 →
    returns 3 (the newest), not 40. The max_per_outlet ceiling binds
    even when len(candidates) <= cap."""
    candidates = [
        _cand(
            f"https://reuters.example/{i}",
            "Reuters",
            f"2026-05-11T{i:02d}:00Z",
        )
        for i in range(40)
    ]
    out = select_diverse_hydration_urls(candidates, cap=40, max_per_outlet=3)
    assert len(out) == 3
    # The 3 newest: indices 39, 38, 37.
    assert [c["url"] for c in out] == [
        "https://reuters.example/39",
        "https://reuters.example/38",
        "https://reuters.example/37",
    ]


def test_select_diverse_hydration_urls_module_constants_default():
    """Defaults match the module-level constants — guards against silent
    drift if someone changes one without updating the other."""
    assert HYDRATION_URL_CAP == 40
    assert MAX_PER_OUTLET == 3


# ---------------------------------------------------------------------------
# attach_hydration_urls_to_assignments — cap integration
# ---------------------------------------------------------------------------


def test_attach_hydration_urls_to_assignments_applies_cap(tmp_path: Path):
    """End-to-end: cluster with 50 findings from many outlets → cap=40
    + max_per_outlet=3 applies, output has ≤40 URLs and ≤3 per outlet."""
    # 50 findings: 10 outlets × 5 URLs each.
    feeds = []
    for outlet_idx in range(10):
        outlet = f"Outlet-{outlet_idx:02d}"
        for url_idx in range(5):
            feeds.append({
                "source_name": outlet,
                "source_url": f"https://o{outlet_idx:02d}.example/{url_idx}",
                "language": "en",
                "title": f"India trade deal coverage {outlet} {url_idx}",
            })
    countries = {f"Outlet-{i:02d}": "GB" for i in range(10)}
    _seed_feeds_and_sources(tmp_path, "2026-04-30", feeds, countries=countries)
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )

    rb = _hydrated_run_bus()
    rb.curator_topics_unsliced = [{
        "title": "India trade deal signed",
        "source_ids": [f"finding-{i}" for i in range(50)],
    }]
    rb.editor_assignments = [{
        "id": "tp-1", "title": "India trade deal signed",
        "topic_slug": "ind-trade", "priority": 5, "selection_reason": "r",
    }]

    out = asyncio.run(stage(rb))
    urls = out.editor_assignments[0]["raw_data"]["hydration_urls"]
    # 10 outlets × max 3 = 30; cap=40 doesn't bind first.
    assert len(urls) == 30
    by_outlet: dict[str, int] = {}
    for u in urls:
        by_outlet[u["outlet"]] = by_outlet.get(u["outlet"], 0) + 1
    assert max(by_outlet.values()) == 3
    assert len(by_outlet) == 10


def test_attach_hydration_urls_to_assignments_cap_overrides(tmp_path: Path):
    """Factory accepts cap / max_per_outlet overrides — tests can
    inject low values without monkey-patching constants."""
    feeds = [
        {"source_name": "Reuters", "source_url": f"https://r.example/{i}",
         "language": "en", "title": f"India trade {i}"}
        for i in range(10)
    ]
    _seed_feeds_and_sources(
        tmp_path, "2026-04-30", feeds, countries={"Reuters": "GB"},
    )
    raw_dir, sources_path = _hyd_layout(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path,
        cap=5, max_per_outlet=2,
    )
    rb = _hydrated_run_bus()
    rb.curator_topics_unsliced = [{
        "title": "India trade deal signed",
        "source_ids": [f"finding-{i}" for i in range(10)],
    }]
    rb.editor_assignments = [{
        "id": "tp-1", "title": "India trade deal signed",
        "topic_slug": "x", "priority": 5, "selection_reason": "r",
    }]

    out = asyncio.run(stage(rb))
    urls = out.editor_assignments[0]["raw_data"]["hydration_urls"]
    # 1 outlet × max_per_outlet=2 = 2 (well under cap=5).
    assert len(urls) == 2
