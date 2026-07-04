"""Editor model swap + fallback (TASK-EDITOR-SWAP-GLM).

The editor stage runs on GLM-5.2 @ xhigh (fp8-pinned) — the operating point the
editor-stage eval made binding (docs/EDITOR-STAGE-MODEL-EVAL-2026-07.md, FINAL
section: GLM won the blind Architect tally 13/20 and is the cheapest arm, but is
retry-fragile under the strict EDITOR_SCHEMA at xhigh — 55 % first-attempt
validity, 22/22 after retries; provider pin from
docs/GLM-PROVIDER-VERIFICATION-2026-07.md, all three re-probed under
EDITOR_SCHEMA in the eval). This module is the **4th line of defence** behind
that call: the pinned-provider order, ``allow_fallbacks:false``, and Agent's
built-in transport retries are lines 1-3 and stay in Agent/OpenRouter. If GLM
*finally* fails — a transport error across all pinned providers after those
retries, OR a final output that is not schema-valid (the ``structured=None``
truncation/parse failure this stage is prone to at xhigh) — this wrapper makes
**exactly one** fallback attempt and returns that instead.

Deliberate choice of fallback: the editor fallback is **Sonnet-5**
(``anthropic/claude-sonnet-5``, ``reasoning {enabled:true, effort:"high"}``, no
temperature), *not* the pre-swap incumbent (Opus 4.6) and *not* the writer's
Opus-4.6 fallback. Sonnet-5 was the eval's **22/22 first-attempt** arm and its
editorial #2 — a validated, known-good safety net that caps the worst case at a
sound selection. (Contrast the writer swap, whose fallback is Opus-4.6: there the
concern was Sonnet-5's citation hygiene; the editor has no citations, and here
Sonnet-5's perfect reliability is exactly what the once-a-day, no-native-fallback
editor needs.)

Two invariants the task pins down (identical to the qa/writer wrappers):

* **Loud, never silent.** A fallback emits a WARNING log line *and* a persisted
  marker — ``model_used`` + ``provider_used`` + ``editor_fallback_used`` — into
  the per-stage ``run_stage_log.jsonl`` row (the runner's
  ``_collect_agent_metrics`` reads the marker attributes this wrapper exposes,
  keyed by ``fallback_marker_key``). The editor is a run-stage, so this is a
  run-level log entry. There is no code path that silently substitutes a model.
* **Minimal mechanism.** This is a thin wrapper over two ordinary
  :class:`~src.agent.Agent` instances — no generic multi-model framework. It
  duck-types the handful of members ``EditorStage`` and the runner touch
  (``run``, ``name``, ``last_cost_usd``, ``last_tokens``, ``reset_call_metrics``)
  so it drops in wherever ``agents["editor"]`` is consumed.

Schema validity is judged against the *live* ``EDITOR_SCHEMA`` object (passed in)
via the generic checker shared with the qa/writer wrappers
(:func:`src.qa_fallback.qa_output_is_schema_valid` — it reads whatever schema is
handed in, so it validates the real production schema with no drift; ``None`` is
always invalid, which is the exact ``structured=None`` failure signal here).
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult
# The schema-validity checker is generic over the schema handed in (it reads the
# schema object, not QA-specific keys); reuse it so the editor fallback trigger
# can never drift from EDITOR_SCHEMA. Aliased to a neutral name at import.
from src.qa_fallback import qa_output_is_schema_valid as output_is_schema_valid

logger = logging.getLogger(__name__)


class EditorWithFallback:
    """Primary GLM-5.2 editor with a one-shot Sonnet-5 model fallback.

    Drop-in for ``agents["editor"]``: :class:`~src.agent_stages.EditorStage` only
    calls ``.run(...)`` and reads nothing else off the agent; the runner's metric
    collector reads ``last_cost_usd`` / ``last_tokens`` / ``reset_call_metrics``
    (duck-typed here) plus the fallback markers ``last_model_used`` /
    ``last_provider_used`` / ``last_fallback_used`` keyed under
    ``fallback_marker_key``.
    """

    # The runner logs the fallback marker under this key (TASK-EDITOR-SWAP-GLM).
    # Distinct from qa_analyze's "qa_fallback_used" and writer's
    # "writer_fallback_used" so each stage's row stays unambiguous.
    fallback_marker_key = "editor_fallback_used"

    def __init__(
        self,
        primary: Agent,
        fallback: Agent,
        output_schema: dict,
        name: str = "editor",
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.output_schema = output_schema
        self.name = name
        # Display model — the intended primary. ``last_model_used`` records what
        # actually served the most recent call.
        self.model = primary.model
        # Mirror the primary's decode params so any introspection of the editor
        # agent (metrics/labels) sees the primary's configuration.
        self.temperature = getattr(primary, "temperature", None)
        self.max_tokens = getattr(primary, "max_tokens", None)
        self.reasoning = getattr(primary, "reasoning", None)

        # Per-stage accumulators (runner reads these after the stage; summed
        # across the primary attempt + any fallback attempt so cost/tokens stay
        # complete even when both models are hit).
        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        # Loud markers surfaced into run_stage_log.jsonl: which model+provider
        # actually served this editor call, and whether the fallback fired.
        self.last_model_used: str = ""
        self.last_provider_used: str = ""
        self.last_fallback_used: bool = False

    def reset_call_metrics(self) -> None:
        """Zero per-stage accumulators + markers. Called by the runner before
        the stage executes (so the marker reflects exactly one editor call)."""
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.last_model_used = ""
        self.last_provider_used = ""
        self.last_fallback_used = False
        # Keep the underlying agents' own accumulators from drifting across
        # runs; this wrapper does its own summation from each AgentResult.
        self.primary.reset_call_metrics()
        self.fallback.reset_call_metrics()

    def _account(self, result: AgentResult) -> None:
        self.last_cost_usd += result.cost_usd
        self.last_tokens += result.tokens_used

    async def run(self, *args: Any, **kwargs: Any) -> AgentResult:
        """Run the primary; fall back to Sonnet-5 exactly once on final failure.

        Final failure = the primary raised after its built-in retries (transport
        failure across all pinned providers) OR returned an output that is not
        schema-valid (``structured=None`` / malformed). A transport failure on
        the *fallback* is allowed to propagate — that is the loud terminal
        failure (the run fails), not a silent success.
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
            "editor FALLBACK: primary %s failed — %s. Making exactly one "
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
            "editor FALLBACK complete: served by %s (provider=%s), schema_valid=%s.",
            self.last_model_used,
            fb.provider or "unknown",
            output_is_schema_valid(fb.structured, self.output_schema),
        )
        return fb
