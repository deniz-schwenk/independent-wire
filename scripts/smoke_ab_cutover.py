"""A/B smoke harness for the triple-stage Curator cutover.

Authoritative reference: TASK-TRIPLE-STAGE-CUTOVER.md §"A/B smoke harness".

For each of the three eval-anchor state files, this harness:

  1. Reads the **old** ``curator_topics_unsliced`` from the on-disk
     state file (already produced by the legacy single-pass
     CuratorStage during the eval-run).
  2. Runs the **new** pipeline end-to-end starting from the same
     ``curator_findings``: pre_cluster_findings →
     CuratorTopicDiscoveryStage → gravitational_assign →
     assemble_curator_topics. Real LLM call, real fastembed.
  3. Renders a side-by-side comparison report at
     ``docs/triple-stage-cutover/smoke-<date>/{dataset}.md``.

The load-bearing acceptance criterion is the architect's editorial
review of the side-by-side comparison — orphan rate is reported as
an observation, not as a quantitative gate. Real precision/recall
validation requires labels against the new topic-centres (Brief 5b).

Usage:
    python scripts/smoke_ab_cutover.py
    python scripts/smoke_ab_cutover.py --dataset 2026-05-13
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import resource
import sys
import time
from collections import Counter
from datetime import date as _date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agent_stages import CuratorTopicDiscoveryStage  # noqa: E402
from src.bus import RunBus  # noqa: E402
from src.stages.gravitational_assign import gravitational_assign  # noqa: E402
from src.stages.pre_cluster import pre_cluster_findings  # noqa: E402
from src.stages.run_stages import assemble_curator_topics  # noqa: E402

from scripts.run import create_agents  # noqa: E402


DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}


OUT_ROOT = REPO_ROOT / "docs" / "triple-stage-cutover" / f"smoke-{_date.today().isoformat()}"


# Patch-target words from agents/curator/INSTRUCTIONS.md rule 3
STATUS_DESCRIPTOR_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("former", re.compile(r"\bformer\b", re.IGNORECASE)),
    ("current", re.compile(r"\bcurrent\b", re.IGNORECASE)),
    ("incumbent", re.compile(r"\bincumbent\b", re.IGNORECASE)),
    ("ex-", re.compile(r"\bex-\w+", re.IGNORECASE)),
)


def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0
    return raw * unit / 1e6


def _load_old_run(state_path: Path) -> tuple[list[dict], list[dict]]:
    with state_path.open() as f:
        data = json.load(f)
    findings = list(data.get("curator_findings") or [])
    old_topics = list(data.get("curator_topics_unsliced") or [])
    return findings, old_topics


def _word_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def _best_match(
    new_topic: dict, old_topics: list[dict]
) -> tuple[dict | None, float, str]:
    """Find the best matching old topic by title-word Jaccard +
    source_id overlap. Returns (old_topic, score, label) where label
    indicates the matching basis."""
    new_title_tokens = _word_tokens(new_topic.get("title", ""))
    new_sids = set(new_topic.get("source_ids") or [])
    best: tuple[dict | None, float, str] = (None, 0.0, "no-match")
    for old in old_topics:
        old_title_tokens = _word_tokens(old.get("title", ""))
        if new_title_tokens or old_title_tokens:
            union_t = len(new_title_tokens | old_title_tokens)
            inter_t = len(new_title_tokens & old_title_tokens)
            title_j = inter_t / union_t if union_t else 0.0
        else:
            title_j = 0.0
        old_sids = set(old.get("source_ids") or [])
        if new_sids or old_sids:
            union_s = len(new_sids | old_sids)
            inter_s = len(new_sids & old_sids)
            source_j = inter_s / union_s if union_s else 0.0
        else:
            source_j = 0.0
        # Weighted combination: source overlap is the stronger signal
        score = 0.4 * title_j + 0.6 * source_j
        label = (
            "source+title"
            if source_j > 0 and title_j > 0
            else "source-only"
            if source_j > 0
            else "title-only"
            if title_j > 0
            else "no-overlap"
        )
        if score > best[1]:
            best = (old, score, label)
    return best


def _count_status_descriptors(topics: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {k: 0 for k, _ in STATUS_DESCRIPTOR_PATTERNS}
    for t in topics:
        text = f"{t.get('title', '')} {t.get('summary', '')}"
        for key, rx in STATUS_DESCRIPTOR_PATTERNS:
            if rx.search(text):
                counts[key] += 1
    return counts


def _region_dist(topics: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for t in topics:
        for r in t.get("geographic_coverage") or []:
            c[r] += 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def _language_dist(topics: list[dict]) -> dict[str, int]:
    c: Counter = Counter()
    for t in topics:
        for lng in t.get("languages") or []:
            c[lng] += 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def _source_count_stats(topics: list[dict]) -> dict:
    counts = [int(t.get("source_count", len(t.get("source_ids") or []))) for t in topics]
    counts.sort()
    n = len(counts)
    if not n:
        return {"n": 0, "min": 0, "median": 0, "mean": 0, "max": 0}
    return {
        "n": n,
        "min": counts[0],
        "median": counts[n // 2],
        "mean": round(sum(counts) / n, 2),
        "max": counts[-1],
    }


async def smoke_one(
    date: str,
    state_path: Path,
    out_dir: Path,
    agent,
) -> dict:
    if not state_path.exists():
        return {"date": date, "error": "state-missing"}

    findings, old_topics = _load_old_run(state_path)
    print(f"  [{date}] {len(findings)} findings, {len(old_topics)} old topics; running new pipeline ...")

    rb = RunBus(
        run_id=f"smoke-ab-{date}",
        run_date=date,
        curator_findings=findings,
    )

    rss_before = _rss_mb_now()
    t_total = time.monotonic()

    # 1. pre_cluster
    t = time.monotonic()
    rb = await pre_cluster_findings(rb)
    t_pre = time.monotonic() - t

    # 2. topic-discovery (real LLM)
    t = time.monotonic()
    rb = await CuratorTopicDiscoveryStage(agent)(rb)
    t_disc = time.monotonic() - t

    # 3. gravitational-assign
    t = time.monotonic()
    rb = await gravitational_assign(rb)
    t_grav = time.monotonic() - t

    # 4. assemble
    t = time.monotonic()
    rb = await assemble_curator_topics(rb)
    t_asm = time.monotonic() - t

    wall_total = time.monotonic() - t_total
    rss_after = _rss_mb_now()

    # Extract slot data
    pre_clusters = rb.curator_pre_clusters
    discovered = rb.curator_discovered_topics
    grav = rb.curator_topic_assignments
    new_topics = rb.curator_topics_unsliced

    n_orphans = int(grav.get("n_orphans", 0))
    orphan_pct = round(100 * n_orphans / max(1, len(findings)), 2)
    n_disc = int(discovered.get("n_topics", 0))
    n_new = len(new_topics)
    llm_cost = float(discovered.get("llm_cost_usd", 0.0) or 0.0)

    # Status-descriptor counts
    sd_new = _count_status_descriptors(new_topics)
    sd_old = _count_status_descriptors(old_topics)

    # Side-by-side comparison
    side_by_side: list[dict] = []
    matched_old_titles: set[str] = set()
    for new in new_topics:
        match, score, label = _best_match(new, old_topics)
        if match is not None:
            matched_old_titles.add(match.get("title", ""))
        side_by_side.append({
            "new_title": new.get("title", ""),
            "new_source_count": int(new.get("source_count", 0)),
            "matched_old_title": match.get("title", "") if match else "",
            "match_score": round(score, 3),
            "match_label": label,
        })

    new_titles_set = {n.get("title", "") for n in new_topics}
    old_orphans: list[str] = []
    for old in old_topics:
        if old.get("title", "") not in matched_old_titles:
            old_orphans.append(old.get("title", ""))

    # Region / language coverage
    new_regions = _region_dist(new_topics)
    old_regions = _region_dist(old_topics)
    new_langs = _language_dist(new_topics)
    old_langs = _language_dist(old_topics)

    # Source-count distribution
    sc_new = _source_count_stats(new_topics)
    sc_old = _source_count_stats(old_topics)

    # Render Markdown
    out_dir.mkdir(parents=True, exist_ok=True)
    rel_state = state_path.relative_to(REPO_ROOT)
    report_path = out_dir / f"{date}.md"
    lines: list[str] = []
    lines.append(f"# A/B cutover smoke — {date}")
    lines.append("")
    lines.append("## Run summary")
    lines.append("")
    lines.append(f"- State file: `{rel_state}`")
    lines.append(f"- New-pipeline agent: `{agent.name}` (`{agent.model}`)")
    lines.append(f"- Wall: pre_cluster {t_pre:.2f}s, discovery {t_disc:.2f}s, "
                 f"grav-assign {t_grav:.2f}s, assemble {t_asm:.2f}s, "
                 f"**total {wall_total:.2f}s**")
    lines.append(f"- RSS Δ: {max(0.0, rss_after - rss_before):.0f} MB")
    lines.append(f"- LLM cost (new pipeline): ${llm_cost:.4f}")
    lines.append(f"- n_findings: {len(findings)}")
    lines.append(f"- n_micro_clusters: {pre_clusters.get('n_clusters', 0)}")
    lines.append(f"- n_discovered_topics (LLM): {n_disc}")
    lines.append(f"- n_topics_after_assemble: {n_new}")
    lines.append(f"- n_old_topics (legacy CuratorStage on disk): {len(old_topics)}")
    lines.append("")

    lines.append("## Orphan rate (observation, not gate)")
    lines.append("")
    lines.append(
        f"- Post-gravitational orphan count: **{n_orphans} / {len(findings)} = {orphan_pct} %**."
    )
    lines.append("")
    lines.append(
        "Orphan rate alone is misleading — lower can mean more off-topic "
        "drift into the topic centres, higher can mean tighter centres "
        "rejecting genuine matches. Real precision/recall validation "
        "requires labels against the new topic-centres (Brief 5b)."
    )
    lines.append("")

    lines.append("## Side-by-side topic comparison")
    lines.append("")
    lines.append(
        "Match score weights source-id Jaccard 0.6 and title-word Jaccard "
        "0.4. Scores above ~0.3 typically indicate a meaningful "
        "correspondence; below that the new topic is materially different "
        "from anything in the old output."
    )
    lines.append("")
    lines.append("| New topic | n_src (new) | Best old match | Score | Basis |")
    lines.append("|---|---:|---|---:|---|")
    for entry in side_by_side:
        new_t = entry["new_title"].replace("|", "/")
        old_t = (entry["matched_old_title"] or "—").replace("|", "/")
        new_t = new_t[:80] + ("..." if len(new_t) > 80 else "")
        old_t = old_t[:80] + ("..." if len(old_t) > 80 else "")
        lines.append(
            f"| {new_t} | {entry['new_source_count']} | {old_t} | "
            f"{entry['match_score']:.2f} | {entry['match_label']} |"
        )
    lines.append("")
    no_old_match = [e for e in side_by_side if e["match_score"] < 0.05]
    if no_old_match:
        lines.append(
            f"**{len(no_old_match)} new topics have no meaningful old-side "
            f"match** (score < 0.05) — newly surfaced stories or "
            f"granularity splits the old pipeline collapsed."
        )
    if old_orphans:
        lines.append("")
        lines.append(
            f"**{len(old_orphans)} old topics have no new-side match** — "
            f"the new pipeline either dissolved them across other topics "
            f"or filtered them out as noise:"
        )
        for t in old_orphans[:10]:
            lines.append(f"- `{t}`")
        if len(old_orphans) > 10:
            lines.append(f"- … +{len(old_orphans) - 10} more")
    lines.append("")

    lines.append("## Source-count distribution")
    lines.append("")
    lines.append("| Pipeline | n | min | median | mean | max |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    lines.append(
        f"| NEW | {sc_new['n']} | {sc_new['min']} | {sc_new['median']} | "
        f"{sc_new['mean']} | {sc_new['max']} |"
    )
    lines.append(
        f"| OLD | {sc_old['n']} | {sc_old['min']} | {sc_old['median']} | "
        f"{sc_old['mean']} | {sc_old['max']} |"
    )
    lines.append("")

    lines.append("## Geographic and language coverage")
    lines.append("")
    lines.append(
        f"- New regions ({len(new_regions)}): "
        f"{', '.join(f'{r} ({n})' for r, n in list(new_regions.items())[:12])}"
        + ("..." if len(new_regions) > 12 else "")
    )
    lines.append(
        f"- Old regions ({len(old_regions)}): "
        f"{', '.join(f'{r} ({n})' for r, n in list(old_regions.items())[:12])}"
        + ("..." if len(old_regions) > 12 else "")
    )
    lines.append("")
    lines.append(
        f"- New languages ({len(new_langs)}): "
        f"{', '.join(f'{l} ({n})' for l, n in list(new_langs.items())[:12])}"
        + ("..." if len(new_langs) > 12 else "")
    )
    lines.append(
        f"- Old languages ({len(old_langs)}): "
        f"{', '.join(f'{l} ({n})' for l, n in list(old_langs.items())[:12])}"
        + ("..." if len(old_langs) > 12 else "")
    )
    lines.append("")

    lines.append("## Status-descriptor counts (Curator-prompt rule 3)")
    lines.append("")
    lines.append(
        "Counts topics whose title or summary contains the targeted "
        "status descriptors. Should drop to zero or near-zero after the "
        "Brief-5 prompt patch."
    )
    lines.append("")
    lines.append("| descriptor | new | old |")
    lines.append("|---|---:|---:|")
    for key, _ in STATUS_DESCRIPTOR_PATTERNS:
        lines.append(f"| {key} | {sd_new[key]} | {sd_old[key]} |")
    total_new_sd = sum(sd_new.values())
    total_old_sd = sum(sd_old.values())
    lines.append(f"| **total** | **{total_new_sd}** | **{total_old_sd}** |")
    lines.append("")

    lines.append("## Qualitative observations")
    lines.append("")
    qualitative: list[str] = []
    # Topic-count delta
    if n_new < len(old_topics) - 2:
        qualitative.append(
            f"- Fewer topics ({n_new}) than the old pipeline ({len(old_topics)})."
        )
    elif n_new > len(old_topics) + 2:
        qualitative.append(
            f"- More topics ({n_new}) than the old pipeline ({len(old_topics)})."
        )
    # Status descriptors
    if total_new_sd > 0:
        qualitative.append(
            f"- {total_new_sd} new-pipeline topic(s) still carry a "
            f"status-descriptor flag (rule-3 patch did not fully suppress "
            f"the bias; surface as known limitation per VISION §10)."
        )
    else:
        qualitative.append(
            "- Status-descriptor count is zero on the new pipeline — "
            "rule-3 patch held."
        )
    # Source distribution
    if sc_new["mean"] > sc_old["mean"] * 2:
        qualitative.append(
            f"- Mean source_count per topic ({sc_new['mean']}) "
            f"is more than 2× the old pipeline's ({sc_old['mean']}) — "
            f"large catch-all topics may be surviving."
        )
    elif sc_new["mean"] < sc_old["mean"] / 4:
        qualitative.append(
            f"- Mean source_count per topic ({sc_new['mean']}) is well "
            f"below the old pipeline's ({sc_old['mean']}) — granularity "
            f"may be too fine."
        )
    # Topic-count band
    if not (10 <= n_disc <= 30):
        qualitative.append(
            f"- LLM emitted {n_disc} topics — outside the prompt's "
            f"stated 10–30 band."
        )
    if not qualitative:
        qualitative.append(
            "- No automated red flags. Architect editorial review still "
            "required — the load-bearing acceptance criterion is the "
            "side-by-side topic comparison above."
        )
    for q in qualitative:
        lines.append(q)
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [{date}] wrote {report_path.relative_to(REPO_ROOT)}")

    return {
        "date": date,
        "n_findings": len(findings),
        "n_micro_clusters": pre_clusters.get("n_clusters", 0),
        "n_discovered_topics": n_disc,
        "n_topics_after_assemble": n_new,
        "n_old_topics": len(old_topics),
        "n_orphans": n_orphans,
        "orphan_pct": orphan_pct,
        "llm_cost_usd": llm_cost,
        "wall_seconds": round(wall_total, 3),
        "status_descriptor_counts_new": sd_new,
        "status_descriptor_counts_old": sd_old,
        "status_descriptor_total_new": total_new_sd,
        "status_descriptor_total_old": total_old_sd,
        "side_by_side": side_by_side,
        "old_topics_with_no_new_match": old_orphans,
        "source_count_stats_new": sc_new,
        "source_count_stats_old": sc_old,
        "qualitative": qualitative,
    }


async def amain(args) -> int:
    datasets = (
        list(DATASETS.items())
        if args.dataset == "all"
        else [(args.dataset, DATASETS[args.dataset])]
    )

    agents = create_agents()
    agent = agents.get("curator_topic_discovery")
    if agent is None:
        print("!! curator_topic_discovery agent not registered in scripts/run.py")
        return 1

    print(f"== A/B cutover smoke — {len(datasets)} dataset(s) ==")
    print(f"   Agent: {agent.name} ({agent.model}, temp {agent.temperature}, "
          f"reasoning {agent.reasoning!r})")
    print(f"   Output: {OUT_ROOT.relative_to(REPO_ROOT)}/")
    results: list[dict] = []
    for date, state in datasets:
        r = await smoke_one(date, state, OUT_ROOT, agent)
        results.append(r)

    # Aggregate
    print("\n== Summary ==")
    print(
        f"{'date':<14} {'n_find':>7} {'n_old':>5} {'n_new':>5} "
        f"{'orph%':>6} {'sd_new':>6} {'$LLM':>7}"
    )
    total_cost = 0.0
    for r in results:
        if "error" in r:
            print(f"{r['date']:<14}  ERROR  {r['error']}")
            continue
        total_cost += r.get("llm_cost_usd", 0.0) or 0.0
        print(
            f"{r['date']:<14} {r['n_findings']:>7} {r['n_old_topics']:>5} "
            f"{r['n_topics_after_assemble']:>5} "
            f"{r['orphan_pct']:>5.1f}% "
            f"{r['status_descriptor_total_new']:>6} "
            f"${r['llm_cost_usd']:>5.3f}"
        )
    print(f"\n  Total LLM cost: ${total_cost:.4f}")

    summary_path = OUT_ROOT / "summary.json"
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "agent": agent.name,
                "model": agent.model,
                "total_llm_cost_usd": total_cost,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  Wrote {summary_path.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dataset",
        choices=list(DATASETS.keys()) + ["all"],
        default="all",
    )
    args = ap.parse_args()
    return asyncio.run(amain(args))


if __name__ == "__main__":
    sys.exit(main())
