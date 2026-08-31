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
from src.schemas import (
    BIAS_CANDIDATES_SCHEMA,
    CONSOLIDATOR_SCHEMA,
    HYDRATION_PHASE1_SCHEMA,
)


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


# --------------------------------------------------------------------------- #
# hydration_aggregator_phase1 — TASK-P1-SWAP-FLASH0731 (T3b §7.2 + P1-CONFIRM)
# --------------------------------------------------------------------------- #
def _phase1_actor(name="A"):
    return {
        "name": name, "role": "spokesperson", "type": "government",
        "position": "said the thing", "evidence_type": "stated",
        "verbatim_quote": "the thing",
    }


VALID_PHASE1 = {
    "article_analyses": [
        {"article_index": 0, "summary": "s", "actors_quoted": []}
    ]
}


def test_phase1_wired_to_flash_0731_at_medium(monkeypatch):
    """P1-CONFIRM's operating point: flash-0731 @ MEDIUM (not the
    consolidator's minimal) with the 160 000 cap medium's reasoning needs.

    Hydrated-only stage, so only that variant registers it.
    """
    agents = load_agents("hydrated", monkeypatch)
    agent = agents["hydration_aggregator_phase1"]
    assert isinstance(agent, FlashStageWithFallback)
    assert agent.name == "hydration_aggregator_phase1"
    assert agent.fallback_marker_key == "hydration_phase1_fallback_used"
    assert_channel_c_primary(
        agent.primary, reasoning="medium", temperature=0.3, max_tokens=160000,
        label="phase1 primary",
    )
    assert_channel_a_fallback(
        agent.fallback, temperature=0.3, max_tokens=160000,
        label="phase1 fallback",
    )
    assert "deepseek-v4-pro" not in (agent.primary.model, agent.fallback.model)
    # the pre-2026-08-24 cross-model net must not reappear
    assert "gemini" not in f"{agent.primary.model}{agent.fallback.model}".lower()


def test_phase1_cap_is_not_the_minimal_cap(monkeypatch):
    """The one cap in the bundle that is NOT 32000, guarded explicitly: medium
    spends its reasoning inside the total budget (flash/minimal 20 727
    completion vs flash/medium 57 460 on the same chunk — caps.json's own
    note), so carrying the minimal cap here would truncate real chunks."""
    agents = load_agents("hydrated", monkeypatch)
    p1 = agents["hydration_aggregator_phase1"]
    cons = agents["consolidator"]
    assert p1.primary.max_tokens == 160000
    assert cons.primary.max_tokens == 32000
    assert p1.primary.reasoning == "medium"
    assert cons.primary.reasoning == "minimal"


def test_phase1_is_not_registered_in_the_production_variant(monkeypatch):
    """Guard the variant boundary: phase1 is hydrated-only, and the swap must
    not have leaked it into the production agent dict."""
    assert "hydration_aggregator_phase1" not in load_agents("production", monkeypatch)


@pytest.mark.asyncio
async def test_phase1_forced_channel_c_failure_falls_back_loudly(caplog):
    """Forced failure: channel C down -> channel A serves the chunk, loudly,
    and hydration_phase1_fallback_used reaches the stage row."""
    wrapper, primary, fallback = forced_c_failure_wrapper(
        schema=HYDRATION_PHASE1_SCHEMA,
        structured=VALID_PHASE1,
        name="hydration_aggregator_phase1",
        marker="hydration_phase1_fallback_used",
    )
    with caplog.at_level(logging.WARNING):
        result = await wrapper.run("msg", context={})

    assert primary.run_calls == 1 and fallback.run_calls == 1
    assert result.structured == VALID_PHASE1
    row = _collect_agent_metrics(_StageWith(wrapper))
    assert row["hydration_phase1_fallback_used"] is True
    assert row["model_used"] == "deepseek/deepseek-v4-flash-0731"
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "hydration_aggregator_phase1 FALLBACK" in text


