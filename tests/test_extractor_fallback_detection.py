"""Per-pass fallback detection in BiasComposite, in the REAL production
topology (TASK-EXTRACTOR-FALLBACK-DETECTION-FIX, 2026-09-21).

Day 1 of the channel pin, 2026-09-20: every bias row said
``extractor_fallback_passes: [1, 2, 3]`` and ``extractor_fallback_used: true``,
on all three topics, on both 09-20 and 09-21 — while the agent log showed 9/9
primary completions on the OpenRouter first-party endpoint and not one failed
call. The composite decided "did this pass fall back?" by comparing the SERVED
provider against the primary's CONFIGURED provider. Those two are different
kinds of string: the served label names the upstream vendor OpenRouter routed
to (``DeepSeek``), the configured key names the channel we asked through
(``openrouter``). They were equal only while the primary was ``deepseek_direct``
— a channel that happens to echo its own key — so the comparison was a topology
assumption that TASK-FLASH-CHANNEL-PIN inverted.

A false fallback marker is the same severity class as a silent fallback, in the
other direction: it makes the watch ledger unreadable, and it is worse than a
missed one in one respect — nobody investigates an alarm that is always on.

These tests run the composite as production wires it — the extractor nested
inside BiasComposite, both legs real ``FlashStageWithFallback`` wrappers — and
pin BOTH directions: a healthy run reports no fallback, and a genuine rung
serve is still caught.
"""

from __future__ import annotations

import logging

import pytest

from src.agent import AgentError, AgentResult
from src.bias_composite import BiasComposite
from src.flash_stage_fallback import FlashStageWithFallback

ARTICLE = "The council's decision dealt a devastating blow to local bakeries."
CANDIDATES = {"candidates": [
    {"excerpt": "a devastating blow", "issue_hint": "loaded language"}]}
JUDGMENTS = {"judgments": [
    {"candidate_id": 1, "verdict": "confirmed", "issue": "loaded",
     "explanation": "e"}], "reader_note": "note"}

# What the two rungs actually put on the wire after TASK-FLASH-CHANNEL-PIN.
# The primary's served PROVIDER label is "DeepSeek" while its configured
# provider key is "openrouter" — the mismatch that used to read as a fallback.
PRIMARY_SERVED = ("deepseek/deepseek-v4.1-flash", "DeepSeek")
RUNG_SERVED = ("deepseek-flash", "deepseek_direct")


def _result(served, structured):
    model, provider = served
    return AgentResult(content="{}", structured=structured, cost_usd=0.001,
                       tokens_used=10, model=model, provider=provider)


class _Leg:
    """A stand-in for one rung's Agent. Raises on the nominated call numbers."""

    def __init__(self, served, structured, model_cfg, provider_cfg,
                 fail_on=()):
        self.model = model_cfg
        self.provider = provider_cfg
        self._served = served
        self._structured = structured
        self.fail_on = set(fail_on)
        self.calls = 0

    async def run(self, *a, **kw):
        self.calls += 1
        if self.calls in self.fail_on:
            raise AgentError(f"simulated final failure on call {self.calls}")
        return _result(self._served, self._structured)

    def reset_call_metrics(self):
        pass


def _composite(*, extractor_fail_on=(), judge_fail_on=()):
    """The production shape: two FlashStageWithFallback wrappers, the extractor
    nested inside the composite where a top-level agents[...] scan cannot see
    it (the trap this task hit for the third time)."""
    ext_schema = {"type": "object",
                  "properties": {"candidates": {"type": "array"}},
                  "required": ["candidates"], "additionalProperties": False}
    judge_schema = {"type": "object",
                    "properties": {"judgments": {"type": "array"},
                                   "reader_note": {"type": "string"}},
                    "required": ["judgments"], "additionalProperties": False}
    extractor = FlashStageWithFallback(
        _Leg(PRIMARY_SERVED, CANDIDATES, "deepseek/deepseek-v4.1-flash",
             "openrouter", fail_on=extractor_fail_on),
        _Leg(RUNG_SERVED, CANDIDATES, "deepseek-v4-flash", "deepseek_direct"),
        ext_schema, name="bias_candidate_extractor",
        fallback_marker_key="extractor_fallback_used")
    judge = FlashStageWithFallback(
        _Leg(("z-ai/glm-5.3", "Z.AI"), JUDGMENTS, "z-ai/glm-5.3", "openrouter",
             fail_on=judge_fail_on),
        _Leg(("anthropic/claude-opus-4.6", "Anthropic"), JUDGMENTS,
             "anthropic/claude-opus-4.6", "openrouter"),
        judge_schema, name="bias_judge",
        fallback_marker_key="bias_judge_fallback_used")
    return BiasComposite(extractor=extractor, judge=judge)


