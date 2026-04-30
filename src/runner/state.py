"""Runner state-persistence helpers.

The PipelineRunner persists Bus snapshots to disk after every stage so
that ``--from STAGE --reuse RUN_ID`` can resume from any earlier stage at
~€0.10 instead of paying the full pipeline cost.

On-disk layout (per task §3.5)::

    output_dir/{run_date}/_state/{run_id}/
      run_bus.json                              # latest RunBus snapshot
      run_bus.{stage_name}.json                 # per-stage RunBus snapshot
      topic_buses.json                          # latest TopicBus list
      topic_buses.{stage_name}.{idx}.json       # per-stage per-topic snapshot
      run_stage_log.jsonl                       # append-only log

Snapshots are Pydantic ``model_dump_json`` outputs; loading round-trips
via ``model_validate_json``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Optional

from src.bus import RunBus, TopicBus
from src.stage import StageInputError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _state_dir(output_dir: Path, run_date: str, run_id: str) -> Path:
    return output_dir / run_date / "_state" / run_id


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# RunBus snapshots
# ---------------------------------------------------------------------------


def save_run_bus_snapshot(
    run_bus: RunBus, output_dir: Path, stage_name: str
) -> Path:
    """Write a RunBus snapshot to disk after the named stage completed.

    Writes both ``run_bus.json`` (latest) and ``run_bus.{stage_name}.json``
    (per-stage), so reuse can target any earlier stage. Returns the
    per-stage path for testability.
    """
    if not run_bus.run_date or not run_bus.run_id:
        raise StageInputError(
            "save_run_bus_snapshot: run_bus.run_date / run_bus.run_id "
            "must be populated (call init_run first)"
        )
    state_dir = _state_dir(output_dir, run_bus.run_date, run_bus.run_id)
    _ensure_dir(state_dir)
    payload = run_bus.model_dump_json(indent=2)
    latest = state_dir / "run_bus.json"
    per_stage = state_dir / f"run_bus.{stage_name}.json"
    latest.write_text(payload, encoding="utf-8")
    per_stage.write_text(payload, encoding="utf-8")
    return per_stage


def load_run_bus_snapshot(
    output_dir: Path, run_id: str, run_date: str, stage_name: str
) -> RunBus:
    """Load the RunBus snapshot written immediately after ``stage_name``
    completed.

    The runner pairs this with stage-list index arithmetic: to resume
    execution at ``from_stage``, the runner loads the snapshot whose
    ``stage_name`` is the run-stage immediately preceding ``from_stage``.
    """
    state_dir = _state_dir(output_dir, run_date, run_id)
    path = state_dir / f"run_bus.{stage_name}.json"
    if not path.exists():
        raise StageInputError(
            f"load_run_bus_snapshot: {path} missing — was the prior run "
            f"cut short before {stage_name!r} ran?"
        )
    return RunBus.model_validate_json(path.read_text(encoding="utf-8"))


def load_run_bus_latest(
    output_dir: Path, run_id: str, run_date: str
) -> RunBus:
    """Load the latest RunBus (``run_bus.json``)."""
    state_dir = _state_dir(output_dir, run_date, run_id)
    path = state_dir / "run_bus.json"
    if not path.exists():
        raise StageInputError(
            f"load_run_bus_latest: {path} missing"
        )
    return RunBus.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# TopicBus collection snapshots
# ---------------------------------------------------------------------------


def save_topic_bus_snapshot(
    topic_bus: TopicBus,
    output_dir: Path,
    run_date: str,
    run_id: str,
    stage_name: str,
    topic_index: int,
) -> Path:
    """Write a TopicBus snapshot to disk after the named topic-stage ran."""
    state_dir = _state_dir(output_dir, run_date, run_id)
    _ensure_dir(state_dir)
    path = state_dir / f"topic_buses.{stage_name}.{topic_index}.json"
    path.write_text(topic_bus.model_dump_json(indent=2), encoding="utf-8")
    return path


def save_topic_bus_collection(
    topic_buses: Iterable[TopicBus],
    output_dir: Path,
    run_date: str,
    run_id: str,
) -> Path:
    """Write the full TopicBus list as a single ``topic_buses.json`` file.

    Overwritten after each topic-stage iteration so a reuse can pick up
    the collection at the latest point regardless of how far each topic
    has progressed.
    """
    state_dir = _state_dir(output_dir, run_date, run_id)
    _ensure_dir(state_dir)
    path = state_dir / "topic_buses.json"
    payload = [tb.model_dump(mode="json") for tb in topic_buses]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_topic_bus_collection(
    output_dir: Path, run_id: str, run_date: str
) -> list[TopicBus]:
    """Load the latest TopicBus list."""
    state_dir = _state_dir(output_dir, run_date, run_id)
    path = state_dir / "topic_buses.json"
    if not path.exists():
        raise StageInputError(
            f"load_topic_bus_collection: {path} missing"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise StageInputError(
            f"load_topic_bus_collection: expected JSON array in {path}, "
            f"got {type(raw).__name__}"
        )
    return [TopicBus.model_validate(item) for item in raw]


def load_topic_bus_per_stage_snapshots(
    output_dir: Path,
    run_id: str,
    run_date: str,
    stage_name: str,
    topic_count: int,
) -> list[TopicBus]:
    """Load per-topic snapshots written immediately after ``stage_name``.

    Reads ``topic_buses.{stage_name}.{idx}.json`` for ``idx in
    range(topic_count)``. Falls back to the latest collection
    (``topic_buses.json``) when per-stage snapshots are missing — covers
    the first topic-stage of any reuse, where only the post-Phase-B
    collection exists.
    """
    state_dir = _state_dir(output_dir, run_date, run_id)
    per_stage_paths = [
        state_dir / f"topic_buses.{stage_name}.{i}.json"
        for i in range(topic_count)
    ]
    if all(p.exists() for p in per_stage_paths):
        return [
            TopicBus.model_validate_json(p.read_text(encoding="utf-8"))
            for p in per_stage_paths
        ]
    return load_topic_bus_collection(output_dir, run_id, run_date)


# ---------------------------------------------------------------------------
# Append-only stage-log
# ---------------------------------------------------------------------------


def append_stage_log(
    output_dir: Path,
    run_date: str,
    run_id: str,
    entry: dict,
) -> Path:
    """Append one JSONL row to ``run_stage_log.jsonl``."""
    state_dir = _state_dir(output_dir, run_date, run_id)
    _ensure_dir(state_dir)
    path = state_dir / "run_stage_log.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return path


__all__ = [
    "append_stage_log",
    "load_run_bus_latest",
    "load_run_bus_snapshot",
    "load_topic_bus_collection",
    "load_topic_bus_per_stage_snapshots",
    "save_run_bus_snapshot",
    "save_topic_bus_collection",
    "save_topic_bus_snapshot",
]
