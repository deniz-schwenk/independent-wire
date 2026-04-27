"""Smoke test for src.hydration_aggregator.

Exercises all four public functions end-to-end on the Lauf-19 hydration
results. For each topic with at least one successful T1 fetch:

  1. Calls ``run_aggregator`` and writes the raw output.
  2. Calls ``build_prepared_dossier`` and writes the result.
  3. Calls ``build_coverage_summary`` and writes the result.
  4. Calls ``merge_dossiers`` against the dummy web-dossier fixture and
     writes the merged dossier.

Prints per-topic source counts at each stage, total tokens, total wall-clock.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from src.hydration_aggregator import (
    AGGREGATOR_MODEL,
    AGGREGATOR_TEMPERATURE,
    AggregatorValidationError,
    PHASE2_MODEL,
    PHASE2_TEMPERATURE,
    PHASE_PROMPT_PATHS,
    build_coverage_summary,
    build_prepared_dossier,
    merge_dossiers,
    run_aggregator,
)
from src.agent import Agent

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITOR_ASSIGNMENTS = REPO_ROOT / "output/2026-04-19/03-editor-assignments.json"
WEB_DOSSIER_FIXTURE = REPO_ROOT / "tests/fixtures/dummy_web_dossier.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aggregator-module-smoke")


def find_latest_t1_results() -> Path:
    """Find the most recent output/*/test_hydration_module/results.json."""
    candidates = sorted(
        (REPO_ROOT / "output").glob("*/test_hydration_module/results.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            "No T1 smoke-test results found under output/*/test_hydration_module/"
        )
    return candidates[0]


def load_assignments_by_topic_code() -> dict[str, dict[str, Any]]:
    data = json.loads(EDITOR_ASSIGNMENTS.read_text())
    out: dict[str, dict[str, Any]] = {}
    for assignment in data:
        assn_id = assignment.get("id", "")
        code = assn_id.rsplit("-", 1)[-1] if assn_id else ""
        if code:
            out[code] = assignment
    return out


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


