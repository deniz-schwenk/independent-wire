"""Bias-stage split: extract -> union -> judge (TASK-BIAS-STAGE-SPLIT).

The single-call emit-then-retract bias prompt reproduced only ~51% of its
confirmed spans across identical cache-cold runs
(docs/BIAS-STAGE-MODEL-EVAL-2026-07.md; the instability lived in the retraction
decision, not the model). This composite replaces it with three calls whose
individual pieces are each more repeatable:

  Phase A  two GENEROUS candidate-extraction calls (deepseek-v4-pro, reasoning
           none, temperature 0.8 -> natural variance = coverage, fp8-pinned).
           Extractor instability is *harmless* — it only widens recall.
  union    DETERMINISTIC Python: verbatim-substring validate, then
           POSITION-ANCHORED merge — resolve each span to its character
           interval(s) and merge only spans that overlap at the same location
           (nesting or partial overlap); multi-occurrence spans are ambiguous
           and never merge (a negation stays distinct from an affirmation).
           Present the shortest variant, keep the variant list, stable order by
           article position, candidate_id 1..N, 2/2-vs-1/2 agreement confidence.
  Phase B  one CLOSED per-candidate judgment call (Opus 4.6, reasoning none):
           a TERNARY verdict (confirmed / borderline / cleared) over a fixed
           candidate list, explanation-before-verdict (TASK-BIAS-TIER-MAPPING).

The wrapper is a thin composite over ordinary :class:`~src.agent.Agent`
instances — same pattern family as the fallback wrappers. It duck-types the
members ``BiasLanguageStage`` and the runner touch (``run``, ``name``,
``last_cost_usd``, ``last_tokens``, ``reset_call_metrics``) so it drops straight
into ``agents["bias_language"]`` with the stage code unchanged, and returns an
:class:`~src.agent.AgentResult` whose ``structured`` is
``{"language_bias": {"findings": [...], "borderline": [...]}, "reader_note": ...}``:
``findings`` is byte-for-byte the shape the old bias_detector agent produced (so
the ``bias_language_findings`` slot + every downstream consumer stay untouched),
and ``borderline`` feeds the additive ``bias_borderline_candidates`` slot.
``cleared`` verdicts are dropped (counted in metrics). Loud per-stage metrics are
surfaced via ``extra_log_fields``.
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

# Extractor cap: how many candidates from EACH extraction pass are carried into
# the union (TASK-BIAS-DEDUP-FIX lowered this 25 -> 18 for the ≤ $0.06/article
# cost target). The extractor prompt is authoritative and untouched — the cap is
# enforced here deterministically, on the raw emission order (the prompt asks the
# model to keep the most clearly loaded ones, so the head of the list is best).
EXTRACTOR_CANDIDATE_CAP = 18


# --------------------------------------------------------------------------- #
# Deterministic union (pure function — no LLM, no I/O)
# --------------------------------------------------------------------------- #
def _occurrences(excerpt: str, body: str) -> list[tuple[int, int]]:
    """All ``[start, end)`` character intervals where ``excerpt`` occurs in
    ``body`` (overlap-aware). Every excerpt reaching this point is already
    validated as a substring, so the list is non-empty."""
    spans: list[tuple[int, int]] = []
    i = body.find(excerpt)
    while i != -1:
        spans.append((i, i + len(excerpt)))
        i = body.find(excerpt, i + 1)
    return spans


def build_union(
    run1: list[dict],
    run2: list[dict],
    article_body: str,
    cap: int = EXTRACTOR_CANDIDATE_CAP,
) -> tuple[list[dict], dict]:
    """Merge two extractor candidate lists into one ordered, position-merged,
    confidence-tagged candidate list.

    Rules (all deterministic):
    - each run is truncated to the first ``cap`` items (extractor cost cap);
    - every ``excerpt`` must be an exact substring of ``article_body`` (invalid
      spans are dropped and counted);
    - **position-anchored merge** (TASK-BIAS-DEDUP-FIX): each validated excerpt
      is resolved to its character interval(s) in ``article_body``. Two
      candidates merge into one *family* only when their intervals overlap **at
      the same location** — nesting or partial overlap. No string-similarity
      merging: a span variant of the same finding collapses, but two unrelated
      occurrences of the same words never do (a negation stays distinct from an
      affirmation). An excerpt that occurs **more than once** is location-
      ambiguous and never merges (conservative by design);
    - a family presents its **shortest** variant to the judge (tie: earliest
      position, then string); the full variant list is kept in ``variants``
      metadata (never shown to the judge, never rendered);
    - a family's ``extraction_confidence`` is ``"2/2"`` when its variants,
      together, were contributed by *both* runs (the location was independently
      flagged twice — the join / max over its variants), else ``"1/2"``;
    - order is by the representative's position in ``article_body`` (excerpt
      string as tiebreak); ``candidate_id`` is 1..N in that order.

    Returns ``(candidates, stats)`` where each candidate is ``{"candidate_id",
    "excerpt", "issue_hint", "extraction_confidence", "variants"}``.
    """
    invalid_dropped = 0
    # distinct excerpt -> {"runs": set[int], "hint": str}
    distinct: dict[str, dict] = {}
    for run_idx, run in ((1, run1), (2, run2)):
        for item in (run or [])[:cap]:
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
    # Resolve each distinct excerpt to its occurrence interval(s). Exactly-once
    # excerpts have a definite location; multi-occurrence excerpts are
    # location-ambiguous and are excluded from any merge.
    intervals: dict[str, list[tuple[int, int]]] = {
        e: _occurrences(e, article_body) for e in excerpts
    }
    unambiguous = {e: intervals[e][0] for e in excerpts if len(intervals[e]) == 1}

    # Union-find over the unambiguous excerpts: merge a pair iff their single
    # intervals overlap (nesting or partial overlap). Merging is transitive
    # (a chain A–B, B–C puts A,B,C in one family).
    parent: dict[str, str] = {e: e for e in excerpts}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    u_keys = list(unambiguous.keys())
    for i in range(len(u_keys)):
        sa, ea = unambiguous[u_keys[i]]
        for j in range(i + 1, len(u_keys)):
            sb, eb = unambiguous[u_keys[j]]
            if sa < eb and sb < ea:  # half-open interval overlap
                union(u_keys[i], u_keys[j])

    # Group excerpts into merge families.
    families: dict[str, list[str]] = {}
    for e in excerpts:
        families.setdefault(find(e), []).append(e)

    def _pos_of(e: str) -> int:
        return intervals[e][0][0]

    candidates: list[dict] = []
    for members in families.values():
        # representative = shortest variant (tie: earliest position, then string)
        rep = min(members, key=lambda m: (len(m), _pos_of(m), m))
        variants = sorted(members, key=lambda m: (_pos_of(m), len(m), m))
        # confidence = join over variants: 2/2 iff both runs contributed to the
        # family (the location was flagged independently by each pass).
        family_runs: set[int] = set()
        for m in members:
            family_runs |= distinct[m]["runs"]
        confidence = "2/2" if family_runs >= {1, 2} else "1/2"
        candidates.append({
            "excerpt": rep,
            "issue_hint": distinct[rep]["hint"],
            "extraction_confidence": confidence,
            "variants": variants,
            "_pos": _pos_of(rep),
        })

    candidates.sort(key=lambda c: (c["_pos"], c["excerpt"]))
    for i, c in enumerate(candidates, start=1):
        c["candidate_id"] = i
        del c["_pos"]

    stats = {
        "extract_run1_raw": len(run1 or []),
        "extract_run2_raw": len(run2 or []),
        "extractor_cap": cap,
        "invalid_span_drops": invalid_dropped,
        "distinct_excerpts": len(distinct),   # valid spans before position merge
        "union_size": len(candidates),        # families after position merge
    }
    return candidates, stats


# --------------------------------------------------------------------------- #
# Mapping judgments back to the existing outer contract
# --------------------------------------------------------------------------- #
def _resolved_issue(judgment: dict, candidate: dict) -> str:
    """The confirmed/borderline ``issue`` string, falling back to the
    extractor's ``issue_hint`` when the judge left it null/empty."""
    issue = judgment.get("issue")
    if not isinstance(issue, str) or not issue:
        return candidate.get("issue_hint", "")
    return issue


