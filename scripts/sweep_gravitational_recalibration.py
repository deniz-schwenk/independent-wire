#!/usr/bin/env python3
"""Gravitational threshold + centre-variant parameter sweep — Phase 1 of
TASK-GRAVITATIONAL-RECALIBRATION.md.

Sweeps:
  Threshold T  ∈ {0.30, 0.35, 0.40, 0.45, 0.50, 0.55}
  Centre var V ∈ {V1=title+summary (current), V2=title only}

For each of the 12 configurations:

  - Per-(audited topic) on/off-topic counts and rates against the audit
    labels in docs/cluster-quality-audit/audit-2026-05-16/_data/.
  - Aggregate weighted off-topic rate across the 30 audited topics.
  - Mean per-topic precision (on / on+off retained per topic).
  - Mean per-topic recall (on_retained / on_in_full_audit per topic).
  - Per-day-and-aggregate assignments-per-finding distribution
    (0/1/2/3/4+, pre-cap) against the full daily populations.
  - Orphan / single / multi counts after applying PER_FINDING_CAP=3.

Outputs:
  docs/gravitational-recalibration-2026-05-16/sweep.md
  docs/gravitational-recalibration-2026-05-16/sweep.json
  docs/gravitational-recalibration-2026-05-16/_cache/{date}/*.npy

Usage:
  python scripts/sweep_gravitational_recalibration.py sweep   # compute + render
  python scripts/sweep_gravitational_recalibration.py render  # render-only (uses cache)
"""

from __future__ import annotations

import argparse
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


AUDIT_ROOT = REPO_ROOT / "docs" / "cluster-quality-audit" / "audit-2026-05-16"
DATA_ROOT = AUDIT_ROOT / "_data"
OUT_ROOT = REPO_ROOT / "docs" / "gravitational-recalibration-2026-05-16"
CACHE_ROOT = OUT_ROOT / "_cache"

DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}

THRESHOLDS: list[float] = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55]
VARIANTS: list[str] = ["V1", "V2"]
CAP: int = 3


# ── Embedding text conventions (must match production) ────────────────────
def _finding_text_full(f: dict) -> str:
    """Mirrors src.stages.pre_cluster._finding_text and
    src.stages.gravitational_assign._finding_text — title + summary +
    description joined with single spaces."""
    return (
        (f.get("title") or "")
        + " "
        + (f.get("summary") or "")
        + " "
        + (f.get("description") or "")
    ).strip()


def _topic_text_v1(t: dict) -> str:
    """Production: title + summary."""
    return ((t.get("title") or "") + " " + (t.get("summary") or "")).strip()


def _topic_text_v2(t: dict) -> str:
    """V2 candidate: title only."""
    return (t.get("title") or "").strip()


# ── State / audit loaders ─────────────────────────────────────────────────
def _load_findings(state_path: Path) -> list[dict]:
    with state_path.open() as fh:
        data = json.load(fh)
    return list(data.get("curator_findings") or [])


def _load_topics(date: str) -> list[dict]:
    return json.loads((DATA_ROOT / date / "_topics.json").read_text(encoding="utf-8"))


def _load_bundle(date: str, bundle_idx: int) -> dict:
    return json.loads(
        (DATA_ROOT / date / f"topic-{bundle_idx:02d}.json").read_text(encoding="utf-8")
    )


def _audited_bundle_indices(date: str) -> list[int]:
    return sorted(
        int(p.stem.split("topic-")[-1])
        for p in (DATA_ROOT / date).glob("topic-*.json")
    )


