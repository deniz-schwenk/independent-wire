"""Tests for the deterministic stage
``partition_canonical_actors_by_evidence`` and the related pool-source
consistency check in ``_enrich_position_clusters_logic``.

Covers:

- Single-tier actor: an actor with all quotes carrying the same
  ``evidence_type`` lands in exactly one pool.
- Cross-form actor: an actor with quotes spanning multiple evidence
  tiers appears in the matching pools, each entry holding the
  evidence-matched quote subset and source_id subset.
- Missing evidence_type policy: quotes with ``None`` /
  missing-key ``evidence_type`` default to ``reported`` (the neutral
  middle tier), and the defaulted count is logged once per topic.
- Empty input: stage is a no-op when ``canonical_actors`` is empty.
- Pool-source consistency: the validator drops cluster sub-list IDs
  that do not appear in the matching pool, with a warning naming both
  the offending tier and the pool(s) the actor is actually present in.
- Pool-source no-op: when the three pool slots are empty (e.g. a
  smoke that bypasses the partition stage), the validator falls back
  to the unified-list check alone.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from src.bus import RunBus, TopicBus
from src.stages.topic_stages import (
    enrich_perspective_clusters,
    partition_canonical_actors_by_evidence,
)


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


# ---------------------------------------------------------------------------
# partition_canonical_actors_by_evidence
# ---------------------------------------------------------------------------


def test_partition_single_tier_actor():
    """An actor whose every quote has the same ``evidence_type`` lands
    in exactly one pool — only that pool's entry references the actor."""
    tb = TopicBus()
    tb.canonical_actors = [
        {
            "id": "actor-001",
            "name": "Putin",
            "role": "President",
            "type": "government",
            "is_anonymous": False,
            "source_ids": ["src-001", "src-002"],
            "quotes": [
                {
                    "source_id": "src-001",
                    "verbatim": None,
                    "position": "p1",
                    "evidence_type": "stated",
                },
                {
                    "source_id": "src-002",
                    "verbatim": None,
                    "position": "p2",
                    "evidence_type": "stated",
                },
            ],
        },
    ]
    tb_after = _run(partition_canonical_actors_by_evidence, tb, _ro())
    assert len(tb_after.canonical_actors_stated) == 1
    assert tb_after.canonical_actors_reported == []
    assert tb_after.canonical_actors_mentioned == []
    entry = tb_after.canonical_actors_stated[0]
    assert entry["id"] == "actor-001"
    assert entry["source_ids"] == ["src-001", "src-002"]
    assert len(entry["quotes"]) == 2


def test_partition_cross_form_actor_appears_in_multiple_pools():
    """An actor with quotes spanning multiple tiers shows up in each
    matching pool, each pool entry holding the evidence-matched quote
    subset and the source_ids referenced by those quotes only."""
    tb = TopicBus()
    tb.canonical_actors = [
        {
            "id": "actor-002",
            "name": "Zelensky",
            "role": "President",
            "type": "government",
            "is_anonymous": False,
            "source_ids": ["src-001", "src-002", "src-003"],
            "quotes": [
                {
                    "source_id": "src-001",
                    "verbatim": "We will defend",
                    "position": "stated_pos",
                    "evidence_type": "stated",
                },
                {
                    "source_id": "src-002",
                    "verbatim": None,
                    "position": "reported_pos",
                    "evidence_type": "reported",
                },
                {
                    "source_id": "src-003",
                    "verbatim": None,
                    "position": "mentioned_pos",
                    "evidence_type": "mentioned",
                },
            ],
        },
    ]
    tb_after = _run(partition_canonical_actors_by_evidence, tb, _ro())
    assert len(tb_after.canonical_actors_stated) == 1
    assert len(tb_after.canonical_actors_reported) == 1
    assert len(tb_after.canonical_actors_mentioned) == 1
    s = tb_after.canonical_actors_stated[0]
    r = tb_after.canonical_actors_reported[0]
    m = tb_after.canonical_actors_mentioned[0]
    # Each pool entry filtered to its tier's quotes.
    assert s["source_ids"] == ["src-001"]
    assert r["source_ids"] == ["src-002"]
    assert m["source_ids"] == ["src-003"]
    assert s["quotes"][0]["position"] == "stated_pos"
    assert r["quotes"][0]["position"] == "reported_pos"
    assert m["quotes"][0]["position"] == "mentioned_pos"


def test_partition_default_missing_evidence_type_to_reported(caplog):
    """A quote with ``evidence_type=None`` (or missing key) defaults to
    the ``reported`` tier. The default is logged once per topic with
    the tally."""
    tb = TopicBus()
    tb.canonical_actors = [
        {
            "id": "actor-001",
            "name": "Researcher-sourced actor",
            "role": "analyst",
            "type": "academia",
            "is_anonymous": False,
            "source_ids": ["src-001", "src-002"],
            "quotes": [
                {
                    "source_id": "src-001",
                    "verbatim": None,
                    "position": "p1",
                    "evidence_type": None,
                },
                {
                    # missing evidence_type key
                    "source_id": "src-002",
                    "verbatim": None,
                    "position": "p2",
                },
            ],
        },
    ]
    with caplog.at_level(logging.INFO, logger="src.stages.topic_stages"):
        tb_after = _run(partition_canonical_actors_by_evidence, tb, _ro())
    assert tb_after.canonical_actors_stated == []
    assert len(tb_after.canonical_actors_reported) == 1
    assert tb_after.canonical_actors_mentioned == []
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "defaulted" in m and "reported" in m for m in messages
    ), messages


