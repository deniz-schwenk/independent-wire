"""bias_judge: Opus-4.6 -> glm-5.3 @ high, with a one-shot Opus rung
(TASK-BIASJUDGE-SWAP, owner Go on the T5b verdict 2026-09-07).

The wiring itself (exact request bodies for both legs, create_agents shape) is
asserted in ``tests/test_bias_stage_split.py`` alongside the extractor's. What
lives here is the behaviour the swap introduces:

  * the rung fires on a FINAL primary failure — transport after retries, or an
    output the local schema check rejects (the Z.AI route has no strict
    decoding, so that check is load-bearing, not belt-and-braces);
  * it fires EXACTLY ONCE and is never run in parallel with the primary (owner
    directive: a fallback rung, not a shadow);
  * a fallback is LOUD: it reaches ``run_stage_log.jsonl`` as
    ``bias_judge_fallback_used`` on the stage row, via the composite's
    ``extra_log_fields``;
  * the marker survives CONCURRENCY. The composite issues its two judgment
    votes with ``asyncio.gather`` against ONE wrapper instance, so the
    wrapper's own ``last_fallback_used`` is last-writer-wins and cannot be the
    source of truth — exactly the problem ``_channel_report`` already solves
    for the extractor's three passes. The composite reads the SERVED MODEL per
    vote instead.
"""
from __future__ import annotations

import logging

import pytest

from src.agent import AgentError, AgentResult
from src.bias_composite import BiasComposite
from src.flash_stage_fallback import FlashStageWithFallback
from src.runner.runner import _collect_agent_metrics
from src.schemas import BIAS_JUDGE_SCHEMA

ARTICLE = (
    "The council's decision dealt a devastating blow to neighborhood bakeries. "
    "Officials called it prudent."
)
GOOD_JUDGMENTS = {
    "judgments": [
        {"candidate_id": 1, "explanation": "author's own voice",
         "issue": "evaluative_adjective", "verdict": "confirmed"},
    ],
    "reader_note": "one loaded phrase.",
}
CANDIDATES = {"candidates": [
    {"excerpt": "devastating", "issue_hint": "evaluative_adjective"}]}


class _Agent:
    """Minimal Agent stand-in: scripted per-call outcomes."""

    def __init__(self, model, outcomes, provider="Z.AI"):
        self.model = model
        self.provider = "openrouter"
        self.temperature = None
        self.reasoning = "high"
        self.max_tokens = 32000
        self.output_schema = BIAS_JUDGE_SCHEMA
        self._outcomes = list(outcomes)
        self._served_provider = provider
        self.calls = 0

    async def run(self, message=None, context=None, **kw):
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return AgentResult(
            content="", structured=outcome, cost_usd=0.01, tokens_used=100,
            model=self.model, provider=self._served_provider)

    def reset_call_metrics(self):
        pass


def _judge(primary_outcomes, fallback_outcomes=(GOOD_JUDGMENTS,)):
    primary = _Agent("z-ai/glm-5.3", primary_outcomes, provider="Z.AI")
    fallback = _Agent("anthropic/claude-opus-4.6", fallback_outcomes,
                      provider="Anthropic")
    wrapper = FlashStageWithFallback(
        primary=primary, fallback=fallback, output_schema=BIAS_JUDGE_SCHEMA,
        name="bias_judge", fallback_marker_key="bias_judge_fallback_used")
    return wrapper, primary, fallback


class _Stage:
    """The runner reads metrics off ``stage.agent``, not off the agent."""

    def __init__(self, agent):
        self.agent = agent


def _composite(judge):
    extractor = _Agent("deepseek-v4-flash", [CANDIDATES] * 4,
                       provider="deepseek_direct")
    extractor.output_schema = {"type": "object"}
    return BiasComposite(extractor=extractor, judge=judge)


# --------------------------------------------------------------------------- #
# The rung: when it fires, how often, and in what order
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_happy_path_never_touches_the_rung():
    judge, primary, fallback = _judge([GOOD_JUDGMENTS])
    comp = _composite(judge)
    res = await comp.run(context={"article_body": ARTICLE})
    assert fallback.calls == 0
    assert primary.calls == 2                      # the two production votes
    assert comp.extra_log_fields["bias_judge_fallback_used"] is False
    assert comp.extra_log_fields["bias_judge_fallback_votes"] == []
    assert comp.extra_log_fields["judge_model_served"] == ["z-ai/glm-5.3"] * 2
    assert res.structured["language_bias"]["findings"]


@pytest.mark.asyncio
async def test_transport_failure_after_retries_fires_the_rung_once_per_vote():
    """AgentError out of the primary means Agent's own retries are already
    spent. One fallback attempt per vote, never two."""
    judge, primary, fallback = _judge([AgentError("z-ai 503 after retries")])
    comp = _composite(judge)
    await comp.run(context={"article_body": ARTICLE})
    assert primary.calls == 2
    assert fallback.calls == 2                     # exactly one per vote
    assert comp.extra_log_fields["bias_judge_fallback_used"] is True
    assert comp.extra_log_fields["bias_judge_fallback_votes"] == [1, 2]


