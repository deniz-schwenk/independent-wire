"""Tests for the --hydrated wiring in scripts/run.py.

Covers:
- create_agents_hydrated() returns the eleven agents the hydrated
  pipeline needs.
- Each hydrated agent carries a non-empty output_schema (no {} stubs).
- attach_hydration_urls (in src.hydration_urls) matches assignments
  to clusters by token overlap and writes urls into raw_data.
- main() raises a clear RuntimeError when --hydrated is invoked
  without --from researcher --reuse {date}.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.hydration_urls import attach_hydration_urls
from src.models import TopicAssignment


def _load_run_module():
    """Import scripts/run.py as a module under the name ``scripts_run``."""
    if "scripts_run" in sys.modules:
        return sys.modules["scripts_run"]
    spec = importlib.util.spec_from_file_location(
        "scripts_run", ROOT / "scripts" / "run.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["scripts_run"] = module
    spec.loader.exec_module(module)
    return module


def test_create_agents_hydrated_returns_all_required_agents():
    run = _load_run_module()
    agents = run.create_agents_hydrated()
    expected = {
        "curator", "editor",
        "researcher_plan", "researcher_assemble",
        "researcher_hydrated_plan",
        "hydration_aggregator_phase1", "hydration_aggregator_phase2",
        "perspektiv", "writer", "qa_analyze", "bias_language",
        "perspektiv_sync",
    }
    assert expected.issubset(agents.keys()), (
        f"missing agents: {expected - agents.keys()}"
    )


def test_create_agents_hydrated_wires_all_schemas():
    run = _load_run_module()
    agents = run.create_agents_hydrated()
    schema_required = [
        "curator", "editor", "researcher_plan", "researcher_assemble",
        "researcher_hydrated_plan",
        "hydration_aggregator_phase1", "hydration_aggregator_phase2",
        "perspektiv", "writer", "qa_analyze", "bias_language",
        "perspektiv_sync",
    ]
    for name in schema_required:
        agent = agents[name]
        schema = getattr(agent, "output_schema", None)
        assert schema, f"{name} has no output_schema"
        assert isinstance(schema, dict) and schema != {}, (
            f"{name} has empty output_schema"
        )


def test_attach_hydration_urls_matches_by_token_overlap(tmp_path):
    reuse = "2026-04-28"
    out = tmp_path / "output" / reuse
    raw = tmp_path / "raw" / reuse
    cfg = tmp_path / "config"
    out.mkdir(parents=True)
    raw.mkdir(parents=True)
    cfg.mkdir(parents=True)

    (out / "02-curator-topics-unsliced.json").write_text(json.dumps([
        {
            "title": "India and New Zealand sign comprehensive free trade agreement",
            "source_ids": ["finding-0", "finding-1"],
        },
        {
            "title": "Tropical storm hits Philippines coast",
            "source_ids": ["finding-2"],
        },
    ]))
    (raw / "feeds.json").write_text(json.dumps([
        {"source_name": "Reuters", "source_url": "https://reuters.example/india", "language": "en", "title": "Reuters India"},
        {"source_name": "BBC", "source_url": "https://bbc.example/india", "language": "en", "title": "BBC India"},
        {"source_name": "AFP", "source_url": "https://afp.example/storm", "language": "en", "title": "AFP storm"},
    ]))
    (cfg / "sources.json").write_text(json.dumps({
        "feeds": [
            {"name": "Reuters", "country": "GB"},
            {"name": "BBC", "country": "GB"},
            {"name": "AFP", "country": "FR"},
        ],
    }))

    assignments = [
        TopicAssignment(
            id="tp-001", title="India New Zealand Free Trade Agreement Signed",
            priority=5, topic_slug="india-nz-fta", selection_reason="r",
        ),
        TopicAssignment(
            id="tp-002", title="Philippines tropical storm casualties",
            priority=4, topic_slug="ph-storm", selection_reason="r",
        ),
    ]
    attach_hydration_urls(assignments, reuse, repo_root=tmp_path)

    a0 = assignments[0].raw_data
    assert a0 is not None
    urls0 = a0["hydration_urls"]
    assert len(urls0) == 2
    assert {u["outlet"] for u in urls0} == {"Reuters", "BBC"}
    assert {u["country"] for u in urls0} == {"GB"}

    urls1 = assignments[1].raw_data["hydration_urls"]
    assert len(urls1) == 1
    assert urls1[0]["outlet"] == "AFP"


def test_attach_hydration_urls_no_match_logs_warning_and_returns_empty(tmp_path):
    reuse = "2026-04-28"
    out = tmp_path / "output" / reuse
    raw = tmp_path / "raw" / reuse
    out.mkdir(parents=True)
    raw.mkdir(parents=True)
    (out / "02-curator-topics-unsliced.json").write_text(json.dumps([
        {"title": "Completely unrelated cluster about lemur migration", "source_ids": []},
    ]))
    (raw / "feeds.json").write_text(json.dumps([]))

    assignments = [
        TopicAssignment(
            id="tp-001", title="India New Zealand free trade",
            priority=5, topic_slug="x", selection_reason="r",
        ),
    ]
    attach_hydration_urls(assignments, reuse, repo_root=tmp_path)

    assert assignments[0].raw_data["hydration_urls"] == []


def test_run_cli_rejects_hydrated_without_reuse():
    run = _load_run_module()

    args = argparse.Namespace(
        from_step=None, to_step=None, topic=None, reuse=None,
        fetch=False, publish=False, hydrated=True,
    )

    async def _go():
        sys.argv = ["run.py", "--hydrated"]

        # Patch parse_args to return our crafted Namespace.
        import scripts_run as run_module  # type: ignore
        original = run_module.parse_args
        run_module.parse_args = lambda: args
        try:
            await run_module.main()
        finally:
            run_module.parse_args = original

    with pytest.raises(RuntimeError, match="--hydrated"):
        asyncio.run(_go())


def test_run_cli_rejects_hydrated_with_wrong_from_step():
    run = _load_run_module()

    args = argparse.Namespace(
        from_step="perspektiv", to_step=None, topic=None, reuse="2026-04-28",
        fetch=False, publish=False, hydrated=True,
    )

    async def _go():
        sys.argv = ["run.py", "--hydrated", "--from", "perspektiv", "--reuse", "2026-04-28"]
        import scripts_run as run_module  # type: ignore
        original = run_module.parse_args
        run_module.parse_args = lambda: args
        try:
            await run_module.main()
        finally:
            run_module.parse_args = original

    with pytest.raises(RuntimeError, match="--hydrated"):
        asyncio.run(_go())
