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
from src.pipeline import Pipeline
from src.tools import web_search_tool


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_agents() -> dict[str, Agent]:
    """Create all pipeline agents with their configurations.

    Models via OpenRouter (eval-validated, April 2026):
    - google/gemini-3-flash-preview: Curator, Researcher Plan, Researcher Assemble (reasoning=none)
    - anthropic/claude-opus-4.6: Editor, Perspektiv, Writer, Bias Language (reasoning=none)
    - anthropic/claude-sonnet-4.6: QA-Analyze (reasoning=none, NEVER use r-medium)
    """
    agents_dir = ROOT / "agents"

    return {
        # DISABLED: Collector deactivated — RSS feeds provide sufficient coverage.
        # Reactivate when scaling to 200+ feeds as pre-filter for the Curator.
        # "collector_plan": Agent(
        #     name="collector_plan",
        #     model="z-ai/glm-5",
        #     prompt_path=str(agents_dir / "collector" / "PLAN.md"),
        #     tools=[],
        #     temperature=0.5,
        #     provider="openrouter",
        # ),
        # "collector_assemble": Agent(
        #     name="collector_assemble",
        #     model="minimax/minimax-m2.7",
        #     prompt_path=str(agents_dir / "collector" / "ASSEMBLE.md"),
        #     tools=[],
        #     temperature=0.2,
        #     provider="openrouter",
        # ),
        "curator": Agent(
            name="curator",
            model="google/gemini-3-flash-preview",
            prompt_path=str(agents_dir / "curator" / "AGENTS.md"),
            tools=[],
            temperature=0.2,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        "editor": Agent(
            name="editor",
            model="anthropic/claude-opus-4.6",
            prompt_path=str(agents_dir / "editor" / "AGENTS.md"),
            tools=[],
            temperature=0.3,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        "researcher_plan": Agent(
            name="researcher_plan",
            model="google/gemini-3-flash-preview",
            prompt_path=str(agents_dir / "researcher" / "PLAN.md"),
            tools=[],
            temperature=0.5,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        "researcher_assemble": Agent(
            name="researcher_assemble",
            model="google/gemini-3-flash-preview",
            prompt_path=str(agents_dir / "researcher" / "ASSEMBLE.md"),
            tools=[],
            temperature=0.2,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        "perspektiv": Agent(
            name="perspektiv",
            model="anthropic/claude-opus-4.6",
            prompt_path=str(agents_dir / "perspektiv" / "AGENTS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
        "writer": Agent(
            name="writer",
            model="anthropic/claude-opus-4.6",
            prompt_path=str(agents_dir / "writer" / "AGENTS.md"),
            tools=[web_search_tool],
            temperature=0.3,
            max_tokens=65536,
            provider="openrouter",
            reasoning="none",
        ),
        "qa_analyze": Agent(
            name="qa_analyze",
            model="anthropic/claude-sonnet-4.6",
            prompt_path=str(agents_dir / "qa_analyze" / "AGENTS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=32768,
            provider="openrouter",
            reasoning="none",
        ),
        "bias_language": Agent(
            name="bias_language",
            model="anthropic/claude-opus-4.6",
            prompt_path=str(agents_dir / "bias_detector" / "AGENTS.md"),
            tools=[],
            temperature=0.1,
            max_tokens=16384,
            provider="openrouter",
            reasoning="none",
        ),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Independent Wire pipeline")
    parser.add_argument(
        "--from", dest="from_step", default=None,
        choices=["collector", "curator", "editor", "researcher", "perspektiv", "writer", "qa_analyze", "bias_detector"],
        help="Start from this step, loading earlier steps from debug output",
    )
    parser.add_argument(
        "--to", dest="to_step", default=None,
        choices=["collector", "curator", "editor", "researcher", "perspektiv", "writer", "qa_analyze", "bias_detector"],
        help="Stop after this step (inclusive). Default: run to the end.",
    )
    parser.add_argument(
        "--topic", type=int, default=None,
        help="Only process this topic number (1-based index)",
    )
    parser.add_argument(
        "--reuse", type=str, default=None,
        help="Date to load debug output from (YYYY-MM-DD). Default: latest available",
    )
    parser.add_argument(
        "--fetch", action="store_true",
        help="Run fetch_feeds.py before the pipeline",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Run publish.py after the pipeline (if at least 1 topic succeeded)",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    setup_logging()
    logger = logging.getLogger("independent_wire")

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

    agents = create_agents()
    pipeline = Pipeline(
        name="daily_report",
        agents=agents,
        output_dir=str(ROOT / "output"),
        state_dir=str(ROOT / "state"),
        max_topics=10,
        max_produce=3,
        mode="quick",
    )

    # Validate --from / --to ordering
    step_order = ["collector", "curator", "editor", "researcher", "perspektiv", "writer", "qa_analyze", "bias_detector"]
    if args.from_step and args.to_step:
        if step_order.index(args.to_step) < step_order.index(args.from_step):
            logger.error(
                "--to '%s' is before --from '%s' in the pipeline order. "
                "Order: %s", args.to_step, args.from_step, " → ".join(step_order),
            )
            sys.exit(1)

    try:
        if args.from_step:
            logger.info(
                "Partial run: --from %s%s%s%s",
                args.from_step,
                f" --to {args.to_step}" if args.to_step else "",
                f" --topic {args.topic}" if args.topic else "",
                f" --reuse {args.reuse}" if args.reuse else "",
            )
            packages = await pipeline.run_partial(
                from_step=args.from_step,
                topic_filter=args.topic,
                reuse_date=args.reuse,
                to_step=args.to_step,
            )
        else:
            packages = await pipeline.run(to_step=args.to_step)
        elapsed = time.time() - start

        completed = [p for p in packages if p.status != "failed"]
        failed = [p for p in packages if p.status == "failed"]
        logger.info("Pipeline finished in %.1f seconds", elapsed)
        logger.info("  Topics: %d completed, %d failed", len(completed), len(failed))
        for p in completed:
            logger.info("  completed %s: %s", p.id, p.metadata.get("title", ""))
        for p in failed:
            logger.info("  failed %s: %s", p.id, p.error or "unknown error")

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
                date_str = packages[0].metadata.get("date", "unknown")
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
