"""perspective swap to Sonnet-5 + Opus-4.6 model fallback — TASK-PERSPECTIVE-SWAP-SONNET5.

Covers:
  * exact request bodies for the primary (Sonnet-5, reasoning{enabled, effort:high},
    NO temperature — the 5-family rejects non-default temperature — max_tokens
    64000, no provider pin) and the fallback (the PRE-SWAP incumbent VERBATIM:
    Opus 4.6, temp 0.1, reasoning=none, default max_tokens 32000, no provider pin);
  * the fallback fires on a simulated final transport failure AND on
    schema-invalid / truncated primary output, and NOT on valid output;
  * the fallback is loud — a WARNING line + the persisted marker
    (model_used / provider_used / perspective_fallback_used) that the runner
    writes to run_stage_log.jsonl — and there is no silent-fallback path;
  * a fallback transport failure propagates (loud terminal failure);
  * the runner surfaces the perspective marker under "perspective_fallback_used"
    (distinct from writer's "writer_fallback_used" and qa's "qa_fallback_used"),
    and omits it for plain agents;
  * the create_agents() wiring (both variants);
  * the fallback is Opus-4.6 (the pre-swap incumbent), never Sonnet-5.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import Agent, AgentAPIError, AgentResult
from src.perspective_fallback import PerspectiveWithFallback, output_is_schema_valid
from src.runner.runner import _collect_agent_metrics
from src.schemas import PERSPECTIVE_SCHEMA

# Minimal PERSPECTIVE_SCHEMA-valid output: one cluster (all three actor sub-lists
# present, as `required`) + one missing position.
VALID_OUTPUT = {
    "position_clusters": [
        {
            "position_label": "Supports the measure",
            "position_summary": "The government backs the reform [src-001].",
            "source_ids": ["src-001"],
            "stated": ["actor-001"],
            "reported": [],
            "mentioned": [],
        }
    ],
    "missing_positions": [
        {"type": "geographic", "description": "No voices from the affected region."}
    ],
}


@pytest.fixture
def prompt_file(tmp_path) -> str:
    path = tmp_path / "AGENTS.md"
    path.write_text("You are a helpful test assistant.")
    return str(path)


def _mk_agent(prompt_file, **kw) -> Agent:
    return Agent(
        name="t",
        model=kw.pop("model", "anthropic/claude-sonnet-5"),
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        api_key="fake-key-for-unit-test",
        **kw,
    )


async def _captured_kwargs(agent: Agent, output_schema=None) -> dict:
    """Drive _call_with_retry once with a mocked client; return the request kwargs."""
    agent._client.chat.completions.create = AsyncMock(return_value=MagicMock())
    await agent._call_with_retry(
        messages=[{"role": "user", "content": "x"}],
        tools=None,
        output_schema=output_schema,
    )
    return agent._client.chat.completions.create.call_args.kwargs


# --- exact request bodies -----------------------------------------------------


@pytest.mark.asyncio
async def test_primary_sonnet5_request_body_exact(prompt_file):
    """Primary = Sonnet-5, reasoning{enabled, effort:high}, NO temperature,
    max_tokens 64000, no provider pin (only require_parameters for the schema)."""
    agent = _mk_agent(
        prompt_file,
        model="anthropic/claude-sonnet-5",
        temperature=None,                                 # 5-family: omit temperature
        max_tokens=64000,
        reasoning={"enabled": True, "effort": "high"},
    )
    kw = await _captured_kwargs(agent, output_schema=PERSPECTIVE_SCHEMA)
    assert kw["model"] == "anthropic/claude-sonnet-5"
    assert "temperature" not in kw                        # never sent (non-default rejected)
    assert "top_p" not in kw
    assert kw["max_tokens"] == 64000
    assert kw["extra_body"]["reasoning"] == {"enabled": True, "effort": "high"}
    assert kw["extra_body"]["provider"] == {"require_parameters": True}  # no pin
    rf = kw["response_format"]["json_schema"]
    assert rf["strict"] is True
    assert rf["schema"] == PERSPECTIVE_SCHEMA


@pytest.mark.asyncio
async def test_fallback_opus46_request_body_exact(prompt_file):
    """Fallback = the pre-swap incumbent VERBATIM: Opus 4.6, temp 0.1,
    reasoning=none, default max_tokens 32000, no provider pin (only
    require_parameters for the schema)."""
    agent = _mk_agent(
        prompt_file,
        model="anthropic/claude-opus-4.6",
        temperature=0.1,
        reasoning="none",
        # max_tokens intentionally unset — matches the pre-swap perspective entry,
        # whose effective max_tokens was the Agent default (32000).
    )
    kw = await _captured_kwargs(agent, output_schema=PERSPECTIVE_SCHEMA)
    assert kw["model"] == "anthropic/claude-opus-4.6"
    assert kw["temperature"] == 0.1
    assert kw["max_tokens"] == 32000                 # Agent default (pre-swap value)
    assert kw["extra_body"]["reasoning"] == {"effort": "none"}
    assert kw["extra_body"]["provider"] == {"require_parameters": True}
    rf = kw["response_format"]["json_schema"]
    assert rf["strict"] is True
    assert rf["schema"] == PERSPECTIVE_SCHEMA


# --- fallback wrapper behaviour ----------------------------------------------


class _FakeAgent:
    """Duck-typed stand-in for an Agent inside the wrapper."""

    def __init__(self, model, result=None, exc=None):
        self.model = model
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
        self.last_cost_usd = 0.0
        self.last_tokens = 0


def _result(model, structured, cost=0.0, tokens=0, provider=""):
    return AgentResult(
        content="{}",
        structured=structured,
        cost_usd=cost,
        tokens_used=tokens,
        model=model,
        provider=provider,
    )


@pytest.mark.asyncio
async def test_no_fallback_on_valid_primary_output(caplog):
    primary = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.15, tokens=4000, provider="Anthropic"),
    )
    fallback = _FakeAgent("anthropic/claude-opus-4.6")
    w = PerspectiveWithFallback(primary, fallback, PERSPECTIVE_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.perspective_fallback"):
        res = await w.run("msg", context={})

    assert res is primary._result
    assert fallback.run_calls == 0
    assert w.last_fallback_used is False
    assert w.last_model_used == "anthropic/claude-sonnet-5"
    assert w.last_provider_used == "Anthropic"
    assert w.last_cost_usd == 0.15 and w.last_tokens == 4000
    assert "FALLBACK" not in caplog.text        # nothing loud on the happy path


@pytest.mark.asyncio
async def test_fallback_on_transport_failure(caplog):
    primary = _FakeAgent("anthropic/claude-sonnet-5", exc=AgentAPIError("provider down", status_code=502))
    fallback = _FakeAgent(
        "anthropic/claude-opus-4.6",
        result=_result("anthropic/claude-opus-4.6", VALID_OUTPUT, cost=0.13, tokens=3800, provider="Anthropic"),
    )
    w = PerspectiveWithFallback(primary, fallback, PERSPECTIVE_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.perspective_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_fallback_used is True
    assert w.last_model_used == "anthropic/claude-opus-4.6"
    # primary raised → only fallback cost is accounted
    assert w.last_cost_usd == 0.13 and w.last_tokens == 3800
    assert "FALLBACK" in caplog.text
    assert "transport failure" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_structured",
    [
        None,                                                    # unparseable / truncated to nothing
        {"position_clusters": []},                               # missing required `missing_positions`
        {"missing_positions": []},                               # missing required `position_clusters`
        {"position_clusters": [                                  # cluster missing required `mentioned`
            {"position_label": "P", "position_summary": "S",
             "source_ids": ["src-001"], "stated": [], "reported": []}],
         "missing_positions": []},
        {**VALID_OUTPUT, "extra": 1},                            # additionalProperties: false
    ],
)
async def test_fallback_on_schema_invalid_output(bad_structured, caplog):
    primary = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", bad_structured, cost=0.16, tokens=64000, provider="Anthropic"),
    )
    fallback = _FakeAgent(
        "anthropic/claude-opus-4.6",
        result=_result("anthropic/claude-opus-4.6", VALID_OUTPUT, cost=0.13, tokens=3900),
    )
    w = PerspectiveWithFallback(primary, fallback, PERSPECTIVE_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.perspective_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_fallback_used is True
    assert w.last_model_used == "anthropic/claude-opus-4.6"
    # primary DID return (not raised), so both attempts are accounted
    assert w.last_cost_usd == pytest.approx(0.29) and w.last_tokens == 67900
    assert "not schema-valid" in caplog.text


@pytest.mark.asyncio
async def test_fallback_transport_failure_propagates_loudly():
    """A transport failure on the *fallback* is the loud terminal failure —
    it propagates (topic fails); it is never swallowed into a silent success."""
    primary = _FakeAgent("anthropic/claude-sonnet-5", exc=AgentAPIError("primary down", status_code=500))
    fallback = _FakeAgent("anthropic/claude-opus-4.6", exc=AgentAPIError("fallback down", status_code=500))
    w = PerspectiveWithFallback(primary, fallback, PERSPECTIVE_SCHEMA)

    with pytest.raises(AgentAPIError):
        await w.run("msg")
    assert fallback.run_calls == 1


@pytest.mark.asyncio
async def test_reset_call_metrics_clears_markers_and_underlying():
    primary = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.15, tokens=50),
    )
    fallback = _FakeAgent("anthropic/claude-opus-4.6")
    w = PerspectiveWithFallback(primary, fallback, PERSPECTIVE_SCHEMA)
    await w.run("msg")
    assert w.last_model_used == "anthropic/claude-sonnet-5"

    w.reset_call_metrics()
    assert w.last_cost_usd == 0.0 and w.last_tokens == 0
    assert w.last_model_used == "" and w.last_provider_used == ""
    assert w.last_fallback_used is False
    assert primary.reset_calls == 1 and fallback.reset_calls == 1


# --- runner marker surfacing --------------------------------------------------


class _Stage:
    def __init__(self, agent):
        self.agent = agent


@pytest.mark.asyncio
async def test_runner_surfaces_perspective_fallback_marker():
    primary = _FakeAgent("anthropic/claude-sonnet-5", exc=AgentAPIError("down", status_code=500))
    fallback = _FakeAgent(
        "anthropic/claude-opus-4.6",
        result=_result("anthropic/claude-opus-4.6", VALID_OUTPUT, cost=0.13, tokens=3800, provider="Anthropic"),
    )
    w = PerspectiveWithFallback(primary, fallback, PERSPECTIVE_SCHEMA)
    await w.run("msg")

    metrics = _collect_agent_metrics(_Stage(w))
    assert metrics["model_used"] == "anthropic/claude-opus-4.6"
    assert metrics["provider_used"] == "Anthropic"
    assert metrics["perspective_fallback_used"] is True
    assert "writer_fallback_used" not in metrics       # perspective key, not writer's
    assert "qa_fallback_used" not in metrics
    assert metrics["cost_usd"] == 0.13 and metrics["tokens"] == 3800


@pytest.mark.asyncio
async def test_runner_marks_perspective_no_fallback_on_happy_path():
    primary = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.15, tokens=4000, provider="Anthropic"),
    )
    fallback = _FakeAgent("anthropic/claude-opus-4.6")
    w = PerspectiveWithFallback(primary, fallback, PERSPECTIVE_SCHEMA)
    await w.run("msg")

    metrics = _collect_agent_metrics(_Stage(w))
    assert metrics["model_used"] == "anthropic/claude-sonnet-5"
    assert metrics["provider_used"] == "Anthropic"
    assert metrics["perspective_fallback_used"] is False   # present + False on the happy path


def test_runner_omits_marker_for_plain_agent():
    class _PlainAgent:
        last_cost_usd = 0.1
        last_tokens = 42

    metrics = _collect_agent_metrics(_Stage(_PlainAgent()))
    assert "model_used" not in metrics
    assert "perspective_fallback_used" not in metrics
    assert metrics == {"cost_usd": 0.1, "tokens": 42}


# --- schema-validity gate -----------------------------------------------------


def test_perspective_output_schema_validity_gate():
    assert output_is_schema_valid(VALID_OUTPUT, PERSPECTIVE_SCHEMA) is True
    # An empty-but-well-formed output is valid (both arrays present, no minItems).
    assert output_is_schema_valid(
        {"position_clusters": [], "missing_positions": []}, PERSPECTIVE_SCHEMA) is True
    assert output_is_schema_valid(None, PERSPECTIVE_SCHEMA) is False    # unparseable/truncated
    assert output_is_schema_valid([], PERSPECTIVE_SCHEMA) is False      # top-level array
    # missing required key
    assert output_is_schema_valid({"position_clusters": []}, PERSPECTIVE_SCHEMA) is False
    # additionalProperties: false at top level
    assert output_is_schema_valid({**VALID_OUTPUT, "extra": 1}, PERSPECTIVE_SCHEMA) is False
    # cluster item missing a required actor sub-list (`mentioned`)
    assert output_is_schema_valid(
        {"position_clusters": [
            {"position_label": "P", "position_summary": "S", "source_ids": [],
             "stated": [], "reported": []}],
         "missing_positions": []}, PERSPECTIVE_SCHEMA) is False


# --- shipped wiring -----------------------------------------------------------


def test_create_agents_perspective_is_sonnet5_with_opus46_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents, create_agents_hydrated

    for factory in (create_agents, create_agents_hydrated):
        perspective = factory()["perspective"]
        assert isinstance(perspective, PerspectiveWithFallback)
        assert perspective.fallback_marker_key == "perspective_fallback_used"
        # primary — the binding Sonnet-5 operating point
        assert perspective.primary.model == "anthropic/claude-sonnet-5"
        assert perspective.primary.temperature is None          # temperature omitted
        assert perspective.primary.max_tokens == 64000
        assert perspective.primary.reasoning == {"enabled": True, "effort": "high"}
        assert not perspective.primary._provider_routing        # no provider pin
        assert perspective.primary.output_schema == PERSPECTIVE_SCHEMA
        # fallback — the PRE-SWAP incumbent VERBATIM (Opus 4.6, NOT Sonnet-5)
        assert perspective.fallback.model == "anthropic/claude-opus-4.6"
        assert perspective.fallback.temperature == 0.1
        assert perspective.fallback.max_tokens == 32000         # Agent default (pre-swap value)
        assert perspective.fallback.reasoning == "none"
        assert not perspective.fallback._provider_routing        # no provider pin (pre-swap)
        assert perspective.fallback.output_schema == PERSPECTIVE_SCHEMA
        assert "sonnet" not in perspective.fallback.model.lower()  # last resort is the incumbent
