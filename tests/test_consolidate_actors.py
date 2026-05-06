"""Tests for ``consolidate_actors`` topic-stage.

Covers TASK-PERSPECTIVE-ACTOR-SCOPING §1.1 contract:

- Exact-string-match dedup on ``name`` (F2 — no normalisation).
- Stable ``actor-NNN`` ID assignment in order of first appearance.
- ``source_ids`` accumulation across multi-source actors.
- ``quotes[]`` accumulation with one record per source-membership.
- Role/type conflict resolution: first encountered value wins.
- Empty / missing-field defensive paths.
- Post-A2 invariant: ``type=media`` entries are absent because
  ``filter_media_actors_quoted`` ran upstream — re-asserted here as a
  smoke for the stage ordering.
"""

from __future__ import annotations

import asyncio

from src.bus import RunBus, TopicBus
from src.stage import get_stage_meta
from src.stages.topic_stages import consolidate_actors


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus = None):
    return (rb or RunBus()).as_readonly()


def test_consolidate_actors_metadata():
    meta = get_stage_meta(consolidate_actors)
    assert meta.kind == "topic"
    assert meta.reads == ("final_sources",)
    assert meta.writes == ("final_actors",)


def test_consolidate_actors_dedup_on_exact_name_match():
    """Two sources, same actor name. One ``actor-NNN`` entry, both
    sources accumulated in ``source_ids``, two quote records."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {
                    "name": "Donald Trump",
                    "role": "President",
                    "type": "government",
                    "position": "Threatens action",
                    "verbatim_quote": "We will respond.",
                },
            ],
        },
        {
            "id": "src-002",
            "actors_quoted": [
                {
                    "name": "Donald Trump",
                    "role": "President",
                    "type": "government",
                    "position": "Repeats threat",
                    "verbatim_quote": None,
                },
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    actors = tb_after.final_actors
    assert len(actors) == 1
    a = actors[0]
    assert a["id"] == "actor-001"
    assert a["name"] == "Donald Trump"
    assert a["source_ids"] == ["src-001", "src-002"]
    assert len(a["quotes"]) == 2
    assert a["quotes"][0] == {
        "source_id": "src-001",
        "verbatim": "We will respond.",
        "position": "Threatens action",
    }
    assert a["quotes"][1]["verbatim"] is None


def test_consolidate_actors_no_alias_resolution_per_F2():
    """F2 baseline: alias variants of the same person are NOT collapsed.
    Three IDs are assigned, alias-dedup is a deferred workstream."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {"name": "Donald Trump", "role": "P", "type": "government",
                 "position": "p1", "verbatim_quote": None},
                {"name": "President Trump", "role": "P", "type": "government",
                 "position": "p2", "verbatim_quote": None},
                {"name": "Trump", "role": "P", "type": "government",
                 "position": "p3", "verbatim_quote": None},
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    names = [a["name"] for a in tb_after.final_actors]
    ids = [a["id"] for a in tb_after.final_actors]
    assert names == ["Donald Trump", "President Trump", "Trump"]
    assert ids == ["actor-001", "actor-002", "actor-003"]


