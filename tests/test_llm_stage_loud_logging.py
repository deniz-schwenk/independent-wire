"""Loud model/provider logging for every LLM stage (TASK-LLM-STAGE-LOUD-LOGGING).

Before this change only fallback-wrapped stages recorded which model/provider
served a call; plain (non-wrapped) Agents logged cost/tokens only. The fix is a
single seam — `src/runner/runner.py::_collect_agent_metrics` emits `model_used`
+ `provider_used` for any agent that tracks the served model (the base
:class:`~src.agent.Agent` now does, on every ``run()``), so all six previously
opaque stages (CuratorTopicDiscovery, Consolidator, HydrationPhase1,
ResearcherHydratedPlan, ResearcherAssemble, ResolveActorAliases) go through the
same path with no per-stage wrapping.

These tests pin the seam behaviour hermetically (no API key, no network); the
end-to-end ``run()`` → seam → log flow with real served values is covered by the
ConsolidatorStage smoke in the task report.
"""
from __future__ import annotations

from src.agent import Agent
from src.runner.runner import _collect_agent_metrics


class _Stage:
    def __init__(self, agent):
        self.agent = agent


class _PlainAgentLike:
    """Minimal surface of a plain Agent as the runner reads it after a stage."""

    def __init__(self, model="deepseek/deepseek-v4-pro", served_model=None,
                 provider="Baidu", cost=0.03, tokens=1200):
        self.model = model
        self.last_model_used = model if served_model is None else served_model
        self.last_provider_used = provider
        self.last_cost_usd = cost
        self.last_tokens = tokens


def test_seam_emits_model_and_provider_for_plain_agent():
    m = _collect_agent_metrics(_Stage(_PlainAgentLike(
        served_model="deepseek/deepseek-v4-pro-20260101", provider="Baidu")))
    assert m["model_used"] == "deepseek/deepseek-v4-pro-20260101"
    assert m["provider_used"] == "Baidu"
    # No fallback marker for a plain agent — it can't substitute a model.
    assert "hydration_phase2_fallback_used" not in m
    assert "qa_fallback_used" not in m
    assert m["cost_usd"] == 0.03 and m["tokens"] == 1200


def test_seam_logs_unknown_provider_when_absent():
    # A response that omits provider metadata -> literal "unknown", never dropped.
    m = _collect_agent_metrics(_Stage(_PlainAgentLike(provider="")))
    assert m["provider_used"] == "unknown"
    assert m["model_used"]  # still present


def test_seam_falls_back_to_requested_model_when_served_absent():
    # If the served id was never captured, log the requested model, not "".
    a = _PlainAgentLike(model="deepseek/deepseek-v4-flash", served_model="")
    m = _collect_agent_metrics(_Stage(a))
    assert m["model_used"] == "deepseek/deepseek-v4-flash"
    assert m["provider_used"] == "Baidu"


def test_seam_skips_agent_without_model_tracking():
    """The BiasComposite (and any agent that reports model via extra_log_fields)
    exposes no last_model_used and must be left untouched by the generic seam."""
    class _CompositeLike:
        last_cost_usd = 0.06
        last_tokens = 1500
        extra_log_fields = {"extractor_model": "deepseek/deepseek-v4-pro"}

    m = _collect_agent_metrics(_Stage(_CompositeLike()))
    assert "model_used" not in m
    assert "provider_used" not in m
    # extra_log_fields still merged (composite path unchanged).
    assert m["extractor_model"] == "deepseek/deepseek-v4-pro"
    assert m == {"cost_usd": 0.06, "tokens": 1500,
                 "extractor_model": "deepseek/deepseek-v4-pro"}


def test_seam_omits_everything_for_deterministic_stage():
    """A stage with no `agent` attribute (deterministic) stays a bare entry."""
    class _DetStage:
        pass

    assert _collect_agent_metrics(_DetStage()) == {}


def test_base_agent_initializes_and_resets_served_model(tmp_path):
    sys_p = tmp_path / "SYSTEM.md"
    ins_p = tmp_path / "INSTRUCTIONS.md"
    sys_p.write_text("sys", encoding="utf-8")
    ins_p.write_text("ins", encoding="utf-8")
    a = Agent(
        name="plain", model="deepseek/deepseek-v4-pro",
        system_prompt_path=str(sys_p), instructions_path=str(ins_p),
        api_key="test-key-not-used",
    )
    # Fresh agent: served-model accumulators start empty.
    assert a.last_model_used == ""
    assert a.last_provider_used == ""
    # After a call they would be populated; the runner reads them, then resets.
    a.last_model_used = "deepseek/deepseek-v4-pro-20260101"
    a.last_provider_used = "Baidu"
    m = _collect_agent_metrics(_Stage(a))
    assert m["model_used"] == "deepseek/deepseek-v4-pro-20260101"
    assert m["provider_used"] == "Baidu"
    a.reset_call_metrics()
    assert a.last_model_used == "" and a.last_provider_used == ""
