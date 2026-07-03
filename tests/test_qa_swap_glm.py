"""qa_analyze swap to GLM-5.2 + Sonnet-5 model fallback — TASK-QA-SWAP-GLM.

Covers:
  * exact request bodies for the primary (GLM-5.2 @ xhigh, fp8 pin) and the
    fallback (Sonnet-5: no temperature, reasoning.enabled=true);
  * the Agent-level knobs the fallback needs (temperature=None omits the field;
    a dict reasoning passes straight through, un-mutated across calls);
  * the fallback fires on a simulated final transport failure AND on
    schema-invalid / truncated primary output, and NOT on valid output;
  * the fallback is loud — a WARNING line + the persisted marker
    (model_used / qa_fallback_used) that the runner writes to
    run_stage_log.jsonl — and there is no silent-fallback path;
  * the schema-validity gate that drives the fallback trigger;
  * the shipped routing constant + create_agents() wiring (both variants).
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import Agent, AgentAPIError, AgentResult
from src.qa_fallback import QaAnalyzeWithFallback, qa_output_is_schema_valid
from src.runner.runner import _collect_agent_metrics
from src.schemas import QA_ANALYZE_SCHEMA
from scripts.run import GLM_5_2_QA_FP8_ROUTING

VALID_OUTPUT = {"problems_found": [], "qa_corrections": [], "divergences": []}


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
    """Primary = GLM-5.2 @ xhigh, temp 0.1, max_tokens 120000, fp8 pin."""
    agent = _mk_agent(
        prompt_file,
        model="z-ai/glm-5.2",
        temperature=0.1,
        max_tokens=120000,
        reasoning="xhigh",
        provider_routing=GLM_5_2_QA_FP8_ROUTING,
    )
    kw = await _captured_kwargs(agent, output_schema=QA_ANALYZE_SCHEMA)
    assert kw["model"] == "z-ai/glm-5.2"
    assert kw["temperature"] == 0.1
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
    assert rf["schema"] == QA_ANALYZE_SCHEMA


@pytest.mark.asyncio
async def test_fallback_sonnet5_request_body_exact(prompt_file):
    """Fallback = Sonnet-5: NO temperature field, reasoning.enabled=true,
    max_tokens 64000, no provider pin (only require_parameters for the schema)."""
    agent = _mk_agent(
        prompt_file,
        model="anthropic/claude-sonnet-5",
        temperature=None,
        max_tokens=64000,
        reasoning={"enabled": True},
    )
    kw = await _captured_kwargs(agent, output_schema=QA_ANALYZE_SCHEMA)
    assert kw["model"] == "anthropic/claude-sonnet-5"
    assert "temperature" not in kw          # 4.7/5 family 400s on non-default temp
    assert kw["max_tokens"] == 64000
    assert kw["extra_body"]["reasoning"] == {"enabled": True}
    assert kw["extra_body"]["provider"] == {"require_parameters": True}


@pytest.mark.asyncio
async def test_temperature_none_omits_field_but_float_is_sent(prompt_file):
    with_temp = _mk_agent(prompt_file, temperature=0.1, reasoning="none")
    kw_with = await _captured_kwargs(with_temp)
    assert kw_with["temperature"] == 0.1

    no_temp = _mk_agent(prompt_file, temperature=None, reasoning="none")
    kw_without = await _captured_kwargs(no_temp)
    assert "temperature" not in kw_without


@pytest.mark.asyncio
async def test_reasoning_dict_passes_through_unmutated(prompt_file):
    routing = {"enabled": True}
    agent = _mk_agent(prompt_file, reasoning=routing, temperature=None)
    kw = await _captured_kwargs(agent)
    assert kw["extra_body"]["reasoning"] == {"enabled": True}
    # the emitted block is a deep copy — mutating it must not touch the instance
    kw["extra_body"]["reasoning"]["enabled"] = False
    assert agent.reasoning == {"enabled": True}
    assert routing == {"enabled": True}


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
    fallback = _FakeAgent("anthropic/claude-sonnet-5")
    w = QaAnalyzeWithFallback(primary, fallback, QA_ANALYZE_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.qa_fallback"):
        res = await w.run("msg", context={})

    assert res is primary._result
    assert fallback.run_calls == 0
    assert w.last_qa_fallback_used is False
    assert w.last_model_used == "z-ai/glm-5.2"
    assert w.last_provider_used == "Baidu"
    assert w.last_cost_usd == 0.02 and w.last_tokens == 500
    assert "FALLBACK" not in caplog.text        # nothing loud on the happy path


@pytest.mark.asyncio
async def test_fallback_on_transport_failure(caplog):
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("all providers down", status_code=502))
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.05, tokens=800, provider="Anthropic"),
    )
    w = QaAnalyzeWithFallback(primary, fallback, QA_ANALYZE_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.qa_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_qa_fallback_used is True
    assert w.last_model_used == "anthropic/claude-sonnet-5"
    # primary raised → only fallback cost is accounted
    assert w.last_cost_usd == 0.05 and w.last_tokens == 800
    assert "FALLBACK" in caplog.text
    assert "transport failure" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_structured",
    [
        None,                                                   # unparseable / truncated to nothing
        {"problems_found": [], "qa_corrections": []},           # missing required `divergences`
        {"problems_found": [{"article_excerpt": "x", "problem": "y"}],  # item missing `explanation`
         "qa_corrections": [], "divergences": []},
    ],
)
async def test_fallback_on_schema_invalid_output(bad_structured, caplog):
    primary = _FakeAgent(
        "z-ai/glm-5.2",
        result=_result("z-ai/glm-5.2", bad_structured, cost=0.03, tokens=64000, provider="Baidu"),
    )
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.05, tokens=900),
    )
    w = QaAnalyzeWithFallback(primary, fallback, QA_ANALYZE_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.qa_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_qa_fallback_used is True
    assert w.last_model_used == "anthropic/claude-sonnet-5"
    # primary DID return (not raised), so both attempts are accounted
    assert w.last_cost_usd == pytest.approx(0.08) and w.last_tokens == 64900
    assert "not schema-valid" in caplog.text


@pytest.mark.asyncio
async def test_fallback_transport_failure_propagates_loudly():
    """A transport failure on the *fallback* is the loud terminal failure —
    it propagates (topic fails); it is never swallowed into a silent success."""
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("primary down", status_code=500))
    fallback = _FakeAgent("anthropic/claude-sonnet-5", exc=AgentAPIError("fallback down", status_code=500))
    w = QaAnalyzeWithFallback(primary, fallback, QA_ANALYZE_SCHEMA)

    with pytest.raises(AgentAPIError):
        await w.run("msg")
    assert fallback.run_calls == 1


@pytest.mark.asyncio
async def test_reset_call_metrics_clears_markers_and_underlying():
    primary = _FakeAgent("z-ai/glm-5.2", result=_result("z-ai/glm-5.2", VALID_OUTPUT, cost=0.02, tokens=5))
    fallback = _FakeAgent("anthropic/claude-sonnet-5")
    w = QaAnalyzeWithFallback(primary, fallback, QA_ANALYZE_SCHEMA)
    await w.run("msg")
    assert w.last_model_used == "z-ai/glm-5.2"

    w.reset_call_metrics()
    assert w.last_cost_usd == 0.0 and w.last_tokens == 0
    assert w.last_model_used == "" and w.last_provider_used == ""
    assert w.last_qa_fallback_used is False
    assert primary.reset_calls == 1 and fallback.reset_calls == 1


# --- runner marker surfacing --------------------------------------------------


class _Stage:
    def __init__(self, agent):
        self.agent = agent


@pytest.mark.asyncio
async def test_runner_surfaces_fallback_marker():
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("down", status_code=500))
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.05, tokens=800, provider="Anthropic"),
    )
    w = QaAnalyzeWithFallback(primary, fallback, QA_ANALYZE_SCHEMA)
    await w.run("msg")

    metrics = _collect_agent_metrics(_Stage(w))
    assert metrics["model_used"] == "anthropic/claude-sonnet-5"
    assert metrics["provider_used"] == "Anthropic"
    assert metrics["qa_fallback_used"] is True
    assert metrics["cost_usd"] == 0.05 and metrics["tokens"] == 800


def test_runner_omits_marker_for_plain_agent():
    class _PlainAgent:
        last_cost_usd = 0.1
        last_tokens = 42

    metrics = _collect_agent_metrics(_Stage(_PlainAgent()))
    assert "model_used" not in metrics
    assert "qa_fallback_used" not in metrics
    assert metrics == {"cost_usd": 0.1, "tokens": 42}


# --- schema-validity gate -----------------------------------------------------


def test_qa_output_schema_validity_gate():
    assert qa_output_is_schema_valid(VALID_OUTPUT, QA_ANALYZE_SCHEMA) is True
    # a full, well-formed record set
    full = {
        "problems_found": [
            {"article_excerpt": "e", "problem": "unsupported_claim", "explanation": "x"}
        ],
        "qa_corrections": [{"proposed_correction": "c", "correction_needed": True}],
        "divergences": [
            {"type": "t", "description": "d", "source_ids": ["s1"],
             "resolution": "resolved", "resolution_note": "n"}
        ],
        "article": {"headline": "h", "subheadline": "s", "body": "b", "summary": "m"},
    }
    assert qa_output_is_schema_valid(full, QA_ANALYZE_SCHEMA) is True

    assert qa_output_is_schema_valid(None, QA_ANALYZE_SCHEMA) is False
    assert qa_output_is_schema_valid([], QA_ANALYZE_SCHEMA) is False   # top-level array
    assert qa_output_is_schema_valid({"problems_found": []}, QA_ANALYZE_SCHEMA) is False  # missing required
    # additionalProperties: false
    assert qa_output_is_schema_valid({**VALID_OUTPUT, "extra": 1}, QA_ANALYZE_SCHEMA) is False
    # wrong scalar type: correction_needed must be boolean
    bad_bool = {"problems_found": [], "divergences": [],
                "qa_corrections": [{"proposed_correction": "c", "correction_needed": "yes"}]}
    assert qa_output_is_schema_valid(bad_bool, QA_ANALYZE_SCHEMA) is False


# --- shipped constant + wiring ------------------------------------------------


def test_glm_qa_routing_constant_is_fp8_and_fail_loud():
    assert GLM_5_2_QA_FP8_ROUTING["order"] == ["baidu/fp8", "ambient/fp8", "venice/fp8"]
    assert GLM_5_2_QA_FP8_ROUTING["allow_fallbacks"] is False
    assert GLM_5_2_QA_FP8_ROUTING["quantizations"] == ["fp8"]
    assert all(t.endswith("/fp8") for t in GLM_5_2_QA_FP8_ROUTING["order"])


def test_create_agents_qa_is_glm_with_sonnet5_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents, create_agents_hydrated

    for factory in (create_agents, create_agents_hydrated):
        qa = factory()["qa_analyze"]
        assert isinstance(qa, QaAnalyzeWithFallback)
        # primary
        assert qa.primary.model == "z-ai/glm-5.2"
        assert qa.primary.temperature == 0.1
        assert qa.primary.max_tokens == 120000
        assert qa.primary.reasoning == "xhigh"
        assert qa.primary._provider_routing == GLM_5_2_QA_FP8_ROUTING
        assert qa.primary.output_schema == QA_ANALYZE_SCHEMA
        # fallback
        assert qa.fallback.model == "anthropic/claude-sonnet-5"
        assert qa.fallback.temperature is None
        assert qa.fallback.max_tokens == 64000
        assert qa.fallback.reasoning == {"enabled": True}
        assert qa.fallback.output_schema == QA_ANALYZE_SCHEMA
