"""One-shot channel fallback for the three v4-flash-0731 schema-bearing stages
(TASK-RESEARCHER-ASSEMBLE-FALLBACK, extended to the siblings; retargeted from
a model fallback to a CHANNEL fallback by TASK-FLASH-0731-SWAP, 2026-08-24).

Three production stages run on ``deepseek-v4-flash-0731``, full precision, with
two independent routes to the same weights (``scripts/run.py``,
``_flash_0731_primary`` / ``_flash_0731_fallback``):

* **Primary — channel C**, ``api.deepseek.com`` direct. The vendor's own API.
* **Fallback — channel A**, OpenRouter pinned to ``{"order": ["deepseek"],
  "allow_fallbacks": false}`` on the dated id ``deepseek/deepseek-v4-flash-0731``.

The stages themselves:

* ``researcher_assemble`` — per-topic; failure drops that topic.
* ``curator_topic_discovery`` — RUN-LEVEL; failure kills the whole day's run.
* ``resolve_actor_aliases`` — per-topic; failure drops that topic.

Agent's built-in transport retries are lines 1-2 of defence. This wrapper is
line 3: if the primary *finally* fails — a transport/API error after those
retries, OR a final output that is not schema-valid — it makes **exactly one**
attempt on the fallback channel and returns that instead.

Why a same-model channel fallback replaced the old cross-model one. Until
2026-08-24 the net was ``google/gemini-3-flash-preview``, chosen for ecosystem
independence: a DeepSeek-wide rate-limit event could not take it down with the
primary. That independence was real, and it was bought by serving a *different
model's* output into the pipeline whenever it fired — on 2026-07-14 it did, for
three Topic Packages. Since 0731 is reachable by two unrelated routes, the
fallback can now preserve both the model and the operating point. What it gives
up is vendor independence: if DeepSeek is down at the account level rather than
at one endpoint, both channels are down. That is a deliberate trade, recorded
here so it is not rediscovered as a surprise. (Channel B, Ollama Cloud, is the
documented last resort and is NOT in the chain — T2b/T2c found a 65 536 output
ceiling with 6 % margin on the largest real assemble call, no server-side JSON
enforcement at all, and a 6.2 % empty-body rate at medium.)

**Neither channel offers strict json_schema decoding**, which makes this
wrapper's schema check load-bearing rather than belt-and-braces. Both agents
run ``structured_output_mode="json_object"``; conformance is judged HERE,
against the *live* ``output_schema`` object (passed in) via the checker shared
with the qa_analyze wrapper
(:func:`src.qa_fallback.qa_output_is_schema_valid`), so the trigger can never
drift from the real production schema. An empty or unparseable body yields
``structured=None``, which that checker treats as invalid — so a runaway that
produces no content falls back rather than passing an empty payload downstream.

Invariants (identical to the writer/qa/editor fallbacks):

* **Loud, never silent.** A fallback emits a WARNING log line *and* a persisted
  marker — ``model_used`` + ``provider_used`` + ``<stage>_fallback_used`` — into
  the per-stage ``run_stage_log.jsonl`` row (the runner's ``_collect_agent_metrics``
  reads the marker attributes this wrapper exposes, keyed by the per-instance
  ``fallback_marker_key``). ``provider_used`` names the channel: ``deepseek_direct``
  for C, the OpenRouter-reported upstream for A. No code path silently
  substitutes a model.
* **Minimal mechanism.** A thin wrapper over two ordinary :class:`~src.agent.Agent`
  instances — no generic multi-model framework. It duck-types the members the
  agent-wrapper stages and the runner touch (``run``, ``name``, ``model``,
  ``temperature``, ``max_tokens``, ``reasoning``, ``last_cost_usd``,
  ``last_tokens``, ``reset_call_metrics``) so it drops in wherever the primary
  ``Agent`` was consumed, in both pipeline variants.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult
from src.qa_fallback import qa_output_is_schema_valid as output_is_schema_valid

logger = logging.getLogger(__name__)


class FlashStageWithFallback:
    """Primary channel-C agent with a one-shot channel-A fallback on the same
    model, parameterized by stage ``name`` + ``fallback_marker_key``.

    Drop-in for the ``agents[...]`` entry of any v4-flash-0731 schema-bearing
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
        """Run the primary; fall back to the other channel exactly once on
        final failure.

        Final failure = the primary raised after its built-in retries (a
        transport failure or a non-retryable 4xx from api.deepseek.com) OR
        returned an output that is not schema-valid — which, with no strict
        decoding on either channel, covers malformed JSON, a truncated body at
        the stage's ``max_tokens``, and an empty completion from a reasoning
        runaway. A transport failure on the *fallback* is allowed to propagate
        — that is the loud terminal failure, not a silent success.
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
            "%s FALLBACK: primary %s (channel %s) failed — %s. Making exactly "
            "one fallback attempt on %s (channel %s). (This is the channel "
            "fallback, not a silent substitution.)",
            self.name,
            self.primary.model,
            getattr(self.primary, "provider", "?"),
            failure_reason,
            self.fallback.model,
            getattr(self.fallback, "provider", "?"),
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
