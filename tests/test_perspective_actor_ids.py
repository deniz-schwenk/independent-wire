"""Tests for the cluster→actor classification flow in
``enrich_perspective_clusters`` (V2 three-sub-list shape with derived
``actor_ids``).

Covers:

- Sub-list shape: ``stated`` / ``reported`` / ``mentioned`` survive the
  enrichment stage and are filtered against ``canonical_actors[]``.
- Validation: every emitted sub-list ID must reference an entry in
  ``canonical_actors[]``; unknown IDs are dropped and a warning is
  logged naming the offending tier.
- Per-tier dedup: an agent that emits the same ID twice within one
  sub-list ends up with a single survivor in that tier.
- Cross-tier dedup: an ID appearing in two or three sub-lists is kept
  in the highest-priority tier (stated > reported > mentioned); a
  warning fires naming both tiers.
- Derived ``actor_ids``: the flat ``actor_ids[]`` field is computed as
  ``sorted(set(stated) | set(reported) | set(mentioned))`` after
  cleaning. The agent does not emit ``actor_ids[]``.
- Multi-cluster membership: an actor may legitimately voice multiple
  positions and appear in two cluster sub-lists.
- Partition invariant: after repair, the union of the three sub-lists
  equals ``actor_ids`` and the three sub-lists are pairwise disjoint.
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


# ---------------------------------------------------------------------------
# Sub-list passthrough, dedup, derived actor_ids
# ---------------------------------------------------------------------------


def test_sublist_passthrough_when_clean():
    """A clean agent output with non-overlapping sub-lists, all IDs known
    to canonical_actors, survives unchanged. ``actor_ids`` is derived
    as the sorted union."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
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
    assert cluster["actor_ids"] == ["actor-001", "actor-002", "actor-003"]
    # Invariant: union equals actor_ids, pairwise disjoint.
    assert set(cluster["stated"]) | set(cluster["reported"]) | set(
        cluster["mentioned"]
    ) == set(cluster["actor_ids"])


def test_actor_ids_derived_as_sorted_union():
    """``actor_ids`` is computed as ``sorted(set-union)`` of the three
    cleaned sub-lists. The agent does not emit it; any agent-side
    ``actor_ids`` field would be ignored."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            # Sub-lists deliberately out of alphabetical order on input;
            # the derived actor_ids must come back sorted.
            "stated": ["actor-003"],
            "reported": ["actor-001"],
            "mentioned": ["actor-002"],
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
    assert cluster["actor_ids"] == ["actor-001", "actor-002", "actor-003"]
    assert cluster["n_actors"] == 3


def test_per_sublist_dedup_within_tier():
    """An agent that emits the same ID twice within one sub-list ends
    up with a single survivor in that tier, preserving first-occurrence
    order."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "stated": ["actor-001", "actor-001", "actor-002"],
            "reported": [],
            "mentioned": [],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["stated"] == ["actor-001", "actor-002"]
    assert cluster["actor_ids"] == ["actor-001", "actor-002"]


def test_actor_membership_can_span_multiple_clusters():
    """The validator does NOT enforce per-actor uniqueness across
    clusters: the same actor may legitimately voice multiple positions
    and appear in two cluster sub-lists."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Cluster A",
            "source_ids": ["src-001"],
            "stated": ["actor-001"],
            "reported": [],
            "mentioned": [],
        },
        {
            "position_label": "Cluster B",
            "source_ids": ["src-002"],
            "stated": ["actor-001", "actor-002"],
            "reported": [],
            "mentioned": [],
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


def test_empty_sublists_yield_empty_actor_ids():
    """A cluster whose agent output omits all three sub-lists ends up
    with empty sub-lists and an empty derived ``actor_ids[]`` — not a
    missing key — so downstream consumers can rely on the fields being
    present."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {"position_label": "X", "source_ids": ["src-001"]},  # no sub-lists
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["actor_ids"] == []
    assert cluster["n_actors"] == 0
    assert cluster["stated"] == []
    assert cluster["reported"] == []
    assert cluster["mentioned"] == []


# ---------------------------------------------------------------------------
# Unknown-ID dropping
# ---------------------------------------------------------------------------


def test_unknown_id_dropped_from_sublist(caplog):
    """A sub-list ID that fails canonical-actor validation is dropped
    with a warning identifying the sub-list."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
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
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "actor-999" in m and "'reported'" in m for m in messages
    ), messages


def test_unknown_id_warning_names_correct_tier(caplog):
    """The warning message names the specific sub-list (``stated`` /
    ``reported`` / ``mentioned``) where the offending ID appeared."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "stated": ["actor-001", "actor-999"],
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


# ---------------------------------------------------------------------------
# Cross-tier deduplication and partition invariant
# ---------------------------------------------------------------------------


def test_cross_tier_duplicate_resolved_priority_stated_first(caplog):
    """An ID appearing in two sub-lists is kept in the higher-priority
    tier (stated > reported > mentioned). A warning fires naming both
    tiers."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
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
    assert cluster["actor_ids"] == ["actor-001"]
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "'stated'" in m and "'reported'" in m for m in messages
    ), messages


def test_partition_invariant_after_cross_tier_repair():
    """After cross-tier dedup, the union of the three sub-lists equals
    the derived ``actor_ids`` and the three sub-lists are pairwise
    disjoint."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "stated": ["actor-001", "actor-002"],
            "reported": ["actor-002"],  # duplicate of stated
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
    stated = set(cluster["stated"])
    reported = set(cluster["reported"])
    mentioned = set(cluster["mentioned"])
    actor_ids = set(cluster["actor_ids"])
    # Cross-tier dedup kept actor-002 in stated (higher priority).
    assert stated == {"actor-001", "actor-002"}
    assert reported == set()
    assert mentioned == {"actor-003"}
    # Union equals actor_ids; pairwise disjoint.
    assert stated | reported | mentioned == actor_ids
    assert stated & reported == set()
    assert stated & mentioned == set()
    assert reported & mentioned == set()


def test_invariant_assertion_fires_on_union_mismatch():
    """The invariant helper raises AssertionError when the sub-list
    union does not equal the supplied ``actor_ids`` set. Synthesised by
    passing a sub-list configuration whose union has fewer members than
    the supplied actor-id set."""
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
