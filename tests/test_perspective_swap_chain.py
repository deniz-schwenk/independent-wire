"""perspective swap to the glm-5.3 draft -> glm-5.3-flash verify chain —
TASK-PERSPECTIVE-SWAP.

Covers:
  * exact request bodies for all three legs — the draft (glm-5.3, reasoning
    high, NO temperature, NO top_p, json_object, z-ai pin, no
    require_parameters), the verify (glm-5.3-flash, temp 1.0 AND top_p 0.95,
    same pin/mode) and the Sonnet-5 fallback (champion operating point, strict
    schema, no pin);
  * the happy-path chain: draft then verify, verify sees the draft under
    `draft` in its context, the VERIFIED object is what returns, and cost and
    tokens are summed across both calls;
  * rung (a) — a draft transport failure AND a schema-invalid draft each fire
    the Sonnet-5 fallback, and the verify pass is SKIPPED in both cases; the
    schema-invalid draft gets exactly ONE repair first (owner refinement,
    2026-09-04), a successful repair never reaches Sonnet, and a transport
    failure gets NO repair;
  * rung (b) — a verify failure gets exactly one repair; a verify that fails
    twice ships the UNVERIFIED draft rather than failing the run, and a repair
    that succeeds returns the verified object;
  * both rungs are loud: WARNING lines plus the persisted markers the runner
    writes into run_stage_log.jsonl;
  * a fallback transport failure propagates (loud terminal failure);
  * the verify work report counts removals, additions and misfiling
    corrections, and reports an ABSENT misfiling measurement as None rather
    than as zero;
  * the runner surfaces perspective_fallback_used plus the verify fields;
  * the create_agents() wiring, in both variants, and that the draft prompts
    are untouched while the verify prompts come from agents/perspective_verify.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import Agent, AgentAPIError, AgentResult
from src.perspective_chain import (
    PerspectiveDraftVerifyChain,
    VERIFY_MESSAGE,
    verify_work_report,
)
from src.runner.runner import _collect_agent_metrics
from src.schemas import PERSPECTIVE_SCHEMA

REPO_ROOT = Path(__file__).resolve().parents[1]

# A PERSPECTIVE_SCHEMA-valid draft: two clusters, one of which cites an actor
# filed under the WRONG sub-list (actor-002 is in the `reported` pool but the
# draft files it under `stated`) plus an actor the verify pass should drop.
DRAFT_OUTPUT = {
    "position_clusters": [
        {
            "position_label": "Supports the measure",
            "position_summary": "The government backs the reform [src-001].",
            "source_ids": ["src-001", "src-002"],
            "stated": ["actor-001", "actor-002"],
            "reported": [],
            "mentioned": [],
        },
        {
            "position_label": "Opposes the measure",
            "position_summary": "Industry groups object [src-002].",
            "source_ids": ["src-002"],
            "stated": ["actor-003"],
            "reported": [],
            "mentioned": [],
        },
    ],
    "missing_positions": [
        {"type": "geographic", "description": "No voices from the affected region."}
    ],
}

# What a working verify pass returns: actor-002 relocated to `reported` (the
# pool that actually holds it), actor-003 and src-002 removed from cluster 0.
VERIFIED_OUTPUT = {
    "position_clusters": [
        {
            "position_label": "Supports the measure",
            "position_summary": "The government backs the reform [src-001].",
            "source_ids": ["src-001"],
            "stated": ["actor-001"],
            "reported": ["actor-002"],
            "mentioned": [],
        },
        {
            "position_label": "Opposes the measure",
            "position_summary": "Industry groups object [src-002].",
            "source_ids": ["src-002"],
            "stated": ["actor-003"],
            "reported": [],
            "mentioned": [],
        },
    ],
    "missing_positions": [
        {"type": "geographic", "description": "No voices from the affected region."}
    ],
}

# The dossier context PerspectiveStage builds. actor-002 lives in the
# `reported` pool, which is what makes the draft's `stated` placement a
# misfiling and the verified placement a correction.
CONTEXT = {
    "title": "A topic",
    "sources": [{"id": "src-001"}, {"id": "src-002"}],
    "canonical_actors_stated": [{"id": "actor-001"}, {"id": "actor-003"}],
    "canonical_actors_reported": [{"id": "actor-002"}],
    "canonical_actors_mentioned": [],
}


@pytest.fixture
def prompt_file(tmp_path) -> str:
    path = tmp_path / "AGENTS.md"
    path.write_text("You are a helpful test assistant.")
    return str(path)


def _mk_agent(prompt_file, **kw) -> Agent:
    return Agent(
        name=kw.pop("name", "t"),
        model=kw.pop("model", "z-ai/glm-5.3"),
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
        **kw,
    )


async def _captured_kwargs(agent: Agent, output_schema=None) -> dict:
    agent._client.chat.completions.create = AsyncMock(return_value=MagicMock())
    await agent._call_with_retry(
        messages=[{"role": "user", "content": "x"}],
        tools=None,
        output_schema=output_schema,
    )
    return agent._client.chat.completions.create.call_args.kwargs


def _result(structured, *, model="z-ai/glm-5.3", provider="Z.AI", cost=0.1, tokens=10):
    return AgentResult(
        content=json.dumps(structured) if structured is not None else "",
        structured=structured,
        model=model,
        provider=provider,
        cost_usd=cost,
        tokens_used=tokens,
    )


class _FakeAgent:
    """Minimal Agent stand-in: a scripted queue of results/exceptions."""

    def __init__(self, model, *responses):
        self.model = model
        self.name = model
        self.temperature = None
        self.max_tokens = 40000
        self.reasoning = "high"
        self._responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    async def run(self, message="", context=None, **kwargs):
        self.calls.append((message, context or {}))
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    def reset_call_metrics(self):
        pass


def _chain(draft, verify, fallback):
    return PerspectiveDraftVerifyChain(
        draft=draft, verify=verify, fallback=fallback,
        output_schema=PERSPECTIVE_SCHEMA,
    )


# --- exact request bodies -----------------------------------------------------


@pytest.mark.asyncio
async def test_draft_glm53_request_body_exact(prompt_file):
    """Draft = glm-5.3, reasoning high, NO temperature, NO top_p, json_object,
    z-ai pin, and crucially NO require_parameters (which would filter the
    schema-less Z.AI endpoint out of its own route)."""
    agent = _mk_agent(
        prompt_file,
        model="z-ai/glm-5.3",
        temperature=None,
        max_tokens=40000,
        reasoning="high",
        provider_routing={"order": ["z-ai"], "allow_fallbacks": False},
        structured_output_mode="json_object",
    )
    kw = await _captured_kwargs(agent, output_schema=PERSPECTIVE_SCHEMA)
    assert kw["model"] == "z-ai/glm-5.3"
    assert "temperature" not in kw          # vendor publishes none -> omitted
    assert "top_p" not in kw
    assert kw["max_tokens"] == 40000
    assert kw["extra_body"]["reasoning"] == {"effort": "high"}
    assert kw["extra_body"]["provider"] == {"order": ["z-ai"], "allow_fallbacks": False}
    assert "require_parameters" not in kw["extra_body"]["provider"]
    assert kw["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_verify_glm53_flash_request_body_exact(prompt_file):
    """Verify = glm-5.3-flash at ITS operating point — temp 1.0 AND top_p 0.95,
    which the draft must NOT carry. top_p rides extra_body_override."""
    agent = _mk_agent(
        prompt_file,
        model="z-ai/glm-5.3-flash",
        temperature=1.0,
        max_tokens=24000,
        reasoning="high",
        provider_routing={"order": ["z-ai"], "allow_fallbacks": False},
        extra_body_override={"top_p": 0.95},
        structured_output_mode="json_object",
    )
    kw = await _captured_kwargs(agent, output_schema=PERSPECTIVE_SCHEMA)
    assert kw["model"] == "z-ai/glm-5.3-flash"
    assert kw["temperature"] == 1.0
    assert kw["extra_body"]["top_p"] == 0.95
    assert kw["max_tokens"] == 24000
    assert kw["extra_body"]["reasoning"] == {"effort": "high"}
    assert kw["extra_body"]["provider"] == {"order": ["z-ai"], "allow_fallbacks": False}
    assert kw["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_fallback_sonnet5_request_body_exact(prompt_file):
    """Fallback = the champion operating point VERBATIM: Sonnet-5, temperature
    omitted, reasoning {enabled, effort:high}, max_tokens 64000, strict schema,
    no provider pin."""
    agent = _mk_agent(
        prompt_file,
        model="anthropic/claude-sonnet-5",
        temperature=None,
        max_tokens=64000,
        reasoning={"enabled": True, "effort": "high"},
    )
    kw = await _captured_kwargs(agent, output_schema=PERSPECTIVE_SCHEMA)
    assert kw["model"] == "anthropic/claude-sonnet-5"
    assert "temperature" not in kw
    assert "top_p" not in kw
    assert kw["max_tokens"] == 64000
    assert kw["extra_body"]["reasoning"] == {"enabled": True, "effort": "high"}
    assert kw["extra_body"]["provider"] == {"require_parameters": True}   # no pin
    assert kw["response_format"]["json_schema"]["strict"] is True
    assert kw["response_format"]["json_schema"]["schema"] == PERSPECTIVE_SCHEMA


# --- happy path ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_runs_draft_then_verify_and_returns_verified():
    draft = _FakeAgent("z-ai/glm-5.3", _result(DRAFT_OUTPUT, cost=0.10, tokens=100))
    verify = _FakeAgent(
        "z-ai/glm-5.3-flash",
        _result(VERIFIED_OUTPUT, model="z-ai/glm-5.3-flash", cost=0.005, tokens=50),
    )
    chain = _chain(draft, verify, _FakeAgent("anthropic/claude-sonnet-5"))

    res = await chain.run("draft this", context=CONTEXT)

    # The VERIFIED object is what reaches the bus, not the draft.
    assert res.structured == VERIFIED_OUTPUT
    assert len(draft.calls) == 1 and len(verify.calls) == 1
    assert chain.last_fallback_used is False
    assert chain.last_verify_skipped is False
    # Cost and tokens are summed across BOTH calls — a two-call stage must not
    # report only its last leg.
    assert chain.last_cost_usd == pytest.approx(0.105)
    assert chain.last_tokens == 150
    assert chain.last_model_used == "z-ai/glm-5.3-flash"


@pytest.mark.asyncio
async def test_verify_receives_draft_in_context_under_draft_key():
    """The verify call gets the dossier PLUS the draft under `draft`, and the
    harness message — the exact shape the T4 evaluation measured."""
    draft = _FakeAgent("z-ai/glm-5.3", _result(DRAFT_OUTPUT))
    verify = _FakeAgent("z-ai/glm-5.3-flash", _result(VERIFIED_OUTPUT))
    chain = _chain(draft, verify, _FakeAgent("anthropic/claude-sonnet-5"))

    await chain.run("draft this", context=CONTEXT)

    msg, ctx = verify.calls[0]
    assert msg == VERIFY_MESSAGE
    assert ctx["draft"] == DRAFT_OUTPUT
    for key in CONTEXT:
        assert ctx[key] == CONTEXT[key]
    # The draft agent must NOT have seen a `draft` key, and the caller's context
    # object must not have been mutated by the chain.
    assert "draft" not in draft.calls[0][1]
    assert "draft" not in CONTEXT


# --- rung (a): draft failure -> Sonnet-5, verify skipped ---------------------


@pytest.mark.asyncio
async def test_draft_transport_failure_falls_back_to_sonnet_and_skips_verify(caplog):
    draft = _FakeAgent("z-ai/glm-5.3", AgentAPIError("z-ai 503", status_code=503))
    verify = _FakeAgent("z-ai/glm-5.3-flash")          # must never be called
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        _result(DRAFT_OUTPUT, model="anthropic/claude-sonnet-5", provider="Anthropic"),
    )
    chain = _chain(draft, verify, fallback)

    with caplog.at_level(logging.WARNING, logger="src.perspective_chain"):
        res = await chain.run("draft this", context=CONTEXT)

    assert res.structured == DRAFT_OUTPUT
    assert verify.calls == []                          # verify SKIPPED
    assert chain.last_fallback_used is True
    assert chain.last_verify_skipped is True
    assert chain.last_model_used == "anthropic/claude-sonnet-5"
    assert chain.extra_log_fields["perspective_verify_skip_reason"] == (
        "sonnet_fallback_not_verified"
    )
    assert "transport failure" in chain.extra_log_fields[
        "perspective_draft_failure_reason"
    ]
    assert any("FALLBACK" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_schema_invalid_draft_repairs_once_then_falls_back(caplog):
    """A draft that does not parse is not a draft. The brief's wording is
    'transport failure'; a schema-invalid draft is treated the same way,
    because the narrow reading would leave the stage with no output at all.

    Owner refinement (2026-09-04): it gets exactly ONE repair first, so a
    trivially repairable JSON glitch cannot escalate to the $1.00 model."""
    draft = _FakeAgent(
        "z-ai/glm-5.3", _result(None), _result(None)     # empty body, twice
    )
    verify = _FakeAgent("z-ai/glm-5.3-flash")
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        _result(DRAFT_OUTPUT, model="anthropic/claude-sonnet-5"),
    )
    chain = _chain(draft, verify, fallback)

    with caplog.at_level(logging.WARNING, logger="src.perspective_chain"):
        await chain.run("draft this", context=CONTEXT)

    assert len(draft.calls) == 2            # one call + exactly one repair
    assert len(fallback.calls) == 1         # escalates only after the repair
    assert verify.calls == []
    assert chain.last_fallback_used is True
    assert chain.extra_log_fields["perspective_draft_attempts"] == 2
    assert chain.extra_log_fields["perspective_draft_failure_kind"] == "schema"
    assert "not schema-valid" in chain.extra_log_fields[
        "perspective_draft_failure_reason"
    ]
    assert any("DRAFT repair" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_schema_invalid_draft_whose_repair_succeeds_never_reaches_sonnet(caplog):
    """The whole point of the refinement: a one-off glitch costs a ~$0.12
    re-roll, not a $1.00 escalation, and the verify pass still runs."""
    draft = _FakeAgent(
        "z-ai/glm-5.3",
        _result(None, cost=0.12, tokens=100),                   # glitch
        _result(DRAFT_OUTPUT, cost=0.12, tokens=100),           # repair works
    )
    verify = _FakeAgent(
        "z-ai/glm-5.3-flash",
        _result(VERIFIED_OUTPUT, model="z-ai/glm-5.3-flash", cost=0.005, tokens=50),
    )
    fallback = _FakeAgent("anthropic/claude-sonnet-5")
    chain = _chain(draft, verify, fallback)

    with caplog.at_level(logging.WARNING, logger="src.perspective_chain"):
        res = await chain.run("draft this", context=CONTEXT)

    assert res.structured == VERIFIED_OUTPUT
    assert len(draft.calls) == 2
    assert fallback.calls == []                 # never escalated
    assert len(verify.calls) == 1               # verify still ran
    assert chain.last_fallback_used is False
    assert chain.extra_log_fields["perspective_draft_attempts"] == 2
    # Both draft calls are billed; the glitch was not free.
    assert chain.last_cost_usd == pytest.approx(0.245)


@pytest.mark.asyncio
async def test_draft_transport_failure_gets_no_repair():
    """Transport gets NO repair: Agent's own retry loop has already exhausted
    its attempts, and `allow_fallbacks: false` leaves no other host, so a
    further identical call is latency without a hypothesis."""
    draft = _FakeAgent("z-ai/glm-5.3", AgentAPIError("z-ai 503", status_code=503))
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        _result(DRAFT_OUTPUT, model="anthropic/claude-sonnet-5"),
    )
    chain = _chain(draft, _FakeAgent("z-ai/glm-5.3-flash"), fallback)

    await chain.run("draft this", context=CONTEXT)

    assert len(draft.calls) == 1                # no repair on transport
    assert chain.extra_log_fields["perspective_draft_attempts"] == 1
    assert chain.extra_log_fields["perspective_draft_failure_kind"] == "transport"


@pytest.mark.asyncio
async def test_failed_draft_calls_still_count_their_cost():
    """Both failed draft calls cost money. They must appear in the run total,
    or the swap's headline saving is measured against an incomplete ledger."""
    draft = _FakeAgent(
        "z-ai/glm-5.3",
        _result(None, cost=0.09, tokens=90),
        _result(None, cost=0.09, tokens=90),
    )
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        _result(DRAFT_OUTPUT, model="anthropic/claude-sonnet-5", cost=1.0, tokens=900),
    )
    chain = _chain(draft, _FakeAgent("z-ai/glm-5.3-flash"), fallback)

    await chain.run("draft this", context=CONTEXT)

    assert chain.last_cost_usd == pytest.approx(1.18)
    assert chain.last_tokens == 1080


