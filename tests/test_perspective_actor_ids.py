"""Tests for the agent-assigned ``actor_ids`` validation flow in
``enrich_perspective_clusters``.

Covers:

- Schema-shape: ``cluster.actor_ids`` survives the enrichment stage.
- Validation: every emitted actor_id must reference an entry in
  ``canonical_actors[]``; unknown IDs are dropped and a warning is logged.
- Multi-cluster membership: an actor appearing in two cluster
  ``actor_ids[]`` survives in both — the validator does NOT enforce
  uniqueness across clusters.
- Per-cluster dedup: an agent that emits the same ID twice within
  one cluster's ``actor_ids[]`` ends up with a single survivor.
"""

from __future__ import annotations

import asyncio
import logging

from src.bus import RunBus, TopicBus
from src.stages.topic_stages import enrich_perspective_clusters


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


def test_actor_ids_pass_through_when_all_known():
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-003"],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
        {"id": "actor-003", "name": "C"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    assert tb_after.perspective_clusters[0]["actor_ids"] == [
        "actor-001", "actor-003"
    ]


def test_unknown_actor_id_dropped_with_warning(caplog):
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-999", "actor-002"],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    with caplog.at_level(logging.WARNING, logger="src.stages.topic_stages"):
        tb_after = _run(enrich_perspective_clusters, tb, _ro())
    assert tb_after.perspective_clusters[0]["actor_ids"] == [
        "actor-001", "actor-002"
    ]
    assert any(
        "actor-999" in record.getMessage() for record in caplog.records
    )


def test_actor_ids_per_cluster_dedup():
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-001", "actor-002"],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    assert tb_after.perspective_clusters[0]["actor_ids"] == [
        "actor-001", "actor-002"
    ]


def test_actor_membership_can_span_multiple_clusters():
    """The validator does NOT enforce per-actor uniqueness across
    clusters: the same actor may legitimately voice multiple positions
    and appear in two cluster ``actor_ids[]`` lists. Verifies the
    architecture criterion §1.8(2)."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Cluster A",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001"],
        },
        {
            "position_label": "Cluster B",
            "source_ids": ["src-002"],
            "actor_ids": ["actor-001", "actor-002"],
        },
    ]
    tb.final_sources = [
        {"id": "src-001", "country": "X", "language": "en"},
        {"id": "src-002", "country": "Y", "language": "en"},
    ]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "Macron"},
        {"id": "actor-002", "name": "Merz"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster_a, cluster_b = tb_after.perspective_clusters
    assert "actor-001" in cluster_a["actor_ids"]
    assert "actor-001" in cluster_b["actor_ids"]


def test_actor_ids_empty_when_agent_omits():
    """A cluster whose agent output omits ``actor_ids`` ends up with an
    empty list — not a missing key — so downstream consumers can rely
    on the field being present."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "X", "source_ids": ["src-001"]},  # no actor_ids
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["actor_ids"] == []
    assert cluster["n_actors"] == 0
