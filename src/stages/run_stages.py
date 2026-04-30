"""RunBus-scoped deterministic stages plus the generic mirror_stage helper.

Stages: init_run, fetch_findings, finalize_run.
Helper: mirror_stage (used by V2-03b topic-level mirror stages).

V1 reference for the deterministic logic: src/pipeline.py — specifically
`_load_feed_findings` (raw/{date}/feeds.json) and `_scan_previous_coverage`
(output/ walk over the last N days). Logic is ported to module-level
Bus-aware functions; class-method semantics (self.state, self.output_dir,
self._save_state) are not preserved.
"""

from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.bus import EditorAssignment, RunBus, RunBusReadOnly, TopicBus, is_empty
from src.stage import StageError, StageInputError, run_stage_def

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mirror helper
# ---------------------------------------------------------------------------


class MirrorMismatchError(StageError):
    """A mirror_stage call names slots that are not declared as a mirror pair
    in the bus's Pydantic schema metadata. Catches typos and accidental
    cross-slot copies."""


def mirror_stage(
    target_slot: str,
    source_slot: str,
    bus: BaseModel,
    *,
    granularity: Literal["slot", "element"] = "slot",
    identity_key: str = "id",
) -> None:
    """Fill `target_slot` from `source_slot`, idempotently.

    Validates the pair against the bus's Pydantic schema metadata: target
    must declare `mirrors_from = source_slot` in `json_schema_extra`. This
    rejects mirror calls between unrelated slots.

    Granularity:

    - `"slot"` (default, slot-level empty-then-fill, ARCH §3.3 (a)):
      copy the source value into target if `is_empty(target)`. No-op when
      target is populated — the agent's value wins.

    - `"element"` (per-element empty-then-fill, ARCH §3.3 (b)):
      walk the source list. For each source element: if a delta exists in
      the target list (matched by `identity_key`), apply the delta's fields
      on top of the source-element values. Otherwise, copy the source
      element verbatim. Result is a fully-populated list.

    `identity_key` defaults to `"id"`. If a slot needs a different key,
    extend this helper with explicit metadata in the bus schema later.
    """
    bus_cls = type(bus)
    if target_slot not in bus_cls.model_fields:
        raise MirrorMismatchError(
            f"target slot {target_slot!r} not a field on {bus_cls.__name__}"
        )
    if source_slot not in bus_cls.model_fields:
        raise MirrorMismatchError(
            f"source slot {source_slot!r} not a field on {bus_cls.__name__}"
        )

    extra = bus_cls.model_fields[target_slot].json_schema_extra or {}
    declared_source = extra.get("mirrors_from") if isinstance(extra, dict) else None
    if declared_source != source_slot:
        raise MirrorMismatchError(
            f"target slot {target_slot!r} declares mirrors_from="
            f"{declared_source!r}, not {source_slot!r}"
        )

    source_value = getattr(bus, source_slot)
    target_value = getattr(bus, target_slot)

    if granularity == "slot":
        if is_empty(target_value):
            setattr(bus, target_slot, _deep_copy_value(source_value))
        return

    if granularity == "element":
        if not isinstance(source_value, list) or not isinstance(target_value, list):
            raise MirrorMismatchError(
                f"element-granularity mirror requires list slots; got "
                f"source={type(source_value).__name__}, "
                f"target={type(target_value).__name__}"
            )
        deltas: dict[Any, dict] = {}
        for elem in target_value:
            if isinstance(elem, dict) and identity_key in elem:
                deltas[elem[identity_key]] = elem
        merged: list = []
        for src_elem in source_value:
            if not isinstance(src_elem, dict):
                merged.append(_deep_copy_value(src_elem))
                continue
            eid = src_elem.get(identity_key)
            if eid is not None and eid in deltas:
                combined = {**copy.deepcopy(src_elem), **copy.deepcopy(deltas[eid])}
                merged.append(combined)
            else:
                merged.append(copy.deepcopy(src_elem))
        setattr(bus, target_slot, merged)
        return

    raise ValueError(f"unknown granularity: {granularity!r}")


def _deep_copy_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_copy(deep=True)
    return copy.deepcopy(value)


# ---------------------------------------------------------------------------
# init_run
# ---------------------------------------------------------------------------


