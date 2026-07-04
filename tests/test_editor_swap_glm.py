"""editor swap to GLM-5.2 + Sonnet-5 model fallback — TASK-EDITOR-SWAP-GLM.

Covers:
  * exact request bodies for the primary (GLM-5.2 @ xhigh, temp 0.3, max_tokens
    120000, fp8 pin) and the fallback (Sonnet-5, reasoning {enabled,effort:high},
    NO temperature, max_tokens 64000, no provider pin — the eval's 22/22 point);
  * the fallback fires on a simulated final transport failure AND on
    schema-invalid / structured=None primary output, and NOT on valid output;
  * the fallback is loud — a WARNING line + the persisted marker
    (model_used / provider_used / editor_fallback_used) that the runner writes to
    the run-level run_stage_log.jsonl row — and there is no silent-fallback path;
  * a fallback transport failure propagates (loud terminal failure);
  * the runner surfaces the editor marker under "editor_fallback_used" (distinct
    from qa_analyze's "qa_fallback_used" and writer's "writer_fallback_used"), and
    omits it for plain agents;
  * the shipped routing constant + create_agents() wiring (both variants);
  * the fallback is Sonnet-5, NOT the pre-swap Opus-4.6 incumbent.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import Agent, AgentAPIError, AgentResult
from src.editor_fallback import EditorWithFallback, output_is_schema_valid
from src.runner.runner import _collect_agent_metrics
from src.schemas import EDITOR_SCHEMA
from scripts.run import GLM_5_2_EDITOR_FP8_ROUTING

# Minimal EDITOR_SCHEMA-valid output (one assignment, all five required keys).
VALID_OUTPUT = {
    "assignments": [
        {
            "title": "A topic",
            "priority": 5,
            "selection_reason": "Because it is contested and significant.",
            "follow_up_to": None,
            "follow_up_reason": None,
        }
    ]
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
        provider_routing=GLM_5_2_EDITOR_FP8_ROUTING,
    )
    kw = await _captured_kwargs(agent, output_schema=EDITOR_SCHEMA)
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
    assert rf["schema"] == EDITOR_SCHEMA


@pytest.mark.asyncio
async def test_fallback_sonnet5_request_body_exact(prompt_file):
    """Fallback = Sonnet-5: reasoning {enabled,effort:high}, NO temperature,
    max_tokens 64000, no provider pin (only require_parameters for the schema)."""
    agent = _mk_agent(
        prompt_file,
        model="anthropic/claude-sonnet-5",
        temperature=None,                       # omitted entirely (5-family)
        max_tokens=64000,
        reasoning={"enabled": True, "effort": "high"},
    )
    kw = await _captured_kwargs(agent, output_schema=EDITOR_SCHEMA)
    assert kw["model"] == "anthropic/claude-sonnet-5"
    assert "temperature" not in kw              # NO temperature on the request
    assert kw["max_tokens"] == 64000
    assert kw["extra_body"]["reasoning"] == {"enabled": True, "effort": "high"}
    assert kw["extra_body"]["provider"] == {"require_parameters": True}
    rf = kw["response_format"]["json_schema"]
    assert rf["strict"] is True
    assert rf["schema"] == EDITOR_SCHEMA


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
    e = EditorWithFallback(primary, fallback, EDITOR_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.editor_fallback"):
        res = await e.run("msg", context={})

    assert res is primary._result
    assert fallback.run_calls == 0
    assert e.last_fallback_used is False
    assert e.last_model_used == "z-ai/glm-5.2"
    assert e.last_provider_used == "Baidu"
    assert e.last_cost_usd == 0.02 and e.last_tokens == 500
    assert "FALLBACK" not in caplog.text        # nothing loud on the happy path


@pytest.mark.asyncio
async def test_fallback_on_transport_failure(caplog):
    """Simulated exhausted-retries transport failure across all pinned providers."""
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("all providers down", status_code=502))
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.07, tokens=800, provider="Azure"),
    )
    e = EditorWithFallback(primary, fallback, EDITOR_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.editor_fallback"):
        res = await e.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert e.last_fallback_used is True
    assert e.last_model_used == "anthropic/claude-sonnet-5"
    assert e.last_provider_used == "Azure"
    # primary raised → only fallback cost is accounted
    assert e.last_cost_usd == 0.07 and e.last_tokens == 800
    assert "FALLBACK" in caplog.text
    assert "transport failure" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_structured",
    [
        None,                                                    # structured=None (the editor's xhigh failure mode)
        {},                                                      # missing required `assignments`
        {"assignments": [{"title": "T", "priority": 5, "selection_reason": "R"}]},  # item missing follow_up_* keys
        {"assignments": [{"title": "T", "priority": 5, "selection_reason": "R",
                          "follow_up_to": None, "follow_up_reason": None, "extra": 1}]},  # additionalProperties
        {**VALID_OUTPUT, "extra": 1},                            # top-level additionalProperties: false
    ],
)
async def test_fallback_on_schema_invalid_output(bad_structured, caplog):
    primary = _FakeAgent(
        "z-ai/glm-5.2",
        result=_result("z-ai/glm-5.2", bad_structured, cost=0.03, tokens=13000, provider="Baidu"),
    )
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.07, tokens=900),
    )
    e = EditorWithFallback(primary, fallback, EDITOR_SCHEMA)

    with caplog.at_level(logging.WARNING, logger="src.editor_fallback"):
        res = await e.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert e.last_fallback_used is True
    assert e.last_model_used == "anthropic/claude-sonnet-5"
    # primary DID return (not raised), so both attempts are accounted
    assert e.last_cost_usd == pytest.approx(0.10) and e.last_tokens == 13900
    assert "not schema-valid" in caplog.text


@pytest.mark.asyncio
async def test_fallback_transport_failure_propagates_loudly():
    """A transport failure on the *fallback* is the loud terminal failure — it
    propagates (the run fails); it is never swallowed into a silent success."""
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("primary down", status_code=500))
    fallback = _FakeAgent("anthropic/claude-sonnet-5", exc=AgentAPIError("fallback down", status_code=500))
    e = EditorWithFallback(primary, fallback, EDITOR_SCHEMA)

    with pytest.raises(AgentAPIError):
        await e.run("msg")
    assert fallback.run_calls == 1


@pytest.mark.asyncio
async def test_reset_call_metrics_clears_markers_and_underlying():
    primary = _FakeAgent("z-ai/glm-5.2", result=_result("z-ai/glm-5.2", VALID_OUTPUT, cost=0.02, tokens=5))
    fallback = _FakeAgent("anthropic/claude-sonnet-5")
    e = EditorWithFallback(primary, fallback, EDITOR_SCHEMA)
    await e.run("msg")
    assert e.last_model_used == "z-ai/glm-5.2"

    e.reset_call_metrics()
    assert e.last_cost_usd == 0.0 and e.last_tokens == 0
    assert e.last_model_used == "" and e.last_provider_used == ""
    assert e.last_fallback_used is False
    assert primary.reset_calls == 1 and fallback.reset_calls == 1


# --- runner marker surfacing --------------------------------------------------


class _Stage:
    def __init__(self, agent):
        self.agent = agent


@pytest.mark.asyncio
async def test_runner_surfaces_editor_fallback_marker():
    primary = _FakeAgent("z-ai/glm-5.2", exc=AgentAPIError("down", status_code=500))
    fallback = _FakeAgent(
        "anthropic/claude-sonnet-5",
        result=_result("anthropic/claude-sonnet-5", VALID_OUTPUT, cost=0.07, tokens=800, provider="Azure"),
    )
    e = EditorWithFallback(primary, fallback, EDITOR_SCHEMA)
    await e.run("msg")

    metrics = _collect_agent_metrics(_Stage(e))
    assert metrics["model_used"] == "anthropic/claude-sonnet-5"
    assert metrics["provider_used"] == "Azure"
    assert metrics["editor_fallback_used"] is True
    assert "qa_fallback_used" not in metrics          # editor key, not qa's
    assert "writer_fallback_used" not in metrics       # editor key, not writer's
    assert metrics["cost_usd"] == 0.07 and metrics["tokens"] == 800


@pytest.mark.asyncio
async def test_runner_marks_editor_no_fallback_on_happy_path():
    primary = _FakeAgent(
        "z-ai/glm-5.2",
        result=_result("z-ai/glm-5.2", VALID_OUTPUT, cost=0.03, tokens=600, provider="Baidu"),
    )
    fallback = _FakeAgent("anthropic/claude-sonnet-5")
    e = EditorWithFallback(primary, fallback, EDITOR_SCHEMA)
    await e.run("msg")

    metrics = _collect_agent_metrics(_Stage(e))
    assert metrics["model_used"] == "z-ai/glm-5.2"
    assert metrics["provider_used"] == "Baidu"
    assert metrics["editor_fallback_used"] is False   # present + False on the happy path


def test_runner_omits_marker_for_plain_agent():
    class _PlainAgent:
        last_cost_usd = 0.1
        last_tokens = 42

    metrics = _collect_agent_metrics(_Stage(_PlainAgent()))
    assert "model_used" not in metrics
    assert "editor_fallback_used" not in metrics
    assert metrics == {"cost_usd": 0.1, "tokens": 42}


# --- schema-validity gate -----------------------------------------------------


def test_editor_output_schema_validity_gate():
    assert output_is_schema_valid(VALID_OUTPUT, EDITOR_SCHEMA) is True
    assert output_is_schema_valid(None, EDITOR_SCHEMA) is False        # structured=None
    assert output_is_schema_valid([], EDITOR_SCHEMA) is False          # top-level array
    assert output_is_schema_valid({}, EDITOR_SCHEMA) is False          # missing assignments
    # assignment missing required follow_up_* keys
    assert output_is_schema_valid(
        {"assignments": [{"title": "T", "priority": 5, "selection_reason": "R"}]},
        EDITOR_SCHEMA) is False
    # top-level additionalProperties: false
    assert output_is_schema_valid({**VALID_OUTPUT, "extra": 1}, EDITOR_SCHEMA) is False


# --- shipped constant + wiring ------------------------------------------------


def test_glm_editor_routing_constant_is_fp8_and_fail_loud():
    assert GLM_5_2_EDITOR_FP8_ROUTING["order"] == ["baidu/fp8", "ambient/fp8", "venice/fp8"]
    assert GLM_5_2_EDITOR_FP8_ROUTING["allow_fallbacks"] is False
    assert GLM_5_2_EDITOR_FP8_ROUTING["quantizations"] == ["fp8"]
    assert all(t.endswith("/fp8") for t in GLM_5_2_EDITOR_FP8_ROUTING["order"])


def test_create_agents_editor_is_glm_with_sonnet5_fallback(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents, create_agents_hydrated

    for factory in (create_agents, create_agents_hydrated):
        editor = factory()["editor"]
        assert isinstance(editor, EditorWithFallback)
        assert editor.fallback_marker_key == "editor_fallback_used"
        # primary — the binding GLM operating point
        assert editor.primary.model == "z-ai/glm-5.2"
        assert editor.primary.temperature == 0.3
        assert editor.primary.max_tokens == 120000
        assert editor.primary.reasoning == "xhigh"
        assert editor.primary._provider_routing == GLM_5_2_EDITOR_FP8_ROUTING
        assert editor.primary.output_schema == EDITOR_SCHEMA
        # fallback — Sonnet-5 (the eval's 22/22 point), NOT the Opus-4.6 incumbent
        assert editor.fallback.model == "anthropic/claude-sonnet-5"
        assert editor.fallback.temperature is None       # omitted (5-family)
        assert editor.fallback.max_tokens == 64000
        assert editor.fallback.reasoning == {"enabled": True, "effort": "high"}
        assert not editor.fallback._provider_routing      # no provider pin (== {})
        assert editor.fallback.output_schema == EDITOR_SCHEMA
        assert "opus" not in editor.fallback.model.lower()  # deliberately not the Opus-4.6 incumbent
