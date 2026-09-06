"""Three-rung fallback ladder for ``researcher_hydrated_plan``.

TASK-PLANNER-SWAP (owner decision 2026-09-05) moves the hydrated planner from
``anthropic/claude-opus-4.6`` to DeepSeek V4-Pro-0813 at ``reasoning_effort:
low``, and pre-registers a ladder the existing two-rung wrapper cannot express:

    rung 1  channel C   api.deepseek.com alias ``deepseek-v4-pro`` (= 0813)
    rung 2  channel A   OpenRouter dated ``deepseek/deepseek-v4-pro-0813``,
                        pinned ``order:["deepseek"], allow_fallbacks:false``
    rung 3  incumbent   ``anthropic/claude-opus-4.6`` at the operating point it
                        ran in production until this swap — the safety net, so
                        a total DeepSeek outage degrades to the model this
                        stage shipped with rather than failing the run.

WHY THIS IS NOT :class:`~src.flash_stage_fallback.FlashStageWithFallback`
NESTED TWICE. Nesting type-checks and would run, but the outer wrapper
accounts cost by reading the returned ``AgentResult``. When the inner wrapper's
own primary fails *after billing tokens*, that spend lives in the inner's
``last_cost_usd`` and never reaches the outer's accumulator, so a
two-rung-deep failure silently under-reports cost in ``run_stage_log.jsonl``.
This class accumulates from every attempt, successful or not, which is the
whole reason it exists as its own small module rather than a clever
composition.

Invariants, identical to the writer/qa/editor/flash fallbacks:

* **Loud, never silent.** Every descent emits a WARNING and a persisted marker
  — ``model_used`` + ``provider_used`` + ``planner_fallback_used`` — into the
  per-stage ``run_stage_log.jsonl`` row, plus ``planner_fallback_rung`` naming
  which rung served, via ``extra_log_fields``. No path silently substitutes a
  model.
* **Failure is transport OR unusable output — judged the way the STAGE judges
  it.** Neither DeepSeek channel offers strict ``json_schema`` decoding
  (``require_parameters:true`` filters the vendor endpoint out of its own
  route), so conformance has to be judged here. It is judged by
  :func:`planner_output_is_usable`, which mirrors
  ``ResearcherHydratedPlanStage``'s own acceptance — **not** by a strict
  validation against ``RESEARCHER_PLAN_SCHEMA``.

  That distinction is the whole reason this helper exists, and it was found by
  the stage-isolated smoke rather than by reasoning: ``PLAN-INSTRUCTIONS.md``
  ends with *"Output only the JSON array"*, while ``RESEARCHER_PLAN_SCHEMA``
  declares a ``{"queries": [...]}`` envelope. Production reconciles the two in
  the stage, with ``_unwrap_list(parsed, "queries")``, which accepts EITHER
  shape. A strict envelope check therefore rejects the bare array the prompt
  actually asks for — which is what the first version of this module did, on
  every DeepSeek call, on every topic, while an Opus rung silently re-did work
  that had already succeeded. The incumbent passed only because strict
  ``json_schema`` decoding forces the envelope on it.

  An empty or truncated body yields ``structured=None``, which is unusable —
  a reasoning runaway descends rather than passing an empty plan downstream.
* **The last rung's transport failure propagates.** That is the loud terminal
  failure, not a silent success.
* **Minimal mechanism.** A thin wrapper over three ordinary
  :class:`~src.agent.Agent` instances, duck-typing exactly the members the
  agent-wrapper stages and the runner touch.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult
from src.agent_stages import _unwrap_list

logger = logging.getLogger(__name__)


def planner_output_is_usable(structured: Any) -> bool:
    """True iff the stage could turn ``structured`` into a usable query plan.

    Deliberately NOT a strict validation against ``RESEARCHER_PLAN_SCHEMA``.
    The acceptance test here has to be the one the consuming stage applies, or
    the ladder descends on output the pipeline would have used happily — see
    the module docstring for the bug that made this concrete.

    Accepted, exactly as ``ResearcherHydratedPlanStage`` accepts them:

    * ``{"queries": [{"query": ..., "language": ...}, ...]}`` — the schema
      envelope, which strict decoding produces;
    * ``[{"query": ..., "language": ...}, ...]`` — the bare array, which
      ``PLAN-INSTRUCTIONS.md`` explicitly asks the model to emit.

    Rejected: ``None`` (empty body / unparseable / truncated), anything that
    unwraps to an empty list, and any element missing a non-empty ``query`` or
    ``language``.

    The empty-list rejection is deliberate: the stage would write
    ``researcher_plan_queries=[]`` and the search stage would silently find
    nothing, which is a collapsed run wearing the costume of a successful one.
    The prompt's "minimum 10 queries" is NOT enforced here — a thin plan is a
    model-quality question that T5a already judged, not a decode failure, and
    descending on it would spend an Opus call to second-guess the eval.
    """
    if structured is None:
        return False
    if not isinstance(structured, (dict, list)):
        return False
    queries = _unwrap_list(structured, "queries")
    if not queries:
        return False
    return all(
        isinstance(q, dict)
        and isinstance(q.get("query"), str) and q["query"].strip()
        and isinstance(q.get("language"), str) and q["language"].strip()
        for q in queries
    )


class PlannerWithFallbackLadder:
    """``deepseek_direct`` primary, dated-OpenRouter rung, Opus-4.6 safety net.

    Drop-in for the ``agents["researcher_hydrated_plan"]`` entry:
    :class:`~src.agent_stages.ResearcherHydratedPlanStage` only calls
    ``.run(...)`` and reads the duck-typed introspection members, while the
    runner's metric collector reads ``last_cost_usd`` / ``last_tokens`` /
    ``reset_call_metrics`` plus the markers ``last_model_used`` /
    ``last_provider_used`` / ``last_fallback_used`` keyed under
    ``fallback_marker_key``, and merges ``extra_log_fields`` verbatim.
    """

    fallback_marker_key = "planner_fallback_used"

    def __init__(
        self,
        primary: Agent,
        fallback_dated: Agent,
        fallback_incumbent: Agent,
        output_schema: dict,
        name: str = "researcher_hydrated_plan",
    ) -> None:
        self.primary = primary
        self.fallback_dated = fallback_dated
        self.fallback_incumbent = fallback_incumbent
        self.output_schema = output_schema
        self.name = name

        # Display model — the intended primary. ``last_model_used`` records
        # what actually served the most recent call.
        self.model = primary.model
        self.temperature = getattr(primary, "temperature", None)
        self.max_tokens = getattr(primary, "max_tokens", None)
        self.reasoning = getattr(primary, "reasoning", None)

        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        self.last_model_used: str = ""
        self.last_provider_used: str = ""
        self.last_fallback_used: bool = False
        self.last_rung: str = ""

    # -- runner seam --------------------------------------------------------

    def reset_call_metrics(self) -> None:
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.last_model_used = ""
        self.last_provider_used = ""
        self.last_fallback_used = False
        self.last_rung = ""
        for agent in (self.primary, self.fallback_dated,
                      self.fallback_incumbent):
            agent.reset_call_metrics()

    @property
    def extra_log_fields(self) -> dict:
        """Which rung served. Present on every run, not only on a descent, so
        the steady state is visible in the log rather than inferred from the
        absence of a marker."""
        return {"planner_fallback_rung": self.last_rung}

    # -- internals ----------------------------------------------------------

    def _account(self, result: AgentResult) -> None:
        """Add one attempt's spend. Called for FAILED attempts too — a call
        that billed tokens and then returned an unusable body still cost
        money, and a cost line that hides it is worse than no cost line."""
        self.last_cost_usd += result.cost_usd
        self.last_tokens += result.tokens_used

    async def _attempt(
        self, agent: Agent, *args: Any, **kwargs: Any
    ) -> tuple[AgentResult | None, str | None]:
        try:
            result = await agent.run(*args, **kwargs)
        except AgentError as exc:
            return None, f"transport failure after retries ({exc})"
        self._account(result)
        if not planner_output_is_usable(result.structured):
            return None, ("unusable plan (empty body, truncation, malformed, "
                          "or no well-formed queries)")
        return result, None

    def _succeed(self, result: AgentResult, agent: Agent, rung: str,
                 used_fallback: bool) -> AgentResult:
        self.last_model_used = result.model or agent.model
        self.last_provider_used = result.provider
        self.last_fallback_used = used_fallback
        self.last_rung = rung
        return result

    # -- the ladder ---------------------------------------------------------

    async def run(self, *args: Any, **kwargs: Any) -> AgentResult:
        result, failure = await self._attempt(self.primary, *args, **kwargs)
        if failure is None:
            assert result is not None
            return self._succeed(result, self.primary, "primary_channel_c",
                                 used_fallback=False)

        logger.warning(
            "%s FALLBACK rung 2: primary %s (channel C, %s) failed — %s. "
            "Retrying the SAME WEIGHTS by the dated OpenRouter id %s. "
            "(Channel fallback, not a model substitution.)",
            self.name, self.primary.model,
            getattr(self.primary, "provider", "?"), failure,
            self.fallback_dated.model,
        )
        first_failure = failure

        result, failure = await self._attempt(
            self.fallback_dated, *args, **kwargs)
        if failure is None:
            assert result is not None
            logger.warning(
                "%s served by the dated-id rung: %s (provider=%s).",
                self.name, result.model or self.fallback_dated.model,
                result.provider or "unknown",
            )
            return self._succeed(result, self.fallback_dated,
                                 "fallback_dated_openrouter",
                                 used_fallback=True)

        logger.error(
            "%s FALLBACK rung 3: BOTH DeepSeek routes failed (C: %s | A: %s). "
            "Descending to the incumbent %s. This is a MODEL substitution — "
            "the plan will not come from the swapped-in planner.",
            self.name, first_failure, failure,
            self.fallback_incumbent.model,
        )

        # Rung 3 is the terminal rung: a transport failure here propagates.
        incumbent = await self.fallback_incumbent.run(*args, **kwargs)
        self._account(incumbent)
        logger.error(
            "%s served by the INCUMBENT safety net: %s (provider=%s), "
            "schema_valid=%s.",
            self.name, incumbent.model or self.fallback_incumbent.model,
            incumbent.provider or "unknown",
            planner_output_is_usable(incumbent.structured),
        )
        return self._succeed(incumbent, self.fallback_incumbent,
                             "fallback_incumbent_opus", used_fallback=True)
