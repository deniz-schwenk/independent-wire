"""Tests for V2 ``scripts/run.py`` — the CLI built on PipelineRunner.

Covers:
- ``create_agents`` / ``create_agents_hydrated`` still return the expected
  agent dicts with non-empty schemas.
- Stage-name validation against the V2 stage lists (production + hydrated).
- Stage-order validation rejects ``--to`` before ``--from``.
- New ``--max-produce`` flag parsing.
- ``--topic`` flag parsing.
- ``_resolve_reuse`` helper resolves date / date+run_id forms.
- The V1 hydrated-gate constraint is gone — ``--hydrated`` without
  ``--from researcher`` is accepted.
- Runner construction wires variant-correct stage lists.

The legacy V1 helper ``src.hydration_urls.attach_hydration_urls`` is still
covered separately in V1 tests; this file focuses on V2 CLI shape.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_run_module():
    """Import ``scripts/run.py`` as a module under the name ``scripts_run``."""
    if "scripts_run" in sys.modules:
        return sys.modules["scripts_run"]
    spec = importlib.util.spec_from_file_location(
        "scripts_run", ROOT / "scripts" / "run.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["scripts_run"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Agent dict shape
# ---------------------------------------------------------------------------


def test_create_agents_hydrated_returns_all_required_agents():
    run = _load_run_module()
    agents = run.create_agents_hydrated()
    expected = {
        "curator", "editor",
        "researcher_plan", "researcher_assemble",
        "researcher_hydrated_plan",
        "hydration_aggregator_phase1", "hydration_aggregator_phase2",
        "perspective", "writer", "qa_analyze", "bias_language",
        "perspective_sync",
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
        "perspective", "writer", "qa_analyze", "bias_language",
        "perspective_sync",
    ]
    for name in schema_required:
        agent = agents[name]
        schema = getattr(agent, "output_schema", None)
        assert schema, f"{name} has no output_schema"
        assert isinstance(schema, dict) and schema != {}, (
            f"{name} has empty output_schema"
        )


# ---------------------------------------------------------------------------
# _resolve_reuse helper
# ---------------------------------------------------------------------------


def test_resolve_reuse_date_only_picks_latest_run_id(tmp_path: Path):
    run = _load_run_module()
    state_dir = tmp_path / "2026-04-30" / "_state"
    state_dir.mkdir(parents=True)
    (state_dir / "run-2026-04-30-aaaaaaaa").mkdir()
    (state_dir / "run-2026-04-30-bbbbbbbb").mkdir()
    # Make bbbbbbbb the more recent one
    import time as _t
    _t.sleep(0.01)
    (state_dir / "run-2026-04-30-bbbbbbbb").touch()

    date, run_id = run._resolve_reuse("2026-04-30", tmp_path)
    assert date == "2026-04-30"
    assert run_id in {"run-2026-04-30-aaaaaaaa", "run-2026-04-30-bbbbbbbb"}


def test_resolve_reuse_explicit_run_id(tmp_path: Path):
    run = _load_run_module()
    state_dir = tmp_path / "2026-04-30" / "_state"
    state_dir.mkdir(parents=True)
    (state_dir / "run-2026-04-30-aaaaaaaa").mkdir()

    date, run_id = run._resolve_reuse(
        "2026-04-30/run-2026-04-30-aaaaaaaa", tmp_path
    )
    assert date == "2026-04-30"
    assert run_id == "run-2026-04-30-aaaaaaaa"


def test_resolve_reuse_missing_state_dir_raises(tmp_path: Path):
    run = _load_run_module()
    with pytest.raises(RuntimeError, match="no state directory"):
        run._resolve_reuse("2026-04-30", tmp_path)


def test_resolve_reuse_unknown_run_id_raises(tmp_path: Path):
    run = _load_run_module()
    state_dir = tmp_path / "2026-04-30" / "_state"
    state_dir.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="not found"):
        run._resolve_reuse("2026-04-30/run-does-not-exist", tmp_path)


# ---------------------------------------------------------------------------
# parse_args — flag presence + defaults
# ---------------------------------------------------------------------------


def test_parse_args_max_produce_default_three():
    run = _load_run_module()
    with patch.object(sys, "argv", ["run.py"]):
        args = run.parse_args()
    assert args.max_produce == 3


def test_parse_args_max_produce_override():
    run = _load_run_module()
    with patch.object(sys, "argv", ["run.py", "--max-produce", "7"]):
        args = run.parse_args()
    assert args.max_produce == 7


def test_parse_args_topic_default_none():
    run = _load_run_module()
    with patch.object(sys, "argv", ["run.py"]):
        args = run.parse_args()
    assert args.topic is None


def test_parse_args_topic_override():
    run = _load_run_module()
    with patch.object(sys, "argv", ["run.py", "--topic", "2"]):
        args = run.parse_args()
    assert args.topic == 2


def test_parse_args_no_choices_constraint_on_from():
    """V1 used choices=[...] for --from. V2 validates dynamically in main()
    against the active variant's stage list, so argparse no longer rejects
    arbitrary strings at parse time."""
    run = _load_run_module()
    with patch.object(sys, "argv", ["run.py", "--from", "anything-goes"]):
        args = run.parse_args()
    assert args.from_step == "anything-goes"


# ---------------------------------------------------------------------------
# main() — stage-name validation
# ---------------------------------------------------------------------------


def _namespace(**overrides):
    base = dict(
        from_step=None, to_step=None, topic=None, reuse=None,
        max_produce=3, fetch=False, publish=False, hydrated=False,
        help_stages=False, force=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _patch_runner(run_module, run_bus_factory=None):
    """Replace PipelineRunner with a mock that captures construction args
    and returns a stub RunBus from .run()."""

    captured = {}

    class _StubRunner:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        async def run(self):
            from src.bus import RunBus
            rb = run_bus_factory() if run_bus_factory else RunBus()
            return rb

    run_module.PipelineRunner = _StubRunner
    return captured


def _patch_create_agents(run_module):
    """Avoid the heavy real Agent construction (which loads prompt files)."""
    fake_agents = {k: MagicMock(name=k) for k in [
        "curator", "editor", "researcher_plan", "researcher_assemble",
        "perspective", "writer", "qa_analyze", "bias_language",
        "researcher_hydrated_plan",
        "hydration_aggregator_phase1", "hydration_aggregator_phase2",
        "perspective_sync",
    ]}
    run_module.create_agents = lambda: dict(fake_agents)
    run_module.create_agents_hydrated = lambda: dict(fake_agents)


def _run_main(run_module, args, capsys=None):
    """Execute main() with parse_args overridden to return the given Namespace."""
    original_parse = run_module.parse_args
    run_module.parse_args = lambda: args
    try:
        return asyncio.run(run_module.main())
    finally:
        run_module.parse_args = original_parse


def test_main_rejects_invalid_from_stage_in_production(caplog):
    run = _load_run_module()
    _patch_create_agents(run)
    _patch_runner(run)
    args = _namespace(from_step="collector", reuse="2026-04-30")  # V1 name, gone

    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as exc_info:
            _run_main(run, args)
    assert exc_info.value.code == 1
    assert "not a valid stage" in caplog.text


def test_main_accepts_v2_production_stage_name(tmp_path: Path):
    run = _load_run_module()
    _patch_create_agents(run)
    captured = _patch_runner(run)
    state_dir = tmp_path / "output" / "2026-04-30" / "_state" / "run-x"
    state_dir.mkdir(parents=True)
    run.ROOT = tmp_path  # redirect output_dir resolution

    args = _namespace(
        from_step="ResearcherPlanStage",
        to_step="ResearcherPlanStage",
        reuse="2026-04-30/run-x",
    )
    _run_main(run, args)
    assert captured["kwargs"]["from_stage"] == "ResearcherPlanStage"
    assert captured["kwargs"]["to_stage"] == "ResearcherPlanStage"


def test_main_rejects_hydrated_only_stage_in_production(caplog):
    run = _load_run_module()
    _patch_create_agents(run)
    _patch_runner(run)
    args = _namespace(
        from_step="HydrationPhase1Stage",  # hydrated-only
        reuse="2026-04-30",
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit):
            _run_main(run, args)
    assert "not a valid stage" in caplog.text


def test_main_accepts_hydrated_only_stage_under_hydrated(tmp_path: Path):
    run = _load_run_module()
    _patch_create_agents(run)
    captured = _patch_runner(run)
    state_dir = tmp_path / "output" / "2026-04-30" / "_state" / "run-x"
    state_dir.mkdir(parents=True)
    run.ROOT = tmp_path

    args = _namespace(
        from_step="HydrationPhase1Stage",
        to_step="HydrationPhase1Stage",
        reuse="2026-04-30/run-x",
        hydrated=True,
    )
    _run_main(run, args)
    assert captured["kwargs"]["from_stage"] == "HydrationPhase1Stage"


def test_main_rejects_to_before_from(caplog, tmp_path: Path):
    run = _load_run_module()
    _patch_create_agents(run)
    _patch_runner(run)
    state_dir = tmp_path / "output" / "2026-04-30" / "_state" / "run-x"
    state_dir.mkdir(parents=True)
    run.ROOT = tmp_path

    args = _namespace(
        from_step="WriterStage",
        to_step="ResearcherPlanStage",
        reuse="2026-04-30/run-x",
    )
    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit):
            _run_main(run, args)
    assert "before --from" in caplog.text


def test_main_rejects_from_without_reuse(caplog):
    run = _load_run_module()
    _patch_create_agents(run)
    _patch_runner(run)
    args = _namespace(from_step="ResearcherPlanStage", reuse=None)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit):
            _run_main(run, args)
    assert "--reuse" in caplog.text


# ---------------------------------------------------------------------------
# main() — V1 hydrated-gate is GONE
# ---------------------------------------------------------------------------


def test_main_hydrated_without_from_or_reuse_does_not_raise(tmp_path: Path):
    """V1 raised when --hydrated had no --from researcher --reuse. V2
    removes this constraint — from-scratch hydrated runs are supported."""
    run = _load_run_module()
    _patch_create_agents(run)
    captured = _patch_runner(run)
    run.ROOT = tmp_path

    args = _namespace(hydrated=True)
    _run_main(run, args)
    # No exception, runner constructed
    assert captured["kwargs"]["from_stage"] is None
    assert captured["kwargs"]["reuse_run_id"] is None


# ---------------------------------------------------------------------------
# main() — runner construction wires variant-correct stage lists
# ---------------------------------------------------------------------------


def test_main_production_runner_kwargs(tmp_path: Path):
    run = _load_run_module()
    _patch_create_agents(run)
    captured = _patch_runner(run)
    run.ROOT = tmp_path

    args = _namespace(max_produce=5, topic=2)
    _run_main(run, args)
    kwargs = captured["kwargs"]
    assert kwargs["topic_filter"] == 2
    # The first run-stage in production is init_run (function); confirm we
    # routed through build_production_stages and not the hydrated builder
    from src.runner.runner import _stage_label
    run_stage_names = [_stage_label(s) for s in kwargs["run_stages"]]
    topic_stage_names = [_stage_label(s) for s in kwargs["topic_stages"]]
    assert "init_run" in run_stage_names
    # production has no hydration_fetch
    assert "hydration_fetch" not in topic_stage_names


def test_main_hydrated_runner_kwargs(tmp_path: Path):
    run = _load_run_module()
    _patch_create_agents(run)
    captured = _patch_runner(run)
    run.ROOT = tmp_path

    args = _namespace(hydrated=True)
    _run_main(run, args)
    from src.runner.runner import _stage_label
    topic_stage_names = [_stage_label(s) for s in captured["kwargs"]["topic_stages"]]
    assert "hydration_fetch" in topic_stage_names
    assert "PerspectiveSyncStage" in topic_stage_names


# ---------------------------------------------------------------------------
# main() — manifest-based reporting
# ---------------------------------------------------------------------------


def test_main_logs_manifest_summary(caplog):
    run = _load_run_module()
    _patch_create_agents(run)

    def _fake_run_bus():
        from src.bus import RunBus
        rb = RunBus()
        rb.run_date = "2026-04-30"
        rb.run_id = "run-x"
        rb.run_topic_manifest = [
            {"topic_id": "t1", "topic_slug": "s1", "status": "success", "stages_completed": []},
            {"topic_id": "t2", "topic_slug": "s2", "status": "failed", "stages_completed": []},
            {"topic_id": "t3", "topic_slug": "s3", "status": "skipped", "stages_completed": []},
        ]
        return rb

    _patch_runner(run, run_bus_factory=_fake_run_bus)
    args = _namespace()
    with caplog.at_level(logging.INFO):
        _run_main(run, args)
    assert "1 completed, 1 skipped, 1 failed" in caplog.text
    assert "completed t1" in caplog.text
    assert "failed t2" in caplog.text
    assert "skipped t3" in caplog.text


# ---------------------------------------------------------------------------
# --force gate on --reuse overwrites
# ---------------------------------------------------------------------------


def test_check_reuse_overwrite_safety_aborts_without_force_when_state_exists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
):
    run = _load_run_module()
    state_dir = tmp_path / "2026-05-04" / "_state"
    state_dir.mkdir(parents=True)
    (state_dir / "run-2026-05-04-deadbeef").mkdir()

    with pytest.raises(SystemExit) as excinfo:
        run._check_reuse_overwrite_safety("2026-05-04", tmp_path, force=False)
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "already exists" in err
    assert "run-2026-05-04-deadbeef" in err
    assert "--force" in err


def test_check_reuse_overwrite_safety_proceeds_with_force_when_state_exists(
    tmp_path: Path,
):
    run = _load_run_module()
    state_dir = tmp_path / "2026-05-04" / "_state"
    state_dir.mkdir(parents=True)
    (state_dir / "run-2026-05-04-deadbeef").mkdir()

    # Must NOT raise
    run._check_reuse_overwrite_safety("2026-05-04", tmp_path, force=True)


def test_check_reuse_overwrite_safety_proceeds_without_force_when_no_prior_state(
    tmp_path: Path,
):
    run = _load_run_module()
    # No state directory at all
    run._check_reuse_overwrite_safety("2026-05-04", tmp_path, force=False)
    # Empty state directory also passes
    (tmp_path / "2026-05-04" / "_state").mkdir(parents=True)
    run._check_reuse_overwrite_safety("2026-05-04", tmp_path, force=False)