def test_partition_empty_input_is_no_op():
    """Empty canonical_actors → all three pools stay at empty defaults
    and the stage returns the bus unchanged."""
    tb = TopicBus()
    tb.canonical_actors = []
    tb_after = _run(partition_canonical_actors_by_evidence, tb, _ro())
    assert tb_after.canonical_actors_stated == []
    assert tb_after.canonical_actors_reported == []
    assert tb_after.canonical_actors_mentioned == []


def test_partition_preserves_identity_fields():
    """Pool entries preserve the actor's id, name, role, type,
    is_anonymous from the canonical_actors entry."""
    tb = TopicBus()
    tb.canonical_actors = [
        {
            "id": "actor-001",
            "name": "Anonymous Source",
            "role": "anonymous official",
            "type": "government",
            "is_anonymous": True,
            "source_ids": ["src-001"],
            "quotes": [
                {
                    "source_id": "src-001",
                    "verbatim": None,
                    "position": "p",
                    "evidence_type": "reported",
                },
            ],
        },
    ]
    tb_after = _run(partition_canonical_actors_by_evidence, tb, _ro())
    entry = tb_after.canonical_actors_reported[0]
    assert entry["id"] == "actor-001"
    assert entry["name"] == "Anonymous Source"
    assert entry["role"] == "anonymous official"
    assert entry["type"] == "government"
    assert entry["is_anonymous"] is True


# ---------------------------------------------------------------------------
# Pool-source consistency check in enrich_perspective_clusters
# ---------------------------------------------------------------------------


def test_validator_drops_actor_not_in_matching_pool(caplog):
    """If cluster.stated references an actor that is not in
    canonical_actors_stated (but is in another pool), the validator
    drops the entry and warns naming the offending tier and the actual
    pool of origin."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "stated": ["actor-001"],  # WRONG — actor-001 is in reported pool
            "reported": [],
            "mentioned": [],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    # actor-001 is in REPORTED pool, not STATED
    tb.canonical_actors_stated = []
    tb.canonical_actors_reported = [{"id": "actor-001", "name": "A"}]
    tb.canonical_actors_mentioned = []

    with caplog.at_level(logging.WARNING, logger="src.stages.topic_stages"):
        tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    # Dropped — validator does NOT silently relocate to reported.
    assert cluster["stated"] == []
    assert cluster["reported"] == []
    assert cluster["actor_ids"] == []
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "actor-001" in m and "canonical_actors_stated" in m
        and "reported" in m
        for m in messages
    ), messages


def test_validator_passes_actor_in_matching_pool():
    """If the agent places the actor in the correct sub-list, the
    pool-source check passes silently."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "stated": ["actor-001"],
            "reported": ["actor-002"],
            "mentioned": [],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    tb.canonical_actors_stated = [{"id": "actor-001", "name": "A"}]
    tb.canonical_actors_reported = [{"id": "actor-002", "name": "B"}]
    tb.canonical_actors_mentioned = []
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["stated"] == ["actor-001"]
    assert cluster["reported"] == ["actor-002"]
    assert cluster["actor_ids"] == ["actor-001", "actor-002"]


def test_validator_pool_check_noop_when_pools_empty():
    """When all three pool slots are empty (legacy smoke that bypasses
    the partition stage), the pool-source check is a no-op and only the
    unified-list check applies."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "stated": ["actor-001"],
            "reported": [],
            "mentioned": [],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    # All three pool slots empty — legacy/partition-bypassed path
    tb.canonical_actors_stated = []
    tb.canonical_actors_reported = []
    tb.canonical_actors_mentioned = []
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    # Pool check skipped; unified-list check passed.
    assert cluster["stated"] == ["actor-001"]
    assert cluster["actor_ids"] == ["actor-001"]


def test_validator_cross_pool_drift_caught_for_each_tier(caplog):
    """An actor placed in the wrong sub-list is dropped regardless of
    which sub-list (stated / reported / mentioned)."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "Pro",
            "source_ids": ["src-001"],
            "stated": [],
            "reported": ["actor-001"],  # WRONG — actor-001 is in stated pool
            "mentioned": [],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    tb.canonical_actors_stated = [{"id": "actor-001", "name": "A"}]
    tb.canonical_actors_reported = []
    tb.canonical_actors_mentioned = []
    with caplog.at_level(logging.WARNING, logger="src.stages.topic_stages"):
        tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["reported"] == []
    assert cluster["actor_ids"] == []
    messages = [r.getMessage() for r in caplog.records]
    assert any(
        "actor-001" in m and "canonical_actors_reported" in m
        for m in messages
    ), messages