def map_to_findings(
    candidates: list[dict], judgments: list[dict]
) -> list[dict]:
    """Turn ``confirmed`` judgments into entries in the existing
    ``bias_language_findings`` slot shape, plus the additive
    ``extraction_confidence`` field — byte-for-byte the shape today's
    consumers expect.

    The ``excerpt`` is taken from the *candidate* (verbatim, Python-owned
    reference data), never from the judge output; the judge contributes only the
    verdict fields (``issue``, ``explanation``) — originary output only.
    """
    by_id = {c["candidate_id"]: c for c in candidates}
    findings: list[dict] = []
    for j in judgments or []:
        if not isinstance(j, dict) or j.get("verdict") != "confirmed":
            continue
        cand = by_id.get(j.get("candidate_id"))
        if cand is None:
            continue  # judge referenced an id outside the list — ignore
        findings.append({
            "excerpt": cand["excerpt"],
            "issue": _resolved_issue(j, cand),
            "explanation": j.get("explanation", "") or "",
            "finding_valid": True,
            "extraction_confidence": cand["extraction_confidence"],
        })
    return findings


def map_to_borderline(
    candidates: list[dict], judgments: list[dict]
) -> list[dict]:
    """Turn ``borderline`` judgments into the additive
    ``bias_borderline_candidates`` slot shape (TASK-BIAS-TIER-MAPPING):
    ``{excerpt, issue, explanation, extraction_confidence}`` — the confirmed
    shape without ``finding_valid`` (these are not findings; they are the honest
    gray zone). Same originary-output discipline: excerpt from the candidate,
    verdict fields from the judge.
    """
    by_id = {c["candidate_id"]: c for c in candidates}
    out: list[dict] = []
    for j in judgments or []:
        if not isinstance(j, dict) or j.get("verdict") != "borderline":
            continue
        cand = by_id.get(j.get("candidate_id"))
        if cand is None:
            continue
        out.append({
            "excerpt": cand["excerpt"],
            "issue": _resolved_issue(j, cand),
            "explanation": j.get("explanation", "") or "",
            "extraction_confidence": cand["extraction_confidence"],
        })
    return out


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
        # Measurement-only per-candidate verdict breakdown (excerpt/verdict/
        # position) for the stability grid — NOT logged, NOT rendered, NOT part
        # of the outer contract. The flip-distance gate reads it.
        self.last_judgments_debug: list[dict] = []

    def reset_call_metrics(self) -> None:
        self.last_cost_usd = 0.0
        self.last_tokens = 0
        self.extra_log_fields = {}
        self.last_judgments_debug = []
        self.extractor.reset_call_metrics()
        self.judge.reset_call_metrics()

    @staticmethod
    def _judgment_breakdown(
        candidates: list[dict], judgments: list[dict], article_body: str
    ) -> list[dict]:
        """Every judged candidate as ``{excerpt, verdict, pos, end}`` (position
        of the candidate's excerpt in the article). Measurement-only — used by
        the gate to detect full flips (confirmed↔cleared) across cold runs."""
        by_id = {c["candidate_id"]: c for c in candidates}
        out: list[dict] = []
        for j in judgments or []:
            if not isinstance(j, dict):
                continue
            cand = by_id.get(j.get("candidate_id"))
            verdict = j.get("verdict")
            if cand is None or verdict not in ("confirmed", "borderline", "cleared"):
                continue
            exc = cand["excerpt"]
            pos = article_body.find(exc)
            out.append({
                "excerpt": exc,
                "verdict": verdict,
                "pos": pos,
                "end": (pos + len(exc)) if pos >= 0 else -1,
            })
        return out

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
        borderline = map_to_borderline(candidates, judgments)
        by_id = {c["candidate_id"]: c for c in candidates}
        cleared_count = sum(
            1 for j in (judgments or [])
            if isinstance(j, dict) and j.get("verdict") == "cleared"
            and j.get("candidate_id") in by_id
        )
        self.last_judgments_debug = self._judgment_breakdown(
            candidates, judgments, article_body)

        # --- loud metrics ----------------------------------------------------
        self.extra_log_fields = {
            "extractor_model": self.extractor.model,
            "extractor_provider": ext_provider,
            "judge_model": self.judge.model,
            "judge_provider": judge_provider,
            "extract_run1_raw": stats["extract_run1_raw"],
            "extract_run2_raw": stats["extract_run2_raw"],
            "extractor_cap": stats["extractor_cap"],
            "invalid_span_drops": stats["invalid_span_drops"],
            "distinct_excerpts": stats["distinct_excerpts"],
            "union_size": stats["union_size"],
            "judge_skipped": judge_skipped,
            "confirmed_count": len(findings),
            "borderline_count": len(borderline),
            "cleared_count": cleared_count,
        }
        logger.info(
            "bias composite: extracted %d/%d (raw), union=%d, invalid_drops=%d, "
            "confirmed=%d, borderline=%d, cleared=%d%s",
            stats["extract_run1_raw"], stats["extract_run2_raw"],
            stats["union_size"], stats["invalid_span_drops"], len(findings),
            len(borderline), cleared_count,
            " (judge skipped: empty candidates)" if judge_skipped else "",
        )

        structured = {
            "language_bias": {"findings": findings, "borderline": borderline},
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