def test_consolidate_actors_id_assignment_in_first_appearance_order():
    """IDs are 1-based zero-padded; the first actor encountered (in
    source-array order, then per-source actor-array order) gets
    actor-001."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {"name": "Bob", "role": "r", "type": "t", "position": "p"},
            ],
        },
        {
            "id": "src-002",
            "actors_quoted": [
                {"name": "Carol", "role": "r", "type": "t", "position": "p"},
                {"name": "Bob", "role": "r", "type": "t", "position": "p"},
                {"name": "Alice", "role": "r", "type": "t", "position": "p"},
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    by_name = {a["name"]: a["id"] for a in tb_after.final_actors}
    assert by_name == {
        "Bob": "actor-001",
        "Carol": "actor-002",
        "Alice": "actor-003",
    }


def test_consolidate_actors_role_type_conflict_first_wins():
    """When the same actor name is classified with different role/type
    in two sources, the first encountered values win."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {
                    "name": "EU Council",
                    "role": "Council President",
                    "type": "international_org",
                    "position": "p1",
                    "verbatim_quote": None,
                },
            ],
        },
        {
            "id": "src-002",
            "actors_quoted": [
                {
                    "name": "EU Council",
                    "role": "Heads of State",
                    "type": "government",
                    "position": "p2",
                    "verbatim_quote": None,
                },
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    a = tb_after.final_actors[0]
    assert a["role"] == "Council President"
    assert a["type"] == "international_org"


def test_consolidate_actors_source_ids_dedup_within_source():
    """A single source listing the same actor twice yields one entry in
    ``source_ids`` (no double-counting) but two quote records."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {"name": "Macron", "role": "P", "type": "government",
                 "position": "calls for restraint", "verbatim_quote": None},
                {"name": "Macron", "role": "P", "type": "government",
                 "position": "warns of escalation", "verbatim_quote": "warning"},
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    a = tb_after.final_actors[0]
    assert a["source_ids"] == ["src-001"]
    assert len(a["quotes"]) == 2


def test_consolidate_actors_empty_input_is_no_op():
    """Empty ``final_sources`` → bus passes through unchanged; the
    optional_write annotation on ``final_actors`` covers post-validation."""
    tb = TopicBus()
    tb.final_sources = []
    tb_after = _run(consolidate_actors, tb, _ro())
    assert tb_after.final_actors == []


def test_consolidate_actors_handles_missing_or_invalid_fields():
    """Defensive: non-dict sources, sources without ``id``, sources with
    no ``actors_quoted``, non-dict actor entries, and entries with empty
    or missing ``name`` are all silently ignored."""
    tb = TopicBus()
    tb.final_sources = [
        "not-a-dict",
        {"id": "", "actors_quoted": [{"name": "X"}]},  # missing id → skip
        {"id": "src-002"},  # no actors_quoted → fine
        {"id": "src-003", "actors_quoted": "not-a-list"},
        {
            "id": "src-004",
            "actors_quoted": [
                "not-a-dict-actor",
                {"name": ""},  # empty name → skip
                {"role": "no-name"},  # missing name → skip
                {"name": "Real",
                 "role": "r", "type": "t", "position": "p"},
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    assert [a["name"] for a in tb_after.final_actors] == ["Real"]
    assert tb_after.final_actors[0]["source_ids"] == ["src-004"]


def test_consolidate_actors_verbatim_normalized_to_none():
    """Empty / non-string ``verbatim_quote`` values are normalised to
    ``None`` in the output quote record."""
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {"name": "A", "role": "r", "type": "t", "position": "p",
                 "verbatim_quote": ""},
                {"name": "B", "role": "r", "type": "t", "position": "p"},
                {"name": "C", "role": "r", "type": "t", "position": "p",
                 "verbatim_quote": "real"},
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    quotes = {a["name"]: a["quotes"][0]["verbatim"]
              for a in tb_after.final_actors}
    assert quotes == {"A": None, "B": None, "C": "real"}


def test_consolidate_actors_post_filter_media_invariant():
    """Smoke: with ``filter_media_actors_quoted`` upstream, no
    ``type=media`` entries should reach this stage. The stage doesn't
    re-filter media itself — it trusts the upstream invariant — but the
    invariant is asserted here so a stage-order regression surfaces.
    The fixture below mimics post-A2 input (no media types present).
    """
    tb = TopicBus()
    tb.final_sources = [
        {
            "id": "src-001",
            "actors_quoted": [
                {"name": "Spokesperson", "role": "r", "type": "government",
                 "position": "p"},
                {"name": "Researcher", "role": "r", "type": "academia",
                 "position": "p"},
            ],
        },
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    types = {a["type"] for a in tb_after.final_actors}
    assert "media" not in types
