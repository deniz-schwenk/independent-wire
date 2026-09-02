"""TASK-BIAS-LEXICON — deterministic canonical-term candidates.

Three prompt generations held judged coverage (D1) at ~3.3, and the `regime`
canary — four own-voice uses in one article — was found 0 times by the newest
prompt while a string scan finds all four. This module tests the string scan:
its own-voice boundary, its matching, and how its output joins the union
without becoming a vote.
"""
from __future__ import annotations

import json

import pytest

from src.bias_composite import (
    EXTRACTOR_CANDIDATE_CAP,
    build_union,
    load_lexicon,
    quoted_spans,
    scan_lexicon,
)

LEX = (("regime", "loaded_term"), ("effectively", "intensifier"),
       ("reportedly", "hedging"), ("a blow", "evaluative_adjective"),
       ("mistakes were made", "passive_obscuring"))


# --------------------------------------------------------------- the file
def test_shipped_lexicon_is_wellformed_and_every_entry_is_sourced():
    lex = load_lexicon()
    assert 25 <= len(lex) <= 40, "seed list is contracted to ~25-40 entries"
    raw = json.loads((__import__("pathlib").Path(__file__).resolve().parents[1]
                      / "config" / "bias_lexicon.json").read_text())
    terms = raw["terms"]
    assert len({t["term"] for t in terms}) == len(terms), "duplicate term"
    for t in terms:
        assert t["term"] and t["term"] == t["term"].strip()
        assert t["issue_hint"] in {
            "evaluative_adjective", "intensifier", "loaded_term",
            "emotionalizing", "passive_obscuring", "hedging"}
        assert t.get("note"), f"{t['term']} carries no source note"


def test_missing_lexicon_file_is_not_fatal(caplog, tmp_path):
    load_lexicon.cache_clear()
    try:
        assert load_lexicon(str(tmp_path / "nope.json")) == ()
        assert any("model-only" in r.getMessage().lower() for r in caplog.records)
    finally:
        load_lexicon.cache_clear()


# ------------------------------------------------------- the quote boundary
def test_boundary_is_quotation_marks_not_attributed_sentences():
    """The v3 canary lesson, pinned. An attributed sentence that PARAPHRASES a
    source still uses the article's own word choice, so it must be scanned."""
    body = 'Officials said the regime would fall within weeks.'
    assert quoted_spans(body) == []
    assert [c["excerpt"] for c in scan_lexicon(body, LEX)] == ["regime"]


def test_inside_straight_double_quotes_is_skipped():
    body = 'The minister said "the regime is finished" on Tuesday.'
    assert [c["excerpt"] for c in scan_lexicon(body, LEX)] == []


@pytest.mark.parametrize("o,c", [("“", "”"), ("‘", "’"),
                                 ("«", "»")])
def test_typographic_and_guillemet_quotes_are_honoured(o, c):
    body = f"The minister said {o}the regime is finished{c} on Tuesday."
    assert scan_lexicon(body, LEX) == []


def test_apostrophes_are_not_treated_as_quotes():
    """A straight apostrophe is a contraction or a possessive in English prose;
    treating it as a quote mark would blank out most of an article."""
    body = "The council's decision didn't stop the regime's collapse."
    assert [c["excerpt"] for c in scan_lexicon(body, LEX)] == ["regime"]


def test_term_outside_quotes_survives_when_another_occurrence_is_quoted():
    body = 'The regime moved first. An aide said "the regime is finished".'
    assert [c["excerpt"] for c in scan_lexicon(body, LEX)] == ["regime"]


def test_nested_attribution_inside_a_quote_is_still_quoted():
    body = 'He said "officials told us the regime would fall" on Tuesday.'
    assert scan_lexicon(body, LEX) == []


# ------------------------------------------------------------ the matching
def test_word_boundary_prevents_substring_hits():
    body = "The regimental band played. Reportedly effective measures followed."
    got = {c["excerpt"].lower() for c in scan_lexicon(body, LEX)}
    assert "regime" not in got            # 'regimental'
    assert "effectively" not in got       # 'effective'
    assert "reportedly" in got            # this one IS a whole word


def test_match_is_case_insensitive_and_the_excerpt_is_verbatim():
    body = "Reportedly, the Regime moved first."
    got = {c["excerpt"] for c in scan_lexicon(body, LEX)}
    assert got == {"Reportedly", "Regime"}   # article's own capitalisation


def test_multiword_term_matches_across_whitespace_runs():
    body = "The report concluded that mistakes   were\nmade in the process."
    got = [c for c in scan_lexicon(body, LEX)]
    assert got and got[0]["issue_hint"] == "passive_obscuring"
    assert got[0]["excerpt"] in body       # verbatim, so build_union accepts it


