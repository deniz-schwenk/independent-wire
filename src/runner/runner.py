"""V2 stage-list-driven pipeline runner.

Replaces V1's ``Pipeline`` / ``PipelineHydrated`` class hierarchy with a
single generic runner. The variant is encoded entirely in the stage list
that is passed to the runner — see :mod:`src.runner.stage_lists`.

Phases (per task §3.3):

A. Run-stages on the RunBus (sequential).
B. Construct TopicBuses from ``run_bus.selected_assignments``.
C. Topic-stages on each TopicBus (serial per TopicBus, ARCH §5.4).
D. Post-run stages: render every successful TopicBus, then ``finalize_run``
   to record the run manifest.

Per-topic failure isolation: a topic-stage exception marks that TopicBus
as failed and the runner continues with the next TopicBus. Failed
TopicBuses are excluded from render but appear in
``run_bus.run_topic_manifest`` with ``status="failed"``.
"""

from __future__ import annotations

import inspect
import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from src.bus import RunBus, RunBusReadOnly, TopicBus
from src.render import render_internal_debug, render_tp_public
from src.stage import (
    StageError,
    get_stage_meta,
    validate_postconditions,
    validate_preconditions,
)
from src.stages import make_finalize_run, make_topic_bus
from src.runner.state import (
    append_stage_log,
    load_run_bus_snapshot,
    load_topic_bus_collection,
    load_topic_bus_per_stage_snapshots,
    save_run_bus_snapshot,
    save_topic_bus_collection,
    save_topic_bus_snapshot,
)

logger = logging.getLogger(__name__)


def _reset_agent_metrics(stage: Any) -> None:
    """Zero per-stage cost/token accumulators on the wrapper's agent, if any.

    Agent-stage wrappers carry `self.agent`. Deterministic stages don't —
    `getattr` with default makes this a no-op for them.
    """
    agent = getattr(stage, "agent", None)
    reset = getattr(agent, "reset_call_metrics", None)
    if callable(reset):
        reset()


def _collect_agent_metrics(stage: Any) -> dict:
    """Read accumulated cost/tokens off the wrapper's agent.

    Returns ``{"cost_usd": float, "tokens": int}`` for agent-stages and
    ``{}`` for deterministic stages — keys are omitted from the log entry
    rather than emitted as zeros, so a deterministic-stage row stays
    distinguishable from an agent-stage row that happened to have no
    measurable cost (e.g. provider failed to report usage).
    """
    agent = getattr(stage, "agent", None)
    if agent is None:
        return {}
    cost = getattr(agent, "last_cost_usd", None)
    tokens = getattr(agent, "last_tokens", None)
    if cost is None and tokens is None:
        return {}
    return {
        "cost_usd": round(float(cost or 0.0), 6),
        "tokens": int(tokens or 0),
    }


# ---------------------------------------------------------------------------
# Stage-label resolution
# ---------------------------------------------------------------------------


def _stage_label(stage: Any) -> str:
    """Return the canonical label for a stage.

    For decorator-stamped functions and class instances stamped via
    ``_AgentStageBase.__init_subclass__``, ``get_stage_meta(stage).name``
    returns the canonical name (function ``__name__`` or class
    ``__name__``). For internal post-run handlers without metadata (eg
    :class:`RenderStage`), falls back to ``type(stage).__name__``.
    """
    try:
        return get_stage_meta(stage).name
    except StageError:
        return type(stage).__name__


def _index_of(stages: list, name: str) -> int:
    """Return the *first* index matching ``name``. Returns ``-1`` if absent.

    The hydrated variant has ``mirror_perspective_synced`` twice; for
    ``--from`` matching we cut at the first occurrence so the second
    instance still runs.
    """
    for i, stage in enumerate(stages):
        if _stage_label(stage) == name:
            return i
    return -1


# ---------------------------------------------------------------------------
# Post-run handlers
# ---------------------------------------------------------------------------


