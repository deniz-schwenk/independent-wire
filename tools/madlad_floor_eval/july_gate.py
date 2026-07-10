#!/usr/bin/env python3
"""july_gate.py — per-language floor GO/NO-GO for the 6 non-Latin target langs.

TASK-MADLAD-FLOOR-LABELSET Phase 2. Consumes july_labeled.json and reports, per
target language, the floor behaviour native vs MADLAD-English at T=0.55:
  * off-topic-above-0.55 rate  (precision / false-admit at the assign floor)
  * on-topic recall at 0.55     (does translation recover on-topic findings?)
  * orphan rate                 (per unique finding: best candidate cos < 0.55)

GO criterion (per the task): translated off-topic-above-floor rate <= native rate
AND within the validated-language reference band from the rescued June results
(native 8.23% / English 6.81%). Borderline is NOT self-decided — flagged ESCALATE.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

T = 0.55
# validated-language June reference band (MADLAD-INTEGRATION-REQUIREMENTS §1)
REF_NATIVE_OFF = 0.0823
REF_ENGLISH_OFF = 0.0681
BAND_CEILING = 0.0823          # "within band" = translated off-rate <= validated native
OFF_TOL = 0.005                # translated may not exceed native off-rate by > this
LANG_ORDER = ["ar", "zh", "ja", "th", "bn", "ne"]
SINGLE_DAY = {"zh", "ja"}      # feeds landed 07-06 -> only 07-07 data (documented)


def rate(num, den):
    return round(num / den, 4) if den else None


def lang_metrics(rows: list[dict]) -> dict:
    off = [r for r in rows if r["label"] == 0]
    on = [r for r in rows if r["label"] == 1]
    nat_off = sum(1 for r in off if r["native_cos"] >= T)
    eng_off = sum(1 for r in off if r["english_cos"] >= T)
    nat_on = sum(1 for r in on if r["native_cos"] >= T)
    eng_on = sum(1 for r in on if r["english_cos"] >= T)
    # per-finding orphan: best candidate cos < T
    by_find: dict[str, dict] = {}
    for r in rows:
        b = by_find.setdefault(r["uid"], {"n": -1.0, "e": -1.0})
        b["n"] = max(b["n"], r["native_cos"]); b["e"] = max(b["e"], r["english_cos"])
    n_find = len(by_find)
    nat_orph = sum(1 for b in by_find.values() if b["n"] < T)
    eng_orph = sum(1 for b in by_find.values() if b["e"] < T)
    return {
        "n_pairs": len(rows), "n_off": len(off), "n_on": len(on), "n_findings": n_find,
        "days": sorted({r["day"] for r in rows}),
        "off_above_floor_native": rate(nat_off, len(off)),
        "off_above_floor_english": rate(eng_off, len(off)),
        "on_recall_native": rate(nat_on, len(on)),
        "on_recall_english": rate(eng_on, len(on)),
        "orphan_rate_native": rate(nat_orph, n_find),
        "orphan_rate_english": rate(eng_orph, n_find),
    }


def verdict(m: dict, lang: str) -> tuple[str, str]:
    no, eo = m["off_above_floor_native"], m["off_above_floor_english"]
    if no is None or eo is None or m["n_off"] < 5:
        return "ESCALATE", f"too few off-topic labels (n_off={m['n_off']}) for a stable rate"
    safety = eo <= no + OFF_TOL
    in_band = eo <= BAND_CEILING
    if safety and in_band:
        base = "GO"
        note = f"translated off {eo:.3f} <= native {no:.3f}, within band (<= {BAND_CEILING})"
    elif not safety:
        base = "NO-GO"
        note = f"translated off {eo:.3f} EXCEEDS native {no:.3f}+tol — admits more off-topic"
    else:
        base = "ESCALATE"
        note = f"translated off {eo:.3f} <= native {no:.3f} but ABOVE band ceiling {BAND_CEILING}"
    if lang in SINGLE_DAY and base == "GO":
        base = "GO*"
        note += "; *single-day (07-07) data only — feeds landed 07-06, lacks >=3-day spread"
    return base, note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", default=str(Path(__file__).resolve().parents[2]
                                             / "scratch/floor-eval/july_labeled.json"))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    labeled = json.loads(Path(args.labeled).read_text(encoding="utf-8"))
    by_lang: dict[str, list] = {}
    for r in labeled:
        by_lang.setdefault(r["language"], []).append(r)

    out = {"T": T, "reference": {"native_off": REF_NATIVE_OFF, "english_off": REF_ENGLISH_OFF,
                                 "band_ceiling": BAND_CEILING}, "per_language": {}}
    print(f"{'lang':<5}{'n':>5}{'off':>5}{'on':>4}  {'off@.55 nat->eng':>18}  "
          f"{'recall nat->eng':>16}  {'orphan nat->eng':>16}  verdict")
    for lang in LANG_ORDER:
        rows = by_lang.get(lang)
        if not rows:
            print(f"{lang:<5}  (no labels)")
            continue
        m = lang_metrics(rows)
        v, note = verdict(m, lang)
        m["verdict"], m["verdict_note"] = v, note
        out["per_language"][lang] = m
        print(f"{lang:<5}{m['n_pairs']:>5}{m['n_off']:>5}{m['n_on']:>4}  "
              f"{str(m['off_above_floor_native']):>8}->{str(m['off_above_floor_english']):<8}  "
              f"{str(m['on_recall_native']):>7}->{str(m['on_recall_english']):<7}  "
              f"{str(m['orphan_rate_native']):>7}->{str(m['orphan_rate_english']):<7}  {v}")
    for lang in LANG_ORDER:
        if lang in out["per_language"]:
            print(f"  {lang}: {out['per_language'][lang]['verdict']} — "
                  f"{out['per_language'][lang]['verdict_note']}")
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
