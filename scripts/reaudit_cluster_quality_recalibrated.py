#!/usr/bin/env python3
"""Re-audit cluster quality after the gravitational-recalibration pin.

Phase 3 of TASK-GRAVITATIONAL-RECALIBRATION.md.

The original audit at ``docs/cluster-quality-audit/audit-2026-05-16/``
labelled 2,542 (finding, topic) pairs against the same 30 topics across
three eval days. Recalibration pinned T=0.55 V1 — title+summary topic-
centre embedding unchanged from production. Because the embedding text
rule did not change, the per-pair similarity at T=0.55 V1 is a strict
filter on the original audit set:

    finding f is assigned to topic K at T=0.55 V1
      ⇔ sim(f, K) ≥ 0.55  (same sim computed under the same V1 embedding)

Every (f, K) pair that was assigned at T=0.30 (the production baseline
of the original audit) and now still passes T=0.55 is a labelled pair —
no new auditing needed. The labels live in the original audit CSVs and
copy forward verbatim.

The harness:

  1. Loads cached topics from
     ``docs/cluster-quality-audit/audit-2026-05-16/_data/{date}/_topics.json``
     and findings from the per-day state files.
  2. Embeds findings + topic centres via the shared fastembed singleton
     (uses the sweep's cache to avoid re-embedding — same .npy files).
  3. Recomputes assignments under the pinned constants.
  4. For each originally-audited topic, intersects the new assigned set
     with the original audit labels.
  5. Writes the recalibrated audit at
     ``docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`` with
     the same file layout as the original.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.stages.coherence import _cosine_normalized, _get_default_embedder  # noqa: E402
from src.stages.gravitational_assign import (  # noqa: E402
    GRAVITATIONAL_THRESHOLD,
    PER_FINDING_CAP,
    _topic_text,
    _finding_text as _grav_finding_text,
)


SRC_AUDIT_ROOT = REPO_ROOT / "docs" / "cluster-quality-audit" / "audit-2026-05-16"
SRC_DATA_ROOT = SRC_AUDIT_ROOT / "_data"

OUT_ROOT = REPO_ROOT / "docs" / "cluster-quality-audit" / "audit-2026-05-16-recalibrated"
OUT_DATA_ROOT = OUT_ROOT / "_data"

# Sweep harness embedding cache — reuse to skip re-embedding.
SWEEP_CACHE_ROOT = (
    REPO_ROOT / "docs" / "gravitational-recalibration-2026-05-16" / "_cache"
)

DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}

TOP_K_TOPICS = 10


def _load_findings(state_path: Path) -> list[dict]:
    with state_path.open() as fh:
        data = json.load(fh)
    return list(data.get("curator_findings") or [])


def _load_topics(date: str) -> list[dict]:
    return json.loads((SRC_DATA_ROOT / date / "_topics.json").read_text(encoding="utf-8"))


def _load_audit_csv_rows(date: str, bundle_idx: int) -> dict[str, dict]:
    """{finding_id: {is_on_topic: int, reasoning_note: str}} for labeled
    rows only."""
    path = SRC_DATA_ROOT / date / f"topic-{bundle_idx:02d}.audit.csv"
    out: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        for row in r:
            label = (row.get("is_on_topic") or "").strip()
            if label not in ("0", "1"):
                continue
            out[row["finding_id"].strip()] = {
                "is_on_topic": int(label),
                "reasoning_note": (row.get("reasoning_note") or "").strip(),
            }
    return out


def _finding_idx_from_id(sid: str) -> int:
    return int(sid.split("finding-")[-1])


def _audited_bundle_indices(date: str) -> list[int]:
    return sorted(
        int(p.stem.split("topic-")[-1])
        for p in (SRC_DATA_ROOT / date).glob("topic-*.json")
    )


def _embed_cached_or_fresh(name: str, texts: list[str]) -> np.ndarray:
    """Re-use the sweep harness embedding cache when available — the
    finding + V1 topic embeddings are identical to what Phase 1 / 2
    computed (same fastembed singleton, same text rule)."""
    cache = SWEEP_CACHE_ROOT / f"{name}.npy"
    if cache.exists():
        mat = np.load(cache)
        if mat.shape[0] == len(texts):
            return mat
    print(f"  embedding {len(texts)} texts → fresh (no cache hit at {name}.npy)")
    emb = _get_default_embedder()
    matrix = _cosine_normalized(emb.embed_batch(texts))
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, matrix)
    return matrix


def reaudit_day(date: str) -> dict[str, Any]:
    print(f"\n== re-auditing {date} ==")
    findings = _load_findings(date_path := DATASETS[date])
    topics = _load_topics(date)
    n_findings = len(findings)
    n_topics = len(topics)
    print(f"  findings={n_findings}, topics={n_topics}")

    # Embed (use sweep cache when present)
    finding_texts = [_grav_finding_text(f) for f in findings]
    topic_texts = [_topic_text(t) for t in topics]
    findings_mat = _embed_cached_or_fresh(f"{date}/findings", finding_texts)
    topics_mat = _embed_cached_or_fresh(f"{date}/topics_v1", topic_texts)
    sim = (findings_mat @ topics_mat.T).astype(np.float64)

    # New per-topic assigned set at T=GRAVITATIONAL_THRESHOLD (no cap
    # binding at T=0.55 per sweep data; verified below).
    T = GRAVITATIONAL_THRESHOLD
    above = sim >= T  # (n_findings, n_topics) bool
    per_finding_counts = above.sum(axis=1)
    n_orphans = int((per_finding_counts == 0).sum())
    cap_binds = int((per_finding_counts > PER_FINDING_CAP).sum())
    if cap_binds:
        print(f"  WARN: cap binds for {cap_binds} findings at T={T} (expected 0)")
    # post-cap assignments per topic — at T=0.55 cap doesn't bind, so
    # this equals above.sum(axis=0).
    new_source_count_per_topic = above.sum(axis=0).tolist()

    # Build new top-10 topic ranking by NEW source_count, descending.
    ranked = sorted(
        list(range(n_topics)),
        key=lambda ti: (
            -int(new_source_count_per_topic[ti]),
            (topics[ti].get("title") or ""),
        ),
    )
    new_top_k_indices = [ti for ti in ranked if new_source_count_per_topic[ti] > 0][
        :TOP_K_TOPICS
    ]
    print(
        f"  new top-{TOP_K_TOPICS} by recalibrated source_count: "
        f"{[(ti, int(new_source_count_per_topic[ti])) for ti in new_top_k_indices]}"
    )

    # Map original bundle-rank → topic_idx in _topics.json by source_ids
    # set. Reuses the same logic as the sweep harness.
    bundle_idx_to_topic_idx: dict[int, int] = {}
    bundle_indices = _audited_bundle_indices(date)
    for bi in bundle_indices:
        b = json.loads((SRC_DATA_ROOT / date / f"topic-{bi:02d}.json").read_text())
        bundle_sids = {f["source_id"] for f in b["findings"]}
        matched = None
        for ti, t in enumerate(topics):
            if set(t.get("source_ids") or []) == bundle_sids:
                matched = ti
                break
        if matched is None:
            # Title fallback
            for ti, t in enumerate(topics):
                if (t.get("title") or "").strip() == (b.get("topic_title") or "").strip():
                    matched = ti
                    break
        if matched is None:
            raise ValueError(
                f"could not match {date}/topic-{bi:02d} ({b['topic_title'][:80]!r}) "
                f"to any topic in _topics.json"
            )
        bundle_idx_to_topic_idx[bi] = matched

    # Per-topic re-audit on the originally-audited 10 topics
    per_topic_rows: list[dict] = []
    day_dir = OUT_DATA_ROOT / date
    day_dir.mkdir(parents=True, exist_ok=True)

    n_findings_audited_day = 0
    n_off_topic_day = 0
    per_topic_off_pcts: list[float] = []

    for bi in bundle_indices:
        topic_idx = bundle_idx_to_topic_idx[bi]
        topic = topics[topic_idx]
        original_bundle = json.loads(
            (SRC_DATA_ROOT / date / f"topic-{bi:02d}.json").read_text()
        )
        labels = _load_audit_csv_rows(date, bi)

        # Sim column for this topic
        sim_col = sim[:, topic_idx]

        # New per-finding assignment for this topic: every finding whose
        # sim ≥ T. Includes findings BEYOND the original source_ids set
        # (those would not have labels). But at T=0.55 V1, the new set
        # is a strict subset of the T=0.30 original set, so every new
        # assignment is already labelled.
        new_assigned_sids: list[str] = []
        for fi in range(n_findings):
            if sim_col[fi] >= T:
                new_assigned_sids.append(f"finding-{fi}")

        # Sanity-check: every new assignment should have a label
        unlabeled = [s for s in new_assigned_sids if s not in labels]
        if unlabeled:
            # Defensive: at T=0.55, would only happen if the embedding
            # cache drifted or topic identity shifted. Surface loudly.
            print(
                f"    WARN: topic-{bi:02d} ({topic.get('title','')[:50]!r}) — "
                f"{len(unlabeled)} new assignments have no label "
                f"(first few: {unlabeled[:5]})"
            )

        labelled_sids = [s for s in new_assigned_sids if s in labels]
        on = sum(1 for s in labelled_sids if labels[s]["is_on_topic"] == 1)
        off = sum(1 for s in labelled_sids if labels[s]["is_on_topic"] == 0)
        n_lab = on + off
        off_pct = (100.0 * off / n_lab) if n_lab else 0.0
        new_source_count = int(new_source_count_per_topic[topic_idx])
        original_source_count = int(original_bundle.get("source_count") or 0)

        # Write the new per-topic bundle — same schema as original audit
        new_findings_payload: list[dict] = []
        for sid in new_assigned_sids:
            fi = _finding_idx_from_id(sid)
            f = findings[fi]
            new_findings_payload.append(
                {
                    "source_id": sid,
                    "title": f.get("title") or "",
                    "summary": f.get("summary") or "",
                    "description": f.get("description") or "",
                    "language": f.get("language") or "",
                    "outlet": f.get("outlet_name")
                    or f.get("source_name")
                    or "",
                    "text": " | ".join(
                        p
                        for p in (
                            (f.get("title") or "").strip(),
                            (f.get("summary") or "").strip(),
                            (f.get("description") or "").strip(),
                        )
                        if p
                    ),
                    "similarity_to_topic_centre": round(float(sim_col[fi]), 4),
                }
            )
        bundle_payload = {
            "topic_index": bi,
            "topic_title": topic.get("title") or "",
            "topic_summary": topic.get("summary") or "",
            "original_source_count": original_source_count,
            "recalibrated_source_count": new_source_count,
            "n_assigned_at_T_0.55_V1": len(new_assigned_sids),
            "geographic_coverage": list(topic.get("geographic_coverage") or []),
            "languages": list(topic.get("languages") or []),
            "n_findings": len(new_findings_payload),
            "findings": new_findings_payload,
        }
        (day_dir / f"topic-{bi:02d}.json").write_text(
            json.dumps(bundle_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Re-emit the audit CSV with only the recalibrated assignments,
        # labels copied verbatim from the original audit.
        csv_path = day_dir / f"topic-{bi:02d}.audit.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["finding_id", "is_on_topic", "reasoning_note"])
            for sid in new_assigned_sids:
                lab = labels.get(sid, {})
                w.writerow(
                    [
                        sid,
                        lab.get("is_on_topic", ""),
                        lab.get("reasoning_note", ""),
                    ]
                )

        per_topic_rows.append(
            {
                "bundle_idx": bi,
                "topic_idx": topic_idx,
                "topic_title": topic.get("title") or "",
                "original_source_count": original_source_count,
                "recalibrated_source_count": new_source_count,
                "n_assigned": len(new_assigned_sids),
                "n_labeled": n_lab,
                "n_unlabeled_new_assignments": len(unlabeled),
                "on_topic": on,
                "off_topic": off,
                "off_topic_pct": round(off_pct, 2),
            }
        )
        n_findings_audited_day += n_lab
        n_off_topic_day += off
        if n_lab:
            per_topic_off_pcts.append(off_pct)

    weighted = (
        100.0 * n_off_topic_day / n_findings_audited_day if n_findings_audited_day else 0.0
    )
    simple = mean(per_topic_off_pcts) if per_topic_off_pcts else 0.0

    # Per-day Markdown
    md: list[str] = []
    md.append(f"# Cluster-quality re-audit — {date}")
    md.append("")
    md.append("Recalibrated at T=0.55, V=title+summary per "
              "TASK-GRAVITATIONAL-RECALIBRATION (architect's pick after Phase 2).")
    md.append("")
    md.append("## Run summary")
    md.append("")
    md.append(f"- State file: `{DATASETS[date].relative_to(REPO_ROOT)}`")
    md.append(f"- Pipeline mode: gravitational_assign at T={GRAVITATIONAL_THRESHOLD:.2f}, V=title+summary")
    md.append(f"- Topics reused from original audit (`audit-2026-05-16/_data/{date}/_topics.json`)")
    md.append(f"- LLM cost for re-audit: $0 (no new LLM calls — same topics, only the assignment cut changed)")
    md.append(f"- n_findings: {n_findings}")
    md.append(f"- n_topics: {n_topics}")
    md.append(f"- n_orphans (full population, all topics): {n_orphans} ({100.0 * n_orphans / n_findings:.1f}%)")
    md.append(f"- topics_audited (originally top by source_count): {len(bundle_indices)}")
    md.append("")
    md.append("## Per-topic results (originally-audited top-10, re-evaluated at the new threshold)")
    md.append("")
    md.append("| # | Topic title | orig src | recal src | on | off | off % | Δ vs baseline |")
    md.append("|---:|---|---:|---:|---:|---:|---:|---|")
    # Need baseline off% for the diff column
    for row in per_topic_rows:
        # Baseline off% = original audit off / (on+off) for this topic
        bi = row["bundle_idx"]
        orig_labels = _load_audit_csv_rows(date, bi)
        base_on = sum(1 for v in orig_labels.values() if v["is_on_topic"] == 1)
        base_off = sum(1 for v in orig_labels.values() if v["is_on_topic"] == 0)
        base_total = base_on + base_off
        base_off_pct = (100.0 * base_off / base_total) if base_total else 0.0
        delta = row["off_topic_pct"] - base_off_pct
        md.append(
            f"| {bi} | {row['topic_title'][:80]} | "
            f"{row['original_source_count']} | {row['recalibrated_source_count']} | "
            f"{row['on_topic']} | {row['off_topic']} | "
            f"{row['off_topic_pct']:.1f}% | "
            f"{delta:+.1f} pp (was {base_off_pct:.1f}%) |"
        )
    md.append("")
    md.append("## Aggregate for this day")
    md.append("")
    md.append(f"- Topics audited: **{len(per_topic_off_pcts)}** of {len(bundle_indices)}")
    md.append(f"- Findings audited (post-recal assigned): **{n_findings_audited_day}**")
    md.append(f"- Off-topic: **{n_off_topic_day}**")
    md.append(f"- Weighted off-topic rate (per-finding): **{weighted:.2f} %**")
    md.append(f"- Simple-mean off-topic rate (per-topic average): **{simple:.2f} %**")
    md.append("")
    md.append("## New top-10 ranking by recalibrated source_count")
    md.append("")
    md.append("After applying T=0.55, topics re-ranked by new assigned-finding count. "
              "Topics that drop out of the top-10 are listed below the divider.")
    md.append("")
    md.append("| Rank | New source_count | Topic title |")
    md.append("|---:|---:|---|")
    for rank, ti in enumerate(new_top_k_indices, start=1):
        md.append(
            f"| {rank} | {int(new_source_count_per_topic[ti])} | "
            f"{(topics[ti].get('title') or '')[:80]} |"
        )
    md.append("")
    md.append("## Per-finding traces")
    md.append("")
    md.append("Per-topic audit CSVs at `_data/{date}/topic-NN.audit.csv` carry the "
              "recalibrated assigned set with labels copied from the original audit. "
              "Per-topic bundles at `_data/{date}/topic-NN.json` carry the per-finding "
              "text + similarity to the topic centre.")
    md.append("")
    (OUT_ROOT / f"{date}.md").write_text("\n".join(md), encoding="utf-8")

    return {
        "date": date,
        "n_findings_population": n_findings,
        "n_topics_population": n_topics,
        "n_orphans_full_population": n_orphans,
        "n_orphans_pct": round(100.0 * n_orphans / n_findings, 2) if n_findings else 0.0,
        "n_topics_audited": len(per_topic_off_pcts),
        "n_topics_in_top_k": len(bundle_indices),
        "n_findings_audited": n_findings_audited_day,
        "n_off_topic": n_off_topic_day,
        "weighted_off_topic_pct": round(weighted, 2),
        "simple_mean_off_topic_pct": round(simple, 2),
        "topics": per_topic_rows,
        "new_top_k_topic_indices": new_top_k_indices,
        "new_source_counts": {
            str(ti): int(new_source_count_per_topic[ti]) for ti in range(n_topics)
        },
    }


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_DATA_ROOT.mkdir(parents=True, exist_ok=True)
    print(
        f"== Re-audit at pinned T={GRAVITATIONAL_THRESHOLD:.2f}, V=title+summary ==\n"
        f"   Output: {OUT_ROOT.relative_to(REPO_ROOT)}/"
    )
    t0 = time.monotonic()
    per_day: list[dict] = []
    for date in DATASETS:
        per_day.append(reaudit_day(date))

    total_findings = sum(d["n_findings_audited"] for d in per_day)
    total_off = sum(d["n_off_topic"] for d in per_day)
    weighted = 100.0 * total_off / total_findings if total_findings else 0.0
    per_topic_pcts: list[float] = []
    topics_above_50: list[dict] = []
    for d in per_day:
        for t in d["topics"]:
            if t["n_labeled"]:
                per_topic_pcts.append(t["off_topic_pct"])
                if t["off_topic_pct"] > 50.0:
                    topics_above_50.append(
                        {
                            "date": d["date"],
                            "bundle_idx": t["bundle_idx"],
                            "topic_title": t["topic_title"],
                            "off_topic_pct": t["off_topic_pct"],
                            "n_labeled": t["n_labeled"],
                            "on": t["on_topic"],
                            "off": t["off_topic"],
                            "recalibrated_source_count": t["recalibrated_source_count"],
                        }
                    )
    simple = mean(per_topic_pcts) if per_topic_pcts else 0.0

    summary = {
        "audit_date": "2026-05-17",
        "audit_label": "recalibrated",
        "calibration": {
            "GRAVITATIONAL_THRESHOLD": GRAVITATIONAL_THRESHOLD,
            "PER_FINDING_CAP": PER_FINDING_CAP,
            "topic_centre_text": "title + summary (V1)",
        },
        "baseline_audit": {
            "path": "docs/cluster-quality-audit/audit-2026-05-16/",
            "weighted_off_topic_pct": 69.59,
            "simple_mean_off_topic_pct": 69.43,
        },
        "datasets": list(DATASETS.keys()),
        "cross_day_aggregate": {
            "n_findings_audited": total_findings,
            "n_off_topic": total_off,
            "weighted_off_topic_pct": round(weighted, 2),
            "simple_mean_off_topic_pct_per_topic": round(simple, 2),
            "n_topics_audited": len(per_topic_pcts),
        },
        "topics_above_50_pct": topics_above_50,
        "per_day": per_day,
    }
    (OUT_ROOT / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Cross-day Markdown for fast architect read
    md = ["# Cluster-quality re-audit — cross-day summary", ""]
    md.append(f"Recalibrated at **T={GRAVITATIONAL_THRESHOLD:.2f}, V=title+summary** "
              "(per architect's Phase-2 pick).")
    md.append("")
    md.append("## Acceptance gates (per brief)")
    md.append("")
    md.append(f"- Aggregate weighted off-topic rate **< 30 %** target: "
              f"**{weighted:.2f} %** "
              f"{'PASS' if weighted < 30.0 else 'FAIL'}")
    md.append(f"- **No** audited top-10 topic above 50 % off-topic: "
              f"{len(topics_above_50)} topic(s) above the line "
              f"{'PASS' if not topics_above_50 else 'FAIL'}")
    md.append("")
    md.append("## Baseline vs recalibrated")
    md.append("")
    md.append("| Metric | Baseline (T=0.30 V1, original audit) | Recalibrated (T=0.55 V1) | Δ |")
    md.append("|---|---:|---:|---:|")
    md.append(
        f"| Weighted off-topic rate | 69.59 % | **{weighted:.2f} %** | "
        f"{weighted - 69.59:+.2f} pp |"
    )
    md.append(
        f"| Simple-mean off-topic rate | 69.43 % | **{simple:.2f} %** | "
        f"{simple - 69.43:+.2f} pp |"
    )
    md.append(f"| Findings audited | 2,542 | **{total_findings:,}** | "
              f"{total_findings - 2542:+,} (fewer findings retained at higher T) |")
    md.append("")
    md.append("## Per-day breakdown")
    md.append("")
    md.append("| Day | n_audited | n_off | weighted off % | simple-mean off % |")
    md.append("|---|---:|---:|---:|---:|")
    for d in per_day:
        md.append(
            f"| {d['date']} | {d['n_findings_audited']:,} | {d['n_off_topic']:,} | "
            f"**{d['weighted_off_topic_pct']:.2f} %** | "
            f"{d['simple_mean_off_topic_pct']:.2f} % |"
        )
    md.append(
        f"| **Cross-day** | **{total_findings:,}** | **{total_off:,}** | "
        f"**{weighted:.2f} %** | **{simple:.2f} %** |"
    )
    md.append("")
    md.append("## Topics still above 50 % off-topic (after recalibration)")
    md.append("")
    if not topics_above_50:
        md.append("_None._ Every audited top-10 topic per day sits at or below 50 % off-topic.")
    else:
        md.append("| Day | bundle | Topic | n_labeled | on | off | off % | recal src |")
        md.append("|---|---:|---|---:|---:|---:|---:|---:|")
        for t in topics_above_50:
            md.append(
                f"| {t['date']} | topic-{t['bundle_idx']:02d} | "
                f"{t['topic_title'][:80]} | {t['n_labeled']} | {t['on']} | "
                f"{t['off']} | **{t['off_topic_pct']:.1f} %** | "
                f"{t['recalibrated_source_count']} |"
            )
    md.append("")
    md.append("## Per-day reports")
    md.append("")
    for d in per_day:
        md.append(f"- [`{d['date']}.md`]({d['date']}.md)")
    md.append("")
    (OUT_ROOT / "README.md").write_text("\n".join(md), encoding="utf-8")

    wall = time.monotonic() - t0
    print("\n== Cross-day aggregate ==")
    print(f"  Findings audited: {total_findings:,}")
    print(f"  Off-topic:        {total_off:,}")
    print(f"  Weighted %:       {weighted:.2f}")
    print(f"  Simple-mean %:    {simple:.2f}")
    print(f"  Topics audited:   {len(per_topic_pcts)}")
    print(f"  Topics > 50%:     {len(topics_above_50)}")
    print(f"  Wall:             {wall:.1f}s")
    print(f"  Wrote {(OUT_ROOT / 'summary.json').relative_to(REPO_ROOT)}")
    print(f"  Wrote {(OUT_ROOT / 'README.md').relative_to(REPO_ROOT)}")

    # Brief watch-item 3 enforcement
    pass_aggregate = weighted < 30.0
    pass_per_topic = not topics_above_50
    if not (pass_aggregate and pass_per_topic):
        print("\n!! Acceptance gate FAILED — per brief watch-item 3, "
              "do NOT pin further iterations inside this brief. Surface.")
        return 1
    print("\n** Acceptance gates PASS — aggregate < 30 % and no topic > 50 %. **")
    return 0


if __name__ == "__main__":
    sys.exit(main())
