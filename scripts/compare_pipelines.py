#!/usr/bin/env python3
"""Independent Wire — A/B compare report (Production vs Hydrated).

Runs both pipelines on a shared Curator + Editor run and renders a
Markdown report comparing deterministic per-topic metrics. Output is
consumed by a separate Claude Project for qualitative judgement; this
script produces no LLM-based evaluation.

Usage:

    python scripts/compare_pipelines.py [--date YYYY-MM-DD] [--fetch]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.models import PipelineState, TopicAssignment, TopicPackage  # noqa: E402
from src.pipeline import Pipeline, _normalise_country  # noqa: E402
from src.pipeline_hydrated import PipelineHydrated  # noqa: E402
from run import create_agents  # noqa: E402
from test_hydration_pipeline import (  # noqa: E402
    _build_hydration_urls,
    _load_country_lookup,
    _match_cluster,
    create_hydrated_agents,
)

log = logging.getLogger("compare_pipelines")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------- state / dir prep -------------------------------------------

def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


async def _preflight_state(
    pipeline: Pipeline,
    date: str,
    assignments: list[TopicAssignment],
    run_id_suffix: str,
) -> None:
    """Pre-populate pipeline.state and persist it to state_dir so the
    subsequent ``pipeline.run()`` resumes from ``produce``."""
    pipeline.state = PipelineState(
        run_id=f"run-{date}-{run_id_suffix}",
        date=date,
        current_step="produce",
        completed_steps=["collect", "curate", "editorial_conference"],
        assignments=[asdict(a) for a in assignments],
        started_at=datetime.now().isoformat(),
    )
    await pipeline._save_state()


# ---------- hydration URL attachment -----------------------------------

def _attach_hydration_urls(
    assignments: list[TopicAssignment],
    clusters_path: Path,
    feeds_path: Path,
    sources_path: Path,
) -> list[TopicAssignment]:
    if not clusters_path.exists():
        raise SystemExit(f"Required Curator clusters missing: {clusters_path}")
    if not feeds_path.exists():
        raise SystemExit(f"Required feeds.json missing: {feeds_path}")
    clusters = json.loads(clusters_path.read_text(encoding="utf-8"))
    feeds = json.loads(feeds_path.read_text(encoding="utf-8"))
    country_by_outlet = _load_country_lookup(sources_path)
    out: list[TopicAssignment] = []
    for a in assignments:
        cluster = _match_cluster(a.title, clusters)
        if cluster is None:
            log.error(
                "No cluster match for assignment %r (title=%r); skipping",
                a.id, a.title,
            )
            continue
        urls = _build_hydration_urls(cluster, feeds, country_by_outlet)
        raw_data = dict(a.raw_data or {})
        raw_data["hydration_urls"] = urls
        raw_data["source_count"] = len(urls)
        log.info("%s → cluster %r: %d URLs", a.id, cluster.get("title"), len(urls))
        out.append(TopicAssignment(
            id=a.id,
            title=a.title,
            priority=a.priority,
            topic_slug=a.topic_slug,
            selection_reason=a.selection_reason,
            raw_data=raw_data,
            follow_up_to=a.follow_up_to,
            follow_up_reason=a.follow_up_reason,
        ))
    return out


# ---------- phases ------------------------------------------------------

async def phase_0_shared(
    date: str,
    root_dir: Path,
    *,
    max_produce: int,
) -> tuple[list[TopicAssignment], Pipeline, float]:
    """Run Curator + Editor via a plain Pipeline instance. Return the
    final filtered/sorted/sliced assignments plus the pipeline for stats
    aggregation and the wall-clock duration."""
    output_dir = root_dir / "shared"
    state_dir = ROOT / "state" / "compare" / date / "shared"
    _reset_dir(state_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    agents = create_agents()
    pipeline = Pipeline(
        name="compare_shared",
        agents=agents,
        output_dir=str(output_dir),
        state_dir=str(state_dir),
        max_topics=10,
        max_produce=max_produce,
        mode="quick",
    )
    log.info("Phase 0: shared Curator + Editor run")
    start = time.monotonic()
    await pipeline.run(date=date, to_step="editor")
    duration = time.monotonic() - start

    raw = [TopicAssignment(**a) for a in pipeline.state.assignments]
    produced = [a for a in raw if a.priority > 0]
    produced.sort(
        key=lambda a: (-a.priority, -len(a.raw_data.get("source_ids", []))),
    )
    selected = produced[:max_produce]
    log.info(
        "Phase 0 done in %.1fs: %d editor assignments, %d after priority>0, "
        "top %d selected", duration, len(raw), len(produced), len(selected),
    )
    return selected, pipeline, duration


async def phase_1_production(
    date: str,
    root_dir: Path,
    assignments: list[TopicAssignment],
) -> tuple[Pipeline, list[TopicPackage], float]:
    output_dir = root_dir / "production"
    state_dir = ROOT / "state" / "compare" / date / "production"
    _reset_dir(state_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    agents = create_agents()
    pipeline = Pipeline(
        name="compare_production",
        agents=agents,
        output_dir=str(output_dir),
        state_dir=str(state_dir),
        max_topics=10,
        max_produce=len(assignments),
        mode="quick",
    )
    await _preflight_state(pipeline, date, assignments, f"cmpA{uuid4().hex[:4]}")

    log.info("Phase 1: production pipeline produce")
    start = time.monotonic()
    packages = await pipeline.run(date=date)
    duration = time.monotonic() - start
    log.info(
        "Phase 1 done in %.1fs: %d TPs (%d failed)", duration, len(packages),
        sum(1 for p in packages if p.status == "failed"),
    )
    return pipeline, packages, duration


async def phase_2_hydrated(
    date: str,
    root_dir: Path,
    assignments: list[TopicAssignment],
    clusters_path: Path,
    feeds_path: Path,
) -> tuple[PipelineHydrated, list[TopicPackage], float]:
    output_dir = root_dir / "hydrated"
    state_dir = ROOT / "state" / "compare" / date / "hydrated"
    _reset_dir(state_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sources_path = ROOT / "config" / "sources.json"
    hydrated_assignments = _attach_hydration_urls(
        assignments, clusters_path, feeds_path, sources_path,
    )
    if not hydrated_assignments:
        raise SystemExit("No assignments with resolvable hydration_urls; aborting Phase 2")

    agents = create_hydrated_agents()
    pipeline = PipelineHydrated(
        name="compare_hydrated",
        agents=agents,
        output_dir=str(output_dir),
        state_dir=str(state_dir),
        max_topics=10,
        max_produce=len(hydrated_assignments),
        mode="quick",
    )
    await _preflight_state(pipeline, date, hydrated_assignments, f"cmpB{uuid4().hex[:4]}")

    log.info("Phase 2: hydrated pipeline produce")
    start = time.monotonic()
    packages = await pipeline.run(date=date)
    duration = time.monotonic() - start
    log.info(
        "Phase 2 done in %.1fs: %d TPs (%d failed)", duration, len(packages),
        sum(1 for p in packages if p.status == "failed"),
    )
    return pipeline, packages, duration


# ---------- metric extraction -------------------------------------------

def _load_tp_from_disk(output_dir: Path, date: str, pkg_id: str) -> dict | None:
    path = output_dir / date / f"{pkg_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        log.warning("Could not parse TP %s: %s", path, e)
        return None


def _outlets(tp: dict) -> set[str]:
    return {
        (s.get("outlet") or "").strip()
        for s in tp.get("sources", []) or []
        if (s.get("outlet") or "").strip()
    }


def _languages(tp: dict) -> list[str]:
    langs = [(s.get("language") or "").strip() for s in tp.get("sources", []) or []]
    return sorted({l for l in langs if l})


def _countries(tp: dict) -> list[str]:
    seen: set[str] = set()
    for s in tp.get("sources", []) or []:
        c = _normalise_country(s.get("country"))
        if c:
            seen.add(c)
    return sorted(seen)


def _stakeholder_count(tp: dict) -> int:
    return len(tp.get("perspectives") or [])


def _stakeholders_with_sources(tp: dict) -> int:
    return sum(
        1 for p in (tp.get("perspectives") or [])
        if p.get("source_ids")
    )


def _verbatim_count(tp: dict) -> int:
    count = 0
    for s in tp.get("sources", []) or []:
        for a in s.get("actors_quoted") or []:
            if a.get("verbatim_quote"):
                count += 1
    return count


def _article_word_count(tp: dict) -> int:
    article = tp.get("article") or {}
    text = " ".join([
        article.get("headline") or "",
        article.get("subheadline") or "",
        article.get("body") or "",
    ])
    return len(text.split())


def _cost_by_agent(stats: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for s in stats:
        c = s.get("cost_usd")
        out[s["agent"]] = out.get(s["agent"], 0.0) + (float(c) if c is not None else 0.0)
    return out


def _total_cost(stats: list[dict]) -> float:
    return sum(float(s.get("cost_usd") or 0.0) for s in stats)


def _total_tokens(stats: list[dict]) -> int:
    return sum(int(s.get("tokens_used") or 0) for s in stats)


def _agents_missing_cost(stats: list[dict]) -> list[str]:
    """Agents whose total cost summed to 0.0 (indicates provider omitted
    cost for that model). Uses set-of-names union."""
    costs: dict[str, float] = {}
    for s in stats:
        c = s.get("cost_usd")
        val = float(c) if c is not None else 0.0
        costs[s["agent"]] = costs.get(s["agent"], 0.0) + val
    return sorted(a for a, total in costs.items() if total == 0.0)


def _fetch_success_rate(hydrated_output_dir: Path, date: str) -> tuple[int, int]:
    base = hydrated_output_dir / date / "test_hydration"
    if not base.exists():
        return 0, 0
    total = 0
    success = 0
    for path in sorted(base.glob("04a-hydration-fetch-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        for entry in data:
            if not isinstance(entry, dict):
                continue
            total += 1
            if entry.get("status") == "success":
                success += 1
    return success, total


# ---------- report rendering --------------------------------------------

def _fmt_delta_num(a: int | float | None, b: int | float | None) -> str:
    if a is None or b is None:
        return "n/a"
    delta = b - a
    if isinstance(delta, float):
        return f"{delta:+.4f}"
    return f"{delta:+d}"


def _fmt_int(v: int | None) -> str:
    return "n/a" if v is None else str(v)


def _fmt_list(items: list[str]) -> str:
    if not items:
        return "none"
    return ", ".join(items)


def _fmt_money(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"${v:.4f}"


def _row(label: str, a_val, b_val, formatter=None) -> str:
    fmt = formatter or (lambda x: "n/a" if x is None else str(x))
    return f"| {label} | {fmt(a_val)} | {fmt(b_val)} | {_fmt_delta_num(a_val, b_val)} |"


def _match_tp(
    assignment: TopicAssignment,
    packages_a: list[TopicPackage],
    packages_b: list[TopicPackage],
    dir_a: Path,
    dir_b: Path,
    date: str,
) -> tuple[dict | None, TopicPackage | None, dict | None, TopicPackage | None]:
    """Return (tp_a_dict, pkg_a, tp_b_dict, pkg_b) for an assignment.

    Primary match: pkg.id == assignment.id. Fallback: metadata title
    match (case-insensitive)."""
    def find(packages: list[TopicPackage]) -> TopicPackage | None:
        for p in packages:
            if p.id == assignment.id:
                return p
        title_l = assignment.title.strip().lower()
        for p in packages:
            if (p.metadata.get("title") or "").strip().lower() == title_l:
                return p
        return None

    pkg_a = find(packages_a)
    pkg_b = find(packages_b)
    tp_a = _load_tp_from_disk(dir_a, date, pkg_a.id) if pkg_a and pkg_a.status != "failed" else None
    tp_b = _load_tp_from_disk(dir_b, date, pkg_b.id) if pkg_b and pkg_b.status != "failed" else None
    return tp_a, pkg_a, tp_b, pkg_b


def _metrics_table(tp_a: dict | None, tp_b: dict | None) -> str:
    lines = [
        "| Metric | A (Production) | B (Hydrated) | Delta |",
        "| --- | --- | --- | --- |",
    ]

    def val(tp: dict | None, fn):
        return fn(tp) if tp is not None else None

    # Source count
    lines.append(_row(
        "Source count",
        val(tp_a, lambda t: len(t.get("sources") or [])),
        val(tp_b, lambda t: len(t.get("sources") or [])),
    ))
    # Language count
    lang_a = val(tp_a, _languages)
    lang_b = val(tp_b, _languages)
    lines.append(_row(
        "Languages (count)",
        len(lang_a) if lang_a is not None else None,
        len(lang_b) if lang_b is not None else None,
    ))
    lines.append(
        f"| Languages (list) | {_fmt_list(lang_a or [])} | {_fmt_list(lang_b or [])} | — |"
    )
    # Country count
    cty_a = val(tp_a, _countries)
    cty_b = val(tp_b, _countries)
    lines.append(_row(
        "Countries (count)",
        len(cty_a) if cty_a is not None else None,
        len(cty_b) if cty_b is not None else None,
    ))
    lines.append(
        f"| Countries (list) | {_fmt_list(cty_a or [])} | {_fmt_list(cty_b or [])} | — |"
    )
    # Stakeholders
    lines.append(_row("Stakeholder count", val(tp_a, _stakeholder_count), val(tp_b, _stakeholder_count)))
    lines.append(_row(
        "Stakeholders with source_ids",
        val(tp_a, _stakeholders_with_sources),
        val(tp_b, _stakeholders_with_sources),
    ))
    # Verbatim quotes
    lines.append(_row(
        "Verbatim quotes in sources",
        val(tp_a, _verbatim_count),
        val(tp_b, _verbatim_count),
    ))
    # Word count
    lines.append(_row("Article word count", val(tp_a, _article_word_count), val(tp_b, _article_word_count)))
    return "\n".join(lines)


def _cost_breakdown_table(
    stats_a: list[dict], stats_b: list[dict], slug: str,
) -> str:
    per_a = _cost_by_agent([s for s in stats_a if s.get("topic") == slug])
    per_b = _cost_by_agent([s for s in stats_b if s.get("topic") == slug])
    agents = sorted(set(per_a) | set(per_b))
    lines = ["| Agent | A | B |", "| --- | --- | --- |"]
    for ag in agents:
        lines.append(
            f"| {ag} | {_fmt_money(per_a.get(ag, 0.0))} | {_fmt_money(per_b.get(ag, 0.0))} |"
        )
    return "\n".join(lines)


def render_report(
    *,
    date: str,
    compare_run_id: str,
    total_duration_s: float,
    assignments: list[TopicAssignment],
    packages_a: list[TopicPackage],
    packages_b: list[TopicPackage],
    stats_a: list[dict],
    stats_b: list[dict],
    duration_a: float,
    duration_b: float,
    dir_a: Path,
    dir_b: Path,
    fetch_success: int,
    fetch_total: int,
) -> str:
    total_cost_a = _total_cost(stats_a)
    total_cost_b = _total_cost(stats_b)
    total_tokens_a = _total_tokens(stats_a)
    total_tokens_b = _total_tokens(stats_b)
    cost_delta = total_cost_b - total_cost_a
    pct_delta = (cost_delta / total_cost_a * 100.0) if total_cost_a else 0.0

    lines: list[str] = []
    lines.append(f"# A/B Compare Report — {date}")
    lines.append("")
    lines.append(f"Run: {compare_run_id}")
    lines.append(f"Duration: {total_duration_s / 60.0:.1f}m")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("Pipeline A: Production (`src.pipeline.Pipeline`)")
    lines.append("Pipeline B: Hydrated (`src.pipeline_hydrated.PipelineHydrated`)")
    lines.append("")
    lines.append(f"Topics compared: {len(assignments)}")
    lines.append(f"Total cost A: {_fmt_money(total_cost_a)}")
    lines.append(f"Total cost B: {_fmt_money(total_cost_b)}")
    lines.append(
        f"Cost delta: {_fmt_money(cost_delta)} "
        f"({pct_delta:+.1f}%)"
    )
    lines.append(f"Total tokens A: {total_tokens_a}")
    lines.append(f"Total tokens B: {total_tokens_b}")
    lines.append(f"Runtime A: {duration_a / 60.0:.1f}m")
    lines.append(f"Runtime B: {duration_b / 60.0:.1f}m")
    if fetch_total:
        lines.append(
            f"Hydration fetch success: {fetch_success}/{fetch_total} "
            f"({fetch_success * 100.0 / fetch_total:.1f}%)"
        )
    else:
        lines.append("Hydration fetch success: n/a (no hydration debug found)")

    missing_cost = sorted(
        set(_agents_missing_cost(stats_a)) | set(_agents_missing_cost(stats_b))
    )
    if missing_cost:
        lines.append("")
        lines.append(
            "_Note: agents with total cost $0.00 (OpenRouter did not report "
            "cost, or agent was free)_: " + ", ".join(missing_cost)
        )

    lines.append("")

    for a in assignments:
        tp_a, pkg_a, tp_b, pkg_b = _match_tp(
            a, packages_a, packages_b, dir_a, dir_b, date,
        )
        slug = a.topic_slug or a.id
        lines.append(f"## Topic: {slug}")
        lines.append("")
        lines.append(f"Assignment title: {a.title}")

        def path_cell(pkg: TopicPackage | None, directory: Path) -> str:
            if pkg is None:
                return "MISSING"
            if pkg.status == "failed":
                return f"FAILED: {pkg.error or 'unknown error'}"
            return f"`{(directory / date / (pkg.id + '.json')).resolve()}`"

        lines.append(f"TP A: {path_cell(pkg_a, dir_a)}")
        lines.append(f"TP B: {path_cell(pkg_b, dir_b)}")
        lines.append("")
        lines.append("### Metrics")
        lines.append("")
        lines.append(_metrics_table(tp_a, tp_b))
        lines.append("")

        outlets_a = _outlets(tp_a) if tp_a else set()
        outlets_b = _outlets(tp_b) if tp_b else set()
        only_a = sorted(outlets_a - outlets_b)
        only_b = sorted(outlets_b - outlets_a)
        shared = sorted(outlets_a & outlets_b)

        lines.append("### Unique outlets only in A")
        if only_a:
            for o in only_a:
                lines.append(f"- {o}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("### Unique outlets only in B")
        if only_b:
            for o in only_b:
                lines.append(f"- {o}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append(f"### Shared outlets ({len(shared)})")
        if shared:
            for o in shared:
                lines.append(f"- {o}")
        else:
            lines.append("- none")
        lines.append("")
        lines.append("### Cost breakdown")
        lines.append("")
        lines.append(_cost_breakdown_table(stats_a, stats_b, slug))
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------- main --------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Production vs Hydrated A/B compare"
    )
    p.add_argument(
        "--date", default=datetime.now().strftime("%Y-%m-%d"),
        help="Date for the run (YYYY-MM-DD). Default: today.",
    )
    p.add_argument(
        "--fetch", action="store_true",
        help="Run scripts/fetch_feeds.py before Phase 0",
    )
    return p.parse_args()


async def main() -> int:
    args = _parse_args()
    setup_logging()
    date = args.date
    compare_run_id = f"compare-{date}-{uuid4().hex[:6]}"

    log.info("Compare run %s (date=%s)", compare_run_id, date)

    if args.fetch:
        log.info("Fetching feeds...")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "fetch_feeds.py")],
        )
        if result.returncode != 0:
            log.error("fetch_feeds.py failed (exit %d)", result.returncode)
            return 1

    root_dir = ROOT / "output" / "compare" / date
    root_dir.mkdir(parents=True, exist_ok=True)

    total_start = time.monotonic()

    # Phase 0 — shared Curator + Editor
    assignments, pipeline_shared, duration_shared = await phase_0_shared(
        date, root_dir, max_produce=3,
    )
    if not assignments:
        log.error("Phase 0 produced no assignments; aborting.")
        return 1

    # Phase 1 — Production
    pipeline_a, packages_a, duration_a = await phase_1_production(
        date, root_dir, assignments,
    )

    # Phase 2 — Hydrated
    clusters_path = root_dir / "shared" / date / "02-curator-topics-unsliced.json"
    feeds_path = ROOT / "raw" / date / "feeds.json"
    pipeline_b, packages_b, duration_b = await phase_2_hydrated(
        date, root_dir, assignments, clusters_path, feeds_path,
    )

    total_duration = time.monotonic() - total_start

    # Phase 3+4 — metric extraction + report
    dir_a = root_dir / "production"
    dir_b = root_dir / "hydrated"
    fetch_success, fetch_total = _fetch_success_rate(dir_b, date)

    # Combine shared pipeline stats (Curator+Editor) into both A and B
    # since both pipelines logically depended on that work. We attribute
    # shared stats to A only, to avoid double-counting in totals.
    stats_a = pipeline_shared._agent_stats + pipeline_a._agent_stats
    stats_b = pipeline_b._agent_stats

    report_md = render_report(
        date=date,
        compare_run_id=compare_run_id,
        total_duration_s=total_duration,
        assignments=assignments,
        packages_a=packages_a,
        packages_b=packages_b,
        stats_a=stats_a,
        stats_b=stats_b,
        duration_a=duration_shared + duration_a,
        duration_b=duration_b,
        dir_a=dir_a,
        dir_b=dir_b,
        fetch_success=fetch_success,
        fetch_total=fetch_total,
    )
    report_path = root_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    log.info("Report written: %s", report_path)

    completed_a = [p for p in packages_a if p.status != "failed"]
    completed_b = [p for p in packages_b if p.status != "failed"]
    log.info(
        "Done: %d/%d A, %d/%d B in %.1fm",
        len(completed_a), len(packages_a),
        len(completed_b), len(packages_b),
        total_duration / 60.0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