class RenderStage:
    """Render every successful TopicBus to disk.

    Writes ``output_dir/{run_date}/{topic_slug}.json`` (TP-public) and
    ``output_dir/{run_date}/_debug/{topic_slug}.json`` (internal debug)
    per TopicBus. Failed TopicBuses are skipped — their state is captured
    in ``run_topic_manifest`` instead.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)

    async def __call__(
        self,
        run_bus: RunBus,
        topic_buses: list[TopicBus],
        statuses: list[str],
    ) -> RunBus:
        run_date = run_bus.run_date or datetime.now(timezone.utc).date().isoformat()
        public_dir = self.output_dir / run_date
        debug_dir = public_dir / "_debug"
        public_dir.mkdir(parents=True, exist_ok=True)
        debug_dir.mkdir(parents=True, exist_ok=True)
        for tb, status in zip(topic_buses, statuses):
            if status in ("failed", "skipped"):
                continue
            slug = tb.editor_selected_topic.topic_slug or tb.editor_selected_topic.id
            public_path = public_dir / f"{slug}.json"
            debug_path = debug_dir / f"{slug}.json"
            public_path.write_text(
                json.dumps(render_tp_public(tb, run_bus), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            debug_path.write_text(
                json.dumps(render_internal_debug(tb, run_bus), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return run_bus


class FinalizeRunStage:
    """Build ``run_topic_manifest`` from runner-tracked per-TopicBus data."""

    async def __call__(
        self,
        run_bus: RunBus,
        topic_buses: list[TopicBus],
        statuses: list[str],
        stages_completed: list[list[str]],
    ) -> RunBus:
        entries = []
        for tb, status, completed in zip(topic_buses, statuses, stages_completed):
            entries.append(
                {
                    "topic_id": tb.editor_selected_topic.id,
                    "topic_slug": tb.editor_selected_topic.topic_slug,
                    "status": status,
                    "stages_completed": list(completed),
                }
            )
        finalize = make_finalize_run(entries)
        return await finalize(run_bus)


# ---------------------------------------------------------------------------
# PipelineRunner
# ---------------------------------------------------------------------------


class PipelineRunner:
    """Stage-list-driven V2 pipeline runner."""

    def __init__(
        self,
        run_stages: list,
        topic_stages: list,
        post_run_stages: Optional[list] = None,
        *,
        output_dir: Path,
        from_stage: Optional[str] = None,
        to_stage: Optional[str] = None,
        reuse_run_id: Optional[str] = None,
        reuse_run_date: Optional[str] = None,
        topic_filter: Optional[int] = None,
        skip_render: bool = False,
        skip_finalize: bool = False,
    ) -> None:
        self.run_stages = list(run_stages)
        self.topic_stages = list(topic_stages)
        self.post_run_stages = list(post_run_stages or [])
        self.output_dir = Path(output_dir)
        self.from_stage = from_stage
        self.to_stage = to_stage
        self.reuse_run_id = reuse_run_id
        self.reuse_run_date = reuse_run_date
        self.topic_filter = topic_filter  # 1-based index; None = all topics
        self.skip_render = skip_render
        self.skip_finalize = skip_finalize

        self.topic_buses: list[TopicBus] = []
        self._topic_status: list[str] = []
        self._topic_stages_completed: list[list[str]] = []
        self._stop_requested = False
        self._current_run_id: Optional[str] = None
        self._current_run_date: Optional[str] = None

        if self.from_stage:
            in_run = _index_of(self.run_stages, self.from_stage) >= 0
            in_topic = _index_of(self.topic_stages, self.from_stage) >= 0
            if not (in_run or in_topic):
                raise StageError(
                    f"PipelineRunner: from_stage={self.from_stage!r} matches "
                    f"no run-stage or topic-stage in the configured lists"
                )
            if (in_run or in_topic) and not (self.reuse_run_id and self.reuse_run_date):
                raise StageError(
                    "PipelineRunner: from_stage requires reuse_run_id and "
                    "reuse_run_date so prior snapshots can be loaded"
                )

    # -- Public entry point --------------------------------------------------

    async def run(self) -> RunBus:
        """Execute the configured stage lists and return the finalised RunBus."""
        run_bus = await self._phase_a_run_stages()
        if self._stop_requested:
            return run_bus

        topic_buses = await self._phase_b_construct_topic_buses(run_bus)
        self.topic_buses = topic_buses
        self._topic_status = ["pending"] * len(topic_buses)
        self._topic_stages_completed = [[] for _ in topic_buses]

        run_bus = await self._phase_c_topic_stages(run_bus)

        for i in range(len(self._topic_status)):
            if self._topic_status[i] == "pending":
                self._topic_status[i] = "success"

        if self._stop_requested:
            return run_bus

        run_bus = await self._phase_d_post_run(run_bus)
        return run_bus

    # -- Phase A -------------------------------------------------------------

    async def _phase_a_run_stages(self) -> RunBus:
        from_index_run = (
            _index_of(self.run_stages, self.from_stage) if self.from_stage else -1
        )
        from_index_topic = (
            _index_of(self.topic_stages, self.from_stage) if self.from_stage else -1
        )

        if from_index_run > 0:
            prior_stage_name = _stage_label(self.run_stages[from_index_run - 1])
            run_bus = load_run_bus_snapshot(
                self.output_dir,
                self.reuse_run_id,
                self.reuse_run_date,
                prior_stage_name,
            )
            start_index = from_index_run
        elif from_index_topic >= 0:
            last_run_stage_name = _stage_label(self.run_stages[-1])
            run_bus = load_run_bus_snapshot(
                self.output_dir,
                self.reuse_run_id,
                self.reuse_run_date,
                last_run_stage_name,
            )
            start_index = len(self.run_stages)
        else:
            run_bus = RunBus()
            start_index = 0

        for i in range(start_index, len(self.run_stages)):
            stage = self.run_stages[i]
            name = _stage_label(stage)
            run_bus = await self._execute_run_stage(stage, run_bus, name)
            if self.to_stage and self.to_stage == name:
                logger.info("Runner: stopping after run-stage %s (--to)", name)
                self._stop_requested = True
                return run_bus
        return run_bus

    async def _execute_run_stage(
        self, stage: Any, run_bus: RunBus, name: str
    ) -> RunBus:
        validate_preconditions(stage, run_bus)
        before_dump = run_bus.model_dump()
        _reset_agent_metrics(stage)
        try:
            run_bus = await self._call_run_stage(stage, run_bus)
        except Exception as exc:
            self._log_stage(
                run_bus, name, "run", "failed",
                error=str(exc),
                **_collect_agent_metrics(stage),
            )
            raise
        validate_postconditions(
            stage,
            RunBus.model_validate(before_dump),
            run_bus,
        )
        self._current_run_id = run_bus.run_id or self._current_run_id
        self._current_run_date = run_bus.run_date or self._current_run_date
        run_bus = self._log_stage(
            run_bus, name, "run", "success",
            **_collect_agent_metrics(stage),
        )
        save_run_bus_snapshot(run_bus, self.output_dir, name)
        return run_bus

    @staticmethod
    async def _call_run_stage(stage: Any, run_bus: RunBus) -> RunBus:
        result = stage(run_bus)
        if inspect.isawaitable(result):
            return await result
        return result

    # -- Phase B -------------------------------------------------------------

    async def _phase_b_construct_topic_buses(
        self, run_bus: RunBus
    ) -> list[TopicBus]:
        from_index_topic = (
            _index_of(self.topic_stages, self.from_stage) if self.from_stage else -1
        )
        if from_index_topic >= 0:
            collection = load_topic_bus_collection(
                self.output_dir, self.reuse_run_id, self.reuse_run_date
            )
            if from_index_topic > 0:
                prior_stage_name = _stage_label(self.topic_stages[from_index_topic - 1])
                collection = load_topic_bus_per_stage_snapshots(
                    self.output_dir,
                    self.reuse_run_id,
                    self.reuse_run_date,
                    prior_stage_name,
                    len(collection),
                )
            return collection

        assignments = list(run_bus.selected_assignments or [])
        return [make_topic_bus(a, run_bus) for a in assignments]

    # -- Phase C -------------------------------------------------------------

    async def _phase_c_topic_stages(self, run_bus: RunBus) -> RunBus:
        from_index_topic = (
            _index_of(self.topic_stages, self.from_stage) if self.from_stage else -1
        )
        start_index = max(from_index_topic, 0)

        for topic_index, topic_bus in enumerate(self.topic_buses):
            if self.topic_filter is not None and topic_index != self.topic_filter - 1:
                # --topic N (1-based) — every TopicBus other than the Nth is
                # marked "skipped" and excluded from render + finalize.
                self._topic_status[topic_index] = "skipped"
                continue
            try:
                run_bus = await self._run_one_topic(
                    topic_index, topic_bus, run_bus, start_index
                )
            except _TopicSkipStop:
                self._stop_requested = True
                return run_bus
            except Exception as exc:
                self._topic_status[topic_index] = "failed"
                run_bus = self._log_stage(
                    run_bus,
                    f"topic-{topic_index}",
                    "topic",
                    "failed",
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                logger.warning(
                    "Runner: topic %d failed at stage; continuing with next topic",
                    topic_index,
                )
        return run_bus

    async def _run_one_topic(
        self,
        topic_index: int,
        topic_bus: TopicBus,
        run_bus: RunBus,
        start_index: int,
    ) -> RunBus:
        for stage_index in range(start_index, len(self.topic_stages)):
            stage = self.topic_stages[stage_index]
            name = _stage_label(stage)
            read_only = run_bus.as_readonly()
            expected_state = run_bus.as_readonly()
            validate_preconditions(stage, topic_bus)
            before_dump = topic_bus.model_dump()
            _reset_agent_metrics(stage)
            try:
                topic_bus = await self._call_topic_stage(stage, topic_bus, read_only)
            except Exception:
                raise
            validate_postconditions(
                stage,
                TopicBus.model_validate(before_dump),
                topic_bus,
                run_bus_before=expected_state,
                run_bus_after=read_only,
            )
            self.topic_buses[topic_index] = topic_bus
            self._topic_stages_completed[topic_index].append(name)
            save_topic_bus_snapshot(
                topic_bus,
                self.output_dir,
                run_bus.run_date,
                run_bus.run_id,
                name,
                topic_index,
            )
            save_topic_bus_collection(
                self.topic_buses,
                self.output_dir,
                run_bus.run_date,
                run_bus.run_id,
            )
            run_bus = self._log_stage(
                run_bus,
                name,
                "topic",
                "success",
                topic_index=topic_index,
                topic_slug=topic_bus.editor_selected_topic.topic_slug,
                **_collect_agent_metrics(stage),
            )
            if self.to_stage and self.to_stage == name:
                if topic_index == len(self.topic_buses) - 1:
                    raise _TopicSkipStop()
                return run_bus
        return run_bus

    @staticmethod
    async def _call_topic_stage(
        stage: Any, topic_bus: TopicBus, run_bus_ro: RunBusReadOnly
    ) -> TopicBus:
        result = stage(topic_bus, run_bus_ro)
        if inspect.isawaitable(result):
            return await result
        return result

    # -- Phase D -------------------------------------------------------------

    async def _phase_d_post_run(self, run_bus: RunBus) -> RunBus:
        if self.to_stage:
            in_topic = _index_of(self.topic_stages, self.to_stage) >= 0
            if in_topic:
                logger.info(
                    "Runner: --to %s cuts before post-run stages; skipping render+finalize",
                    self.to_stage,
                )
                return run_bus

        if not self.skip_render:
            render_stage = RenderStage(self.output_dir)
            await render_stage(run_bus, self.topic_buses, self._topic_status)
            run_bus = self._log_stage(run_bus, "render", "post_run", "success")

        if not self.skip_finalize:
            finalize_stage = FinalizeRunStage()
            run_bus = await finalize_stage(
                run_bus,
                self.topic_buses,
                self._topic_status,
                self._topic_stages_completed,
            )
            run_bus = self._log_stage(run_bus, "finalize_run", "post_run", "success")
            if run_bus.run_id and run_bus.run_date:
                save_run_bus_snapshot(run_bus, self.output_dir, "finalize_run")

        return run_bus

    # -- Logging helper ------------------------------------------------------

    def _log_stage(
        self,
        run_bus: Optional[RunBus],
        name: str,
        kind: str,
        status: str,
        **extra: Any,
    ) -> Optional[RunBus]:
        """Append a stage entry to disk JSONL and the in-memory Bus slot.

        Returns the updated ``run_bus`` (with the entry appended to
        ``run_stage_log``) so callers can thread the new state forward.
        Returns ``None`` if ``run_bus`` was ``None``. When ``run_id`` or
        ``run_date`` cannot be resolved (very early in a fresh run before
        ``init_run``), the disk write is skipped but the Bus-slot mirror
        is still applied so a valid ``run_bus`` always carries an
        observable in-memory log.
        """
        entry = {
            "stage": name,
            "kind": kind,
            "status": status,
            "ts": datetime.now(timezone.utc).isoformat(),
            **extra,
        }
        run_id = (run_bus.run_id if run_bus else None) or self.reuse_run_id or self._current_run_id
        run_date = (run_bus.run_date if run_bus else None) or self.reuse_run_date or self._current_run_date
        if run_id and run_date:
            try:
                append_stage_log(self.output_dir, run_date, run_id, entry)
            except Exception as exc:  # state-log is advisory — never crash the runner
                logger.debug("stage-log append failed: %s", exc)
        if run_bus is None:
            return None
        return run_bus.model_copy(
            update={"run_stage_log": [*run_bus.run_stage_log, entry]}
        )


class _TopicSkipStop(Exception):
    """Internal flow-control: --to matched and the last topic finished."""


__all__ = [
    "FinalizeRunStage",
    "PipelineRunner",
    "RenderStage",
    "_stage_label",
]