class RunInitConfig(BaseModel):
    """Configuration for `init_run`. The runner constructs a stage closure
    over this config; the stage callable itself is a pure async function."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    run_id_override: Optional[str] = None
    run_date_override: Optional[str] = None
    run_variant: str = "production"
    max_produce: Optional[int] = None
    output_dir: Path = Field(default_factory=lambda: Path("output"))
    previous_coverage_days: int = 7


def _new_run_id(date_str: str) -> str:
    """Run-id format `run-{date}-{8-char-hex}`. Matches the V1 state-file
    glob pattern (run-{date}-*.json) so legacy tooling can still discover
    V2 runs by date."""
    return f"run-{date_str}-{uuid.uuid4().hex[:8]}"


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _scan_previous_coverage(
    output_dir: Path, current_date: str, days: int = 7
) -> list[dict]:
    """Walk `output_dir` for date-named subdirs (last `days` days, excluding
    `current_date`); read each `tp-*.json`; project to a coverage record.

    Ported from V1 `Pipeline._scan_previous_coverage`. Same projection
    fields ({tp_id, date, headline, slug, summary}), same skip rules
    (no headline → drop), same sort (date descending).
    """
    try:
        current = datetime.strptime(current_date, "%Y-%m-%d")
    except ValueError:
        return []

    if not output_dir.exists():
        return []

    results: list[dict] = []
    for d in output_dir.iterdir():
        if not d.is_dir() or len(d.name) != 10:
            continue
        if d.name == current_date:
            continue
        try:
            dir_date = datetime.strptime(d.name, "%Y-%m-%d")
        except ValueError:
            continue
        if (current - dir_date).days > days or dir_date > current:
            continue

        for tp_path in d.glob("tp-*.json"):
            try:
                data = json.loads(tp_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError, OSError) as e:
                logger.warning("Could not read previous TP %s: %s", tp_path, e)
                continue
            article = data.get("article") or {}
            headline = article.get("headline") or ""
            if not headline:
                continue
            meta = data.get("metadata") or {}
            results.append(
                {
                    "tp_id": data.get("id") or "",
                    "date": meta.get("date") or d.name,
                    "headline": headline,
                    "slug": meta.get("topic_slug") or "",
                    "summary": article.get("summary") or "",
                }
            )

    results.sort(key=lambda r: r["date"], reverse=True)
    if results:
        date_dirs = len({r["date"] for r in results})
        logger.info(
            "Previous coverage: loaded %d TPs across %d days from %s",
            len(results),
            date_dirs,
            output_dir,
        )
    return results


def make_init_run(config: Optional[RunInitConfig] = None) -> Callable:
    """Build an `init_run` stage closing over the given config.

    Default config = `RunInitConfig()`. The default-config stage is exported
    as the module-level `init_run`.
    """
    cfg = config or RunInitConfig()

    @run_stage_def(
        reads=(),
        writes=(
            "run_id",
            "run_date",
            "run_variant",
            "max_produce",
            "previous_coverage",
        ),
    )
    async def init_run(run_bus: RunBus) -> RunBus:
        run_date = cfg.run_date_override or _today_iso()
        run_bus.run_date = run_date
        run_bus.run_id = cfg.run_id_override or _new_run_id(run_date)
        run_bus.run_variant = cfg.run_variant
        if cfg.max_produce is not None:
            run_bus.max_produce = cfg.max_produce
        run_bus.previous_coverage = _scan_previous_coverage(
            output_dir=cfg.output_dir,
            current_date=run_date,
            days=cfg.previous_coverage_days,
        )
        return run_bus

    return init_run


init_run = make_init_run()


# ---------------------------------------------------------------------------
# fetch_findings
# ---------------------------------------------------------------------------


def _load_feed_findings(raw_dir: Path, run_date: str) -> list[dict]:
    """Read `raw/{run_date}/feeds.json` and return the list of findings.

    Ported from V1 `Pipeline._load_feed_findings`. Differences from V1:
    - V1 returned [] on missing file; V2 raises StageInputError (per task §3.4).
      The runner decides how to handle (probably abort).
    - V1 silently swallowed JSONDecodeError; V2 re-raises wrapped in
      StageInputError so failures are loud.
    """
    feeds_path = raw_dir / run_date / "feeds.json"
    if not feeds_path.exists():
        raise StageInputError(
            f"fetch_findings: no feeds file at {feeds_path}. Run "
            f"`scripts/fetch_feeds.py` for {run_date} first."
        )
    try:
        data = json.loads(feeds_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError) as e:
        raise StageInputError(
            f"fetch_findings: could not read {feeds_path}: {e}"
        ) from e
    if not isinstance(data, list):
        raise StageInputError(
            f"fetch_findings: {feeds_path} must contain a JSON array, got "
            f"{type(data).__name__}"
        )
    logger.info("fetch_findings: loaded %d findings from %s", len(data), feeds_path)
    return data


def make_fetch_findings(raw_dir: Optional[Path] = None) -> Callable:
    rd = raw_dir or Path("raw")

    @run_stage_def(reads=("run_date",), writes=("curator_findings",))
    async def fetch_findings(run_bus: RunBus) -> RunBus:
        if not run_bus.run_date:
            raise StageError(
                "fetch_findings: run_bus.run_date is empty. Run init_run first."
            )
        run_bus.curator_findings = _load_feed_findings(rd, run_bus.run_date)
        return run_bus

    return fetch_findings


fetch_findings = make_fetch_findings()


# ---------------------------------------------------------------------------
# finalize_run
# ---------------------------------------------------------------------------


class TopicManifestEntry(BaseModel):
    """One row of `run_topic_manifest`. Aggregated by finalize_run from
    per-TopicBus completion data the runner collects (V2-10)."""

    model_config = ConfigDict(extra="forbid")

    topic_id: str
    topic_slug: str
    status: Literal["success", "partial", "failed"]
    stages_completed: list[str] = Field(default_factory=list)


def make_finalize_run(
    manifest_entries: Sequence[Any] = (),
    *,
    expected_stage_count: Optional[int] = None,
) -> Callable:
    """Build a `finalize_run` stage closing over per-TopicBus manifest data.

    `manifest_entries` is a sequence of either `TopicManifestEntry` instances
    or dicts validated against that shape. The runner (V2-10) will assemble
    these from each completed TopicBus and pass them in.

    `expected_stage_count` (optional): if provided, derives status from
    `len(stages_completed)` vs this value when status is not pre-set in the
    entry. For V2-03a, status is taken verbatim from the entry; this hook
    exists for V2-10 to refine.
    """
    raw_entries = list(manifest_entries)

    @run_stage_def(
        reads=("run_id", "run_date", "run_variant"),
        writes=("run_topic_manifest",),
    )
    async def finalize_run(run_bus: RunBus) -> RunBus:
        normalized: list[dict] = []
        for entry in raw_entries:
            if isinstance(entry, TopicManifestEntry):
                normalized.append(entry.model_dump())
            elif isinstance(entry, dict):
                normalized.append(TopicManifestEntry.model_validate(entry).model_dump())
            else:
                raise StageError(
                    f"finalize_run: manifest entry must be TopicManifestEntry "
                    f"or dict, got {type(entry).__name__}"
                )
        run_bus.run_topic_manifest = normalized
        return run_bus

    return finalize_run


finalize_run = make_finalize_run()


# ---------------------------------------------------------------------------
# select_topics (run/topic boundary)
# ---------------------------------------------------------------------------


@run_stage_def(
    reads=("editor_assignments", "max_produce"),
    writes=("selected_assignments",),
)
async def select_topics(run_bus: RunBus) -> RunBus:
    """Filter, sort, and slice editor_assignments to produce the selected
    subset that the runner will instantiate as TopicBuses.

    V1 reference: src/pipeline.py around lines 1336-1366. Same rules:
    - Drop entries with priority <= 0 (Editor's reject signal).
    - Sort by (-priority, -len(raw_data.source_ids)) — priority first,
      source-count tiebreaker descending, then array position.
    - Slice to run_bus.max_produce.

    Reads:  editor_assignments, max_produce.
    Writes: selected_assignments (the trimmed/sorted list of dicts).

    The runner reads selected_assignments, calls `make_topic_bus(assignment,
    run_bus)` per entry, and dispatches the topic-stage chain on each.
    """
    accepted: list[dict] = []
    for entry in run_bus.editor_assignments or []:
        if not isinstance(entry, dict):
            continue
        priority = entry.get("priority")
        if not isinstance(priority, (int, float)) or priority <= 0:
            continue
        accepted.append(entry)

    accepted.sort(
        key=lambda e: (
            -int(e.get("priority", 0)),
            -len((e.get("raw_data") or {}).get("source_ids", []) or []),
        )
    )

    budget = run_bus.max_produce or 0
    if budget > 0 and len(accepted) > budget:
        logger.info(
            "select_topics: %d accepted topics, producing top %d",
            len(accepted),
            budget,
        )
        accepted = accepted[:budget]

    run_bus.selected_assignments = accepted
    return run_bus


def make_topic_bus(
    assignment: dict | EditorAssignment, run_bus: RunBus | RunBusReadOnly
) -> TopicBus:
    """Construct a TopicBus from one selected assignment.

    Not a stage — a plain factory the runner calls per entry in
    `run_bus.selected_assignments`. The TopicBus's `editor_selected_topic`
    is populated with an EditorAssignment instance; every other slot stays
    at its typed empty default.
    """
    if isinstance(assignment, EditorAssignment):
        ea = assignment.model_copy(deep=True)
    elif isinstance(assignment, dict):
        ea = EditorAssignment.model_validate(assignment)
    else:
        raise StageError(
            f"make_topic_bus: assignment must be dict or EditorAssignment, "
            f"got {type(assignment).__name__}"
        )
    return TopicBus(editor_selected_topic=ea)


__all__ = [
    "MirrorMismatchError",
    "RunInitConfig",
    "TopicManifestEntry",
    "fetch_findings",
    "finalize_run",
    "init_run",
    "make_fetch_findings",
    "make_finalize_run",
    "make_init_run",
    "make_topic_bus",
    "mirror_stage",
    "select_topics",
]
