"""Tests for scripts/migrate_what_is_missing_in_tp_json.py.

The migration script backfills ``perspectives.what_is_missing`` into
historical published Topic Packages by calling the Consolidator agent
once per TP. Tests use a fake agent so they do not hit the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


def _load_migrate_module():
    """Load scripts/migrate_what_is_missing_in_tp_json.py as a module.

    The repo's ``scripts/`` directory is not a package, so we load by
    explicit path to keep the test independent of sys.path tweaks.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "migrate_what_is_missing_in_tp_json.py"
    )
    spec = importlib.util.spec_from_file_location(
        "migrate_what_is_missing_in_tp_json", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migrate_what_is_missing_in_tp_json"] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _FakeResult:
    content: str = ""
    structured: dict | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0


class _FakeAgent:
    """Records every call so tests can assert how many LLM round-trips
    the migration triggered. ``returns`` is the structured payload the
    fake echoes back via the next ``run`` call."""

    def __init__(self, returns: dict) -> None:
        self._returns = returns
        self.calls: list[dict] = []

    async def run(self, message: str = "", context: dict | None = None):
        self.calls.append({"message": message, "context": context or {}})
        return _FakeResult(structured=dict(self._returns))


def _old_shape_tp() -> dict:
    return {
        "perspectives": {
            "position_clusters": [],
            "missing_positions": [
                {"type": "civil_society",
                 "description": "Labor rights NGOs not quoted."},
                {"type": "academia",
                 "description": "No mining safety researchers cited."},
            ],
        },
        "bias_analysis": {
            "selection": {
                "coverage_gaps": [
                    "African outlets absent from corpus.",
                    "No coverage of mine ownership financial structure.",
                ]
            }
        },
        "consolidated_missing_coverage": {
            "missing_stakeholder_voices": [{"type": "civil_society",
                                            "description": "..."}],
            "missing_topic_dimensions": ["..."],
        },
    }


def _new_shape_tp() -> dict:
    return {
        "perspectives": {
            "position_clusters": [],
            "missing_positions": [
                {"type": "civil_society", "description": "..."}
            ],
            "what_is_missing": {
                "voices_missing": ["Labor rights organizations"],
                "topics_missing": ["Financial structure"],
            },
        },
        "bias_analysis": {"selection": {}},
    }


def _empty_inputs_tp() -> dict:
    return {
        "perspectives": {
            "position_clusters": [],
            "missing_positions": [],
        },
        "bias_analysis": {"selection": {"coverage_gaps": []}},
    }


@pytest.mark.asyncio
async def test_migrate_old_shape_tp_writes_what_is_missing(tmp_path):
    """A TP that lacks `what_is_missing` but has legacy inputs gets
    migrated: the Consolidator is called once, the result is written
    into `perspectives.what_is_missing`, and the legacy keys are
    removed (hard-cut policy)."""
    mod = _load_migrate_module()
    tp_file = tmp_path / "tp-2026-04-13-001.json"
    tp_file.write_text(json.dumps(_old_shape_tp()))

    agent = _FakeAgent(
        returns={
            "voices_missing": ["Labor rights NGOs", "African outlets"],
            "topics_missing": ["Mine ownership financial structure"],
        }
    )

    status, _msg = await mod.migrate_tp_file(
        tp_file, consolidator_agent=agent, dry_run=False
    )

    assert status == "migrated"
    assert len(agent.calls) == 1
    written = json.loads(tp_file.read_text())
    wim = written["perspectives"]["what_is_missing"]
    assert wim["voices_missing"] == ["Labor rights NGOs", "African outlets"]
    assert wim["topics_missing"] == ["Mine ownership financial structure"]
    # Hard-cut: legacy keys removed
    assert "consolidated_missing_coverage" not in written
    assert "coverage_gaps" not in written["bias_analysis"]["selection"]


@pytest.mark.asyncio
async def test_migrate_new_shape_tp_is_skipped_no_llm_call(tmp_path):
    """A TP that already carries a non-empty `what_is_missing` is
    idempotently skipped — the LLM is not invoked, and the file is not
    modified."""
    mod = _load_migrate_module()
    tp_file = tmp_path / "tp-2026-05-28-001.json"
    original = _new_shape_tp()
    tp_file.write_text(json.dumps(original))

    agent = _FakeAgent(returns={"voices_missing": ["x"], "topics_missing": []})

    status, _msg = await mod.migrate_tp_file(
        tp_file, consolidator_agent=agent, dry_run=False
    )

    assert status == "skip"
    assert agent.calls == []
    assert json.loads(tp_file.read_text()) == original


@pytest.mark.asyncio
async def test_migrate_empty_inputs_tp_skipped(tmp_path):
    """A TP with no legacy inputs to feed the Consolidator is skipped
    (no LLM call, file unchanged)."""
    mod = _load_migrate_module()
    tp_file = tmp_path / "tp-2026-04-09-001.json"
    original = _empty_inputs_tp()
    tp_file.write_text(json.dumps(original))

    agent = _FakeAgent(returns={"voices_missing": [], "topics_missing": []})

    status, _msg = await mod.migrate_tp_file(
        tp_file, consolidator_agent=agent, dry_run=False
    )

    assert status == "skip-empty"
    assert agent.calls == []
    assert json.loads(tp_file.read_text()) == original


@pytest.mark.asyncio
async def test_migrate_is_idempotent_on_second_run(tmp_path):
    """Running the migration twice on the same TP triggers exactly one
    LLM call. The second pass observes the populated `what_is_missing`
    and skips."""
    mod = _load_migrate_module()
    tp_file = tmp_path / "tp-2026-04-13-001.json"
    tp_file.write_text(json.dumps(_old_shape_tp()))

    agent = _FakeAgent(
        returns={"voices_missing": ["Labor rights"], "topics_missing": ["X"]}
    )

    first, _ = await mod.migrate_tp_file(
        tp_file, consolidator_agent=agent, dry_run=False
    )
    second, _ = await mod.migrate_tp_file(
        tp_file, consolidator_agent=agent, dry_run=False
    )

    assert first == "migrated"
    assert second == "skip"
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_migrate_dry_run_does_not_write(tmp_path):
    """`--dry-run` mode reports what would happen but does not invoke
    the LLM and does not modify the file."""
    mod = _load_migrate_module()
    tp_file = tmp_path / "tp-2026-04-13-001.json"
    original = _old_shape_tp()
    tp_file.write_text(json.dumps(original))

    agent = _FakeAgent(
        returns={"voices_missing": ["x"], "topics_missing": []}
    )

    status, _msg = await mod.migrate_tp_file(
        tp_file, consolidator_agent=agent, dry_run=True
    )

    assert status == "migrated-dry"
    assert agent.calls == []
    # File unchanged
    assert json.loads(tp_file.read_text()) == original


@pytest.mark.asyncio
async def test_migrate_passes_inputs_with_expected_shape(tmp_path):
    """The Consolidator receives the same context shape it expects in
    the live pipeline: `perspective_missing_positions` (structured) +
    `merged_coverage_gaps` (free-text strings)."""
    mod = _load_migrate_module()
    tp_file = tmp_path / "tp.json"
    tp_file.write_text(json.dumps(_old_shape_tp()))

    agent = _FakeAgent(returns={"voices_missing": [], "topics_missing": []})

    await mod.migrate_tp_file(
        tp_file, consolidator_agent=agent, dry_run=False
    )

    ctx = agent.calls[0]["context"]
    assert "perspective_missing_positions" in ctx
    assert "merged_coverage_gaps" in ctx
    # Structured shape preserved
    assert ctx["perspective_missing_positions"][0]["type"] == "civil_society"
    # Free-text shape preserved
    assert all(isinstance(s, str) for s in ctx["merged_coverage_gaps"])
