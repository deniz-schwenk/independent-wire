"""Tests for the V2 stage interface (src/stage.py).

Ten invariants per TASK-V2-02 §4 plus a small set of defensive checks.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from src.bus import RunBus, RunBusReadOnly, TopicBus
from src.stage import (
    StageError,
    StagePostconditionError,
    StagePreconditionError,
    StageReadOnlyViolationError,
    get_stage_meta,
    run_stage_def,
    topic_stage_def,
    validate_postconditions,
    validate_preconditions,
)


# ---------------------------------------------------------------------------
# Fixture stages
# ---------------------------------------------------------------------------


@run_stage_def(reads=("curator_topics",), writes=("editor_assignments",))
async def noop_run_stage(run_bus: RunBus) -> RunBus:
    """Run-stage fixture: writes a non-empty editor_assignments."""
    run_bus.editor_assignments = [{"id": "tp-001", "title": "x"}]
    return run_bus


@topic_stage_def(
    reads=("perspective_clusters",),
    writes=("perspective_missing_positions",),
)
async def noop_topic_stage(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Topic-stage fixture: writes a non-empty perspective_missing_positions."""
    topic_bus.perspective_missing_positions = [{"voice": "smallholder farmers"}]
    return topic_bus


@run_stage_def(reads=(), writes=("run_id",))
async def dummy_set_run_id(run_bus: RunBus) -> RunBus:
    """Minimal run-stage that sets run_id."""
    run_bus.run_id = "run-abc-123"
    return run_bus


@run_stage_def(reads=(), writes=("run_id",))
async def silent_run_stage(run_bus: RunBus) -> RunBus:
    """Declares a write but does not perform it — must trip post-validation."""
    return run_bus


