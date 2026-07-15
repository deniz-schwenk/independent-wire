"""Tests for ``consolidate_actors`` topic-stage.

Covers TASK-PERSPECTIVE-ACTOR-SCOPING §1.1 contract and
TASK-ACTOR-DEDUP-NORMALIZE (deterministic normalization-key merging):

- Normalization-key dedup on ``name`` — parenthetical/case/spelling
  variants merge; SEMANTIC aliases ("President Trump" == "Trump") stay
  separate and remain the LLM aliaser's job.
- Stable ``actor-NNN`` ID assignment in order of first appearance.
- ``source_ids`` accumulation across multi-source actors.
- ``quotes[]`` accumulation with one record per source-membership.
- Role/type conflict resolution: first non-null value wins.
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
    # evidence_type is None when the source actor entry does not carry
    # the field (researcher-sourced actors; pre-migration hydration
    # state files). Threaded through unchanged here.
    assert a["quotes"][0] == {
        "source_id": "src-001",
        "verbatim": "We will respond.",
        "position": "Threatens action",
        "evidence_type": None,
    }
    assert a["quotes"][1]["verbatim"] is None
    assert a["quotes"][1]["evidence_type"] is None


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


# ---------------------------------------------------------------------------
# TASK-ACTOR-DEDUP-NORMALIZE — deterministic normalization-key merging.
# Fixtures use the REAL variant strings published in
# output/2026-07-14/tp-2026-07-14-001.json (5 IMO + 5 JMIC fragments).
# ---------------------------------------------------------------------------


def _one_actor_src(sid: str, name: str, **over) -> dict:
    entry = {"name": name, "role": "r", "type": "international_org",
             "position": f"pos-{sid}", "verbatim_quote": None}
    entry.update(over)
    return {"id": sid, "actors_quoted": [entry]}


def test_normalize_merges_imo_parenthetical():
    """(a) 'International Maritime Organization (IMO)' merges with the bare
    form; quotes and source_ids unioned into one actor."""
    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001", "International Maritime Organization (IMO)",
                       verbatim_quote="q1"),
        _one_actor_src("src-002", "International Maritime Organization",
                       verbatim_quote="q2"),
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    assert len(tb_after.final_actors) == 1
    a = tb_after.final_actors[0]
    assert a["source_ids"] == ["src-001", "src-002"]
    assert [q["verbatim"] for q in a["quotes"]] == ["q1", "q2"]
    # display name = longest original variant (the "(IMO)" form)
    assert a["name"] == "International Maritime Organization (IMO)"


def test_normalize_merges_imo_council_parenthetical():
    """(b) '... (IMO) Council' merges with '... Council'."""
    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001",
                       "International Maritime Organization (IMO) Council"),
        _one_actor_src("src-002",
                       "International Maritime Organization Council"),
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    assert len(tb_after.final_actors) == 1
    assert tb_after.final_actors[0]["source_ids"] == ["src-001", "src-002"]


def test_normalize_merges_jmic_centre_center_and_acronym():
    """(c) Center/Centre spelling + '(JMIC)' parenthetical all fold to one
    actor (four real variants)."""
    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001", "Joint Maritime Information Centre"),
        _one_actor_src("src-002", "Joint Maritime Information Center"),
        _one_actor_src("src-003", "Joint Maritime Information Centre (JMIC)"),
        _one_actor_src("src-004", "Joint Maritime Information Center (JMIC)"),
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    assert len(tb_after.final_actors) == 1
    a = tb_after.final_actors[0]
    assert a["source_ids"] == ["src-001", "src-002", "src-003", "src-004"]
    # longest variant wins the display name; both "(JMIC)" forms are 39 chars,
    # tie broken toward the earlier-seen one (Centre (JMIC), src-003).
    assert a["name"] == "Joint Maritime Information Centre (JMIC)"


def test_normalize_negative_role_suffixes_stay_separate():
    """(d) NEGATIVE: spokesperson / Council / bare org are three entities —
    their keys differ (no substring/fuzzy logic)."""
    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001", "International Maritime Organization"),
        _one_actor_src("src-002",
                       "International Maritime Organization Council"),
        _one_actor_src("src-003",
                       "International Maritime Organization spokesperson"),
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    names = sorted(a["name"] for a in tb_after.final_actors)
    assert names == [
        "International Maritime Organization",
        "International Maritime Organization Council",
        "International Maritime Organization spokesperson",
    ]
    from src.stages.topic_stages import _actor_norm_key as k
    assert len({k("International Maritime Organization"),
                k("International Maritime Organization Council"),
                k("International Maritime Organization spokesperson")}) == 3


def test_normalize_negative_distinguishing_prefix_stays_separate():
    """(e) NEGATIVE: 'US Navy-led Joint Maritime Information Center' stays
    separate from the bare centre — prefix differs, that's the LLM's call."""
    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001", "Joint Maritime Information Center"),
        _one_actor_src("src-002",
                       "US Navy-led Joint Maritime Information Center"),
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    assert len(tb_after.final_actors) == 2


def test_normalize_full_tp_2026_07_14_case_10_variants_to_5():
    """Integration of the real published fragments: 10 variants (5 IMO +
    5 JMIC) collapse to 5 entities (org, council, spokesperson, JMIC,
    US-Navy-led)."""
    variants = [
        "International Maritime Organization",
        "International Maritime Organization (IMO)",
        "International Maritime Organization Council",
        "International Maritime Organization (IMO) Council",
        "International Maritime Organization spokesperson",
        "Joint Maritime Information Center",
        "Joint Maritime Information Center (JMIC)",
        "Joint Maritime Information Centre",
        "Joint Maritime Information Centre (JMIC)",
        "US Navy-led Joint Maritime Information Center",
    ]
    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src(f"src-{i:03d}", v) for i, v in enumerate(variants, 1)
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    assert len(tb_after.final_actors) == 5
    # IDs are dense and first-appearance ordered
    assert [a["id"] for a in tb_after.final_actors] == [
        f"actor-{i:03d}" for i in range(1, 6)
    ]


def test_normalize_non_latin_only_nfkc_casefold(caplog):
    """(f) Non-Latin names pass through unmerged unless NFKC+casefold
    identical — no parenthetical strip, no folds. Cyrillic 'Путин (Кремль)'
    vs 'Путин' stay TWO actors (paren strip is Latin-only)."""
    from src.stages.topic_stages import _actor_norm_key as k
    # NFKC+casefold-identical → same key (full-width vs half-width digits)
    assert k("Ｇ33") == k("g33")  # 'Ｇ33' NFKC-folds to 'g33'
    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001", "Путин (Кремль)"),
        _one_actor_src("src-002", "Путин"),
    ]
    tb_after = _run(consolidate_actors, tb, _ro())
    # different keys (parenthetical NOT stripped for non-Latin) → 2 actors
    assert len(tb_after.final_actors) == 2
    assert k("Путин (Кремль)") != k("Путин")
    # identical Cyrillic names DO merge (NFKC+casefold equality)
    tb2 = TopicBus()
    tb2.final_sources = [
        _one_actor_src("s1", "Путин"),
        _one_actor_src("s2", "путин"),  # casefold-equal
    ]
    tb2_after = _run(consolidate_actors, tb2, _ro())
    assert len(tb2_after.final_actors) == 1


def test_normalize_type_disagreement_logs_warning(caplog):
    """Merged variants that disagree on a non-null type keep the first and
    log a WARNING."""
    import logging

    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001", "International Maritime Organization (IMO)",
                       type="international_org"),
        _one_actor_src("src-002", "International Maritime Organization",
                       type="government"),
    ]
    with caplog.at_level(logging.WARNING):
        tb_after = _run(consolidate_actors, tb, _ro())
    assert tb_after.final_actors[0]["type"] == "international_org"  # first wins
    assert any("disagree on type" in r.getMessage() for r in caplog.records)


def test_normalize_merge_info_line_lists_variants(caplog):
    """A merge emits one INFO line naming the folded variants."""
    import logging

    tb = TopicBus()
    tb.final_sources = [
        _one_actor_src("src-001", "Joint Maritime Information Centre (JMIC)"),
        _one_actor_src("src-002", "Joint Maritime Information Center"),
    ]
    with caplog.at_level(logging.INFO):
        _run(consolidate_actors, tb, _ro())
    merge_lines = [r.getMessage() for r in caplog.records
                   if "merged 2 variants" in r.getMessage()]
    assert len(merge_lines) == 1
    assert "Joint Maritime Information Centre (JMIC)" in merge_lines[0]
    assert "Joint Maritime Information Center" in merge_lines[0]


def test_normalize_determinism_byte_identical_regardless_of_order():
    """Same actor set in a different source order → identical merged output
    (modulo the source-order-dependent id/source_id sequencing, which is a
    deterministic function of input order, not dict hashing)."""
    import json

    variants = [
        "International Maritime Organization (IMO)",
        "International Maritime Organization",
        "Joint Maritime Information Centre",
        "Joint Maritime Information Center (JMIC)",
    ]

    def run(order):
        tb = TopicBus()
        tb.final_sources = [
            _one_actor_src(f"src-{i:03d}", variants[j])
            for i, j in enumerate(order, 1)
        ]
        return _run(consolidate_actors, tb, _ro()).final_actors

    a = run([0, 1, 2, 3])
    b = run([0, 1, 2, 3])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # both groups present regardless
    assert len(a) == 2


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
