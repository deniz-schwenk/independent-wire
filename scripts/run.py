#!/usr/bin/env python3
"""Independent Wire — Run the daily pipeline."""

import argparse
import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path

# Repo root for resolving paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.runner.runner import PipelineRunner
from src.runner.stage_lists import (
    build_hydrated_stages,
    build_production_stages,
    hydrated_stage_names,
    production_stage_names,
)
from src.schemas import (
    BIAS_DETECTOR_SCHEMA,
    CURATOR_SCHEMA,
    EDITOR_SCHEMA,
    HYDRATION_PHASE1_SCHEMA,
    HYDRATION_PHASE2_SCHEMA,
    PERSPECTIVE_SCHEMA,
    PERSPECTIVE_SYNC_SCHEMA,
    QA_ANALYZE_SCHEMA,
    RESEARCHER_ASSEMBLE_SCHEMA,
    RESEARCHER_PLAN_SCHEMA,
    WRITER_SCHEMA,
)
from src.tools import web_search_tool


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_agents() -> dict[str, Agent]:
    """Create all pipeline agents with their configurations.

    Models via OpenRouter (eval-validated, April 2026; Researcher Plan promoted
    to Opus 4.6 in Researcher-Polish iter 1, May 2026):
    - google/gemini-3-flash-preview: Curator, Researcher Assemble (reasoning=none)
    - anthropic/claude-opus-4.6: Editor, Researcher Plan, Perspective, Writer, Bias Language (reasoning=none)
    - anthropic/claude-sonnet-4.6: QA-Analyze (reasoning=none, NEVER use r-medium)
    """
    agents_dir = ROOT / "agents"

    return {
        # DISABLED: Collector deactivated — RSS feeds provide sufficient coverage.
        # Reactivate when scaling to 200+ feeds as pre-filter for the Curator.
        # "collector_plan": Agent(
        #     name="collector_plan",
        #     model="z-ai/glm-5",
        #     system_prompt_path=str(agents_dir / "collector" / "PLAN-SYSTEM.md"),
        #     instructions_path=str(agents_dir / "collector" / "PLAN-INSTRUCTIONS.md"),
        #     tools=[],
        #     temperature=0.5,
        #     provider="openrouter",
        # ),
        # "collector_assemble": Agent(
        #     name="collector_assemble",
        #     model="minimax/minimax-m2.7",
        #     system_prompt_path=str(agents_dir / "collector" / "ASSEMBLE-SYSTEM.md"),
        #     instructions_path=str(agents_dir / "collector" / "ASSEMBLE-INSTRUCTIONS.md"),
        #     tools=[],
        #     temperature=0.2,
        #     provider="openrouter",
        # ),
        "curator": Agent(
            name="curator",
            model="google/gemini-3-flash-preview",
            system_prompt_path=str(agents_dir / "curator" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "curator" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.2,
            provider="openrouter",
            reasoning="none",
            # The S13 envelope {topics, cluster_assignments} pushes the array to
            # the end of the JSON. With ~1400 findings, the flat cluster_assignments
            # alone needs ~5–10k tokens; topics + envelope add another ~5k. The
            # 32k default truncates mid-array, and _extract_dict's prose-extraction
            # discards everything after the last `}`, dropping cluster_assignments
            # entirely. 64k gives steady-state headroom.
            max_tokens=64000,
            output_schema=CURATOR_SCHEMA,
        ),
        "editor": Agent(
            name="editor",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "editor" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "editor" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.3,
            provider="openrouter",
            reasoning="none",
            output_schema=EDITOR_SCHEMA,
        ),
        "researcher_plan": Agent(
            name="researcher_plan",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "researcher" / "PLAN-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher" / "PLAN-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            provider="openrouter",
            reasoning="none",
            output_schema=RESEARCHER_PLAN_SCHEMA,
        ),
        "researcher_assemble": Agent(
            name="researcher_assemble",
            model="google/gemini-3-flash-preview",
            system_prompt_path=str(agents_dir / "researcher" / "ASSEMBLE-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher" / "ASSEMBLE-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.2,
            provider="openrouter",
            reasoning="none",
            output_schema=RESEARCHER_ASSEMBLE_SCHEMA,
        ),
        "perspective": Agent(
            name="perspective",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "perspective" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "perspective" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            provider="openrouter",
            reasoning="none",
            output_schema=PERSPECTIVE_SCHEMA,
        ),
        "writer": Agent(
            name="writer",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "writer" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "writer" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.3,
            provider="openrouter",
            reasoning="none",
            output_schema=WRITER_SCHEMA,
        ),
        "qa_analyze": Agent(
            name="qa_analyze",
            model="anthropic/claude-sonnet-4.6",
            system_prompt_path=str(agents_dir / "qa_analyze" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "qa_analyze" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=64000,
            provider="openrouter",
            reasoning="none",
            output_schema=QA_ANALYZE_SCHEMA,
        ),
        "bias_language": Agent(
            name="bias_language",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "bias_detector" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "bias_detector" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            provider="openrouter",
            reasoning="none",
            output_schema=BIAS_DETECTOR_SCHEMA,
        ),
    }


def create_agents_hydrated() -> dict[str, Agent]:
    """Agents for the hydrated pipeline.

    Mirrors :func:`create_agents` for the agents shared with production,
    and adds the three hydrated-only agents (``researcher_hydrated_plan``,
    ``hydration_aggregator_phase1``, ``hydration_aggregator_phase2``,
    ``perspective_sync``). All eleven agents carry their ``output_schema``
    so strict-mode JSON enforcement applies on every LLM call.
    """
    agents_dir = ROOT / "agents"
    base = create_agents()
    base.update({
        "researcher_hydrated_plan": Agent(
            name="researcher_hydrated_plan",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "researcher_hydrated" / "PLAN-SYSTEM.md"),
            instructions_path=str(agents_dir / "researcher_hydrated" / "PLAN-INSTRUCTIONS.md"),
            tools=[],
            temperature=0.5,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
            output_schema=RESEARCHER_PLAN_SCHEMA,
        ),
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
            output_schema=HYDRATION_PHASE1_SCHEMA,
        ),
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
            output_schema=HYDRATION_PHASE2_SCHEMA,
        ),
        "perspective_sync": Agent(
            name="perspective_sync",
            model="anthropic/claude-opus-4.6",
            system_prompt_path=str(agents_dir / "perspective_sync" / "SYSTEM.md"),
            instructions_path=str(agents_dir / "perspective_sync" / "INSTRUCTIONS.md"),
            tools=[],
            temperature=0.1,
            provider="openrouter",
            reasoning="none",
            output_schema=PERSPECTIVE_SYNC_SCHEMA,
        ),
    })
    return base


