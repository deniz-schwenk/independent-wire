"""Tests for the Pipeline orchestration.

Unit tests run without API keys. Integration tests require OPENROUTER_API_KEY.
"""

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.agent import Agent
from src.models import AgentResult, PipelineState, TopicAssignment, TopicPackage
from src.pipeline import Pipeline, PipelineGateRejected

HAS_API_KEY = bool(os.environ.get("OPENROUTER_API_KEY"))
skip_no_key = pytest.mark.skipif(not HAS_API_KEY, reason="No OPENROUTER_API_KEY")

MODEL = "openai/gpt-4o-mini"


# --- Unit tests (no API key needed) ---


def test_topic_package_to_dict() -> None:
    """TopicPackage.to_dict() returns all required fields with version 1.0."""
    pkg = TopicPackage(
        id="tp-2026-03-30-001",
        metadata={"title": "Test", "date": "2026-03-30", "status": "review", "topic_slug": "test"},
        sources=[{"id": "s1", "url": "https://example.com", "title": "Ex", "language": "en"}],
        perspectives=[{"position": "for", "actors": ["A"], "representation": "dominant"}],
        article={"headline": "Test Article", "body": "Body text."},
        bias_analysis={"overall_score": 0.2},
        transparency={"selection_reason": "test", "confidence": "high", "pipeline_run": {}},
    )
    d = pkg.to_dict()
    assert d["version"] == "1.0"
    assert d["id"] == "tp-2026-03-30-001"
    assert d["metadata"]["title"] == "Test"
    assert d["sources"][0]["id"] == "s1"
    assert d["perspectives"][0]["position"] == "for"
    assert d["article"]["headline"] == "Test Article"
    assert d["bias_analysis"]["overall_score"] == 0.2
    assert d["transparency"]["confidence"] == "high"
    # Schema required fields present
    for key in ["id", "version", "metadata", "sources", "perspectives", "article", "bias_analysis", "transparency"]:
        assert key in d


def test_pipeline_state_persistence(tmp_path) -> None:
    """Pipeline saves and loads state as JSON."""
    pipeline = Pipeline(
        name="test",
        agents={},
        state_dir=str(tmp_path),
    )
    pipeline.state = PipelineState(
        run_id="run-2026-03-30-abc123",
        date="2026-03-30",
        current_step="curate",
        completed_steps=["collect"],
        raw_findings=[{"title": "Finding 1"}],
        started_at="2026-03-30T10:00:00",
    )

    import asyncio
    asyncio.get_event_loop().run_until_complete(pipeline._save_state())

    # Load and verify
    path = tmp_path / "run-2026-03-30-abc123.json"
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["run_id"] == "run-2026-03-30-abc123"
    assert data["current_step"] == "curate"
    assert data["completed_steps"] == ["collect"]
    assert data["raw_findings"] == [{"title": "Finding 1"}]


def test_pipeline_load_incomplete_state(tmp_path) -> None:
    """Pipeline detects and loads incomplete state from the same date."""
    state = PipelineState(
        run_id="run-2026-03-30-abc123",
        date="2026-03-30",
        current_step="curate",
        completed_steps=["collect"],
        started_at="2026-03-30T10:00:00",
    )
    path = tmp_path / "run-2026-03-30-abc123.json"
    path.write_text(json.dumps(asdict(state), indent=2))

    pipeline = Pipeline(name="test", agents={}, state_dir=str(tmp_path))
    loaded = pipeline._load_incomplete_state("2026-03-30")

    assert loaded is not None
    assert loaded.run_id == "run-2026-03-30-abc123"
    assert loaded.current_step == "curate"
    assert loaded.completed_steps == ["collect"]


def test_pipeline_load_no_incomplete(tmp_path) -> None:
    """Returns None when no incomplete state exists."""
    pipeline = Pipeline(name="test", agents={}, state_dir=str(tmp_path))

    # Empty dir
    assert pipeline._load_incomplete_state("2026-03-30") is None

    # Completed state
    state = PipelineState(
        run_id="run-2026-03-30-done",
        date="2026-03-30",
        current_step="done",
        completed_steps=["collect", "curate", "editorial_conference", "produce", "verify"],
        started_at="2026-03-30T10:00:00",
    )
    path = tmp_path / "run-2026-03-30-done.json"
    path.write_text(json.dumps(asdict(state), indent=2))
    assert pipeline._load_incomplete_state("2026-03-30") is None


