#!/usr/bin/env python3
"""Independent Wire — Run the daily pipeline."""

import argparse
import asyncio
import logging
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

    Models via OpenRouter (reliable, large context windows):
    - minimax/minimax-m2.7: 204k context, good for collection/curation
    - z-ai/glm-5: 202k context, strong reasoning for editorial/writing

    Ollama Cloud (ollama_cloud provider) is also supported but currently
    has reliability issues (timeouts, ~30% failure rate on some models).
    To use Ollama Cloud instead, change provider to "ollama_cloud" and
    models to "minimax-m2.7:cloud" / "glm-5:cloud".
    """
    agents_dir = ROOT / "agents"

    return {
        "collector": Agent(
            name="collector",
            model="minimax/minimax-m2.7",
            prompt_path=str(agents_dir / "collector" / "AGENTS.md"),
            tools=[web_search_tool],
            temperature=0.2,
            provider="openrouter",
        ),
        "curator": Agent(
            name="curator",
            model="minimax/minimax-m2.7",
            prompt_path=str(agents_dir / "curator" / "AGENTS.md"),
            tools=[],
            temperature=0.2,
            provider="openrouter",
        ),
        "editor": Agent(
            name="editor",
            model="z-ai/glm-5",
            prompt_path=str(agents_dir / "editor" / "AGENTS.md"),
            tools=[],
            temperature=0.3,
            provider="openrouter",
        ),
        "researcher": Agent(
            name="researcher",
            model="z-ai/glm-5",
            prompt_path=str(agents_dir / "researcher" / "AGENTS.md"),
            tools=[web_search_tool],
            temperature=0.2,
            provider="openrouter",
        ),
        "writer": Agent(
            name="writer",
            model="z-ai/glm-5",
            prompt_path=str(agents_dir / "writer" / "AGENTS.md"),
            tools=[web_search_tool],
            temperature=0.3,
            provider="openrouter",
        ),
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Independent Wire pipeline")
    parser.add_argument(
        "--from", dest="from_step", default=None,
        choices=["collector", "curator", "editor", "researcher", "writer"],
        help="Start from this step, loading earlier steps from debug output",
    )
    parser.add_argument(
        "--topic", type=int, default=None,
        help="Only process this topic number (1-based index)",
    )
    parser.add_argument(
        "--reuse", type=str, default=None,
        help="Date to load debug output from (YYYY-MM-DD). Default: latest available",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    setup_logging()
    logger = logging.getLogger("independent_wire")

    logger.info("Starting Independent Wire pipeline...")
    start = time.time()

    agents = create_agents()
    pipeline = Pipeline(
        name="daily_report",
        agents=agents,
        output_dir=str(ROOT / "output"),
        state_dir=str(ROOT / "state"),
        max_topics=3,
        mode="quick",
    )

    try:
        if args.from_step:
            logger.info(
                "Partial run: --from %s%s%s",
                args.from_step,
                f" --topic {args.topic}" if args.topic else "",
                f" --reuse {args.reuse}" if args.reuse else "",
            )
            packages = await pipeline.run_partial(
                from_step=args.from_step,
                topic_filter=args.topic,
                reuse_date=args.reuse,
            )
        else:
            packages = await pipeline.run()
        elapsed = time.time() - start

        completed = [p for p in packages if p.status != "failed"]
        failed = [p for p in packages if p.status == "failed"]
        logger.info("Pipeline finished in %.1f seconds", elapsed)
        logger.info("  Topics: %d completed, %d failed", len(completed), len(failed))
        for p in completed:
            logger.info("  completed %s: %s", p.id, p.metadata.get("title", ""))
        for p in failed:
            logger.info("  failed %s: %s", p.id, p.error or "unknown error")

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error("Pipeline failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