def _load_audit_csv(date: str, bundle_idx: int) -> list[tuple[str, int]]:
    path = DATA_ROOT / date / f"topic-{bundle_idx:02d}.audit.csv"
    out: list[tuple[str, int]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        r = csv.DictReader(fh)
        for row in r:
            label = (row.get("is_on_topic") or "").strip()
            if label not in ("0", "1"):
                continue
            out.append((row["finding_id"].strip(), int(label)))
    return out


def _finding_idx_from_id(sid: str) -> int:
    return int(sid.split("finding-")[-1])


def _bundle_to_topic_idx(bundle: dict, topics: list[dict]) -> int:
    """Match a bundle to its row in _topics.json by source_ids set."""
    bundle_sids = {f["source_id"] for f in bundle["findings"]}
    for ti, t in enumerate(topics):
        if set(t.get("source_ids") or []) == bundle_sids:
            return ti
    for ti, t in enumerate(topics):
        if (t.get("title") or "").strip() == (bundle["topic_title"] or "").strip():
            return ti
    raise ValueError(
        f"could not match bundle {bundle['topic_title'][:80]!r} to any topic in _topics.json"
    )


# ── Embedding cache ───────────────────────────────────────────────────────
def _embed_cached(name: str, texts: list[str]) -> np.ndarray:
    path = CACHE_ROOT / f"{name}.npy"
    if path.exists():
        mat = np.load(path)
        if mat.shape[0] == len(texts):
            return mat
        # Stale cache (different population) — drop and recompute.
        path.unlink()
    print(f"    embedding {len(texts)} texts → {name}.npy ...")
    t0 = time.monotonic()
    emb = _get_default_embedder()
    matrix = _cosine_normalized(emb.embed_batch(texts))
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, matrix)
    print(f"      done in {time.monotonic() - t0:.1f}s")
    return matrix


# ── Per-day prep ──────────────────────────────────────────────────────────
def prepare_day(date: str) -> dict[str, Any]:
    """Load findings + topics + audit bundles for one day, materialise
    cosine-similarity matrices for both centre-variants."""
    state_path = DATASETS[date]
    findings = _load_findings(state_path)
    topics = _load_topics(date)

    finding_texts = [_finding_text_full(f) for f in findings]
    topics_v1_texts = [_topic_text_v1(t) for t in topics]
    topics_v2_texts = [_topic_text_v2(t) for t in topics]

    findings_mat = _embed_cached(f"{date}/findings", finding_texts)
    topics_v1_mat = _embed_cached(f"{date}/topics_v1", topics_v1_texts)
    topics_v2_mat = _embed_cached(f"{date}/topics_v2", topics_v2_texts)

    sim_v1 = (findings_mat @ topics_v1_mat.T).astype(np.float64)
    sim_v2 = (findings_mat @ topics_v2_mat.T).astype(np.float64)

    audited: list[dict[str, Any]] = []
    for bi in _audited_bundle_indices(date):
        bundle = _load_bundle(date, bi)
        topic_idx = _bundle_to_topic_idx(bundle, topics)
        labels = _load_audit_csv(date, bi)
        audited.append(
            {
                "bundle_idx": bi,
                "topic_idx": topic_idx,
                "title": bundle["topic_title"],
                "summary": bundle.get("topic_summary", ""),
                "source_count": int(bundle.get("source_count") or 0),
                "labels": labels,
            }
        )

    return {
        "date": date,
        "n_findings": len(findings),
        "n_topics": len(topics),
        "sim_v1": sim_v1,
        "sim_v2": sim_v2,
        "audited": audited,
    }


# ── Sweep math ────────────────────────────────────────────────────────────
def _post_cap_count(pre_cap: int, cap: int) -> int:
    return min(pre_cap, cap)


