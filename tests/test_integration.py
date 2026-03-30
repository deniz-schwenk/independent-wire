"""Smoke test for the full integration — requires API keys."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HAS_API_KEY = bool(os.environ.get("OPENROUTER_API_KEY"))


@pytest.mark.skipif(not HAS_API_KEY, reason="OPENROUTER_API_KEY not set")
@pytest.mark.asyncio
async def test_pipeline_smoke(tmp_path) -> None:
    """Run the pipeline with max_topics=1 and verify output."""
    from scripts.run import create_agents
    from src.pipeline import Pipeline

    agents = create_agents()
    pipeline = Pipeline(
        name="test_run",
        agents=agents,
        output_dir=str(tmp_path / "output"),
        state_dir=str(tmp_path / "state"),
        max_topics=1,
        mode="quick",
    )
    packages = await pipeline.run()
    assert len(packages) >= 1
    # At least one should not be failed
    assert any(p.status != "failed" for p in packages)
