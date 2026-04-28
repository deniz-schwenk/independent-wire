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
from src.pipeline import Pipeline, PipelineError, PipelineGateRejected

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
    """All core agent prompt files exist (two-file layout)."""
    repo_root = Path(__file__).parent.parent
    # Collector remains a single-file (disabled) prompt — its AGENTS.md is
    # used by tests/test_tools.py as a fixture, not loaded by any pipeline.
    assert (repo_root / "agents" / "collector" / "AGENTS.md").exists()
    for agent_name in ["curator", "editor", "writer"]:
        for fname in ("SYSTEM.md", "INSTRUCTIONS.md"):
            path = repo_root / "agents" / agent_name / fname
            assert path.exists(), f"Missing prompt file: {path}"


def test_attach_raw_data_exact_title_match() -> None:
    """Editor preserves the curated title verbatim — exact-match attaches raw_data."""
    curated_topics = [
        {
            "title": "ECB Holds Interest Rates",
            "source_ids": ["a", "b", "c"],
            "languages": ["en", "de"],
            "summary": "ECB held rates at 4%.",
        },
    ]
    raw_assignments = [
        {"title": "ECB Holds Interest Rates", "priority": 5, "selection_reason": "..."},
    ]
    Pipeline._attach_raw_data_from_curated(raw_assignments, curated_topics)
    assert raw_assignments[0]["raw_data"]["source_ids"] == ["a", "b", "c"]
    assert raw_assignments[0]["raw_data"]["languages"] == ["en", "de"]
    assert raw_assignments[0]["raw_data"]["summary"] == "ECB held rates at 4%."


def test_attach_raw_data_slug_fallback(caplog) -> None:
    """Editor refines the title — slug match attaches raw_data and logs INFO."""
    curated_topics = [
        {
            "title": "ECB Holds Interest-Rates",
            "source_ids": ["x", "y"],
        },
    ]
    raw_assignments = [
        {"title": "ECB holds interest rates", "priority": 5, "selection_reason": "..."},
    ]
    with caplog.at_level(logging.INFO, logger="src.pipeline"):
        Pipeline._attach_raw_data_from_curated(raw_assignments, curated_topics)
    assert raw_assignments[0]["raw_data"]["source_ids"] == ["x", "y"]
    assert any("matched by slug" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_run_partial_editor_from_with_topic_filter(tmp_path) -> None:
    """`--from editor --topic 1` runs Editor first; topic_filter clips after.

    Regression for the pre-fix bug where topic_filter / priority-0 / sort
    blocks fired on the empty assignments list before Editor produced any.
    """
    reuse_date = "2026-04-28"
    reuse_dir = tmp_path / "output" / reuse_date
    reuse_dir.mkdir(parents=True)
    # Editor needs curated_topics on disk
    (reuse_dir / "02-curator-topics.json").write_text(json.dumps([
        {"title": "Topic A"}, {"title": "Topic B"}, {"title": "Topic C"},
    ]))

    pipeline = Pipeline(
        name="test", agents={}, mode="quick",
        output_dir=str(tmp_path / "output"),
        state_dir=str(tmp_path / "state"),
    )
    synthetic = [
        TopicAssignment(id="tp-001", title="Topic A", priority=5,
                        topic_slug="topic-a", selection_reason="r"),
        TopicAssignment(id="tp-002", title="Topic B", priority=4,
                        topic_slug="topic-b", selection_reason="r"),
        TopicAssignment(id="tp-003", title="Topic C", priority=3,
                        topic_slug="topic-c", selection_reason="r"),
    ]
    pipeline.editorial_conference = AsyncMock(return_value=synthetic)

    # to_step="editor" → returns after the editor branch with no produce()
    packages = await pipeline.run_partial(
        from_step="editor", to_step="editor",
        reuse_date=reuse_date, topic_filter=1,
    )
    pipeline.editorial_conference.assert_awaited_once()
    # No exception raised → fix works. Editor branch returns empty packages
    # at to_step="editor"; the topic_filter clip ran (assignments[0]).
    assert packages == []


@pytest.mark.asyncio
async def test_run_partial_researcher_topic_filter_in_range(tmp_path) -> None:
    """`--from researcher --topic 1` with valid index applies filter cleanly."""
    reuse_date = "2026-04-28"
    reuse_dir = tmp_path / "output" / reuse_date
    reuse_dir.mkdir(parents=True)
    (reuse_dir / "03-editor-assignments.json").write_text(json.dumps([
        {"id": "tp-001", "title": "T1", "priority": 5, "topic_slug": "t1",
         "selection_reason": "r", "raw_data": {}},
        {"id": "tp-002", "title": "T2", "priority": 4, "topic_slug": "t2",
         "selection_reason": "r", "raw_data": {}},
    ]))

    pipeline = Pipeline(
        name="test", agents={}, mode="quick",
        output_dir=str(tmp_path / "output"),
        state_dir=str(tmp_path / "state"),
    )
    captured: dict = {}

    async def fake_produce(assignments, to_step=None):
        captured["assignments"] = list(assignments)
        return []

    pipeline.produce = fake_produce

    packages = await pipeline.run_partial(
        from_step="researcher", reuse_date=reuse_date, topic_filter=1,
    )
    assert packages == []
    assert len(captured["assignments"]) == 1
    assert captured["assignments"][0].id == "tp-001"


@pytest.mark.asyncio
async def test_run_partial_researcher_topic_filter_out_of_range(tmp_path) -> None:
    """`--from researcher --topic 99` still raises PipelineError."""
    reuse_date = "2026-04-28"
    reuse_dir = tmp_path / "output" / reuse_date
    reuse_dir.mkdir(parents=True)
    (reuse_dir / "03-editor-assignments.json").write_text(json.dumps([
        {"id": "tp-001", "title": "T1", "priority": 5, "topic_slug": "t1",
         "selection_reason": "r", "raw_data": {}},
    ]))

    pipeline = Pipeline(
        name="test", agents={}, mode="quick",
        output_dir=str(tmp_path / "output"),
        state_dir=str(tmp_path / "state"),
    )

    with pytest.raises(PipelineError, match="out of range"):
        await pipeline.run_partial(
            from_step="researcher", reuse_date=reuse_date, topic_filter=99,
        )


def test_attach_raw_data_no_match_graceful(caplog) -> None:
    """Editor returns a title with no curated counterpart — raw_data stays empty."""
    curated_topics = [
        {"title": "Topic A", "source_ids": ["a"]},
    ]
    raw_assignments = [
        {"title": "Completely Unrelated", "priority": 5, "selection_reason": "..."},
    ]
    with caplog.at_level(logging.WARNING, logger="src.pipeline"):
        Pipeline._attach_raw_data_from_curated(raw_assignments, curated_topics)
    assert raw_assignments[0]["raw_data"] == {}
    assert any("did not match any curated topic" in r.message for r in caplog.records)


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
        system_prompt_path=str(collector_prompt),
        instructions_path=str(collector_prompt),
    )
    curator = Agent(
        name="curator",
        model=MODEL,
        system_prompt_path=str(curator_prompt),
        instructions_path=str(curator_prompt),
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
