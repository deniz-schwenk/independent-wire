"""One-shot model fallback for the DeepSeek-V4-Flash schema-bearing stages
(TASK-RESEARCHER-ASSEMBLE-FALLBACK, extended to the sibling flash stages).

Three production stages run on ``deepseek/deepseek-v4-flash`` pinned to a closed
list of fp8 providers verified for strict json_schema
(``DEEPSEEK_V4_FLASH_FP8_ROUTING`` in ``scripts/run.py``; ``allow_fallbacks:
false`` fails loud rather than dropping to an unverified/fp4 or schema-incapable
provider):

* ``researcher_assemble`` — per-topic; failure drops that topic.
* ``curator_topic_discovery`` — RUN-LEVEL; failure kills the whole day's run.
* ``resolve_actor_aliases`` — per-topic; failure drops that topic.

The pinned providers plus Agent's built-in transport retries are lines 1-3 of
defence. This wrapper is line 4: if the primary *finally* fails — a transport/API
error across all pinned providers after those retries, OR a final output that is
not schema-valid — it makes **exactly one** fallback attempt on a different model
and returns that instead.

Motivation: on 2026-07-14 the primary's fp8 providers were transiently 429-rate-
limited and routing fell to streamlake, which returned a non-retryable 400 (it
had silently dropped strict-json_schema support). That single bad-provider hit
was fatal and dropped tp-2026-07-14-002 — the stage had no fallback. (streamlake
has since been removed from the pin; this wrapper is the second, independent line
of insurance against a *total* deepseek-flash outage — all pinned providers
rate-limited at once. Especially load-bearing for the run-level
curator_topic_discovery, whose failure ends the whole run.)

Fallback model: ``google/gemini-3-flash-preview`` — the PRE-migration incumbent
for all three stages (they *were* Gemini-3-Flash until 2026-05-18/19, Wave-1/2
sweeps; deepseek-v4-flash won on cost, not quality — docs/AGENT-IO-MAP.md,
docs/cost-efficiency-sweep-2026-05-18/). Deliberately a different provider
ecosystem (Google) from DeepSeek-on-OpenRouter, so a broad DeepSeek rate-limit
event (the 2026-07-14 trigger) does not take the fallback down with the primary.
Cheap, and re-verified 2026-07-14 to honor strict json_schema against all three
live schemas (RESEARCHER_ASSEMBLE / CURATOR_TOPIC_DISCOVERY / RESOLVE_ACTOR_
ALIASES, via the production checker). Each stage's fallback Agent runs at that
stage's original Gemini operating point and carries NO fp8 provider_routing (the
pin is DeepSeek-specific); wiring in ``scripts/run.py``.

Invariants (identical to the writer/qa/editor fallbacks):

* **Loud, never silent.** A fallback emits a WARNING log line *and* a persisted
  marker — ``model_used`` + ``provider_used`` + ``<stage>_fallback_used`` — into
  the per-stage ``run_stage_log.jsonl`` row (the runner's ``_collect_agent_metrics``
  reads the marker attributes this wrapper exposes, keyed by the per-instance
  ``fallback_marker_key``). No code path silently substitutes a model.
* **Minimal mechanism.** A thin wrapper over two ordinary :class:`~src.agent.Agent`
  instances — no generic multi-model framework. It duck-types the members the
  agent-wrapper stages and the runner touch (``run``, ``name``, ``model``,
  ``temperature``, ``max_tokens``, ``reasoning``, ``last_cost_usd``,
  ``last_tokens``, ``reset_call_metrics``) so it drops in wherever the primary
  ``Agent`` was consumed, in both pipeline variants.

Schema validity is judged against the *live* ``output_schema`` object (passed in)
via the generic checker shared with the qa_analyze wrapper
(:func:`src.qa_fallback.qa_output_is_schema_valid`), so the trigger can never
drift from the real production schema.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult
from src.qa_fallback import qa_output_is_schema_valid as output_is_schema_valid

logger = logging.getLogger(__name__)


class FlashStageWithFallback:
    """Primary DeepSeek-V4-Flash agent with a one-shot gemini-3-flash-preview
    model fallback, parameterized by stage ``name`` + ``fallback_marker_key``.

    Drop-in for the ``agents[...]`` entry of any deepseek-v4-flash schema-bearing
    stage: the agent-wrapper stages only call ``.run(...)`` and read the
    duck-typed introspection members (``name`` / ``model`` / ``temperature`` /
    ``max_tokens`` / ``reasoning``); the runner's metric collector reads
    ``last_cost_usd`` / ``last_tokens`` / ``reset_call_metrics`` plus the fallback
    markers ``last_model_used`` / ``last_provider_used`` / ``last_fallback_used``
    keyed under ``fallback_marker_key``.
    """

    def __init__(
        self,
        primary: Agent,
        fallback: Agent,
        output_schema: dict,
        name: str,
        fallback_marker_key: str,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.output_schema = output_schema
        self.name = name
        # Per-instance marker key (the runner logs the fallback marker under it);
        # distinct per stage so a row stays unambiguous.
        self.fallback_marker_key = fallback_marker_key
        # Display model — the intended primary. ``last_model_used`` records what
        # actually served the most recent call.
        self.model = primary.model
        # Mirror the primary's decode params so any introspection (the stages'
        # own metric getattr, labels) sees the primary's configuration.
        self.temperature = getattr(primary, "temperature", None)
        self.max_tokens = getattr(primary, "max_tokens", None)
        self.reasoning = getattr(primary, "reasoning", None)

        # Per-stage accumulators (summed across the primary attempt + any
        # fallback attempt so cost/tokens stay complete even when both hit).
        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        # Loud markers surfaced into run_stage_log.jsonl.
        self.last_model_used: str = ""
        self.last_provider_used: str = ""
        self.last_fallback_used: bool = False

    def reset_call_metrics(self) -> None:
        """Zero per-stage accumulators + markers. Called by the runner before
        each stage execution (so the marker reflects exactly one call)."""
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.last_model_used = ""
        self.last_provider_used = ""
        self.last_fallback_used = False
        self.primary.reset_call_metrics()
        self.fallback.reset_call_metrics()

    def _account(self, result: AgentResult) -> None:
        self.last_cost_usd += result.cost_usd
        self.last_tokens += result.tokens_used

    async def run(self, *args: Any, **kwargs: Any) -> AgentResult:
        """Run the primary; fall back to gemini-3-flash-preview exactly once on
        final failure.

        Final failure = the primary raised after its built-in retries (transport
        failure across all pinned providers, e.g. every fp8 provider 429-limited,
        or a non-retryable 4xx) OR returned an output that is not schema-valid
        (truncation / malformed). A transport failure on the *fallback* is
        allowed to propagate — that is the loud terminal failure, not a silent
        success.
        """
        failure_reason: str | None = None
        result: AgentResult | None = None

        try:
            result = await self.primary.run(*args, **kwargs)
        except AgentError as exc:
            failure_reason = f"transport failure after retries ({exc})"

        if result is not None:
            self._account(result)
            if not output_is_schema_valid(result.structured, self.output_schema):
                failure_reason = "final output not schema-valid (truncation or malformed)"

        if failure_reason is None:
            assert result is not None  # for type-checkers; guaranteed here
            self.last_model_used = result.model or self.primary.model
            self.last_provider_used = result.provider
            self.last_fallback_used = False
            return result

        logger.warning(
            "%s FALLBACK: primary %s failed — %s. Making exactly one fallback "
            "attempt on %s. (This is the model fallback, not a silent "
            "substitution.)",
            self.name,
            self.primary.model,
            failure_reason,
            self.fallback.model,
        )

        fb = await self.fallback.run(*args, **kwargs)
        self._account(fb)
        self.last_model_used = fb.model or self.fallback.model
        self.last_provider_used = fb.provider
        self.last_fallback_used = True
        logger.warning(
            "%s FALLBACK complete: served by %s (provider=%s), schema_valid=%s.",
            self.name,
            self.last_model_used,
            fb.provider or "unknown",
            output_is_schema_valid(fb.structured, self.output_schema),
        )
        return fb
