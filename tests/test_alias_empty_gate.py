"""Empty output = final failure, truthful stage rows, real publish gate.

TASK-ALIAS-EMPTY-GATE (2026-09-15). The case this file pins, in full:

  2026-09-14, topic 3. ResolveActorAliasesStage got `{"aliases": [],
  "anonymous_flags": []}` on all three in-stage attempts against 63 actors. It
  logged ERROR "downstream gate will fire loud", never entered the fallback
  ladder, wrote `status: "success"` to run_stage_log.jsonl, and the dossier
  published with 0 of 63 actors merged. Nothing fired, because no such gate
  existed anywhere in the codebase.

Three separate defects hid inside one symptom, and each gets its own section:

  1. The wrapper cannot see this failure. `FlashStageWithFallback` judges the
     primary against `output_schema`, and an empty-but-well-formed payload is
     schema-valid. Emptiness is a per-stage semantic predicate, so the STAGE
     has to hand the verdict to the wrapper — `escalate_to_fallback`.
  2. The runner had exactly one non-raising outcome, "success". A stage that
     produced nothing usable could not say so.
  3. The gate was a log string, not code.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from src.agent import AgentError, AgentResult
from src.agent_stages import ResolveActorAliasesStage
from src.bus import EditorAssignment, RunBus, TopicBus
from src.flash_stage_fallback import FlashStageWithFallback
from src.runner.runner import (
    _stage_status,
    degraded_stage_rows,
    fire_degradation_gate,
)

RESOLVER_SCHEMA = {
    "type": "object",
    "properties": {"aliases": {"type": "array"},
                   "anonymous_flags": {"type": "array"}},
    "required": ["aliases", "anonymous_flags"],
}


def _run(stage, *a, **kw):
    return asyncio.run(stage(*a, **kw))


def _ro():
    return RunBus().as_readonly()


def _empty(rid: str = "resp-empty") -> AgentResult:
    """Schema-VALID and useless — the shape the wrapper cannot reject."""
    return AgentResult(content="", structured={"aliases": [], "anonymous_flags": []},
                       cost_usd=0.001, tokens_used=5_000, response_id=rid,
                       model="deepseek-flash", provider="deepseek_direct")


def _merged(model: str, provider: str) -> AgentResult:
    return AgentResult(
        content="",
        structured={"aliases": [{"alias_id": "actor-002",
                                 "canonical_id": "actor-001"}],
                    "anonymous_flags": []},
        cost_usd=0.004, tokens_used=9_000, response_id="resp-ok",
        model=model, provider=provider)


class _Seq:
    """Fake Agent returning a scripted sequence, or raising."""

    def __init__(self, results, *, model="m", provider="p", raises=None):
        self._results = list(results)
        self.model, self.provider = model, provider
        self._raises = raises
        self.calls: list[dict] = []
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.temperature = 0.5
        self.max_tokens = 16000
        self.reasoning = "low"

    async def run(self, message: str = "", context: dict | None = None, **kw):
        self.calls.append({"message": message, "context": context or {}})
        if self._raises:
            raise self._raises
        assert self._results, "fake agent exhausted — too many calls"
        return self._results.pop(0)

    def reset_call_metrics(self):
        self.last_cost_usd = 0.0
        self.last_tokens = 0


def _wrapped(primary_results, fallback_results, *, fallback_raises=None):
    return FlashStageWithFallback(
        primary=_Seq(primary_results, model="deepseek-flash",
                     provider="deepseek_direct"),
        fallback=_Seq(fallback_results, model="deepseek/deepseek-v4.1-flash",
                      provider="DeepSeek", raises=fallback_raises),
        output_schema=RESOLVER_SCHEMA,
        name="resolve_actor_aliases",
        fallback_marker_key="resolve_actor_aliases_fallback_used",
    )


# Two actor lists, and the difference between them is the whole of
# TASK-ALIAS-GATE-TRIGGER:
#
#   MERGEABLE   — carries a transliteration variant pair (Zelenskyy/Zelensky),
#                 so an empty result IS suspicious and must escalate.
#   ALL_DISTINCT — 2026-09-14 topic 3's actual shape: uniquely-named people
#                 with nothing to merge, where empty is the CORRECT answer.
#
# ALL_DISTINCT deliberately includes the two traps that made the first,
# naive discriminator fire on that topic: repeated GIVEN names across unrelated
# people (Michael/Josh/Mike), and one self-glossed non-Latin name.
_MERGEABLE = ["Volodymyr Zelenskyy", "Volodymyr Zelensky", "Andrii Sybiha",
              "Radoslaw Sikorski", "Kaja Kallas", "Emmanuel Macron"]
_ALL_DISTINCT = [
    "Donald Trump", "Dario Amodei", "Sam Altman", "Elon Musk", "Jacob Coxon",
    "Josh Gottheimer", "Mike Lawler", "Demis Hassabis", "Sarah Heck",
    "Michael Kratsios", "Josh Engles", "Mike Johnson", "Jakub Pachocki",
    "Evan Hubinger", "Emil Michael", "Greg Casar", "Greg Brockman",
    "Marc Andreessen", "Marc Warner", "Wendy Hall", "Jensen Huang",
    "Simsim \u2013 \u0645\u0634\u0627\u0631\u0643\u0629 "
    "\u0645\u0648\u0627\u0637\u0646\u0629 (Simsim \u2013 Citizen "
    "Participation Association)",
]


def _actors(names):
    return [
        {"id": f"actor-{i:03d}", "name": n, "role": "", "type": "individual",
         "source_ids": [f"src-{i:03d}"],
         "quotes": [{"source_id": f"src-{i:03d}", "position": "p",
                     "verbatim": None}]}
        for i, n in enumerate(names, 1)
    ]


def _tb(n_actors: int = 63) -> TopicBus:
    """An actor list WITH merge candidates, at the 2026-09-14 topic-3 size."""
    names = [_MERGEABLE[i % len(_MERGEABLE)] if i < len(_MERGEABLE)
             else f"Unrelated Person {i}" for i in range(n_actors)]
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.final_actors = _actors(names[:n_actors])
    return tb


def _tb_no_candidates() -> TopicBus:
    """2026-09-14 topic 3's shape: nothing to merge, empty is correct."""
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.final_actors = _actors(_ALL_DISTINCT)
    return tb


