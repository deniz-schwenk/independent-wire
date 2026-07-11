#!/usr/bin/env python3
"""july_collect.py — sample the 6 target-language findings from July run states.

TASK-MADLAD-FLOOR-LABELSET Phase 1, step 1. Deterministic, READ-ONLY over the
production run states 2026-07-01..07-07. For each target non-Latin language
(ar/zh/ja/th/bn/ne) collects that language's findings + each day's discovered
topics, and deterministically samples findings (seeded, spread across >=3 days)
so the downstream (finding, topic) pair pool clears >=100 pairs/language.

Selection and counts are pure Python (seed recorded). No translation, no
embedding, no LLM here.

Outputs (scratch working dir):
  july_findings.json  — flat list {uid, day, finding_id, language, title, summary}
                        (reaudit_translate input; uid = day:finding_id).
  july_topics.json    — {day: [{topic_idx, title, summary, topic_text}]}.
  july_collect.meta.json — per-language counts, days covered, seed.
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.stages.gravitational_assign import _topic_text  # noqa: E402
from madlad_common import norm_lang  # noqa: E402

TARGETS = ["ar", "zh", "ja", "th", "bn", "ne"]
DAYS = [f"2026-07-0{i}" for i in range(1, 8)]
# per-language finding sample cap (sparse langs take all; dense langs sampled).
SAMPLE_CAP = 45
SEED = 20260707


def _snap(day: str):
    hits = glob.glob(str(REPO / "output" / day / "_state" / "run-*"
                        / "run_bus.gravitational_assign.json"))
    return json.loads(Path(hits[0]).read_text(encoding="utf-8")) if hits else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-findings", default=str(REPO / "scratch/floor-eval/july_findings.json"))
    ap.add_argument("--out-topics", default=str(REPO / "scratch/floor-eval/july_topics.json"))
    ap.add_argument("--cap", type=int, default=SAMPLE_CAP)
    args = ap.parse_args()

    topics_by_day: dict[str, list] = {}
    # lang -> list of finding records
    by_lang: dict[str, list] = {lg: [] for lg in TARGETS}
    for day in DAYS:
        d = _snap(day)
        if d is None:
            continue
        findings = d.get("curator_findings") or []
        topics = (d.get("curator_discovered_topics") or {}).get("topics") or []
        topics_by_day[day] = [{
            "topic_idx": ti, "title": t.get("title") or "",
            "summary": t.get("summary") or "", "topic_text": _topic_text(t),
        } for ti, t in enumerate(topics)]
        for fi, f in enumerate(findings):
            lg = norm_lang(f.get("language"))
            if lg not in TARGETS:
                continue
            title, summary = f.get("title") or "", f.get("summary") or ""
            if not (title.strip() or summary.strip()):
                continue
            by_lang[lg].append({
                "uid": f"{day}:finding-{fi}", "day": day,
                "finding_id": f"finding-{fi}", "language": lg,
                "title": title, "summary": summary,
            })

    rng = random.Random(SEED)
    sampled: list[dict] = []
    meta_lang = {}
    for lg in TARGETS:
        recs = sorted(by_lang[lg], key=lambda r: r["uid"])
        rng.shuffle(recs)
        take = recs[:args.cap]
        # guarantee >=3 distinct days if the language spans them
        days_all = {r["day"] for r in recs}
        days_take = {r["day"] for r in take}
        if len(days_all) >= 3 and len(days_take) < 3:
            for r in recs:
                if r["day"] not in days_take:
                    take.append(r); days_take.add(r["day"])
                    if len(days_take) >= 3:
                        break
        sampled.extend(take)
        meta_lang[lg] = {"available": len(recs), "sampled": len(take),
                         "days_covered": sorted({r["day"] for r in take})}

    Path(args.out_findings).write_text(
        json.dumps(sampled, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(args.out_topics).write_text(
        json.dumps(topics_by_day, ensure_ascii=False, indent=1), encoding="utf-8")
    meta = {"seed": SEED, "days": DAYS, "cap": args.cap,
            "n_findings_sampled": len(sampled), "by_language": meta_lang}
    Path(str(args.out_findings).replace(".json", ".meta.json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"sampled {len(sampled)} findings across {len(TARGETS)} languages")
    for lg in TARGETS:
        m = meta_lang[lg]
        print(f"  {lg}: {m['sampled']}/{m['available']} findings, "
              f"days={len(m['days_covered'])} {m['days_covered']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