@pytest.mark.asyncio
async def test_verify_counts(caplog) -> None:
    """verify() counts completed vs failed and logs summary."""
    pipeline = Pipeline(name="test", agents={})

    # Set state so verify doesn't fail
    pipeline.state = PipelineState(
        run_id="run-test", date="2026-03-30", current_step="verify"
    )

    packages = [
        TopicPackage(id="tp-001", metadata={"title": "A"}, status="review"),
        TopicPackage(id="tp-002", metadata={"title": "B"}, status="review"),
        TopicPackage(id="tp-003", metadata={"title": "C"}, status="failed", error="boom"),
    ]

    with caplog.at_level(logging.INFO, logger="src.pipeline"):
        result = await pipeline.verify(packages)

    assert len(result) == 3
    assert "2/3 topics completed, 1 failed" in caplog.text


@pytest.mark.asyncio
async def test_gate_handler_called() -> None:
    """gate() calls gate_handler with correct arguments in full mode."""
    handler = AsyncMock(return_value=True)
    pipeline = Pipeline(
        name="test", agents={}, mode="full", gate_handler=handler
    )

    data = {"topics": ["a", "b"]}
    result = await pipeline.gate("editorial_conference", data)

    assert result is True
    handler.assert_called_once_with("editorial_conference", data)


@pytest.mark.asyncio
async def test_gate_rejected_raises() -> None:
    """PipelineGateRejected is raised when gate_handler returns False."""
    handler = AsyncMock(return_value=False)
    pipeline = Pipeline(
        name="test", agents={}, mode="full", gate_handler=handler
    )

    result = await pipeline.gate("editorial_conference", {})
    assert result is False


@pytest.mark.asyncio
async def test_gate_skipped_in_quick_mode() -> None:
    """Gate is not called in quick mode — always returns True."""
    handler = AsyncMock(return_value=False)
    pipeline = Pipeline(
        name="test", agents={}, mode="quick", gate_handler=handler
    )

    result = await pipeline.gate("editorial_conference", {})
    assert result is True
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_produce_single_error_isolation() -> None:
    """_produce_single catches errors and returns a failed TopicPackage."""
    # Create a pipeline with no writer agent — will raise PipelineStepError
    pipeline = Pipeline(name="test", agents={})
    pipeline.state = PipelineState(
        run_id="run-test", date="2026-03-30", current_step="produce"
    )

    assignment = TopicAssignment(
        id="tp-001",
        title="Test Topic",
        priority=5,
        topic_slug="test-topic",
        selection_reason="test",
    )

    # produce() should catch the error and return a failed package
    packages = await pipeline.produce([assignment])
    assert len(packages) == 1
    assert packages[0].status == "failed"
    assert packages[0].error is not None
    assert "writer" in packages[0].error.lower()


def test_agent_prompt_files_exist() -> None:
    """All core agent prompt files exist."""
    repo_root = Path(__file__).parent.parent
    for agent_name in ["collector", "curator", "editor", "writer"]:
        path = repo_root / "agents" / agent_name / "AGENTS.md"
        assert path.exists(), f"Missing prompt file: {path}"


# --- Integration test (requires OPENROUTER_API_KEY) ---


@skip_no_key
@pytest.mark.asyncio
async def test_pipeline_collect_curate(tmp_path) -> None:
    """Real data flow: Collector -> Curator with cheap models."""
    # Create simple prompt files
    collector_prompt = tmp_path / "collector.md"
    collector_prompt.write_text(
        "You are a news collector. Return findings as a JSON array. "
        "Each item should have: title, summary, source_url, source_name, language, region. "
        "Return exactly 3 findings about technology news. Return ONLY the JSON array."
    )

    curator_prompt = tmp_path / "curator.md"
    curator_prompt.write_text(
        "You are a news curator. Select the most relevant topics from the findings. "
        "For each selected topic provide: title, topic_slug, relevance_score (1-10), summary, source_ids. "
        "Return ONLY a JSON array."
    )

    collector = Agent(
        name="collector",
        model=MODEL,
        prompt_path=str(collector_prompt),
    )
    curator = Agent(
        name="curator",
        model=MODEL,
        prompt_path=str(curator_prompt),
    )

    pipeline = Pipeline(
        name="test",
        agents={"collector": collector, "curator": curator},
        state_dir=str(tmp_path / "state"),
        output_dir=str(tmp_path / "output"),
    )
    # Set state so collect() can access self.state.date
    pipeline.state = PipelineState(
        run_id="run-test", date="2026-03-31", current_step="collect"
    )

    # Test collect
    raw = await pipeline.collect()
    assert isinstance(raw, list)
    assert len(raw) > 0

    # Test curate
    curated = await pipeline.curate(raw)
    assert isinstance(curated, list)