def metrics_for_config(per_day: dict[str, dict], T: float, V: str) -> dict[str, Any]:
    """Compute one (T, V) row's metrics across all three days."""
    sim_key = "sim_v1" if V == "V1" else "sim_v2"

    per_topic: list[dict] = []
    total_on_retained = 0
    total_off_retained = 0
    total_on_full = 0

    for date, day in per_day.items():
        sim_mat = day[sim_key]
        for at in day["audited"]:
            ti = at["topic_idx"]
            sim_col = sim_mat[:, ti]
            on_r = 0
            off_r = 0
            on_full = 0
            for sid, label in at["labels"]:
                fi = _finding_idx_from_id(sid)
                sim = float(sim_col[fi])
                retained = sim >= T
                if label == 1:
                    on_full += 1
                if retained:
                    if label == 1:
                        on_r += 1
                    else:
                        off_r += 1
            n_r = on_r + off_r
            precision = (on_r / n_r) if n_r else None
            recall = (on_r / on_full) if on_full else None
            off_pct = (100.0 * off_r / n_r) if n_r else 0.0
            per_topic.append(
                {
                    "date": date,
                    "bundle_idx": at["bundle_idx"],
                    "title": at["title"],
                    "source_count": at["source_count"],
                    "n_in_full_audit": len(at["labels"]),
                    "on_full": on_full,
                    "n_retained": n_r,
                    "on_retained": on_r,
                    "off_retained": off_r,
                    "off_topic_pct": round(off_pct, 2),
                    "precision": round(precision, 4) if precision is not None else None,
                    "recall": round(recall, 4) if recall is not None else None,
                }
            )
            total_on_retained += on_r
            total_off_retained += off_r
            total_on_full += on_full

    total_retained = total_on_retained + total_off_retained
    weighted_off_pct = (
        100.0 * total_off_retained / total_retained if total_retained else 0.0
    )
    valid_precisions = [t["precision"] for t in per_topic if t["precision"] is not None]
    valid_recalls = [t["recall"] for t in per_topic if t["recall"] is not None]
    mean_precision = float(np.mean(valid_precisions)) if valid_precisions else 0.0
    mean_recall = float(np.mean(valid_recalls)) if valid_recalls else 0.0
    # Topics with zero retained — these are dead-on-arrival under (T, V).
    n_topics_zero_retained = sum(1 for t in per_topic if t["n_retained"] == 0)

    # Full-population assignment distribution + orphan + multi
    total_findings = 0
    bucket_0 = 0
    bucket_1 = 0
    bucket_2 = 0
    bucket_3 = 0
    bucket_4plus = 0
    multi_count = 0  # post-cap >= 2
    single_count = 0  # post-cap == 1
    n_assignments = 0
    per_day_dist: dict[str, dict[str, int]] = {}

    for date, day in per_day.items():
        sim_mat = day[sim_key]
        mask = sim_mat >= T
        counts = mask.sum(axis=1)
        d0 = d1 = d2 = d3 = d4 = 0
        for c in counts:
            c = int(c)
            total_findings += 1
            if c == 0:
                bucket_0 += 1
                d0 += 1
            elif c == 1:
                bucket_1 += 1
                d1 += 1
            elif c == 2:
                bucket_2 += 1
                d2 += 1
            elif c == 3:
                bucket_3 += 1
                d3 += 1
            else:
                bucket_4plus += 1
                d4 += 1
            post = _post_cap_count(c, CAP)
            n_assignments += post
            if post >= 2:
                multi_count += 1
            elif post == 1:
                single_count += 1
        per_day_dist[date] = {
            "n_findings": int(counts.size),
            "0": d0,
            "1": d1,
            "2": d2,
            "3": d3,
            "4+": d4,
        }

    orphan_pct = 100.0 * bucket_0 / total_findings if total_findings else 0.0

    return {
        "T": T,
        "V": V,
        "config_name": f"T={T:.2f}-{V}",
        # Audit-set metrics
        "n_audited_findings_retained": total_retained,
        "n_audited_on_retained": total_on_retained,
        "n_audited_off_retained": total_off_retained,
        "n_audited_on_full": total_on_full,
        "weighted_off_topic_pct": round(weighted_off_pct, 2),
        "mean_per_topic_precision": round(mean_precision, 4),
        "mean_per_topic_recall": round(mean_recall, 4),
        "n_topics_zero_retained": n_topics_zero_retained,
        # Full-population metrics (across 3 days)
        "n_findings_total": total_findings,
        "n_multi_assigned": multi_count,
        "n_single_assigned": single_count,
        "n_orphans": bucket_0,
        "orphan_pct": round(orphan_pct, 2),
        "n_assignments_post_cap": n_assignments,
        "assignments_per_finding_pre_cap": {
            "0": bucket_0,
            "1": bucket_1,
            "2": bucket_2,
            "3": bucket_3,
            "4+": bucket_4plus,
        },
        "per_day_assignments_pre_cap": per_day_dist,
        "per_topic": per_topic,
    }


# ── Rendering ─────────────────────────────────────────────────────────────
def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}%"


def _fmt_float(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.4f}"


GRAVITY_TRAP_OFF_PCT_THRESHOLD: float = 80.0
"""Off-topic rate at baseline (T=0.30 V1) that flags a topic as a gravity
trap for brief watch-item 2. Data-driven: any audited topic whose
production-baseline off-topic rate is ≥ 80% counts. This catches Putin/
Schröder, Yermak, Ramaphosa, China defense ministers, Latvian defense
minister, Nunes Marques on the three eval days."""


