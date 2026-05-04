"""Tests for src/runner — PipelineRunner, stage_lists, state persistence.

No real LLM calls. Stages are either real deterministic stages from
src/stages/, or fake decorator-stamped functions that mark progress in
RunBus / TopicBus slots.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from src.bus import (
    EditorAssignment,
    RunBus,
    RunBusReadOnly,
    TopicBus,
    WriterArticle,
)
from src.stage import (
    StageError,
    StageReadOnlyViolationError,
    get_stage_meta,
    run_stage_def,
    topic_stage_def,
)
from src.runner.runner import (
    FinalizeRunStage,
    PipelineRunner,
    RenderStage,
    _stage_label,
)
from src.runner.stage_lists import (
    build_hydrated_stages,
    build_production_stages,
    hydrated_stage_names,
    production_stage_names,
)
from src.runner.state import (
    load_run_bus_latest,
    load_run_bus_snapshot,
    load_topic_bus_collection,
    load_topic_bus_per_stage_snapshots,
    save_run_bus_snapshot,
    save_topic_bus_collection,
    save_topic_bus_snapshot,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAgent:
    """Stand-in for src.agent.Agent — only carries a name attribute."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, *args, **kwargs):  # pragma: no cover — wrappers don't run
        raise RuntimeError("fake agent should not be invoked in stage-list tests")


def _fake_agent_dict(keys: list[str]) -> dict:
    return {k: _FakeAgent(k) for k in keys}


_PRODUCTION_AGENTS = [
    "curator", "editor", "researcher_plan", "researcher_assemble",
    "perspective", "writer", "qa_analyze", "bias_language",
]
_HYDRATED_AGENTS = _PRODUCTION_AGENTS + [
    "researcher_hydrated_plan",
    "hydration_aggregator_phase1",
    "hydration_aggregator_phase2",
    "perspective_sync",
]


def _make_assignment(topic_id: str = "topic-001") -> EditorAssignment:
    return EditorAssignment(
        id=topic_id,
        title=f"Title {topic_id}",
        topic_slug=f"slug-{topic_id}",
        priority=5,
        selection_reason="for testing",
        raw_data={"hydration_urls": []},
    )


# ---------------------------------------------------------------------------
# Stage-list-builder tests
# ---------------------------------------------------------------------------


def test_build_production_stages_returns_three_lists():
    agents = _fake_agent_dict(_PRODUCTION_AGENTS)
    run_stages, topic_stages, post_run_stages = build_production_stages(agents)
    assert run_stages, "run_stages should not be empty"
    assert topic_stages, "topic_stages should not be empty"
    assert post_run_stages == [], "production post_run_stages reserved for runner-built handlers"
    assert len(topic_stages) == 16, f"expected 16 production topic-stages per ARCH §5.1+V2-06b, got {len(topic_stages)}"


def test_build_hydrated_stages_returns_three_lists():
    agents = _fake_agent_dict(_HYDRATED_AGENTS)
    run_stages, topic_stages, post_run_stages = build_hydrated_stages(agents)
    assert run_stages, "run_stages should not be empty"
    assert len(topic_stages) == 23, f"expected 23 hydrated topic-stages per ARCH §5.2+V2-06b, got {len(topic_stages)}"


def test_production_stage_names_unique():
    agents = _fake_agent_dict(_PRODUCTION_AGENTS)
    run_stages, topic_stages, _ = build_production_stages(agents)
    names = [_stage_label(s) for s in run_stages + topic_stages]
    assert len(names) == len(set(names)), f"duplicate stage names: {names}"


def test_hydrated_stage_names_repeat_only_for_double_mirror():
    agents = _fake_agent_dict(_HYDRATED_AGENTS)
    run_stages, topic_stages, _ = build_hydrated_stages(agents)
    names = [_stage_label(s) for s in run_stages + topic_stages]
    duplicates = [n for n in set(names) if names.count(n) > 1]
    assert duplicates == ["mirror_perspective_synced"], (
        f"hydrated should have exactly one duplicated stage (mirror_perspective_synced); got {duplicates}"
    )


