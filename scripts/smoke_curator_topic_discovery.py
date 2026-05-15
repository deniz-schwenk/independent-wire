"""End-to-end smoke harness for ``CuratorTopicDiscoveryStage``.

Authoritative reference: TASK-CURATOR-TOPIC-DISCOVERY-STAGE.md §"Smoke
harness".

For each of the three eval-anchor state files (2026-05-08,
2026-05-11-v1-baseline, 2026-05-13):

  1. Load ``curator_findings``.
  2. Run Brief 1's ``pre_cluster_findings`` against those findings to
     produce ``curator_pre_clusters``.
  3. Run the new ``CuratorTopicDiscoveryStage`` against the populated
     RunBus — real LLM call, real fastembed.
  4. Render a Markdown summary with the complete topic list (title +
     summary), the run summary, and an anomaly note section.

Output: ``docs/curator-topic-discovery/smoke-2026-05-16/{date}.md`` +
``summary.json``. **The load-bearing acceptance criterion for Brief 4
is the architect's editorial review of this output — do the topics
look like stories, not categories? Did K=8 produce coherent input?**

Cost: ~€0.05 per call at Gemini 3 Flash, ~€0.20 for three runs.
Surfaces if cost diverges materially.

Usage:
    python scripts/smoke_curator_topic_discovery.py
    python scripts/smoke_curator_topic_discovery.py --dataset 2026-05-13
"""

from __future__ import annotations

import argparse
import asyncio
import json
import resource
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agent_stages import CuratorTopicDiscoveryStage  # noqa: E402
from src.bus import RunBus  # noqa: E402
from src.stages.pre_cluster import pre_cluster_findings  # noqa: E402

# scripts/run.py builds the production agents (incl. curator_topic_discovery).
# We import the registry helper rather than re-declaring an Agent here so the
# smoke uses the exact agent registration Brief 5 will wire in production.
from scripts.run import create_agents  # noqa: E402


DATASETS: dict[str, Path] = {
    "2026-05-08": REPO_ROOT
    / "output/2026-05-08/_state/run-2026-05-08-607bb556/run_bus.CuratorStage.json",
    "2026-05-11": REPO_ROOT
    / "output/2026-05-11-v1-baseline/_state/run-2026-05-11-722571ae/run_bus.CuratorStage.json",
    "2026-05-13": REPO_ROOT
    / "output/2026-05-13/_state/run-2026-05-13-bb2bce61/run_bus.CuratorStage.json",
}


OUT_ROOT = REPO_ROOT / "docs" / "curator-topic-discovery" / "smoke-2026-05-16"


def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0
    return raw * unit / 1e6


def _load_findings(state_path: Path) -> list[dict]:
    with state_path.open() as f:
        data = json.load(f)
    return list(data.get("curator_findings") or [])


