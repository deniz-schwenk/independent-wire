"""TASK-EXTRACTOR-BREADTH part 1 — round-robin per-pass cap in build_union.

The cap VALUE is unchanged (18, a downstream judge-cost constraint). What
changed is the truncation rule: `run[:cap]` kept the first 18 items in raw
model order, which deletes whole trailing pattern families under a
sweep-structured prompt that emits candidates pattern by pattern. `_cap_run`
takes items round-robin across `issue_hint` instead.
"""
from __future__ import annotations

from collections import Counter

import pytest

from src.bias_composite import EXTRACTOR_CANDIDATE_CAP, _cap_run, build_union

PATTERNS = ["evaluative_adjective", "intensifier", "loaded_term",
            "emotionalizing", "passive_obscuring"]


def _sweep_run(per_pattern: int, patterns=PATTERNS) -> list[dict]:
    """A pass shaped the way prompt v2 emits: pattern by pattern, not interleaved."""
    return [{"excerpt": f"{p}_{i}", "issue_hint": p}
            for p in patterns for i in range(per_pattern)]


# --------------------------------------------------------------------- (a)
def test_thirty_item_five_pattern_pass_keeps_every_pattern():
    run = _sweep_run(6)                       # 30 items, 5 patterns x 6
    assert len(run) == 30
    kept = _cap_run(run, 18)

    assert len(kept) == 18
    counts = Counter(item["issue_hint"] for item in kept)
    assert set(counts) == set(PATTERNS), "a whole pattern family was truncated away"
    assert min(counts.values()) >= 3 and max(counts.values()) <= 4, counts


def test_head_truncation_would_have_lost_the_trailing_patterns():
    """The regression this fix exists for, stated as a test rather than a claim."""
    run = _sweep_run(6)
    head = run[:18]
    assert set(Counter(i["issue_hint"] for i in head)) == set(PATTERNS[:3])
    assert PATTERNS[3] not in {i["issue_hint"] for i in head}
    assert PATTERNS[4] not in {i["issue_hint"] for i in head}
    # round-robin keeps all five
    assert set(i["issue_hint"] for i in _cap_run(run, 18)) == set(PATTERNS)


def test_within_a_pattern_the_models_own_order_decides():
    run = _sweep_run(6)
    kept = _cap_run(run, 18)
    ev = [i["excerpt"] for i in kept if i["issue_hint"] == "evaluative_adjective"]
    assert ev == [f"evaluative_adjective_{i}" for i in range(len(ev))]


# --------------------------------------------------------------------- (b)
@pytest.mark.parametrize("n", [0, 1, 17, 18])
def test_pass_at_or_under_the_cap_is_untouched_and_order_preserved(n):
    run = [{"excerpt": f"w{i}", "issue_hint": PATTERNS[i % 5]} for i in range(n)]
    out = _cap_run(run, 18)
    assert out == run                          # same items, same order
    assert out is not run                      # and a copy, not the caller's list


def test_single_pattern_pass_still_truncates_head_first():
    """One bucket => round-robin degenerates to the old behaviour exactly."""
    run = [{"excerpt": f"w{i}", "issue_hint": "loaded_term"} for i in range(30)]
    kept = _cap_run(run, 18)
    assert [i["excerpt"] for i in kept] == [f"w{i}" for i in range(18)]


# --------------------------------------------------------------------- (c)
@pytest.mark.parametrize("hint", [None, "", 7, [], {"x": 1}])
def test_unknown_or_missing_issue_hint_never_crashes(hint):
    run = [{"excerpt": f"w{i}", "issue_hint": hint} for i in range(25)]
    kept = _cap_run(run, 18)
    assert len(kept) == 18
    assert [i["excerpt"] for i in kept] == [f"w{i}" for i in range(18)]


def test_issue_hint_key_entirely_absent_never_crashes():
    run = [{"excerpt": f"w{i}"} for i in range(25)]
    assert len(_cap_run(run, 18)) == 18


def test_non_dict_items_do_not_crash_the_cap():
    run = ["not a dict", None, 42] + [{"excerpt": f"w{i}", "issue_hint": "a"}
                                      for i in range(20)]
    kept = _cap_run(run, 18)
    assert len(kept) == 18
    # build_union drops the non-dicts downstream; the cap must not raise on them
    assert any(isinstance(i, dict) for i in kept)


def test_unlabelled_items_go_last_and_never_displace_a_pattern():
    run = ([{"excerpt": f"u{i}"} for i in range(10)]            # unlabelled FIRST
           + [{"excerpt": f"n{i}", "issue_hint": "loaded_term"} for i in range(20)])
    kept = _cap_run(run, 18)
    assert all("issue_hint" in i for i in kept), \
        "an unlabelled item displaced a named-pattern item"


def test_unlabelled_items_fill_the_room_the_patterns_leave():
    run = ([{"excerpt": f"n{i}", "issue_hint": "loaded_term"} for i in range(5)]
           + [{"excerpt": f"u{i}"} for i in range(20)])
    kept = _cap_run(run, 18)
    assert len(kept) == 18
    assert [i["excerpt"] for i in kept[:5]] == [f"n{i}" for i in range(5)]
    assert [i["excerpt"] for i in kept[5:]] == [f"u{i}" for i in range(13)]


# --------------------------------------------------------------------- (d)
def test_build_union_applies_the_round_robin_cap_per_pass():
    """End-to-end through build_union: a sweep-shaped 30-item pass reaches the
    union with all five patterns represented, not the first three."""
    run = _sweep_run(6)
    body = " ".join(item["excerpt"] for item in run)
    cands, stats = build_union([run, [], []], body, cap=18)

    assert stats["union_size"] == 18
    assert set(c["issue_hint"] for c in cands) == set(PATTERNS)


def test_build_union_default_cap_is_still_eighteen():
    assert EXTRACTOR_CANDIDATE_CAP == 18
    run = _sweep_run(10)                       # 50 items
    body = " ".join(item["excerpt"] for item in run)
    cands, _ = build_union([run, [], []], body)
    assert len(cands) == 18
