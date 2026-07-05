"""Hydration Phase-2 model swap + fallback (TASK-HYDRATION-P2-GLM-SWAP).

The ``hydration_aggregator_phase2`` reducer runs on GLM-5.2 @ xhigh (fp8-pinned)
— the operating point the phase-2 model eval made binding
(docs/HYDRATION-P2-MODEL-EVAL-2026-07.md: GLM-5.2 ties the Opus-4.8 golden
ceiling at overall 4.46, halves fabrications vs the pre-swap Opus-4.6 incumbent
— 8 vs 14 across 21 topics — and is 2.7x cheaper; provider pin from
docs/GLM-PROVIDER-VERIFICATION-2026-07.md, the same three fp8 providers verified
for the editor/qa/writer swaps). This module is the **4th line of defence**
behind that call: the pinned-provider order, ``allow_fallbacks:false``, and
Agent's built-in transport retries are lines 1-3 and stay in Agent/OpenRouter.
If GLM *finally* fails — a transport error across all pinned providers after
those retries, OR a final output that is not schema-valid (the
``structured=None`` truncation/parse failure) — this wrapper makes **exactly
one** fallback attempt and returns that instead.

Choice of fallback: the phase-2 fallback is the **pre-swap production incumbent**
(``anthropic/claude-opus-4.6``, temperature 0.1, reasoning ``none``, max_tokens
32000, same PHASE2 prompts + ``HYDRATION_PHASE2_SCHEMA``) — the exact
configuration this stage ran in production before the swap, so the worst case
degrades to the known-good prior behaviour. This mirrors the writer swap
(whose fallback is likewise the pre-swap Opus-4.6 incumbent); phase-2 is a
per-topic reducer with no native fallback, so a validated last resort matters.

Two invariants the task pins down (identical to the qa/writer/editor wrappers):

* **Loud, never silent.** A fallback emits a WARNING log line *and* a persisted
  marker — ``model_used`` + ``provider_used`` + ``hydration_phase2_fallback_used``
  — into the per-stage ``run_stage_log.jsonl`` row (the runner's
  ``_collect_agent_metrics`` reads the marker attributes this wrapper exposes,
  keyed by ``fallback_marker_key``). Phase-2 is a topic-stage, so this is a
  per-topic log entry. There is no code path that silently substitutes a model.
  (Before this task the Phase2 row carried only cost/tokens — the three fields
  are new for this stage.)
* **Minimal mechanism.** This is a thin wrapper over two ordinary
  :class:`~src.agent.Agent` instances — no generic multi-model framework. It
  duck-types the handful of members ``HydrationPhase2Stage`` and the runner
  touch (``run``, ``name``, ``last_cost_usd``, ``last_tokens``,
  ``reset_call_metrics``) so it drops in wherever
  ``agents["hydration_aggregator_phase2"]`` is consumed.

Schema validity is judged against the *live* ``HYDRATION_PHASE2_SCHEMA`` object
(passed in) via the generic checker shared with the qa/writer/editor wrappers
(:func:`src.qa_fallback.qa_output_is_schema_valid` — it reads whatever schema is
handed in, so it validates the real production schema with no drift; ``None`` is
always invalid, which is the exact ``structured=None`` failure signal here).
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult
# The schema-validity checker is generic over the schema handed in (it reads the
# schema object, not QA-specific keys); reuse it so the phase-2 fallback trigger
# can never drift from HYDRATION_PHASE2_SCHEMA. Aliased to a neutral name.
from src.qa_fallback import qa_output_is_schema_valid as output_is_schema_valid

logger = logging.getLogger(__name__)


class HydrationPhase2WithFallback:
    """Primary GLM-5.2 phase-2 reducer with a one-shot Opus-4.6 model fallback.

    Drop-in for ``agents["hydration_aggregator_phase2"]``:
    :class:`~src.agent_stages.HydrationPhase2Stage` (via ``_run_phase2_reducer``)
    only calls ``.run(...)`` and reads ``result.structured`` off it; the runner's
    metric collector reads ``last_cost_usd`` / ``last_tokens`` /
    ``reset_call_metrics`` (duck-typed here) plus the fallback markers
    ``last_model_used`` / ``last_provider_used`` / ``last_fallback_used`` keyed
    under ``fallback_marker_key``.
    """

    # The runner logs the fallback marker under this key. Distinct from the
    # editor/writer/qa/perspective keys so a phase-2 row stays unambiguous — the
    # established per-stage convention (each stage names its own marker).
    fallback_marker_key = "hydration_phase2_fallback_used"

    def __init__(
        self,
        primary: Agent,
        fallback: Agent,
        output_schema: dict,
        name: str = "hydration_aggregator_phase2",
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.output_schema = output_schema
        self.name = name
        # Display model — the intended primary. ``last_model_used`` records what
        # actually served the most recent call.
        self.model = primary.model
        # Mirror the primary's decode params so any introspection of the agent
        # (metrics/labels) sees the primary's configuration.
        self.temperature = getattr(primary, "temperature", None)
        self.max_tokens = getattr(primary, "max_tokens", None)
        self.reasoning = getattr(primary, "reasoning", None)

        # Per-stage accumulators (runner reads these after the stage; summed
        # across the primary attempt + any fallback attempt so cost/tokens stay
        # complete even when both models are hit).
        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        # Loud markers surfaced into run_stage_log.jsonl: which model+provider
        # actually served this phase-2 call, and whether the fallback fired.
        self.last_model_used: str = ""
        self.last_provider_used: str = ""
        self.last_fallback_used: bool = False

    def reset_call_metrics(self) -> None:
        """Zero per-stage accumulators + markers. Called by the runner before
        the stage executes (so the marker reflects exactly one phase-2 call)."""
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
        failure across all pinned providers) OR returned an output that is not
        schema-valid (``structured=None`` / malformed). A transport failure on
        the *fallback* is allowed to propagate — that is the loud terminal
        failure (the topic fails), not a silent success.
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
                failure_reason = "final output not schema-valid (structured=None / malformed)"

        if failure_reason is None:
            # Primary served a valid result — the common path.
            assert result is not None  # for type-checkers; guaranteed here
            self.last_model_used = result.model or self.primary.model
            self.last_provider_used = result.provider
            self.last_fallback_used = False
            return result

        logger.warning(
            "hydration_phase2 FALLBACK: primary %s failed — %s. Making exactly "
            "one fallback attempt on %s. (This is the model fallback, not a "
            "silent substitution.)",
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
            "hydration_phase2 FALLBACK complete: served by %s (provider=%s), "
            "schema_valid=%s.",
            self.last_model_used,
            fb.provider or "unknown",
            output_is_schema_valid(fb.structured, self.output_schema),
        )
        return fb
