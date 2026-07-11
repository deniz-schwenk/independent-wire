#!/usr/bin/env python3
"""july_ingest_labels.py — merge Opus-4.8 subagent verdicts into labelled pairs.

TASK-MADLAD-FLOOR-LABELSET Phase 1, step 4c. Reads the per-batch judge responses
(scratch/floor-eval/labels_raw/batch-NN.json, each a JSON list of
{pair_id, label, reason}) produced by the spawned Opus-4.8 subagents, merges the
on/off-topic labels into july_pairs.json, and emits:

  * scratch/floor-eval/july_labeled.json  — full labelled pairs (Phase-2 gate
    input; carries native_text so the pre-cluster probe can be reused).
  * docs/evals/madlad-floor-gate/labels/{lang}.json  — TRACKED compact labels.
  * docs/evals/madlad-floor-gate/labels/architect_review_sample.json — TRACKED
    10% stratified (language x label) sample WITH text, for the ARCHITECT's
    independent BLIND second-review (a spawned Opus-4.8 subagent, no human step).
    Phase 2 results are provisional until this blind spot-check passes.
  * docs/evals/madlad-floor-gate/labels/_meta.json — counts, seed, method.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LABELS_DIR = REPO / "docs/evals/madlad-floor-gate/labels"
SEED = 20260707
SAMPLE_FRAC = 0.10
LANG_ORDER = ["ar", "zh", "ja", "th", "bn", "ne"]


def _load_raw(raw_dir: Path) -> dict[str, dict]:
    """pair_id -> {label, reason} across all batch response files. Tolerant of a
    bare list or {labels:[...]} wrapper."""
    out: dict[str, dict] = {}
    for f in sorted(raw_dir.glob("batch-*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        rows = data.get("labels") if isinstance(data, dict) else data
        for r in rows:
            pid = r["pair_id"]
            lab = int(r["label"])
            if lab not in (0, 1):
                continue
            out[pid] = {"label": lab, "reason": (r.get("reason") or "").strip()[:200]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(REPO / "scratch/floor-eval/july_pairs.json"))
    ap.add_argument("--raw-dir", default=str(REPO / "scratch/floor-eval/labels_raw"))
    ap.add_argument("--out", default=str(REPO / "scratch/floor-eval/july_labeled.json"))
    args = ap.parse_args()

    pairs = json.loads(Path(args.pairs).read_text(encoding="utf-8"))
    raw = _load_raw(Path(args.raw_dir))

    labeled, missing = [], []
    for p in pairs:
        v = raw.get(p["pair_id"])
        if v is None:
            missing.append(p["pair_id"])
            continue
        labeled.append({**p, "native_text": p["finding_text"],
                        "label": v["label"], "judge_note": v["reason"]})

    if missing:
        print(f"WARNING: {len(missing)} pairs unlabeled (first few: {missing[:5]})",
              file=sys.stderr)

    Path(args.out).write_text(json.dumps(labeled, ensure_ascii=False, indent=1),
                              encoding="utf-8")

    # tracked compact labels per language
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    per_lang_counts = {}
    for lang in LANG_ORDER:
        recs = [{
            "pair_id": p["pair_id"], "uid": p["uid"], "day": p["day"],
            "finding_id": p["finding_id"], "topic_idx": p["topic_idx"],
            "topic_title": p["topic_title"], "label": p["label"],
            "judge_note": p["judge_note"],
            "native_cos": p["native_cos"], "english_cos": p["english_cos"],
        } for p in labeled if p["language"] == lang]
        if not recs:
            continue
        (LABELS_DIR / f"{lang}.json").write_text(
            json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
        per_lang_counts[lang] = {
            "n": len(recs), "on": sum(1 for r in recs if r["label"] == 1),
            "off": sum(1 for r in recs if r["label"] == 0),
            "days": sorted({r["day"] for r in recs}),
        }

    # 10% stratified (language x label) Architect blind-review sample WITH text
    rng = random.Random(SEED)
    strata: dict[tuple, list] = {}
    for p in labeled:
        strata.setdefault((p["language"], p["label"]), []).append(p)
    sample = []
    for key, recs in sorted(strata.items()):
        recs = sorted(recs, key=lambda p: p["pair_id"])
        rng.shuffle(recs)
        k = max(1, round(len(recs) * SAMPLE_FRAC))
        for p in recs[:k]:
            sample.append({
                "pair_id": p["pair_id"], "language": p["language"],
                "day": p["day"], "finding_text": p["finding_text"],
                "topic_title": p["topic_title"], "topic_text": p["topic_text"],
                "assigned_label": p["label"],
                "label_meaning": "on-topic" if p["label"] == 1 else "off-topic",
                "judge_note": p["judge_note"],
            })
    (LABELS_DIR / "architect_review_sample.json").write_text(
        json.dumps(sorted(sample, key=lambda s: s["pair_id"]),
                   ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {
        "seed": SEED, "sample_frac": SAMPLE_FRAC,
        "n_labeled": len(labeled), "n_unlabeled": len(missing),
        "n_human_sample": len(sample),
        "by_language": per_lang_counts,
        "method": "Opus-4.8 spawned subagents, blind: native finding text + "
                  "English topic title/summary only; no MADLAD output, no cosine, "
                  "no outlet in judge context (circularity + bias guards).",
    }
    (LABELS_DIR / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"labeled {len(labeled)} pairs ({len(missing)} unlabeled)")
    for lang in LANG_ORDER:
        c = per_lang_counts.get(lang)
        if c:
            print(f"  {lang}: n={c['n']} on={c['on']} off={c['off']} days={len(c['days'])}")
    print(f"architect blind-review sample: {len(sample)} pairs -> {LABELS_DIR}/architect_review_sample.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
