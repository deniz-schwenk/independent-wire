"""Tests for the deterministic count fields written by
``enrich_perspective_clusters``: ``n_actors``, ``n_sources``,
``n_regions``, ``n_languages``.

These replace the prior ``representation`` bucket and surface the
underlying objective signals readers can act on.
"""

from __future__ import annotations

import asyncio

from src.bus import RunBus, TopicBus
from src.stages.topic_stages import enrich_perspective_clusters


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


def test_count_fields_populated_on_normal_cluster():
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001", "src-002", "src-003"],
            "actor_ids": ["actor-001", "actor-002"],
        },
    ]
    tb.final_sources = [
        {"id": "src-001", "country": "United States", "language": "en"},
        {"id": "src-002", "country": "France",        "language": "fr"},
        {"id": "src-003", "country": "United Kingdom", "language": "en"},
    ]
    tb.final_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["n_sources"] == 3
    assert cluster["n_actors"] == 2
    assert cluster["n_regions"] == 3
    assert cluster["n_languages"] == 2


def test_n_sources_counts_raw_source_ids_not_matches():
    """When a cluster references a source not present in
    ``final_sources``, ``n_sources`` reflects the raw count of
    ``source_ids`` (matches the prior V1 representation-ratio behaviour
    so renderer logic that surfaces "N sources" stays consistent)."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "X",
            "source_ids": ["src-001", "src-999"],  # src-999 missing
            "actor_ids": [],
        },
    ]
    tb.final_sources = [
        {"id": "src-001", "country": "United States", "language": "en"},
    ]
    tb.final_actors = []
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["n_sources"] == 2  # raw count
    assert cluster["n_regions"] == 1  # only matched source contributed


def test_n_regions_and_n_languages_dedup():
    """Two sources from the same country / same language → counts
    deduplicate. n_regions counts distinct normalised countries,
    n_languages counts distinct normalised language codes."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "X",
            "source_ids": ["src-001", "src-002", "src-003"],
            "actor_ids": [],
        },
    ]
    tb.final_sources = [
        {"id": "src-001", "country": "United States", "language": "en"},
        {"id": "src-002", "country": "United States", "language": "en"},
        {"id": "src-003", "country": "France",        "language": "fr"},
    ]
    tb.final_actors = []
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["n_regions"] == 2
    assert cluster["n_languages"] == 2


def test_n_actors_reflects_validated_actor_ids_only():
    """``n_actors`` matches the LENGTH of the validated ``actor_ids``
    list, not the agent-emitted raw count. Hallucinations are excluded
    from the count."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "X",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-999", "actor-002"],
        },
    ]
    tb.final_sources = [
        {"id": "src-001", "country": "X", "language": "en"},
    ]
    tb.final_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["n_actors"] == 2
    assert cluster["actor_ids"] == ["actor-001", "actor-002"]


def test_count_fields_zero_on_empty_cluster():
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "Empty", "source_ids": [], "actor_ids": []},
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.final_actors = [{"id": "actor-001", "name": "A"}]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["n_sources"] == 0
    assert cluster["n_actors"] == 0
    assert cluster["n_regions"] == 0
    assert cluster["n_languages"] == 0
