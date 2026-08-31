"""DSV4-SWAPS-BUNDLE — consolidator / phase1 / bias-extractor on v4-flash-0731.

Three stages leave the OpenRouter ``deepseek-v4-pro`` fp8 pin for
``deepseek-v4-flash-0731`` on the two-channel wiring already proven by the
2026-08-24 swap (``_flash_0731_primary`` / ``_flash_0731_fallback``): channel C
(api.deepseek.com direct) primary, channel A (OpenRouter pinned to the vendor's
own endpoint) as the one-shot fallback.

What this file guards, per stage:

* **Wiring** — the operating point the eval validated actually reaches the
  agent: model, provider, reasoning effort, temperature, ``max_tokens`` from
  ``scratch/eval/t3b/caps.json``, ``json_object`` structured-output mode, no
  quantization filter on the fallback route, distinct fallback marker key —
  in BOTH pipeline variants.
* **Forced failure** — the C -> A path fires on a simulated channel-C transport
  failure and is LOUD: the fallback result is returned, the markers are set,
  and ``_collect_agent_metrics`` puts the stage's marker key into the
  ``run_stage_log.jsonl`` row. That path had never fired in production or in
  eval (0/54 in P1-CONFIRM), so it is exercised here before it is trusted.

The generic wrapper semantics live in tests/test_flash_stage_fallback.py; the
2026-08-24 stages' own operating points live in tests/test_flash_0731_swap.py.
"""

from __future__ import annotations

import logging

import pytest

from src.agent import AgentAPIError, AgentResult
from src.flash_stage_fallback import FlashStageWithFallback
from src.runner.runner import _collect_agent_metrics
from src.schemas import CONSOLIDATOR_SCHEMA


# --------------------------------------------------------------------------- #
# Shared helpers (one set for all three stages of the bundle)
# --------------------------------------------------------------------------- #
class FakeChannel:
    """Duck-typed stand-in for one channel's Agent inside the wrapper."""

    def __init__(self, model, structured=None, exc=None, provider="",
                 cost=0.0, tokens=0):
        self.model = model
        self._structured = structured
        self._exc = exc
        self._provider = provider
        self._cost = cost
        self._tokens = tokens
        self.run_calls = 0
        self.reset_calls = 0
        self.last_cost_usd = 0.0
        self.last_tokens = 0

    async def run(self, *args, **kwargs):
        self.run_calls += 1
        if self._exc is not None:
            raise self._exc
        return AgentResult(
            content="{}",
            structured=self._structured,
            cost_usd=self._cost,
            tokens_used=self._tokens,
            model=self.model,
            provider=self._provider,
        )

    def reset_call_metrics(self):
        self.reset_calls += 1
        self.last_cost_usd = 0.0
        self.last_tokens = 0


def forced_c_failure_wrapper(*, schema, structured, name, marker):
    """A wrapper whose channel-C primary is DOWN and whose channel-A fallback
    returns ``structured``. The shared forced-failure fixture for the bundle."""
    primary = FakeChannel(
        "deepseek-v4-flash",
        exc=AgentAPIError("channel C transport failure (simulated)", status_code=503),
    )
    fallback = FakeChannel(
        "deepseek/deepseek-v4-flash-0731",
        structured=structured,
        provider="DeepSeek",
        cost=0.0011,
        tokens=1234,
    )
    wrapper = FlashStageWithFallback(
        primary=primary,
        fallback=fallback,
        output_schema=schema,
        name=name,
        fallback_marker_key=marker,
    )
    return wrapper, primary, fallback


class _StageWith:
    """Minimal stand-in for the runner's view of an agent-stage."""

    def __init__(self, agent):
        self.agent = agent


def assert_channel_c_primary(agent, *, reasoning, temperature, max_tokens, label):
    assert agent.provider == "deepseek_direct", label
    # The vendor exposes exactly one flash id and 400s on every dated form.
    assert agent.model == "deepseek-v4-flash", label
    assert agent.reasoning == reasoning, label
    assert agent.temperature == temperature, label
    assert agent.max_tokens == max_tokens, label
    assert agent.structured_output_mode == "json_object", label
    assert not getattr(agent, "_provider_routing", {}), (
        label, "the direct API has no provider routing")


def assert_channel_a_fallback(agent, *, temperature, max_tokens, label):
    assert agent.provider == "openrouter", label
    assert agent.model == "deepseek/deepseek-v4-flash-0731", label
    assert agent.reasoning == "medium", label
    assert agent.temperature == temperature, label
    assert agent.max_tokens == max_tokens, label
    assert agent.structured_output_mode == "json_object", label
    routing = agent._provider_routing
    assert routing["order"] == ["deepseek"], label
    assert routing["allow_fallbacks"] is False, label
    # A quantization filter (or the strict-schema path's require_parameters)
    # removes the DeepSeek endpoint from its own route and the call 404s
    # (T2b §1.1) — the reason this route carries neither.
    assert "quantizations" not in routing, label
    assert "require_parameters" not in routing, label


