"""v4-flash-0731 swap — channel C primary, channel A fallback
(TASK-FLASH-0731-SWAP, 2026-08-24).

Covers the three things the swap adds that nothing else in the suite pins:

1. the ``deepseek_direct`` provider path in ``src.agent`` — key resolution,
   ``reasoning_effort`` as a STRING, ``json_object`` instead of strict
   ``json_schema``, computed cost, and the channel label in ``provider_used``;
2. the ``json_object`` mode on channel A, which is not cosmetic — the strict
   path would inject ``require_parameters: true`` and 404 the pinned DeepSeek
   endpoint out of its own route (T2b §1.1);
3. the forced-failure path: channel C returns invalid JSON, channel A fallback
   fires, and it is LOUD (warning line + persisted markers).

Every eval reference is to docs/evals/dsv4-0731/.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import (
    Agent,
    AgentError,
    AgentResult,
    DEEPSEEK_DIRECT_PRICES,
    JSON_OBJECT_ONLY_PROVIDERS,
    PROVIDER_DEFAULTS,
    deepseek_direct_cost_usd,
    deepseek_price_window,
)
from src.flash_stage_fallback import FlashStageWithFallback

TINY_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
    "additionalProperties": False,
}


@pytest.fixture
def prompt_file(tmp_path) -> str:
    path = tmp_path / "AGENTS.md"
    path.write_text("You are a helpful test assistant.")
    return str(path)


def _mk(prompt_file, **kw) -> Agent:
    kw.setdefault("api_key", "fake-key-for-unit-test")
    kw.setdefault("model", "deepseek-v4-flash")
    return Agent(
        name="t",
        system_prompt_path=prompt_file,
        instructions_path=prompt_file,
        **kw,
    )


async def _captured(agent: Agent, output_schema=None) -> dict:
    """Drive _call_with_retry once against a mocked client; return the kwargs."""
    agent._client.chat.completions.create = AsyncMock(return_value=MagicMock())
    await agent._call_with_retry(
        messages=[{"role": "user", "content": "x"}],
        tools=None,
        output_schema=output_schema,
    )
    return agent._client.chat.completions.create.call_args.kwargs


# --- 1. the deepseek_direct provider path ------------------------------------

def test_provider_default_points_at_the_vendor_and_reads_the_env_var():
    d = PROVIDER_DEFAULTS["deepseek_direct"]
    assert d["base_url"] == "https://api.deepseek.com"
    assert d["api_key_env"] == "DEEPSEEK_API_KEY"


def test_key_comes_from_the_environment(prompt_file, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
    agent = Agent(
        name="t", model="deepseek-v4-flash",
        system_prompt_path=prompt_file, instructions_path=prompt_file,
        provider="deepseek_direct",
    )
    assert agent.base_url == "https://api.deepseek.com"


def test_missing_key_fails_loudly_naming_the_variable(prompt_file, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        Agent(
            name="t", model="deepseek-v4-flash",
            system_prompt_path=prompt_file, instructions_path=prompt_file,
            provider="deepseek_direct",
        )


@pytest.mark.asyncio
async def test_reasoning_is_a_string_not_the_openrouter_object(prompt_file):
    """The direct API takes ``reasoning_effort: "<level>"``. Sending
    OpenRouter's ``reasoning: {"effort": ...}`` is ACCEPTED and ignored, so
    the wrong shape would silently run at the default (T2d §1.3)."""
    agent = _mk(prompt_file, provider="deepseek_direct", reasoning="low")
    body = await _captured(agent)
    assert body["extra_body"] == {"reasoning_effort": "low"}
    assert "reasoning" not in body["extra_body"]


@pytest.mark.asyncio
async def test_no_reasoning_configured_sends_none_explicitly(prompt_file):
    """The API's own default is reasoning ON — a silent multi-x cost surprise.
    'Not configured' must reach the wire as an explicit none."""
    agent = _mk(prompt_file, provider="deepseek_direct", reasoning=None)
    body = await _captured(agent)
    assert body["extra_body"]["reasoning_effort"] == "none"


@pytest.mark.asyncio
async def test_reasoning_dict_is_refused_rather_than_sent(prompt_file):
    """A dict is the OpenRouter shape. Because this API accepts and ignores
    it, silence is the failure mode — so the call raises instead of running
    at the default and billing for reasoning nobody configured."""
    agent = _mk(prompt_file, provider="deepseek_direct",
                reasoning={"effort": "medium"})
    with pytest.raises(AgentError, match="reasoning_effort STRING"):
        await _captured(agent)


@pytest.mark.asyncio
async def test_schema_becomes_json_object_never_strict(prompt_file):
    agent = _mk(prompt_file, provider="deepseek_direct", reasoning="low")
    body = await _captured(agent, output_schema=TINY_SCHEMA)
    assert body["response_format"] == {"type": "json_object"}
    assert "provider" not in body.get("extra_body", {})


def test_json_object_is_forced_for_the_provider_whatever_the_call_site_says(prompt_file):
    """A strict schema on this route is ignored by the server — the worst of
    both worlds — so the provider coerces the mode."""
    assert "deepseek_direct" in JSON_OBJECT_ONLY_PROVIDERS
    agent = _mk(prompt_file, provider="deepseek_direct",
                structured_output_mode="strict_schema")
    assert agent.structured_output_mode == "json_object"


def test_unknown_structured_output_mode_is_refused(prompt_file):
    with pytest.raises(AgentError, match="structured_output_mode"):
        _mk(prompt_file, provider="openrouter", structured_output_mode="loose")


# --- 2. channel A must also avoid the strict path ----------------------------

@pytest.mark.asyncio
async def test_channel_a_json_object_mode_omits_require_parameters(prompt_file):
    """``require_parameters: true`` is what filters the pinned DeepSeek
    endpoint out of its own route and 404s the call (T2b §1.1). In
    json_object mode it must not appear, while the pin itself still does."""
    routing = {"order": ["deepseek"], "allow_fallbacks": False}
    agent = _mk(
        prompt_file, model="deepseek/deepseek-v4-flash-0731",
        provider="openrouter", reasoning="medium",
        provider_routing=routing, structured_output_mode="json_object",
    )
    body = await _captured(agent, output_schema=TINY_SCHEMA)
    assert body["response_format"] == {"type": "json_object"}
    assert body["extra_body"]["provider"] == {
        "order": ["deepseek"], "allow_fallbacks": False,
    }
    assert "require_parameters" not in body["extra_body"]["provider"]
    assert "quantizations" not in body["extra_body"]["provider"]


@pytest.mark.asyncio
async def test_strict_mode_is_still_the_default_everywhere_else(prompt_file):
    """The swap must not quietly relax structured output for other stages."""
    agent = _mk(prompt_file, model="z-ai/glm-5.2", provider="openrouter",
                reasoning="none")
    body = await _captured(agent, output_schema=TINY_SCHEMA)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["extra_body"]["provider"]["require_parameters"] is True


# --- 3. cost, which the direct API does not report ---------------------------

def test_price_window_boundaries():
    """Peak is 01:00-04:00 and 06:00-10:00 UTC, Mon-Fri; the boundaries decide
    whether the 06:00-local production run pays double."""
    mon = lambda h: datetime(2026, 8, 24, h, 0, tzinfo=timezone.utc)   # noqa: E731
    sun = lambda h: datetime(2026, 8, 23, h, 0, tzinfo=timezone.utc)   # noqa: E731
    assert deepseek_price_window(mon(2)) == "peak"
    assert deepseek_price_window(mon(4)) == "offpeak"   # block is [01, 04)
    assert deepseek_price_window(mon(6)) == "peak"
    assert deepseek_price_window(mon(10)) == "offpeak"
    assert deepseek_price_window(sun(2)) == "offpeak"   # weekends never peak


def test_cost_is_computed_from_the_cache_split():
    usage = SimpleNamespace(prompt_cache_hit_tokens=100_000,
                            prompt_cache_miss_tokens=100_000,
                            completion_tokens=10_000)
    off = deepseek_direct_cost_usd(
        "deepseek-v4-flash", usage, datetime(2026, 8, 23, 19, tzinfo=timezone.utc))
    # 100k * .007 + 100k * .22 + 10k * .66, per million
    assert off == pytest.approx((100_000 * 0.007 + 100_000 * 0.22
                                 + 10_000 * 0.66) / 1e6)
    peak = deepseek_direct_cost_usd(
        "deepseek-v4-flash", usage, datetime(2026, 8, 24, 2, tzinfo=timezone.utc))
    assert peak == pytest.approx(off * 2)               # peak is exactly double


def test_cost_without_a_cache_split_bills_everything_as_a_miss():
    usage = SimpleNamespace(prompt_tokens=1_000_000, completion_tokens=0)
    got = deepseek_direct_cost_usd(
        "deepseek-v4-flash", usage, datetime(2026, 8, 23, 19, tzinfo=timezone.utc))
    assert got == pytest.approx(0.22)


def test_unpriced_model_reports_none_not_zero():
    """An alias roll must not silently report a wrong cost. None means
    'not measurable'; 0.0 would mean 'free'."""
    usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=1000)
    assert deepseek_direct_cost_usd("deepseek-v5-flash", usage) is None
    assert "deepseek-v4-flash" in DEEPSEEK_DIRECT_PRICES


def test_cost_for_prefers_the_reported_value(prompt_file):
    """OpenRouter reports cost directly; the computed path must not override
    it, or a channel-A call would be priced with a DeepSeek table."""
    agent = _mk(prompt_file, provider="openrouter",
                model="deepseek/deepseek-v4-flash-0731")
    resp = SimpleNamespace(
        model="deepseek/deepseek-v4-flash-0731",
        usage=SimpleNamespace(cost=0.0123, prompt_tokens=10, completion_tokens=10),
    )
    assert agent._cost_for(resp) == pytest.approx(0.0123)


def test_cost_for_computes_on_the_direct_channel(prompt_file):
    agent = _mk(prompt_file, provider="deepseek_direct", reasoning="low")
    resp = SimpleNamespace(
        model="deepseek-v4-flash",
        usage=SimpleNamespace(prompt_cache_hit_tokens=0,
                              prompt_cache_miss_tokens=1_000_000,
                              completion_tokens=0),
    )
    assert agent._cost_for(resp) is not None
    assert agent._cost_for(resp) > 0


def test_cost_for_warns_loudly_on_an_unpriced_served_model(prompt_file, caplog):
    agent = _mk(prompt_file, provider="deepseek_direct", reasoning="low")
    resp = SimpleNamespace(
        model="deepseek-v9-flash",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
    )
    with caplog.at_level(logging.WARNING, logger="src.agent"):
        assert agent._cost_for(resp) is None
    assert "price table" in caplog.text
    assert "tripwire" in caplog.text


# --- 4. forced failure: C returns invalid JSON, A fallback fires -------------

class _FakeAgent:
    """Duck-typed Agent stand-in, matching tests/test_flash_stage_fallback.py."""

    def __init__(self, model, provider, result=None, exc=None):
        self.model = model
        self.provider = provider
        self._result = result
        self._exc = exc
        self.run_calls = 0
        self.last_cost_usd = 0.0
        self.last_tokens = 0

    async def run(self, *args, **kwargs):
        self.run_calls += 1
        if self._exc is not None:
            raise self._exc
        return self._result

    def reset_call_metrics(self):
        self.last_cost_usd = 0.0
        self.last_tokens = 0


def _result(model, structured, provider="", content="{}"):
    return AgentResult(content=content, structured=structured, cost_usd=0.01,
                       tokens_used=100, model=model, provider=provider)


def _wrap(primary, fallback, schema=TINY_SCHEMA):
    return FlashStageWithFallback(
        primary, fallback, schema, name="researcher_assemble",
        fallback_marker_key="researcher_assemble_fallback_used",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_structured,label",
    [
        (None, "unparseable JSON — the parser chain returned nothing"),
        ({"answer": "seven"}, "parses, but violates the schema"),
        ({}, "empty object — a reasoning runaway that emitted no content"),
    ],
)
async def test_channel_c_invalid_json_falls_back_to_channel_a_loudly(
    bad_structured, label, caplog
):
    """The acceptance test: channel C returns something unusable, channel A
    serves instead, and the substitution is loud in both the log and the
    persisted markers."""
    primary = _FakeAgent(
        "deepseek-v4-flash", "deepseek_direct",
        result=_result("deepseek-v4-flash", bad_structured,
                       provider="deepseek_direct", content="not json at all"),
    )
    fallback = _FakeAgent(
        "deepseek/deepseek-v4-flash-0731", "openrouter",
        result=_result("deepseek/deepseek-v4-flash-0731", {"answer": 7},
                       provider="DeepSeek"),
    )
    wrapper = _wrap(primary, fallback)

    with caplog.at_level(logging.WARNING, logger="src.flash_stage_fallback"):
        res = await wrapper.run("msg", context={})

    assert res is fallback._result, label
    assert fallback.run_calls == 1
    assert wrapper.last_fallback_used is True
    assert wrapper.last_model_used == "deepseek/deepseek-v4-flash-0731"
    assert wrapper.last_provider_used == "DeepSeek"
    # cost/tokens are summed across BOTH attempts, not just the winner
    assert wrapper.last_cost_usd == pytest.approx(0.02)
    assert wrapper.last_tokens == 200
    # loud: names both channels and says it is not a silent substitution
    assert "FALLBACK" in caplog.text
    assert "deepseek_direct" in caplog.text
    assert "openrouter" in caplog.text
    assert "not a silent substitution" in caplog.text


@pytest.mark.asyncio
async def test_valid_channel_c_output_never_touches_the_fallback(caplog):
    primary = _FakeAgent(
        "deepseek-v4-flash", "deepseek_direct",
        result=_result("deepseek-v4-flash", {"answer": 7},
                       provider="deepseek_direct"),
    )
    fallback = _FakeAgent("deepseek/deepseek-v4-flash-0731", "openrouter")
    wrapper = _wrap(primary, fallback)

    with caplog.at_level(logging.WARNING, logger="src.flash_stage_fallback"):
        res = await wrapper.run("msg", context={})

    assert res is primary._result
    assert fallback.run_calls == 0
    assert wrapper.last_fallback_used is False
    assert wrapper.last_provider_used == "deepseek_direct"
    assert "FALLBACK" not in caplog.text


# --- 5. the wiring itself ----------------------------------------------------

def test_production_wiring_is_channel_c_primary_channel_a_fallback(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    from scripts.run import create_agents

    agents = create_agents()
    expected = {
        "curator_topic_discovery": ("medium", 128000, 128000),
        "researcher_assemble": ("low", 128000, 128000),
        # primary and fallback agree at 16 000 = 2.38x the observed worst
        "resolve_actor_aliases": ("low", 16000, 16000),
    }
    for stage, (effort, primary_mt, fallback_mt) in expected.items():
        w = agents[stage]
        assert isinstance(w, FlashStageWithFallback), stage

        p = w.primary
        assert p.provider == "deepseek_direct", stage
        # the vendor exposes ONE flash id and 400s on every dated form
        assert p.model == "deepseek-v4-flash", stage
        assert p.reasoning == effort, stage
        assert p.max_tokens == primary_mt, stage
        assert p.structured_output_mode == "json_object", stage

        f = w.fallback
        assert f.provider == "openrouter", stage
        assert f.model == "deepseek/deepseek-v4-flash-0731", stage
        assert f.reasoning == "medium", stage      # A's calibrated equivalent
        assert f.max_tokens == fallback_mt, stage
        assert f.structured_output_mode == "json_object", stage
        assert f._provider_routing == {"order": ["deepseek"],
                                       "allow_fallbacks": False}, stage
        assert "quantizations" not in f._provider_routing, stage

        assert w.fallback_marker_key == f"{stage}_fallback_used", stage


def test_no_flash_stage_still_runs_the_retired_fp8_route(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "unit-test-key")
    from scripts.run import create_agents_hydrated

    for stage in ("curator_topic_discovery", "researcher_assemble",
                  "resolve_actor_aliases"):
        w = create_agents_hydrated()[stage]
        for agent in (w.primary, w.fallback):
            assert "fp8" not in str(agent._provider_routing), stage
            assert agent.model != "deepseek/deepseek-v4-flash", stage
            assert agent.model != "google/gemini-3-flash-preview", stage
