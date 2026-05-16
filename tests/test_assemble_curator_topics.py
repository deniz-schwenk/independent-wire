"""Tests for ``assemble_curator_topics`` — Brief 5 integration stage of
the triple-stage Curator (docs/ADR-CURATOR-TRIPLE-STAGE.md).

The stage is deterministic Python. Tests inject synthetic ``curator_
discovered_topics`` (Brief 4 shape) and ``curator_topic_assignments``
(Brief 2 shape) on the bus, and assert the assembled ``curator_topics_
unsliced`` / ``curator_topics`` against the expected enriched shape.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from src.bus import RunBus
from src.stage import get_stage_meta
from src.stages.run_stages import (
    DEFAULT_MAX_TOPICS,
    assemble_curator_topics,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_findings(n: int = 6) -> list[dict]:
    """Six findings — three from Iran (de), three from Climate (en)."""
    return [
        {"title": "Iran A", "summary": "tehran", "region": "ME", "language": "de", "source_name": "src1"},
        {"title": "Iran B", "summary": "iran", "region": "ME", "language": "en", "source_name": "src2"},
        {"title": "Iran C", "summary": "iran", "region": "ME", "language": "fa", "source_name": "src3"},
        {"title": "Climate A", "summary": "paris", "region": "EU", "language": "en", "source_name": "src4"},
        {"title": "Climate B", "summary": "carbon", "region": "EU", "language": "fr", "source_name": "src5"},
        {"title": "Climate C", "summary": "climate", "region": "US", "language": "en", "source_name": "src6"},
    ]


def _make_rb(
    *,
    findings: list[dict],
    discovered: list[dict],
    assignments: list[dict],
    run_date: str = "2026-05-16",
) -> RunBus:
    return RunBus(
        run_id="run-test-assemble",
        run_date=run_date,
        curator_findings=findings,
        curator_discovered_topics={"topics": discovered, "n_topics": len(discovered)},
        curator_topic_assignments={"topics": assignments},
    )


def _run(stage, rb: RunBus) -> RunBus:
    return asyncio.run(stage(rb))


# ---------------------------------------------------------------------------
# 1. Stage metadata
# ---------------------------------------------------------------------------


def test_stage_metadata():
    meta = get_stage_meta(assemble_curator_topics)
    assert meta.name == "assemble_curator_topics"
    assert meta.kind == "run"
    assert set(meta.reads) == {
        "curator_findings",
        "curator_discovered_topics",
        "curator_topic_assignments",
    }
    assert meta.writes == ("curator_topics_unsliced", "curator_topics")


# ---------------------------------------------------------------------------
# 2. Source-id attachment from gravitational assignments
# ---------------------------------------------------------------------------


def test_source_ids_attached_positionally():
    """Topic at index 0 in discovered gets source_ids from
    assignments.topics where topic_index=0; topic at index 1 from
    topic_index=1; etc."""
    findings = _make_findings()
    discovered = [
        {"title": "Iran story", "summary": "Iran-related coverage"},
        {"title": "Climate story", "summary": "Climate-related coverage"},
    ]
    assignments = [
        {
            "topic_index": 0,
            "topic_title": "Iran story",
            "n_assigned": 3,
            "assignments": [
                {"source_id": "finding-0", "similarity": 0.9},
                {"source_id": "finding-1", "similarity": 0.85},
                {"source_id": "finding-2", "similarity": 0.8},
            ],
        },
        {
            "topic_index": 1,
            "topic_title": "Climate story",
            "n_assigned": 3,
            "assignments": [
                {"source_id": "finding-3", "similarity": 0.9},
                {"source_id": "finding-4", "similarity": 0.85},
                {"source_id": "finding-5", "similarity": 0.8},
            ],
        },
    ]
    rb = _make_rb(findings=findings, discovered=discovered, assignments=assignments)
    out = _run(assemble_curator_topics, rb)
    topics_full = out.curator_topics_unsliced

    assert len(topics_full) == 2
    by_title = {t["title"]: t for t in topics_full}
    assert by_title["Iran story"]["source_ids"] == ["finding-0", "finding-1", "finding-2"]
    assert by_title["Climate story"]["source_ids"] == ["finding-3", "finding-4", "finding-5"]


def test_topic_without_assignments_surfaces_with_source_count_zero():
    """A topic the gravitational stage left empty appears in the output
    with ``source_count = 0``, not silently dropped — preserves
    transparency for the Editor's downstream rejection reason."""
    findings = _make_findings()
    discovered = [
        {"title": "Iran story", "summary": "Iran-related coverage"},
        {"title": "Orphan story", "summary": "Nothing assigned"},
    ]
    assignments = [
        {
            "topic_index": 0,
            "topic_title": "Iran story",
            "n_assigned": 1,
            "assignments": [{"source_id": "finding-0", "similarity": 0.9}],
        },
        # No entry for topic_index=1 — gravitational found no above-threshold
        # findings for it.
    ]
    rb = _make_rb(findings=findings, discovered=discovered, assignments=assignments)
    out = _run(assemble_curator_topics, rb)
    topics_full = out.curator_topics_unsliced

    titles = [t["title"] for t in topics_full]
    assert "Orphan story" in titles
    orphan = next(t for t in topics_full if t["title"] == "Orphan story")
    assert orphan["source_count"] == 0
    assert orphan["source_ids"] == []
    assert orphan["geographic_coverage"] == []
    assert orphan["languages"] == []


