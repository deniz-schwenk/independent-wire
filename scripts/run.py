#!/usr/bin/env python3
"""Independent Wire — Run the daily pipeline."""

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
    """Create all pipeline agents with their configurations."""
    agents_dir = ROOT / "agents"

    return {
        "collector": Agent(
            name="collector",
            model="openai/gpt-4o-mini",
            prompt_path=str(agents_dir / "collector" / "AGENTS.md"),
            tools=[web_search_tool],
            temperature=0.2,
            provider="openrouter",
        ),
        "curator": Agent(
            name="curator",
            model="openai/gpt-4o-mini",
            prompt_path=str(agents_dir / "curator" / "AGENTS.md"),
            tools=[],
            temperature=0.2,
            provider="openrouter",
        ),
        "editor": Agent(
            name="editor",
            model="openai/gpt-4o-mini",
            prompt_path=str(agents_dir / "editor" / "AGENTS.md"),
            tools=[],
            temperature=0.3,
            provider="openrouter",
        ),
        "writer": Agent(
            name="writer",
            model="openai/gpt-4o-mini",
            prompt_path=str(agents_dir / "writer" / "AGENTS.md"),
            tools=[web_search_tool],
            temperature=0.3,
            provider="openrouter",
        ),
    }


async def main():
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
