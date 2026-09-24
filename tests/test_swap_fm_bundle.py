"""hydration_phase2 + qa_analyze -> glm-5.3-flash @ max (TASK-SWAP-FM-BUNDLE).

One bundled change, two stages, one operating point (T3-bundle precedent). The
two stages arrive here on DIFFERENT evidence and this file records which is
which, because the distinction is the thing most likely to be lost:

  hydration_aggregator_phase2 -- CONFIRMED. Addendum D +1.056 [+0.607, +1.504];
    pre-registered fresh confirmation D +0.889 [+0.633, +1.145], W/T/L 8/1/0,
    17 of 18 judge firsts. Across 18 instances the champion never won a case.

  qa_analyze -- COST-LED, NOT confirmed. Two pre-registered confirmations FAILED
    (n=8 CI [-0.093, +1.405]; n=9 CI [-0.146, +1.035]) and the point estimate
    drifted DOWN across three batches (+0.667 -> +0.656 -> +0.444). The pooled
    secondary reading is n=26, D +0.587 [+0.300, +0.874]. The honest claim is
    "quality at least level, probably modestly better, -88% cost", never
    "confirmed better".

Evidence: scratch/eval/glm53-prose/{flashm,confirm,confirm-qa2}/reports/.
"""

from __future__ import annotations

import pytest

from src.qa_fallback import QaAnalyzeWithFallback
from src.hydration_phase2_fallback import HydrationPhase2WithFallback
from src.schemas import HYDRATION_PHASE2_SCHEMA, QA_ANALYZE_SCHEMA

TARGET = {
    "model": "z-ai/glm-5.3-flash",
    "temperature": 1.0,
    "max_tokens": 120000,
    "reasoning": "max",
    "provider": "openrouter",
    "structured_output_mode": "json_object",
}
ZAI_PIN = {"order": ["z-ai"], "allow_fallbacks": False}


@pytest.fixture
def agents(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents_hydrated

    return create_agents_hydrated()


@pytest.mark.parametrize("stage,wrapper,schema", [
    ("qa_analyze", QaAnalyzeWithFallback, QA_ANALYZE_SCHEMA),
    ("hydration_aggregator_phase2", HydrationPhase2WithFallback,
     HYDRATION_PHASE2_SCHEMA),
])
def test_both_stages_sit_at_the_evaluated_operating_point(
        agents, stage, wrapper, schema):
    """Eval parity, asserted field by field. Every number here was the arm's
    configuration in the batches above; a drift in any one of them means
    production is running something no eval measured."""
    w = agents[stage]
    assert isinstance(w, wrapper)
    p = w.primary
    assert p.model == TARGET["model"], stage
    assert p.temperature == TARGET["temperature"], stage
    assert p.max_tokens == TARGET["max_tokens"], stage
    assert p.reasoning == TARGET["reasoning"], stage
    assert p.provider == TARGET["provider"], stage
    assert p.structured_output_mode == TARGET["structured_output_mode"], stage
    assert p.output_schema == schema, stage
    # top_p has no Agent parameter; the vendor publishes it as a PAIR with
    # temperature and every arm sent both.
    assert p._extra_body_override == {"top_p": 0.95}, stage


@pytest.mark.parametrize("stage", ["qa_analyze",
                                   "hydration_aggregator_phase2"])
def test_the_pin_is_the_vendor_endpoint_with_no_filters(agents, stage):
    """First-party route. A `quantizations` filter or `require_parameters`
    would 404 this endpoint out of its own route — the same trap the
    perspective chain documents — so both must be absent, and conformance is
    enforced locally by the wrapper instead."""
    p = agents[stage].primary
    assert p._provider_routing == ZAI_PIN, stage
    assert "quantizations" not in p._provider_routing, stage
    assert p.structured_output_mode == "json_object", stage


@pytest.mark.parametrize("stage,model,max_tokens", [
    ("qa_analyze", "anthropic/claude-sonnet-5", 64000),
    ("hydration_aggregator_phase2", "anthropic/claude-opus-4.6", 32000),
])
def test_the_fallback_rungs_are_untouched(agents, stage, model, max_tokens):
    """The swap moves the PRIMARY only. Both nets predate it and neither was
    re-evaluated, so a change here would be an unmeasured config riding along
    with a measured one."""
    f = agents[stage].fallback
    assert f.model == model, stage
    assert f.max_tokens == max_tokens, stage


def test_writer_and_editor_stay_on_glm_5_2(agents):
    """Explicitly out of scope, and the easiest thing to break by accident:
    all four prose stages ran GLM-5.2 under near-identical fp8 pins, so a
    careless swap takes the wrong pair with it."""
    for stage in ("writer", "editor"):
        p = agents[stage].primary
        assert p.model == "z-ai/glm-5.2", stage
        assert p.reasoning == "xhigh", stage
        assert p.temperature != 1.0, stage
        # still on the third-party fp8 route, not the vendor endpoint
        assert p._provider_routing["quantizations"] == ["fp8"], stage
        assert p._provider_routing["order"] == [
            "baidu/fp8", "venice/fp8"], stage


def test_no_other_stage_moved_to_glm_5_3_flash(agents):
    """The blast radius is exactly two stages. glm-5.3-flash legitimately
    appears elsewhere — the perspective chain's verify leg — so this asserts
    the SET, not the absence."""
    from src.bias_composite import BiasComposite

    def models(obj):
        """Every model id reachable from one agents[...] entry, across the
        wrapper shapes this file actually uses: plain Agent, primary/fallback
        wrappers, the perspective draft/verify chain, and the bias composite."""
        out = set()
        m = getattr(obj, "model", "")
        if isinstance(m, str) and m:
            out.add(m)
        for attr in ("primary", "fallback", "draft", "verify",
                     "extractor", "judge"):
            sub = getattr(obj, attr, None)
            if sub is not None and sub is not obj:
                out |= models(sub)
        return out

    moved = {name for name, a in agents.items()
             if "z-ai/glm-5.3-flash" in models(a)}
    # perspective's VERIFY leg has run glm-5.3-flash since TASK-PERSPECTIVE-SWAP
    # and is untouched here; asserting the set rather than an absence is what
    # makes this test notice a third stage drifting in.
    assert moved == {"qa_analyze", "hydration_aggregator_phase2",
                     "perspective"}, sorted(moved)
    assert isinstance(agents["bias_language"], BiasComposite)
    assert "z-ai/glm-5.3-flash" not in models(agents["bias_language"])


def test_the_dead_glm_5_2_pins_are_gone():
    """Both stages' fp8 constants died with their primaries. Leaving a pin
    nothing references is how a future reader concludes the stage still runs
    under it."""
    import scripts.run as run

    assert not hasattr(run, "GLM_5_2_QA_FP8_ROUTING")
    assert not hasattr(run, "GLM_5_2_HYDRATION_P2_FP8_ROUTING")
    # ...and the two that are still live are still live
    assert hasattr(run, "GLM_5_2_WRITER_FP8_ROUTING")
    assert hasattr(run, "GLM_5_2_EDITOR_FP8_ROUTING")
