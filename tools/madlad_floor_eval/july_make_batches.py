#!/usr/bin/env python3
"""july_make_batches.py — emit BLIND judge batches from july_pairs.json.

TASK-MADLAD-FLOOR-LABELSET Phase 1, step 4a. The on/off-topic label is assigned
from the NATIVE finding text only — no MADLAD output, no cosine, no outlet, no
language tag in the judge context (circularity + bias guards). This script writes
per-batch JSON containing only {pair_id, finding_text (native), topic_title,
topic_summary}; the main agent spawns one Opus-4.8 subagent per batch (judges are
spawned subagents, never direct API — the standing eval rule).

Output: scratch/floor-eval/batches/batch-NN.json, each
        {batch_id, n, pairs:[{pair_id, finding_text, topic_title, topic_summary}]}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BATCH_SIZE = 24
LANG_ORDER = ["ar", "zh", "ja", "th", "bn", "ne"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=str(REPO / "scratch/floor-eval/july_pairs.json"))
    ap.add_argument("--out-dir", default=str(REPO / "scratch/floor-eval/batches"))
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = ap.parse_args()

    pairs = json.loads(Path(args.pairs).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("batch-*.json"):
        old.unlink()

    # batch WITHIN language (one script per batch keeps the judge focused)
    by_lang: dict[str, list] = {}
    for p in pairs:
        by_lang.setdefault(p["language"], []).append(p)

    n_batch = 0
    manifest = []
    for lang in LANG_ORDER:
        recs = sorted(by_lang.get(lang, []), key=lambda p: p["pair_id"])
        for i in range(0, len(recs), args.batch_size):
            chunk = recs[i:i + args.batch_size]
            bid = f"{n_batch:02d}"
            payload = {
                "batch_id": bid, "language": lang, "n": len(chunk),
                "pairs": [{
                    "pair_id": p["pair_id"],
                    "finding_text": p["finding_text"],
                    "topic_title": p["topic_title"],
                    "topic_summary": p["topic_text"].split(p["topic_title"], 1)[-1].strip()
                    if p["topic_title"] and p["topic_title"] in p["topic_text"]
                    else p["topic_text"],
                } for p in chunk],
            }
            (out_dir / f"batch-{bid}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            manifest.append({"batch_id": bid, "language": lang, "n": len(chunk)})
            n_batch += 1

    (out_dir / "manifest.json").write_text(
        json.dumps({"n_batches": n_batch, "batch_size": args.batch_size,
                    "batches": manifest}, indent=2), encoding="utf-8")
    print(f"wrote {n_batch} batches to {out_dir}")
    for m in manifest:
        print(f"  batch-{m['batch_id']}: {m['language']} n={m['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