async def run_topic(
    phase1_agent: Agent,
    phase2_agent: Agent,
    topic_code: str,
    assignment: dict[str, Any],
    hydration_results: list[dict[str, Any]],
    web_dossier: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    slug = assignment.get("topic_slug") or f"topic-{topic_code}"
    successful = [r for r in hydration_results if r.get("status") == "success"]
    log.info(
        "topic %s (%s): %d hydration records, %d successful",
        topic_code, slug, len(hydration_results), len(successful),
    )

    try:
        aggregator_output = await run_aggregator(
            assignment, hydration_results,
            phase1_agent=phase1_agent, phase2_agent=phase2_agent,
        )
    except AggregatorValidationError as exc:
        log.error("topic %s: aggregator validation failed: %s", topic_code, exc)
        raise

    write_json(out_dir / f"aggregator_{slug}.json", aggregator_output)

    prepared = build_prepared_dossier(hydration_results, aggregator_output)
    write_json(out_dir / f"prepared_{slug}.json", prepared)

    coverage = build_coverage_summary(prepared)
    write_json(out_dir / f"coverage_{slug}.json", coverage)

    merged = merge_dossiers(prepared, web_dossier)
    write_json(out_dir / f"merged_{slug}.json", merged)

    return {
        "topic": topic_code,
        "slug": slug,
        "n_success_input": len(successful),
        "n_analyses": len(aggregator_output["article_analyses"]),
        "n_divergences": len(aggregator_output["preliminary_divergences"]),
        "n_gaps": len(aggregator_output["coverage_gaps"]),
        "n_prepared_sources": len(prepared["sources"]),
        "n_merged_sources": len(merged["sources"]),
        "n_merged_divergences": len(merged["preliminary_divergences"]),
        "n_merged_gaps": len(merged["coverage_gaps"]),
        "n_pre_sources_in_merge": len(prepared["sources"]),
        "merged_path": str(out_dir / f"merged_{slug}.json"),
    }


async def run_all() -> int:
    t1_results_path = find_latest_t1_results()
    log.info("Loaded T1 results from %s", t1_results_path)
    t1_results = json.loads(t1_results_path.read_text())

    assignments_by_code = load_assignments_by_topic_code()
    web_dossier = json.loads(WEB_DOSSIER_FIXTURE.read_text())

    by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in t1_results:
        code = record.get("topic")
        if code:
            by_topic[code].append(record)

    eligible = [
        code for code, recs in sorted(by_topic.items())
        if any(r.get("status") == "success" for r in recs)
        and code in assignments_by_code
    ]
    log.info("Eligible topics (≥1 success + editor assignment): %s", eligible)

    today = date.today().isoformat()
    out_dir = REPO_ROOT / "output" / today / "test_hydration_aggregator"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Two registered Agent instances — one per phase — built once and
    # reused across all topics. Mirrors the production registration in
    # scripts/test_hydration_pipeline.py:create_hydrated_agents().
    phase1_system, phase1_instructions = PHASE_PROMPT_PATHS["phase1"]
    phase2_system, phase2_instructions = PHASE_PROMPT_PATHS["phase2"]
    phase1_agent = Agent(
        name="hydration_aggregator_phase1",
        model=AGGREGATOR_MODEL,
        system_prompt_path=str(REPO_ROOT / phase1_system),
        instructions_path=str(REPO_ROOT / phase1_instructions),
        temperature=AGGREGATOR_TEMPERATURE,
        max_tokens=32000,
        provider="openrouter",
        reasoning="none",
    )
    phase2_agent = Agent(
        name="hydration_aggregator_phase2",
        model=PHASE2_MODEL,
        system_prompt_path=str(REPO_ROOT / phase2_system),
        instructions_path=str(REPO_ROOT / phase2_instructions),
        temperature=PHASE2_TEMPERATURE,
        max_tokens=32000,
        provider="openrouter",
        reasoning="none",
    )

    start = time.monotonic()
    summaries: list[dict[str, Any]] = []
    for code in eligible:
        summary = await run_topic(
            phase1_agent=phase1_agent,
            phase2_agent=phase2_agent,
            topic_code=code,
            assignment=assignments_by_code[code],
            hydration_results=by_topic[code],
            web_dossier=web_dossier,
            out_dir=out_dir,
        )
        summaries.append(summary)

    wall = time.monotonic() - start

    log.info("=" * 70)
    log.info("Per-topic counts:")
    log.info(
        "  %-4s %-48s %6s %8s %8s %8s",
        "code", "slug", "succ", "prepared", "merged", "div/gap",
    )
    for s in summaries:
        log.info(
            "  %-4s %-48s %6d %8d %8d %4d/%-3d",
            s["topic"], s["slug"][:48],
            s["n_success_input"], s["n_prepared_sources"],
            s["n_merged_sources"],
            s["n_merged_divergences"], s["n_merged_gaps"],
        )
    log.info("=" * 70)
    log.info("Total wall-clock: %.1fs", wall)
    log.info("Output dir: %s", out_dir)
    log.info(
        "Cost: not tracked per-call by src.agent.Agent; model=%s, "
        "expect ~$0.03 total based on Spike C rates (~$0.015 per topic).",
        AGGREGATOR_MODEL,
    )

    # Light post-run acceptance checks.
    problems: list[str] = []
    for s in summaries:
        if s["n_analyses"] != s["n_success_input"]:
            problems.append(
                f"topic {s['topic']}: {s['n_analyses']} analyses vs "
                f"{s['n_success_input']} success inputs"
            )
        if s["n_prepared_sources"] != s["n_success_input"]:
            problems.append(
                f"topic {s['topic']}: prepared={s['n_prepared_sources']} vs "
                f"success={s['n_success_input']}"
            )

    # T2-followup: verbatim_quote preservation and normalisation.
    expected_actor_keys = {"name", "role", "type", "position", "verbatim_quote"}
    any_verbatim = False
    for s in summaries:
        merged = json.loads(Path(s["merged_path"]).read_text())
        n_pre = s["n_pre_sources_in_merge"]
        for src_idx, source in enumerate(merged.get("sources", [])):
            for actor in source.get("actors_quoted") or []:
                if set(actor.keys()) != expected_actor_keys:
                    problems.append(
                        f"topic {s['topic']} source {src_idx} actor "
                        f"{actor.get('name')!r}: keys={sorted(actor.keys())} "
                        f"(expected exactly {sorted(expected_actor_keys)})"
                    )
                if src_idx >= n_pre and actor.get("verbatim_quote") is not None:
                    problems.append(
                        f"topic {s['topic']} source {src_idx} (web-search "
                        f"origin): verbatim_quote is not null"
                    )
                if src_idx < n_pre and isinstance(actor.get("verbatim_quote"), str):
                    any_verbatim = True

    if not any_verbatim:
        problems.append(
            "no non-null verbatim_quote found in any merged dossier "
            "(Aggregator should have extracted at least one across 3 topics)"
        )

    if problems:
        log.error("Post-run checks failed:")
        for p in problems:
            log.error("  - %s", p)
        return 1
    log.info("Post-run checks: OK (verbatim_quote preserved, actor shape uniform)")
    return 0


def main() -> int:
    return asyncio.run(run_all())


if __name__ == "__main__":
    raise SystemExit(main())