# --- 1. empty-x3 engages the ladder ------------------------------------------

def test_empty_on_every_primary_attempt_engages_the_fallback_rung(caplog):
    w = _wrapped([_empty("r1"), _empty("r2"), _empty("r3")],
                 [_merged("deepseek/deepseek-v4.1-flash", "DeepSeek")])
    stage = ResolveActorAliasesStage(w)

    with caplog.at_level(logging.WARNING, logger="src.flash_stage_fallback"):
        _run(stage, _tb(), _ro())

    assert len(w.primary.calls) == 3, "the in-stage retries still run first"
    assert len(w.fallback.calls) == 1, "and then EXACTLY one rung-2 attempt"
    assert "empty output on all 3 attempts" in caplog.text
    assert "FALLBACK" in caplog.text


def test_the_ladder_is_engaged_through_the_wrappers_own_seam():
    """Not a private re-implementation: the stage reaches rung 2 through the
    same public method `run()` uses, so both paths share the exactly-once
    contract and the marker bookkeeping."""
    w = _wrapped([_empty(), _empty(), _empty()],
                 [_merged("deepseek/deepseek-v4.1-flash", "DeepSeek")])
    assert callable(w.escalate_to_fallback)
    _run(ResolveActorAliasesStage(w), _tb(), _ro())
    assert w.last_fallback_used is True
    assert w.last_model_used == "deepseek/deepseek-v4.1-flash"
    assert w.last_provider_used == "DeepSeek"


# --- 2. a recovering ladder produces a TRUTHFUL row --------------------------