@topic_stage_def(reads=(), writes=("qa_corrected_article",))
async def silent_qa_topic_stage(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Declares writing qa_corrected_article but emits nothing — must pass
    post-validation because qa_corrected_article has mirrors_from metadata."""
    return topic_bus


@run_stage_def(reads=(), writes=("previous_coverage",))
async def silent_optional_write_run_stage(run_bus: RunBus) -> RunBus:
    """Declares writing previous_coverage but leaves it at the empty default.
    Must pass post-validation because previous_coverage has
    optional_write=True metadata (legitimately empty on first-ever run)."""
    return run_bus


@run_stage_def(reads=("nonexistent_slot",), writes=())
async def stage_with_typo_in_reads(run_bus: RunBus) -> RunBus:
    return run_bus


@topic_stage_def(reads=(), writes=())
async def stage_assigns_to_proxy(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Topic-stage that tries to assign a field on the read-only proxy."""
    run_bus.run_id = "tampered"  # type: ignore[misc]
    return topic_bus


@topic_stage_def(reads=(), writes=())
async def stage_inplace_mutates_proxy(
    topic_bus: TopicBus, run_bus: RunBusReadOnly
) -> TopicBus:
    """Topic-stage that does in-place mutation on a proxy list — silently
    accepted by Pydantic frozen-model semantics; caught by post-validation."""
    run_bus.curator_topics.append({"injected": True})
    return topic_bus


# ---------------------------------------------------------------------------
# 1. Stage metadata discovery
# ---------------------------------------------------------------------------


def test_run_stage_metadata_is_discoverable():
    meta = get_stage_meta(noop_run_stage)
    assert meta.name == "noop_run_stage"
    assert meta.kind == "run"
    assert meta.reads == ("curator_topics",)
    assert meta.writes == ("editor_assignments",)


def test_topic_stage_metadata_is_discoverable():
    meta = get_stage_meta(noop_topic_stage)
    assert meta.name == "noop_topic_stage"
    assert meta.kind == "topic"
    assert meta.reads == ("perspective_clusters",)
    assert meta.writes == ("perspective_missing_positions",)


def test_get_stage_meta_raises_on_undecorated_callable():
    async def plain(run_bus: RunBus) -> RunBus:
        return run_bus

    with pytest.raises(StageError, match="no stage metadata"):
        get_stage_meta(plain)


def test_decorator_rejects_sync_function():
    with pytest.raises(TypeError, match="async def"):

        @run_stage_def(reads=(), writes=())
        def sync_stage(run_bus: RunBus) -> RunBus:  # type: ignore[misc]
            return run_bus


# ---------------------------------------------------------------------------
# 2 + 3. Pre-condition validator
# ---------------------------------------------------------------------------


def test_validate_preconditions_passes_for_real_slot():
    rb = RunBus()
    validate_preconditions(noop_run_stage, rb)  # curator_topics exists on RunBus


def test_validate_preconditions_raises_on_missing_slot():
    rb = RunBus()
    with pytest.raises(StagePreconditionError) as exc:
        validate_preconditions(stage_with_typo_in_reads, rb)
    assert "stage_with_typo_in_reads" in str(exc.value)
    assert "nonexistent_slot" in str(exc.value)


def test_validate_preconditions_rejects_mismatched_bus_type():
    """Topic-stage validated against a RunBus → StageError (not Precondition)."""
    rb = RunBus()
    with pytest.raises(StageError, match="expects TopicBus"):
        validate_preconditions(noop_topic_stage, rb)


# ---------------------------------------------------------------------------
# 4 + 5. Post-condition validator — happy + failing path
# ---------------------------------------------------------------------------


def test_validate_postconditions_passes_when_writes_populated():
    rb_before = RunBus()
    rb_after = rb_before.model_copy(deep=True)
    rb_after.run_id = "run-abc-123"
    validate_postconditions(dummy_set_run_id, rb_before, rb_after)


def test_validate_postconditions_raises_when_write_slot_left_empty():
    rb_before = RunBus()
    rb_after = rb_before.model_copy(deep=True)
    with pytest.raises(StagePostconditionError) as exc:
        validate_postconditions(silent_run_stage, rb_before, rb_after)
    assert "silent_run_stage" in str(exc.value)
    assert "run_id" in str(exc.value)


# ---------------------------------------------------------------------------
# 6. Mirror-target exception
# ---------------------------------------------------------------------------


def test_validate_postconditions_allows_empty_mirror_target_slot():
    """qa_corrected_article has mirrors_from=writer_article; a stage that
    declares writing it but leaves it empty is legitimate (mirror stage will
    fill it). No exception expected."""
    tb_before = TopicBus()
    tb_after = tb_before.model_copy(deep=True)
    rb_before = RunBus().as_readonly()
    rb_after = RunBus().as_readonly()
    validate_postconditions(
        silent_qa_topic_stage,
        tb_before,
        tb_after,
        run_bus_before=rb_before,
        run_bus_after=rb_after,
    )


def test_validate_postconditions_allows_empty_optional_write_slot():
    """previous_coverage carries optional_write=True; a stage that declares
    writing it but leaves it at the empty default is legitimate (no prior
    runs in the last N days). No exception expected.

    Contrast with the mirror-target exception: the mirror exception relies
    on a downstream mirror_* stage filling the slot; the optional_write
    exception accepts that the slot may stay empty for the entire run."""
    rb_before = RunBus()
    rb_after = rb_before.model_copy(deep=True)
    # previous_coverage is still [] on rb_after — and that is fine.
    validate_postconditions(
        silent_optional_write_run_stage, rb_before, rb_after
    )


# ---------------------------------------------------------------------------
# 7. Read-only enforcement — direct field assignment
# ---------------------------------------------------------------------------


def test_topic_stage_field_assignment_to_proxy_raises_pydantic_error():
    """Pydantic frozen=True propagates a ValidationError on field assignment.
    The error originates in Pydantic, not in our validators — the assignment
    fails immediately, the topic-stage cannot complete."""
    from pydantic import ValidationError

    tb = TopicBus()
    rb = RunBus().as_readonly()
    with pytest.raises(ValidationError):
        asyncio.run(stage_assigns_to_proxy(tb, rb))


# ---------------------------------------------------------------------------
# 8. Read-only enforcement — in-place mutation, post-call detection
# ---------------------------------------------------------------------------


def test_topic_stage_inplace_proxy_mutation_caught_by_post_validation():
    """Pydantic frozen=True does NOT block in-place list/dict mutation. The
    deep-copy in as_readonly() isolates the source RunBus from harm, but the
    mutation is silent. Post-validation compares snapshots and raises."""
    rb = RunBus()
    rb.curator_topics = [{"id": "topic-001"}]

    tb = TopicBus()
    proxy = rb.as_readonly()
    proxy_before_snapshot = rb.as_readonly()

    asyncio.run(stage_inplace_mutates_proxy(tb, proxy))

    # The actual RunBus is unchanged — deep-copy isolation from V2-01 holds.
    assert rb.curator_topics == [{"id": "topic-001"}]

    # The proxy was mutated in place; compare the post-call proxy against the
    # before-snapshot.
    with pytest.raises(StageReadOnlyViolationError) as exc:
        validate_postconditions(
            stage_inplace_mutates_proxy,
            tb,
            tb,
            run_bus_before=proxy_before_snapshot,
            run_bus_after=proxy,
        )
    assert "stage_inplace_mutates_proxy" in str(exc.value)


def test_topic_stage_post_validation_requires_proxy_snapshots():
    """A topic-stage post-call must receive proxy before/after snapshots so
    read-only enforcement can run. silent_qa_topic_stage is used because its
    write slot is a mirror target (no empty-write trip), so the missing-
    snapshot check is reached first."""
    tb = TopicBus()
    with pytest.raises(StageError, match="run_bus_before and run_bus_after"):
        validate_postconditions(silent_qa_topic_stage, tb, tb)


# ---------------------------------------------------------------------------
# 9. Stage signature shape
# ---------------------------------------------------------------------------


def test_run_stage_signature_shape():
    """`from __future__ import annotations` defers annotation evaluation to
    strings — use typing.get_type_hints to resolve them to actual types."""
    import typing

    sig = inspect.signature(noop_run_stage)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "run_bus"

    hints = typing.get_type_hints(noop_run_stage)
    assert hints["run_bus"] is RunBus
    assert hints["return"] is RunBus
    assert inspect.iscoroutinefunction(noop_run_stage)


def test_topic_stage_signature_shape():
    import typing

    sig = inspect.signature(noop_topic_stage)
    params = list(sig.parameters.values())
    assert len(params) == 2
    assert params[0].name == "topic_bus"
    assert params[1].name == "run_bus"

    hints = typing.get_type_hints(noop_topic_stage)
    assert hints["topic_bus"] is TopicBus
    assert hints["run_bus"] is RunBusReadOnly
    assert hints["return"] is TopicBus
    assert inspect.iscoroutinefunction(noop_topic_stage)


# ---------------------------------------------------------------------------
# 10. Async dispatch + validators integrate cleanly
# ---------------------------------------------------------------------------


def test_run_stage_full_async_validate_cycle():
    """End-to-end: pre-validate, await the stage, post-validate."""

    async def cycle() -> RunBus:
        rb = RunBus()
        validate_preconditions(dummy_set_run_id, rb)
        rb_before = rb.model_copy(deep=True)
        rb_after = await dummy_set_run_id(rb)
        validate_postconditions(dummy_set_run_id, rb_before, rb_after)
        return rb_after

    rb_after = asyncio.run(cycle())
    assert rb_after.run_id == "run-abc-123"


def test_topic_stage_full_async_validate_cycle():
    """End-to-end for topic-stages including read-only check on the proxy."""

    async def cycle() -> TopicBus:
        rb = RunBus()
        rb.run_id = "run-001"
        rb.run_date = "2026-04-30"

        tb = TopicBus()
        validate_preconditions(noop_topic_stage, tb)

        tb_before = tb.model_copy(deep=True)
        proxy_before = rb.as_readonly()
        proxy_for_call = rb.as_readonly()
        tb_after = await noop_topic_stage(tb, proxy_for_call)

        validate_postconditions(
            noop_topic_stage,
            tb_before,
            tb_after,
            run_bus_before=proxy_before,
            run_bus_after=proxy_for_call,
        )
        return tb_after

    tb_after = asyncio.run(cycle())
    assert tb_after.perspective_missing_positions == [
        {"voice": "smallholder farmers"}
    ]


# ---------------------------------------------------------------------------
# Defensive checks
# ---------------------------------------------------------------------------


def test_validate_postconditions_rejects_wrong_bus_type():
    rb = RunBus()
    tb = TopicBus()
    with pytest.raises(StageError, match="expected RunBus"):
        validate_postconditions(dummy_set_run_id, rb, tb)


def test_validate_postconditions_topic_requires_readonly_proxies():
    tb = TopicBus()
    with pytest.raises(StageError, match="RunBusReadOnly"):
        # Pass mutable RunBus instead of RunBusReadOnly proxies.
        validate_postconditions(
            silent_qa_topic_stage,
            tb,
            tb,
            run_bus_before=RunBus(),  # type: ignore[arg-type]
            run_bus_after=RunBus(),  # type: ignore[arg-type]
        )


def test_validate_postconditions_rejects_writes_typo():
    """A stage whose writes name a non-field is caught at post-validation."""

    @run_stage_def(reads=(), writes=("nope_not_a_slot",))
    async def stage_with_bad_write(run_bus: RunBus) -> RunBus:
        return run_bus

    rb = RunBus()
    with pytest.raises(StagePostconditionError, match="nope_not_a_slot"):
        validate_postconditions(stage_with_bad_write, rb, rb)
