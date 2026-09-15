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
    ResolveActorAliasesStage, merge_signals, validate_merges,
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

def test_validate_splits_kept_from_rejected():
    actors = {a["id"]: a for a in [
        A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
        A(3, "Marco Rubio", "Secretary of State of the United States"),
        A(4, "Donald Trump", "President of the United States")]}
    pairs = [{"alias_id": "actor-001", "canonical_id": "actor-002"},
             {"alias_id": "actor-003", "canonical_id": "actor-004"}]

    kept, rejected = validate_merges(pairs, actors)

    assert kept == [pairs[0]]
    assert len(rejected) == 1
    assert rejected[0]["alias_name"] == "Marco Rubio"
    assert rejected[0]["canonical_name"] == "Donald Trump"


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


def test_stage_drops_the_hallucination_and_keeps_the_real_merge(caplog):
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

    # first-source-wins picks the SMALLER numeric id as canonical, so the
    # surviving pair is recorded 002 -> 001; compare unordered.
    merged = {frozenset((m["alias_id"], m["canonical_id"]))
              for m in out.actor_alias_mapping}
    assert frozenset(("actor-001", "actor-002")) in merged
    assert frozenset(("actor-003", "actor-004")) not in merged
    # Rubio survives as his own canonical entry rather than vanishing into Trump
    assert "actor-003" in {a["id"] for a in out.canonical_actors}
    assert "REJECTED 1 of 2" in caplog.text
    assert "'Marco Rubio' -> 'Donald Trump'" in caplog.text


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


def test_validation_runs_before_the_union_find():
    """The 46-into-1 shape. Union-find is transitive, so ONE un-anchored pair
    inside a chain drags every member together; validating afterwards would
    already have lost them."""
    actors = [A(1, "Volodymyr Zelenskyy"), A(2, "Volodymyr Zelensky"),
              A(3, "Friedrich Merz", "German Chancellor")]
    agent = _Agent({"aliases": [
        {"alias_id": "actor-001", "canonical_id": "actor-002"},
        {"alias_id": "actor-003", "canonical_id": "actor-002"}],
        "anonymous_flags": []})
    stage = ResolveActorAliasesStage(agent)
    out = _run(stage, *_bus(actors))

    ids = {a["id"] for a in out.canonical_actors}
    assert "actor-003" in ids, "Merz must not be dragged in transitively"
    assert len(out.actor_alias_mapping) == 1