# --- direction 1: the healthy run, which was the regression -----------------

@pytest.mark.asyncio
async def test_a_healthy_run_reports_no_extractor_fallback(caplog):
    """The 2026-09-20 case. Every pass served by the primary, whose provider
    LABEL ("DeepSeek") does not equal its provider KEY ("openrouter") — and
    that must mean nothing at all."""
    comp = _composite()
    with caplog.at_level(logging.WARNING, logger="src.bias_composite"):
        await comp.run("msg", context={"article_body": ARTICLE})

    f = comp.extra_log_fields
    assert f["extractor_fallback_passes"] == []
    assert f["extractor_fallback_used"] is False
    assert f["bias_candidate_extractor_fallback_used"] is False
    assert f["bias_judge_fallback_used"] is False
    assert f["bias_judge_fallback_votes"] == []
    assert "FALLBACK" not in caplog.text
    # the served ids still travel — the fix removes an inference, not telemetry
    assert f["bias_candidate_extractor_model_used"] == \
        ["deepseek/deepseek-v4.1-flash"] * 3
    assert f["bias_candidate_extractor_provider_used"] == ["DeepSeek"] * 3


@pytest.mark.asyncio
async def test_the_compound_marker_still_names_what_served():
    comp = _composite()
    await comp.run("msg", context={"article_body": ARTICLE})
    assert comp.last_model_used == "deepseek/deepseek-v4.1-flash x3 -> z-ai/glm-5.3 x2"
    assert comp.last_provider_used == "DeepSeek x3 -> Z.AI x2"


# --- direction 2: a real fallback is still caught ---------------------------

@pytest.mark.asyncio
async def test_a_genuine_rung_serve_is_detected_and_named(caplog):
    """Pass 2's primary attempt fails, so pass 2 — and only pass 2 — is served
    by the rung. The failing pass is deliberately not the last to finish, which
    is what the wrapper's own last-writer-wins marker cannot express."""
    comp = _composite(extractor_fail_on=(2,))
    with caplog.at_level(logging.WARNING, logger="src.bias_composite"):
        await comp.run("msg", context={"article_body": ARTICLE})

    f = comp.extra_log_fields
    assert f["extractor_fallback_passes"] == [2]
    assert f["extractor_fallback_used"] is True
    assert f["bias_candidate_extractor_fallback_used"] is True
    # the rung's served id is in the per-pass list at the right position
    assert f["bias_candidate_extractor_model_used"][1] == "deepseek-flash"
    msg = caplog.text
    assert "bias extractor FALLBACK" in msg
    assert "[2]" in msg
    # the warning names the rung agent and the primary it replaced — the old
    # text claimed passes were "served by the channel-A route, not openrouter",
    # which was both wrong and self-contradictory after the pin
    assert "deepseek-v4-flash" in msg and "deepseek/deepseek-v4.1-flash" in msg
    assert "channel-A route" not in msg


@pytest.mark.asyncio
async def test_every_pass_falling_back_is_reported_as_every_pass():
    comp = _composite(extractor_fail_on=(1, 2, 3, 4))
    await comp.run("msg", context={"article_body": ARTICLE})
    assert comp.extra_log_fields["extractor_fallback_passes"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_judge_votes_use_the_same_mechanism(caplog):
    """The sibling path audited by the same task: vote 1 falls back, vote 2
    does not. Both votes run concurrently against ONE wrapper."""
    comp = _composite(judge_fail_on=(1,))
    with caplog.at_level(logging.WARNING, logger="src.bias_composite"):
        await comp.run("msg", context={"article_body": ARTICLE})

    f = comp.extra_log_fields
    assert f["bias_judge_fallback_votes"] == [1]
    assert f["bias_judge_fallback_used"] is True
    assert f["extractor_fallback_used"] is False, "legs report independently"
    assert "bias judge FALLBACK" in caplog.text


# --- the invariant, stated directly -----------------------------------------

@pytest.mark.asyncio
async def test_detection_ignores_what_the_response_says_about_its_provider():
    """The regression guard proper. Give the primary a provider label from
    another planet; the rung fact is unchanged, because it never came from
    there."""
    comp = _composite()
    comp.extractor.primary._served = ("some/other-id", "SomeOtherProvider")
    await comp.run("msg", context={"article_body": ARTICLE})

    f = comp.extra_log_fields
    assert f["extractor_fallback_passes"] == []
    assert f["extractor_fallback_used"] is False
    # …and the odd ids are still reported verbatim, which is how a real
    # provider-side substitution stays visible
    assert f["bias_candidate_extractor_model_used"] == ["some/other-id"] * 3
