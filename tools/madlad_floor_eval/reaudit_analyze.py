#!/usr/bin/env python3
"""reaudit_analyze.py — native vs MADLAD-English floor metrics + calibration gate.

TASK-MADLAD-FLOOR-LABELSET Phase 0, step 4. Consumes scored.json and reproduces
the June re-audit table at T=0.55, then checks the SELF-CALIBRATION GATE: the
rebuilt harness must reproduce the rescued reference numbers
(scratch/MADLAD-INTEGRATION-REQUIREMENTS.md §1) within tolerance. If it cannot,
the gate FAILS and new-language measurement must not proceed on an uncalibrated
instrument.

Reference (native @0.55 validity anchor, English @0.55):
  native : assigned 486, off 40, off-rate 8.23%, recall 0.577, precision 0.9177
  english: assigned 470, off 32, off-rate 6.81%, recall 0.5666, precision 0.9319
  off-topic rate shift −1.42pp (DOWNWARD); cosine shifts negative; topics>50% = 0
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import mean

T = 0.55

REF = {
    "native": {"assigned": 486, "off": 40, "off_rate": 0.0823, "recall": 0.577},
    "english": {"assigned": 470, "off": 32, "off_rate": 0.0681, "recall": 0.5666},
    "off_rate_delta_pp": -1.42,
}


def arm_metrics(scored: list[dict], key: str, total_on: int) -> dict:
    assigned = [p for p in scored if p[key] >= T]
    off = sum(1 for p in assigned if p["label"] == 0)
    n = len(assigned)
    on_assigned = n - off
    # per-topic off% among assigned
    per_topic: dict[tuple, list[int]] = {}
    for p in assigned:
        per_topic.setdefault((p["day"], p["topic_idx"]), []).append(p["label"])
    topic_off_pct = [100.0 * (len(v) - sum(v)) / len(v) for v in per_topic.values()]
    return {
        "assigned": n,
        "off_topic": off,
        "on_topic": on_assigned,
        "off_rate": round(off / n, 4) if n else 0.0,
        "precision": round(on_assigned / n, 4) if n else 0.0,
        "recall": round(on_assigned / total_on, 4) if total_on else 0.0,
        "topics_over_50pct_off": sum(1 for x in topic_off_pct if x > 50.0),
        "n_topics": len(per_topic),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    scored = json.loads(Path(args.scored).read_text(encoding="utf-8"))
    total_on = sum(1 for p in scored if p["label"] == 1)

    nat = arm_metrics(scored, "native_cos", total_on)
    eng = arm_metrics(scored, "english_cos", total_on)

    # cosine shifts (english - native), overall and non-English only
    def shift(pred):
        d = [p["english_cos"] - p["native_cos"] for p in scored if pred(p)]
        return round(mean(d), 4) if d else 0.0
    non_en = lambda p: p["language"] not in ("en", "eng", "english")
    shifts = {
        "on_topic_all": shift(lambda p: p["label"] == 1),
        "off_topic_all": shift(lambda p: p["label"] == 0),
        "on_topic_nonEN": shift(lambda p: p["label"] == 1 and non_en(p)),
        "off_topic_nonEN": shift(lambda p: p["label"] == 0 and non_en(p)),
    }

    # per-language mean cosine shift (non-English) + off-rate native vs english
    langs = sorted({p["language"] for p in scored if non_en(p)})
    per_lang = {}
    for lg in langs:
        sub = [p for p in scored if p["language"] == lg]
        na = arm_metrics(sub, "native_cos", sum(1 for p in sub if p["label"] == 1))
        en = arm_metrics(sub, "english_cos", sum(1 for p in sub if p["label"] == 1))
        per_lang[lg] = {
            "n_pairs": len(sub),
            "mean_cos_shift": round(mean(p["english_cos"] - p["native_cos"] for p in sub), 4),
            "native_off_rate": na["off_rate"], "english_off_rate": en["off_rate"],
            "native_assigned": na["assigned"], "english_assigned": en["assigned"],
        }

    # --- calibration gate ---
    def close(a, b, tol):
        return abs(a - b) <= tol
    checks = {
        "native_assigned_486_pm2": close(nat["assigned"], 486, 2),
        "native_off_40_pm2": close(nat["off_topic"], 40, 2),
        "native_off_rate_8.23pm0.4": close(nat["off_rate"] * 100, 8.23, 0.4),
        "native_recall_0.577pm0.01": close(nat["recall"], 0.577, 0.01),
        "english_assigned_470_pm3": close(eng["assigned"], 470, 3),
        "english_off_rate_6.81pm0.5": close(eng["off_rate"] * 100, 6.81, 0.5),
        "off_rate_shift_downward": eng["off_rate"] < nat["off_rate"],
        "cos_shift_on_negative": shifts["on_topic_all"] < 0,
        "cos_shift_off_negative": shifts["off_topic_all"] < 0,
        "off_drops_more_than_on": shifts["off_topic_all"] < shifts["on_topic_all"],
        "native_no_topic_over_50": nat["topics_over_50pct_off"] == 0,
        "english_no_topic_over_50": eng["topics_over_50pct_off"] == 0,
        "all_perlang_shift_negative": all(v["mean_cos_shift"] < 0 for v in per_lang.values()),
    }
    passed = all(checks.values())

    result = {
        "T": T, "n_pairs": len(scored), "total_on_labeled": total_on,
        "native": nat, "english": eng,
        "off_rate_delta_pp": round((eng["off_rate"] - nat["off_rate"]) * 100, 2),
        "cosine_shifts": shifts,
        "per_language": per_lang,
        "reference": REF,
        "calibration_checks": checks,
        "calibration_gate": "PASS" if passed else "FAIL",
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    print(f"\n{'metric':<22}{'native':>10}{'english':>10}{'ref-nat':>10}{'ref-eng':>10}")
    for k in ("assigned", "off_topic", "off_rate", "precision", "recall"):
        rn = REF["native"].get(k, ""); re_ = REF["english"].get(k, "")
        print(f"{k:<22}{str(nat[k]):>10}{str(eng[k]):>10}{str(rn):>10}{str(re_):>10}")
    print(f"\noff-rate shift: {result['off_rate_delta_pp']:+.2f}pp (ref −1.42pp)")
    print(f"cosine shifts: {shifts}")
    print("\nper-language (mean cos shift | native->english off-rate):")
    for lg, v in per_lang.items():
        print(f"  {lg}: shift {v['mean_cos_shift']:+.4f}  "
              f"off {v['native_off_rate']:.3f}->{v['english_off_rate']:.3f}  n={v['n_pairs']}")
    print("\ncalibration checks:")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\n=== CALIBRATION GATE: {result['calibration_gate']} ===")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