def test_ladder_recovery_is_success_but_records_the_fallback():
    w = _wrapped([_empty(), _empty(), _empty()],
                 [_merged("deepseek/deepseek-v4.1-flash", "DeepSeek")])
    stage = ResolveActorAliasesStage(w)

    tb_after = _run(stage, _tb(), _ro())

    # rung 2 produced usable output, so this is a real success...
    assert stage.last_degraded is False
    assert _stage_status(stage)[0] == "success"
    assert tb_after.actor_alias_mapping, "the merge actually landed"
    # ...but the row must not read like a clean primary run.
    assert w.last_fallback_used is True
    assert w.last_model_used == "deepseek/deepseek-v4.1-flash"


def test_cost_and_tokens_include_every_rung():
    """A fallback that is not billed into the row is a quiet cost leak.

    Four calls are made and all four are billed: three empty primaries at
    0.001/5 000 plus the rung-2 recovery at 0.004/9 000. The empty attempts
    cost real money — on 2026-09-14 topic 3 they burned 63 453 tokens — so
    dropping them would understate a degraded run precisely when someone is
    trying to work out what it cost.
    """
    w = _wrapped([_empty(), _empty(), _empty()],
                 [_merged("deepseek/deepseek-v4.1-flash", "DeepSeek")])
    _run(ResolveActorAliasesStage(w), _tb(), _ro())
    assert w.last_cost_usd == pytest.approx(0.003 + 0.004)
    assert w.last_tokens == 3 * 5_000 + 9_000


# --- 3. every rung empty → degraded, and the gate fires ----------------------

def test_every_rung_empty_is_degraded_never_success(caplog):
    w = _wrapped([_empty("r1"), _empty("r2"), _empty("r3")], [_empty("r4")])
    stage = ResolveActorAliasesStage(w)

    with caplog.at_level(logging.ERROR, logger="src.agent_stages"):
        tb_after = _run(stage, _tb(), _ro())

    assert len(w.fallback.calls) == 1
    assert stage.last_degraded is True
    status, fields = _stage_status(stage)
    assert status == "degraded"
    assert fields["degraded"] is True
    assert "no aliases resolved across 63 actors" in fields["degraded_reason"]
    assert "fallback rung ALSO returned empty" in caplog.text
    # the dossier is still written — degraded, not destroyed
    assert len(tb_after.canonical_actors) == 63
    assert tb_after.actor_alias_mapping == []


def test_a_dead_fallback_rung_degrades_rather_than_killing_the_topic(caplog):
    """The 2026-09-10 shape: rung 2 itself unreachable. The topic degrades
    loudly instead of dying, because an unmerged dossier beats no dossier."""
    w = _wrapped([_empty(), _empty(), _empty()], [],
                 fallback_raises=AgentError("404 No endpoints found"))
    stage = ResolveActorAliasesStage(w)

    with caplog.at_level(logging.ERROR, logger="src.agent_stages"):
        tb_after = _run(stage, _tb(), _ro())

    assert stage.last_degraded is True
    assert "fallback rung ALSO failed" in caplog.text
    assert len(tb_after.canonical_actors) == 63


def test_reset_clears_degradation_between_topics():
    """Stage instances are reused across topics; a sticky flag would mark
    every later topic degraded too."""
    w = _wrapped([_empty(), _empty(), _empty()], [_empty()])
    stage = ResolveActorAliasesStage(w)
    _run(stage, _tb(), _ro())
    assert stage.last_degraded is True

    stage.reset_stage_markers()

    assert stage.last_degraded is False
    assert stage.last_degraded_reason == ""
    assert _stage_status(stage) == ("success", {})


def test_the_runner_reset_seam_clears_it(monkeypatch):
    """...and the runner is actually wired to that reset."""
    from src.runner.runner import _reset_agent_metrics

    w = _wrapped([_empty(), _empty(), _empty()], [_empty()])
    stage = ResolveActorAliasesStage(w)
    _run(stage, _tb(), _ro())
    assert stage.last_degraded is True

    _reset_agent_metrics(stage)

    assert stage.last_degraded is False


