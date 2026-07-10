#!/usr/bin/env python3
"""latin_baseline.py — native clustering baseline for non-English Latin languages.

TASK-MADLAD-FLOOR-LABELSET Phase 3. Deterministic, $0, no LLM. READ-ONLY over the
production run states for 2026-07-01..07-07: joins each day's `curator_findings`
language field with the `gravitational_assign` outcome (per-finding assignment
cosine / orphan best-similarity, both persisted in `curator_topic_assignments`).

Purpose: the agreed rule "if non-English Latin scripts cluster measurably worse
natively, extend translation to them later" needs a quantified baseline. Reports
per-language orphan rate and assignment-cosine distribution. NO decision here.

For context (free from the same states) it also reports the non-Latin target
languages' native orphan rates — the direct comparison the extension rule needs.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from madlad_common import norm_lang  # noqa: E402

LATIN = ["es", "pt", "vi", "de", "tr", "fr", "it", "uz", "zu", "sw"]
NON_LATIN_TARGETS = ["ar", "zh", "ja", "th", "bn", "ne"]
DAYS = [f"2026-07-0{i}" for i in range(1, 8)]
T = 0.55


def _finding_idx(sid: str) -> int:
    return int(sid.split("finding-")[-1])


def collect(day: str) -> dict[int, dict]:
    """finding_index -> {lang, best_cos, assigned} for one day, or {} if no snap."""
    snaps = glob.glob(str(REPO / "output" / day / "_state" / "run-*"
                          / "run_bus.gravitational_assign.json"))
    if not snaps:
        return {}
    d = json.loads(Path(snaps[0]).read_text(encoding="utf-8"))
    findings = d.get("curator_findings") or []
    a = d.get("curator_topic_assignments") or {}
    best: dict[int, float] = {}
    assigned: set[int] = set()
    for t in a.get("topics", []):
        for asg in t.get("assignments", []):
            fi = _finding_idx(asg["source_id"])
            best[fi] = max(best.get(fi, -1.0), float(asg["similarity"]))
            assigned.add(fi)
    for o in a.get("orphans", []):
        fi = _finding_idx(o["source_id"])
        best.setdefault(fi, float(o.get("best_similarity") or 0.0))
    out: dict[int, dict] = {}
    for fi, f in enumerate(findings):
        out[fi] = {
            "lang": norm_lang(f.get("language")),
            "best_cos": best.get(fi, 0.0),
            "assigned": fi in assigned,
        }
    return out


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    orph = sum(1 for r in rows if not r["assigned"])
    best = np.array([r["best_cos"] for r in rows], dtype=float)
    asg = np.array([r["best_cos"] for r in rows if r["assigned"]], dtype=float)
    pct = lambda a, q: round(float(np.percentile(a, q)), 4) if a.size else None
    return {
        "n": n,
        "n_orphans": orph,
        "orphan_rate": round(orph / n, 4),
        "best_cos_mean": round(float(best.mean()), 4),
        "best_cos_p10": pct(best, 10), "best_cos_p50": pct(best, 50),
        "best_cos_p90": pct(best, 90),
        "assigned_cos_mean": round(float(asg.mean()), 4) if asg.size else None,
        "assigned_cos_median": pct(asg, 50),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    per_lang: dict[str, list[dict]] = {}
    per_day_counts: dict[str, int] = {}
    for day in DAYS:
        rows = collect(day)
        per_day_counts[day] = len(rows)
        for r in rows.values():
            per_lang.setdefault(r["lang"], []).append(r)

    latin = {lg: summarize(per_lang.get(lg, [])) for lg in LATIN}
    non_latin = {lg: summarize(per_lang.get(lg, [])) for lg in NON_LATIN_TARGETS}
    en = summarize(per_lang.get("en", []))

    result = {
        "days": DAYS, "threshold": T, "per_day_finding_counts": per_day_counts,
        "english_reference": en,
        "latin_baseline": latin,
        "non_latin_context": non_latin,
    }
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    def row(lg, s):
        if not s.get("n"):
            return f"  {lg:<4} n=0"
        return (f"  {lg:<4} n={s['n']:<5} orphan={s['orphan_rate']*100:5.1f}%  "
                f"best_cos[p10/p50/p90]={s['best_cos_p10']}/{s['best_cos_p50']}/{s['best_cos_p90']}  "
                f"assigned_cos_mean={s['assigned_cos_mean']}")
    print(f"days {DAYS[0]}..{DAYS[-1]}  T={T}")
    print(f"EN reference: {row('en', en)}")
    print("Latin baseline (non-English Latin script):")
    for lg in LATIN:
        print(row(lg, latin[lg]))
    print("Non-Latin targets (native, context for the extension rule):")
    for lg in NON_LATIN_TARGETS:
        print(row(lg, non_latin[lg]))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
