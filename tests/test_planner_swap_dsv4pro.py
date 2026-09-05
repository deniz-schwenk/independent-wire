"""Planner swap to dsv4-pro-0813 @ low — TASK-PLANNER-SWAP (owner 2026-09-05).

Covers the three-rung ladder in :mod:`src.planner_fallback`:
  * rung 1 serves and nothing descends when the primary output is schema-valid;
  * rung 2 fires on a primary transport failure AND on a schema-invalid
    primary output, and returns the dated-id result;
  * rung 3 (the incumbent Opus-4.6 safety net) fires only when BOTH DeepSeek
    routes fail, and is loud at ERROR level because it is a model substitution;
  * a rung-3 transport failure propagates — the loud terminal failure;
  * cost/tokens are summed across FAILED attempts too (the specific defect that
    nesting two FlashStageWithFallback instances would have introduced);
  * markers and ``planner_fallback_rung`` are surfaced for the runner.

Plus wiring assertions: the hydrated planner is the ladder with the T5a
operating point on every rung, and the non-hydrated ``researcher_plan`` — never
evaluated — is untouched.
"""

from __future__ import annotations

import logging

import pytest

from src.agent import AgentAPIError, AgentResult
from src.planner_fallback import (
    PlannerWithFallbackLadder,
    planner_output_is_usable,
)
from src.schemas import RESEARCHER_PLAN_SCHEMA

# The envelope shape, which strict json_schema decoding produces (the
# incumbent Opus rung).
VALID = {"queries": [{"query": "Hormuz transit fees 2026", "language": "en"}]}
# The BARE ARRAY, which PLAN-INSTRUCTIONS.md explicitly asks the model to emit
# and which both DeepSeek rungs actually return on json_object. The first
# version of these tests fed the envelope on every rung, which is why they
# passed while the wrapper rejected every real DeepSeek plan in the smoke.
VALID_BARE = [{"query": "Hormuz transit fees 2026", "language": "en"}]
INVALID = {"not_the_schema": []}


def _result(model, structured, provider="deepseek_direct", cost=0.01,
            tokens=100):
    return AgentResult(
        content="{}", structured=structured, model=model, provider=provider,
        cost_usd=cost, tokens_used=tokens,
    )


class _FakeAgent:
    def __init__(self, model, result=None, exc=None):
        self.model = model
        self.provider = "openrouter"
        self._result = result
        self._exc = exc
        self.run_calls = 0
        self.reset_calls = 0
        self.last_cost_usd = 0.0
        self.last_tokens = 0

    async def run(self, *args, **kwargs):
        self.run_calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result

    def reset_call_metrics(self):
        self.reset_calls += 1


def _ladder(primary, dated, incumbent):
    return PlannerWithFallbackLadder(
        primary=primary, fallback_dated=dated, fallback_incumbent=incumbent,
        output_schema=RESEARCHER_PLAN_SCHEMA,
    )


# --------------------------------------------------------------- rung 1


@pytest.mark.asyncio
async def test_primary_serves_and_nothing_descends():
    p = _FakeAgent("deepseek-v4-pro", _result("deepseek-v4-pro", VALID))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813")
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)

    out = await lad.run("msg")

    assert out.structured == VALID
    assert (p.run_calls, d.run_calls, i.run_calls) == (1, 0, 0)
    assert lad.last_fallback_used is False
    assert lad.last_rung == "primary_channel_c"
    assert lad.extra_log_fields == {"planner_fallback_rung": "primary_channel_c"}
    assert lad.last_model_used == "deepseek-v4-pro"


# --------------------------------------------------------------- rung 2


@pytest.mark.asyncio
async def test_primary_transport_failure_descends_to_dated_id():
    p = _FakeAgent("deepseek-v4-pro", exc=AgentAPIError("boom"))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813",
                   _result("deepseek/deepseek-v4-pro-0813", VALID,
                           provider="DeepSeek"))
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)

    out = await lad.run("msg")

    assert out.structured == VALID
    assert (d.run_calls, i.run_calls) == (1, 0)
    assert lad.last_fallback_used is True
    assert lad.last_rung == "fallback_dated_openrouter"
    assert lad.last_provider_used == "DeepSeek"


@pytest.mark.asyncio
async def test_schema_invalid_primary_descends_to_dated_id():
    p = _FakeAgent("deepseek-v4-pro", _result("deepseek-v4-pro", INVALID))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813",
                   _result("deepseek/deepseek-v4-pro-0813", VALID))
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)

    await lad.run("msg")

    assert (d.run_calls, i.run_calls) == (1, 0)
    assert lad.last_rung == "fallback_dated_openrouter"


@pytest.mark.asyncio
async def test_empty_body_counts_as_failure_not_an_empty_plan():
    """structured=None is what an empty completion looks like. It must
    descend, never pass an empty plan to the search stage."""
    p = _FakeAgent("deepseek-v4-pro", _result("deepseek-v4-pro", None))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813",
                   _result("deepseek/deepseek-v4-pro-0813", VALID))
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)

    await lad.run("msg")

    assert d.run_calls == 1
    assert lad.last_rung == "fallback_dated_openrouter"