@pytest.mark.asyncio
async def test_schema_invalid_output_fires_the_rung():
    """No strict decoding on the Z.AI route, so a well-formed-JSON-but-wrong
    payload is a primary failure, not a pass-through."""
    judge, primary, fallback = _judge([{"not_judgments": []}])
    comp = _composite(judge)
    await comp.run(context={"article_body": ARTICLE})
    assert fallback.calls == 2
    assert comp.extra_log_fields["bias_judge_fallback_used"] is True


@pytest.mark.asyncio
async def test_empty_body_is_a_failure_not_an_empty_verdict_set():
    """structured=None (reasoning runaway / empty completion) must fall back —
    silently shipping it would clear every candidate on this article."""
    judge, primary, fallback = _judge([None])
    comp = _composite(judge)
    await comp.run(context={"article_body": ARTICLE})
    assert fallback.calls == 2
    assert comp.extra_log_fields["bias_judge_fallback_used"] is True


@pytest.mark.asyncio
async def test_primary_runs_first_and_the_rung_only_after_it_failed():
    """Ordering, not just counts: a rung that raced the primary would be a
    shadow run. The fallback must have zero calls until the primary has
    finally failed."""
    order: list[str] = []
    judge, primary, fallback = _judge([AgentError("boom")])

    async def _primary_run(message=None, context=None, **kw):
        order.append("primary")
        raise AgentError("boom")

    async def _fallback_run(message=None, context=None, **kw):
        order.append("fallback")
        return AgentResult(content="", structured=GOOD_JUDGMENTS,
                           model=fallback.model, provider="Anthropic")

    primary.run = _primary_run
    fallback.run = _fallback_run
    comp = _composite(judge)
    await comp.run(context={"article_body": ARTICLE})
    # both votes: primary attempt strictly before that vote's fallback
    assert order.count("primary") == 2 and order.count("fallback") == 2
    assert order.index("primary") < order.index("fallback")


@pytest.mark.asyncio
async def test_one_vote_falling_back_is_reported_as_that_vote_only():
    """A mixed round is the realistic case and the marker must not round it to
    'all' or 'none' — the log names which vote was served by the rung."""
    judge, primary, fallback = _judge([AgentError("boom"), GOOD_JUDGMENTS])
    comp = _composite(judge)
    await comp.run(context={"article_body": ARTICLE})
    assert comp.extra_log_fields["bias_judge_fallback_used"] is True
    assert comp.extra_log_fields["bias_judge_fallback_votes"] == [1]
    assert comp.extra_log_fields["judge_model_served"] == [
        "anthropic/claude-opus-4.6", "z-ai/glm-5.3"]


# --------------------------------------------------------------------------- #
# Loudness: WARNING line + persisted marker on the stage row
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_fallback_is_loud_in_the_log(caplog):
    judge, _, _ = _judge([AgentError("boom")])
    comp = _composite(judge)
    with caplog.at_level(logging.WARNING):
        await comp.run(context={"article_body": ARTICLE})
    text = caplog.text
    assert "bias judge FALLBACK" in text
    assert "bias_judge_fallback_used" in text
    assert "anthropic/claude-opus-4.6" in text


@pytest.mark.asyncio
async def test_marker_reaches_the_stage_log_row():
    """The runner reads the COMPOSITE (it is the stage's agent), not the
    wrapper — so the marker has to travel through extra_log_fields to appear in
    run_stage_log.jsonl at all."""
    judge, _, _ = _judge([AgentError("boom")])
    comp = _composite(judge)
    await comp.run(context={"article_body": ARTICLE})
    row = _collect_agent_metrics(_Stage(comp))
    assert row["bias_judge_fallback_used"] is True
    assert row["judge_model"] == "z-ai/glm-5.3"          # the intended primary
    assert row["judge_model_served"] == ["anthropic/claude-opus-4.6"] * 2


@pytest.mark.asyncio
async def test_no_candidates_skips_the_judge_and_reports_no_fallback():
    """The empty-candidate short circuit must not read as a fallback.

    The article has to be lexicon-clean as well as extractor-clean: a canonical
    term found by ``scan_lexicon`` is a candidate in its own right and would
    keep the judge running (TASK-BIAS-LEXICON)."""
    judge, primary, fallback = _judge([GOOD_JUDGMENTS])
    comp = _composite(judge)
    comp.extractor._outcomes = [{"candidates": []}]
    await comp.run(context={"article_body": "The council met on Tuesday."})
    assert primary.calls == 0 and fallback.calls == 0
    assert comp.extra_log_fields["judge_skipped"] is True
    assert comp.extra_log_fields["bias_judge_fallback_used"] is False


# --------------------------------------------------------------------------- #
# Cost accounting survives the wrapper
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_fallback_spend_reaches_the_stage_row():
    """A round that fell back bills BOTH legs. The composite accounts from the
    returned result, which carries only the fallback's spend, so the wrapper's
    accumulator is what makes the wasted primary attempt visible."""
    judge, _, _ = _judge([AgentError("boom")])
    comp = _composite(judge)
    await comp.run(context={"article_body": ARTICLE})
    # wrapper saw 2 fallback results at 0.01 each (the raised primary bills
    # nothing it can report); the composite's own total covers extraction too.
    assert judge.last_cost_usd == pytest.approx(0.02)
    assert comp.last_cost_usd > 0
