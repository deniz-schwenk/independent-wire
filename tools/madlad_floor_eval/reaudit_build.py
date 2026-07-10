#!/usr/bin/env python3
"""reaudit_build.py — reconstruct the 2,542-label off-topic calibration set.

TASK-MADLAD-FLOOR-LABELSET Phase 0, step 1 (harness rebuild). The original
re-audit harness (reaudit_build/translate/score/analyze) was lost to a scratch
cleanup; this rebuilds it, git-tracked, from the documented method
(scratch/MADLAD-INTEGRATION-REQUIREMENTS.md §1, §9).

The 2,542 labelled (finding, topic) pairs live in the May cluster-quality audit
`audit-2026-05-16`, untracked in the working tree since `e2d917f` but recoverable
from git `310a55d`. Each per-topic bundle `topic-NN.json` carries the NATIVE
finding text (title/summary/description/language); each `topic-NN.audit.csv`
carries the human on/off-topic label. This script joins them into a flat
`labelset.json` — pure reconstruction, no translation, no embedding.

Input : an extracted copy of `audit-2026-05-16/_data/` (default: the scratch
        working dir; extract with
        `git archive 310a55d docs/cluster-quality-audit/audit-2026-05-16 | tar -x -C <workdir>`).
Output: `<workdir>/labelset.json` — list of pairs, each:
        {day, bundle_idx, topic_idx, topic_title, topic_text, finding_id,
         language, title, summary, description, native_text, label}
        plus `labelset.meta.json` with per-language / per-day counts + provenance.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Production text rules — single source of truth (no drift).
from src.stages.gravitational_assign import _finding_text, _topic_text  # noqa: E402
from madlad_common import norm_lang  # noqa: E402

GIT_REF = "310a55d"
AUDIT_REL = "docs/cluster-quality-audit/audit-2026-05-16"
DAYS = ["2026-05-08", "2026-05-11", "2026-05-13"]


def _day_finding_map(day_dir: Path) -> dict[str, dict]:
    """finding_id -> native finding dict, unioned across all topic bundles that
    day (a finding assigned to several topics appears in several bundles with
    identical text; last write wins, they agree)."""
    out: dict[str, dict] = {}
    for bundle in sorted(day_dir.glob("topic-*.json")):
        b = json.loads(bundle.read_text(encoding="utf-8"))
        for f in b.get("findings", []):
            out[f["source_id"]] = f
    return out


def _map_bundle_to_topic(bundle: dict, topics: list[dict]) -> int:
    """Bundle -> _topics.json index by source_ids set equality, title fallback
    (same logic as the lost harness / reaudit_cluster_quality_recalibrated.py)."""
    bsids = {f["source_id"] for f in bundle.get("findings", [])}
    for ti, t in enumerate(topics):
        if set(t.get("source_ids") or []) == bsids:
            return ti
    btitle = (bundle.get("topic_title") or "").strip()
    for ti, t in enumerate(topics):
        if (t.get("title") or "").strip() == btitle:
            return ti
    raise ValueError(f"could not map bundle {bundle.get('topic_index')} "
                     f"({btitle[:60]!r}) to any topic")


def _load_labels(csv_path: Path) -> list[tuple[str, int, str]]:
    rows: list[tuple[str, int, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            lab = (row.get("is_on_topic") or "").strip()
            if lab not in ("0", "1"):
                continue
            rows.append((row["finding_id"].strip(), int(lab),
                         (row.get("reasoning_note") or "").strip()))
    return rows


def build(data_root: Path) -> tuple[list[dict], dict]:
    pairs: list[dict] = []
    missing = 0
    for day in DAYS:
        day_dir = data_root / day
        topics = json.loads((day_dir / "_topics.json").read_text(encoding="utf-8"))
        findings = _day_finding_map(day_dir)
        for csv_path in sorted(day_dir.glob("topic-*.audit.csv")):
            bundle_idx = int(csv_path.stem.split("topic-")[-1].split(".")[0])
            bundle = json.loads(
                (day_dir / f"topic-{bundle_idx:02d}.json").read_text(encoding="utf-8"))
            topic_idx = _map_bundle_to_topic(bundle, topics)
            topic = topics[topic_idx]
            # bundle carries its own topic_title/summary; assert it agrees with
            # the mapped _topics.json centre (the text June embedded).
            assert (topic.get("title") or "") == (bundle.get("topic_title") or ""), \
                f"topic title drift {day} bundle {bundle_idx}"
            topic_text = _topic_text(topic)
            for finding_id, label, note in _load_labels(csv_path):
                f = findings.get(finding_id)
                if f is None:
                    missing += 1
                    continue
                pairs.append({
                    "day": day,
                    "bundle_idx": bundle_idx,
                    "topic_idx": topic_idx,
                    "topic_title": topic.get("title") or "",
                    "topic_text": topic_text,
                    "finding_id": finding_id,
                    # finding-NNN indexes into a DAY's findings, so it collides
                    # across days (520 collisions here). uid = day:finding_id is
                    # the stable per-finding key for translation/scoring lookups.
                    "uid": f"{day}:{finding_id}",
                    "language": norm_lang(f.get("language")),
                    "title": f.get("title") or "",
                    "summary": f.get("summary") or "",
                    "description": f.get("description") or "",
                    "native_text": _finding_text(f),
                    "label": label,  # 1 = on-topic, 0 = off-topic
                })

    by_lang: dict[str, int] = {}
    by_day: dict[str, int] = {}
    off_by_lang: dict[str, int] = {}
    for p in pairs:
        by_lang[p["language"]] = by_lang.get(p["language"], 0) + 1
        by_day[p["day"]] = by_day.get(p["day"], 0) + 1
        if p["label"] == 0:
            off_by_lang[p["language"]] = off_by_lang.get(p["language"], 0) + 1
    meta = {
        "git_ref": GIT_REF,
        "audit": AUDIT_REL,
        "days": DAYS,
        "n_pairs": len(pairs),
        "n_missing_finding_text": missing,
        "n_on_topic": sum(1 for p in pairs if p["label"] == 1),
        "n_off_topic": sum(1 for p in pairs if p["label"] == 0),
        "by_language": dict(sorted(by_lang.items(), key=lambda kv: -kv[1])),
        "off_by_language": off_by_lang,
        "by_day": by_day,
    }
    return pairs, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", default=str(
        REPO / "scratch/floor-eval" / AUDIT_REL / "_data"),
        help="extracted audit-2026-05-16/_data/ dir")
    ap.add_argument("--out", default=str(REPO / "scratch/floor-eval/labelset.json"))
    args = ap.parse_args()

    data_root = Path(args.data_root)
    if not data_root.exists():
        print(f"ERROR: {data_root} not found. Extract with:\n"
              f"  git archive {GIT_REF} {AUDIT_REL} | tar -x -C scratch/floor-eval/",
              file=sys.stderr)
        return 2

    pairs, meta = build(data_root)
    out = Path(args.out)
    out.write_text(json.dumps(pairs, ensure_ascii=False, indent=1), encoding="utf-8")
    Path(str(out).replace(".json", ".meta.json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"labelset: {meta['n_pairs']} pairs "
          f"({meta['n_on_topic']} on / {meta['n_off_topic']} off), "
          f"missing text: {meta['n_missing_finding_text']}")
    print("by day:", meta["by_day"])
    print("by language:", meta["by_language"])
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