@pytest.mark.asyncio
async def test_phase1_chunk_survives_a_channel_c_outage():
    """Stage level: the chunk orchestration is unchanged by the swap. A
    channel-C outage costs the chunk ONE fallback call, and the empty-retry
    wrapper above it sees a non-empty answer, so it does not re-roll."""
    from src.agent_stages import _run_phase1_chunk_with_empty_retry

    wrapper, primary, fallback = forced_c_failure_wrapper(
        schema=HYDRATION_PHASE1_SCHEMA,
        structured={
            "article_analyses": [
                {"article_index": 0, "summary": "s",
                 "actors_quoted": [_phase1_actor()]}
            ]
        },
        name="hydration_aggregator_phase1",
        marker="hydration_phase1_fallback_used",
    )
    analyses, attempts = await _run_phase1_chunk_with_empty_retry(
        {"title": "t", "selection_reason": "r"},
        [{"url": "https://example.org/a", "text": "body"}],
        chunk_idx=0,
        agent=wrapper,
    )
    assert attempts == 1                      # the empty-retry loop did not fire
    assert primary.run_calls == 1 and fallback.run_calls == 1
    assert len(analyses) == 1
    assert wrapper.last_fallback_used is True


# --------------------------------------------------------------------------- #
# bias_candidate_extractor — TASK-BIAS-EXTRACTOR-COUPLED
# --------------------------------------------------------------------------- #
VALID_CANDIDATES = {
    "candidates": [{"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"}]
}


@pytest.mark.parametrize("variant", ["production", "hydrated"])
def test_bias_extractor_wired_to_flash_0731_at_minimal(variant, monkeypatch):
    """The extractor is the composite's sub-agent, so the wrapper lives INSIDE
    BiasComposite rather than in the agents dict. T3b's triage level, and the
    temperature 0.8 that makes three passes a recall mechanism instead of three
    identical calls."""
    from src.bias_composite import BiasComposite

    composite = load_agents(variant, monkeypatch)["bias_language"]
    assert isinstance(composite, BiasComposite)
    extractor = composite.extractor
    assert isinstance(extractor, FlashStageWithFallback)
    assert extractor.fallback_marker_key == "extractor_fallback_used"
    assert_channel_c_primary(
        extractor.primary, reasoning="minimal", temperature=0.8, max_tokens=32000,
        label="extractor primary",
    )
    assert_channel_a_fallback(
        extractor.fallback, temperature=0.8, max_tokens=32000,
        label="extractor fallback",
    )
    assert "deepseek-v4-pro" not in (extractor.primary.model, extractor.fallback.model)


def test_own_voice_prompt_fix_is_live(monkeypatch):
    """Part 1 of the coupled landing: the prompt files the eval measured are
    the ones production loads. Checked on CONTENT, not on a hash — a hash test
    fails on any future edit; these three sentences are the fix itself."""
    from pathlib import Path

    system = Path("agents/bias_candidate_extractor/SYSTEM.md").read_text(encoding="utf-8")
    instructions = Path(
        "agents/bias_candidate_extractor/INSTRUCTIONS.md").read_text(encoding="utf-8")

    assert "in the article's own editorial voice" in system
    assert "## Whose voice" in instructions
    # the rule that drives quote-harvest to zero
    assert "never the speech itself" in instructions
    # ... and the worked example that shows what IS extractable at a quote
    assert '"excerpt": "admitted"' in instructions


def test_prompt_fix_and_model_swap_landed_together(monkeypatch):
    """The coupling, asserted. The own-voice prompt on the April v4-pro build
    is the WORST cell the eval measured (2.60 against flash's 4.30) — landing
    the prompt without the model would have made the stage worse. This guard
    fails if a future change reverts one half and leaves the other."""
    from pathlib import Path

    instructions = Path(
        "agents/bias_candidate_extractor/INSTRUCTIONS.md").read_text(encoding="utf-8")
    extractor = load_agents("hydrated", monkeypatch)["bias_language"].extractor
    own_voice_prompt = "## Whose voice" in instructions
    flash_model = getattr(extractor, "primary", extractor).model == "deepseek-v4-flash"
    assert own_voice_prompt == flash_model, (
        "the own-voice prompt fix and the flash-0731 swap are coupled by eval "
        "evidence; they land and revert together (TASK-BIAS-EXTRACTOR-COUPLED)"
    )


