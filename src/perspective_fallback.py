"""Perspective model swap + fallback (TASK-PERSPECTIVE-SWAP-SONNET5).

The perspective stage runs on Sonnet-5 @ ``reasoning{enabled, effort:high}`` (no
temperature) — the operating point the blind eval made binding
(docs/PERSPECTIVE-STAGE-MODEL-EVAL-2026-07.md: Sonnet-5 beats the incumbent
19–2, matches the golden ceiling on the product-core criteria R1/R5/R9, fewest
confirmed invented positions, fully reliable 21/21). Both open-weight candidates
regressed BELOW the incumbent on this stage, so this is a pure quality swap.
Sonnet-5 is Anthropic-served — no provider pin — but the served provider is
still recorded per call.

This module is the **safety net** behind that call: Agent's built-in transport
retries are the first line and stay in Agent/OpenRouter. If Sonnet-5 *finally*
fails — a transport error after those retries, OR a final output that is not
schema-valid (truncation included) — this wrapper makes **exactly one** fallback
attempt and returns that instead.

The fallback is the **pre-swap production incumbent VERBATIM**
(``anthropic/claude-opus-4.6``, ``temperature=0.1``, ``reasoning="none"``, its
current ``max_tokens``) — a validated known-good configuration that served this
stage in production up to the swap. (Contrast the writer wrapper, whose fallback
is likewise the pre-swap incumbent, and the qa wrapper, whose fallback is
Sonnet-5; the fallback identity is always the task-specified last resort, not a
fixed model.)

Two invariants the task pins down (identical to TASK-WRITER-SWAP-GLM):

* **Loud, never silent.** A fallback emits a WARNING log line *and* a persisted
  marker — ``model_used`` + ``provider_used`` + ``perspective_fallback_used`` —
  into the per-stage ``run_stage_log.jsonl`` row (the runner's
  ``_collect_agent_metrics`` reads the marker attributes this wrapper exposes,
  keyed by ``fallback_marker_key``). There is no code path that silently
  substitutes a model.
* **Minimal mechanism.** This is a thin wrapper over two ordinary
  :class:`~src.agent.Agent` instances — no generic multi-model framework. It
  duck-types the handful of members :class:`~src.agent_stages.PerspectiveStage`
  and the runner touch (``run``, ``name``, ``last_cost_usd``, ``last_tokens``,
  ``reset_call_metrics``) so it drops in wherever ``agents["perspective"]`` is
  consumed, in both pipeline variants.

Schema validity is judged against the *live* ``PERSPECTIVE_SCHEMA`` object
(passed in) via the generic checker shared with the qa_analyze / writer wrappers
(:func:`src.qa_fallback.qa_output_is_schema_valid` — it reads whatever schema is
handed in, so it validates the real production schema with no drift).
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult
# The schema-validity checker is generic over the schema handed in (it reads the
# schema object, not QA-specific keys); reuse it so the perspective fallback
# trigger can never drift from PERSPECTIVE_SCHEMA. Aliased to a neutral name.
from src.qa_fallback import qa_output_is_schema_valid as output_is_schema_valid

logger = logging.getLogger(__name__)


class PerspectiveWithFallback:
    """Primary Sonnet-5 perspective agent with a one-shot Opus-4.6 model fallback.

    Drop-in for ``agents["perspective"]``:
    :class:`~src.agent_stages.PerspectiveStage` only calls ``.run(...)`` and reads
    nothing else off the agent; the runner's metric collector reads
    ``last_cost_usd`` / ``last_tokens`` / ``reset_call_metrics`` (duck-typed here)
    plus the fallback markers ``last_model_used`` / ``last_provider_used`` /
    ``last_fallback_used`` keyed under ``fallback_marker_key``.
    """

    # The runner logs the fallback marker under this key
    # (TASK-PERSPECTIVE-SWAP-SONNET5). Distinct from writer's
    # "writer_fallback_used" / qa's "qa_fallback_used" so a perspective-stage row
    # stays unambiguous.
    fallback_marker_key = "perspective_fallback_used"

    def __init__(
        self,
        primary: Agent,
        fallback: Agent,
        output_schema: dict,
        name: str = "perspective",
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.output_schema = output_schema
        self.name = name
        # Display model — the intended primary. ``last_model_used`` records what
        # actually served the most recent call.
        self.model = primary.model
        # Mirror the primary's decode params so any introspection of the
        # perspective agent (metrics/labels) sees the primary's configuration.
        self.temperature = getattr(primary, "temperature", None)
        self.max_tokens = getattr(primary, "max_tokens", None)
        self.reasoning = getattr(primary, "reasoning", None)

        # Per-stage accumulators (runner reads these after each stage; summed
        # across the primary attempt + any fallback attempt so cost/tokens stay
        # complete even when both models are hit).
        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        # Loud markers surfaced into run_stage_log.jsonl: which model+provider
        # actually served this perspective call, and whether the fallback fired.
        self.last_model_used: str = ""
        self.last_provider_used: str = ""
        self.last_fallback_used: bool = False

    def reset_call_metrics(self) -> None:
        """Zero per-stage accumulators + markers. Called by the runner before
        each stage execution (so the marker reflects exactly one perspective
        call)."""
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.last_model_used = ""
        self.last_provider_used = ""
        self.last_fallback_used = False
        # Keep the underlying agents' own accumulators from drifting across
        # topics; this wrapper does its own summation from each AgentResult.
        self.primary.reset_call_metrics()
        self.fallback.reset_call_metrics()

    def _account(self, result: AgentResult) -> None:
        self.last_cost_usd += result.cost_usd
        self.last_tokens += result.tokens_used

    async def run(self, *args: Any, **kwargs: Any) -> AgentResult:
        """Run the primary; fall back to Opus-4.6 exactly once on final failure.

        Final failure = the primary raised after its built-in retries (transport
        failure) OR returned an output that is not schema-valid (truncation /
        malformed). A transport failure on the *fallback* is allowed to
        propagate — that is the loud terminal failure (the topic fails), not a
        silent success.
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
            # Primary served a valid result — the common path.
            assert result is not None  # for type-checkers; guaranteed here
            self.last_model_used = result.model or self.primary.model
            self.last_provider_used = result.provider
            self.last_fallback_used = False
            return result

        logger.warning(
            "perspective FALLBACK: primary %s failed — %s. Making exactly one "
            "fallback attempt on %s. (This is the model fallback, not a silent "
            "substitution.)",
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
            "perspective FALLBACK complete: served by %s (provider=%s), "
            "schema_valid=%s.",
            self.last_model_used,
            fb.provider or "unknown",
            output_is_schema_valid(fb.structured, self.output_schema),
        )
        return fb