# --------------------------------------------------------------- rung 3


@pytest.mark.asyncio
async def test_both_deepseek_routes_failing_reaches_the_incumbent(caplog):
    p = _FakeAgent("deepseek-v4-pro", exc=AgentAPIError("C down"))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813", exc=AgentAPIError("A down"))
    i = _FakeAgent("anthropic/claude-opus-4.6",
                   _result("anthropic/claude-opus-4.6", VALID,
                           provider="Anthropic"))
    lad = _ladder(p, d, i)

    with caplog.at_level(logging.ERROR):
        out = await lad.run("msg")

    assert out.structured == VALID
    assert i.run_calls == 1
    assert lad.last_fallback_used is True
    assert lad.last_rung == "fallback_incumbent_opus"
    assert lad.last_model_used == "anthropic/claude-opus-4.6"
    # loud, and explicitly named as a model substitution
    assert any("MODEL substitution" in r.message or "MODEL substitution" in r.getMessage()
               for r in caplog.records)


@pytest.mark.asyncio
async def test_incumbent_is_not_reached_when_the_dated_rung_works():
    p = _FakeAgent("deepseek-v4-pro", exc=AgentAPIError("C down"))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813",
                   _result("deepseek/deepseek-v4-pro-0813", VALID))
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)

    await lad.run("msg")

    assert i.run_calls == 0


@pytest.mark.asyncio
async def test_incumbent_transport_failure_propagates():
    p = _FakeAgent("deepseek-v4-pro", exc=AgentAPIError("C down"))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813", exc=AgentAPIError("A down"))
    i = _FakeAgent("anthropic/claude-opus-4.6", exc=AgentAPIError("Opus down"))
    lad = _ladder(p, d, i)

    with pytest.raises(AgentAPIError):
        await lad.run("msg")


# --------------------------------------------------------------- accounting


@pytest.mark.asyncio
async def test_failed_attempts_still_count_their_cost():
    """The defect that ruled out nesting two FlashStageWithFallback wrappers:
    a rung that billed tokens and then returned an unusable body must still
    appear in the stage's cost line."""
    p = _FakeAgent("deepseek-v4-pro",
                   _result("deepseek-v4-pro", INVALID, cost=0.02, tokens=200))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813",
                   _result("deepseek/deepseek-v4-pro-0813", INVALID,
                           cost=0.03, tokens=300))
    i = _FakeAgent("anthropic/claude-opus-4.6",
                   _result("anthropic/claude-opus-4.6", VALID,
                           cost=0.40, tokens=900))
    lad = _ladder(p, d, i)

    await lad.run("msg")

    assert lad.last_cost_usd == pytest.approx(0.45)
    assert lad.last_tokens == 1400


@pytest.mark.asyncio
async def test_reset_clears_markers_and_all_three_agents():
    p = _FakeAgent("deepseek-v4-pro", _result("deepseek-v4-pro", VALID))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813")
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)
    await lad.run("msg")

    lad.reset_call_metrics()

    assert lad.last_cost_usd == 0.0 and lad.last_tokens == 0
    assert lad.last_rung == "" and lad.last_fallback_used is False
    assert (p.reset_calls, d.reset_calls, i.reset_calls) == (1, 1, 1)


def test_runner_marker_seam_is_present():
    """The members src/runner/runner.py::_collect_agent_metrics reads."""
    p = _FakeAgent("deepseek-v4-pro")
    lad = _ladder(p, _FakeAgent("d"), _FakeAgent("i"))
    for member in ("last_cost_usd", "last_tokens", "reset_call_metrics",
                   "last_model_used", "last_provider_used",
                   "last_fallback_used", "fallback_marker_key",
                   "extra_log_fields", "name", "model"):
        assert hasattr(lad, member), member
    assert lad.fallback_marker_key == "planner_fallback_used"


# --------------------------------------------------------------- wiring


def _hydrated_planner():
    from scripts.run import create_agents_hydrated
    return create_agents_hydrated()["researcher_hydrated_plan"]


def test_hydrated_planner_is_the_ladder_at_the_t5a_operating_point():
    lad = _hydrated_planner()
    assert isinstance(lad, PlannerWithFallbackLadder)

    # rung 1 — channel C alias, T5a operating point
    assert lad.primary.model == "deepseek-v4-pro"
    assert lad.primary.provider == "deepseek_direct"
    assert lad.primary.reasoning == "low"
    # temperature/top_p omitted: every T5a number was measured without them
    assert lad.primary.temperature is None
    assert lad.primary.max_tokens == 24000

    # rung 2 — same weights, dated id, vendor endpoint, no third-party host
    assert lad.fallback_dated.model == "deepseek/deepseek-v4-pro-0813"
    assert lad.fallback_dated.provider == "openrouter"
    assert lad.fallback_dated.reasoning == "low"
    assert lad.fallback_dated.temperature is None
    routing = lad.fallback_dated._provider_routing
    assert routing["order"] == ["deepseek"]
    assert routing["allow_fallbacks"] is False

    # rung 3 — the incumbent at its production operating point
    assert lad.fallback_incumbent.model == "anthropic/claude-opus-4.6"
    assert lad.fallback_incumbent.temperature == 0.5
    assert lad.fallback_incumbent.max_tokens == 16384
    assert lad.fallback_incumbent.reasoning == "none"