@pytest.mark.asyncio
async def test_bias_extractor_forced_channel_c_failure_falls_back_loudly(caplog):
    """Forced failure at the wrapper: channel C down -> channel A serves."""
    wrapper, primary, fallback = forced_c_failure_wrapper(
        schema=BIAS_CANDIDATES_SCHEMA,
        structured=VALID_CANDIDATES,
        name="bias_candidate_extractor",
        marker="extractor_fallback_used",
    )
    with caplog.at_level(logging.WARNING):
        result = await wrapper.run("msg", context={})
    assert primary.run_calls == 1 and fallback.run_calls == 1
    assert result.structured == VALID_CANDIDATES
    assert wrapper.last_fallback_used is True
    assert "bias_candidate_extractor FALLBACK" in " ".join(
        r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_composite_reports_the_fallback_even_though_passes_race(caplog):
    """The composite runs its passes CONCURRENTLY against one wrapper, so the
    wrapper's own last_fallback_used marker is last-writer-wins and cannot
    answer "did any pass fall back?". The composite derives it from each
    pass's served provider instead — this test is the reason that code exists.
    """
    from src.bias_composite import BiasComposite

    body = "The council's decision dealt a devastating blow to bakeries."
    calls = {"n": 0}

    class _RacingExtractor:
        """Pass 2 is served by channel A; passes 1 and 3 by channel C. The
        pass that falls back is NOT the last to finish."""

        model = "deepseek-v4-flash"
        primary = type("P", (), {"provider": "deepseek_direct"})()

        async def run(self, *a, **kw):
            calls["n"] += 1
            n = calls["n"]
            provider = "DeepSeek" if n == 2 else "deepseek_direct"
            model = ("deepseek/deepseek-v4-flash-0731" if n == 2
                     else "deepseek-v4-flash")
            return AgentResult(
                content="{}",
                structured={"candidates": [
                    {"excerpt": "a devastating blow", "issue_hint": "x"}]},
                cost_usd=0.0, tokens_used=1, model=model, provider=provider,
            )

        def reset_call_metrics(self):
            pass

    class _Judge:
        model = "anthropic/claude-opus-4.6"
        output_schema: dict = {}

        async def run(self, *a, **kw):
            return AgentResult(
                content="{}",
                structured={"judgments": [
                    {"candidate_id": 1, "verdict": "cleared", "issue": "",
                     "explanation": ""}], "reader_note": ""},
                cost_usd=0.0, tokens_used=1, model=self.model, provider="Anthropic",
            )

        def reset_call_metrics(self):
            pass

    composite = BiasComposite(extractor=_RacingExtractor(), judge=_Judge())
    with caplog.at_level(logging.WARNING):
        await composite.run("msg", context={"article_body": body})

    fields = composite.extra_log_fields
    assert fields["extractor_fallback_used"] is True
    assert fields["extractor_fallback_passes"] == [2]
    assert "bias extractor FALLBACK" in " ".join(
        r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_composite_reports_no_fallback_on_the_healthy_path():
    """Negative control: every pass on channel C means the marker is False and
    the served model is the one the stage log should show."""
    from src.bias_composite import BiasComposite

    class _HealthyExtractor:
        model = "deepseek-v4-flash"
        primary = type("P", (), {"provider": "deepseek_direct"})()

        async def run(self, *a, **kw):
            return AgentResult(
                content="{}", structured={"candidates": []},
                cost_usd=0.0, tokens_used=1,
                model="deepseek-v4-flash", provider="deepseek_direct",
            )

        def reset_call_metrics(self):
            pass

    class _Judge:
        model = "anthropic/claude-opus-4.6"
        output_schema: dict = {}

        async def run(self, *a, **kw):  # pragma: no cover - never reached
            raise AssertionError("judge must be skipped on an empty candidate list")

        def reset_call_metrics(self):
            pass

    composite = BiasComposite(extractor=_HealthyExtractor(), judge=_Judge())
    await composite.run("msg", context={"article_body": "clean text"})
    fields = composite.extra_log_fields
    assert fields["extractor_fallback_used"] is False
    assert fields["extractor_fallback_passes"] == []
    assert fields["extractor_model_served"] == "deepseek-v4-flash"
    assert fields["extractor_provider"] == "deepseek_direct"


def test_the_v4_pro_fp8_pin_is_gone_from_run_py():
    """Part 2's last clause: with the extractor swapped, nothing references
    DEEPSEEK_V4_PRO_FP8_ROUTING, so the constant is deleted rather than left to
    rot. (tests/test_agent_provider_routing.py owns the full retirement guard;
    this asserts the bundle's own precondition for deleting it.)"""
    import scripts.run as run_mod

    assert not hasattr(run_mod, "DEEPSEEK_V4_PRO_FP8_ROUTING")


# --------------------------------------------------------------------------- #
# Adaptive 4th extraction pass — TASK-BIAS-EXTRACTOR-COUPLED part 3
# --------------------------------------------------------------------------- #
# 25 distinct, non-overlapping spans so a scripted pass can emit any count up
# to the extractor cap without colliding (build_union merges on POSITION, so
# spans must not overlap or the union collapses them and the counts lie).
_SPANS = [f"loaded phrase {i:02d}" for i in range(25)]
ARTICLE_BODY = ". ".join(f"The report called it {span}" for span in _SPANS) + "."


def _cands(n):
    return [{"excerpt": _SPANS[i], "issue_hint": "loaded_term"} for i in range(n)]


class ScriptedExtractor:
    """Returns a scripted candidate count per call, in order. The last entry
    repeats, so an unscripted extra pass is still answerable."""

    model = "deepseek-v4-flash"
    primary = type("P", (), {"provider": "deepseek_direct"})()

    def __init__(self, counts):
        self.counts = list(counts)
        self.calls = 0

    async def run(self, *a, **kw):
        n = self.counts[min(self.calls, len(self.counts) - 1)]
        self.calls += 1
        return AgentResult(
            content="{}", structured={"candidates": _cands(n)},
            cost_usd=0.001, tokens_used=10,
            model="deepseek-v4-flash", provider="deepseek_direct",
        )

    def reset_call_metrics(self):
        pass


class SilentJudge:
    model = "anthropic/claude-opus-4.6"
    output_schema: dict = {}

    async def run(self, *a, **kw):
        return AgentResult(
            content="{}",
            structured={"judgments": [], "reader_note": ""},
            cost_usd=0.0, tokens_used=1, model=self.model, provider="Anthropic",
        )

    def reset_call_metrics(self):
        pass


async def _run_composite(counts):
    from src.bias_composite import BiasComposite

    extractor = ScriptedExtractor(counts)
    composite = BiasComposite(extractor=extractor, judge=SilentJudge())
    await composite.run("msg", context={"article_body": ARTICLE_BODY})
    return extractor, composite


# --- the detector, as a pure function ---------------------------------------
@pytest.mark.parametrize(
    "counts,expected",
    [
        ([2, 10, 11], [1]),        # one clear thin pass
        ([4, 10, 25], [1]),        # the live 2026-08-30 topic-0 shape
        ([1, 1, 10], [1, 2]),      # two outliers at once
        ([1, 1, 1], []),           # uniformly thin: relative rule, no trigger
        ([0, 0, 0], []),           # uniformly empty: zero-median guard
        ([10, 11, 12], []),        # healthy
        ([6, 10, 11], []),         # thin-ish but not below half the median
        ([0, 10, 11], [1]),        # a pass that died counts as the thinnest
    ],
)
def test_thin_outlier_detector(counts, expected):
    from src.bias_composite import thin_outlier_passes

    assert thin_outlier_passes(counts) == expected


# --- (a) an outlier triggers one extra pass and the union covers all 4 -------
@pytest.mark.asyncio
async def test_outlier_triggers_exactly_one_extra_pass_and_union_covers_four():
    extractor, composite = await _run_composite([2, 10, 11, 9])
    assert extractor.calls == 4
    fields = composite.extra_log_fields
    assert fields["extractor_extra_pass"] is True
    assert fields["extractor_outlier_passes"] == [1]
    assert fields["extraction_passes"] == 4
    assert len(fields["extract_raw"]) == 4          # the union saw all four
    assert fields["extract_raw"] == [2, 10, 11, 9]


# --- (b) three uniformly low passes -> no extra pass -------------------------
@pytest.mark.asyncio
async def test_uniformly_thin_article_does_not_buy_a_fourth_call():
    """The rule is relative. A short clean article that legitimately yields one
    candidate per pass must not pay for an extra call."""
    extractor, composite = await _run_composite([1, 1, 1])
    assert extractor.calls == 3
    fields = composite.extra_log_fields
    assert fields["extractor_extra_pass"] is False
    assert fields["extractor_outlier_passes"] == []
    assert fields["extraction_passes"] == 3


# --- (c) two outliers -> still exactly one extra pass ------------------------
@pytest.mark.asyncio
async def test_two_outliers_still_buy_exactly_one_extra_pass():
    extractor, composite = await _run_composite([1, 1, 10, 8])
    assert extractor.calls == 4                     # capped at one extra, ever
    fields = composite.extra_log_fields
    assert fields["extractor_outlier_passes"] == [1, 2]
    assert fields["extractor_extra_pass"] is True
    assert fields["extraction_passes"] == 4


# --- (d) confidence strings reflect the real denominator ---------------------
@pytest.mark.asyncio
async def test_confidence_denominator_follows_the_real_pass_count():
    """K/4 after an extra pass, K/3 without one. The denominator is
    ``len(runs)`` in build_union, so this is a consequence rather than a second
    implementation — asserted because it is the visible contract."""
    from src.bias_composite import build_union, thin_outlier_passes

    # 2 candidates in the thin pass, 3 in the others, 3 in the extra: the two
    # shared spans are flagged by all four passes, the third by three.
    runs4 = [_cands(2), _cands(3), _cands(3), _cands(3)]
    assert thin_outlier_passes([len(r) for r in runs4[:3]]) == []
    cands4, _ = build_union(runs4, ARTICLE_BODY)
    conf4 = {c["excerpt"]: c["extraction_confidence"] for c in cands4}
    assert conf4[_SPANS[0]] == "4/4"
    assert conf4[_SPANS[2]] == "3/4"

    cands3, _ = build_union(runs4[:3], ARTICLE_BODY)
    conf3 = {c["excerpt"]: c["extraction_confidence"] for c in cands3}
    assert conf3[_SPANS[0]] == "3/3"
    assert conf3[_SPANS[2]] == "2/3"


@pytest.mark.asyncio
async def test_extra_pass_never_recurses():
    """The cap is absolute: even when the extra pass is itself thin, no fifth
    call happens."""
    extractor, composite = await _run_composite([2, 10, 11, 1])
    assert extractor.calls == 4
    assert composite.extra_log_fields["extract_raw"] == [2, 10, 11, 1]


@pytest.mark.asyncio
async def test_failed_extra_pass_does_not_widen_the_denominator(caplog):
    """If the extra call itself fails, the union runs over the original three.
    Appending an empty fourth run would penalise every candidate's confidence
    for a transport failure."""
    from src.agent import AgentError
    from src.bias_composite import BiasComposite

    class DyingOnFourth(ScriptedExtractor):
        async def run(self, *a, **kw):
            if self.calls == 3:
                self.calls += 1
                raise AgentError("extra pass down")
            return await super().run(*a, **kw)

    extractor = DyingOnFourth([2, 10, 11])
    composite = BiasComposite(extractor=extractor, judge=SilentJudge())
    with caplog.at_level(logging.ERROR):
        await composite.run("msg", context={"article_body": ARTICLE_BODY})

    assert extractor.calls == 4
    fields = composite.extra_log_fields
    assert fields["extractor_extra_pass"] is True   # it was attempted...
    assert fields["extraction_passes"] == 3         # ...but contributed nothing
    assert "extra pass FAILED" in " ".join(r.getMessage() for r in caplog.records)