def load_agents(variant, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents, create_agents_hydrated

    return create_agents() if variant == "production" else create_agents_hydrated()


VALID_CONSOLIDATION = {"voices_missing": ["a voice"], "topics_missing": []}


# --------------------------------------------------------------------------- #
# consolidator — TASK-CONSOLIDATOR-SWAP-FLASH0731 (T3b §7.1)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("variant", ["production", "hydrated"])
def test_consolidator_wired_to_flash_0731_at_minimal(variant, monkeypatch):
    """T3b §7.1's operating point, in both variants: flash-0731 @ minimal on
    channel C, temperature 0.3 and max_tokens 32000 unchanged by the swap."""
    agent = load_agents(variant, monkeypatch)["consolidator"]
    assert isinstance(agent, FlashStageWithFallback)
    assert agent.name == "consolidator"
    assert agent.fallback_marker_key == "consolidator_fallback_used"
    assert_channel_c_primary(
        agent.primary, reasoning="minimal", temperature=0.3, max_tokens=32000,
        label="consolidator primary",
    )
    assert_channel_a_fallback(
        agent.fallback, temperature=0.3, max_tokens=32000,
        label="consolidator fallback",
    )
    # the retired route must not reappear anywhere on this stage
    assert "deepseek-v4-pro" not in (agent.primary.model, agent.fallback.model)
    assert "fp8" not in str(agent.fallback._provider_routing)


@pytest.mark.asyncio
async def test_consolidator_forced_channel_c_failure_falls_back_loudly(caplog):
    """Forced failure: channel C is down, channel A serves, and the fallback is
    loud — WARNING line plus the persisted markers."""
    wrapper, primary, fallback = forced_c_failure_wrapper(
        schema=CONSOLIDATOR_SCHEMA,
        structured=VALID_CONSOLIDATION,
        name="consolidator",
        marker="consolidator_fallback_used",
    )
    with caplog.at_level(logging.WARNING):
        result = await wrapper.run("msg", context={})

    assert primary.run_calls == 1 and fallback.run_calls == 1
    assert result.structured == VALID_CONSOLIDATION
    assert wrapper.last_fallback_used is True
    assert wrapper.last_model_used == "deepseek/deepseek-v4-flash-0731"
    assert wrapper.last_provider_used == "DeepSeek"
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "consolidator FALLBACK" in text
    assert "channel C transport failure (simulated)" in text


@pytest.mark.asyncio
async def test_consolidator_fallback_marker_reaches_the_stage_log(caplog):
    """The forced fallback is not just logged, it is PERSISTED: the runner's
    metric collector emits ``consolidator_fallback_used`` into the stage row."""
    wrapper, _primary, _fallback = forced_c_failure_wrapper(
        schema=CONSOLIDATOR_SCHEMA,
        structured=VALID_CONSOLIDATION,
        name="consolidator",
        marker="consolidator_fallback_used",
    )
    with caplog.at_level(logging.WARNING):
        await wrapper.run("msg", context={})

    row = _collect_agent_metrics(_StageWith(wrapper))
    assert row["consolidator_fallback_used"] is True
    assert row["model_used"] == "deepseek/deepseek-v4-flash-0731"
    assert row["provider_used"] == "DeepSeek"
    assert row["cost_usd"] == pytest.approx(0.0011)
    assert row["tokens"] == 1234


@pytest.mark.asyncio
async def test_consolidator_no_fallback_when_channel_c_answers():
    """The negative control: a healthy primary means no fallback call, and the
    row reports channel C — the state every production row should show."""
    primary = FakeChannel(
        "deepseek-v4-flash", structured=VALID_CONSOLIDATION,
        provider="deepseek_direct", cost=0.0004, tokens=900,
    )
    fallback = FakeChannel("deepseek/deepseek-v4-flash-0731",
                           structured=VALID_CONSOLIDATION)
    wrapper = FlashStageWithFallback(
        primary=primary, fallback=fallback, output_schema=CONSOLIDATOR_SCHEMA,
        name="consolidator", fallback_marker_key="consolidator_fallback_used",
    )
    await wrapper.run("msg", context={})
    assert fallback.run_calls == 0
    row = _collect_agent_metrics(_StageWith(wrapper))
    assert row["consolidator_fallback_used"] is False
    assert row["provider_used"] == "deepseek_direct"


@pytest.mark.asyncio
async def test_consolidator_stage_survives_a_channel_c_outage(monkeypatch):
    """End-to-end at stage level: ConsolidatorStage's empty-emission guard runs
    ON TOP of the wrapper, so a channel-C outage costs a fallback call, not the
    topic. The guard's retry budget is untouched by the swap."""
    from src.agent_stages import ConsolidatorStage
    from src.bus import EditorAssignment, RunBus, TopicBus

    wrapper, primary, fallback = forced_c_failure_wrapper(
        schema=CONSOLIDATOR_SCHEMA,
        structured=VALID_CONSOLIDATION,
        name="consolidator",
        marker="consolidator_fallback_used",
    )
    stage = ConsolidatorStage(wrapper)
    topic_bus = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    topic_bus.perspective_missing_positions = [
        {"type": "government", "description": "an unheard position"},
    ]
    out = await stage(topic_bus, RunBus().as_readonly())
    assert out.what_is_missing.voices_missing == ["a voice"]
    # exactly one guard attempt: the fallback's answer is non-empty
    assert primary.run_calls == 1 and fallback.run_calls == 1
    assert wrapper.last_fallback_used is True