def _is_gravity_trap(per_topic: dict) -> bool:
    return per_topic["off_topic_pct"] >= GRAVITY_TRAP_OFF_PCT_THRESHOLD


def render_markdown(
    rows: list[dict], per_day: dict[str, dict], audit_n_findings: int
) -> str:
    out: list[str] = []
    out.append("# Gravitational recalibration — parameter sweep")
    out.append("")
    out.append("Phase 1 of `TASK-GRAVITATIONAL-RECALIBRATION.md`.")
    out.append("")
    out.append("Sweeps the gravitational threshold and topic-centre embedding text against the 2,542 audit labels from `TASK-CLUSTER-QUALITY-AUDIT` (audit at `docs/cluster-quality-audit/audit-2026-05-16/`, HEAD 6d8ffc4).")
    out.append("")
    out.append("## Method")
    out.append("")
    out.append("- **Thresholds T:** `{0.30, 0.35, 0.40, 0.45, 0.50, 0.55}`.")
    out.append("- **Variants V:** `V1 = title + summary` (production), `V2 = title only`.")
    out.append("- **Per-(T, V) recomputation:** the audited findings' similarities are recomputed against re-embedded topic centres; on/off-topic counts use the audit labels.")
    out.append("- **Full-population diagnostics** (orphan rate, assignments-per-finding distribution): all topics × all findings per day, pre-cap counts plus post-cap multi/single/orphan.")
    out.append(f"- **PER_FINDING_CAP:** {CAP} (current production constant; unchanged across the sweep).")
    pop_parts = " / ".join(f"{d} = {x['n_findings']}" for d, x in per_day.items())
    total_n = sum(x["n_findings"] for x in per_day.values())
    total_t = sum(x["n_topics"] for x in per_day.values())
    out.append(
        f"- **Day populations:** {pop_parts}; total {total_n} findings, "
        f"{total_t} topics, 30 audited topics, {audit_n_findings} audited findings."
    )
    out.append("")

    # ── Top-level table ──
    out.append("## Top-level table")
    out.append("")
    out.append("Ranked by weighted off-topic %. Reach (lower is better) and recall (higher is better) compete — read both.")
    out.append("")
    out.append(
        "| Rank | T | V | Weighted off % | Mean prec | Mean recall | Multi | Single | Orphan | Orphan % | Topics w/ 0 retained |"
    )
    out.append("|---:|---:|:--|---:|---:|---:|---:|---:|---:|---:|---:|")
    rows_ranked = sorted(rows, key=lambda r: r["weighted_off_topic_pct"])
    for rank, r in enumerate(rows_ranked, start=1):
        out.append(
            f"| {rank} | {r['T']:.2f} | {r['V']} | "
            f"{r['weighted_off_topic_pct']:.2f}% | "
            f"{r['mean_per_topic_precision']:.4f} | "
            f"{r['mean_per_topic_recall']:.4f} | "
            f"{r['n_multi_assigned']:,} | "
            f"{r['n_single_assigned']:,} | "
            f"{r['n_orphans']:,} | "
            f"{r['orphan_pct']:.2f}% | "
            f"{r['n_topics_zero_retained']} |"
        )
    out.append("")

    # ── Assignments-per-finding distribution ──
    out.append("## Assignments-per-finding distribution (pre-cap, all topics × all findings)")
    out.append("")
    out.append("`PER_FINDING_CAP = 3` would truncate the `4+` bucket to 3. Findings in `0` are orphans at this (T, V).")
    out.append("")
    out.append(
        "| T | V | 0 | 1 | 2 | 3 | 4+ | mean assignments/finding (post-cap) |"
    )
    out.append("|---:|:--|---:|---:|---:|---:|---:|---:|")
    for r in sorted(rows, key=lambda r: (r["V"], r["T"])):
        d = r["assignments_per_finding_pre_cap"]
        n = r["n_findings_total"]
        mean_post = r["n_assignments_post_cap"] / n if n else 0.0
        out.append(
            f"| {r['T']:.2f} | {r['V']} | "
            f"{d['0']:,} | {d['1']:,} | {d['2']:,} | {d['3']:,} | {d['4+']:,} | "
            f"{mean_post:.3f} |"
        )
    out.append("")

    # ── Gravity-trap movement across all 12 configurations ──
    out.append("## Gravity-trap topic movement (per brief watch-item 2)")
    out.append("")
    out.append(
        f"Gravity-trap = baseline T=0.30 V1 off-topic rate ≥ {GRAVITY_TRAP_OFF_PCT_THRESHOLD:.0f}%. "
        "This catches Putin/Schröder, Yermak, Ramaphosa, China defense ministers, "
        "Latvian defense minister, and Nunes Marques on the three eval days. "
        "A configuration that drops aggregate to <30% but leaves these >50% is failing the editorial job. "
        "Per-topic off-topic % across all 12 configurations:"
    )
    out.append("")
    # Gather all per_topic rows keyed by (date, bundle_idx). Use V1@0.30 row to find gravity-trap topics.
    base_row = next(r for r in rows if r["T"] == 0.30 and r["V"] == "V1")
    gravity_traps = [t for t in base_row["per_topic"] if _is_gravity_trap(t)]
    if gravity_traps:
        for gt in gravity_traps:
            out.append(
                f"### {gt['date']} · topic-{gt['bundle_idx']:02d} · {gt['title'][:90]}"
            )
            out.append("")
            out.append(
                f"_source_count={gt['source_count']}, audit on-topic={gt['on_full']} / {gt['n_in_full_audit']}_ "
            )
            out.append("")
            out.append("| T | V | Retained | On | Off | Off % | Precision | Recall |")
            out.append("|---:|:--|---:|---:|---:|---:|---:|---:|")
            for r in sorted(rows, key=lambda r: (r["V"], r["T"])):
                # Find the matching per_topic entry
                match = next(
                    pt
                    for pt in r["per_topic"]
                    if pt["date"] == gt["date"] and pt["bundle_idx"] == gt["bundle_idx"]
                )
                out.append(
                    f"| {r['T']:.2f} | {r['V']} | {match['n_retained']} | "
                    f"{match['on_retained']} | {match['off_retained']} | "
                    f"{match['off_topic_pct']:.1f}% | "
                    f"{_fmt_float(match['precision'])} | "
                    f"{_fmt_float(match['recall'])} |"
                )
            out.append("")
    else:
        out.append("_(none of the gravity-trap titles matched the keyword set; consult per-topic detail.)_")
        out.append("")

    # ── Per-topic detail (all 30) ──
    out.append("## Per-topic detail — all 30 audited topics across 12 configurations")
    out.append("")
    out.append("For each topic, off-topic % at each (T, V). The lower row of each topic also shows the retained count, so you can see when a configuration empties the bucket.")
    out.append("")
    # Build a (date, bundle_idx) → 12-cell map
    topic_keys = sorted(
        {(t["date"], t["bundle_idx"]) for r in rows for t in r["per_topic"]},
        key=lambda k: (k[0], k[1]),
    )
    for date, bi in topic_keys:
        ref = next(t for t in base_row["per_topic"] if t["date"] == date and t["bundle_idx"] == bi)
        out.append(
            f"### {date} · topic-{bi:02d} · {ref['title'][:90]}"
        )
        out.append("")
        out.append(
            f"_source_count={ref['source_count']}, audit on={ref['on_full']} / {ref['n_in_full_audit']}_"
        )
        out.append("")
        out.append("| Metric | T=0.30 V1 | T=0.35 V1 | T=0.40 V1 | T=0.45 V1 | T=0.50 V1 | T=0.55 V1 | T=0.30 V2 | T=0.35 V2 | T=0.40 V2 | T=0.45 V2 | T=0.50 V2 | T=0.55 V2 |")
        out.append("|---|" + "---:|" * 12)
        cells_off: list[str] = []
        cells_ret: list[str] = []
        cells_prec: list[str] = []
        for V in VARIANTS:
            for T in THRESHOLDS:
                r = next(rr for rr in rows if rr["T"] == T and rr["V"] == V)
                match = next(pt for pt in r["per_topic"] if pt["date"] == date and pt["bundle_idx"] == bi)
                cells_off.append(f"{match['off_topic_pct']:.1f}%")
                cells_ret.append(f"{match['n_retained']}")
                cells_prec.append(_fmt_float(match["precision"]))
        out.append("| off % | " + " | ".join(cells_off) + " |")
        out.append("| retained | " + " | ".join(cells_ret) + " |")
        out.append("| precision | " + " | ".join(cells_prec) + " |")
        out.append("")

    # ── Recommendation paragraph ──
    out.append("## CC recommendation")
    out.append("")
    rec = build_recommendation(rows)
    out.append(rec)
    out.append("")
    out.append("This is the data CC sees. The architect picks the configuration after reading the qualitative samples in Phase 2.")

    return "\n".join(out)


