"""Flash-stage one-shot model fallback — TASK-RESEARCHER-ASSEMBLE-FALLBACK
(extended to curator_topic_discovery + resolve_actor_aliases).

Covers the generic wrapper behaviour (mirrors tests/test_writer_swap_glm.py):
  * no fallback + no loud logging when the primary output is schema-valid;
  * the fallback fires on a simulated final transport failure AND on a
    schema-invalid final output, and returns the fallback result;
  * the fallback is loud — a WARNING line + the persisted markers
    (last_model_used / last_provider_used / last_fallback_used) surfaced under
    the per-instance fallback_marker_key;
  * a fallback transport failure propagates (loud terminal failure);
  * cost/tokens accounting (fallback-only when primary raised; summed when the
    primary returned an invalid output then the fallback ran);
Plus a wiring assertion: all three deepseek-v4-flash stages are wrapped with a
gemini-3-flash-preview fallback, the correct distinct marker keys, and NO fp8
pin on the fallback — in both pipeline variants.
"""

from __future__ import annotations

import logging

import pytest

from src.agent import AgentAPIError, AgentResult
from src.flash_stage_fallback import FlashStageWithFallback
from src.schemas import RESEARCHER_ASSEMBLE_SCHEMA

VALID_OUTPUT = {
    "sources": [],
    "preliminary_divergences": [],
    "coverage_gaps": [],
}
MARKER = "researcher_assemble_fallback_used"


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


def _wrap(primary, fallback, name="researcher_assemble", marker=MARKER):
    return FlashStageWithFallback(
        primary, fallback, RESEARCHER_ASSEMBLE_SCHEMA, name=name, fallback_marker_key=marker
    )


def test_marker_key_name_and_mirrored_params():
    primary = _FakeAgent("deepseek/deepseek-v4-flash")
    primary.temperature, primary.max_tokens, primary.reasoning = 0.5, 160000, "none"
    w = _wrap(primary, _FakeAgent("google/gemini-3-flash-preview"))
    assert w.fallback_marker_key == MARKER
    assert w.name == "researcher_assemble"
    assert w.model == "deepseek/deepseek-v4-flash"
    # decode params mirror the primary for the stages' introspection getattr
    assert w.temperature == 0.5 and w.max_tokens == 160000 and w.reasoning == "none"


@pytest.mark.asyncio
async def test_no_fallback_on_valid_primary_output(caplog):
    primary = _FakeAgent(
        "deepseek/deepseek-v4-flash",
        result=_result("deepseek/deepseek-v4-flash", VALID_OUTPUT, cost=0.01, tokens=500, provider="Baidu"),
    )
    fallback = _FakeAgent("google/gemini-3-flash-preview")
    w = _wrap(primary, fallback)

    with caplog.at_level(logging.WARNING, logger="src.flash_stage_fallback"):
        res = await w.run("msg", context={})

    assert res is primary._result
    assert fallback.run_calls == 0
    assert w.last_fallback_used is False
    assert w.last_model_used == "deepseek/deepseek-v4-flash"
    assert w.last_provider_used == "Baidu"
    assert w.last_cost_usd == 0.01 and w.last_tokens == 500
    assert "FALLBACK" not in caplog.text