def test_hydrated_run_stages_extends_production_with_hydration_attach():
    """The hydrated variant runs an extra ``attach_hydration_urls_to_assignments``
    run-stage between Editor and select_topics."""
    prod_agents = _fake_agent_dict(_PRODUCTION_AGENTS)
    hyd_agents = _fake_agent_dict(_HYDRATED_AGENTS)
    prod_run, _, _ = build_production_stages(prod_agents)
    hyd_run, _, _ = build_hydrated_stages(hyd_agents)
    prod_names = [_stage_label(s) for s in prod_run]
    hyd_names = [_stage_label(s) for s in hyd_run]
    assert prod_names == [
        "init_run", "fetch_findings", "CuratorStage", "EditorStage",
        "select_topics",
    ]
    assert hyd_names == [
        "init_run", "fetch_findings", "CuratorStage", "EditorStage",
        "attach_hydration_urls_to_assignments", "select_topics",
    ]


def test_hydrated_mirror_appears_exactly_twice():
    agents = _fake_agent_dict(_HYDRATED_AGENTS)
    _, topic_stages, _ = build_hydrated_stages(agents)
    names = [_stage_label(s) for s in topic_stages]
    assert names.count("mirror_perspective_synced") == 2


# ---------------------------------------------------------------------------
# State persistence tests
# ---------------------------------------------------------------------------


def _populated_run_bus(run_id: str = "run-2026-04-30-aabbccdd", run_date: str = "2026-04-30") -> RunBus:
    rb = RunBus()
    rb.run_id = run_id
    rb.run_date = run_date
    rb.run_variant = "production"
    rb.max_produce = 3
    return rb


def test_save_run_bus_snapshot_writes_files(tmp_path: Path):
    rb = _populated_run_bus()
    save_run_bus_snapshot(rb, tmp_path, "init_run")
    state_dir = tmp_path / rb.run_date / "_state" / rb.run_id
    assert (state_dir / "run_bus.json").exists()
    assert (state_dir / "run_bus.init_run.json").exists()


def test_load_run_bus_snapshot_round_trip(tmp_path: Path):
    rb = _populated_run_bus()
    rb.editor_assignments = [{"id": "x", "topic_slug": "y"}]
    save_run_bus_snapshot(rb, tmp_path, "editor")
    loaded = load_run_bus_snapshot(tmp_path, rb.run_id, rb.run_date, "editor")
    assert loaded.run_id == rb.run_id
    assert loaded.editor_assignments == rb.editor_assignments


def test_save_and_load_topic_bus_collection(tmp_path: Path):
    rb = _populated_run_bus()
    tbs = [TopicBus(editor_selected_topic=_make_assignment(f"topic-{i:03d}")) for i in range(3)]
    save_topic_bus_collection(tbs, tmp_path, rb.run_date, rb.run_id)
    loaded = load_topic_bus_collection(tmp_path, rb.run_id, rb.run_date)
    assert len(loaded) == 3
    assert [t.editor_selected_topic.id for t in loaded] == [
        "topic-000", "topic-001", "topic-002"
    ]


def test_load_run_bus_snapshot_missing_raises(tmp_path: Path):
    from src.stage import StageInputError
    with pytest.raises(StageInputError):
        load_run_bus_snapshot(tmp_path, "run-x", "2026-04-30", "init_run")


def test_per_stage_topic_snapshots_round_trip(tmp_path: Path):
    rb = _populated_run_bus()
    tbs = [TopicBus(editor_selected_topic=_make_assignment(f"topic-{i:03d}")) for i in range(2)]
    for i, tb in enumerate(tbs):
        save_topic_bus_snapshot(tb, tmp_path, rb.run_date, rb.run_id, "merge_sources", i)
    save_topic_bus_collection(tbs, tmp_path, rb.run_date, rb.run_id)
    loaded = load_topic_bus_per_stage_snapshots(
        tmp_path, rb.run_id, rb.run_date, "merge_sources", 2
    )
    assert len(loaded) == 2
    assert loaded[0].editor_selected_topic.id == "topic-000"


# ---------------------------------------------------------------------------
# Runner orchestration tests (mock-based)
# ---------------------------------------------------------------------------


@run_stage_def(reads=(), writes=("run_id", "run_date"))
async def _fake_init(run_bus: RunBus) -> RunBus:
    run_bus.run_id = "run-2026-04-30-fake"
    run_bus.run_date = "2026-04-30"
    return run_bus