def build_recommendation(rows: list[dict]) -> str:
    """Identify top-three configurations on weighted off-topic %, then
    surface the worst-offender gravity-trap movement for each. The
    architect uses both signals to make the call."""
    rows_ranked = sorted(rows, key=lambda r: r["weighted_off_topic_pct"])
    top3 = rows_ranked[:3]

    base_row = next(r for r in rows if r["T"] == 0.30 and r["V"] == "V1")
    trap_keys = {
        (t["date"], t["bundle_idx"]) for t in base_row["per_topic"] if _is_gravity_trap(t)
    }

    def _trap_summary(r: dict) -> str:
        traps = [
            t
            for t in r["per_topic"]
            if (t["date"], t["bundle_idx"]) in trap_keys
        ]
        if not traps:
            return "—"
        return ", ".join(
            f"{t['date']}/topic-{t['bundle_idx']:02d}={t['off_topic_pct']:.0f}% (n_r={t['n_retained']})"
            for t in traps
        )

    def _max_trap(r: dict) -> float:
        traps = [
            t
            for t in r["per_topic"]
            if (t["date"], t["bundle_idx"]) in trap_keys
        ]
        return max((t["off_topic_pct"] for t in traps), default=0.0)

    def _min_trap_retained(r: dict) -> int:
        traps = [
            t
            for t in r["per_topic"]
            if (t["date"], t["bundle_idx"]) in trap_keys
        ]
        return min((t["n_retained"] for t in traps), default=0)

    out: list[str] = []
    out.append(
        f"**Top three configurations by aggregate weighted off-topic %** (the ranking the brief asks for):"
    )
    out.append("")
    for i, r in enumerate(top3, start=1):
        out.append(
            f"{i}. **T={r['T']:.2f}, {r['V']}** — weighted off={r['weighted_off_topic_pct']:.2f}%, "
            f"mean recall={r['mean_per_topic_recall']:.3f}, "
            f"orphan%={r['orphan_pct']:.1f}%, "
            f"max gravity-trap off={_max_trap(r):.1f}%, "
            f"min gravity-trap retained={_min_trap_retained(r)}."
        )
        out.append(f"   - Per-trap movement: {_trap_summary(r)}")
        out.append("")

    base = next(r for r in rows if r["T"] == 0.30 and r["V"] == "V1")
    out.append(
        f"Baseline T=0.30 V1 (current production) — weighted off **{base['weighted_off_topic_pct']:.2f}%**, "
        f"recall {base['mean_per_topic_recall']:.3f}, "
        f"orphan {base['orphan_pct']:.1f}%, "
        f"max gravity-trap off={_max_trap(base):.1f}%."
    )
    out.append("")
    out.append("### Dual-constraint read")
    out.append("")
    out.append(
        "The brief sets two thresholds: aggregate weighted off-topic **< 30 %** and "
        "**no gravity-trap topic above 50 % off-topic**. Configurations that satisfy "
        "both, ranked by ascending weighted off:"
    )
    out.append("")
    out.append("| Rank | T | V | Weighted off % | Max trap off % | Mean recall | Orphan % | Min trap retained |")
    out.append("|---:|---:|:--|---:|---:|---:|---:|---:|")
    dual_pass = [
        r
        for r in sorted(rows, key=lambda r: r["weighted_off_topic_pct"])
        if r["weighted_off_topic_pct"] < 30.0 and _max_trap(r) <= 50.0
    ]
    for rank, r in enumerate(dual_pass, start=1):
        out.append(
            f"| {rank} | {r['T']:.2f} | {r['V']} | "
            f"{r['weighted_off_topic_pct']:.2f}% | {_max_trap(r):.1f}% | "
            f"{r['mean_per_topic_recall']:.3f} | {r['orphan_pct']:.1f}% | "
            f"{_min_trap_retained(r)} |"
        )
    out.append("")
    def _row(T, V):
        return next(r for r in rows if r["T"] == T and r["V"] == V)

    r55v2 = _row(0.55, "V2")
    r55v1 = _row(0.55, "V1")
    r50v2 = _row(0.50, "V2")

    out.append(
        "**Reading the trade-off.** Raising T tightens precision at the cost of "
        "recall. V2 (title-only) collapses faster than V1 because the title has less "
        "semantic surface area — at high T the gravity-trap small-core topics (Yermak, "
        "Nunes Marques) drop to retained=1, which is below the editorial-viability "
        f"floor. T=0.55 V2 minimises the aggregate ({r55v2['weighted_off_topic_pct']:.2f}%) but at "
        f"recall {r55v2['mean_per_topic_recall']:.2f} it loses more than half the on-topic content; "
        f"min trap retained = {_min_trap_retained(r55v2)}. "
        f"T=0.55 V1 holds recall at {r55v1['mean_per_topic_recall']:.2f} with max-trap "
        f"off {_max_trap(r55v1):.1f}% and min trap retained "
        f"{_min_trap_retained(r55v1)}. "
        f"T=0.50 V2 sits between them at recall {r50v2['mean_per_topic_recall']:.2f} "
        f"with max-trap off {_max_trap(r50v2):.1f}% (Nunes Marques exactly on the "
        f"50% line, retained=2)."
    )
    out.append("")
    out.append(
        "**CC's recommendation.** Surface T=0.55 V2, T=0.55 V1, and T=0.50 V2 for "
        "qualitative Phase-2 sampling — they are the three configurations that satisfy "
        "the brief's dual-constraint test and the top three by weighted off-topic %. "
        "If CC had to pick one without seeing the samples, **T=0.55 V1** is the best "
        f"balance on the numbers: aggregate {r55v1['weighted_off_topic_pct']:.2f}%, gravity-trap "
        f"max {_max_trap(r55v1):.1f}%, recall {r55v1['mean_per_topic_recall']:.2f}, every "
        f"gravity-trap small-core topic retains ≥{_min_trap_retained(r55v1)} findings. "
        "T=0.50 V2 is the runner-up — same dual-constraint pass, lower recall, but "
        "the title-only centre narrows the embedding anchor in a way the architect "
        "may prefer editorially. T=0.55 V2 is the aggressive choice: strongest "
        "aggregate, but Yermak and Nunes Marques fall to one finding each — a small-"
        "core erosion the architect should see in the Phase-2 samples before choosing."
    )
    return "\n".join(out)