@pytest.mark.asyncio
async def test_fallback_on_transport_failure(caplog):
    # exactly the 2026-07-14 shape: a non-retryable provider error surfaces as
    # AgentAPIError after Agent's own retries.
    primary = _FakeAgent(
        "deepseek/deepseek-v4-flash",
        exc=AgentAPIError("Provider returned error", status_code=400),
    )
    fallback = _FakeAgent(
        "google/gemini-3-flash-preview",
        result=_result("google/gemini-3-flash-preview", VALID_OUTPUT, cost=0.02, tokens=800, provider="Google"),
    )
    w = _wrap(primary, fallback)

    with caplog.at_level(logging.WARNING, logger="src.flash_stage_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_fallback_used is True
    assert w.last_model_used == "google/gemini-3-flash-preview"
    assert w.last_provider_used == "Google"
    # primary raised → only fallback cost is accounted
    assert w.last_cost_usd == 0.02 and w.last_tokens == 800
    assert "FALLBACK" in caplog.text
    assert "transport failure" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_structured",
    [
        None,                                                          # unparseable / truncated to nothing
        {"sources": [], "preliminary_divergences": []},                # missing required coverage_gaps
        {**VALID_OUTPUT, "extra": 1},                                  # additionalProperties: false
        {"sources": [{"url": "x"}], "preliminary_divergences": [], "coverage_gaps": []},  # source item missing required fields
    ],
)
async def test_fallback_on_schema_invalid_output(bad_structured, caplog):
    primary = _FakeAgent(
        "deepseek/deepseek-v4-flash",
        result=_result("deepseek/deepseek-v4-flash", bad_structured, cost=0.03, tokens=160000, provider="Baidu"),
    )
    fallback = _FakeAgent(
        "google/gemini-3-flash-preview",
        result=_result("google/gemini-3-flash-preview", VALID_OUTPUT, cost=0.02, tokens=900),
    )
    w = _wrap(primary, fallback)

    with caplog.at_level(logging.WARNING, logger="src.flash_stage_fallback"):
        res = await w.run("msg")

    assert res is fallback._result
    assert fallback.run_calls == 1
    assert w.last_fallback_used is True
    assert w.last_model_used == "google/gemini-3-flash-preview"
    # primary DID return (not raised), so both attempts are accounted
    assert w.last_cost_usd == pytest.approx(0.05) and w.last_tokens == 160900
    assert "not schema-valid" in caplog.text


@pytest.mark.asyncio
async def test_fallback_transport_failure_propagates():
    primary = _FakeAgent("deepseek/deepseek-v4-flash", exc=AgentAPIError("primary down", status_code=502))
    fallback = _FakeAgent("google/gemini-3-flash-preview", exc=AgentAPIError("fallback down too", status_code=500))
    w = _wrap(primary, fallback)
    with pytest.raises(AgentAPIError, match="fallback down too"):
        await w.run("msg")


def test_reset_call_metrics_clears_markers_and_delegates():
    primary = _FakeAgent("deepseek/deepseek-v4-flash")
    fallback = _FakeAgent("google/gemini-3-flash-preview")
    w = _wrap(primary, fallback)
    w.last_fallback_used = True
    w.last_model_used = "x"
    w.last_cost_usd = 1.0
    w.reset_call_metrics()
    assert w.last_fallback_used is False
    assert w.last_model_used == ""
    assert w.last_cost_usd == 0.0
    assert primary.reset_calls == 1 and fallback.reset_calls == 1


@pytest.mark.parametrize("variant", ["production", "hydrated"])
def test_all_three_flash_stages_wired_with_gemini_fallback(variant):
    """Wiring: researcher_assemble, curator_topic_discovery, resolve_actor_aliases
    are each wrapped with a gemini-3-flash-preview fallback carrying the right
    distinct marker key and NO fp8 pin — in both pipeline variants."""
    from scripts.run import create_agents, create_agents_hydrated

    ags = create_agents() if variant == "production" else create_agents_hydrated()
    expected = {
        "researcher_assemble": "researcher_assemble_fallback_used",
        "curator_topic_discovery": "curator_topic_discovery_fallback_used",
        "resolve_actor_aliases": "resolve_actor_aliases_fallback_used",
    }
    for key, marker in expected.items():
        a = ags[key]
        assert isinstance(a, FlashStageWithFallback), (key, type(a))
        assert a.fallback_marker_key == marker
        assert a.name == key
        assert a.primary.model == "deepseek/deepseek-v4-flash"
        # streamlake removed from the pin (the 2026-07-14 fix)
        assert "streamlake/fp8" not in a.primary._provider_routing["order"]
        # fallback is gemini on a different ecosystem, with NO fp8 pin
        assert a.fallback.model == "google/gemini-3-flash-preview"
        assert not getattr(a.fallback, "_provider_routing", {}), (key, "fallback must not carry the fp8 pin")