@run_stage_def(reads=("run_id",), writes=("editor_assignments",))
async def _fake_curator(run_bus: RunBus) -> RunBus:
    run_bus.editor_assignments = [
        {"id": "topic-001", "topic_slug": "slug-001", "title": "T1", "priority": 5,
         "selection_reason": "x", "raw_data": {}},
        {"id": "topic-002", "topic_slug": "slug-002", "title": "T2", "priority": 4,
         "selection_reason": "x", "raw_data": {}},
    ]
    return run_bus


@run_stage_def(reads=("editor_assignments",), writes=("selected_assignments",))
async def _fake_select(run_bus: RunBus) -> RunBus:
    run_bus.selected_assignments = list(run_bus.editor_assignments or [])
    return run_bus


@topic_stage_def(reads=("editor_selected_topic",), writes=("writer_article",))
async def _fake_writer(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
    article = WriterArticle(
        headline="H " + topic_bus.editor_selected_topic.id,
        summary="S",
        body="B",
    )
    return topic_bus.model_copy(update={"writer_article": article})


@topic_stage_def(reads=("editor_selected_topic",), writes=("writer_article",))
async def _failing_topic_stage(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
    raise RuntimeError(
        f"intentional failure for {topic_bus.editor_selected_topic.id}"
    )


@topic_stage_def(reads=("editor_selected_topic",), writes=("writer_article",))
async def _readonly_violator(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
    object.__setattr__(run_bus, "run_id", "MUTATED")
    return topic_bus.model_copy(
        update={"writer_article": WriterArticle(headline="h", summary="s", body="b")}
    )


def test_runner_empty_stage_lists(tmp_path: Path):
    runner = PipelineRunner([], [], output_dir=tmp_path)
    rb = asyncio.run(runner.run())
    assert isinstance(rb, RunBus)


def test_runner_executes_run_stages_in_order(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    rb = asyncio.run(runner.run())
    assert rb.run_id == "run-2026-04-30-fake"
    assert len(rb.editor_assignments) == 2
    assert len(rb.selected_assignments) == 2


def test_runner_constructs_topic_buses_from_selected(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    asyncio.run(runner.run())
    assert len(runner.topic_buses) == 2
    ids = [tb.editor_selected_topic.id for tb in runner.topic_buses]
    assert ids == ["topic-001", "topic-002"]


def test_runner_topic_stages_serial_per_topic_bus(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    asyncio.run(runner.run())
    headlines = [tb.writer_article.headline for tb in runner.topic_buses]
    assert headlines == ["H topic-001", "H topic-002"]


def test_runner_isolates_topic_failure(tmp_path: Path):
    @topic_stage_def(reads=("editor_selected_topic",), writes=("writer_article",))
    async def _selective_fail(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
        if topic_bus.editor_selected_topic.id == "topic-001":
            raise RuntimeError("topic-001 boom")
        return topic_bus.model_copy(
            update={"writer_article": WriterArticle(headline="h", summary="s", body="b")}
        )

    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_selective_fail],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    asyncio.run(runner.run())
    assert runner._topic_status[0] == "failed"
    assert runner._topic_status[1] == "success"


def test_runner_catches_readonly_violation(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_readonly_violator],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    asyncio.run(runner.run())
    assert runner._topic_status[0] == "failed"
    assert runner._topic_status[1] == "failed"


def test_runner_run_topic_manifest_correct_after_mixed_outcomes(tmp_path: Path):
    @topic_stage_def(reads=("editor_selected_topic",), writes=("writer_article",))
    async def _topic_001_fails(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
        if topic_bus.editor_selected_topic.id == "topic-001":
            raise RuntimeError("boom")
        return topic_bus.model_copy(
            update={"writer_article": WriterArticle(headline="h", summary="s", body="b")}
        )

    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_topic_001_fails],
        output_dir=tmp_path,
        skip_render=True,
    )
    rb = asyncio.run(runner.run())
    manifest = rb.run_topic_manifest
    assert len(manifest) == 2
    by_id = {m["topic_id"]: m for m in manifest}
    assert by_id["topic-001"]["status"] == "failed"
    assert by_id["topic-002"]["status"] == "success"


def test_runner_from_stage_skips_earlier_run_stages(tmp_path: Path):
    """First seed snapshots from a prior run; then resume `--from _fake_select`."""
    runner1 = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    rb1 = asyncio.run(runner1.run())

    @run_stage_def(reads=("editor_assignments",), writes=("selected_assignments",))
    async def _fake_select_v2(run_bus: RunBus) -> RunBus:
        # After resume from snapshot, editor_assignments is still populated;
        # trim to one to demonstrate this stage actually ran.
        run_bus.selected_assignments = [list(run_bus.editor_assignments or [])[0]]
        return run_bus

    runner2 = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select_v2],
        topic_stages=[],
        output_dir=tmp_path,
        from_stage="_fake_select_v2",
        reuse_run_id=rb1.run_id,
        reuse_run_date=rb1.run_date,
        skip_render=True,
        skip_finalize=True,
    )
    rb2 = asyncio.run(runner2.run())
    # Loaded curator output, ran only _fake_select_v2 (which trims to 1)
    assert len(rb2.selected_assignments) == 1


def test_runner_to_stage_stops_in_topic_phase(tmp_path: Path):
    """--to in topic-phase suppresses post-run stages."""
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
        to_stage="_fake_writer",
    )
    rb = asyncio.run(runner.run())
    # No render output should be written because --to cuts before Phase D
    assert not (tmp_path / rb.run_date / "slug-001.json").exists()
    # And finalize_run was skipped, so manifest stays empty
    assert rb.run_topic_manifest == []


def test_runner_from_to_reuse_runs_one_stage(tmp_path: Path):
    runner1 = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    rb1 = asyncio.run(runner1.run())

    runner2 = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[],
        output_dir=tmp_path,
        from_stage="_fake_select",
        to_stage="_fake_select",
        reuse_run_id=rb1.run_id,
        reuse_run_date=rb1.run_date,
        skip_render=True,
        skip_finalize=True,
    )
    rb2 = asyncio.run(runner2.run())
    # Loaded curator output, ran only _fake_select; assignments preserved
    assert len(rb2.selected_assignments) == 2


def test_runner_from_stage_without_reuse_id_raises(tmp_path: Path):
    with pytest.raises(StageError):
        PipelineRunner(
            run_stages=[_fake_init, _fake_curator, _fake_select],
            topic_stages=[],
            output_dir=tmp_path,
            from_stage="_fake_select",  # no reuse_run_id/date
        )


# ---------------------------------------------------------------------------
# Render integration tests
# ---------------------------------------------------------------------------


def test_runner_writes_tp_public_after_full_run(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
    )
    rb = asyncio.run(runner.run())
    assert (tmp_path / rb.run_date / "slug-001.json").exists()
    assert (tmp_path / rb.run_date / "slug-002.json").exists()


def test_runner_writes_debug_dir(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
    )
    rb = asyncio.run(runner.run())
    debug_dir = tmp_path / rb.run_date / "_debug"
    assert debug_dir.is_dir()
    assert (debug_dir / "slug-001.json").exists()


def test_runner_finalize_writes_manifest(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
        skip_render=True,  # but keep finalize
    )
    rb = asyncio.run(runner.run())
    assert len(rb.run_topic_manifest) == 2
    statuses = {m["topic_id"]: m["status"] for m in rb.run_topic_manifest}
    assert statuses == {"topic-001": "success", "topic-002": "success"}


def test_runner_failed_topic_excluded_from_render(tmp_path: Path):
    @topic_stage_def(reads=("editor_selected_topic",), writes=("writer_article",))
    async def _topic_002_fails(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus:
        if topic_bus.editor_selected_topic.id == "topic-002":
            raise RuntimeError("boom")
        return topic_bus.model_copy(
            update={"writer_article": WriterArticle(headline="h", summary="s", body="b")}
        )

    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_topic_002_fails],
        output_dir=tmp_path,
    )
    rb = asyncio.run(runner.run())
    assert (tmp_path / rb.run_date / "slug-001.json").exists()
    assert not (tmp_path / rb.run_date / "slug-002.json").exists()


