"""QA-Analyze model swap + fallback (TASK-QA-SWAP-GLM).

The qa_analyze stage runs on GLM-5.2 @ xhigh (fp8-pinned) — the operating
point the shadow eval made binding (docs/QA-STAGE-MODEL-EVAL-SHADOW-BACKFILL.md
v2; provider pin from docs/GLM-PROVIDER-VERIFICATION-2026-07.md). This module
is the **4th line of defence** behind that call: the pinned-provider order,
``allow_fallbacks:false``, and Agent's built-in transport retries are lines
1–3 and stay in Agent/OpenRouter. If GLM *finally* fails — a transport error
across all pinned providers after those retries, OR a final output that is
not schema-valid (truncation included) — this wrapper makes **exactly one**
fallback attempt on ``anthropic/claude-sonnet-5`` and returns that instead.

Two invariants the task pins down:

* **Loud, never silent.** A fallback emits a WARNING log line *and* a
  persisted marker — ``model_used`` + ``qa_fallback_used`` — into the
  per-stage ``run_stage_log.jsonl`` row (the runner's ``_collect_agent_metrics``
  reads the marker attributes this wrapper exposes). There is no code path
  that silently substitutes a model.
* **Minimal mechanism.** This is a thin wrapper over two ordinary
  :class:`~src.agent.Agent` instances — no generic multi-model framework. It
  duck-types the handful of members ``QaAnalyzeStage`` and the runner touch
  (``run``, ``name``, ``last_cost_usd``, ``last_tokens``,
  ``reset_call_metrics``) so it drops in wherever ``agents["qa_analyze"]``
  is consumed, in both pipeline variants.

Schema validity is judged against the *live* ``QA_ANALYZE_SCHEMA`` object
(passed in), not a hand-copied mirror, so the fallback trigger can never
drift from the production schema.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult

logger = logging.getLogger(__name__)


# --- minimal JSON-Schema validity check --------------------------------------
# A tiny recursive checker over exactly the JSON-Schema keywords
# QA_ANALYZE_SCHEMA uses (type / properties / required / additionalProperties /
# items). It is generic over whatever schema is handed in — it reads the schema
# object rather than QA's specific keys — so it validates the real schema with
# no drift, and needs no third-party dependency (jsonschema is not vendored).

_PY_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "null": type(None),
}


def _matches(value: Any, schema: dict) -> bool:
    """Return True iff ``value`` satisfies ``schema`` (supported keywords only)."""
    declared = schema.get("type")
    # Union type, e.g. ``{"type": ["string", "null"]}`` (EDITOR_SCHEMA's
    # follow_up_to / follow_up_reason): value matches if it satisfies ANY member
    # type. Member types here are scalars, so per-member recursion is exact.
    if isinstance(declared, list):
        return any(_matches(value, {**schema, "type": t}) for t in declared)
    if declared is not None:
        py = _PY_TYPES.get(declared)
        if py is not None:
            # bool is a subclass of int in Python — keep the JSON distinction:
            # a boolean is not an integer/number, and vice versa.
            if declared in ("integer", "number") and isinstance(value, bool):
                return False
            if declared != "boolean" and isinstance(value, bool) and py is not bool:
                return False
            if not isinstance(value, py):
                return False

    if declared == "object":
        if not isinstance(value, dict):
            return False
        props: dict = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                return False
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    return False
        for key, subschema in props.items():
            if key in value and not _matches(value[key], subschema):
                return False
    elif declared == "array":
        if not isinstance(value, list):
            return False
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for item in value:
                if not _matches(item, item_schema):
                    return False
    return True


def qa_output_is_schema_valid(obj: Any, schema: dict) -> bool:
    """True iff ``obj`` is a non-None value satisfying ``schema``.

    ``None`` (an unparseable / absent structured output) is always invalid —
    that is the truncation / parse-failure signal that triggers the fallback.
    """
    if obj is None:
        return False
    return _matches(obj, schema)


# --- the fallback wrapper -----------------------------------------------------


class QaAnalyzeWithFallback:
    """Primary GLM-5.2 QA agent with a one-shot Sonnet-5 model fallback.

    Drop-in for ``agents["qa_analyze"]``: :class:`QaAnalyzeStage` only calls
    ``.run(...)`` and reads nothing else off the agent; the runner's metric
    collector reads ``last_cost_usd`` / ``last_tokens`` /
    ``reset_call_metrics`` (duck-typed here) plus the optional
    ``last_model_used`` / ``last_qa_fallback_used`` markers.
    """

    def __init__(
        self,
        primary: Agent,
        fallback: Agent,
        output_schema: dict,
        name: str = "qa_analyze",
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.output_schema = output_schema
        self.name = name
        # Display model — the intended primary. ``last_model_used`` records
        # what actually served the most recent call.
        self.model = primary.model

        # Per-stage accumulators (runner reads these after each stage; summed
        # across the primary attempt + any fallback attempt so cost/tokens
        # stay complete even when both models are hit).
        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        # Loud marker surfaced into run_stage_log.jsonl: which model+provider
        # actually served this qa call, and whether the fallback fired. The
        # provider is otherwise never persisted anywhere (AgentResult.provider
        # is in-memory only — the gap docs/DEEPSEEK-FP8-PIN-2026-07.md flagged),
        # so recording it here also closes the fp8-pin audit loop.
        self.last_model_used: str = ""
        self.last_provider_used: str = ""
        self.last_qa_fallback_used: bool = False

    def reset_call_metrics(self) -> None:
        """Zero per-stage accumulators + markers. Called by the runner before
        each stage execution (so the marker reflects exactly one qa call)."""
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.last_model_used = ""
        self.last_provider_used = ""
        self.last_qa_fallback_used = False
        # Keep the underlying agents' own accumulators from drifting across
        # topics; this wrapper does its own summation from each AgentResult.
        self.primary.reset_call_metrics()
        self.fallback.reset_call_metrics()

    def _account(self, result: AgentResult) -> None:
        self.last_cost_usd += result.cost_usd
        self.last_tokens += result.tokens_used

    async def run(self, *args: Any, **kwargs: Any) -> AgentResult:
        """Run the primary; fall back to Sonnet-5 exactly once on final failure.

        Final failure = the primary raised after its built-in retries
        (transport failure across all pinned providers) OR returned an output
        that is not schema-valid (truncation / malformed). A transport failure
        on the *fallback* is allowed to propagate — that is the loud terminal
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
            if not qa_output_is_schema_valid(result.structured, self.output_schema):
                failure_reason = "final output not schema-valid (truncation or malformed)"

        if failure_reason is None:
            # Primary served a valid result — the common path.
            assert result is not None  # for type-checkers; guaranteed here
            self.last_model_used = result.model or self.primary.model
            self.last_provider_used = result.provider
            self.last_qa_fallback_used = False
            return result

        logger.warning(
            "qa_analyze FALLBACK: primary %s failed — %s. Making exactly one "
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
        self.last_qa_fallback_used = True
        logger.warning(
            "qa_analyze FALLBACK complete: served by %s (provider=%s), "
            "schema_valid=%s.",
            self.last_model_used,
            fb.provider or "unknown",
            qa_output_is_schema_valid(fb.structured, self.output_schema),
        )
        return fb
