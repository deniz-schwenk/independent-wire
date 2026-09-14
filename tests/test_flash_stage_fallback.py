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
Plus wiring assertions: the deepseek-flash stages are wrapped with the channel-A
fallback, the correct distinct marker keys, and NO fp8 pin on the fallback — in
both pipeline variants; and a forced-failure test that drives each wrapped
stage's primary into final failure and inspects the request the ladder actually
puts on the wire for rung 2 (TASK-RUNG2-REPAIR).
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
        {"sources": []},                                               # missing required preliminary_divergences
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
async def test_no_fallback_when_coverage_gaps_absent(caplog):
    """TASK-ASSEMBLE-SCHEMA-FIX. The assemble prompt asks for two
    top-level fields and never names ``coverage_gaps``; the stage drops
    the key on arrival. This wrapper validates the primary's output
    against RESEARCHER_ASSEMBLE_SCHEMA locally, so while the key was in
    ``required`` a fully prompt-compliant dossier read as schema-invalid
    and burned a Gemini fallback call. It only never happened in
    production because provider-side strict decoding force-filled the
    key first (T2b, docs/evals/dsv4-0731/T2B-REPORT.md). The
    prompt-shaped output must be accepted on the primary.
    """
    prompt_shaped = {"sources": [], "preliminary_divergences": []}
    primary = _FakeAgent(
        "deepseek/deepseek-v4-flash",
        result=_result(
            "deepseek/deepseek-v4-flash", prompt_shaped,
            cost=0.01, tokens=500, provider="Baidu",
        ),
    )
    fallback = _FakeAgent("google/gemini-3-flash-preview")
    w = _wrap(primary, fallback)

    with caplog.at_level(logging.WARNING, logger="src.flash_stage_fallback"):
        res = await w.run("msg", context={})

    assert res is primary._result
    assert fallback.run_calls == 0
    assert w.last_fallback_used is False
    assert "not schema-valid" not in caplog.text


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
def test_all_three_flash_stages_wired_with_channel_fallback(variant, monkeypatch):
    """Wiring: researcher_assemble, curator_topic_discovery,
    resolve_actor_aliases are each wrapped with a CHANNEL fallback carrying
    the right distinct marker key — in both pipeline variants.

    Retargeted 2026-08-24 (TASK-FLASH-0731-SWAP). Until then the net was
    ``google/gemini-3-flash-preview`` — a different model, which is what it
    served into the pipeline whenever it fired. Both channels then carried
    v4-flash-0731; since TASK-RUNG2-REPAIR (2026-09-14) they carry the vendor's
    current flash build on each side rather than one shared dated id: channel C
    (api.deepseek.com) primary, channel A (OpenRouter pinned to the vendor's
    own endpoint) fallback. The detailed
    per-stage operating points live in tests/test_flash_0731_swap.py; this
    test guards the wrapper topology.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
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
        # channel C primary: the vendor's single undated flash id
        assert a.primary.provider == "deepseek_direct", key
        assert a.primary.model == "deepseek-v4-flash", key
        assert not getattr(a.primary, "_provider_routing", {}), (
            key, "the direct API has no provider routing")
        # channel A fallback: the vendor's CURRENT first-party flash build
        # (the dated 0731 id it used to carry was retired from the vendor's
        # OpenRouter endpoint — TASK-RUNG2-REPAIR), vendor endpoint pinned,
        # and NO quantization filter (that would 404 the endpoint out)
        assert a.fallback.provider == "openrouter", key
        assert a.fallback.model == "deepseek/deepseek-v4.1-flash", key
        assert a.fallback._provider_routing["order"] == ["deepseek"], key
        assert "quantizations" not in a.fallback._provider_routing, key
        # the retired routes must not reappear
        assert "google/gemini-3-flash-preview" not in (
            a.primary.model, a.fallback.model), key
        assert "fp8" not in str(a.fallback._provider_routing), key


# --- rung-2 repair: forced failure, inspected on the wire ---------------------
# TASK-RUNG2-REPAIR (2026-09-14). The vendor retired
# `deepseek/deepseek-v4-flash-0731` from its own OpenRouter endpoint between
# 2026-09-06 and 2026-09-10; the native pin then resolved to the empty set and
# the rung 404'd, losing a Topic Package on 09-10
# (scratch/audit/bias-telemetry-forensics.md, A4).
#
# The wiring test above reads the configured attributes. This one is stronger
# and is the acceptance check: it drives a REAL production wrapper's primary
# into final failure and asserts on the request body the fallback Agent puts on
# the wire — model id AND the native pin together, since either one alone is
# what broke (a live id with a dead pin 404s exactly like a dead id).

ALL_FLASH_STAGES = (
    "curator_topic_discovery",
    "researcher_assemble",
    "resolve_actor_aliases",
    "consolidator",
    "hydration_aggregator_phase1",
)


def _flash_wrappers(monkeypatch):
    """Every FlashStageWithFallback in the hydrated production wiring.

    Six, not the three TASK-FLASH-0731-SWAP shipped: TASK-DSV4-SWAPS-BUNDLE
    added consolidator, hydration_aggregator_phase1 and the bias extractor to
    the same helpers, and the bias one is nested inside the BiasComposite where
    a top-level `agents[...]` scan does not see it.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents_hydrated

    ags = create_agents_hydrated()
    out = {k: ags[k] for k in ALL_FLASH_STAGES}
    out["bias_candidate_extractor"] = ags["bias_language"].extractor
    return out


@pytest.mark.asyncio
async def test_forced_primary_failure_puts_v41_flash_on_the_wire(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from src.agent import AgentError

    wrappers = _flash_wrappers(monkeypatch)
    assert len(wrappers) == 6, "all six flash stages share the repaired rung"

    for stage, w in wrappers.items():
        async def _boom(*a, **k):
            raise AgentError("channel C down (simulated final failure)")

        monkeypatch.setattr(w.primary, "run", _boom)
        create = AsyncMock(return_value=MagicMock())
        monkeypatch.setattr(w.fallback._client.chat.completions, "create", create)

        try:
            await w.run("go")
        except Exception:
            # The stubbed response is not parseable; irrelevant here — the
            # assertion is about what was SENT, which is already recorded.
            pass

        assert create.call_args_list, f"{stage}: rung 2 never attempted"
        # The FIRST request is the rung-2 attempt. Later ones are Agent's own
        # parse-retries against the stubbed (unparseable) MagicMock response
        # and carry a different body; asserting on call_args would test the
        # retry, not the rung.
        kw = create.call_args_list[0].kwargs
        assert kw["model"] == "deepseek/deepseek-v4.1-flash", stage
        prov = kw["extra_body"]["provider"]
        assert prov == {"order": ["deepseek"], "allow_fallbacks": False}, stage
        # the two things that individually 404 this endpoint out of its own
        # route, and so must stay absent (T2b §1.1 / verified 2026-08-31)
        assert "quantizations" not in prov, stage
        assert "require_parameters" not in kw["extra_body"], stage
        assert kw["response_format"] == {"type": "json_object"}, stage


def test_no_stage_still_points_rung_2_at_the_retired_dated_id(monkeypatch):
    """The retirement is silent from the repo's side — nothing raises if this
    regresses, the rung simply 404s in production at 06:00. Pin it."""
    for stage, w in _flash_wrappers(monkeypatch).items():
        assert w.fallback.model == "deepseek/deepseek-v4.1-flash", stage
        assert "0731" not in w.fallback.model, stage
