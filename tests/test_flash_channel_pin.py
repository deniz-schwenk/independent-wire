"""Six flash primaries moved to the OpenRouter first-party endpoint
(TASK-FLASH-CHANNEL-PIN, 2026-09-18).

The swap is a NAMED SUBSTITUTION, not a model choice. Channel C exposes exactly
one flash id, an undated alias, and the vendor rolled it between the 2026-09-09
and 2026-09-10 production runs (server echo ``deepseek-v4-flash`` ->
``deepseek-flash``). From then until this change every flash call ran an
unverified build and booked $0.00 — the served alias is absent from
``DEEPSEEK_DIRECT_PRICES``, so the price tripwire fired ~27-30x per run. Naming
``deepseek/deepseek-v4.1-flash`` on the vendor's OpenRouter endpoint changes
what the config SAYS, not what serves; what it buys back is a pinned identity
``model_used`` can be checked against, and a measured cost per call.

The ladder half matters as much: with the primary on channel A, the old rung 2
(also channel A, same id, same pin) would have left both rungs on one route.
Channel C takes the rung instead — same vendor, different transport.

What these tests do NOT claim: that v4.1-flash is the right model for these six
stages on quality. No eval backs that. The frozen-input probe
(scratch/audit/flash-channel-pin/probe/probe.jsonl) establishes schema-valid,
same-shaped output at each stage's own level — parity of plumbing, not of
judgement.
"""

from __future__ import annotations

import pytest

from src.agent import DEEPSEEK_DIRECT_PRICES, deepseek_direct_cost_usd
from src.flash_stage_fallback import FlashStageWithFallback

# stage key -> the level that stage has always run, unchanged by the swap
SIX = {
    "curator_topic_discovery": "medium",
    "researcher_assemble": "low",
    "resolve_actor_aliases": "low",
    "consolidator": "minimal",
    "hydration_aggregator_phase1": "medium",
    "bias_candidate_extractor": "minimal",
}
NAMED_ID = "deepseek/deepseek-v4.1-flash"
ALIAS_ID = "deepseek-v4-flash"


def _wrappers(monkeypatch) -> dict:
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents_hydrated

    ags = create_agents_hydrated()
    out = {k: ags[k] for k in SIX if k != "bias_candidate_extractor"}
    out["bias_candidate_extractor"] = ags["bias_language"].extractor
    return out


def test_all_six_primaries_are_the_named_first_party_id(monkeypatch):
    """The point of the change: an id that can be checked, on a route pinned to
    the vendor's own endpoint."""
    wrappers = _wrappers(monkeypatch)
    assert set(wrappers) == set(SIX)
    for key, w in wrappers.items():
        assert isinstance(w, FlashStageWithFallback), key
        p = w.primary
        assert p.model == NAMED_ID, key
        assert p.provider == "openrouter", key
        assert p._provider_routing == {"order": ["deepseek"],
                                       "allow_fallbacks": False}, key
        # both of these individually 404 the DeepSeek endpoint out of its own
        # route (T2b 1.1) — and now they would do it on the PRIMARY path
        assert "quantizations" not in p._provider_routing, key
        assert "require_parameters" not in p._provider_routing, key
        assert p.structured_output_mode == "json_object", key


def test_rung_two_is_channel_c_and_a_different_route(monkeypatch):
    """A ladder whose rungs share a route protects against nothing."""
    for key, w in _wrappers(monkeypatch).items():
        assert w.fallback.model == ALIAS_ID, key
        assert w.fallback.provider == "deepseek_direct", key
        assert not getattr(w.fallback, "_provider_routing", {}), key
        assert w.primary.provider != w.fallback.provider, key


def test_the_swap_re_routes_without_re_tuning(monkeypatch):
    """Level, temperature and cap are identical on both rungs and unchanged
    from before the swap.

    The level is worth a word, because the config used to say the opposite. The
    T2d calibration found channel A and channel C levels were NOT
    interchangeable (``A-medium`` == ``C-low``), and the old rung 2 ran a fixed
    ``medium`` for that reason. That was measured on the 0731 build and does not
    reproduce on v4.1: paired on identical frozen inputs the literal level
    tracks the old channel-C spend at every stage measured, while the
    "equivalent" level moves it — curator 103.5k -> 91.2k tokens at ``high``,
    phase1 58.3k -> 96.6k. Hence the same string on both rungs
    (scratch/audit/flash-channel-pin/probe/probe.jsonl)."""
    for key, w in _wrappers(monkeypatch).items():
        assert w.primary.reasoning == SIX[key], key
        assert w.fallback.reasoning == SIX[key], key
        assert w.primary.temperature == w.fallback.temperature, key
        assert w.primary.max_tokens == w.fallback.max_tokens, key


def test_a_zero_dollar_flash_call_now_means_a_fallback_fired(monkeypatch):
    """The cost half of the change, stated as the invariant it creates.

    Channel C's served alias is unpriced, by construction: the vendor's direct
    API reports no cost and the alias is not in the price table. Before the
    swap that made EVERY flash call $0.00 and tripped the tripwire ~27-30x per
    run. After it, the primary path reports a real cost, so a $0.00 flash row
    is no longer background noise — it is the signature of a fired rung 2, and
    ``<stage>_fallback_used`` in the same row says so."""
    usage = type("U", (), {"prompt_tokens": 1000, "completion_tokens": 100,
                           "prompt_cache_hit_tokens": None,
                           "prompt_cache_miss_tokens": None})()
    assert deepseek_direct_cost_usd("deepseek-flash", usage) is None
    assert "deepseek-flash" not in DEEPSEEK_DIRECT_PRICES
    # and the tripwire's own precondition: the primary no longer routes there
    for key, w in _wrappers(monkeypatch).items():
        assert w.primary.provider != "deepseek_direct", key


@pytest.mark.parametrize("key,expected", [
    ("editor", "z-ai/glm-5.2"),
    ("writer", "z-ai/glm-5.2"),
    ("qa_analyze", "z-ai/glm-5.3-flash"),
    ("hydration_aggregator_phase2", "z-ai/glm-5.3-flash"),
])
def test_no_non_flash_stage_moved(monkeypatch, key, expected):
    """Blast radius: exactly the six. The glm stages keep their own models."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents_hydrated

    a = create_agents_hydrated()[key]
    assert getattr(a, "primary", a).model == expected


def test_the_planner_still_owns_its_own_ladder(monkeypatch):
    """The planner shares DEEPSEEK_NATIVE_ROUTING with the flash primaries but
    is a v4-pro stage on its own task — it must not have been dragged along."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents_hydrated

    planner = create_agents_hydrated()["researcher_hydrated_plan"]
    models = {getattr(planner, a).model for a in ("primary", "fallback")
              if getattr(planner, a, None) is not None}
    assert models and all("flash" not in m for m in models), models