# --- 4. the gate exists, fires, and the announcement matches it --------------

def _run_bus_with_rows(rows):
    return RunBus(run_stage_log=rows)


def test_gate_fires_loud_on_a_degraded_row(caplog):
    rb = _run_bus_with_rows([
        {"stage": "ResolveActorAliasesStage", "status": "degraded",
         "topic_index": 2, "topic_slug": "ai-executives",
         "degraded_reason": "no aliases resolved across 63 actors",
         "model_used": "deepseek-flash"},
    ])
    with caplog.at_level(logging.ERROR, logger="src.runner.runner"):
        fired = fire_degradation_gate(rb)

    assert len(fired) == 1
    assert "DEGRADATION GATE" in caplog.text
    assert "ResolveActorAliasesStage" in caplog.text
    assert "topic 2" in caplog.text
    assert "no aliases resolved across 63 actors" in caplog.text
    assert all(r.levelno == logging.ERROR for r in caplog.records)


def test_gate_is_silent_on_a_clean_run(caplog):
    rb = _run_bus_with_rows([
        {"stage": "ResolveActorAliasesStage", "status": "success",
         "topic_index": 0},
    ])
    with caplog.at_level(logging.ERROR, logger="src.runner.runner"):
        assert fire_degradation_gate(rb) == []
    assert caplog.text == ""


def test_gate_names_run_level_degradations_distinctly(caplog):
    rb = _run_bus_with_rows([
        {"stage": "CuratorTopicDiscoveryStage", "status": "degraded",
         "degraded_reason": "no topics discovered"},
    ])
    with caplog.at_level(logging.ERROR, logger="src.runner.runner"):
        fire_degradation_gate(rb)
    assert "RUN-LEVEL" in caplog.text


def test_gate_tolerates_a_missing_or_empty_log():
    assert fire_degradation_gate(None) == []
    assert fire_degradation_gate(RunBus()) == []
    assert degraded_stage_rows(None) == []


def test_the_announcement_and_the_gate_say_the_same_thing(caplog):
    """Defect 2 was a dead promise in a log line: "downstream gate will fire
    loud", with no gate behind it. A log claim nobody implemented is worse
    than no claim, because during triage it reads as a guarantee.

    Asserted on the EMITTED records rather than by scanning the source, so the
    history can still be written down in a docstring where it belongs.
    """
    w = _wrapped([_empty(), _empty(), _empty()], [_empty()])
    stage = ResolveActorAliasesStage(w)

    with caplog.at_level(logging.WARNING):
        _run(stage, _tb(), _ro())
    emitted = " ".join(r.getMessage() for r in caplog.records)

    assert "downstream gate will fire loud" not in emitted
    # what it says instead is exactly what then happens
    assert "PRIMARY FINAL FAILURE" in emitted
    assert "escalating to the fallback rung" in emitted
    assert "publish-time gate will fire" in emitted

    caplog.clear()
    rb = _run_bus_with_rows([
        {"stage": "ResolveActorAliasesStage", "status": "degraded",
         "topic_index": 2, **_stage_status(stage)[1]},
    ])
    with caplog.at_level(logging.ERROR, logger="src.runner.runner"):
        assert fire_degradation_gate(rb), "the promised gate fires"


def test_the_gate_runs_before_anything_is_rendered():
    """Ordering matters: the gate is a PUBLISH-DECISION-time check, so it has
    to fire ahead of RenderStage rather than after the packages are on disk."""
    import inspect

    from src.runner.runner import PipelineRunner

    body = inspect.getsource(PipelineRunner._phase_d_post_run)
    assert body.index("fire_degradation_gate") < body.index("RenderStage")


# --- 5. the trigger is a heuristic, and it can be legitimately wrong ---------
# Found by replaying the motivating incident on frozen input
# (scratch/audit/alias-empty-repro/). It is pinned here rather than left in a
# report because it changes how the gate's output must be READ: the flag means
# "no merges happened", not "the model failed".