@pytest.mark.asyncio
async def test_fallback_transport_failure_propagates():
    """The last resort failing is a loud terminal failure, not a silent one."""
    draft = _FakeAgent("z-ai/glm-5.3", AgentAPIError("z-ai 503", status_code=503))
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5", AgentAPIError("anthropic 500", status_code=500)
    )
    chain = _chain(draft, _FakeAgent("z-ai/glm-5.3-flash"), fallback)

    with pytest.raises(AgentAPIError):
        await chain.run("draft this", context=CONTEXT)


# --- rung (b): verify failure -> one repair, then ship the draft -------------


@pytest.mark.asyncio
async def test_verify_failure_gets_exactly_one_repair_then_succeeds(caplog):
    draft = _FakeAgent("z-ai/glm-5.3", _result(DRAFT_OUTPUT))
    verify = _FakeAgent(
        "z-ai/glm-5.3-flash",
        _result(None),                                   # first attempt: empty body
        _result(VERIFIED_OUTPUT, model="z-ai/glm-5.3-flash"),   # repair succeeds
    )
    chain = _chain(draft, verify, _FakeAgent("anthropic/claude-sonnet-5"))

    with caplog.at_level(logging.WARNING, logger="src.perspective_chain"):
        res = await chain.run("draft this", context=CONTEXT)

    assert res.structured == VERIFIED_OUTPUT
    assert len(verify.calls) == 2
    assert chain.last_verify_skipped is False
    assert chain.extra_log_fields["perspective_verify_attempts"] == 2
    assert any("VERIFY repair" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_verify_failing_twice_ships_the_unverified_draft(caplog):
    """T4C licenses this: the unverified glm-5.3 draft is non-inferior to
    Sonnet-5 at n=15, so a broken filter must never fail the run."""
    draft = _FakeAgent(
        "z-ai/glm-5.3", _result(DRAFT_OUTPUT, model="z-ai/glm-5.3", cost=0.1)
    )
    verify = _FakeAgent(
        "z-ai/glm-5.3-flash",
        AgentAPIError("z-ai 503", status_code=503),
        AgentAPIError("z-ai 503", status_code=503),
    )
    chain = _chain(draft, verify, _FakeAgent("anthropic/claude-sonnet-5"))

    with caplog.at_level(logging.WARNING, logger="src.perspective_chain"):
        res = await chain.run("draft this", context=CONTEXT)

    assert res.structured == DRAFT_OUTPUT              # the DRAFT ships
    assert len(verify.calls) == 2                      # one call + one repair, no more
    assert chain.last_fallback_used is False           # NOT a model fallback
    assert chain.last_verify_skipped is True
    assert chain.last_model_used == "z-ai/glm-5.3"
    assert chain.extra_log_fields["perspective_verify_skipped"] is True
    assert "transport failure" in chain.extra_log_fields[
        "perspective_verify_skip_reason"
    ]
    assert any("VERIFY SKIPPED" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_verify_failure_never_calls_the_sonnet_fallback():
    """Rungs (a) and (b) are independent: a bad verify must not escalate the
    whole stage to the $1.00 model."""
    draft = _FakeAgent("z-ai/glm-5.3", _result(DRAFT_OUTPUT))
    verify = _FakeAgent("z-ai/glm-5.3-flash", _result(None), _result(None))
    fallback = _FakeAgent("anthropic/claude-sonnet-5")
    chain = _chain(draft, verify, fallback)

    await chain.run("draft this", context=CONTEXT)

    assert fallback.calls == []


# --- the verify work report ---------------------------------------------------


def test_verify_work_report_counts_removals_and_misfiling_corrections():
    r = verify_work_report(DRAFT_OUTPUT, VERIFIED_OUTPUT, CONTEXT)
    # ("stated", actor-002) and ("stated", actor-003)->kept... only cluster 0
    # changed: actor-002 moved stated->reported, so one removal + one addition.
    assert r["perspective_verify_actor_refs_removed"] == 1
    assert r["perspective_verify_actor_refs_added"] == 1
    assert r["perspective_verify_source_refs_removed"] == 0   # src-002 still in cl.1
    assert r["perspective_verify_clusters_before"] == 2
    assert r["perspective_verify_clusters_after"] == 2
    # actor-002 lives in the `reported` pool: filed under `stated` it is a
    # misfiling, and relocating it is the correction.
    assert r["perspective_verify_misfiled_before"] == 1
    assert r["perspective_verify_misfiled_after"] == 0
    assert r["perspective_verify_misfiled_corrected"] == 1


def test_verify_work_report_reports_absent_misfiling_measurement_as_none():
    """Without all three pools the misfiling count is unknowable. Reporting it
    as 0 would read as 'nothing was wrong'."""
    r = verify_work_report(DRAFT_OUTPUT, VERIFIED_OUTPUT, {"title": "x"})
    assert r["perspective_verify_misfiled_before"] is None
    assert r["perspective_verify_misfiled_corrected"] is None
    assert r["perspective_verify_actor_refs_removed"] == 1     # still measured


def test_verify_work_report_tolerates_malformed_objects():
    """Measurement must never be the thing that raises inside a good run."""
    r = verify_work_report({"position_clusters": [None, "x"]}, None, CONTEXT)
    assert r["perspective_verify_clusters_after"] == 0


# --- runner surface -----------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_surfaces_chain_markers():
    draft = _FakeAgent("z-ai/glm-5.3", _result(DRAFT_OUTPUT, cost=0.10, tokens=100))
    verify = _FakeAgent(
        "z-ai/glm-5.3-flash",
        _result(VERIFIED_OUTPUT, model="z-ai/glm-5.3-flash", cost=0.005, tokens=50),
    )
    chain = _chain(draft, verify, _FakeAgent("anthropic/claude-sonnet-5"))
    await chain.run("draft this", context=CONTEXT)

    metrics = _collect_agent_metrics(MagicMock(agent=chain))
    assert metrics["perspective_fallback_used"] is False
    assert metrics["model_used"] == "z-ai/glm-5.3-flash"
    assert metrics["provider_used"] == "Z.AI"
    assert metrics["cost_usd"] == pytest.approx(0.105)
    assert metrics["perspective_verify_skipped"] is False
    assert metrics["perspective_verify_misfiled_corrected"] == 1
    assert metrics["perspective_draft_model"] == "z-ai/glm-5.3"
    assert "writer_fallback_used" not in metrics


@pytest.mark.asyncio
async def test_runner_surfaces_fallback_marker_true_on_draft_failure():
    draft = _FakeAgent("z-ai/glm-5.3", AgentAPIError("boom", status_code=500))
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        _result(DRAFT_OUTPUT, model="anthropic/claude-sonnet-5", provider="Anthropic"),
    )
    chain = _chain(draft, _FakeAgent("z-ai/glm-5.3-flash"), fallback)
    await chain.run("draft this", context=CONTEXT)

    metrics = _collect_agent_metrics(MagicMock(agent=chain))
    assert metrics["perspective_fallback_used"] is True
    assert metrics["model_used"] == "anthropic/claude-sonnet-5"
    assert metrics["perspective_verify_skipped"] is True


def test_reset_call_metrics_clears_markers_between_topics():
    chain = _chain(
        _FakeAgent("z-ai/glm-5.3"),
        _FakeAgent("z-ai/glm-5.3-flash"),
        _FakeAgent("anthropic/claude-sonnet-5"),
    )
    chain.last_cost_usd = 1.0
    chain.last_fallback_used = True
    chain.last_verify_skipped = True
    chain.extra_log_fields = {"stale": True}
    chain.reset_call_metrics()
    assert chain.last_cost_usd == 0.0
    assert chain.last_fallback_used is False
    assert chain.last_verify_skipped is False
    assert chain.extra_log_fields == {}


# --- wiring -------------------------------------------------------------------


def _load_run_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "run_for_perspective_chain_test", REPO_ROOT / "scripts" / "run.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("factory_name", ["create_agents", "create_agents_hydrated"])
def test_create_agents_wires_the_chain(monkeypatch, factory_name):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    run = _load_run_module()
    perspective = getattr(run, factory_name)()["perspective"]

    assert isinstance(perspective, PerspectiveDraftVerifyChain)
    assert perspective.fallback_marker_key == "perspective_fallback_used"

    assert perspective.draft.model == "z-ai/glm-5.3"
    assert perspective.draft.temperature is None
    assert perspective.draft.max_tokens == 40000
    assert perspective.draft.reasoning == "high"
    assert perspective.draft.structured_output_mode == "json_object"
    assert perspective.draft._provider_routing == {
        "order": ["z-ai"], "allow_fallbacks": False,
    }
    assert perspective.draft._extra_body_override == {}      # no top_p on the draft

    assert perspective.verify.model == "z-ai/glm-5.3-flash"
    assert perspective.verify.temperature == 1.0
    assert perspective.verify.max_tokens == 24000
    assert perspective.verify.reasoning == "high"
    assert perspective.verify.structured_output_mode == "json_object"
    assert perspective.verify._extra_body_override == {"top_p": 0.95}

    assert perspective.fallback.model == "anthropic/claude-sonnet-5"
    assert perspective.fallback.temperature is None
    assert perspective.fallback.max_tokens == 64000
    assert perspective.fallback.reasoning == {"enabled": True, "effort": "high"}
    assert perspective.fallback._provider_routing == {}      # Anthropic: no pin
    assert perspective.fallback.structured_output_mode == "strict_schema"

    for agent in (perspective.draft, perspective.verify, perspective.fallback):
        assert agent.output_schema == PERSPECTIVE_SCHEMA


def test_draft_prompts_untouched_verify_prompts_are_the_new_pair(monkeypatch):
    """The swap adds a prompt pair; it does not edit the draft's."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    run = _load_run_module()
    p = run.create_agents()["perspective"]

    for agent in (p.draft, p.fallback):
        assert Path(agent.system_prompt_path).parent.name == "perspective"
        assert Path(agent.instructions_path).parent.name == "perspective"
    assert Path(p.verify.system_prompt_path).parent.name == "perspective_verify"
    assert Path(p.verify.instructions_path).parent.name == "perspective_verify"


def test_verify_prompts_are_byte_identical_to_the_evaluated_staging_pair():
    """The eval measured these exact bytes. A reflow or a stray edit would make
    the production verify pass a different thing from the one T4E scored."""
    import hashlib

    expected = {
        # Recorded in the T4D and T4E reports before either round ran.
        "SYSTEM.md": "de7a03982f046d50fbffecbabe97a142ad04c794d0ff0e0f61e96f43428caa42",
        "INSTRUCTIONS.md": "927c6f8bfcc0e20e17ef9025a78f79202d3ac86a60d1a7e1b143f557fdb96523",
    }
    for name, digest in expected.items():
        landed = (REPO_ROOT / "agents" / "perspective_verify" / name).read_bytes()
        assert hashlib.sha256(landed).hexdigest() == digest, name
