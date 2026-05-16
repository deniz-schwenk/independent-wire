"""Sweep harness — determinism + minimal-correctness tests.

The sweep is read-only on production code, but the recomputed-assignment
math (per brief watch-item: determinism of the helper) needs a lock-down
to keep future numpy / threshold changes from silently shifting Phase-1
output. We use a synthetic per_day dict so the test stays self-contained
and never loads the real audit data."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.sweep_gravitational_recalibration import (
    CAP,
    THRESHOLDS,
    VARIANTS,
    _finding_idx_from_id,
    metrics_for_config,
)


def _synth_per_day() -> dict:
    """Two-day, two-topic synthetic dataset with hand-rolled similarities
    and labels chosen so each (T, V) row's metrics are predictable."""
    # Day A: 4 findings × 2 topics; topic-0 is audited.
    #   finding-0: sim_v1 to topic-0 = 0.60, to topic-1 = 0.20 — on-topic
    #   finding-1: sim_v1 to topic-0 = 0.40, to topic-1 = 0.10 — off-topic
    #   finding-2: sim_v1 to topic-0 = 0.32, to topic-1 = 0.05 — off-topic
    #   finding-3: sim_v1 to topic-0 = 0.10, to topic-1 = 0.55 — never assigned to topic-0
    sim_v1_A = np.array(
        [
            [0.60, 0.20],
            [0.40, 0.10],
            [0.32, 0.05],
            [0.10, 0.55],
        ]
    )
    sim_v2_A = np.array(
        [
            [0.50, 0.18],
            [0.35, 0.08],
            [0.28, 0.04],
            [0.05, 0.45],
        ]
    )
    audited_A = [
        {
            "bundle_idx": 0,
            "topic_idx": 0,
            "title": "Synth topic A",
            "summary": "",
            "source_count": 3,
            "labels": [
                ("finding-0", 1),
                ("finding-1", 0),
                ("finding-2", 0),
            ],
        }
    ]
    day_A = {
        "date": "2026-01-01",
        "n_findings": 4,
        "n_topics": 2,
        "sim_v1": sim_v1_A,
        "sim_v2": sim_v2_A,
        "audited": audited_A,
    }

    # Day B: 3 findings × 1 topic; topic-0 is audited.
    #   finding-0: sim 0.45 on
    #   finding-1: sim 0.31 on
    #   finding-2: sim 0.29 off (below 0.30 even at baseline)
    sim_v1_B = np.array([[0.45], [0.31], [0.29]])
    sim_v2_B = np.array([[0.40], [0.20], [0.20]])
    audited_B = [
        {
            "bundle_idx": 0,
            "topic_idx": 0,
            "title": "Synth topic B",
            "summary": "",
            "source_count": 2,
            "labels": [
                ("finding-0", 1),
                ("finding-1", 1),
            ],
        }
    ]
    day_B = {
        "date": "2026-01-02",
        "n_findings": 3,
        "n_topics": 1,
        "sim_v1": sim_v1_B,
        "sim_v2": sim_v2_B,
        "audited": audited_B,
    }
    return {"2026-01-01": day_A, "2026-01-02": day_B}


def test_finding_idx_from_id_round_trip():
    assert _finding_idx_from_id("finding-0") == 0
    assert _finding_idx_from_id("finding-12") == 12
    assert _finding_idx_from_id("finding-999") == 999


def test_metrics_for_config_determinism_two_runs():
    """Same input ⇒ byte-identical output across repeated calls."""
    per_day = _synth_per_day()
    first = metrics_for_config(per_day, 0.30, "V1")
    second = metrics_for_config(per_day, 0.30, "V1")
    assert first == second


def test_metrics_for_config_baseline_recall_one():
    """At T=0.30 V1 every label whose similarity is ≥ 0.30 is retained;
    on_full equals on_retained for any topic whose audited findings all
    cross the production threshold."""
    per_day = _synth_per_day()
    m = metrics_for_config(per_day, 0.30, "V1")
    # day A topic-0: on=1, off=2 retained; on_full=1, recall=1.0
    # day B topic-0: finding-0 (0.45, on) retained, finding-1 (0.31, on) retained → on=2 retained, on_full=2, recall=1.0
    recalls = [t["recall"] for t in m["per_topic"]]
    assert all(r == 1.0 for r in recalls if r is not None)


def test_metrics_for_config_threshold_drops_findings_monotonically_v1():
    """V1 raises shrink the audited retained set (same embeddings, just
    higher cut). Audited findings retained is monotone non-increasing in T."""
    per_day = _synth_per_day()
    prev_total_retained = None
    for T in THRESHOLDS:
        m = metrics_for_config(per_day, T, "V1")
        total = sum(t["n_retained"] for t in m["per_topic"])
        if prev_total_retained is not None:
            assert total <= prev_total_retained, (
                f"V1 retained count not monotone at T={T}: {total} > {prev_total_retained}"
            )
        prev_total_retained = total


def test_metrics_for_config_orphan_count_matches_distribution():
    """Orphan count equals the '0' bucket in assignments_per_finding."""
    per_day = _synth_per_day()
    for V in VARIANTS:
        for T in THRESHOLDS:
            m = metrics_for_config(per_day, T, V)
            assert m["n_orphans"] == m["assignments_per_finding_pre_cap"]["0"]


def test_metrics_for_config_weighted_off_pct_matches_per_topic_sum():
    """Aggregate weighted off% = total_off / (total_on + total_off)
    across all per-topic rows."""
    per_day = _synth_per_day()
    for V in VARIANTS:
        for T in THRESHOLDS:
            m = metrics_for_config(per_day, T, V)
            sum_on = sum(t["on_retained"] for t in m["per_topic"])
            sum_off = sum(t["off_retained"] for t in m["per_topic"])
            sum_total = sum_on + sum_off
            expected = (100.0 * sum_off / sum_total) if sum_total else 0.0
            assert m["weighted_off_topic_pct"] == round(expected, 2)


def test_metrics_for_config_post_cap_assignments_capped_at_cap():
    """No finding contributes more than CAP to n_assignments_post_cap.
    Sanity-check against the pre-cap distribution."""
    per_day = _synth_per_day()
    for V in VARIANTS:
        for T in THRESHOLDS:
            m = metrics_for_config(per_day, T, V)
            d = m["assignments_per_finding_pre_cap"]
            expected = (
                0 * d["0"]
                + 1 * d["1"]
                + 2 * d["2"]
                + 3 * d["3"]
                + CAP * d["4+"]  # cap binds for 4+
            )
            assert m["n_assignments_post_cap"] == expected