async def smoke_one(
    date: str,
    state_path: Path,
    out_dir: Path,
    agent,
) -> dict:
    if not state_path.exists():
        return {"date": date, "error": "state-missing"}

    print(f"  [{date}] loading {state_path.relative_to(REPO_ROOT)} ...")
    findings = _load_findings(state_path)
    print(f"  [{date}] {len(findings)} findings → running pre_cluster ...")

    rb = RunBus(
        run_id=f"smoke-{date}-discovery",
        run_date=date,
        curator_findings=findings,
    )

    # 1. Pre-cluster (Brief 1)
    rss_before = _rss_mb_now()
    t_pc = time.monotonic()
    rb = await pre_cluster_findings(rb)
    pc_wall = time.monotonic() - t_pc
    n_pre = rb.curator_pre_clusters.get("n_clusters", 0)
    print(f"  [{date}] pre_cluster: {n_pre} micro-clusters in {pc_wall:.1f}s")

    # 2. Topic-Discovery (Brief 4)
    stage = CuratorTopicDiscoveryStage(agent)
    print(f"  [{date}] topic discovery — calling LLM ...")
    t_td = time.monotonic()
    rb = await stage(rb)
    td_wall = time.monotonic() - t_td
    rss_after = _rss_mb_now()

    cdt = rb.curator_discovered_topics
    n_topics = cdt.get("n_topics", 0)
    cost = cdt.get("llm_cost_usd", 0.0)
    print(
        f"  [{date}] discovered {n_topics} topics in {td_wall:.1f}s "
        f"(LLM ${cost:.4f})"
    )

    # Render Markdown report
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{date}.md"
    rel_state = state_path.relative_to(REPO_ROOT)

    lines: list[str] = []
    lines.append(f"# Curator topic-discovery smoke — {date}")
    lines.append("")
    lines.append("## Run summary")
    lines.append("")
    lines.append(f"- State file: `{rel_state}`")
    lines.append(f"- Agent: `{cdt.get('agent_name', '')}`")
    lines.append(f"- Model: `{cdt.get('model_name', '')}`")
    params = cdt.get("params", {}) or {}
    lines.append(
        f"- Params: temperature={params.get('temperature')}, "
        f"max_tokens={params.get('max_tokens')}, "
        f"reasoning={params.get('reasoning')!r}"
    )
    lines.append(f"- K (sample_titles_per_cluster): {cdt.get('sample_titles_per_cluster')}")
    lines.append(f"- Pre-cluster wall: {pc_wall:.2f} s")
    lines.append(f"- Topic-discovery wall: {td_wall:.2f} s")
    lines.append(f"- RSS Δ (full smoke): {max(0.0, rss_after - rss_before):.0f} MB")
    lines.append(f"- n_findings: {len(findings)}")
    lines.append(f"- n_micro_clusters_input: {cdt.get('n_micro_clusters_input')}")
    lines.append(f"- n_topics_output: {n_topics}")
    lines.append(f"- LLM cost (USD): ${cost:.4f}")
    lines.append(f"- Tokens used: {cdt.get('tokens_used')}")
    lines.append("")

    lines.append("## Discovered topics")
    lines.append("")
    lines.append("Complete list, in the order the LLM emitted them.")
    lines.append("")
    for i, t in enumerate(cdt.get("topics", []), start=1):
        title = t.get("title", "")
        summary = t.get("summary", "")
        lines.append(f"### {i}. {title}")
        lines.append("")
        lines.append(summary)
        lines.append("")

    lines.append("## Anomaly notes")
    lines.append("")
    # Some automated sanity checks — surface for the architect's eye.
    anomalies: list[str] = []
    catchall_signals = ("other news", "miscellaneous", "various", "general news")
    category_signals = (
        "middle east news", "asia news", "europe news", "africa news",
        "domestic news", "international news", "world news",
    )
    titles_lower = [(t.get("title") or "").lower() for t in cdt.get("topics", [])]
    for ts in titles_lower:
        for marker in catchall_signals:
            if marker in ts:
                anomalies.append(
                    f"- Catch-all signal in topic title: \"{ts}\" "
                    f"(contains '{marker}')"
                )
        for marker in category_signals:
            if marker in ts:
                anomalies.append(
                    f"- Category-shape signal in topic title: \"{ts}\" "
                    f"(contains '{marker}')"
                )
    if not (10 <= n_topics <= 30):
        anomalies.append(
            f"- n_topics={n_topics} is outside the prompt's stated 10–30 band."
        )
    if anomalies:
        for a in anomalies:
            lines.append(a)
    else:
        lines.append(
            "No automated anomaly signals tripped. Architect review still "
            "required — the editorial coherence of the topic list is the "
            "load-bearing acceptance criterion."
        )
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  [{date}] wrote {report_path.relative_to(REPO_ROOT)}")

    return {
        "date": date,
        "state_file": str(rel_state),
        "n_findings": len(findings),
        "n_micro_clusters_input": cdt.get("n_micro_clusters_input"),
        "n_topics_output": n_topics,
        "pre_cluster_wall_seconds": round(pc_wall, 3),
        "topic_discovery_wall_seconds": round(td_wall, 3),
        "llm_cost_usd": cost,
        "tokens_used": cdt.get("tokens_used"),
        "topics": cdt.get("topics", []),
        "automated_anomalies": anomalies,
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

    print(f"== Curator topic-discovery smoke — {len(datasets)} dataset(s) ==")
    print(f"   agent={agent.name}, model={agent.model}, "
          f"temp={agent.temperature}, reasoning={agent.reasoning!r}, "
          f"max_tokens={agent.max_tokens}")
    results: list[dict] = []
    for date, state in datasets:
        r = await smoke_one(date, state, OUT_ROOT, agent)
        results.append(r)

    # Aggregate
    print("\n== Summary ==")
    print(
        f"{'date':<14} {'n_find':>7} {'n_micro':>8} {'n_top':>6} "
        f"{'pc_s':>5} {'td_s':>5} {'$LLM':>7} {'tok':>7}"
    )
    total_cost = 0.0
    for r in results:
        if "error" in r:
            print(f"{r['date']:<14}  ERROR  {r['error']}")
            continue
        total_cost += r.get("llm_cost_usd", 0.0) or 0.0
        print(
            f"{r['date']:<14} {r['n_findings']:>7} "
            f"{r['n_micro_clusters_input']:>8} {r['n_topics_output']:>6} "
            f"{r['pre_cluster_wall_seconds']:>4.1f}s "
            f"{r['topic_discovery_wall_seconds']:>4.1f}s "
            f"${r['llm_cost_usd']:>5.3f} {r['tokens_used']:>7}"
        )
    print(f"\n  Total LLM cost: ${total_cost:.4f}")

    summary_path = OUT_ROOT / "summary.json"
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            {
                "agent": agent.name,
                "model": agent.model,
                "params": {
                    "temperature": agent.temperature,
                    "max_tokens": agent.max_tokens,
                    "reasoning": agent.reasoning,
                },
                "sample_titles_per_cluster": 8,
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
