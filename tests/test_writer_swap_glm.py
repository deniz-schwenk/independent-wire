"""writer swap to GLM-5.2 + Opus-4.6 model fallback — TASK-WRITER-SWAP-GLM.

Covers:
  * exact request bodies for the primary (GLM-5.2 @ xhigh, temp 0.3, max_tokens
    120000, fp8 pin) and the fallback (the PRE-SWAP incumbent VERBATIM: Opus 4.6,
    temp 0.3, reasoning=none, default max_tokens 32000, no provider pin);
  * the fallback fires on a simulated final transport failure AND on
    schema-invalid / truncated primary output, and NOT on valid output;
  * the fallback is loud — a WARNING line + the persisted marker
    (model_used / provider_used / writer_fallback_used) that the runner writes to
    run_stage_log.jsonl — and there is no silent-fallback path;
  * a fallback transport failure propagates (loud terminal failure);
  * the runner surfaces the writer marker under "writer_fallback_used" (distinct
    from qa_analyze's "qa_fallback_used"), and omits it for plain agents;
  * the shipped routing constant + create_agents() wiring (both variants);
  * the fallback is Opus-4.6, NOT Sonnet-5 (the deliberate difference from QA).
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import Agent, AgentAPIError, AgentResult
from src.runner.runner import _collect_agent_metrics
from src.schemas import WRITER_SCHEMA
from src.writer_fallback import WriterWithFallback, output_is_schema_valid
from scripts.run import GLM_5_2_WRITER_FP8_ROUTING

# Minimal WRITER_SCHEMA-valid output (sources items require only `src_id`).
VALID_OUTPUT = {
    "headline": "H",
    "subheadline": "S",
    "body": "Body sentence [src-001].",
    "summary": "M",
    "sources": [{"src_id": "src-001"}],
}


@pytest.fixture
def prompt_file(tmp_path) -> str:
    path = tmp_path / "AGENTS.md"
    path.write_text("You are a helpful test assistant.")
    return str(path)


def _mk_agent(prompt_file, **kw) -> Agent:
    return Agent(
        name="t",
        model=kw.pop("model", "z-ai/glm-5.2"),
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
async def test_primary_glm_request_body_exact(prompt_file):
    """Primary = GLM-5.2 @ xhigh, temp 0.3, max_tokens 120000, fp8 pin."""
    agent = _mk_agent(
        prompt_file,
        model="z-ai/glm-5.2",
        temperature=0.3,
        max_tokens=120000,
        reasoning="xhigh",
        provider_routing=GLM_5_2_WRITER_FP8_ROUTING,
    )
    kw = await _captured_kwargs(agent, output_schema=WRITER_SCHEMA)
    assert kw["model"] == "z-ai/glm-5.2"
    assert kw["temperature"] == 0.3
    assert kw["max_tokens"] == 120000
    assert kw["extra_body"]["reasoning"] == {"effort": "xhigh"}
    assert kw["extra_body"]["provider"] == {
        "order": ["baidu/fp8", "ambient/fp8", "venice/fp8"],
        "allow_fallbacks": False,
        "quantizations": ["fp8"],
        "require_parameters": True,  # added by Agent for schema calls
    }
    rf = kw["response_format"]["json_schema"]
    assert rf["strict"] is True
    assert rf["schema"] == WRITER_SCHEMA


@pytest.mark.asyncio
async def test_fallback_opus46_request_body_exact(prompt_file):
    """Fallback = the pre-swap incumbent VERBATIM: Opus 4.6, temp 0.3,
    reasoning=none, default max_tokens 32000, no provider pin (only
    require_parameters for the schema)."""
    agent = _mk_agent(
        prompt_file,
        model="anthropic/claude-opus-4.6",
        temperature=0.3,
        reasoning="none",
        # max_tokens intentionally unset — matches the pre-swap writer entry,
        # whose effective max_tokens was the Agent default (32000).
    )
    kw = await _captured_kwargs(agent, output_schema=WRITER_SCHEMA)
    assert kw["model"] == "anthropic/claude-opus-4.6"
    assert kw["temperature"] == 0.3
    assert kw["max_tokens"] == 32000                 # Agent default (pre-swap value)
    assert kw["extra_body"]["reasoning"] == {"effort": "none"}
    assert kw["extra_body"]["provider"] == {"require_parameters": True}
    rf = kw["response_format"]["json_schema"]
    assert rf["strict"] is True
    assert rf["schema"] == WRITER_SCHEMA


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
        "z-ai/glm-5.2",
        result=_result("z-ai/glm-5.2", VALID_OUTPUT, cost=0.02, tokens=500, provider="Baidu"),
    )
    fallback = _FakeAgent("anthropic/claude-opus-4.6")
    w = WriterWithFallback(primary, fallback, WRITER_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.writer_fallback"):
        res = await w.run("msg", context={})

    assert res is primary._result
    assert fallback.run_calls == 0
    assert w.last_fallback_used is False
    assert w.last_model_used == "z-ai/glm-5.2"
    assert w.last_provider_used == "Baidu"
    assert w.last_cost_usd == 0.02 and w.last_tokens == 500
    assert "FALLBACK" not in caplog.text        # nothing loud on the happy path


@pytest.mark.asyncio
async def test_fallback_on_transport_failure(caplog):
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("all providers down", status_code=502))
    fallback = _FakeAgent(
        "anthropic/claude-opus-4.6",
        result=_result("anthropic/claude-opus-4.6", VALID_OUTPUT, cost=0.13, tokens=800, provider="Anthropic"),
    )
    w = WriterWithFallback(primary, fallback, WRITER_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.writer_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_fallback_used is True
    assert w.last_model_used == "anthropic/claude-opus-4.6"
    # primary raised → only fallback cost is accounted
    assert w.last_cost_usd == 0.13 and w.last_tokens == 800
    assert "FALLBACK" in caplog.text
    assert "transport failure" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_structured",
    [
        None,                                                    # unparseable / truncated to nothing
        {"headline": "H", "subheadline": "S", "body": "B", "summary": "M"},  # missing required `sources`
        {"headline": "H", "subheadline": "S", "body": "B", "summary": "M",
         "sources": [{"outlet": "x"}]},                          # source item missing required `src_id`
        {**VALID_OUTPUT, "extra": 1},                            # additionalProperties: false
    ],
)
async def test_fallback_on_schema_invalid_output(bad_structured, caplog):
    primary = _FakeAgent(
        "z-ai/glm-5.2",
        result=_result("z-ai/glm-5.2", bad_structured, cost=0.03, tokens=120000, provider="Baidu"),
    )
    fallback = _FakeAgent(
        "anthropic/claude-opus-4.6",
        result=_result("anthropic/claude-opus-4.6", VALID_OUTPUT, cost=0.13, tokens=900),
    )
    w = WriterWithFallback(primary, fallback, WRITER_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.writer_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_fallback_used is True
    assert w.last_model_used == "anthropic/claude-opus-4.6"
    # primary DID return (not raised), so both attempts are accounted
    assert w.last_cost_usd == pytest.approx(0.16) and w.last_tokens == 120900
    assert "not schema-valid" in caplog.text


@pytest.mark.asyncio
async def test_fallback_transport_failure_propagates_loudly():
    """A transport failure on the *fallback* is the loud terminal failure —
    it propagates (topic fails); it is never swallowed into a silent success."""
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("primary down", status_code=500))
    fallback = _FakeAgent("anthropic/claude-opus-4.6", exc=AgentAPIError("fallback down", status_code=500))
    w = WriterWithFallback(primary, fallback, WRITER_SCHEMA)

    with pytest.raises(AgentAPIError):
        await w.run("msg")
    assert fallback.run_calls == 1


@pytest.mark.asyncio
async def test_reset_call_metrics_clears_markers_and_underlying():
    primary = _FakeAgent("z-ai/glm-5.2", result=_result("z-ai/glm-5.2", VALID_OUTPUT, cost=0.02, tokens=5))
    fallback = _FakeAgent("anthropic/claude-opus-4.6")
    w = WriterWithFallback(primary, fallback, WRITER_SCHEMA)
    await w.run("msg")
    assert w.last_model_used == "z-ai/glm-5.2"

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
async def test_runner_surfaces_writer_fallback_marker():
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("down", status_code=500))
    fallback = _FakeAgent(
        "anthropic/claude-opus-4.6",
        result=_result("anthropic/claude-opus-4.6", VALID_OUTPUT, cost=0.13, tokens=800, provider="Anthropic"),
    )
    w = WriterWithFallback(primary, fallback, WRITER_SCHEMA)
    await w.run("msg")

    metrics = _collect_agent_metrics(_Stage(w))
    assert metrics["model_used"] == "anthropic/claude-opus-4.6"
    assert metrics["provider_used"] == "Anthropic"
    assert metrics["writer_fallback_used"] is True
    assert "qa_fallback_used" not in metrics          # writer key, not qa's
    assert metrics["cost_usd"] == 0.13 and metrics["tokens"] == 800


@pytest.mark.asyncio
async def test_runner_marks_writer_no_fallback_on_happy_path():
    primary = _FakeAgent(
        "z-ai/glm-5.2",
        result=_result("z-ai/glm-5.2", VALID_OUTPUT, cost=0.05, tokens=600, provider="Baidu"),
    )
    fallback = _FakeAgent("anthropic/claude-opus-4.6")
    w = WriterWithFallback(primary, fallback, WRITER_SCHEMA)
    await w.run("msg")

    metrics = _collect_agent_metrics(_Stage(w))
    assert metrics["model_used"] == "z-ai/glm-5.2"
    assert metrics["provider_used"] == "Baidu"
    assert metrics["writer_fallback_used"] is False   # present + False on the happy path


def test_runner_omits_marker_for_plain_agent():
    class _PlainAgent:
        last_cost_usd = 0.1
        last_tokens = 42

    metrics = _collect_agent_metrics(_Stage(_PlainAgent()))
    assert "model_used" not in metrics
    assert "writer_fallback_used" not in metrics
    assert "qa_fallback_used" not in metrics
    assert metrics == {"cost_usd": 0.1, "tokens": 42}


# --- schema-validity gate -----------------------------------------------------


def test_writer_output_schema_validity_gate():
    assert output_is_schema_valid(VALID_OUTPUT, WRITER_SCHEMA) is True
    assert output_is_schema_valid(None, WRITER_SCHEMA) is False        # unparseable/truncated
    assert output_is_schema_valid([], WRITER_SCHEMA) is False          # top-level array
    # missing required key
    assert output_is_schema_valid(
        {"headline": "H", "subheadline": "S", "body": "B", "summary": "M"}, WRITER_SCHEMA) is False
    # additionalProperties: false
    assert output_is_schema_valid({**VALID_OUTPUT, "extra": 1}, WRITER_SCHEMA) is False
    # source item missing required src_id
    assert output_is_schema_valid(
        {**VALID_OUTPUT, "sources": [{"outlet": "x"}]}, WRITER_SCHEMA) is False


# --- shipped constant + wiring ------------------------------------------------


def test_glm_writer_routing_constant_is_fp8_and_fail_loud():
    assert GLM_5_2_WRITER_FP8_ROUTING["order"] == ["baidu/fp8", "ambient/fp8", "venice/fp8"]
    assert GLM_5_2_WRITER_FP8_ROUTING["allow_fallbacks"] is False
    assert GLM_5_2_WRITER_FP8_ROUTING["quantizations"] == ["fp8"]
    assert all(t.endswith("/fp8") for t in GLM_5_2_WRITER_FP8_ROUTING["order"])


def test_create_agents_writer_is_glm_with_opus46_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents, create_agents_hydrated

    for factory in (create_agents, create_agents_hydrated):
        writer = factory()["writer"]
        assert isinstance(writer, WriterWithFallback)
        assert writer.fallback_marker_key == "writer_fallback_used"
        # primary — the binding GLM operating point
        assert writer.primary.model == "z-ai/glm-5.2"
        assert writer.primary.temperature == 0.3
        assert writer.primary.max_tokens == 120000
        assert writer.primary.reasoning == "xhigh"
        assert writer.primary._provider_routing == GLM_5_2_WRITER_FP8_ROUTING
        assert writer.primary.output_schema == WRITER_SCHEMA
        # fallback — the PRE-SWAP incumbent VERBATIM (Opus 4.6, NOT Sonnet-5)
        assert writer.fallback.model == "anthropic/claude-opus-4.6"
        assert writer.fallback.temperature == 0.3
        assert writer.fallback.max_tokens == 32000       # Agent default (pre-swap value)
        assert writer.fallback.reasoning == "none"
        assert not writer.fallback._provider_routing      # no provider pin (== {}, as pre-swap)
        assert writer.fallback.output_schema == WRITER_SCHEMA
        assert "sonnet" not in writer.fallback.model.lower()  # deliberately not Sonnet-5