def test_all_three_rungs_share_the_production_plan_prompt():
    lad = _hydrated_planner()
    for agent in (lad.primary, lad.fallback_dated, lad.fallback_incumbent):
        assert agent.system_prompt_path.endswith(
            "researcher_hydrated/PLAN-SYSTEM.md")
        assert agent.instructions_path.endswith(
            "researcher_hydrated/PLAN-INSTRUCTIONS.md")
        assert agent.output_schema is RESEARCHER_PLAN_SCHEMA


def test_neither_deepseek_rung_requests_strict_schema():
    """`require_parameters: true` filters the DeepSeek endpoint out of its own
    route (404). Both DeepSeek rungs must run json_object."""
    lad = _hydrated_planner()
    assert lad.primary.structured_output_mode == "json_object"
    assert lad.fallback_dated.structured_output_mode == "json_object"


def test_non_hydrated_researcher_plan_is_untouched():
    """Out of scope by the brief: that variant was never evaluated."""
    from scripts.run import create_agents, create_agents_hydrated
    for factory in (create_agents, create_agents_hydrated):
        planner = factory()["researcher_plan"]
        assert planner.model == "anthropic/claude-opus-4.6"
        assert planner.provider == "openrouter"


# ------------------------------------- the shape the prompt actually produces


def test_bare_array_is_usable_because_the_prompt_asks_for_it():
    """PLAN-INSTRUCTIONS.md: "Output only the JSON array." The stage's own
    `_unwrap_list` accepts it, so the ladder must too. Regression for the bug
    the 2026-09-05 stage-isolated smoke caught: a strict envelope check
    rejected every DeepSeek plan and paid Opus to redo work that had already
    succeeded."""
    assert planner_output_is_usable(VALID_BARE) is True
    assert planner_output_is_usable(VALID) is True


@pytest.mark.parametrize("bad, why", [
    (None, "empty body / unparseable"),
    ([], "empty bare list starves the search stage"),
    ({"queries": []}, "empty envelope, same"),
    ("a string", "not a container"),
    ([{"query": "x"}], "missing language"),
    ([{"language": "en"}], "missing query"),
    ([{"query": "  ", "language": "en"}], "blank query"),
])
def test_unusable_shapes_are_rejected(bad, why):
    assert planner_output_is_usable(bad) is False, why


@pytest.mark.asyncio
async def test_primary_returning_a_bare_array_serves_without_descending():
    """End-to-end through the ladder, with the shape production really sees."""
    p = _FakeAgent("deepseek-v4-pro", _result("deepseek-v4-pro", VALID_BARE))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813")
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)

    out = await lad.run("msg")

    assert out.structured == VALID_BARE
    assert (d.run_calls, i.run_calls) == (0, 0), (
        "a bare array is what the prompt asks for; descending on it is the "
        "smoke-caught bug")
    assert lad.last_rung == "primary_channel_c"
    assert lad.last_fallback_used is False


# ------------------------------- Architect-requested: rung-1 spend is logged


@pytest.mark.asyncio
async def test_rung1_failure_spend_reaches_the_stage_log():
    """The exact bug src/planner_fallback.py exists to avoid.

    A rung-1 call that billed tokens and then returned an unusable body must
    still appear in the row the runner writes to run_stage_log.jsonl — not
    just in the wrapper's own attribute. Asserted through the runner's real
    metric collector, not by reading the accumulator directly."""
    from src.runner.runner import _collect_agent_metrics

    p = _FakeAgent("deepseek-v4-pro",
                   _result("deepseek-v4-pro", None, cost=0.0187, tokens=16483))
    d = _FakeAgent("deepseek/deepseek-v4-pro-0813",
                   _result("deepseek/deepseek-v4-pro-0813", VALID_BARE,
                           provider="DeepSeek", cost=0.0202, tokens=17252))
    i = _FakeAgent("anthropic/claude-opus-4.6")
    lad = _ladder(p, d, i)

    await lad.run("msg")

    class _Stage:
        agent = lad

    entry = _collect_agent_metrics(_Stage())

    assert entry["cost_usd"] == pytest.approx(0.0389), (
        "rung-1's $0.0187 must not vanish from the logged cost")
    assert entry["tokens"] == 33735
    assert entry["model_used"] == "deepseek/deepseek-v4-pro-0813"
    assert entry["planner_fallback_used"] is True
    assert entry["planner_fallback_rung"] == "fallback_dated_openrouter"
