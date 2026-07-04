"""Bias-stage split: extract -> union -> judge (TASK-BIAS-STAGE-SPLIT).

The single-call emit-then-retract bias prompt reproduced only ~51% of its
confirmed spans across identical cache-cold runs
(docs/BIAS-STAGE-MODEL-EVAL-2026-07.md; the instability lived in the retraction
decision, not the model). This composite replaces it with three calls whose
individual pieces are each more repeatable:

  Phase A  two GENEROUS candidate-extraction calls (deepseek-v4-pro, reasoning
           none, temperature 0.8 -> natural variance = coverage, fp8-pinned).
           Extractor instability is *harmless* — it only widens recall.
  union    DETERMINISTIC Python: verbatim-substring validate, merge both runs,
           dedup (identical + contained spans -> keep the shorter), stable order
           by article position, candidate_id 1..N, 2/2/1-2 agreement confidence.
  Phase B  one CLOSED per-candidate judgment call (Opus 4.6, reasoning none):
           yes/no over a fixed candidate list, explanation-before-verdict.

The wrapper is a thin composite over ordinary :class:`~src.agent.Agent`
instances — same pattern family as the fallback wrappers. It duck-types the
members ``BiasLanguageStage`` and the runner touch (``run``, ``name``,
``last_cost_usd``, ``last_tokens``, ``reset_call_metrics``) so it drops straight
into ``agents["bias_language"]`` with the stage code unchanged, and returns an
:class:`~src.agent.AgentResult` whose ``structured`` is the *same*
``{"language_bias": {"findings": [...]}, "reader_note": ...}`` shape the old
bias_detector agent produced — so the outer Bus slot + every downstream consumer
stay untouched. Loud per-stage metrics are surfaced via ``extra_log_fields``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.agent import Agent, AgentError, AgentResult

logger = logging.getLogger(__name__)

# User turns for the three calls (the task briefs live in the agents' prompt
# files; these are the per-run messages). Kept as module constants so the unit
# tests can assert the exact request bodies.
EXTRACT_MESSAGE = (
    "List every candidate bias passage in this article. Cast a wide net — a "
    "separate judge evaluates each candidate afterwards."
)
JUDGE_MESSAGE = (
    "Judge each numbered candidate passage in context and decide whether it "
    "constitutes linguistic bias in the article's own voice."
)


# --------------------------------------------------------------------------- #
# Deterministic union (pure function — no LLM, no I/O)
# --------------------------------------------------------------------------- #
def build_union(
    run1: list[dict], run2: list[dict], article_body: str
) -> tuple[list[dict], dict]:
    """Merge two extractor candidate lists into one ordered, de-duplicated,
    confidence-tagged candidate list.

    Rules (all deterministic):
    - every ``excerpt`` must be an exact substring of ``article_body`` (invalid
      spans are dropped and counted);
    - identical spans across runs collapse; a span fully contained in a longer
      span collapses into the shorter (minimal) span — the judge only ever sees
      minimal spans;
    - a kept span's ``extraction_confidence`` is ``"2/2"`` when *either run*
      contributed a span at that location (i.e. some distinct excerpt containing
      it came from each run), else ``"1/2"``;
    - order is by first position in ``article_body`` (excerpt string as
      tiebreak); ``candidate_id`` is 1..N in that order.

    Returns ``(candidates, stats)`` where each candidate is
    ``{"candidate_id", "excerpt", "issue_hint", "extraction_confidence"}``.
    """
    invalid_dropped = 0
    # distinct excerpt -> {"runs": set[int], "hint": str}
    distinct: dict[str, dict] = {}
    for run_idx, run in ((1, run1), (2, run2)):
        for item in run or []:
            if not isinstance(item, dict):
                continue
            excerpt = item.get("excerpt")
            if not isinstance(excerpt, str) or excerpt == "":
                invalid_dropped += 1
                continue
            if excerpt not in article_body:  # verbatim-substring validation
                invalid_dropped += 1
                continue
            hint = item.get("issue_hint")
            hint = hint if isinstance(hint, str) else ""
            rec = distinct.get(excerpt)
            if rec is None:
                distinct[excerpt] = {"runs": {run_idx}, "hint": hint}
            else:
                rec["runs"].add(run_idx)
                # first hint seen (run1 before run2) wins — deterministic.
                if not rec["hint"]:
                    rec["hint"] = hint

    excerpts = list(distinct.keys())
    # A span is KEPT iff it is minimal: no *other* distinct span is a strictly
    # shorter substring of it.
    kept: list[str] = []
    for e in excerpts:
        minimal = True
        for f in excerpts:
            if f != e and len(f) < len(e) and f in e:
                minimal = False
                break
        if minimal:
            kept.append(e)

    candidates: list[dict] = []
    for k in kept:
        # runs(K) = union of runs of every distinct span that contains K
        # (K itself included) — agreement propagates from longer spans down to
        # the minimal one they collapse into.
        runs: set[int] = set()
        for d, rec in distinct.items():
            if k in d:  # k is a substring of d (or equal)
                runs |= rec["runs"]
        confidence = "2/2" if runs >= {1, 2} else "1/2"
        candidates.append({
            "excerpt": k,
            "issue_hint": distinct[k]["hint"],
            "extraction_confidence": confidence,
            "_pos": article_body.index(k),
        })

    candidates.sort(key=lambda c: (c["_pos"], c["excerpt"]))
    for i, c in enumerate(candidates, start=1):
        c["candidate_id"] = i
        del c["_pos"]

    stats = {
        "extract_run1_raw": len(run1 or []),
        "extract_run2_raw": len(run2 or []),
        "invalid_span_drops": invalid_dropped,
        "union_size": len(candidates),
    }
    return candidates, stats


# --------------------------------------------------------------------------- #
# Mapping judgments back to the existing outer contract
# --------------------------------------------------------------------------- #
def map_to_findings(
    candidates: list[dict], judgments: list[dict]
) -> list[dict]:
    """Turn confirmed judgments (``is_bias=true``) into entries in the existing
    ``bias_language_findings`` slot shape, plus the additive
    ``extraction_confidence`` field.

    The ``excerpt`` is taken from the *candidate* (verbatim, Python-owned
    reference data), never from the judge output; the judge contributes only the
    verdict fields (``issue``, ``explanation``) — originary output only.
    """
    by_id = {c["candidate_id"]: c for c in candidates}
    findings: list[dict] = []
    for j in judgments or []:
        if not isinstance(j, dict) or j.get("is_bias") is not True:
            continue
        cid = j.get("candidate_id")
        cand = by_id.get(cid)
        if cand is None:
            continue  # judge referenced an id outside the list — ignore
        issue = j.get("issue")
        if not isinstance(issue, str) or not issue:
            issue = cand.get("issue_hint", "")  # confirmed but null issue
        findings.append({
            "excerpt": cand["excerpt"],
            "issue": issue,
            "explanation": j.get("explanation", "") or "",
            "finding_valid": True,
            "extraction_confidence": cand["extraction_confidence"],
        })
    return findings


class BiasComposite:
    """extract(x2) -> union -> judge, presented as a single bias_language agent.

    Drop-in for ``agents["bias_language"]``: :class:`BiasLanguageStage` calls only
    ``.run(message, context={"article_body", "bias_card"})`` and reads
    ``language_bias.findings`` + ``reader_note`` off the returned result. The
    runner reads ``last_cost_usd`` / ``last_tokens`` / ``reset_call_metrics``
    plus, via ``extra_log_fields``, the loud per-stage metrics.
    """

    def __init__(
        self,
        extractor: Agent,
        judge: Agent,
        name: str = "bias_language",
    ) -> None:
        self.extractor = extractor
        self.judge = judge
        self.name = name
        self.model = f"bias-composite({extractor.model} x2 -> {judge.model})"
        # The composite enforces structured output at both sub-agents; its
        # authoritative decision schema is the judge's (the confirmed verdict).
        # Exposed so create_agents' "every agent wires a schema" contract holds.
        self.output_schema = judge.output_schema
        # runner accumulators (summed across all three calls).
        self.last_cost_usd: float = 0.0
        self.last_tokens: int = 0
        # Loud, per-call metrics surfaced into run_stage_log.jsonl.
        self.extra_log_fields: dict = {}

    def reset_call_metrics(self) -> None:
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.extra_log_fields = {}
        self.extractor.reset_call_metrics()
        self.judge.reset_call_metrics()

    def _account(self, result: AgentResult) -> None:
        self.last_cost_usd += result.cost_usd
        self.last_tokens += result.tokens_used

    async def run(
        self, message: str | None = None, context: dict | None = None, **kwargs: Any
    ) -> AgentResult:
        context = context or {}
        article_body = context.get("article_body", "") or ""

        # --- Phase A: two generous extraction passes (concurrent) ------------
        async def _extract() -> AgentResult | None:
            try:
                return await self.extractor.run(
                    EXTRACT_MESSAGE, context={"article_body": article_body}
                )
            except AgentError as exc:
                logger.warning("bias extractor pass failed: %s", exc)
                return None

        r1, r2 = await asyncio.gather(_extract(), _extract())
        if r1 is None and r2 is None:
            raise AgentError("bias extraction failed on both passes")
        ext_provider = ""
        run1 = run2 = []
        for res, holder in ((r1, "run1"), (r2, "run2")):
            if res is None:
                continue
            self._account(res)
            ext_provider = ext_provider or res.provider
            cands = (res.structured or {}).get("candidates") or []
            if holder == "run1":
                run1 = cands
            else:
                run2 = cands

        candidates, stats = build_union(run1, run2, article_body)

        # --- Phase B: closed judgment (skip on empty candidate list) ---------
        judge_skipped = not candidates
        judge_provider = ""
        judgments: list[dict] = []
        reader_note = ""
        if not judge_skipped:
            judge_input = [
                {
                    "candidate_id": c["candidate_id"],
                    "excerpt": c["excerpt"],
                    "issue_hint": c["issue_hint"],
                }
                for c in candidates
            ]
            jres = await self.judge.run(
                JUDGE_MESSAGE,
                context={"article_body": article_body, "candidates": judge_input},
            )
            self._account(jres)
            judge_provider = jres.provider
            parsed = jres.structured or {}
            judgments = parsed.get("judgments") or []
            reader_note = parsed.get("reader_note", "") or ""

        findings = map_to_findings(candidates, judgments)

        # --- loud metrics ----------------------------------------------------
        self.extra_log_fields = {
            "extractor_model": self.extractor.model,
            "extractor_provider": ext_provider,
            "judge_model": self.judge.model,
            "judge_provider": judge_provider,
            "extract_run1_raw": stats["extract_run1_raw"],
            "extract_run2_raw": stats["extract_run2_raw"],
            "invalid_span_drops": stats["invalid_span_drops"],
            "union_size": stats["union_size"],
            "judge_skipped": judge_skipped,
            "confirmed_count": len(findings),
        }
        logger.info(
            "bias composite: extracted %d/%d (raw), union=%d, invalid_drops=%d, "
            "confirmed=%d%s",
            stats["extract_run1_raw"], stats["extract_run2_raw"],
            stats["union_size"], stats["invalid_span_drops"], len(findings),
            " (judge skipped: empty candidates)" if judge_skipped else "",
        )

        structured = {
            "language_bias": {"findings": findings},
            "reader_note": reader_note,
        }
        return AgentResult(
            content=json.dumps(structured, ensure_ascii=False),
            structured=structured,
            tokens_used=self.last_tokens,
            cost_usd=self.last_cost_usd,
            model=self.model,
            provider=judge_provider or ext_provider,
        )
