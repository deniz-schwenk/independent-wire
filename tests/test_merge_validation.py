"""Deterministic merge validation (TASK-MERGE-VALIDATION).

The resolver's other failure mode, and the worse one. Empty output degrades a
dossier visibly; a hallucinated merge degrades it invisibly — the package
simply asserts fewer, wronger actors, and a reader has no way to tell. On
2026-07-27 forty-six distinct German politicians were merged into one actor in
a PUBLISHED dossier (tp-2026-07-27-003).

Every case below is a real pair from the historical corpus, with real role
text. Inventory and the measured trade-off: scratch/audit/merge-validation/.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from src.agent_stages import (
    COLLAPSE_SHAPE_MIN_ALIASES, ResolveActorAliasesStage, collapse_shape_groups,
    merge_signals, validate_merges,
)


def A(i, name, role="", **kw):
    return {"id": f"actor-{i:03d}", "name": name, "role": role,
            "type": "individual", "source_ids": [f"src-{i:03d}"],
            "quotes": [], **kw}


# --- direction 1: hallucinated merges are rejected ---------------------------
# The five the brief requires. Each is a verified resolver error.

@pytest.mark.parametrize("a,c", [
    (A(1, "Marco Rubio", "Secretary of State of the United States"),
     A(2, "Donald Trump", "President of the United States")),
    (A(1, "Kevin Warsh", "Federal Reserve Chair"),
     A(2, "Jerome Powell", "Former Fed chair")),
    (A(1, "Mark Levine", "New York City Comptroller"),
     A(2, "Thomas DiNapoli", "New York State Comptroller")),
    (A(1, "Marcie Frost", "CEO of the California Public Employees' "
                          "Retirement System"),
     A(2, "Thomas DiNapoli", "New York State Comptroller")),
    (A(1, "Friedrich Merz", "German Chancellor"),
     A(2, "Iris Spranger", "Berlin Senator for the Interior")),
])
def test_the_known_hallucinations_carry_no_signal(a, c):
    assert merge_signals(a, c) == [], (a["name"], c["name"])


def test_levine_dinapoli_is_why_role_similarity_was_rejected():
    """'New York City Comptroller' and 'New York State Comptroller' share three
    of four tokens and are two different offices held by two different people.
    Any role-similarity threshold loose enough to excuse the corpus's
    cross-language institution merges also excuses this one — which is why the
    detector has no role-overlap signal. Measured in REPORT.md section 4."""
    a = A(1, "Mark Levine", "New York City Comptroller")
    c = A(2, "Thomas DiNapoli", "New York State Comptroller")
    ra, rc = set("new york city comptroller".split()), set("new york state comptroller".split())
    assert len(ra & rc) / len(ra | rc) >= 0.6, "the roles really are that similar"
    assert merge_signals(a, c) == []


# --- direction 2: legitimate merges survive ----------------------------------

@pytest.mark.parametrize("a,c,signal", [
    # spelling / transliteration drift
    (A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"), "name_shared"),
    (A(1, "Andriy Sybiga"), A(2, "Andrii Sybiha"), "name_variant"),
    # acronym expansion
    (A(1, "Islamic Revolutionary Guard Corps"), A(2, "IRGC"), "acronym"),
    # cross-script name with a Latin gloss
    (A(1, "الجيش الإسرا"
          "ئيلي (Israeli military)"),
     A(2, "Israeli military"), "gloss"),
    # person <-> the institution their role names
    (A(1, "Tim Hawkins", "Spokesperson for US Central Command"),
     A(2, "US Central Command (Centcom)", "US military command"), "role_link"),
    (A(1, "Matthew Diller", "President, New York City Bar Association"),
     A(2, "New York City Bar Association", "Professional legal organization"),
     "role_link"),
    # one-token canonical inside a role
    (A(1, "Sheikh Mohammed bin Abdulrahman Al Thani", "Prime Minister of Qatar"),
     A(2, "Qatar", "Government of Qatar"), "role_link"),
    # cross-language institution, matched through the role
    (A(1, "Ministère britannique des Affaires étrangères",
        "UK Foreign Office"),
     A(2, "British Foreign Office", "British government's foreign ministry"),
     "role_link"),
])
def test_legitimate_merges_keep_their_signal(a, c, signal):
    assert signal in merge_signals(a, c), (a["name"], c["name"])


def test_cross_script_is_an_abstention_not_evidence():
    """A Cyrillic name and a Latin one share no characters by construction, so
    a transliteration merge is indistinguishable from an invented one without
    transliterating. The guard abstains rather than accusing."""
    a = A(1, "Володимир "
             "Зеленський")
    c = A(2, "Volodymyr Zelensky")
    sig = merge_signals(a, c)
    assert sig == ["cross_script"]
    kept, rejected = validate_merges(
        [{"alias_id": "actor-001", "canonical_id": "actor-002"}],
        {"actor-001": a, "actor-002": c})
    assert rejected == [] and len(kept) == 1


# --- validate_merges bookkeeping ---------------------------------------------

def _rubio_case():
    actors = {a["id"]: a for a in [
        A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
        A(3, "Marco Rubio", "Secretary of State of the United States"),
        A(4, "Donald Trump", "President of the United States")]}
    pairs = [{"alias_id": "actor-001", "canonical_id": "actor-002"},
             {"alias_id": "actor-003", "canonical_id": "actor-004"}]
    return actors, pairs


def test_detector_mode_is_the_default():
    from src.agent_stages import MERGE_VALIDATION_MODE
    assert MERGE_VALIDATION_MODE == "detector"


def test_detector_mode_keeps_every_merge_and_still_counts():
    """The shipped mode. Zero behaviour change on the product: `kept` is the
    input, unchanged and in order, while `rejected` still names what reject
    mode would have removed."""
    actors, pairs = _rubio_case()

    kept, flagged = validate_merges(pairs, actors, mode="detector")

    assert kept == pairs, "detector mode must not alter merge output at all"
    assert len(flagged) == 1
    assert flagged[0]["alias_name"] == "Marco Rubio"
    assert flagged[0]["canonical_name"] == "Donald Trump"


def test_reject_mode_drops_what_detector_mode_counts():
    """Detection is identical in both modes; only the drop differs. Asserted
    against each other rather than separately, so the two cannot drift."""
    actors, pairs = _rubio_case()

    kept_d, flagged_d = validate_merges(pairs, actors, mode="detector")
    kept_r, flagged_r = validate_merges(pairs, actors, mode="reject")

    assert flagged_d == flagged_r, "the COUNT is the same in both modes"
    assert kept_r == [p for p in kept_d if p not in flagged_ids(flagged_r, kept_d)]
    assert kept_r == [pairs[0]]
    assert len(kept_d) - len(kept_r) == len(flagged_r)


def flagged_ids(flagged, pairs):
    keys = {(f["alias_id"], f["canonical_id"]) for f in flagged}
    return [p for p in pairs if (p["alias_id"], p["canonical_id"]) in keys]


def test_an_unknown_mode_is_refused_rather_than_guessed():
    actors, pairs = _rubio_case()
    with pytest.raises(ValueError, match="unknown mode"):
        validate_merges(pairs, actors, mode="drop-everything")


def test_unknown_ids_are_left_to_the_existing_id_validation():
    """Not this guard's job to police ids — judging a pair whose actors it
    cannot look up would reject on missing data rather than on evidence."""
    kept, rejected = validate_merges(
        [{"alias_id": "actor-999", "canonical_id": "actor-001"}],
        {"actor-001": A(1, "Donald Trump")})
    assert rejected == [] and len(kept) == 1


# --- the stage ---------------------------------------------------------------

class _Agent:
    def __init__(self, structured):
        self.model, self.provider = "m", "p"
        self.temperature, self.max_tokens, self.reasoning = 0.5, 16000, "low"
        self._s = structured
        self.last_cost_usd, self.last_tokens = 0.0, 0

    async def run(self, message="", context=None, **kw):
        from src.agent import AgentResult
        return AgentResult(content="", structured=self._s, cost_usd=0.001,
                           tokens_used=10, response_id="r", model=self.model,
                           provider=self.provider)

    def reset_call_metrics(self):
        pass


def _run(stage, tb, rb):
    return asyncio.run(stage(tb, rb))


def _bus(actors):
    from src.bus import EditorAssignment, RunBus, TopicBus
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.final_actors = actors
    return tb, RunBus().as_readonly()


def test_stage_in_detector_mode_flags_but_still_merges(caplog):
    """The shipped behaviour. Rubio is still merged into Trump — the product is
    exactly as it was — and the run log now says so out loud."""
    actors = [A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
              A(3, "Marco Rubio", "Secretary of State of the United States"),
              A(4, "Donald Trump", "President of the United States")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"},
        {"alias_id": "actor-003", "canonical_id": "actor-004"}],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)
    tb, rb = _bus(actors)

    with caplog.at_level(logging.ERROR, logger="src.agent_stages"):
        out = _run(stage, tb, rb)

    # first-source-wins picks the SMALLER numeric id as canonical, so pairs are
    # recorded 002 -> 001; compare unordered.
    merged = {frozenset((m["alias_id"], m["canonical_id"]))
              for m in out.actor_alias_mapping}
    assert frozenset(("actor-001", "actor-002")) in merged
    assert frozenset(("actor-003", "actor-004")) in merged, (
        "detector mode must not change the merge result")
    assert "FLAGGED 1 of 2" in caplog.text
    assert "DETECTOR MODE" in caplog.text
    assert "'Marco Rubio' -> 'Donald Trump'" in caplog.text
    assert stage.last_rejected_merges[0]["alias_name"] == "Marco Rubio"


def test_reject_mode_would_have_kept_rubio_separate(monkeypatch):
    """The capability that stays wired behind the mode: with the drop enabled,
    Rubio survives as his own canonical entry instead of vanishing into Trump.
    Nothing in the tree sets this today."""
    import src.agent_stages as ags
    monkeypatch.setattr(ags, "MERGE_VALIDATION_MODE", "reject")

    actors = [A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
              A(3, "Marco Rubio", "Secretary of State of the United States"),
              A(4, "Donald Trump", "President of the United States")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"},
        {"alias_id": "actor-003", "canonical_id": "actor-004"}],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)
    out = _run(stage, *_bus(actors))

    merged = {frozenset((m["alias_id"], m["canonical_id"]))
              for m in out.actor_alias_mapping}
    assert frozenset(("actor-003", "actor-004")) not in merged
    assert "actor-003" in {a["id"] for a in out.canonical_actors}


def test_rejection_is_a_drop_not_a_retry():
    """The model is never asked to re-grade its own hallucination: one call in,
    one call out."""
    calls = {"n": 0}

    class Counting(_Agent):
        async def run(self, message="", context=None, **kw):
            calls["n"] += 1
            return await super().run(message, context, **kw)

    actors = [A(1, "Marco Rubio", "Secretary of State of the United States"),
              A(2, "Donald Trump", "President of the United States"),
              A(3, "Kaja Kallas"), A(4, "Volodymyr Zelenskyy"),
              A(5, "Volodymyr Zelensky")]
    agent = Counting({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"}],
        "anonymous_flags": []})
    _run(ResolveActorAliasesStage(agent), *_bus(actors))
    assert calls["n"] == 1


def test_the_stage_row_counts_the_rejections():
    from src.runner.runner import _collect_agent_metrics

    actors = [A(1, "Marco Rubio", "Secretary of State of the United States"),
              A(2, "Donald Trump", "President of the United States"),
              A(3, "Kaja Kallas")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"}],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)
    _run(stage, *_bus(actors))

    row = _collect_agent_metrics(stage)
    assert row["merges_rejected"] == 1
    assert row["merges_rejected_detail"] == ["Marco Rubio -> Donald Trump"]
    # the row says which mode produced the count, so a future flip is legible
    # in the series rather than an unexplained step change
    assert row["merge_validation_mode"] == "detector"


def test_a_clean_run_leaves_the_row_shape_untouched():
    from src.runner.runner import _collect_agent_metrics

    actors = [A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
              A(3, "Kaja Kallas")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"}],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)
    _run(stage, *_bus(actors))

    row = _collect_agent_metrics(stage)
    assert "merges_rejected" not in row
    assert stage.last_rejected_merges == []


def test_a_zero_flag_run_still_logs_that_validation_ran(caplog):
    """A silent day must be auditable as "ran and found nothing": the
    checked/flagged line appears even when nothing is flagged."""
    actors = [A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
              A(3, "Kaja Kallas")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"}],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)

    with caplog.at_level(logging.INFO, logger="src.agent_stages"):
        _run(stage, *_bus(actors))

    assert "merge validation: 1 pairs checked, 0 flagged (detector mode)" \
        in caplog.text
    assert stage.last_rejected_merges == []


def test_a_flagging_run_logs_the_same_line_with_its_count(caplog):
    actors = [A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
              A(3, "Marco Rubio", "Secretary of State of the United States"),
              A(4, "Donald Trump", "President of the United States")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"},
        {"alias_id": "actor-003", "canonical_id": "actor-004"}],
        "anonymous_flags": []})

    with caplog.at_level(logging.INFO, logger="src.agent_stages"):
        _run(ResolveActorAliasesStage(agent), *_bus(actors))

    assert "merge validation: 2 pairs checked, 1 flagged (detector mode)" \
        in caplog.text


def test_validation_runs_before_the_union_find(monkeypatch):
    """The 46-into-1 shape. Union-find is transitive, so ONE un-anchored pair
    inside a chain drags every member together.

    Position matters even in detector mode, which drops nothing: validating
    AFTER the union-find would inspect the collapsed result rather than the
    pair that caused it, so the COUNT would be wrong too — the un-anchored pair
    would have acquired a shared canonical by then. Asserted on the count here,
    and on the drop under reject mode below.
    """
    actors = [A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
              A(3, "Friedrich Merz", "German Chancellor")]
    aliases = [{"alias_id": "actor-001", "canonical_id": "actor-002"},
               {"alias_id": "actor-003", "canonical_id": "actor-002"}]

    stage = ResolveActorAliasesStage(_Agent(
        {"aliases": aliases, "anonymous_flags": []}))
    out = _run(stage, *_bus(actors))
    # detector: the collapse still happens, and is counted exactly once
    assert len(stage.last_rejected_merges) == 1
    assert stage.last_rejected_merges[0]["alias_name"] == "Friedrich Merz"
    assert len(out.actor_alias_mapping) == 2

    import src.agent_stages as ags
    monkeypatch.setattr(ags, "MERGE_VALIDATION_MODE", "reject")
    stage = ResolveActorAliasesStage(_Agent(
        {"aliases": aliases, "anonymous_flags": []}))
    out = _run(stage, *_bus(actors))
    assert "actor-003" in {a["id"] for a in out.canonical_actors}, (
        "Merz must not be dragged in transitively")
    assert len(out.actor_alias_mapping) == 1


# --- collapse shapes get their own line (VALIDATION-DETECTOR-MODE amendment) --
# Same detection, same counts, same fields — a louder prefix for the one shape
# that has ever destroyed a published dossier. Precision is on record (50%
# pair-level, 74% alias-weighted, 9 firings in 4 months), so the line is an
# eye-catcher, not a verdict.

def test_a_collapse_shape_gets_the_tagged_prefix(caplog):
    """Four signal-less aliases onto one canonical: the 2026-07-27 shape in
    miniature. It must announce itself as a collapse shape — and still merge,
    because detector mode rejects nothing."""
    canonical = A(9, "Iris Spranger", "Berlin Senator for the Interior")
    aliases = [A(1, "Friedrich Merz", "German Chancellor"),
               A(2, "Kai Wegner", "Governing Mayor of Berlin"),
               A(3, "Nancy Faeser", "Federal Interior Minister"),
               A(4, "Bettina Jarasch", "Berlin politician")]
    agent = _Agent({"aliases": [
        {"alias_id": a["id"], "canonical_id": canonical["id"]} for a in aliases],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)
    tb, rb = _bus(aliases + [canonical])

    with caplog.at_level(logging.ERROR, logger="src.agent_stages"):
        out = _run(stage, tb, rb)

    assert "COLLAPSE-SHAPE FLAGGED 4 signal-less alias(es)" in caplog.text
    assert "'Iris Spranger'" in caplog.text
    assert "DETECTOR MODE: counted only" in caplog.text
    # nothing rejected: every proposed merge still lands
    assert len(out.actor_alias_mapping) == 4
    assert stage.last_rejected_merges and len(stage.last_rejected_merges) == 4


def test_ordinary_flags_keep_the_plain_prefix(caplog):
    """Two unrelated one-off hallucinations. Neither reaches the collapse
    threshold, so neither may borrow the louder line."""
    actors = [A(1, "Marco Rubio", "Secretary of State of the United States"),
              A(2, "Donald Trump", "President of the United States"),
              A(3, "Kevin Warsh", "Federal Reserve Chair"),
              A(4, "Jerome Powell", "Former Fed chair")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"},
        {"alias_id": "actor-003", "canonical_id": "actor-004"}],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)
    tb, rb = _bus(actors)

    with caplog.at_level(logging.ERROR, logger="src.agent_stages"):
        _run(stage, tb, rb)

    assert "FLAGGED 2 of 2 proposed merge(s)" in caplog.text
    assert "COLLAPSE-SHAPE" not in caplog.text


def test_the_threshold_is_three_aliases_onto_one_canonical():
    """Below the threshold is not a shape; at it, it is. Grouping is by
    canonical, so two pairs onto two different canonicals never combine."""
    def rows(n, canonical="actor-100"):
        return [{"alias_id": f"actor-{i:03d}", "canonical_id": canonical,
                 "alias_name": f"A{i}", "canonical_name": "C"}
                for i in range(n)]

    assert COLLAPSE_SHAPE_MIN_ALIASES == 3
    assert collapse_shape_groups(rows(2)) == []
    g = collapse_shape_groups(rows(3))
    assert len(g) == 1 and g[0]["count"] == 3
    split = rows(2) + rows(2, canonical="actor-200")
    assert collapse_shape_groups(split) == []


def test_collapse_grouping_does_not_change_what_is_counted():
    """The tagged line is a read over the flagged list, not a second judgement:
    every flagged pair appears in exactly one of the two lines."""
    flagged = [{"alias_id": f"actor-{i:03d}",
                "canonical_id": "actor-100" if i < 3 else f"actor-{200 + i}",
                "alias_name": f"A{i}", "canonical_name": "C"}
               for i in range(5)]
    groups = collapse_shape_groups(flagged)
    collapsed = {g["canonical_id"] for g in groups}
    tagged = sum(g["count"] for g in groups)
    ordinary = [r for r in flagged if r["canonical_id"] not in collapsed]
    assert tagged == 3 and len(ordinary) == 2
    assert tagged + len(ordinary) == len(flagged)
