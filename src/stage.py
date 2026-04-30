"""V2 pipeline stage interface — signatures, metadata, and validators.

Authoritative reference: docs/ARCH-V2-BUS-SCHEMA.md Section 5.3.

Two stage signatures:
- `run_stage(run_bus: RunBus) -> RunBus` — operates on the RunBus.
- `topic_stage(topic_bus: TopicBus, run_bus: RunBusReadOnly) -> TopicBus` —
  operates on a single TopicBus; receives a frozen, deep-copied RunBus proxy.

Both are async by convention so the runner can dispatch them uniformly.

Stages declare `reads` and `writes` slot lists via `@run_stage_def` /
`@topic_stage_def` decorators. The metadata is discoverable via
`get_stage_meta(stage)`; this module's validators consume it. The Pipeline
Runner (TASK-V2-10) imports the validators here.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any, Callable, Literal, Optional, Sequence

from pydantic import BaseModel

from src.bus import RunBus, RunBusReadOnly, TopicBus, is_empty

StageKind = Literal["run", "topic"]

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class StageError(Exception):
    """Parent for all stage-validation errors."""


class StagePreconditionError(StageError):
    """A declared input slot is not a field on the relevant bus."""


class StagePostconditionError(StageError):
    """A declared output slot is still empty on bus_after, and the slot is not
    a mirror-target (mirror-target slots are legitimately allowed to remain
    empty until the corresponding mirror stage runs)."""


class StageReadOnlyViolationError(StageError):
    """A topic-stage mutated its read-only RunBus proxy."""


class StageInputError(StageError):
    """A stage's external input (file on disk, etc.) is missing or unreadable.

    Distinct from StagePreconditionError: pre-conditions check Bus-slot presence,
    StageInputError flags external resources outside the Bus contract.
    """


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class StageMeta:
    name: str
    kind: StageKind
    reads: tuple[str, ...]
    writes: tuple[str, ...]


_STAGE_META_ATTR = "_stage_meta"


def _attach(target: Any, meta: StageMeta) -> Any:
    setattr(target, _STAGE_META_ATTR, meta)
    return target


def _check_async(func: Callable, kind: StageKind) -> None:
    if not inspect.iscoroutinefunction(func):
        raise TypeError(
            f"{kind}-stage {func.__name__!r} must be declared `async def`"
        )


def run_stage_def(
    *,
    reads: Sequence[str] = (),
    writes: Sequence[str] = (),
) -> Callable[[Callable], Callable]:
    """Mark an async function as a run-stage.

    Stamps `_stage_meta = StageMeta(kind="run", ...)` onto the function so the
    runner can introspect reads, writes, and dispatch shape.
    """

    def decorator(func: Callable) -> Callable:
        _check_async(func, "run")
        meta = StageMeta(
            name=func.__name__,
            kind="run",
            reads=tuple(reads),
            writes=tuple(writes),
        )
        return _attach(func, meta)

    return decorator


def topic_stage_def(
    *,
    reads: Sequence[str] = (),
    writes: Sequence[str] = (),
) -> Callable[[Callable], Callable]:
    """Mark an async function as a topic-stage.

    `reads` and `writes` are TopicBus slot names. Topic-stages may read run-
    scoped slots (run_id, run_date) from the read-only RunBus proxy; those
    reads are implicit and not declared in stage metadata.
    """

    def decorator(func: Callable) -> Callable:
        _check_async(func, "topic")
        meta = StageMeta(
            name=func.__name__,
            kind="topic",
            reads=tuple(reads),
            writes=tuple(writes),
        )
        return _attach(func, meta)

    return decorator


def get_stage_meta(stage: Any) -> StageMeta:
    """Return the StageMeta attached to a stage callable.

    Works for decorator-stamped functions and for class-based stages that
    expose `_stage_meta` on the class or instance.
    """
    meta = getattr(stage, _STAGE_META_ATTR, None)
    if meta is None and not inspect.isclass(stage):
        meta = getattr(type(stage), _STAGE_META_ATTR, None)
    if meta is None:
        raise StageError(
            f"{stage!r} has no stage metadata; missing @run_stage_def / "
            f"@topic_stage_def decorator?"
        )
    if not isinstance(meta, StageMeta):
        raise StageError(f"{stage!r}._stage_meta is not a StageMeta instance")
    return meta


# ---------------------------------------------------------------------------
# Bus-class lookup
# ---------------------------------------------------------------------------


def _bus_class_for(kind: StageKind) -> type[BaseModel]:
    return RunBus if kind == "run" else TopicBus


def _has_mirrors_from(model_cls: type[BaseModel], slot: str) -> bool:
    field = model_cls.model_fields.get(slot)
    if field is None:
        return False
    extra = field.json_schema_extra or {}
    if isinstance(extra, dict):
        return "mirrors_from" in extra
    return False


# ---------------------------------------------------------------------------
# Pre-condition validator
# ---------------------------------------------------------------------------


def validate_preconditions(stage: Any, bus: BaseModel) -> None:
    """Validate that every slot in `stage.reads` is a declared field on `bus`.

    Catches typos in stage metadata. Does NOT verify slot non-emptiness —
    legitimate emptiness is a per-pipeline-variant concern (e.g.
    `hydration_pre_dossier` is empty in the production variant).
    """
    meta = get_stage_meta(stage)
    expected_cls = _bus_class_for(meta.kind)
    if not isinstance(bus, expected_cls):
        raise StageError(
            f"stage {meta.name!r} (kind={meta.kind!r}) expects "
            f"{expected_cls.__name__}, got {type(bus).__name__}"
        )
    valid = expected_cls.model_fields
    for slot in meta.reads:
        if slot not in valid:
            raise StagePreconditionError(
                f"stage {meta.name!r} declares read slot {slot!r} which is "
                f"not a field on {expected_cls.__name__}"
            )


# ---------------------------------------------------------------------------
# Post-condition validator (writes + read-only enforcement)
# ---------------------------------------------------------------------------


def validate_postconditions(
    stage: Any,
    bus_before: BaseModel,
    bus_after: BaseModel,
    *,
    run_bus_before: Optional[RunBusReadOnly] = None,
    run_bus_after: Optional[RunBusReadOnly] = None,
) -> None:
    """Validate that the stage populated its declared writes (with the
    mirror-target exception) and, for topic-stages, that the read-only
    RunBus proxy was not mutated.

    For run-stages: only `stage`, `bus_before`, `bus_after` are required.
    For topic-stages: `run_bus_before` and `run_bus_after` are also required —
    both must be `RunBusReadOnly` snapshots taken immediately before and after
    the stage call. If they differ, the topic-stage mutated the proxy and
    `StageReadOnlyViolationError` is raised.

    The mirror-target exception (§3.4): a writes-slot may be empty after the
    stage iff its schema metadata declares `mirrors_from`. The corresponding
    `mirror_*` stage will fill it later.
    """
    meta = get_stage_meta(stage)
    expected_cls = _bus_class_for(meta.kind)
    if not isinstance(bus_after, expected_cls):
        raise StageError(
            f"stage {meta.name!r} (kind={meta.kind!r}) returned "
            f"{type(bus_after).__name__}, expected {expected_cls.__name__}"
        )
    if not isinstance(bus_before, expected_cls):
        raise StageError(
            f"stage {meta.name!r} bus_before snapshot is "
            f"{type(bus_before).__name__}, expected {expected_cls.__name__}"
        )

    # Writes must be non-empty unless the slot is a mirror target.
    for slot in meta.writes:
        if slot not in expected_cls.model_fields:
            raise StagePostconditionError(
                f"stage {meta.name!r} declares write slot {slot!r} which is "
                f"not a field on {expected_cls.__name__}"
            )
        if _has_mirrors_from(expected_cls, slot):
            continue
        if is_empty(getattr(bus_after, slot)):
            raise StagePostconditionError(
                f"stage {meta.name!r} promised to write {slot!r} but the slot "
                f"is empty on {expected_cls.__name__} after the stage ran"
            )

    # Read-only enforcement: topic-stage may not mutate its proxy.
    if meta.kind == "topic":
        if run_bus_before is None or run_bus_after is None:
            raise StageError(
                f"topic-stage {meta.name!r} post-validation requires both "
                f"run_bus_before and run_bus_after RunBusReadOnly snapshots"
            )
        if not isinstance(run_bus_before, RunBusReadOnly) or not isinstance(
            run_bus_after, RunBusReadOnly
        ):
            raise StageError(
                f"topic-stage {meta.name!r} run_bus snapshots must be "
                f"RunBusReadOnly instances"
            )
        if run_bus_before.model_dump() != run_bus_after.model_dump():
            raise StageReadOnlyViolationError(
                f"topic-stage {meta.name!r} mutated its read-only RunBus "
                f"proxy (in-place container mutation or otherwise). The "
                f"mutation was discarded by deep-copy isolation but the "
                f"intent is a programming error."
            )


__all__ = [
    "StageError",
    "StageInputError",
    "StageKind",
    "StageMeta",
    "StagePostconditionError",
    "StagePreconditionError",
    "StageReadOnlyViolationError",
    "get_stage_meta",
    "run_stage_def",
    "topic_stage_def",
    "validate_postconditions",
    "validate_preconditions",
]