# ---------------------------------------------------------------------------
# Stage-label helper coverage
# ---------------------------------------------------------------------------


def test_run_stage_log_bus_slot_mirrors_disk_jsonl(tmp_path: Path):
    """Bug-2 regression: after a run completes, run_bus.run_stage_log holds
    the same entries as the on-disk run_stage_log.jsonl (in the same order).

    V2-08 only wrote to disk; the in-memory Bus slot stayed empty. This
    test asserts the post-V2-09c parity.
    """
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
    )
    rb = asyncio.run(runner.run())

    # Disk JSONL
    state_dir = tmp_path / rb.run_date / "_state" / rb.run_id
    jsonl_path = state_dir / "run_stage_log.jsonl"
    assert jsonl_path.exists(), "disk JSONL must exist after a successful run"
    disk_entries = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # Bus slot mirror
    bus_entries = list(rb.run_stage_log)

    assert bus_entries, "run_bus.run_stage_log must not be empty after a run"
    assert len(bus_entries) == len(disk_entries), (
        f"slot count {len(bus_entries)} != disk count {len(disk_entries)}"
    )
    for d, b in zip(disk_entries, bus_entries):
        assert d["stage"] == b["stage"], f"stage mismatch: disk={d}, bus={b}"
        assert d["status"] == b["status"], f"status mismatch: disk={d}, bus={b}"
        assert d["kind"] == b["kind"]