# ---------------------------------------------------------------------------
# 3. Enrichment fields populated
# ---------------------------------------------------------------------------


def test_every_topic_carries_enrichment_fields():
    findings = _make_findings()
    discovered = [{"title": "Iran story", "summary": "Iran-related"}]
    assignments = [{
        "topic_index": 0,
        "topic_title": "Iran story",
        "n_assigned": 3,
        "assignments": [
            {"source_id": "finding-0", "similarity": 0.9},
            {"source_id": "finding-1", "similarity": 0.85},
            {"source_id": "finding-2", "similarity": 0.8},
        ],
    }]
    rb = _make_rb(findings=findings, discovered=discovered, assignments=assignments)
    out = _run(assemble_curator_topics, rb)
    topic = out.curator_topics_unsliced[0]

    required = {
        "title", "summary", "source_ids",
        "geographic_coverage", "languages", "source_count",
        "missing_regions", "missing_languages", "source_diversity",
    }
    assert required.issubset(topic.keys()), (
        f"missing enrichment fields: {required - set(topic.keys())}"
    )
    assert topic["source_count"] == 3
    assert sorted(topic["geographic_coverage"]) == ["ME"]
    assert sorted(topic["languages"]) == ["de", "en", "fa"]
    # The three findings span ME with de/en/fa; missing regions are EU and US
    assert sorted(topic["missing_regions"]) == ["EU", "US"]
    assert sorted(topic["missing_languages"]) == ["fr"]


# ---------------------------------------------------------------------------
# 4. Determinism — byte-identical on identical input
# ---------------------------------------------------------------------------


def test_determinism_two_runs_byte_identical():
    findings = _make_findings()
    discovered = [
        {"title": "Climate story", "summary": "Climate-related"},
        {"title": "Iran story", "summary": "Iran-related"},
    ]
    assignments = [
        {
            "topic_index": 0,
            "topic_title": "Climate story",
            "n_assigned": 2,
            "assignments": [
                {"source_id": "finding-3", "similarity": 0.9},
                {"source_id": "finding-4", "similarity": 0.8},
            ],
        },
        {
            "topic_index": 1,
            "topic_title": "Iran story",
            "n_assigned": 1,
            "assignments": [{"source_id": "finding-0", "similarity": 0.9}],
        },
    ]
    rb1 = _make_rb(
        findings=copy.deepcopy(findings),
        discovered=copy.deepcopy(discovered),
        assignments=copy.deepcopy(assignments),
    )
    rb2 = _make_rb(
        findings=copy.deepcopy(findings),
        discovered=copy.deepcopy(discovered),
        assignments=copy.deepcopy(assignments),
    )
    out1 = _run(assemble_curator_topics, rb1)
    out2 = _run(assemble_curator_topics, rb2)
    assert (
        json.dumps(out1.curator_topics_unsliced, sort_keys=True)
        == json.dumps(out2.curator_topics_unsliced, sort_keys=True)
    )
    assert (
        json.dumps(out1.curator_topics, sort_keys=True)
        == json.dumps(out2.curator_topics, sort_keys=True)
    )


# ---------------------------------------------------------------------------
# 5. Sort + slice — by source_count desc, title asc tiebreak
# ---------------------------------------------------------------------------