# ── Driver ────────────────────────────────────────────────────────────────
def run_sweep() -> tuple[list[dict], dict[str, dict], int]:
    per_day: dict[str, dict] = {}
    for date in DATASETS:
        print(f"== preparing {date} ==")
        per_day[date] = prepare_day(date)
    audit_n_findings = sum(
        sum(len(a["labels"]) for a in d["audited"]) for d in per_day.values()
    )

    rows: list[dict] = []
    for V in VARIANTS:
        for T in THRESHOLDS:
            print(f"  computing T={T:.2f} V={V} ...")
            rows.append(metrics_for_config(per_day, T, V))
    return rows, per_day, audit_n_findings


def write_outputs(rows: list[dict], per_day: dict[str, dict], audit_n_findings: int) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    md = render_markdown(rows, per_day, audit_n_findings)
    (OUT_ROOT / "sweep.md").write_text(md, encoding="utf-8")
    payload = {
        "audit_label_count": audit_n_findings,
        "per_day_population": {
            d: {"n_findings": x["n_findings"], "n_topics": x["n_topics"]}
            for d, x in per_day.items()
        },
        "cap": CAP,
        "thresholds": THRESHOLDS,
        "variants": VARIANTS,
        "rows": rows,
    }
    (OUT_ROOT / "sweep.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {(OUT_ROOT / 'sweep.md').relative_to(REPO_ROOT)}")
    print(f"Wrote {(OUT_ROOT / 'sweep.json').relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "subcommand", choices=("sweep", "render"), nargs="?", default="sweep"
    )
    args = ap.parse_args()

    if args.subcommand == "render":
        # Render-only path: still needs day prep (sim matrices), but the
        # cache will service the embeds without LLM/fastembed cost.
        rows, per_day, n = run_sweep()
        write_outputs(rows, per_day, n)
    else:
        rows, per_day, n = run_sweep()
        write_outputs(rows, per_day, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