def test_all_distinct_actors_empty_is_accepted_as_a_true_negative(caplog):
    """The 2026-09-14 topic-3 shape: empty is CORRECT, so nothing fires.

    This test replaces the one the plumbing commit left here, which pinned the
    opposite — that a correct empty answer still produced a degraded flag —
    and said in its own docstring that tightening the trigger was an owner
    decision. TASK-ALIAS-GATE-TRIGGER is that decision, so the assertion
    inverts. What must NOT change is the reason it mattered: a gate that fires
    on correct output gets ignored, which recreates the defect it was built for.
    """
    w = _wrapped([_empty()], [])
    stage = ResolveActorAliasesStage(w)

    with caplog.at_level(logging.INFO, logger="src.agent_stages"):
        tb_after = _run(stage, _tb_no_candidates(), _ro())

    assert len(w.primary.calls) == 1, "no retries on a correct empty answer"
    assert len(w.fallback.calls) == 0, "and no rung-2 spend"
    assert stage.last_degraded is False
    assert _stage_status(stage) == ("success", {})
    assert "no merge or anonymous-flag candidate" in caplog.text
    # the dossier is written exactly as before — this is about the verdict on
    # the output, not the output itself
    assert len(tb_after.canonical_actors) == len(_ALL_DISTINCT)
    assert tb_after.actor_alias_mapping == []


def test_the_traps_that_broke_the_naive_discriminator_stay_fixed():
    """Both false signals that made a bare token/script rule fire on
    2026-09-14 topic 3, pinned individually so neither can creep back.

    Measured, not asserted: replaying a bare "any shared token" rule over that
    topic fires on six shared GIVEN names (Michael, Josh, Mike, Evan, Greg,
    Marc) across unrelated people, and a bare "two scripts present" rule fires
    on one self-glossed Arabic name. Evidence:
    scratch/audit/alias-trigger/REPORT.md.
    """
    from src.agent_stages import merge_candidates_present

    # given-name collisions across unrelated people are not merge candidates
    present, why = merge_candidates_present(_actors(
        ["Emil Michael", "Michael Kratsios", "Josh Gottheimer", "Josh Engles"]))
    assert present is False, why

    # a non-Latin name carrying its OWN Latin gloss is already disambiguated
    present, why = merge_candidates_present(_actors(
        ["Donald Trump", "Sam Altman",
         "Simsim \u2013 \u0645\u0634\u0627\u0631\u0643\u0629 "
         "\u0645\u0648\u0627\u0637\u0646\u0629 (Simsim \u2013 Citizen "
         "Participation Association)"]))
    assert present is False, why


def test_cross_script_variants_without_a_latin_handle_do_count():
    """The hazard the brief names: \u0421\u0438\u0431\u0456\u0433\u0430 -> Sybiha is invisible to any
    Latin-side normalisation, so a bare non-Latin name among Latin ones has to
    count as a candidate on the possibility alone."""
    from src.agent_stages import merge_candidates_present

    present, why = merge_candidates_present(_actors(
        ["Andrii Sybiha", "Radoslaw Sikorski",
         "\u0421\u0438\u0431\u0456\u0433\u0430"]))
    assert present is True
    assert "multi_script" in why


@pytest.mark.parametrize("names,expect,signal", [
    (["Volodymyr Zelenskyy", "Volodymyr Zelensky", "Kaja Kallas"],
     True, "variant_pair"),
    (["World Health Organization", "WHO Director-General", "Kaja Kallas"],
     True, "acronym"),
    (["Israeli military", "\u0627\u0644\u062c\u064a\u0634 "
      "\u0627\u0644\u0625\u0633\u0631\u0627\u0626\u064a\u0644\u064a "
      "(Israeli military)", "Kaja Kallas"], True, "paren_gloss"),
    (["Kaja Kallas", "US officials", "Emmanuel Macron"], True, "generic_label"),
    (["Kaja Kallas", "Trump adviser", "Emmanuel Macron"], True, "role_as_name"),
    (["Donald Trump", "Sam Altman", "Elon Musk"], False, None),
])
def test_each_signal_fires_on_its_own_shape(names, expect, signal):
    from src.agent_stages import merge_candidates_present

    present, why = merge_candidates_present(_actors(names))
    assert present is expect, why
    if signal:
        assert signal in why