def test_sort_by_source_count_desc_with_title_asc_tiebreak():
    findings = _make_findings()
    # Three topics: A (3 sources), B (1 source), C (1 source)
    discovered = [
        {"title": "C topic", "summary": "small"},
        {"title": "A topic", "summary": "big"},
        {"title": "B topic", "summary": "small"},
    ]
    assignments = [
        {  # topic_index 0 — C — 1 source
            "topic_index": 0, "topic_title": "C topic",
            "n_assigned": 1, "assignments": [{"source_id": "finding-3", "similarity": 0.8}],
        },
        {  # topic_index 1 — A — 3 sources
            "topic_index": 1, "topic_title": "A topic",
            "n_assigned": 3,
            "assignments": [
                {"source_id": "finding-0", "similarity": 0.9},
                {"source_id": "finding-1", "similarity": 0.85},
                {"source_id": "finding-2", "similarity": 0.8},
            ],
        },
        {  # topic_index 2 — B — 1 source
            "topic_index": 2, "topic_title": "B topic",
            "n_assigned": 1, "assignments": [{"source_id": "finding-4", "similarity": 0.8}],
        },
    ]
    rb = _make_rb(findings=findings, discovered=discovered, assignments=assignments)
    out = _run(assemble_curator_topics, rb)
    titles = [t["title"] for t in out.curator_topics_unsliced]
    # Expected order: A (3), B (1, B < C alphabetically), C (1)
    assert titles == ["A topic", "B topic", "C topic"]


def test_slice_to_default_max_topics():
    findings = _make_findings()
    discovered = [
        {"title": f"Topic {i:02d}", "summary": "s"} for i in range(15)
    ]
    assignments = [
        {
            "topic_index": i,
            "topic_title": f"Topic {i:02d}",
            "n_assigned": 1,
            "assignments": [{"source_id": "finding-0", "similarity": 0.9}],
        }
        for i in range(15)
    ]
    rb = _make_rb(findings=findings, discovered=discovered, assignments=assignments)
    out = _run(assemble_curator_topics, rb)
    assert len(out.curator_topics_unsliced) == 15
    assert len(out.curator_topics) == DEFAULT_MAX_TOPICS == 10


# ---------------------------------------------------------------------------
# 6. Pass-through of upstream slots
# ---------------------------------------------------------------------------


def test_upstream_slots_unchanged():
    findings = _make_findings()
    discovered = [{"title": "Iran story", "summary": "Iran"}]
    assignments = [{
        "topic_index": 0, "topic_title": "Iran story",
        "n_assigned": 1, "assignments": [{"source_id": "finding-0", "similarity": 0.9}],
    }]
    rb = _make_rb(findings=findings, discovered=discovered, assignments=assignments)
    findings_before = json.dumps(rb.curator_findings, sort_keys=True)
    discovered_before = json.dumps(rb.curator_discovered_topics, sort_keys=True)
    assignments_before = json.dumps(rb.curator_topic_assignments, sort_keys=True)

    out = _run(assemble_curator_topics, rb)
    assert json.dumps(out.curator_findings, sort_keys=True) == findings_before
    assert json.dumps(out.curator_discovered_topics, sort_keys=True) == discovered_before
    assert json.dumps(out.curator_topic_assignments, sort_keys=True) == assignments_before


# ---------------------------------------------------------------------------
# 7. EditorStage compatibility — curator_topics carries the shape Editor expects
# ---------------------------------------------------------------------------


def test_editor_input_shape_compatibility():
    """The shape `assemble_curator_topics` writes is the shape the legacy
    `EditorStage` already reads from `curator_topics`. Each entry has
    `title`, `summary`, `source_ids`, `source_count`,
    `geographic_coverage`, `languages`, `source_diversity`,
    `missing_regions`, `missing_languages` — every field the old
    `_attach_raw_data_from_curated` / `_CURATOR_RAW_DATA_FIELDS` chain
    expects to find."""
    from src.agent_stages import _CURATOR_RAW_DATA_FIELDS

    findings = _make_findings()
    discovered = [{"title": "Iran story", "summary": "Iran-related"}]
    assignments = [{
        "topic_index": 0, "topic_title": "Iran story",
        "n_assigned": 2,
        "assignments": [
            {"source_id": "finding-0", "similarity": 0.9},
            {"source_id": "finding-1", "similarity": 0.85},
        ],
    }]
    rb = _make_rb(findings=findings, discovered=discovered, assignments=assignments)
    out = _run(assemble_curator_topics, rb)
    topic = out.curator_topics[0]

    # Every Editor-expected raw_data field (except relevance_score, which
    # the new pipeline no longer emits) is present.
    for field in _CURATOR_RAW_DATA_FIELDS:
        if field == "relevance_score":
            continue  # New pipeline drops this; Editor's priority is the
            # editorial relevance judgement, not a Curator-side score.
        assert field in topic, f"missing Editor-input field: {field}"


# ---------------------------------------------------------------------------
# 8. Edge case — no discovered topics
# ---------------------------------------------------------------------------


def test_no_discovered_topics_empty_slots():
    findings = _make_findings()
    rb = _make_rb(findings=findings, discovered=[], assignments=[])
    out = _run(assemble_curator_topics, rb)
    assert out.curator_topics_unsliced == []
    assert out.curator_topics == []


def test_default_max_topics_pinned():
    assert DEFAULT_MAX_TOPICS == 10