def parse_args():
    parser = argparse.ArgumentParser(description="Independent Wire pipeline")
    parser.add_argument(
        "--from", dest="from_step", default=None,
        help=(
            "Start from this V2 stage (resume from on-disk snapshot). Stage "
            "names match the V2 stage list — see --help-stages for the full "
            "set per variant. Requires --reuse."
        ),
    )
    parser.add_argument(
        "--to", dest="to_step", default=None,
        help="Stop after this V2 stage (inclusive). Default: run to the end.",
    )
    parser.add_argument(
        "--topic", type=int, default=None,
        help=(
            "Only process the Nth selected topic (1-based index). "
            "Other topics are marked 'skipped' and excluded from render."
        ),
    )
    parser.add_argument(
        "--reuse", type=str, default=None,
        help=(
            "Reuse a prior run's snapshots. Accepts 'YYYY-MM-DD' (auto-resolves "
            "to the latest run_id under output/{date}/_state/) or "
            "'YYYY-MM-DD/run-YYYY-MM-DD-xxxxxxxx' for an exact run_id."
        ),
    )
    parser.add_argument(
        "--max-produce", dest="max_produce", type=int, default=3,
        help="Maximum number of topics to produce per run (default: 3).",
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="Run fetch_feeds.py before the pipeline",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Run publish.py after the pipeline (if at least 1 topic succeeded)",
    )
    parser.add_argument(
        "--hydrated", action="store_true",
        help=(
            "Run the hydrated pipeline (T1 fetch + Phase 1/2 aggregator + "
            "Perspective-Sync) instead of production. From-scratch hydrated "
            "runs are supported (V2 stage list is complete)."
        ),
    )
    parser.add_argument(
        "--help-stages", action="store_true",
        help="Print the production and hydrated stage names, then exit.",
    )
    return parser.parse_args()