def test_run_stage_log_bus_slot_records_topic_stage_entries(tmp_path: Path):
    """Topic-stage success entries also land in the Bus slot, not just disk."""
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
    )
    rb = asyncio.run(runner.run())

    topic_entries = [e for e in rb.run_stage_log if e.get("kind") == "topic"]
    # 2 topics × 1 topic-stage each = 2 topic entries
    assert len(topic_entries) == 2
    assert {e.get("topic_index") for e in topic_entries} == {0, 1}
    assert all(e["stage"] == "_fake_writer" for e in topic_entries)


def test_run_stage_log_persists_cost_and_tokens_for_agent_stage(tmp_path: Path):
    """Agent-stage entries carry cost_usd and tokens; deterministic stages
    omit those keys. Closes the gap surfaced in
    SMOKE-POST-POLISH-2026-05-02.md cost-verification step."""
    from src.agent_stages import _AgentStageBase

    class _MeteredAgent:
        """Mimics the Agent contract for cost/token accumulation."""

        def __init__(self, name: str, cost_per_call: float, tokens_per_call: int) -> None:
            self.name = name
            self._cost_per_call = cost_per_call
            self._tokens_per_call = tokens_per_call
            self.last_cost_usd: float = 0.0
            self.last_tokens: int = 0

        def reset_call_metrics(self) -> None:
            self.last_cost_usd = 0.0
            self.last_tokens = 0

        async def run(self, *args: Any, **kwargs: Any):
            self.last_cost_usd += self._cost_per_call
            self.last_tokens += self._tokens_per_call
            return None

    class _FakeAgentTopicStage(_AgentStageBase):
        stage_kind = "topic"
        reads = ("editor_selected_topic",)
        writes = ("writer_article",)
        agent_role = "metered"

        def __init__(self, agent: _MeteredAgent) -> None:
            self.agent = agent

        async def __call__(
            self, topic_bus: TopicBus, run_bus: RunBusReadOnly
        ) -> TopicBus:
            await self.agent.run()
            await self.agent.run()
            return topic_bus.model_copy(
                update={"writer_article": WriterArticle(headline="h", summary="s", body="b")}
            )

    metered = _MeteredAgent("metered", cost_per_call=0.0123, tokens_per_call=1234)
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_FakeAgentTopicStage(metered)],
        output_dir=tmp_path,
        skip_render=True,
        skip_finalize=True,
    )
    rb = asyncio.run(runner.run())

    state_dir = tmp_path / rb.run_date / "_state" / rb.run_id
    jsonl_path = state_dir / "run_stage_log.jsonl"
    entries = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    agent_entries = [e for e in entries if e["stage"] == "_FakeAgentTopicStage"]
    assert len(agent_entries) == 2, f"expected one agent entry per topic; got {agent_entries}"
    for entry in agent_entries:
        # Two run() calls per stage execution × cost_per_call=0.0123
        assert entry["cost_usd"] == pytest.approx(0.0246, abs=1e-9)
        assert entry["tokens"] == 2468
        # Reset between topics: each topic's entry reflects only its own calls
        # (not cumulative across topics). The accumulator is zeroed by the
        # runner before each stage execution.

    # Deterministic stages must NOT carry the keys
    deterministic_entries = [e for e in entries if e["stage"] in {"_fake_init", "_fake_curator", "_fake_select"}]
    assert deterministic_entries, "expected deterministic stages in log"
    for entry in deterministic_entries:
        assert "cost_usd" not in entry, f"deterministic stage leaked cost_usd: {entry}"
        assert "tokens" not in entry, f"deterministic stage leaked tokens: {entry}"