def test_one_candidate_per_distinct_wording():
    body = "The regime fell. The regime returned. The regime endured."
    assert len(scan_lexicon(body, LEX)) == 1


def test_output_is_ordered_by_position():
    body = "Reportedly the regime effectively fell."
    assert [c["excerpt"] for c in scan_lexicon(body, LEX)] == [
        "Reportedly", "regime", "effectively"]


def test_empty_lexicon_and_empty_body_are_no_ops():
    assert scan_lexicon("The regime fell.", ()) == []
    assert scan_lexicon("", LEX) == []


# ------------------------------------------------------------- the union
BODY = "The regime effectively dealt a blow to the plan. Officials called it prudent."


def test_lexicon_only_family_is_flagged_and_carries_no_fake_vote():
    cands, stats = build_union([[], [], []], BODY,
                               lexicon_candidates=scan_lexicon(BODY, LEX))
    assert cands, "lexicon alone must be able to populate the union"
    for c in cands:
        assert c["source"] == "lexicon"
        assert c["extraction_confidence"] == "lexicon"   # never "0/3"
    assert stats["lexicon_only_families"] == len(cands)


def test_model_family_keeps_its_confidence_when_the_lexicon_agrees():
    runs = [[{"excerpt": "regime", "issue_hint": "loaded_term"}]] * 3
    cands, _ = build_union(runs, BODY, lexicon_candidates=scan_lexicon(BODY, LEX))
    regime = [c for c in cands if c["excerpt"] == "regime"][0]
    assert regime["extraction_confidence"] == "3/3"   # NOT 4/3, NOT 4/4
    assert regime["source"] == "model"


def test_denominator_is_model_passes_only():
    runs = [[{"excerpt": "prudent", "issue_hint": "loaded_term"}], [], []]
    cands, _ = build_union(runs, BODY, lexicon_candidates=scan_lexicon(BODY, LEX))
    prudent = [c for c in cands if c["excerpt"] == "prudent"][0]
    assert prudent["extraction_confidence"] == "1/3"


def test_lexicon_is_exempt_from_the_per_pass_cap():
    body = " ".join(f"term{i} regime" for i in range(40))
    lex_hits = [{"excerpt": f"term{i}", "issue_hint": "loaded_term"}
                for i in range(40)]
    cands, stats = build_union([[], [], []], body, cap=EXTRACTOR_CANDIDATE_CAP,
                               lexicon_candidates=lex_hits)
    assert stats["lexicon_candidates"] == 40
    assert len(cands) == 40, "the cap must not evict lexicon candidates"


def test_model_passes_are_still_capped_with_a_lexicon_present():
    body = " ".join(f"w{i}" for i in range(60))
    run = [{"excerpt": f"w{i}", "issue_hint": "loaded_term"} for i in range(30)]
    cands, stats = build_union([run, [], []], body, cap=18,
                               lexicon_candidates=[])
    assert stats["union_size"] == 18


def test_lexicon_excerpt_not_in_body_is_dropped_and_counted():
    cands, stats = build_union(
        [[], [], []], BODY,
        lexicon_candidates=[{"excerpt": "not in the article", "issue_hint": "hedging"}])
    assert cands == []
    assert stats["lexicon_span_drops"] == 1
    assert stats["invalid_span_drops"] == 1


def test_no_lexicon_argument_reproduces_the_old_behaviour():
    runs = [[{"excerpt": "prudent", "issue_hint": "loaded_term"}], [], []]
    a, sa = build_union(runs, BODY)
    b, sb = build_union(runs, BODY, lexicon_candidates=[])
    assert a == b and sa == sb
    assert [c["excerpt"] for c in a] == ["prudent"]
    assert a[0]["source"] == "model"
    assert sa["lexicon_candidates"] == 0 and sa["lexicon_only_families"] == 0


def test_the_regime_canary_the_prompt_line_could_not_close():
    """Four own-voice uses in one article; prompt v3 found zero."""
    body = ("Sanctions aim to sever every lifeline supporting the Iranian regime. "
            "El Pais reported the objective remains to bring down the Iranian "
            "regime. One specialist doubted sanctions would collapse the regime. "
            "Gulf states preferred pressure to regime collapse.")
    hits = scan_lexicon(body, LEX)
    assert [c["excerpt"] for c in hits] == ["regime"]      # one distinct wording
    cands, _ = build_union([[], [], []], body, lexicon_candidates=hits)
    assert len(cands) == 1 and cands[0]["source"] == "lexicon"
    # and every occurrence is reachable from that one candidate
    assert body.count("regime") == 4
