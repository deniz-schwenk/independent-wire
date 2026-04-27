"""Independent Wire — T3 orchestrator for the hydrated pipeline.

Drives :class:`src.pipeline_hydrated.PipelineHydrated` against a completed
production run. Reuses that run's Editor assignments and Curator clusters so
the hydrated pipeline produces side-by-side Topic Packages without re-running
collection / curation / editorial steps.

Usage:

    python scripts/test_hydration_pipeline.py --date 2026-04-19

Outputs:
    - Hydrated TPs at ``output/{date}/test_hydration/tp-{slug}.json``
    - Intermediate debug artefacts at ``output/{date}/test_hydration/``

The orchestrator does not render HTML and does not publish.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent  # noqa: E402
from src.models import PipelineState, TopicAssignment  # noqa: E402
from src.pipeline_hydrated import PipelineHydrated  # noqa: E402
from src.tools import web_search_tool  # noqa: E402


def setup_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("t3_orchestrator")


# ---------- input resolution ----------

_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "and", "or", "to", "for", "as", "is",
    "by", "at", "with", "from", "after", "into", "that", "which", "it", "its",
    "be", "are", "was", "were", "this", "over", "amid", "against", "about",
    "near", "upon", "has", "have", "had", "been", "being", "will", "shall",
})


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def _match_cluster(assignment_title: str, clusters: list[dict]) -> dict | None:
    """Match an Editor assignment to its originating Curator cluster by
    title-word overlap. Returns ``None`` if no cluster scores ≥ 2 shared
    terms (indicates a genuine mismatch rather than a noisy win)."""
    a_tokens = _tokens(assignment_title)
    best: dict | None = None
    best_score = 0
    for cluster in clusters:
        score = len(a_tokens & _tokens(cluster.get("title", "")))
        if score > best_score:
            best_score = score
            best = cluster
    if best_score < 2:
        return None
    return best


def _load_country_lookup(sources_path: Path) -> dict[str, str | None]:
    try:
        data = json.loads(sources_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    feeds = data.get("feeds", []) if isinstance(data, dict) else []
    return {entry["name"]: entry.get("country") for entry in feeds}


def _build_hydration_urls(
    cluster: dict,
    feeds: list[dict],
    country_by_outlet: dict[str, str | None],
) -> list[dict]:
    urls: list[dict] = []
    for sid in cluster.get("source_ids", []):
        try:
            idx = int(sid.split("finding-")[-1])
        except (ValueError, IndexError):
            continue
        if not 0 <= idx < len(feeds):
            continue
        entry = feeds[idx]
        outlet = entry.get("source_name", "unknown")
        urls.append({
            "url": entry.get("source_url", ""),
            "outlet": outlet,
            "language": entry.get("language", "en"),
            "country": country_by_outlet.get(outlet),
            "title": entry.get("title"),
        })
    return urls


def load_assignments_with_urls(
    date: str,
    max_topics: int,
    log: logging.Logger,
) -> list[TopicAssignment]:
    editor_path = ROOT / "output" / date / "03-editor-assignments.json"
    curator_path = ROOT / "output" / date / "02-curator-topics-unsliced.json"
    feeds_path = ROOT / "raw" / date / "feeds.json"
    sources_path = ROOT / "config" / "sources.json"

    for path in (editor_path, curator_path, feeds_path):
        if not path.exists():
            raise SystemExit(f"Required input missing: {path}")

    editor = json.loads(editor_path.read_text(encoding="utf-8"))
    clusters = json.loads(curator_path.read_text(encoding="utf-8"))
    feeds = json.loads(feeds_path.read_text(encoding="utf-8"))
    country_by_outlet = _load_country_lookup(sources_path)

    produced_assignments = [a for a in editor if int(a.get("priority", 0)) > 0]
    produced_assignments.sort(key=lambda a: -int(a.get("priority", 0)))
    selected = produced_assignments[:max_topics]
    log.info(
        "Editor: loaded %d assignments, selected top %d by priority",
        len(editor), len(selected),
    )

    assignments: list[TopicAssignment] = []
    for raw in selected:
        cluster = _match_cluster(raw.get("title", ""), clusters)
        if cluster is None:
            log.error(
                "Could not match cluster for assignment %r (title=%r) — skipping",
                raw.get("id"), raw.get("title"),
            )
            continue
        hydration_urls = _build_hydration_urls(cluster, feeds, country_by_outlet)
        log.info(
            "%s → cluster %r: %d URLs",
            raw.get("id"), cluster.get("title"), len(hydration_urls),
        )
        raw_data = dict(raw.get("raw_data") or {})
        raw_data["hydration_urls"] = hydration_urls
        raw_data["source_count"] = len(hydration_urls)
        assignments.append(TopicAssignment(
            id=raw.get("id", ""),
            title=raw.get("title", ""),
            priority=int(raw.get("priority", 5)),
            topic_slug=raw.get("topic_slug", ""),
            selection_reason=raw.get("selection_reason", ""),
            raw_data=raw_data,
            follow_up_to=raw.get("follow_up_to"),
            follow_up_reason=raw.get("follow_up_reason"),
        ))
    return assignments


# ---------- agent wiring ----------

def create_hydrated_agents() -> dict[str, Agent]:
    """Agents used by the hydrated pipeline. Mirrors scripts/run.py for the
    downstream agents and adds ``researcher_hydrated_plan`` plus the two
    Hydration Aggregator phase agents."""
    agents_dir = ROOT / "agents"
    return {
        # Hydrated planner (sees the pre-dossier coverage summary).
        "researcher_hydrated_plan": Agent(
            name="researcher_hydrated_plan",
            model="google/gemini-3-flash-preview",
            system_prompt_path=str(agents_dir / "researcher_hydrated" / "PLAN-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher_hydrated" / "PLAN-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        # Researcher Assembler — unchanged from production.
        "researcher_assemble": Agent(
            name="researcher_assemble",
            model="google/gemini-3-flash-preview",
            system_prompt_path=str(agents_dir / "researcher" / "ASSEMBLE-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher" / "ASSEMBLE-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.2,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        # Hydration Aggregator Phase 1 — per-chunk article analysis on
        # Gemini 3 Flash. Pinned per Session-12 eval.
        "hydration_aggregator_phase1": Agent(
            name="hydration_aggregator_phase1",
            model="google/gemini-3-flash-preview",
            system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE1-SYSTEM.md"),
            instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE1-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.3,
            max_tokens=32000,
            provider="openrouter",
            reasoning="none",
        ),
        # Hydration Aggregator Phase 2 — cross-corpus reducer on Opus 4.6
        # @ 0.1 (variant B, 114/120 in Session-12 eval).
        "hydration_aggregator_phase2": Agent(
            name="hydration_aggregator_phase2",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "hydration_aggregator" / "PHASE2-SYSTEM.md"),
            instructions_path=str(agents_dir / "hydration_aggregator" / "PHASE2-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=32000,
            provider="openrouter",
            reasoning="none",
        ),
        # Downstream agents — identical to production configs.
        "perspektiv": Agent(
            name="perspektiv",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "perspektiv" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "perspektiv" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        "writer": Agent(
            name="writer",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "writer" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "writer" / "INSTRUCTIONS.md"),
            tools=[web_search_tool],
            temperature=0.3,
            max_tokens=65536,
            provider="openrouter",
            reasoning="none",
        ),
        "qa_analyze": Agent(
            name="qa_analyze",
            model="anthropic/claude-sonnet-4.6",
            system_prompt_path=str(agents_dir / "qa_analyze" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "qa_analyze" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=32768,
            provider="openrouter",
            reasoning="none",
        ),
        "bias_language": Agent(
            name="bias_language",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "bias_detector" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "bias_detector" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
    }


# ---------- summary helpers ----------

def _read_debug(date: str, filename: str) -> object | None:
    path = ROOT / "output" / date / "test_hydration" / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None


def _topic_sources_summary(date: str, slug: str) -> dict[str, int]:
    """Extract per-topic source counts from the debug artefacts."""
    hydr = _read_debug(date, f"04a-hydration-fetch-{slug}.json") or []
    pre = _read_debug(date, f"04b-hydration-pre-dossier-{slug}.json") or {}
    merged = _read_debug(date, f"04d-hydration-merged-{slug}.json") or {}
    n_succ = sum(
        1 for r in (hydr if isinstance(hydr, list) else [])
        if isinstance(r, dict) and r.get("status") == "success"
    )
    n_pre = len((pre or {}).get("sources", []))
    n_merged = len((merged or {}).get("sources", []))
    return {
        "n_hydration_urls": len(hydr) if isinstance(hydr, list) else 0,
        "n_hydration_success": n_succ,
        "n_pre_dossier_sources": n_pre,
        "n_web_sources_after_blocklist": max(0, n_merged - n_pre),
        "n_merged_sources": n_merged,
    }


def _topic_actor_flags(date: str, slug: str) -> tuple[int, int]:
    """Return (total_actors, actors_with_verbatim) in the merged dossier."""
    merged = _read_debug(date, f"04d-hydration-merged-{slug}.json") or {}
    total = 0
    with_quote = 0
    for source in (merged or {}).get("sources", []):
        for actor in source.get("actors_quoted") or []:
            total += 1
            if actor.get("verbatim_quote"):
                with_quote += 1
    return total, with_quote


# ---------- main ----------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="T3 hydrated pipeline orchestrator")
    p.add_argument(
        "--date", required=True,
        help="Date of the completed production run whose Editor + Curator outputs to reuse (YYYY-MM-DD).",
    )
    p.add_argument(
        "--max-topics", type=int, default=3,
        help="Maximum number of Editor-selected topics to produce hydrated TPs for.",
    )
    return p.parse_args()


async def run_pipeline(
    date: str,
    max_topics: int,
    log: logging.Logger,
) -> None:
    assignments = load_assignments_with_urls(date, max_topics, log)
    if not assignments:
        raise SystemExit(
            f"No assignments with resolvable hydration_urls for {date}; nothing to run."
        )

    agents = create_hydrated_agents()
    pipeline = PipelineHydrated(
        name="hydrated_test",
        agents=agents,
        output_dir=str(ROOT / "output"),
        state_dir=str(ROOT / "state"),
        max_topics=10,
        max_produce=max_topics,
        mode="quick",
    )
    # Minimal state to satisfy downstream helpers that read date / run_id.
    pipeline.state = PipelineState(
        run_id=f"hydrated-{date}-{uuid4().hex[:6]}",
        date=date,
        current_step="produce",
        completed_steps=["collect", "curate", "editorial_conference"],
        assignments=[asdict(a) for a in assignments],
        started_at=datetime.utcnow().isoformat(),
    )

    start = time.monotonic()
    packages = await pipeline.produce(assignments)
    wall = time.monotonic() - start

    # Write the final Topic Packages.
    out_dir = ROOT / "output" / date / "test_hydration"
    out_dir.mkdir(parents=True, exist_ok=True)
    for pkg in packages:
        slug = pkg.metadata.get("topic_slug") or pkg.id
        path = out_dir / f"tp-{slug}.json"
        path.write_text(
            json.dumps(pkg.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info(
            "wrote %s  (status=%s, sources=%d)",
            path.relative_to(ROOT), pkg.status, len(pkg.sources),
        )

    # Summary ------------------------------------------------------------
    log.info("=" * 80)
    log.info(
        "Hydrated pipeline produced %d/%d TPs in %.1fs",
        sum(1 for p in packages if p.status != "failed"),
        len(packages), wall,
    )
    log.info(
        "  %-4s %-48s %6s %6s %6s %6s %6s  tokens  quotes",
        "id", "slug", "urls", "succ", "pre", "web", "merged",
    )
    total_tokens = 0
    any_verbatim = False
    for pkg in packages:
        slug = pkg.metadata.get("topic_slug") or pkg.id
        counts = _topic_sources_summary(date, slug)
        topic_tokens = sum(
            s.get("tokens_used", 0) for s in pipeline._agent_stats
            if s.get("topic") == slug
        )
        total_tokens += topic_tokens
        actors_total, actors_with_quote = _topic_actor_flags(date, slug)
        if actors_with_quote > 0:
            any_verbatim = True
        log.info(
            "  %-4s %-48s %6d %6d %6d %6d %6d  %6d  %3d/%-3d",
            pkg.id.split("-")[-1],
            slug[:48],
            counts["n_hydration_urls"],
            counts["n_hydration_success"],
            counts["n_pre_dossier_sources"],
            counts["n_web_sources_after_blocklist"],
            counts["n_merged_sources"],
            topic_tokens,
            actors_with_quote, actors_total,
        )
    log.info("=" * 80)
    log.info(
        "Tracked tokens (downstream only; aggregator tokens logged by Agent but not in _agent_stats): %d",
        total_tokens,
    )
    log.info("Output dir: %s", out_dir.relative_to(ROOT))

    # Light structural checks — surface problems, don't fail the run.
    problems: list[str] = []
    for pkg in packages:
        slug = pkg.metadata.get("topic_slug") or pkg.id
        counts = _topic_sources_summary(date, slug)
        if counts["n_merged_sources"] != (
            counts["n_pre_dossier_sources"]
            + counts["n_web_sources_after_blocklist"]
        ):
            problems.append(
                f"{pkg.id}: merged ({counts['n_merged_sources']}) != "
                f"pre ({counts['n_pre_dossier_sources']}) + "
                f"web ({counts['n_web_sources_after_blocklist']})"
            )
    if not any_verbatim:
        problems.append(
            "no merged dossier contains a non-null verbatim_quote — expected "
            "at least one across 3 topics"
        )
    if problems:
        log.warning("Validation flags:")
        for prob in problems:
            log.warning("  - %s", prob)
    else:
        log.info("Validation: OK (merged counts add up; verbatim quotes present)")


def main() -> int:
    args = _parse_args()
    log = setup_logging()
    asyncio.run(run_pipeline(args.date, args.max_topics, log))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
