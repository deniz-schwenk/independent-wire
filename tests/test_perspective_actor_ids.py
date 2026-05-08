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
- Three-level partition: ``stated`` / ``reported`` / ``mentioned``
  survive enrichment, are filtered against ``canonical_actors``,
  cross-tier duplicates are repaired (priority stated > reported >
  mentioned), unclassified actors are defaulted to ``mentioned``,
  and the partition invariant
  (``set(stated) | set(reported) | set(mentioned) == set(actor_ids)``,
  pairwise-disjoint) holds after repair.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from src.bus import RunBus, TopicBus
from src.stages.topic_stages import (
    _assert_partition_invariant,
    enrich_perspective_clusters,
)


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
    # Three-level sub-lists also surface as empty arrays.
    assert cluster["stated"] == []
    assert cluster["reported"] == []
    assert cluster["mentioned"] == []


# ---------------------------------------------------------------------------
# Three-level partition (stated / reported / mentioned)
# ---------------------------------------------------------------------------


def test_sublist_passthrough_when_clean():
    """A clean agent output with non-overlapping sub-lists whose union
    matches ``actor_ids`` survives unchanged."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-002", "actor-003"],
            "stated": ["actor-001"],
            "reported": ["actor-002"],
            "mentioned": ["actor-003"],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
        {"id": "actor-003", "name": "C"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["stated"] == ["actor-001"]
    assert cluster["reported"] == ["actor-002"]
    assert cluster["mentioned"] == ["actor-003"]
    # Invariant: union equals actor_ids, pairwise disjoint.
    assert set(cluster["stated"]) | set(cluster["reported"]) | set(
        cluster["mentioned"]
    ) == set(cluster["actor_ids"])


def test_unknown_id_dropped_from_sublist(caplog):
    """A sub-list ID that fails canonical-actor validation is dropped
    with a warning identifying the sub-list."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-002"],
            "stated": ["actor-001"],
            "reported": ["actor-002", "actor-999"],  # actor-999 unknown
            "mentioned": [],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    with caplog.at_level(logging.WARNING, logger="src.stages.topic_stages"):
        tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["reported"] == ["actor-002"]
    assert cluster["actor_ids"] == ["actor-001", "actor-002"]
    # actor-999 was warned. The warning either fires from the actor_ids
    # loop (when the agent included it there too) or from the sub-list
    # filter (when only present in a sub-list).
    assert any("actor-999" in record.getMessage() for record in caplog.records)


def test_unknown_only_in_sublist_warned_with_tier_label(caplog):
    """When an unknown ID appears ONLY in a sub-list (not in
    ``actor_ids``), the validator warns from the sub-list filter and
    names the offending tier in the message."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001"],
            "stated": ["actor-001", "actor-999"],  # 999 not in actor_ids
            "reported": [],
            "mentioned": [],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    with caplog.at_level(logging.WARNING, logger="src.stages.topic_stages"):
        tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["stated"] == ["actor-001"]
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "actor-999" in m and "'stated'" in m for m in messages
    ), messages


def test_cross_tier_duplicate_resolved_priority_stated_first(caplog):
    """An ID appearing in two sub-lists is kept in the higher-priority
    tier (stated > reported > mentioned). A warning fires naming both
    tiers."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001"],
            "stated": ["actor-001"],
            "reported": ["actor-001"],  # duplicate; lower priority
            "mentioned": ["actor-001"],  # duplicate; lowest priority
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    with caplog.at_level(logging.WARNING, logger="src.stages.topic_stages"):
        tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["stated"] == ["actor-001"]
    assert cluster["reported"] == []
    assert cluster["mentioned"] == []
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "'stated'" in m and "'reported'" in m for m in messages
    ), messages


def test_actor_in_actor_ids_but_no_sublist_defaults_to_mentioned(caplog):
    """An ID in ``actor_ids`` that the agent failed to classify into
    any of the three sub-lists is default-assigned to ``mentioned`` —
    the lowest evidentiary tier — with a warning."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-002"],
            "stated": ["actor-001"],
            "reported": [],
            "mentioned": [],
            # actor-002 is in actor_ids but absent from all three lists.
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    with caplog.at_level(logging.WARNING, logger="src.stages.topic_stages"):
        tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["stated"] == ["actor-001"]
    assert cluster["mentioned"] == ["actor-002"]
    assert cluster["reported"] == []
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "actor-002" in m and "defaulting to mentioned" in m
        for m in messages
    ), messages


def test_partition_invariant_after_repair():
    """After all repairs, the union of the three sub-lists equals
    actor_ids and the three sub-lists are pairwise disjoint."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-002", "actor-003"],
            "stated": ["actor-001", "actor-002"],
            "reported": ["actor-002"],  # duplicate of stated
            "mentioned": [],  # actor-003 missing → defaulted to mentioned
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
        {"id": "actor-003", "name": "C"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    stated = set(cluster["stated"])
    reported = set(cluster["reported"])
    mentioned = set(cluster["mentioned"])
    actor_ids = set(cluster["actor_ids"])
    # Union equals actor_ids.
    assert stated | reported | mentioned == actor_ids
    # Pairwise disjoint.
    assert stated & reported == set()
    assert stated & mentioned == set()
    assert reported & mentioned == set()


def test_invariant_assertion_fires_on_union_mismatch():
    """The invariant helper raises AssertionError when the sub-list
    union does not equal ``actor_ids``. Synthesised by passing a
    sub-list configuration whose union has fewer members than the
    actor-id set."""
    with pytest.raises(AssertionError, match="sub-list union"):
        _assert_partition_invariant(
            "pc-001",
            stated=["actor-001"],
            reported=[],
            mentioned=[],
            actor_ids_set={"actor-001", "actor-002"},
        )


def test_invariant_assertion_fires_on_pairwise_overlap():
    """The invariant helper raises AssertionError when two sub-lists
    share an element."""
    with pytest.raises(AssertionError, match="not pairwise-disjoint"):
        _assert_partition_invariant(
            "pc-001",
            stated=["actor-001"],
            reported=["actor-001"],
            mentioned=[],
            actor_ids_set={"actor-001"},
        )
