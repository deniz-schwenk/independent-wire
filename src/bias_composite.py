"""Bias-stage split: extract -> union -> judge (TASK-BIAS-STAGE-SPLIT).

The single-call emit-then-retract bias prompt reproduced only ~51% of its
confirmed spans across identical cache-cold runs
(docs/BIAS-STAGE-MODEL-EVAL-2026-07.md; the instability lived in the retraction
decision, not the model). This composite replaces it with three calls whose
individual pieces are each more repeatable:

  Phase A  three GENEROUS candidate-extraction calls (deepseek-v4-pro, reasoning
           none, temperature 0.8 -> natural variance = coverage, fp8-pinned;
           TASK-BIAS-THIRD-EXTRACTOR). Extractor instability is *harmless* — it
           only widens recall; a third pass drops a p=0.8 candidate's miss
           probability from ~4% to ~1%.
  union    DETERMINISTIC Python: verbatim-substring validate, then
           POSITION-ANCHORED merge — resolve each span to its character
           interval(s) and merge only spans that overlap at the same location
           (nesting or partial overlap); multi-occurrence spans are ambiguous
           and never merge (a negation stays distinct from an affirmation).
           Present the shortest variant, keep the variant list, stable order by
           article position, candidate_id 1..N, 2/2-vs-1/2 agreement confidence.
  Phase B  TWO CLOSED per-candidate judgment votes (Opus 4.6, reasoning none):
           identical input to both calls, each a TERNARY verdict (confirmed /
           borderline / cleared), explanation-before-verdict. Python assigns the
           tier from the two votes — both-confirmed => confirmed, both-cleared =>
           cleared, anything else => borderline (TASK-BIAS-DUAL-JUDGE). A single
           sample cannot perceive its own boundary; marginality is only visible
           ACROSS samples, so the second vote is what makes a straddler land in
           the (ungated) gray zone instead of flipping poles cold-to-cold.

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
from collections import Counter
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

# Number of independent extraction passes (TASK-BIAS-THIRD-EXTRACTOR). Three
# passes drop the miss probability of a p=0.8 candidate from ~4% (two passes) to
# ~1%; production runs each article exactly once, so missed surfacing is
# unobservable live and is hardened here. Also the ``extraction_confidence``
# denominator ("K/3").
EXTRACTION_PASSES = 3


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
    runs: list[list[dict]],
    article_body: str,
    cap: int = EXTRACTOR_CANDIDATE_CAP,
) -> tuple[list[dict], dict]:
    """Merge N extractor candidate lists into one ordered, position-merged,
    confidence-tagged candidate list.

    ``runs`` is the list of per-pass candidate lists (three in production —
    TASK-BIAS-THIRD-EXTRACTOR; a failed pass contributes an empty list so the
    confidence denominator stays fixed at ``len(runs)``).

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
    - a family's ``extraction_confidence`` is ``"K/N"`` where K is the number of
      passes (of ``N = len(runs)``) that flagged the location — the join over its
      variants' contributing runs (e.g. ``"3/3"``, ``"2/3"``, ``"1/3"``);
    - order is by the representative's position in ``article_body`` (excerpt
      string as tiebreak); ``candidate_id`` is 1..N in that order.

    Returns ``(candidates, stats)`` where each candidate is ``{"candidate_id",
    "excerpt", "issue_hint", "extraction_confidence", "variants"}``.
    """
    n_runs = len(runs)
    invalid_dropped = 0
    # distinct excerpt -> {"runs": set[int], "hint": str}
    distinct: dict[str, dict] = {}
    for run_idx, run in enumerate(runs, start=1):
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
        # confidence = join over variants: K/N where K passes (of N) flagged the
        # location (some distinct span containing a variant came from that pass).
        family_runs: set[int] = set()
        for m in members:
            family_runs |= distinct[m]["runs"]
        confidence = f"{len(family_runs)}/{n_runs}"
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
        "extract_raw": [len(r or []) for r in runs],  # per-pass raw emission count
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


# --------------------------------------------------------------------------- #
# Dual-judge vote aggregation (TASK-BIAS-DUAL-JUDGE)
# --------------------------------------------------------------------------- #
# Marginality is only observable ACROSS samples: a single judge call cannot feel
# that it sits on a boundary, so a genuinely borderline candidate commits to
# opposite poles across cold runs. We run the judge TWICE (identical input) and
# assign the tier from the two votes IN PYTHON — deterministic-before-LLM in its
# purest form: the LLM only votes, the tier is code.
_VERDICTS = ("confirmed", "borderline", "cleared")
# Explanation/issue pick priority: a borderline vote names both readings by
# design, so it wins; otherwise the confirmed vote; cleared last. Ties broken by
# call order (call 1 before call 2) via a stable min.
_PICK_PRIORITY = {"borderline": 0, "confirmed": 1, "cleared": 2}


def _norm_verdict(judgment: Any) -> str:
    """The judge's verdict normalized to one of ``_VERDICTS``; anything missing
    or malformed is treated as ``cleared`` (the conservative pole — a candidate
    the judge did not clearly address is never confirmed)."""
    if isinstance(judgment, dict):
        v = judgment.get("verdict")
        if v in _VERDICTS:
            return v
    return "cleared"


def aggregate_family(candidate: dict, j1: Any, j2: Any) -> dict:
    """Deterministic tier + presentation for one merged candidate family from
    the two judge votes (``j1`` = call 1, ``j2`` = call 2).

    Tier rule (TASK-BIAS-DUAL-JUDGE):
      both confirmed -> confirmed; both cleared -> cleared; ANY other
      combination (any disagreement, or any borderline vote) -> borderline.

    Presentation: the explanation/issue come from the highest-priority vote
    (borderline > confirmed > cleared; ties -> call 1). ``judge_votes`` is the
    honest vote split (e.g. ``"confirmed 1/2 · cleared 1/2"``); ``judge_confidence``
    is the confirmed-vote fraction (``"2/2"`` for a confirmed finding).
    """
    v1, v2 = _norm_verdict(j1), _norm_verdict(j2)
    if v1 == "confirmed" and v2 == "confirmed":
        tier = "confirmed"
    elif v1 == "cleared" and v2 == "cleared":
        tier = "cleared"
    else:
        tier = "borderline"

    votes = [(v1, j1), (v2, j2)]
    _, picked = min(votes, key=lambda t: _PICK_PRIORITY[t[0]])  # stable: call1 wins tie
    picked = picked if isinstance(picked, dict) else {}
    counts = Counter([v1, v2])
    judge_votes = " · ".join(
        f"{v} {counts[v]}/2" for v in _VERDICTS if counts[v]
    )
    return {
        "tier": tier,
        "issue": _resolved_issue(picked, candidate),
        "explanation": picked.get("explanation", "") or "",
        "judge_votes": judge_votes,
        "judge_confidence": f"{counts['confirmed']}/2",
        "v1": v1,
        "v2": v2,
    }


def aggregate_judgments(
    candidates: list[dict], judgments1: list[dict], judgments2: list[dict]
) -> tuple[list[dict], list[dict], int, list[dict]]:
    """Aggregate two judge votes per candidate family into
    ``(findings, borderline, cleared_count, family_debug)``.

    - ``findings`` (tier confirmed) use the existing ``bias_language_findings``
      shape plus the additive ``extraction_confidence`` / ``judge_confidence``
      / ``judge_votes``.
    - ``borderline`` (tier borderline) use the ``bias_borderline_candidates``
      shape plus ``judge_votes`` (no ``finding_valid``).
    - ``cleared`` (tier cleared) are dropped, only counted.
    - ``family_debug`` is measurement-only: every family's aggregated tier +
      both raw votes + position, for the flip-distance gate.

    Iterating over *candidates* (not judgments) guarantees every merged family
    gets exactly one tier; a candidate no judge addressed aggregates to cleared.
    """
    by_id1 = {j.get("candidate_id"): j for j in (judgments1 or []) if isinstance(j, dict)}
    by_id2 = {j.get("candidate_id"): j for j in (judgments2 or []) if isinstance(j, dict)}
    findings: list[dict] = []
    borderline: list[dict] = []
    cleared_count = 0
    family_debug: list[dict] = []
    for cand in candidates:
        cid = cand["candidate_id"]
        agg = aggregate_family(cand, by_id1.get(cid), by_id2.get(cid))
        family_debug.append({
            "excerpt": cand["excerpt"],
            "tier": agg["tier"],
            "v1": agg["v1"],
            "v2": agg["v2"],
            "judge_votes": agg["judge_votes"],
        })
        if agg["tier"] == "confirmed":
            findings.append({
                "excerpt": cand["excerpt"],
                "issue": agg["issue"],
                "explanation": agg["explanation"],
                "finding_valid": True,
                "extraction_confidence": cand["extraction_confidence"],
                "judge_confidence": agg["judge_confidence"],
                "judge_votes": agg["judge_votes"],
            })
        elif agg["tier"] == "borderline":
            borderline.append({
                "excerpt": cand["excerpt"],
                "issue": agg["issue"],
                "explanation": agg["explanation"],
                "extraction_confidence": cand["extraction_confidence"],
                "judge_votes": agg["judge_votes"],
            })
        else:
            cleared_count += 1
    return findings, borderline, cleared_count, family_debug


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
        self.model = f"bias-composite({extractor.model} x3 -> {judge.model} x2)"
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

        results = await asyncio.gather(
            *(_extract() for _ in range(EXTRACTION_PASSES)))
        if all(r is None for r in results):
            raise AgentError("bias extraction failed on all passes")
        ext_provider = ""
        runs: list[list[dict]] = []
        for res in results:
            if res is None:
                runs.append([])            # failed pass -> empty (denominator fixed)
                continue
            self._account(res)
            ext_provider = ext_provider or res.provider
            runs.append((res.structured or {}).get("candidates") or [])

        candidates, stats = build_union(runs, article_body)

        # --- Phase B: TWO closed judgment votes, deterministic aggregation ----
        # (skip both on an empty candidate list). Identical input to both calls;
        # Python assigns the tier from the two votes (TASK-BIAS-DUAL-JUDGE).
        judge_skipped = not candidates
        judge1_provider = judge2_provider = ""
        judgments1: list[dict] = []
        judgments2: list[dict] = []
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
            judge_ctx = {"article_body": article_body, "candidates": judge_input}
            jres1, jres2 = await asyncio.gather(
                self.judge.run(JUDGE_MESSAGE, context=judge_ctx),
                self.judge.run(JUDGE_MESSAGE, context=judge_ctx),
            )
            for jres, which in ((jres1, 1), (jres2, 2)):
                self._account(jres)
                parsed = jres.structured or {}
                if which == 1:
                    judgments1 = parsed.get("judgments") or []
                    judge1_provider = jres.provider
                else:
                    judgments2 = parsed.get("judgments") or []
                    judge2_provider = jres.provider
            # the reader_note is a whole-article summary; take call 1's (its
            # findings drive the confirmed set the note describes).
            reader_note = (jres1.structured or {}).get("reader_note", "") or ""

        findings, borderline, cleared_count, family_debug = aggregate_judgments(
            candidates, judgments1, judgments2)

        # attach positions to the measurement-only debug (gate reads pos/end).
        for d in family_debug:
            pos = article_body.find(d["excerpt"])
            d["pos"] = pos
            d["end"] = (pos + len(d["excerpt"])) if pos >= 0 else -1
        self.last_judgments_debug = family_debug
        disagreements = sum(1 for d in family_debug if d["v1"] != d["v2"])

        # --- loud metrics ----------------------------------------------------
        self.extra_log_fields = {
            "extractor_model": self.extractor.model,
            "extractor_provider": ext_provider,
            "extraction_passes": EXTRACTION_PASSES,
            "judge_model": self.judge.model,
            "judge1_provider": judge1_provider,
            "judge2_provider": judge2_provider,
            "extract_raw": stats["extract_raw"],
            "extractor_cap": stats["extractor_cap"],
            "invalid_span_drops": stats["invalid_span_drops"],
            "distinct_excerpts": stats["distinct_excerpts"],
            "union_size": stats["union_size"],
            "judge_skipped": judge_skipped,
            "confirmed_count": len(findings),
            "borderline_count": len(borderline),
            "cleared_count": cleared_count,
            "judge_disagreements": disagreements,
        }
        logger.info(
            "bias composite: extracted %s (raw/pass), union=%d, invalid_drops=%d, "
            "confirmed=%d, borderline=%d, cleared=%d, judge_disagree=%d%s",
            stats["extract_raw"],
            stats["union_size"], stats["invalid_span_drops"], len(findings),
            len(borderline), cleared_count, disagreements,
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
            provider=judge1_provider or ext_provider,
        )
