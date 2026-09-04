"""Perspective draft->verify chain + fallback ladder (TASK-PERSPECTIVE-SWAP).

The perspective stage moves from a single Sonnet-5 call to a two-call chain:

    z-ai/glm-5.3 (draft)  ->  z-ai/glm-5.3-flash (verify)  ->  bus

The T4 evaluation series made this operating point binding. Phase A established
each model's endpoint behaviour and operating point (``scratch/eval/
t4-perspective/REPORT.md``: glm-5.3 at reasoning ``high`` with temperature and
top_p OMITTED, glm-5.3-flash at reasoning ``high`` with the vendor "Recommended
Settings" temp 1.0 / top_p 0.95, both ``json_object`` because the Z.AI endpoint
exposes no strict ``json_schema``, both pinned to the ``z-ai`` provider).
T4C established that the glm-5.3 draft ALONE is non-inferior to Sonnet-5 at
n=15 — which is what makes the verify pass droppable in the ladder below
without failing the run. T4E then compared the two verify architectures over
those same 15 dossiers and picked this one: cheap verifier over strong draft
beats strong verifier over cheap draft, because breadth is set by the draft and
no amount of checking puts back a position the draft never had (arm B's
verifier cut misfilings 16->5, three times as much, and still landed level
overall on a D1 deficit of -0.556). On the winning arm the verify pass bought
D4 fidelity +0.389 and cut confirmed fabrications 2 -> 1 for 4.6% added cost.

Cost: ~$0.38/run against the champion's ~$1.00.

**The chain is a wrapper, not a stage rewrite.** Like
:class:`~src.perspective_fallback.PerspectiveWithFallback` before it, this class
duck-types the handful of members
:class:`~src.agent_stages.PerspectiveStage` and the runner touch (``run``,
``name``, ``last_cost_usd``, ``last_tokens``, ``reset_call_metrics``, the
fallback markers, ``extra_log_fields``), so it drops into
``agents["perspective"]`` and PerspectiveStage itself is untouched. The stage
still makes one ``.run()`` call and still writes the same two bus slots; the
verify pass emits the same object shape, so no schema or slot changes.

**The fallback ladder is pre-registered** (owner brief, 2026-09-04) and has two
rungs, which fire independently:

(a) **Draft failure -> Sonnet-5, verify SKIPPED.** If the glm-5.3 draft fails,
    the whole stage falls back to a single full Sonnet-5 call at the champion
    operating point — the incumbent as it shipped. Its output is NOT verified:
    the verify prompt exists to correct glm-5.3's attribution errors, and
    Sonnet-5 is the configuration this stage ran in production for two months.
    Marker: ``perspective_fallback_used=true``.

    A SCHEMA-invalid draft first gets exactly ONE logged repair attempt (owner
    refinement, 2026-09-04): a trivially repairable JSON glitch must not
    escalate to the $1.00 model when a ~$0.12 re-roll usually clears it. A
    TRANSPORT failure escalates immediately — Agent's retry loop has already
    exhausted its attempts and ``allow_fallbacks: false`` leaves no other host,
    so another identical call is latency without a hypothesis.

    *Interpretation, stated because the brief's wording is narrower than the
    code:* the brief says "draft transport failure". This implementation also
    treats a schema-INVALID draft as a draft failure. A draft that does not
    parse is not a draft — there would be nothing for verify to check and
    nothing to ship — and this matches both rung (b), which the brief does
    define as "transport or schema", and the incumbent
    ``PerspectiveWithFallback``, which has always triggered on either. The
    narrower reading would leave the stage with no output at all on a
    schema-invalid draft, which cannot be what the ladder is for.

(b) **Verify failure -> ship the DRAFT.** If the verify pass fails (transport,
    or schema-invalid output) it gets exactly ONE logged repair attempt; if that
    also fails the DRAFT ships unverified. T4C is the licence for this: the
    unverified glm-5.3 draft is non-inferior to Sonnet-5 at n=15, so a broken
    filter must never fail a run. Marker: ``perspective_verify_skipped=true``
    plus a machine-readable ``perspective_verify_skip_reason``.

Both rungs are **loud, never silent**: a WARNING log line plus persisted markers
in the per-stage ``run_stage_log.jsonl`` row. In addition, every successful
verify records what it actually did — references removed, misfilings corrected,
clusters dropped — the same mechanics the T4E report gates on, so a verify pass
that silently becomes a no-op in production is visible in the run log rather
than discovered in the next evaluation.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable

from src.agent import Agent, AgentError, AgentResult
# Generic over the schema handed in (it reads the schema object, not QA-specific
# keys), so the validity trigger here can never drift from PERSPECTIVE_SCHEMA.
from src.qa_fallback import qa_output_is_schema_valid as output_is_schema_valid

logger = logging.getLogger(__name__)

# The three canonical-actor sub-lists a cluster can file an actor under. Order
# matters only for reporting; membership is what the misfiling count reads.
_SUBLISTS = ("stated", "reported", "mentioned")

# The user-turn message the verify call carries. Byte-identical to the message
# the T4D/T4E harness used (`scratch/eval/t4d-flash-multipass/prompts_pass.py`),
# so the production verify call reproduces the evaluated one exactly: same
# system prompt, same instructions, same context object plus `draft`, same
# closing line.
VERIFY_MESSAGE = (
    "Complete the task described in your instructions using the context above."
)


def _refs(obj: Any) -> tuple[set[tuple[str, str]], set[str]]:
    """Return ``({(sub_list, actor_id)}, {source_id})`` cited by a perspective
    object. Tolerant of malformed shapes — this is measurement, not validation,
    and it must never be the thing that raises inside a successful run."""
    actors: set[tuple[str, str]] = set()
    sources: set[str] = set()
    if not isinstance(obj, dict):
        return actors, sources
    for cluster in obj.get("position_clusters") or []:
        if not isinstance(cluster, dict):
            continue
        for sub in _SUBLISTS:
            for actor_id in cluster.get(sub) or []:
                if isinstance(actor_id, str):
                    actors.add((sub, actor_id))
        for src_id in cluster.get("source_ids") or []:
            if isinstance(src_id, str):
                sources.add(src_id)
    return actors, sources


def _misfiled_count(obj: Any, context: dict) -> int | None:
    """How many actor references sit in a sub-list whose pool does not hold them.

    This is the T4E "misfiled" measure: the id exists somewhere in the dossier's
    three pools but is filed under the wrong one. Distinct from a NONEXISTENT
    id, which the verify prompt removes outright. Returns ``None`` when the
    context does not carry all three pools, so an absent measurement is never
    reported as a zero.
    """
    pools: dict[str, set[str]] = {}
    for sub in _SUBLISTS:
        entries = context.get(f"canonical_actors_{sub}")
        if entries is None:
            return None
        pools[sub] = {
            e.get("id") for e in entries if isinstance(e, dict) and e.get("id")
        }
    everywhere: set[str] = set().union(*pools.values()) if pools else set()
    actors, _ = _refs(obj)
    return sum(
        1 for sub, aid in actors if aid in everywhere and aid not in pools[sub]
    )


def _n_clusters(obj: Any) -> int:
    if not isinstance(obj, dict):
        return 0
    return len(obj.get("position_clusters") or [])


def verify_work_report(draft: Any, verified: Any, context: dict) -> dict:
    """What the verify pass actually changed, as loud log fields.

    Mirrors the mechanics table in the T4E report so a production run is
    directly comparable to the evaluation: on the winning arm the verify pass
    removed 18 actor references and added 0 across 15 topics, changed no cluster
    counts, and cut misfilings 6 -> 4. A production row showing zeros everywhere
    means the pass has become a no-op — which the evaluation would not catch,
    but this field will.
    """
    d_actors, d_sources = _refs(draft)
    v_actors, v_sources = _refs(verified)
    mis_before = _misfiled_count(draft, context)
    mis_after = _misfiled_count(verified, context)
    return {
        "perspective_verify_actor_refs_removed": len(d_actors - v_actors),
        "perspective_verify_actor_refs_added": len(v_actors - d_actors),
        "perspective_verify_source_refs_removed": len(d_sources - v_sources),
        "perspective_verify_source_refs_added": len(v_sources - d_sources),
        "perspective_verify_clusters_before": _n_clusters(draft),
        "perspective_verify_clusters_after": _n_clusters(verified),
        "perspective_verify_misfiled_before": mis_before,
        "perspective_verify_misfiled_after": mis_after,
        "perspective_verify_misfiled_corrected": (
            None
            if mis_before is None or mis_after is None
            else mis_before - mis_after
        ),
    }


class PerspectiveDraftVerifyChain:
    """glm-5.3 draft -> glm-5.3-flash verify, with the pre-registered ladder.

    Drop-in for ``agents["perspective"]``: PerspectiveStage only calls
    ``.run(...)``; the runner's ``_collect_agent_metrics`` reads
    ``last_cost_usd`` / ``last_tokens`` / ``reset_call_metrics``, the served
    ``last_model_used`` / ``last_provider_used``, the fallback marker keyed by
    ``fallback_marker_key``, and merges ``extra_log_fields`` verbatim.
    """

    # Same key the incumbent wrapper used, so the swap does not rename a field
    # the daily cost/health reporting already reads.
    fallback_marker_key = "perspective_fallback_used"

    def __init__(
        self,
        draft: Agent,
        verify: Agent,
        fallback: Agent,
        output_schema: dict,
        name: str = "perspective",
    ) -> None:
        self.draft = draft
        self.verify = verify
        self.fallback = fallback
        self.output_schema = output_schema
        self.name = name
        # Display model — the intended primary of the chain. `last_model_used`
        # records what actually served the object that reached the bus.
        self.model = draft.model
        # Mirror the draft's decode params so introspection of the perspective
        # agent (metrics/labels) sees the primary configuration.
        self.temperature = getattr(draft, "temperature", None)
        self.max_tokens = getattr(draft, "max_tokens", None)
        self.reasoning = getattr(draft, "reasoning", None)

        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        self.last_model_used: str = ""
        self.last_provider_used: str = ""
        self.last_fallback_used: bool = False
        self.last_verify_skipped: bool = False
        self.extra_log_fields: dict[str, Any] = {}

    # -- runner surface ----------------------------------------------------
    def reset_call_metrics(self) -> None:
        """Zero per-stage accumulators + markers before each stage execution, so
        every marker describes exactly one perspective call."""
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.last_model_used = ""
        self.last_provider_used = ""
        self.last_fallback_used = False
        self.last_verify_skipped = False
        self.extra_log_fields = {}
        for agent in (self.draft, self.verify, self.fallback):
            agent.reset_call_metrics()

    def _account(self, result: AgentResult) -> None:
        """Sum cost/tokens across every call the chain made, so a two-call run
        reports what it actually spent rather than the last leg only."""
        self.last_cost_usd += result.cost_usd
        self.last_tokens += result.tokens_used

    def _served(self, result: AgentResult, agent: Agent) -> None:
        self.last_model_used = result.model or agent.model
        self.last_provider_used = result.provider

    # -- the chain ---------------------------------------------------------
    async def _attempt(
        self, agent: Agent, *args: Any, **kwargs: Any
    ) -> tuple[AgentResult | None, str | None, str | None]:
        """One call. Returns ``(result, failure_reason, failure_kind)``.

        ``failure_kind`` is ``"transport"`` or ``"schema"``, and the caller
        treats them differently: a transport failure has ALREADY exhausted
        Agent's built-in retries, so repeating the call adds nothing, while a
        schema failure may be a one-off malformed body worth re-rolling once.

        A result whose structured output is not schema-valid IS a failure —
        including the Z.AI empty-body mode observed during T4D/T4E, where the
        transport reports success with a zero-length body and
        ``finish_reason: "error"``. Cost is accounted either way: a failed call
        still costs money and must appear in the run's total.
        """
        try:
            result = await agent.run(*args, **kwargs)
        except AgentError as exc:
            return None, f"transport failure after retries ({exc})", "transport"
        self._account(result)
        if not output_is_schema_valid(result.structured, self.output_schema):
            return (
                None,
                "output not schema-valid (empty body, truncation or malformed)",
                "schema",
            )
        return result, None, None

    async def run(
        self, message: str = "", context: dict | None = None, **kwargs: Any
    ) -> AgentResult:
        """Draft, then verify, applying the pre-registered ladder on failure."""
        context = context or {}

        # --- rung (a): the draft ------------------------------------------
        draft_result, draft_failure, draft_kind = await self._attempt(
            self.draft, message, context=context, **kwargs
        )
        draft_attempts = 1

        # A SCHEMA-invalid draft gets exactly one logged repair before the
        # ladder escalates (owner refinement, 2026-09-04). The rationale is a
        # cost one: a trivially repairable JSON glitch — the Z.AI empty body is
        # the observed instance, and a probe minutes later on the same input
        # returned clean JSON during T4D — must not escalate the whole stage to
        # the $1.00 model when a ~$0.12 re-roll usually clears it. This mirrors
        # rung (b)'s repair semantics exactly.
        #
        # A TRANSPORT failure gets no repair here and escalates immediately:
        # Agent's own retry loop has already exhausted its attempts against this
        # endpoint, and `allow_fallbacks: false` means there is no other host to
        # try, so a fourth identical call is latency without a hypothesis.
        if draft_failure is not None and draft_kind == "schema":
            logger.warning(
                "perspective DRAFT repair: draft %s returned %s. Making exactly "
                "one repair attempt before escalating to %s.",
                self.draft.model,
                draft_failure,
                self.fallback.model,
            )
            draft_result, draft_failure, draft_kind = await self._attempt(
                self.draft, message, context=context, **kwargs
            )
            draft_attempts = 2

        if draft_failure is not None:
            logger.warning(
                "perspective FALLBACK: draft %s failed — %s. Making exactly one "
                "fallback attempt on %s, and SKIPPING the verify pass (the "
                "fallback is the incumbent configuration as it shipped). "
                "(This is the model fallback, not a silent substitution.)",
                self.draft.model,
                draft_failure,
                self.fallback.model,
            )
            fb = await self.fallback.run(message, context=context, **kwargs)
            self._account(fb)
            self._served(fb, self.fallback)
            self.last_fallback_used = True
            self.last_verify_skipped = True
            self.extra_log_fields = {
                "perspective_verify_skipped": True,
                "perspective_verify_skip_reason": "sonnet_fallback_not_verified",
                "perspective_draft_failure_reason": draft_failure,
                "perspective_draft_failure_kind": draft_kind,
                "perspective_draft_attempts": draft_attempts,
            }
            logger.warning(
                "perspective FALLBACK complete: served by %s (provider=%s), "
                "schema_valid=%s, verify skipped.",
                self.last_model_used,
                fb.provider or "unknown",
                output_is_schema_valid(fb.structured, self.output_schema),
            )
            return fb

        assert draft_result is not None  # guaranteed: failure_reason was None
        draft_obj = draft_result.structured
        self._served(draft_result, self.draft)

        # --- rung (b): the verify pass ------------------------------------
        # The draft goes into the context under `draft`, exactly as the T4
        # harness passed it. Deep-copied so the verify call cannot mutate the
        # dossier object the stage built.
        verify_context = copy.deepcopy(dict(context))
        verify_context["draft"] = draft_obj

        verify_failure: str | None = None
        for attempt in (1, 2):        # one call + exactly one logged repair
            verify_result, verify_failure, _ = await self._attempt(
                self.verify, VERIFY_MESSAGE, context=verify_context, **kwargs
            )
            if verify_failure is None:
                assert verify_result is not None
                self._served(verify_result, self.verify)
                self.last_fallback_used = False
                self.last_verify_skipped = False
                self.extra_log_fields = {
                    "perspective_draft_model": draft_result.model or self.draft.model,
                    "perspective_draft_provider": draft_result.provider or "unknown",
                    "perspective_draft_attempts": draft_attempts,
                    "perspective_verify_model": (
                        verify_result.model or self.verify.model
                    ),
                    "perspective_verify_provider": (
                        verify_result.provider or "unknown"
                    ),
                    "perspective_verify_skipped": False,
                    "perspective_verify_attempts": attempt,
                    **verify_work_report(draft_obj, verify_result.structured, context),
                }
                return verify_result
            if attempt == 1:
                logger.warning(
                    "perspective VERIFY repair: verify %s failed — %s. Making "
                    "exactly one repair attempt.",
                    self.verify.model,
                    verify_failure,
                )

        # Both verify attempts failed. Ship the DRAFT: T4C established the
        # unverified glm-5.3 draft is non-inferior to Sonnet-5 at n=15, so the
        # filter failing must never fail the run.
        logger.warning(
            "perspective VERIFY SKIPPED: verify %s failed twice — %s. Shipping "
            "the UNVERIFIED %s draft (non-inferior alone, T4C n=15). The run "
            "continues; this is loud, not silent.",
            self.verify.model,
            verify_failure,
            self.draft.model,
        )
        self.last_fallback_used = False
        self.last_verify_skipped = True
        self.extra_log_fields = {
            "perspective_draft_model": draft_result.model or self.draft.model,
            "perspective_draft_provider": draft_result.provider or "unknown",
            "perspective_draft_attempts": draft_attempts,
            "perspective_verify_skipped": True,
            "perspective_verify_skip_reason": verify_failure,
            "perspective_verify_attempts": 2,
        }
        return draft_result