def _resolve_reuse(reuse_arg: str, output_dir: Path) -> tuple[str, str]:
    """Resolve --reuse argument to (run_date, run_id).

    Accepts:
    - "2026-04-30" → latest run_id under output_dir/{date}/_state/
    - "2026-04-30/run-2026-04-30-abc12345" → exact run_id
    """
    parts = reuse_arg.strip("/").split("/")
    run_date = parts[0]
    state_dir = output_dir / run_date / "_state"

    if len(parts) == 2:
        run_id = parts[1]
        if not (state_dir / run_id).is_dir():
            raise RuntimeError(
                f"--reuse: run_id {run_id!r} not found under {state_dir}"
            )
        return run_date, run_id

    if not state_dir.is_dir():
        raise RuntimeError(
            f"--reuse: no state directory at {state_dir}. Was a prior run "
            f"completed for this date?"
        )

    candidates = sorted(
        [d for d in state_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(f"--reuse: no runs found under {state_dir}")
    return run_date, candidates[0].name


def _print_stage_help() -> None:
    print("V2 stage names (--from / --to choices)\n")
    print("  Production variant:")
    for n in production_stage_names():
        print(f"    {n}")
    print("\n  Hydrated variant:")
    for n in hydrated_stage_names():
        print(f"    {n}")


async def main():
    args = parse_args()
    setup_logging()
    logger = logging.getLogger("independent_wire")

    if args.help_stages:
        _print_stage_help()
        return

    # Pre-pipeline: fetch feeds if requested
    if args.fetch:
        logger.info("Fetching feeds...")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "fetch_feeds.py")],
        )
        if result.returncode != 0:
            logger.error("fetch_feeds.py failed (exit %d)", result.returncode)
            sys.exit(1)

    logger.info("Starting Independent Wire pipeline...")
    start = time.time()

    output_dir = ROOT / "output"
    if args.hydrated:
        agents = create_agents_hydrated()
        run_stages, topic_stages, post_run_stages = build_hydrated_stages(
            agents,
            web_search_tool=web_search_tool,
            max_produce=args.max_produce,
            output_dir=output_dir,
        )
        valid_names = hydrated_stage_names()
    else:
        agents = create_agents()
        run_stages, topic_stages, post_run_stages = build_production_stages(
            agents,
            web_search_tool=web_search_tool,
            max_produce=args.max_produce,
            output_dir=output_dir,
        )
        valid_names = production_stage_names()

    # Validate --from / --to against the active variant's stage names
    if args.from_step and args.from_step not in valid_names:
        logger.error(
            "--from %r is not a valid stage. Run with --help-stages for the "
            "%s stage list.",
            args.from_step,
            "hydrated" if args.hydrated else "production",
        )
        sys.exit(1)
    if args.to_step and args.to_step not in valid_names:
        logger.error(
            "--to %r is not a valid stage. Run with --help-stages for the "
            "%s stage list.",
            args.to_step,
            "hydrated" if args.hydrated else "production",
        )
        sys.exit(1)
    if args.from_step and args.to_step:
        if valid_names.index(args.to_step) < valid_names.index(args.from_step):
            logger.error(
                "--to %r is before --from %r in the stage order.",
                args.to_step, args.from_step,
            )
            sys.exit(1)

    # Resolve --reuse
    reuse_run_id = None
    reuse_run_date = None
    if args.reuse:
        try:
            reuse_run_date, reuse_run_id = _resolve_reuse(args.reuse, output_dir)
        except RuntimeError as e:
            logger.error("%s", e)
            sys.exit(1)

    if args.from_step and not reuse_run_id:
        logger.error("--from requires --reuse so prior snapshots can be loaded.")
        sys.exit(1)

    runner = PipelineRunner(
        run_stages=run_stages,
        topic_stages=topic_stages,
        post_run_stages=post_run_stages,
        output_dir=output_dir,
        from_stage=args.from_step,
        to_stage=args.to_step,
        reuse_run_id=reuse_run_id,
        reuse_run_date=reuse_run_date,
        topic_filter=args.topic,
    )

    if args.from_step or args.to_step or args.topic or args.reuse:
        logger.info(
            "Partial run:%s%s%s%s",
            f" --from {args.from_step}" if args.from_step else "",
            f" --to {args.to_step}" if args.to_step else "",
            f" --topic {args.topic}" if args.topic else "",
            f" --reuse {args.reuse}" if args.reuse else "",
        )

    try:
        run_bus = await runner.run()
        elapsed = time.time() - start

        manifest = run_bus.run_topic_manifest or []
        completed = [m for m in manifest if m["status"] == "success"]
        skipped = [m for m in manifest if m["status"] == "skipped"]
        failed = [m for m in manifest if m["status"] == "failed"]
        logger.info("Pipeline finished in %.1f seconds", elapsed)
        logger.info(
            "  Topics: %d completed, %d skipped, %d failed",
            len(completed), len(skipped), len(failed),
        )
        for m in completed:
            logger.info("  completed %s: %s", m["topic_id"], m.get("topic_slug", ""))
        for m in skipped:
            logger.info("  skipped %s: %s", m["topic_id"], m.get("topic_slug", ""))
        for m in failed:
            logger.info("  failed %s: %s", m["topic_id"], m.get("topic_slug", ""))

        # Post-pipeline: publish if requested and at least 1 topic succeeded
        if args.publish and completed:
            logger.info("Publishing site...")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "publish.py")],
            )
            if result.returncode == 0:
                logger.info("Deploying to GitHub Pages...")
                subprocess.run(
                    ["git", "add", "site/"],
                    cwd=str(ROOT),
                )
                date_str = run_bus.run_date or "unknown"
                commit_msg = f"Publish {date_str}: {len(completed)} dossier{'s' if len(completed) != 1 else ''}"
                commit_result = subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    cwd=str(ROOT),
                    capture_output=True,
                    text=True,
                )
                if commit_result.returncode == 0:
                    push_result = subprocess.run(
                        ["git", "push"],
                        cwd=str(ROOT),
                        capture_output=True,
                        text=True,
                    )
                    if push_result.returncode == 0:
                        logger.info("Deployed: %s", commit_msg)
                    else:
                        logger.error("Git push failed: %s", push_result.stderr)
                elif "nothing to commit" in commit_result.stdout:
                    logger.info("No site changes to deploy")
                else:
                    logger.error("Git commit failed: %s", commit_result.stderr)

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
