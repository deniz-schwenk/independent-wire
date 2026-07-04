"""Bias stage split: extract -> union -> judge (TASK-BIAS-STAGE-SPLIT).

Covers:
  * deterministic union: verbatim-substring validation (+ drop count), identical
    / contained dedup keeping the shorter minimal span, 2/2 vs 1/2 agreement
    confidence, article-position ordering, candidate_id assignment, issue_hint
    from the first run;
  * mapping confirmed judgments back to the existing bias_language_findings
    shape (excerpt from the candidate not the judge, finding_valid=True, additive
    extraction_confidence, null-issue fallback, unknown-id ignored);
  * BiasComposite orchestration: two extraction passes + one judge call, the
    empty-candidates skip path, aggregated cost/tokens, loud extra_log_fields;
  * BIAS_JUDGE_SCHEMA field order (explanation before issue/is_bias);
  * exact request bodies for all three calls (extractor x2, judge) via
    create_agents(), incl. the fp8 pin, reasoning=none, temperatures;
  * the runner surfaces extra_log_fields into the stage-log row.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agent import Agent, AgentError, AgentResult
from src.bias_composite import (
    BiasComposite,
    EXTRACT_MESSAGE,
    JUDGE_MESSAGE,
    aggregate_family,
    aggregate_judgments,
    build_union,
)
from src.runner.runner import _collect_agent_metrics
from src.schemas import BIAS_CANDIDATES_SCHEMA, BIAS_JUDGE_SCHEMA

ARTICLE = (
    "The council's decision dealt a devastating blow to neighborhood bakeries, "
    "and inspection fees were quietly doubled. Officials called it prudent."
)


# --------------------------------------------------------------------------- #
# build_union
# --------------------------------------------------------------------------- #
def test_union_drops_non_substring_excerpts_and_counts_them():
    run1 = [
        {"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"},
        {"excerpt": "NOT IN THE ARTICLE", "issue_hint": "loaded_term"},
        {"excerpt": "", "issue_hint": "hedging"},
    ]
    cands, stats = build_union(run1, [], ARTICLE)
    assert [c["excerpt"] for c in cands] == ["a devastating blow"]
    assert stats["invalid_span_drops"] == 2
    assert stats["extract_run1_raw"] == 3
    assert stats["union_size"] == 1


def test_union_identical_span_both_runs_is_2_of_2():
    run1 = [{"excerpt": "quietly doubled", "issue_hint": "passive_obscuring"}]
    run2 = [{"excerpt": "quietly doubled", "issue_hint": "passive_obscuring"}]
    cands, _ = build_union(run1, run2, ARTICLE)
    assert len(cands) == 1
    assert cands[0]["extraction_confidence"] == "2/2"


def test_union_contained_span_keeps_shorter_and_folds_agreement():
    # run1 emits the long span, run2 the short one it contains -> keep the short
    # ("devastating"), and both runs count toward its agreement -> 2/2.
    run1 = [{"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"}]
    run2 = [{"excerpt": "devastating", "issue_hint": "evaluative_adjective"}]
    cands, _ = build_union(run1, run2, ARTICLE)
    assert [c["excerpt"] for c in cands] == ["devastating"]
    assert cands[0]["extraction_confidence"] == "2/2"


def test_union_single_run_span_is_1_of_2():
    run1 = [{"excerpt": "prudent", "issue_hint": "loaded_term"}]
    cands, _ = build_union(run1, [], ARTICLE)
    assert cands[0]["extraction_confidence"] == "1/2"


def test_union_orders_by_article_position_and_assigns_ids():
    # "prudent" appears after "quietly doubled" after "devastating" in ARTICLE.
    run1 = [
        {"excerpt": "prudent", "issue_hint": "loaded_term"},
        {"excerpt": "devastating", "issue_hint": "evaluative_adjective"},
        {"excerpt": "quietly doubled", "issue_hint": "passive_obscuring"},
    ]
    cands, _ = build_union(run1, [], ARTICLE)
    assert [c["excerpt"] for c in cands] == ["devastating", "quietly doubled", "prudent"]
    assert [c["candidate_id"] for c in cands] == [1, 2, 3]


def test_union_issue_hint_from_first_run():
    run1 = [{"excerpt": "prudent", "issue_hint": "loaded_term"}]
    run2 = [{"excerpt": "prudent", "issue_hint": "hedging"}]
    cands, _ = build_union(run1, run2, ARTICLE)
    assert cands[0]["issue_hint"] == "loaded_term"  # run1 wins


def test_union_empty_inputs_yield_empty():
    cands, stats = build_union([], [], ARTICLE)
    assert cands == []
    assert stats["union_size"] == 0


def test_union_no_internal_pos_key_leaks():
    cands, _ = build_union(
        [{"excerpt": "prudent", "issue_hint": "loaded_term"}], [], ARTICLE)
    # `variants` is deliberate merge-family metadata; `_pos` must never leak.
    assert set(cands[0].keys()) == {
        "candidate_id", "excerpt", "issue_hint", "extraction_confidence",
        "variants"}
    assert cands[0]["variants"] == ["prudent"]


# --------------------------------------------------------------------------- #
# build_union — position-anchored merge (TASK-BIAS-DEDUP-FIX)
# --------------------------------------------------------------------------- #
# A crafted article giving us (i) a nested + partial-overlap cluster around
# "devastating" and (ii) the SAME words "ongoing defiance" occurring twice —
# once negated ("no ongoing defiance") and once affirmed — so the negation
# guard can be exercised.
MERGE_ARTICLE = (
    "The audit found no ongoing defiance among the northern councils. "
    "Yet ongoing defiance in some localities dealt a devastating blow to "
    "public trust through the winter."
)


def test_merge_a_nested_spans_at_same_location_merge():
    # "devastating" is nested inside "a devastating blow" (single occurrence
    # each) -> one family, shortest variant presented.
    run1 = [{"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"}]
    run2 = [{"excerpt": "devastating", "issue_hint": "evaluative_adjective"}]
    cands, stats = build_union(run1, run2, MERGE_ARTICLE)
    assert stats["union_size"] == 1
    assert cands[0]["excerpt"] == "devastating"                 # shortest variant
    # variants are ordered by article position: "a devastating blow" starts two
    # chars before "devastating".
    assert cands[0]["variants"] == ["a devastating blow", "devastating"]


def test_merge_b_partial_overlap_at_same_location_merges():
    # "a devastating" and "devastating blow" overlap on "devastating" but
    # neither contains the other -> still merge (same location).
    run1 = [{"excerpt": "a devastating", "issue_hint": "evaluative_adjective"}]
    run2 = [{"excerpt": "devastating blow", "issue_hint": "evaluative_adjective"}]
    cands, stats = build_union(run1, run2, MERGE_ARTICLE)
    assert stats["union_size"] == 1
    assert cands[0]["excerpt"] == "a devastating"               # shortest (13 < 16)
    assert set(cands[0]["variants"]) == {"a devastating", "devastating blow"}


def test_merge_c_negation_does_not_merge_across_locations():
    # "ongoing defiance" occurs twice (once inside "no ongoing defiance" at P1,
    # once inside "ongoing defiance in some localities" at P2). Because it is
    # multi-occurrence it is location-ambiguous and must NOT collapse the P2
    # affirmation — the negation stays a distinct candidate.
    run1 = [
        {"excerpt": "ongoing defiance", "issue_hint": "loaded_term"},
        {"excerpt": "ongoing defiance in some localities", "issue_hint": "loaded_term"},
    ]
    cands, stats = build_union(run1, [], MERGE_ARTICLE)
    excerpts = [c["excerpt"] for c in cands]
    assert "ongoing defiance" in excerpts
    assert "ongoing defiance in some localities" in excerpts
    assert stats["union_size"] == 2                             # NOT merged


def test_merge_d_ambiguous_multioccurrence_stays_unmerged():
    # An excerpt occurring more than once never merges with an overlapping
    # single-occurrence span, even a longer one that contains one occurrence.
    body = "Costs soared. Prices soared beyond all forecasts. Costs soared again."
    run1 = [
        {"excerpt": "soared", "issue_hint": "intensifier"},          # occurs 3x
        {"excerpt": "soared beyond all forecasts", "issue_hint": "intensifier"},
    ]
    cands, stats = build_union(run1, [], body)
    excerpts = [c["excerpt"] for c in cands]
    assert "soared" in excerpts                                 # stands alone
    assert "soared beyond all forecasts" in excerpts
    assert stats["union_size"] == 2


def test_merge_e_confidence_is_max_over_variants():
    # A family whose variants come from BOTH runs is 2/2 (the join / max over
    # variants); a family drawn from a single run is 1/2.
    run1 = [{"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"}]
    run2 = [{"excerpt": "devastating", "issue_hint": "evaluative_adjective"}]
    cands, _ = build_union(run1, run2, MERGE_ARTICLE)
    assert cands[0]["extraction_confidence"] == "2/2"           # both runs -> max

    # same family, both variants from run1 only -> 1/2 (max of {1/2, 1/2}).
    run1_only = [
        {"excerpt": "a devastating blow", "issue_hint": "evaluative_adjective"},
        {"excerpt": "devastating", "issue_hint": "evaluative_adjective"},
    ]
    cands2, _ = build_union(run1_only, [], MERGE_ARTICLE)
    assert cands2[0]["extraction_confidence"] == "1/2"


def test_extractor_cap_truncates_each_run():
    # Each run is capped before the union; a 30-item run keeps only the first 18.
    body = " ".join(f"word{i}" for i in range(40))
    run = [{"excerpt": f"word{i}", "issue_hint": "loaded_term"} for i in range(30)]
    cands, stats = build_union(run, [], body, cap=18)
    assert stats["union_size"] == 18
    kept = {c["excerpt"] for c in cands}
    assert "word0" in kept and "word17" in kept
    assert "word18" not in kept                                 # dropped by cap


# --------------------------------------------------------------------------- #
# Dual-judge vote aggregation (TASK-BIAS-DUAL-JUDGE)
# --------------------------------------------------------------------------- #
CANDS = [
    {"candidate_id": 1, "excerpt": "devastating", "issue_hint": "evaluative_adjective",
     "extraction_confidence": "2/2"},
    {"candidate_id": 2, "excerpt": "prudent", "issue_hint": "loaded_term",
     "extraction_confidence": "1/2"},
]


def _v(verdict, explanation="e", issue="loaded_term"):
    return {"candidate_id": 1, "verdict": verdict, "explanation": explanation,
            "issue": issue}


# --- the full 3×3 vote matrix -> tier -------------------------------------- #
# both-confirmed => confirmed, both-cleared => cleared, everything else => borderline.
@pytest.mark.parametrize("v1,v2,tier", [
    ("confirmed", "confirmed", "confirmed"),
    ("cleared", "cleared", "cleared"),
    ("borderline", "borderline", "borderline"),
    ("confirmed", "cleared", "borderline"),     # disagreement across poles
    ("cleared", "confirmed", "borderline"),
    ("confirmed", "borderline", "borderline"),
    ("borderline", "confirmed", "borderline"),
    ("cleared", "borderline", "borderline"),
    ("borderline", "cleared", "borderline"),
])
def test_vote_matrix_tier(v1, v2, tier):
    agg = aggregate_family(CANDS[0], _v(v1), _v(v2))
    assert agg["tier"] == tier


def test_vote_summary_and_judge_confidence():
    assert aggregate_family(CANDS[0], _v("confirmed"), _v("confirmed"))["judge_votes"] \
        == "confirmed 2/2"
    assert aggregate_family(CANDS[0], _v("confirmed"), _v("cleared"))["judge_votes"] \
        == "confirmed 1/2 · cleared 1/2"
    assert aggregate_family(CANDS[0], _v("borderline"), _v("cleared"))["judge_votes"] \
        == "borderline 1/2 · cleared 1/2"
    # judge_confidence = confirmed-vote fraction
    assert aggregate_family(CANDS[0], _v("confirmed"), _v("confirmed"))["judge_confidence"] == "2/2"
    assert aggregate_family(CANDS[0], _v("confirmed"), _v("cleared"))["judge_confidence"] == "1/2"
    assert aggregate_family(CANDS[0], _v("borderline"), _v("borderline"))["judge_confidence"] == "0/2"


# --- explanation/issue pick: borderline > confirmed > cleared, tie -> call 1 -- #
def test_pick_prefers_borderline_explanation():
    agg = aggregate_family(
        CANDS[0],
        _v("confirmed", explanation="own voice", issue="evaluative_adjective"),
        _v("borderline", explanation="both readings hold", issue="loaded_term"))
    assert agg["explanation"] == "both readings hold"   # borderline wins
    assert agg["issue"] == "loaded_term"                # issue follows the pick


def test_pick_confirmed_when_no_borderline():
    # confirmed + cleared -> borderline tier, but explanation comes from confirmed.
    agg = aggregate_family(
        CANDS[0],
        _v("cleared", explanation="defensible", issue=None),
        _v("confirmed", explanation="own voice", issue="evaluative_adjective"))
    assert agg["tier"] == "borderline"
    assert agg["explanation"] == "own voice"
    assert agg["issue"] == "evaluative_adjective"


def test_pick_tie_breaks_to_call_one():
    agg = aggregate_family(
        CANDS[0],
        _v("confirmed", explanation="first", issue="loaded_term"),
        _v("confirmed", explanation="second", issue="hedging"))
    assert agg["explanation"] == "first"                # call 1 wins the tie


def test_pick_issue_falls_back_to_hint_when_null():
    agg = aggregate_family(
        CANDS[0],
        _v("confirmed", explanation="x", issue=None),
        _v("confirmed", explanation="y", issue=None))
    assert agg["issue"] == "evaluative_adjective"       # candidate issue_hint


def test_missing_vote_treated_as_cleared():
    # one judge omits this candidate -> (confirmed, cleared) -> borderline.
    assert aggregate_family(CANDS[0], _v("confirmed"), None)["tier"] == "borderline"
    assert aggregate_family(CANDS[0], None, None)["tier"] == "cleared"


# --- aggregate_judgments: build findings / borderline / cleared / debug ------ #
def test_aggregate_judgments_splits_three_tiers():
    j1 = [_v("confirmed") | {"candidate_id": 1},
          {"candidate_id": 2, "verdict": "borderline", "explanation": "both",
           "issue": "loaded_term"}]
    j2 = [{"candidate_id": 1, "verdict": "confirmed", "explanation": "own voice",
           "issue": "evaluative_adjective"},
          {"candidate_id": 2, "verdict": "cleared", "explanation": "d", "issue": None}]
    findings, borderline, cleared, debug = aggregate_judgments(CANDS, j1, j2)
    # cid1 both confirmed -> finding; cid2 borderline+cleared -> borderline
    assert [f["excerpt"] for f in findings] == ["devastating"]
    assert [b["excerpt"] for b in borderline] == ["prudent"]
    assert cleared == 0
    # confirmed finding carries judge_confidence 2/2 + judge_votes
    f = findings[0]
    assert f["judge_confidence"] == "2/2"
    assert f["judge_votes"] == "confirmed 2/2"
    assert set(f.keys()) == {
        "excerpt", "issue", "explanation", "finding_valid",
        "extraction_confidence", "judge_confidence", "judge_votes"}
    # borderline entry carries the honest vote split, no finding_valid
    b = borderline[0]
    assert b["judge_votes"] == "borderline 1/2 · cleared 1/2"
    assert set(b.keys()) == {
        "excerpt", "issue", "explanation", "extraction_confidence", "judge_votes"}
    # debug carries both votes + tier for every family
    assert {d["excerpt"]: d["tier"] for d in debug} == {
        "devastating": "confirmed", "prudent": "borderline"}


def test_aggregate_judgments_cleared_dropped_and_counted():
    j = [{"candidate_id": 1, "verdict": "cleared", "explanation": "d", "issue": None},
         {"candidate_id": 2, "verdict": "cleared", "explanation": "d", "issue": None}]
    findings, borderline, cleared, debug = aggregate_judgments(CANDS, j, j)
    assert findings == [] and borderline == []
    assert cleared == 2
    assert all(d["tier"] == "cleared" for d in debug)


def test_aggregate_judgments_confirmed_needs_both():
    # confirmed in call 1 only -> borderline, NOT confirmed.
    j1 = [{"candidate_id": 1, "verdict": "confirmed", "explanation": "x", "issue": "e"}]
    j2 = [{"candidate_id": 1, "verdict": "cleared", "explanation": "y", "issue": None}]
    findings, borderline, cleared, _ = aggregate_judgments([CANDS[0]], j1, j2)
    assert findings == []
    assert len(borderline) == 1


# --------------------------------------------------------------------------- #
# BiasComposite orchestration (fake agents)
# --------------------------------------------------------------------------- #
class FakeAgent:
    def __init__(self, model, structured):
        self.model = model
        self.temperature = 0.5
        self.reasoning = "none"
        self.max_tokens = 32000
        self.output_schema = {"type": "object"}  # mirror the real Agent interface
        self._structured = structured
        self.calls: list[dict] = []
        self.reset_count = 0

    async def run(self, message=None, context=None, **kw):
        self.calls.append({"message": message, "context": context})
        return AgentResult(
            content="", structured=self._structured, cost_usd=0.02,
            tokens_used=500, model=self.model, provider="FakeProv")

    def reset_call_metrics(self):
        self.reset_count += 1


class RaisingAgent(FakeAgent):
    async def run(self, message=None, context=None, **kw):
        self.calls.append({"message": message, "context": context})
        raise AgentError("boom")


@pytest.mark.asyncio
async def test_composite_runs_extract_then_judge_and_maps():
    extractor = FakeAgent(
        "deepseek/deepseek-v4-pro",
        {"candidates": [
            {"excerpt": "devastating", "issue_hint": "evaluative_adjective"},
            {"excerpt": "quietly doubled", "issue_hint": "passive_obscuring"},
        ]})
    judge = FakeAgent(
        "anthropic/claude-opus-4.6",
        {"judgments": [
            {"candidate_id": 1, "explanation": "own voice", "issue": "evaluative_adjective",
             "verdict": "confirmed"},
            {"candidate_id": 2, "explanation": "both readings hold", "issue": "passive_obscuring",
             "verdict": "borderline"},
        ], "reader_note": "The article calls the impact devastating in its own voice."})
    comp = BiasComposite(extractor, judge, name="bias_language")

    res = await comp.run("msg", context={"article_body": ARTICLE, "bias_card": {"x": 1}})

    # two extraction passes, TWO judge votes (identical input to both)
    assert len(extractor.calls) == 2
    assert len(judge.calls) == 2
    assert extractor.calls[0]["message"] == EXTRACT_MESSAGE
    assert extractor.calls[0]["context"] == {"article_body": ARTICLE}
    assert judge.calls[0]["message"] == JUDGE_MESSAGE
    assert judge.calls[0]["context"] == judge.calls[1]["context"]   # identical
    # judge sees the numbered candidate list (id/excerpt/issue_hint only)
    jc = judge.calls[0]["context"]
    assert jc["article_body"] == ARTICLE
    assert [c["candidate_id"] for c in jc["candidates"]] == [1, 2]
    assert set(jc["candidates"][0].keys()) == {"candidate_id", "excerpt", "issue_hint"}

    # both votes identical -> cid1 confirmed (2/2), cid2 borderline (2/2)
    findings = res.structured["language_bias"]["findings"]
    borderline = res.structured["language_bias"]["borderline"]
    assert len(findings) == 1
    assert findings[0]["excerpt"] == "devastating"
    assert findings[0]["finding_valid"] is True
    assert findings[0]["judge_confidence"] == "2/2"
    assert findings[0]["judge_votes"] == "confirmed 2/2"
    assert len(borderline) == 1
    assert borderline[0]["excerpt"] == "quietly doubled"
    assert borderline[0]["judge_votes"] == "borderline 2/2"
    assert "finding_valid" not in borderline[0]
    assert res.structured["reader_note"].startswith("The article calls")

    # aggregated metrics: 2 extract + 2 judge = 4 calls * 0.02 / 500
    assert comp.last_cost_usd == pytest.approx(0.08)
    assert comp.last_tokens == 2000
    # loud metrics
    x = comp.extra_log_fields
    assert x["union_size"] == 2 and x["confirmed_count"] == 1
    assert x["borderline_count"] == 1 and x["cleared_count"] == 0
    assert x["judge_disagreements"] == 0            # identical votes
    assert x["judge_skipped"] is False
    assert x["extractor_model"] == "deepseek/deepseek-v4-pro"
    assert x["judge_model"] == "anthropic/claude-opus-4.6"
    assert x["judge1_provider"] == "FakeProv" and x["judge2_provider"] == "FakeProv"


@pytest.mark.asyncio
async def test_composite_empty_candidates_skips_judge():
    extractor = FakeAgent("deepseek/deepseek-v4-pro", {"candidates": []})
    judge = FakeAgent("anthropic/claude-opus-4.6", {"judgments": [], "reader_note": "x"})
    comp = BiasComposite(extractor, judge)

    res = await comp.run("m", context={"article_body": ARTICLE})

    assert len(extractor.calls) == 2
    assert judge.calls == []                       # judge skipped
    assert res.structured["language_bias"]["findings"] == []
    assert res.structured["language_bias"]["borderline"] == []   # valid-empty
    assert res.structured["reader_note"] == ""     # valid-empty path
    assert comp.extra_log_fields["judge_skipped"] is True
    assert comp.extra_log_fields["union_size"] == 0
    assert comp.extra_log_fields["borderline_count"] == 0
    assert comp.extra_log_fields["cleared_count"] == 0


@pytest.mark.asyncio
async def test_composite_one_extractor_failure_still_proceeds():
    # A single failed extraction pass must not sink the stage (redundancy).
    good = FakeAgent(
        "deepseek/deepseek-v4-pro",
        {"candidates": [{"excerpt": "prudent", "issue_hint": "loaded_term"}]})
    judge = FakeAgent(
        "anthropic/claude-opus-4.6",
        {"judgments": [{"candidate_id": 1, "explanation": "x", "issue": "loaded_term",
                        "verdict": "confirmed"}], "reader_note": "note"})
    # extractor that fails on the 2nd of its two invocations: simulate by a
    # wrapper agent alternating success/failure.
    class Flaky(FakeAgent):
        def __init__(self, *a):
            super().__init__(*a)
            self._n = 0

        async def run(self, message=None, context=None, **kw):
            self.calls.append({"message": message})
            self._n += 1
            if self._n == 2:
                raise AgentError("second pass down")
            return AgentResult(content="", structured=self._structured,
                               cost_usd=0.02, tokens_used=500, model=self.model,
                               provider="FakeProv")
    extractor = Flaky(
        "deepseek/deepseek-v4-pro",
        {"candidates": [{"excerpt": "prudent", "issue_hint": "loaded_term"}]})
    comp = BiasComposite(extractor, judge)
    res = await comp.run("m", context={"article_body": ARTICLE})
    # one pass survived -> union built -> judge ran -> one confirmed finding
    assert res.structured["language_bias"]["findings"][0]["excerpt"] == "prudent"


@pytest.mark.asyncio
async def test_composite_both_extractors_fail_raises():
    extractor = RaisingAgent("deepseek/deepseek-v4-pro", {})
    judge = FakeAgent("anthropic/claude-opus-4.6", {"judgments": [], "reader_note": ""})
    comp = BiasComposite(extractor, judge)
    with pytest.raises(AgentError):
        await comp.run("m", context={"article_body": ARTICLE})
    assert judge.calls == []


def test_composite_reset_clears_accumulators_and_underlying():
    extractor = FakeAgent("deepseek/deepseek-v4-pro", {"candidates": []})
    judge = FakeAgent("anthropic/claude-opus-4.6", {"judgments": [], "reader_note": ""})
    comp = BiasComposite(extractor, judge)
    comp.last_cost_usd = 1.0
    comp.last_tokens = 10
    comp.extra_log_fields = {"x": 1}
    comp.last_judgments_debug = [{"excerpt": "x"}]
    comp.reset_call_metrics()
    assert comp.last_cost_usd == 0.0 and comp.last_tokens == 0
    assert comp.extra_log_fields == {}
    assert comp.last_judgments_debug == []
    assert extractor.reset_count == 1 and judge.reset_count == 1


@pytest.mark.asyncio
async def test_composite_cleared_dropped_and_debug_breakdown():
    # confirmed + borderline + cleared, one each -> findings=1, borderline=1,
    # cleared dropped but counted; the grid-facing debug carries all three.
    extractor = FakeAgent(
        "deepseek/deepseek-v4-pro",
        {"candidates": [
            {"excerpt": "devastating", "issue_hint": "evaluative_adjective"},
            {"excerpt": "quietly doubled", "issue_hint": "passive_obscuring"},
            {"excerpt": "prudent", "issue_hint": "loaded_term"},
        ]})
    judge = FakeAgent(
        "anthropic/claude-opus-4.6",
        {"judgments": [
            {"candidate_id": 1, "explanation": "own voice", "issue": "evaluative_adjective",
             "verdict": "confirmed"},
            {"candidate_id": 2, "explanation": "both hold", "issue": "passive_obscuring",
             "verdict": "borderline"},
            {"candidate_id": 3, "explanation": "defensible", "issue": None,
             "verdict": "cleared"},
        ], "reader_note": "note"})
    comp = BiasComposite(extractor, judge)
    res = await comp.run("m", context={"article_body": ARTICLE})

    # both judge votes identical -> cid1 confirmed, cid2 borderline, cid3 cleared
    assert len(res.structured["language_bias"]["findings"]) == 1
    assert len(res.structured["language_bias"]["borderline"]) == 1
    x = comp.extra_log_fields
    assert (x["confirmed_count"], x["borderline_count"], x["cleared_count"]) == (1, 1, 1)
    assert x["judge_disagreements"] == 0
    # measurement-only debug: every family's aggregated tier + both votes +
    # position, incl. cleared (needed by the full-flip gate). Not rendered.
    dbg = {d["excerpt"]: d["tier"] for d in comp.last_judgments_debug}
    assert dbg == {"devastating": "confirmed", "quietly doubled": "borderline",
                   "prudent": "cleared"}
    assert all(d["v1"] and d["v2"] for d in comp.last_judgments_debug)
    assert all(d["pos"] >= 0 and d["end"] > d["pos"] for d in comp.last_judgments_debug)


# --------------------------------------------------------------------------- #
# Runner surfaces the loud metrics
# --------------------------------------------------------------------------- #
def test_runner_surfaces_extra_log_fields():
    class Stage:
        agent = MagicMock(
            last_cost_usd=0.06, last_tokens=1500,
            fallback_marker_key=None,
            extra_log_fields={"union_size": 4, "confirmed_count": 2,
                              "invalid_span_drops": 1, "judge_skipped": False,
                              "extractor_model": "deepseek/deepseek-v4-pro"})
    # MagicMock auto-creates last_qa_fallback_used; force the hasattr-gated path off
    del Stage.agent.last_qa_fallback_used
    out = _collect_agent_metrics(Stage())
    assert out["cost_usd"] == pytest.approx(0.06)
    assert out["union_size"] == 4
    assert out["confirmed_count"] == 2
    assert out["invalid_span_drops"] == 1
    assert out["extractor_model"] == "deepseek/deepseek-v4-pro"


# --------------------------------------------------------------------------- #
# Judge schema field order (load-bearing)
# --------------------------------------------------------------------------- #
def test_judge_schema_field_order_explanation_before_verdict():
    item = BIAS_JUDGE_SCHEMA["properties"]["judgments"]["items"]
    props = list(item["properties"].keys())
    assert props == ["candidate_id", "explanation", "issue", "verdict"]
    assert props.index("explanation") < props.index("issue")
    assert props.index("explanation") < props.index("verdict")


def test_judge_schema_verdict_is_ternary_enum():
    item = BIAS_JUDGE_SCHEMA["properties"]["judgments"]["items"]
    verdict = item["properties"]["verdict"]
    assert verdict["type"] == "string"
    assert verdict["enum"] == ["confirmed", "borderline", "cleared"]
    # issue stays nullable (null for cleared); verdict required, no is_bias.
    assert item["properties"]["issue"]["type"] == ["string", "null"]
    assert item["required"] == ["candidate_id", "explanation", "issue", "verdict"]
    assert "is_bias" not in item["properties"]


def test_candidates_schema_shape():
    props = BIAS_CANDIDATES_SCHEMA["properties"]["candidates"]["items"]
    assert set(props["properties"].keys()) == {"excerpt", "issue_hint"}
    assert props["additionalProperties"] is False
    assert props["required"] == ["excerpt", "issue_hint"]


# --------------------------------------------------------------------------- #
# Exact request bodies for all three calls (via create_agents wiring)
# --------------------------------------------------------------------------- #
async def _captured_kwargs(agent: Agent, output_schema=None) -> dict:
    agent._client.chat.completions.create = AsyncMock(return_value=MagicMock())
    await agent._call_with_retry(
        messages=[{"role": "user", "content": "x"}], tools=None,
        output_schema=output_schema)
    return agent._client.chat.completions.create.call_args.kwargs


def _composite(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents
    return create_agents()["bias_language"]


@pytest.mark.asyncio
async def test_extractor_request_body_exact(monkeypatch):
    comp = _composite(monkeypatch)
    kw = await _captured_kwargs(comp.extractor, output_schema=BIAS_CANDIDATES_SCHEMA)
    assert kw["model"] == "deepseek/deepseek-v4-pro"
    assert kw["temperature"] == 0.8
    assert kw["extra_body"]["reasoning"] == {"effort": "none"}
    # fp8 pin present (+ require_parameters injected for schema calls)
    prov = kw["extra_body"]["provider"]
    assert prov["order"] == ["baidu/fp8", "wandb/fp8", "parasail/fp8"]
    assert prov["allow_fallbacks"] is False
    assert prov["quantizations"] == ["fp8"]
    assert prov["require_parameters"] is True
    assert kw["response_format"]["json_schema"]["schema"] == BIAS_CANDIDATES_SCHEMA


@pytest.mark.asyncio
async def test_judge_request_body_exact(monkeypatch):
    comp = _composite(monkeypatch)
    kw = await _captured_kwargs(comp.judge, output_schema=BIAS_JUDGE_SCHEMA)
    assert kw["model"] == "anthropic/claude-opus-4.6"
    assert kw["temperature"] == 0.1
    assert kw["max_tokens"] == 32000                       # Agent default
    assert kw["extra_body"]["reasoning"] == {"effort": "none"}
    assert kw["extra_body"]["provider"] == {"require_parameters": True}  # no pin
    assert kw["response_format"]["json_schema"]["schema"] == BIAS_JUDGE_SCHEMA


def test_create_agents_bias_is_composite_both_variants(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-for-unit-test")
    from scripts.run import create_agents, create_agents_hydrated
    for d in (create_agents(), create_agents_hydrated()):
        bl = d["bias_language"]
        assert isinstance(bl, BiasComposite)
        assert bl.extractor.model == "deepseek/deepseek-v4-pro"
        assert bl.extractor.temperature == 0.8
        assert bl.extractor.reasoning == "none"
        assert bl.judge.model == "anthropic/claude-opus-4.6"
        assert bl.judge.temperature == 0.1


# --------------------------------------------------------------------------- #
# New bias_borderline_candidates slot (optional_write / valid-empty) + stage
# --------------------------------------------------------------------------- #
def test_borderline_slot_metadata_optional_and_empty_default():
    from src.bus import TopicBus
    field = TopicBus.model_fields["bias_borderline_candidates"]
    extra = field.json_schema_extra or {}
    assert extra.get("optional_write") is True
    assert extra.get("visibility") == ["tp", "mcp"]      # same as findings slot
    assert TopicBus().bias_borderline_candidates == []   # valid-empty default


def test_bias_stage_declares_borderline_write():
    from src.agent_stages import BiasLanguageStage
    assert "bias_borderline_candidates" in BiasLanguageStage.writes
    # existing findings/reader_note writes remain
    assert "bias_language_findings" in BiasLanguageStage.writes
    assert "bias_reader_note" in BiasLanguageStage.writes


# --------------------------------------------------------------------------- #
# Transparency card: borderline section renders ONLY when non-empty
# --------------------------------------------------------------------------- #
def _tp_with(borderline):
    return {
        "bias_analysis": {
            "language": [],
            "borderline": borderline,
            "source": {"by_language": {}, "total": 0},
            "framing": {"cluster_count": 0, "distinct_actor_count": 0},
        },
        "sources": [],
    }


def test_card_borderline_section_absent_when_empty():
    from scripts.render import build_bias_card
    html = build_bias_card(_tp_with([]))
    assert "Borderline formulations" not in html


def test_card_borderline_section_renders_when_present():
    from scripts.render import build_bias_card
    html = build_bias_card(_tp_with([
        {"excerpt": "quietly doubled", "issue": "passive_obscuring",
         "explanation": "reads two ways", "extraction_confidence": "1/2",
         "judge_votes": "confirmed 1/2 · cleared 1/2"},
    ]))
    assert "Borderline formulations" in html
    assert "Defensible readings exist on both sides" in html
    assert "quietly doubled" in html
    assert "reads two ways" in html
    # honest vote split rendered when present (TASK-BIAS-DUAL-JUDGE)
    assert "confirmed 1/2 · cleared 1/2" in html


def test_card_findings_unaffected_by_borderline_absence():
    # existing findings render path is byte-compatible: a confirmed finding
    # still renders whether or not a borderline key is present.
    from scripts.render import build_bias_card
    tp = _tp_with([])
    tp["bias_analysis"]["language"] = [
        {"excerpt": "devastating", "issue": "evaluative_adjective",
         "explanation": "own voice", "finding_valid": True}
    ]
    html = build_bias_card(tp)
    assert "devastating" in html and "own voice" in html
    assert "Borderline formulations" not in html