def test_role_text_naming_another_actor_counts():
    """How the corpus's legitimate person<->organisation merges present
    themselves — the name pair alone shares nothing."""
    from src.agent_stages import merge_candidates_present

    actors = _actors(["Matthew Diller", "New York City Bar Association"])
    actors[0]["role"] = "President, New York City Bar Association"
    present, why = merge_candidates_present(actors)
    assert present is True
    assert "role_names_actor" in why

    # It requires the other actor's FULL multi-token name, but that still
    # matches a geographic phrase embedded in a role: "Marco Rubio", role
    # "Secretary of State of the United States", beside an actor "United
    # States", fires. That is a FALSE POSITIVE and it is accepted knowingly —
    # it costs at most the retries the stage already made, whereas the opposite
    # error accepts a real degradation in silence. Pinned so the asymmetry is a
    # recorded decision rather than an accident.
    actors = _actors(["Marco Rubio", "United States"])
    actors[0]["role"] = "Secretary of State of the United States"
    present, why = merge_candidates_present(actors)
    assert present is True and "role_names_actor" in why


def test_a_malformed_response_is_still_empty_emission(caplog):
    """The discriminator relaxes the verdict on a WELL-FORMED empty answer
    only. A response that does not parse is a transport failure whatever the
    input looks like, and must still retry and escalate."""
    bad = AgentResult(content="", structured=None, cost_usd=0.001,
                      tokens_used=10, response_id="r", model="m", provider="p")
    w = _wrapped([bad, bad, bad], [_merged("deepseek/deepseek-v4.1-flash",
                                           "DeepSeek")])
    stage = ResolveActorAliasesStage(w)

    with caplog.at_level(logging.ERROR, logger="src.agent_stages"):
        _run(stage, _tb_no_candidates(), _ro())

    # The wrapper's own schema check catches structured=None before the stage's
    # empty predicate is ever consulted, so the ladder engages on the FIRST
    # attempt rather than after three. The point stands either way, and is the
    # one that matters: an unparseable response on a nothing-to-merge input is
    # still escalated, never waved through as a true negative.
    assert len(w.primary.calls) == 1
    assert len(w.fallback.calls) == 1
    assert w.last_fallback_used is True


def test_candidate_present_empty_still_escalates_and_degrades(caplog):
    """The other direction, unchanged: candidates present + every rung empty
    still engages the ladder and still degrades."""
    w = _wrapped([_empty(), _empty(), _empty()], [_empty()])
    stage = ResolveActorAliasesStage(w)

    with caplog.at_level(logging.ERROR, logger="src.agent_stages"):
        _run(stage, _tb(), _ro())

    assert len(w.fallback.calls) == 1
    assert stage.last_degraded is True
    assert _stage_status(stage)[0] == "degraded"
    # the reason now names WHICH signals fired, so triage starts from evidence
    assert "variant_pair" in stage.last_degraded_reason


def test_two_actors_is_the_legitimate_empty_path_and_never_degrades():
    """The existing `< 3 actors` carve-out: with nothing plausibly to merge the
    predicate is constant-False, so there is no retry, no rung-2 call and no
    flag. The one case the heuristic already gets right."""
    w = _wrapped([_empty()], [])
    stage = ResolveActorAliasesStage(w)

    _run(stage, _tb(2), _ro())

    assert len(w.primary.calls) == 1
    assert len(w.fallback.calls) == 0
    assert stage.last_degraded is False
    assert _stage_status(stage) == ("success", {})