def test_stage_label_function():
    assert _stage_label(_fake_init) == "_fake_init"


def test_stage_label_class_instance():
    class _Pseudo:
        async def __call__(self, run_bus):  # pragma: no cover
            return run_bus

    assert _stage_label(_Pseudo()) == "_Pseudo"


# ---------------------------------------------------------------------------
# Extensions: topic_filter, max_produce, name helpers (V2-09 prereqs)
# ---------------------------------------------------------------------------


def test_runner_topic_filter_skips_other_topics(tmp_path: Path):
    """--topic 2 → only TopicBus index 1 runs through topic-stages."""
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
        topic_filter=2,
    )
    rb = asyncio.run(runner.run())
    statuses = {m["topic_id"]: m["status"] for m in rb.run_topic_manifest}
    assert statuses == {"topic-001": "skipped", "topic-002": "success"}
    # Only the selected topic gets rendered to disk
    assert not (tmp_path / rb.run_date / "slug-001.json").exists()
    assert (tmp_path / rb.run_date / "slug-002.json").exists()


def test_runner_topic_filter_writer_runs_only_for_selected_topic(tmp_path: Path):
    runner = PipelineRunner(
        run_stages=[_fake_init, _fake_curator, _fake_select],
        topic_stages=[_fake_writer],
        output_dir=tmp_path,
        topic_filter=1,
        skip_render=True,
        skip_finalize=True,
    )
    asyncio.run(runner.run())
    # topic 0 ran, topic 1 was skipped → its writer_article stays empty default
    assert runner.topic_buses[0].writer_article.headline == "H topic-001"
    assert runner.topic_buses[1].writer_article.headline == ""
    assert runner._topic_status == ["success", "skipped"]


def test_build_production_stages_max_produce_threads_to_init_run(tmp_path: Path):
    """build_production_stages(max_produce=N) produces an init_run that
    sets RunBus.max_produce to N."""
    agents = _fake_agent_dict(_PRODUCTION_AGENTS)
    run_stages, _, _ = build_production_stages(
        agents, max_produce=7, output_dir=tmp_path
    )
    init_stage = run_stages[0]
    rb = asyncio.run(init_stage(RunBus()))
    assert rb.max_produce == 7
    assert rb.run_variant == "production"


def test_build_hydrated_stages_max_produce_threads_to_init_run(tmp_path: Path):
    agents = _fake_agent_dict(_HYDRATED_AGENTS)
    run_stages, _, _ = build_hydrated_stages(
        agents, max_produce=2, output_dir=tmp_path
    )
    init_stage = run_stages[0]
    rb = asyncio.run(init_stage(RunBus()))
    assert rb.max_produce == 2
    assert rb.run_variant == "hydrated"


def test_production_stage_names_matches_builder_output():
    agents = _fake_agent_dict(_PRODUCTION_AGENTS)
    runs, topics, _ = build_production_stages(agents)
    expected = [_stage_label(s) for s in runs + topics]
    assert production_stage_names() == expected


def test_hydrated_stage_names_matches_builder_first_occurrence():
    """Static name list dedupes mirror_perspective_synced (which appears
    twice in the hydrated stage list)."""
    agents = _fake_agent_dict(_HYDRATED_AGENTS)
    runs, topics, _ = build_hydrated_stages(agents)
    full = [_stage_label(s) for s in runs + topics]
    # Static list is the deduped order-preserving first-occurrence sequence
    seen: set = set()
    expected: list = []
    for name in full:
        if name == "mirror_perspective_synced" and name in seen:
            continue
        expected.append(name)
        seen.add(name)
    assert hydrated_stage_names() == expected
