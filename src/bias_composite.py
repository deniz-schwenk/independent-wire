"""Bias-stage split: extract -> union -> judge (TASK-BIAS-STAGE-SPLIT).

The single-call emit-then-retract bias prompt reproduced only ~51% of its
confirmed spans across identical cache-cold runs
(docs/BIAS-STAGE-MODEL-EVAL-2026-07.md; the instability lived in the retraction
decision, not the model). This composite replaces it with three calls whose
individual pieces are each more repeatable:

  Phase A  three GENEROUS candidate-extraction calls (v4-flash-0731 @ minimal
           since 2026-08-31 — TASK-DSV4-SWAPS-BUNDLE; deepseek-v4-pro fp8-pinned
           before that — reasoning minimal, temperature 0.8 -> natural variance
           = coverage; TASK-BIAS-THIRD-EXTRACTOR). Extractor instability is
           *harmless* — it only widens recall; a third pass drops a p=0.8
           candidate's miss probability from ~4% to ~1%.
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
import itertools
import json
import logging
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
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
# enforced here deterministically.
#
# The cap value is unchanged; HOW it truncates is not. It used to keep the first
# 18 items in raw emission order, which was right while the prompt asked the
# model to "keep the 25 most clearly loaded ones" — the head of the list was the
# best of the list. It is wrong for a sweep-structured prompt, which emits
# candidates pattern by pattern: head-truncation then deletes whole trailing
# pattern families (hedging and intensifier last), and the union loses a
# category rather than its weakest members. `_cap_run` truncates round-robin
# across `issue_hint` instead, so every pattern the pass found survives the cap.
EXTRACTOR_CANDIDATE_CAP = 18

# Number of independent extraction passes (TASK-BIAS-THIRD-EXTRACTOR). Three
# passes drop the miss probability of a p=0.8 candidate from ~4% (two passes) to
# ~1%; production runs each article exactly once, so missed surfacing is
# unobservable live and is hardened here. Also the ``extraction_confidence``
# denominator ("K/3").
EXTRACTION_PASSES = 3

# Adaptive 4th pass (TASK-BIAS-EXTRACTOR-COUPLED part 3). A pass whose
# candidate count collapses relative to its siblings is a THIN PASS: the model
# emitted a fraction of what the same prompt on the same article produced twice
# over, so the union loses coverage the article actually offered. Observed
# live on 2026-08-30 topic 0 at raw counts [4, 10, 25].
#
# The rule is deliberately RELATIVE — a pass is an outlier only against the
# median of the OTHER passes, never against an absolute floor. A short clean
# article that legitimately yields [1, 1, 1] must not buy a fourth call, and
# with the median of the others at 1 it does not. The zero-median guard makes
# [0, 0, 0] explicit for the same reason.
#
# Cap: exactly ONE extra pass, ever, however many outliers there are. The extra
# pass is an ordinary pass — `build_union` then runs over all four and the
# confidence denominator follows `len(runs)` (K/4), which it already did.
#
# Ordering matters: this check runs AFTER the gather, so it sees the pass set
# that survived Agent's transport retries and the channel fallback. It cannot
# double-fire with the empty-body handling because that handling has already
# finished by the time a count exists to compare.
EXTRA_PASS_OUTLIER_RATIO = 0.5


# --------------------------------------------------------------------------- #
# Adaptive extra pass (pure function — no LLM, no I/O)
# --------------------------------------------------------------------------- #
def _median(values: list[int]) -> float:
    """Median of a non-empty list; 0.0 for an empty one."""
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def thin_outlier_passes(
    counts: list[int], ratio: float = EXTRA_PASS_OUTLIER_RATIO
) -> list[int]:
    """1-based indices of passes whose candidate count is below ``ratio`` times
    the median of the OTHER passes.

    Relative by construction: each pass is compared against its siblings, never
    against a fixed floor, so a uniformly thin article triggers nothing. A
    median of zero (every other pass empty too) also triggers nothing — there
    is no evidence of a richer article to recover.
    """
    outliers: list[int] = []
    for i, count in enumerate(counts, start=1):
        others = counts[:i - 1] + counts[i:]
        if not others:
            continue
        median_others = _median(others)
        if median_others > 0 and count < ratio * median_others:
            outliers.append(i)
    return outliers


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


LEXICON_PATH = Path(__file__).resolve().parents[1] / "config" / "bias_lexicon.json"

# Quotation marks that open or close reported speech in the corpus. Straight and
# typographic doubles, typographic singles, and the guillemets that appear in
# fetched French/Spanish/Russian copy. The straight APOSTROPHE is deliberately
# absent: in English prose it is overwhelmingly a contraction or a possessive,
# and treating it as a quotation mark would blank out most of the article.
_QUOTE_PAIRS = [('"', '"'), ("\u201c", "\u201d"), ("\u2018", "\u2019"),
                ("\u00ab", "\u00bb"), ("\u201e", "\u201c")]


@lru_cache(maxsize=1)
def load_lexicon(path: str | None = None) -> tuple[tuple[str, str], ...]:
    """The curated canonical-term list as ``((term, issue_hint), ...)``.

    Cached: the file is a tracked config read once per process, like
    ``config/outlet_registry.json``. A missing or unreadable file is NOT fatal —
    the stage degrades to model-only extraction and says so loudly, because a
    lexicon outage must never take the bias card down.
    """
    p = Path(path) if path else LEXICON_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                                     # noqa: BLE001
        logger.error("bias lexicon unreadable at %s (%s) — extraction continues "
                     "MODEL-ONLY, lexicon candidates are absent this run", p, exc)
        return ()
    out = []
    for row in data.get("terms") or []:
        term, hint = row.get("term"), row.get("issue_hint")
        if isinstance(term, str) and term and isinstance(hint, str) and hint:
            out.append((term, hint))
    if not out:
        logger.warning("bias lexicon at %s has no usable entries — model-only", p)
    return tuple(out)


def quoted_spans(body: str) -> list[tuple[int, int]]:
    """Character ranges of quoted speech, marks included, merged and sorted.

    THE BOUNDARY IS QUOTATION MARKS ONLY — deliberately, and this is the one
    design decision in this module that is easy to get backwards.

    An earlier detector in this line of work treated an *attributed sentence*
    as outside the article's own voice. Measured on the nine reference articles
    (TASK-EXTRACTOR-BREADTH-V3 §3), that classifies **every** occurrence of
    "regime" as not-own-voice and the scan finds nothing at all. That is the
    wrong reading of the contract: when an article paraphrases a source and
    chooses the word "regime" itself, the word is the article's own
    characterisation. The extractor prompt says so ("the characterization the
    article wraps around the quote"), and the judge rubric's own-voice anchor is
    specifically about language *inside a quoted statement*. Only the marks
    close the door.

    Same-mark pairs (straight and typographic doubles) are paired left to right;
    an unpaired trailing mark is ignored. Directional pairs (typographic single,
    guillemets) are matched open-to-next-close. Overlapping results are merged.
    """
    spans: list[tuple[int, int]] = []
    for open_ch, close_ch in _QUOTE_PAIRS:
        if open_ch == close_ch:
            marks = [i for i, ch in enumerate(body) if ch == open_ch]
            spans += [(marks[i], marks[i + 1] + 1)
                      for i in range(0, len(marks) - 1, 2)]
        else:
            i = body.find(open_ch)
            while i != -1:
                j = body.find(close_ch, i + 1)
                if j == -1:
                    break
                spans.append((i, j + 1))
                i = body.find(open_ch, j + 1)
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def scan_lexicon(article_body: str,
                 lexicon: tuple[tuple[str, str], ...] | None = None) -> list[dict]:
    """Deterministic canonical-term candidates from the article's own voice.

    Why this exists: three prompt generations held judged coverage (D1) at ~3.3,
    and the `regime` canary — four own-voice uses in one article — was found 0
    times by the newest prompt while a string scan finds every one of them
    (TASK-EXTRACTOR-BREADTH / -V3). Closed-vocabulary recall is Python's job;
    the open-ended half (framing, emotionalizing, quote handling) stays the
    model's, where it already scores at ceiling.

    Matching is case-insensitive on word boundaries, longest term first so a
    multi-word entry wins over a single-word one that sits inside it. The
    excerpt is the **verbatim matched substring** of ``article_body``, not the
    lexicon spelling, so it survives ``build_union``'s substring validation
    with the article's own capitalisation.

    ONE CANDIDATE PER DISTINCT WORDING: a term matched five times yields one
    candidate. That is the same economy the prompts state, and ``build_union``
    already expands a multi-occurrence excerpt into its occurrences.

    A hit whose every occurrence lies inside quoted speech is not emitted.
    """
    lex = load_lexicon() if lexicon is None else lexicon
    if not lex or not article_body:
        return []
    quotes = quoted_spans(article_body)

    def in_quote(a: int, b: int) -> bool:
        return any(s <= a and b <= e for s, e in quotes)

    out: list[dict] = []
    seen: set[str] = set()
    for term, hint in sorted(lex, key=lambda t: (-len(t[0]), t[0])):
        pattern = re.compile(r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b",
                             re.IGNORECASE)
        for m in pattern.finditer(article_body):
            if in_quote(m.start(), m.end()):
                continue
            text = m.group(0)
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append({"excerpt": text, "issue_hint": hint,
                        "_at": m.start()})
    out.sort(key=lambda c: c["_at"])
    for c in out:
        c.pop("_at")
    return out


def _cap_run(run: list, cap: int) -> list:
    """Truncate ONE extraction pass to ``cap`` items without losing a pattern.

    Items are bucketed by ``issue_hint`` and taken round-robin: one from each
    pattern in turn until the cap is reached. So a 30-item pass covering five
    patterns contributes items from all five, where head-truncation would have
    kept the first three patterns whole and dropped the last two entirely.

    Ordering is fully deterministic and prompt-agnostic:

    * **pattern order** is first appearance in the pass. The schema types
      ``issue_hint`` as a free string with no enum, so the six pattern names are
      a prompt contract rather than a code contract — hardcoding them here would
      invent one. For a sweep-structured prompt, first-appearance order IS the
      sweep order.
    * **item order within a pattern** is the pass's own order, so the model's
      own ranking still decides which of a pattern's items survive.
    * items whose ``issue_hint`` is missing, empty, or not a string are taken
      **last**, only once every named pattern has been served — an unlabelled
      item is not a pattern family and must never displace one. A pass
      consisting only of such items still truncates cleanly to the cap.

    A pass at or under the cap is returned unchanged, in its original order —
    no reordering happens when no truncation is needed.
    """
    if len(run) <= cap:
        return list(run)

    named: dict[str, list] = {}
    unknown: list = []
    for item in run:
        hint = item.get("issue_hint") if isinstance(item, dict) else None
        if isinstance(hint, str) and hint:
            named.setdefault(hint, []).append(item)
        else:
            unknown.append(item)

    kept: list = []
    # dict preserves first-appearance order of the named patterns
    for row in itertools.zip_longest(*named.values()):
        for item in row:
            if item is None:
                continue
            kept.append(item)
            if len(kept) == cap:
                return kept
    # unknown/missing hint goes LAST: it is not a pattern family, so it must
    # never displace one. It still gets whatever room the named patterns leave.
    for item in unknown:
        kept.append(item)
        if len(kept) == cap:
            break
    return kept


def build_union(
    runs: list[list[dict]],
    article_body: str,
    cap: int = EXTRACTOR_CANDIDATE_CAP,
    lexicon_candidates: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Merge N extractor candidate lists into one ordered, position-merged,
    confidence-tagged candidate list.

    ``runs`` is the list of per-pass candidate lists (three in production —
    TASK-BIAS-THIRD-EXTRACTOR; a failed pass contributes an empty list so the
    confidence denominator stays fixed at ``len(runs)``).

    Rules (all deterministic):
    - each run is truncated to ``cap`` items round-robin across ``issue_hint``
      (extractor cost cap; see :func:`_cap_run` — a pass at or under the cap is
      untouched, and no pattern the pass found is lost to truncation);
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
    - ``lexicon_candidates`` (from :func:`scan_lexicon`) join as ONE additional
      deterministic list. **They are not a vote**: the confidence denominator
      stays ``len(runs)``, so a lexicon hit never inflates a model family's K/N.
      A family the model also found keeps its ``K/N`` and ``source: "model"``;
      a family that exists ONLY because of the lexicon carries
      ``extraction_confidence: "lexicon"`` and ``source: "lexicon"``. Both are
      additive values of existing free-string fields — no schema change. The
      lexicon list is EXEMPT from ``cap``: it is already bounded by the size of
      the curated file, and capping it would re-introduce the eviction the
      round-robin cap exists to prevent;
    - order is by the representative's position in ``article_body`` (excerpt
      string as tiebreak); ``candidate_id`` is 1..N in that order.

    Returns ``(candidates, stats)`` where each candidate is ``{"candidate_id",
    "excerpt", "issue_hint", "extraction_confidence", "variants", "source"}``.
    The bias judge is shown only ``candidate_id`` / ``excerpt`` / ``issue_hint``
    (see the ``judge_input`` projection below and agents/bias_judge), so
    ``source`` and the ``"lexicon"`` confidence value are provenance for the
    transparency surface and never reach a model.
    """
    n_runs = len(runs)                      # MODEL passes only — the lexicon
                                            # is provenance, not a vote
    invalid_dropped = 0
    lexicon_dropped = 0
    # Run index 0 is the lexicon; model passes are 1..N. Index 0 is excluded
    # from every confidence count, so the denominator is unchanged.
    sources: list[tuple[int, list, bool]] = [
        (0, list(lexicon_candidates or []), False)          # False = no cap
    ] + [(i, run or [], True) for i, run in enumerate(runs, start=1)]

    # distinct excerpt -> {"runs": set[int], "hint": str}
    distinct: dict[str, dict] = {}
    for run_idx, run, capped in sources:
        for item in (_cap_run(run, cap) if capped else run):
            if not isinstance(item, dict):
                continue
            excerpt = item.get("excerpt")
            if not isinstance(excerpt, str) or excerpt == "":
                invalid_dropped += 1
                continue
            if excerpt not in article_body:  # verbatim-substring validation
                invalid_dropped += 1
                if run_idx == 0:
                    lexicon_dropped += 1
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
        model_runs = family_runs - {0}
        if model_runs:
            confidence = f"{len(model_runs)}/{n_runs}"
            source = "model"
        else:
            # only the lexicon put this family here. "lexicon" is an additive
            # value of the existing free-string field, not a new field, and it
            # is honest: no model pass voted, so no K/N would be true.
            confidence = "lexicon"
            source = "lexicon"
        candidates.append({
            "excerpt": rep,
            "issue_hint": distinct[rep]["hint"],
            "extraction_confidence": confidence,
            "source": source,
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
        "lexicon_candidates": len(lexicon_candidates or []),
        "lexicon_span_drops": lexicon_dropped,
        "lexicon_only_families": sum(1 for c in candidates
                                     if c["source"] == "lexicon"),
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

    def _primary_channel(self) -> str:
        """The provider the extractor's PRIMARY route is expected to report.

        The extractor may be a plain :class:`~src.agent.Agent` or a channel
        wrapper (``FlashStageWithFallback``); for the wrapper the primary is
        the inner agent. Read generically so neither shape needs special
        casing here."""
        primary = getattr(self.extractor, "primary", self.extractor)
        return getattr(primary, "provider", "") or ""

    def _channel_report(
        self, results: list[AgentResult | None]
    ) -> tuple[str, str, list[int]]:
        """``(provider, served_model, fallback_pass_indices)`` for the
        extraction passes.

        The composite runs its passes CONCURRENTLY against one wrapper
        instance, so the wrapper's own ``last_fallback_used`` marker is
        last-writer-wins across them and cannot answer "did any pass fall
        back?". The per-result provider can: a pass served by anything other
        than the primary channel took the fallback route. Indices are 1-based
        to match the ``extraction_confidence`` run numbering."""
        primary_channel = self._primary_channel()
        providers = [r.provider for r in results if r is not None]
        models = [r.model for r in results if r is not None and r.model]
        fallback_passes = [
            i for i, r in enumerate(results, start=1)
            if r is not None and primary_channel and r.provider != primary_channel
        ]
        return (providers[0] if providers else "",
                models[0] if models else "",
                fallback_passes)

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
        runs: list[list[dict]] = []
        for res in results:
            if res is None:
                runs.append([])            # failed pass -> empty (denominator fixed)
                continue
            self._account(res)
            runs.append((res.structured or {}).get("candidates") or [])

        # --- adaptive 4th pass on an outlier-thin pass -----------------------
        outlier_passes = thin_outlier_passes([len(r) for r in runs])
        extra_pass_run = False
        if outlier_passes:
            logger.warning(
                "bias extractor THIN PASS: pass(es) %s of %s are below %.0f%% "
                "of the median of the others — running exactly one extra "
                "extraction pass (capped at one).",
                outlier_passes, [len(r) for r in runs],
                EXTRA_PASS_OUTLIER_RATIO * 100,
            )
            extra = await _extract()
            extra_pass_run = True
            if extra is None:
                # The extra pass failed outright. Do NOT append an empty run:
                # that would widen the confidence denominator to 4 with a
                # guaranteed-empty pass and penalise every candidate for a
                # transport failure.
                logger.error(
                    "bias extractor extra pass FAILED — union runs over the "
                    "original %d passes, denominator unchanged.", len(runs),
                )
            else:
                self._account(extra)
                results = list(results) + [extra]
                runs.append((extra.structured or {}).get("candidates") or [])

        ext_provider, ext_model, ext_fallback_passes = self._channel_report(results)

        # Deterministic canonical-term candidates, scanned from the article's
        # own voice and merged in alongside the model passes. Runs on every
        # article, costs nothing, and cannot fail the stage: an unreadable
        # lexicon logs loudly and yields [] (see load_lexicon).
        lexicon_candidates = scan_lexicon(article_body)
        candidates, stats = build_union(runs, article_body,
                                        lexicon_candidates=lexicon_candidates)

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
            "extractor_model_served": ext_model,
            "extractor_provider": ext_provider,
            "extractor_fallback_used": bool(ext_fallback_passes),
            "extractor_fallback_passes": ext_fallback_passes,
            "extraction_passes": len(runs),
            "extractor_extra_pass": extra_pass_run,
            "extractor_outlier_passes": outlier_passes,
            "judge_model": self.judge.model,
            "judge1_provider": judge1_provider,
            "judge2_provider": judge2_provider,
            "extract_raw": stats["extract_raw"],
            "extractor_cap": stats["extractor_cap"],
            "invalid_span_drops": stats["invalid_span_drops"],
            "distinct_excerpts": stats["distinct_excerpts"],
            "union_size": stats["union_size"],
            "lexicon_candidates": stats["lexicon_candidates"],
            "lexicon_only_families": stats["lexicon_only_families"],
            "lexicon_span_drops": stats["lexicon_span_drops"],
            "judge_skipped": judge_skipped,
            "confirmed_count": len(findings),
            "borderline_count": len(borderline),
            "cleared_count": cleared_count,
            "judge_disagreements": disagreements,
        }
        if ext_fallback_passes:
            logger.warning(
                "bias extractor FALLBACK: pass(es) %s were served by the "
                "channel-A route, not %s. Loud by design — the marker is "
                "extractor_fallback_used in run_stage_log.jsonl.",
                ext_fallback_passes, self._primary_channel() or "the primary channel",
            )
        logger.info(
            "bias composite: extracted %s (raw/pass over %d passes%s), union=%d, "
            "invalid_drops=%d, confirmed=%d, borderline=%d, cleared=%d, "
            "judge_disagree=%d%s",
            stats["extract_raw"], len(runs),
            f", extra pass on thin {outlier_passes}" if extra_pass_run else "",
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
