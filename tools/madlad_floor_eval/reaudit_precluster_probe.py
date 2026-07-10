#!/usr/bin/env python3
"""reaudit_precluster_probe.py — pre-cluster floor (cosine 0.30) merge probe.

TASK-MADLAD-FLOOR-LABELSET Phase 0/2. Runs in the PRODUCTION .venv. The
pre-cluster stage merges findings by average-linkage at distance_threshold=0.7
(= cosine-sim 0.30). This is the documented raw pairwise proxy (spec §1): among
finding-finding pairs, what fraction sit >=0.30 (would risk a merge), native vs
MADLAD-English?

  * unrelated pairs = two findings on-topic for DIFFERENT topics -> a >=0.30
    cosine is a SPURIOUS cross-topic merge (lower is safer).
  * related pairs = two findings on-topic for the SAME topic -> a >=0.30 cosine
    is a genuine merge retained (higher is better).

Reference (validated-language calibration set, spec §1): unrelated >=0.30
fraction 0.110 -> 0.083 (drops under English); related 0.813 -> 0.779.

Deterministic sampling (seed fixed). Reuses the finding native/English text
rules from reaudit_score. Optional --language filter for the per-language P2 probe.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from itertools import combinations
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.stages.coherence import _cosine_normalized, _get_default_embedder  # noqa: E402
from src.stages.gravitational_assign import _finding_text  # noqa: E402
from madlad_common import ENGLISH_LANGS, FLORES, norm_lang  # noqa: E402

FLOOR = 0.30
MAX_PAIRS_PER_CLASS = 20000  # deterministic cap so the probe stays cheap


def english_text(pair: dict, tmap: dict) -> str:
    uid = pair["uid"]
    lang = norm_lang(pair.get("language"))
    tr = tmap.get(uid)
    if lang in ENGLISH_LANGS or lang not in FLORES or tr is None:
        return pair["native_text"]
    return _finding_text({"title": tr.get("title_en") or "",
                          "summary": tr.get("summary_en") or "", "description": ""})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labelset", required=True)
    ap.add_argument("--translation-map", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--language", default=None,
                    help="restrict findings to this language (per-language P2 probe)")
    ap.add_argument("--seed", type=int, default=20260707)
    args = ap.parse_args()

    pairs = json.loads(Path(args.labelset).read_text(encoding="utf-8"))
    tmap = json.loads(Path(args.translation_map).read_text(encoding="utf-8"))

    # One record per finding: its native/english text + the set of topics it is
    # on-topic for (label==1), keyed by (day, finding_id) so cross-day findings
    # never collide.
    findings: dict[tuple, dict] = {}
    for p in pairs:
        if args.language and norm_lang(p.get("language")) != args.language:
            continue
        key = (p["day"], p["finding_id"])
        rec = findings.setdefault(key, {
            "native": p["native_text"], "english": english_text(p, tmap),
            "on_topics": set(), "lang": norm_lang(p.get("language"))})
        if int(p["label"]) == 1:
            rec["on_topics"].add((p["day"], p["topic_idx"]))

    # Keep only findings that are on-topic for >=1 topic (needed to classify pairs)
    keys = [k for k, r in findings.items() if r["on_topics"]]
    if len(keys) < 2:
        Path(args.out).write_text(json.dumps(
            {"error": "too few on-topic findings", "n": len(keys),
             "language": args.language}, indent=2), encoding="utf-8")
        print(f"too few on-topic findings ({len(keys)}) for probe"
              f"{' lang=' + args.language if args.language else ''}")
        return 0

    # Embed unique texts once
    uniq_nat = sorted({findings[k]["native"] for k in keys})
    uniq_eng = sorted({findings[k]["english"] for k in keys})
    emb = _get_default_embedder()
    nat_map = {t: v for t, v in zip(uniq_nat, _cosine_normalized(emb.embed_batch(uniq_nat)))}
    eng_map = {t: v for t, v in zip(uniq_eng, _cosine_normalized(emb.embed_batch(uniq_eng)))}

    # Classify + (deterministically) sample finding-finding pairs
    rng = random.Random(args.seed)
    related, unrelated = [], []
    all_pairs = list(combinations(keys, 2))
    rng.shuffle(all_pairs)
    for a, b in all_pairs:
        ta, tb = findings[a]["on_topics"], findings[b]["on_topics"]
        if ta & tb:
            if len(related) < MAX_PAIRS_PER_CLASS:
                related.append((a, b))
        elif not (ta & tb):
            if len(unrelated) < MAX_PAIRS_PER_CLASS:
                unrelated.append((a, b))
        if len(related) >= MAX_PAIRS_PER_CLASS and len(unrelated) >= MAX_PAIRS_PER_CLASS:
            break

    def frac_ge(sample, arm_map, key):
        if not sample:
            return None, 0
        c = 0
        for a, b in sample:
            va, vb = arm_map[findings[a][key]], arm_map[findings[b][key]]
            if float(va @ vb) >= FLOOR:
                c += 1
        return round(c / len(sample), 4), len(sample)

    res = {
        "language": args.language, "floor": FLOOR, "seed": args.seed,
        "n_findings": len(keys),
        "unrelated_native_ge_floor": frac_ge(unrelated, nat_map, "native")[0],
        "unrelated_english_ge_floor": frac_ge(unrelated, eng_map, "english")[0],
        "n_unrelated_pairs": len(unrelated),
        "related_native_ge_floor": frac_ge(related, nat_map, "native")[0],
        "related_english_ge_floor": frac_ge(related, eng_map, "english")[0],
        "n_related_pairs": len(related),
        "reference_calibration": {"unrelated": [0.110, 0.083], "related": [0.813, 0.779]},
    }
    Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"probe{' lang=' + args.language if args.language else ' (all langs)'}: "
          f"findings={len(keys)}")
    print(f"  unrelated >=0.30: native {res['unrelated_native_ge_floor']} -> "
          f"english {res['unrelated_english_ge_floor']}  (n={len(unrelated)}, ref 0.110->0.083)")
    print(f"  related   >=0.30: native {res['related_native_ge_floor']} -> "
          f"english {res['related_english_ge_floor']}  (n={len(related)}, ref 0.813->0.779)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
