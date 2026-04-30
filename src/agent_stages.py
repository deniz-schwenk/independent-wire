"""V2 agent-stage wrappers — Curator, Editor, Researcher Plan.

Per ARCH-V2-BUS-SCHEMA §3.2: agents are isolated from the bus schema; the
wrapper does the mapping. Each wrapper class:

- carries the Agent instance via dependency injection at construction
- exposes the V2-02 stage interface as class attributes
  (`stage_kind`, `reads`, `writes`) so `get_stage_meta` works on instances
- implements `async __call__` to run the agent and write output to the bus

This task ships three pilot wrappers (Curator, Editor, Researcher Plan).
QA, Researcher Assemble, Perspective, Writer, Bias Language, Perspective
Sync, and the two Hydration phases ship in V2-06.

V1 references for the deterministic post-processing each wrapper folds in:
- _slugify                          src/pipeline.py:25-47
- _prepare_curator_input            src/pipeline.py:1499-1546
- _recover_truncated_cluster_       src/pipeline.py:1548-1596
  assignments
- _rebuild_curator_source_ids       src/pipeline.py:1598-1696
- _enrich_curator_output            src/pipeline.py:1698-1792
- _attach_raw_data_from_curated     src/pipeline.py:1928-1988
- editorial_conference id/slug      src/pipeline.py:2042-2102
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.agent import Agent
from src.bus import EditorAssignment, RunBus, RunBusReadOnly, TopicBus
from src.stage import StageMeta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stage-meta wiring for class-based wrappers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AttachMeta:
    """Sentinel marker; the actual StageMeta is built from class attributes
    by `__init_subclass__` on `_AgentStageBase` so `get_stage_meta(instance)`
    returns a frozen dataclass identical to the decorator-stamped version."""


class _AgentStageBase:
    """Common base for agent-stage wrappers.

    Subclasses declare:
        stage_kind: Literal["run", "topic"]
        reads:      tuple[str, ...]
        writes:     tuple[str, ...]
        agent_role: str   # short name for logs, "curator" / "editor" / etc.

    On subclass creation, `_stage_meta` is auto-stamped on the class so
    `get_stage_meta(instance)` returns the dataclass — same surface as the
    decorator-stamped functions in V2-03/04.
    """

    stage_kind: str = "run"
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    agent_role: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._stage_meta = StageMeta(
            name=cls.__name__,
            kind=cls.stage_kind,  # type: ignore[arg-type]
            reads=tuple(cls.reads),
            writes=tuple(cls.writes),
        )


# ---------------------------------------------------------------------------
# Output parsing — thin layer over result.structured + Agent._parse_json
# ---------------------------------------------------------------------------


def _parse_agent_output(result: Any) -> Any:
    """Return the parsed agent output as a dict or list (or None).

    Tries `result.structured` first (the agent's schema-validated parse);
    falls back to `Agent._parse_json(result.content)` for the rare cases
    where structured is None but the final raw response is recoverable.

    Per V2-05 §3.3: defensive but lean. Does NOT reimplement V1's
    `_extract_dict` / `_extract_list` multi-strategy chain — the agent's
    own `_parse_or_retry_structured` already runs that logic upstream.
    """
    structured = getattr(result, "structured", None)
    if isinstance(structured, (dict, list)):
        return structured
    content = getattr(result, "content", None) or ""
    if not content:
        return None
    return Agent._parse_json(content)


def _unwrap_list(parsed: Any, key: str) -> list:
    """Unwrap a `{key: [...]}` envelope to its list, falling back to
    `parsed` itself if it is already a list. Returns `[]` if neither
    shape matches.

    Used by Editor (`{"assignments": [...]}` per the schema) and
    ResearcherPlan (`{"queries": [...]}` per the schema).
    """
    if isinstance(parsed, dict):
        inner = parsed.get(key)
        if isinstance(inner, list):
            return inner
    if isinstance(parsed, list):
        return parsed
    return []


# ---------------------------------------------------------------------------
# Slug helper (V1 src/pipeline.py:25-47)
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    """Deterministic ASCII-fold slug. NFKD-normalised, non-`\\w` runs to `-`,
    truncated to 60 chars at the nearest hyphen boundary."""
    if not title:
        return ""
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    s = ascii_only.lower()
    s = re.sub(r"[^\w]+", "-", s, flags=re.ASCII)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-_")
    if len(s) > 60:
        s = s[:60]
        last_hyphen = s.rfind("-")
        if last_hyphen >= 30:
            s = s[:last_hyphen]
        s = s.strip("-_")
    return s


# ---------------------------------------------------------------------------
# Curator helpers (V1 src/pipeline.py:1499-1792)
# ---------------------------------------------------------------------------


def _prepare_curator_input(raw_findings: list[dict]) -> list[dict]:
    """Compress findings for the Curator. URL dedup + strip non-input fields
    + summary-vs-title heuristic. V1: src/pipeline.py:1499-1546."""
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for f in raw_findings:
        url = f.get("source_url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique.append(f)

    url_dupes = len(raw_findings) - len(unique)
    if url_dupes:
        logger.info("Curator prep: removed %d URL duplicates", url_dupes)

    compressed: list[dict] = []
    for i, f in enumerate(unique):
        title = f.get("title", "").strip()
        if not title:
            continue
        entry: dict = {
            "id": f"finding-{i}",
            "title": title,
            "source_name": f.get("source_name", ""),
        }
        summary = f.get("summary", "").strip()
        if (
            summary
            and summary.lower() != title.lower()
            and not title.lower().startswith(summary.lower()[:50])
        ):
            entry["summary"] = summary
        compressed.append(entry)

    logger.info(
        "Curator prep: %d raw → %d unique → %d with titles (compressed)",
        len(raw_findings),
        len(unique),
        len(compressed),
    )
    return compressed


def _recover_truncated_cluster_assignments(
    content: str, n_findings: int
) -> Optional[list]:
    """Regex-recover `cluster_assignments` from raw Curator content when
    bracket-balance JSON repair dropped the partial trailing array.
    V1: src/pipeline.py:1548-1596."""
    if not content:
        return None
    m = re.search(r'"cluster_assignments"\s*:\s*\[', content)
    if not m:
        return None
    pos = m.end()
    n = len(content)
    entries: list = []
    while pos < n and len(entries) < n_findings:
        while pos < n and content[pos] in " \n\t\r":
            pos += 1
        if pos >= n:
            break
        ch = content[pos]
        if ch == "]":
            break
        if ch == ",":
            pos += 1
            continue
        if content.startswith("null", pos):
            entries.append(None)
            pos += 4
            continue
        m2 = re.match(r"-?\d+", content[pos:])
        if m2:
            entries.append(int(m2.group()))
            pos += m2.end()
            continue
        break
    return entries


def _rebuild_curator_source_ids(
    result: Any, raw_findings: list[dict]
) -> list[dict]:
    """Extract Curator topics and rebuild source_ids deterministically.

    Handles three shapes:
    - S13 envelope `{topics, cluster_assignments}` (canonical)
    - Truncation-recovery: dict carries topics but null cluster_assignments
      (Gemini Flash mid-array truncation + bracket-balance JSON repair)
    - Legacy top-level list of topics with source_ids already attached

    V1: src/pipeline.py:1598-1696. Verbatim port.
    """
    parsed = _parse_agent_output(result)

    # Truncation recovery: dict has `topics` but `cluster_assignments` is
    # missing or None. Re-extract the array from raw content via regex.
    if (
        isinstance(parsed, dict)
        and isinstance(parsed.get("topics"), list)
        and parsed.get("cluster_assignments") is None
    ):
        recovered = _recover_truncated_cluster_assignments(
            getattr(result, "content", "") or "", len(raw_findings)
        )
        if recovered is not None:
            logger.warning(
                "Curator cluster_assignments dropped by JSON repair; "
                "recovered %d entries via regex (expected %d)",
                len(recovered),
                len(raw_findings),
            )
            parsed["cluster_assignments"] = recovered

    new_shape = (
        isinstance(parsed, dict)
        and isinstance(parsed.get("topics"), list)
        and isinstance(parsed.get("cluster_assignments"), list)
    )
    if not new_shape:
        # Legacy: top-level list of topics with source_ids attached.
        if isinstance(parsed, list):
            return parsed
        return []

    topics_in: list = parsed.get("topics") or []
    topics: list[dict] = [t for t in topics_in if isinstance(t, dict)]
    for t in topics:
        t["source_ids"] = []

    n_findings = len(raw_findings)
    n_topics = len(topics)
    assignments: list = parsed.get("cluster_assignments") or []
    n_assignments = len(assignments)

    if n_assignments != n_findings:
        logger.warning(
            "Curator cluster_assignments length=%d does not match findings "
            "length=%d; processing the overlap only",
            n_assignments,
            n_findings,
        )

    overlap = min(n_assignments, n_findings)
    for finding_index in range(overlap):
        topic_index = assignments[finding_index]
        if topic_index is None:
            continue
        if not isinstance(topic_index, int):
            logger.warning(
                "Curator cluster_assignments[%d]=%r is not an int|null; skipping",
                finding_index,
                topic_index,
            )
            continue
        if not (0 <= topic_index < n_topics):
            logger.warning(
                "Curator cluster_assignments[%d]=%d is out of range "
                "(have %d topics); skipping",
                finding_index,
                topic_index,
                n_topics,
            )
            continue
        topics[topic_index]["source_ids"].append(f"finding-{finding_index}")

    for ti, t in enumerate(topics):
        if not t["source_ids"]:
            logger.info(
                "Curator topic %d ('%s') has no cluster_assignments — "
                "empty source_ids; unlikely to survive Editor",
                ti,
                t.get("title", "?"),
            )
    return topics


def _enrich_curator_output(
    topics: list[dict],
    raw_findings: list[dict],
    *,
    sources_json_path: Path | None = None,
) -> list[dict]:
    """Add geographic_coverage / missing_perspectives / languages /
    source_diversity deterministically. V1: src/pipeline.py:1698-1792.

    `sources_json_path` defaults to `config/sources.json`; tests inject a
    tmp_path. Per V2-05 §3.4: the disk read stays here for V2-05 — V1's
    behaviour preserved. A future refactor may move this into init_run via
    a new RunBus slot; flagged in CC Report.
    """
    sources_path = sources_json_path or Path("config") / "sources.json"
    source_meta: dict[str, dict] = {}
    if sources_path.exists():
        try:
            data = json.loads(sources_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Could not load sources.json: %s", e)
            data = {"feeds": []}
        source_meta = {s["name"]: s for s in data.get("feeds", [])}

    finding_index: dict[str, dict] = {}
    for i, f in enumerate(raw_findings):
        finding_index[f"finding-{i}"] = f

    all_regions: set[str] = set()
    all_languages: set[str] = set()
    for f in raw_findings:
        r = f.get("region", "")
        if r:
            all_regions.add(r)
        lang = f.get("language", "")
        if lang:
            all_languages.add(lang)

    for topic in topics:
        source_ids = topic.get("source_ids", [])
        topic_regions: set[str] = set()
        topic_languages: set[str] = set()
        topic_sources: list[dict] = []
        for sid in source_ids:
            finding = finding_index.get(sid)
            if not finding:
                continue
            r = finding.get("region", "")
            if r:
                topic_regions.add(r)
            lang = finding.get("language", "")
            if lang:
                topic_languages.add(lang)
            sname = finding.get("source_name", "")
            meta = source_meta.get(sname, {})
            topic_sources.append(
                {
                    "name": sname,
                    "tier": meta.get("tier"),
                    "editorial_independence": meta.get("editorial_independence"),
                }
            )
        topic["geographic_coverage"] = sorted(topic_regions)
        topic["languages"] = sorted(topic_languages)
        topic["source_count"] = len(source_ids)
        missing_regions = sorted(all_regions - topic_regions)
        topic["missing_regions"] = missing_regions
        missing_langs = sorted(all_languages - topic_languages)
        topic["missing_languages"] = missing_langs
        topic["source_diversity"] = topic_sources
        parts: list[str] = []
        if missing_regions:
            parts.append(f"No sources from: {', '.join(missing_regions)}")
        if missing_langs:
            parts.append(f"No coverage in: {', '.join(missing_langs)}")
        existing = topic.get("missing_perspectives", "")
        deterministic = ". ".join(parts) if parts else ""
        if existing and deterministic:
            topic["missing_perspectives"] = (
                f"{existing} [Deterministic: {deterministic}]"
            )
        elif deterministic:
            topic["missing_perspectives"] = deterministic
    return topics


# ---------------------------------------------------------------------------
# Editor helpers (V1 src/pipeline.py:1928-2102)
# ---------------------------------------------------------------------------


_CURATOR_RAW_DATA_FIELDS: tuple[str, ...] = (
    "source_ids",
    "summary",
    "geographic_coverage",
    "languages",
    "missing_perspectives",
    "source_count",
    "missing_regions",
    "missing_languages",
    "source_diversity",
    "relevance_score",
)


def _attach_raw_data_from_curated(
    raw_assignments: list[dict], curated_topics: list[dict]
) -> None:
    """Attach Curator's enrichment to Editor's assignments in place. Match
    by exact title first, then by slug. V1: src/pipeline.py:1928-1988."""

    def _extract(t: dict) -> dict:
        return {k: t[k] for k in _CURATOR_RAW_DATA_FIELDS if k in t}

    title_lookup: dict[str, dict] = {}
    slug_buckets: dict[str, list[dict]] = {}
    for t in curated_topics:
        if not isinstance(t, dict):
            continue
        title = t.get("title") or ""
        raw_data = _extract(t)
        if title and title not in title_lookup:
            title_lookup[title] = raw_data
        slug = _slugify(title)
        if slug:
            slug_buckets.setdefault(slug, []).append(raw_data)

    for a in raw_assignments:
        if not isinstance(a, dict):
            continue
        if a.get("raw_data"):
            continue
        title = a.get("title") or ""
        if title in title_lookup:
            a["raw_data"] = title_lookup[title]
            continue
        slug = _slugify(title)
        if slug and slug in slug_buckets:
            bucket = slug_buckets[slug]
            if len(bucket) == 1:
                a["raw_data"] = bucket[0]
                logger.info(
                    "editor refined title; matched by slug: '%s' (slug=%s)",
                    title,
                    slug,
                )
                continue
            logger.warning(
                "editor topic '%s' has %d slug-level matches; raw_data left empty",
                title,
                len(bucket),
            )
            a["raw_data"] = {}
            continue
        logger.warning(
            "editor topic '%s' did not match any curated topic; "
            "raw_data unavailable for tiebreaker and researcher_plan",
            title,
        )
        a["raw_data"] = {}


def _assign_ids_and_slugs(
    raw_assignments: list[dict], run_date: str
) -> list[dict]:
    """Filter rejects, sort survivors by (priority desc, source_count desc,
    position asc), assign sequential `tp-{date}-NNN` ids. Rejects appear at
    the tail with `id=""`. Returns plain dicts (caller wraps in
    EditorAssignment via Pydantic validation).

    V1: src/pipeline.py:2042-2102."""
    survivors: list[dict] = []
    rejected: list[dict] = []
    for position, a in enumerate(raw_assignments):
        if not isinstance(a, dict):
            continue
        priority_raw = a.get("priority", 5)
        try:
            priority = int(priority_raw)
        except (TypeError, ValueError):
            priority = 5
        source_count = len(a.get("raw_data", {}).get("source_ids", []))
        entry = {
            "raw": a,
            "priority": priority,
            "source_count": source_count,
            "position": position,
        }
        if priority <= 0:
            rejected.append(entry)
        else:
            survivors.append(entry)

    survivors.sort(
        key=lambda e: (-e["priority"], -e["source_count"], e["position"])
    )

    out: list[dict] = []
    for seq, entry in enumerate(survivors, start=1):
        a = entry["raw"]
        title = a.get("title", "") or ""
        slug = _slugify(title) or "topic"
        out.append(
            {
                "id": f"tp-{run_date}-{seq:03d}",
                "title": title,
                "priority": entry["priority"],
                "topic_slug": slug,
                "selection_reason": a.get("selection_reason", ""),
                "raw_data": a.get("raw_data", {}),
                "follow_up_to": a.get("follow_up_to"),
                "follow_up_reason": a.get("follow_up_reason"),
            }
        )
    for entry in rejected:
        a = entry["raw"]
        out.append(
            {
                "id": "",
                "title": a.get("title", "") or "",
                "priority": entry["priority"],
                "topic_slug": "",
                "selection_reason": a.get("selection_reason", ""),
                "raw_data": a.get("raw_data", {}),
                "follow_up_to": a.get("follow_up_to"),
                "follow_up_reason": a.get("follow_up_reason"),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Wrapper: CuratorStage  (run-stage)
# ---------------------------------------------------------------------------


class CuratorStage(_AgentStageBase):
    """Curator agent wrapper.

    Reads `curator_findings`. Calls Curator with compressed prepared input.
    Post-processes via _rebuild_curator_source_ids + _enrich_curator_output,
    sorts by relevance_score desc, slices to max_topics. Writes
    curator_topics_unsliced (full sorted list) and curator_topics (top-N).
    """

    stage_kind = "run"
    reads = ("curator_findings",)
    writes = ("curator_topics_unsliced", "curator_topics")
    agent_role = "curator"

    DEFAULT_MAX_TOPICS = 10

    def __init__(
        self,
        agent: Agent,
        *,
        max_topics: int = DEFAULT_MAX_TOPICS,
        sources_json_path: Path | None = None,
    ) -> None:
        self.agent = agent
        self.max_topics = max_topics
        self.sources_json_path = sources_json_path

    async def __call__(self, run_bus: RunBus) -> RunBus:
        raw_findings = list(run_bus.curator_findings or [])
        prepared = _prepare_curator_input(raw_findings)

        message = (
            "Review these findings. Cluster related findings into topics. "
            "Score each topic's newsworthiness on a 1-10 scale."
        )
        result = await self.agent.run(message, context={"findings": prepared})

        topics = _rebuild_curator_source_ids(result, raw_findings)
        topics = _enrich_curator_output(
            topics, raw_findings, sources_json_path=self.sources_json_path
        )
        topics.sort(key=lambda t: t.get("relevance_score", 0), reverse=True)
        topics_top_n = topics[: self.max_topics]

        logger.info(
            "Curator: %d topics, slicing to top %d",
            len(topics),
            self.max_topics,
        )
        return run_bus.model_copy(
            update={
                "curator_topics_unsliced": topics,
                "curator_topics": topics_top_n,
            }
        )


# ---------------------------------------------------------------------------
# Wrapper: EditorStage  (run-stage)
# ---------------------------------------------------------------------------


class EditorStage(_AgentStageBase):
    """Editor agent wrapper.

    Reads `curator_topics`, `previous_coverage`. Unwraps the schema's
    `{"assignments": [...]}` envelope, attaches Curator-side raw_data via
    title/slug match, sorts survivors and assigns tp-{date}-NNN ids,
    appends rejected entries with id="". Writes `editor_assignments` as a
    list of dicts (the bus's Pydantic validator does NOT coerce — slot is
    typed `list`, the dicts pass through).
    """

    stage_kind = "run"
    reads = ("curator_topics", "previous_coverage")
    writes = ("editor_assignments",)
    agent_role = "editor"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(self, run_bus: RunBus) -> RunBus:
        curated = list(run_bus.curator_topics or [])
        previous = list(run_bus.previous_coverage or [])
        run_date = run_bus.run_date or ""

        message = (
            "Prioritize these topics for today's report. For each, assign a "
            "priority (1-10) and a selection_reason. Today's date is "
            f"{run_date}."
        )
        result = await self.agent.run(
            message,
            context={"topics": curated, "previous_coverage": previous},
        )
        parsed = _parse_agent_output(result)
        raw_assignments = _unwrap_list(parsed, "assignments")

        # In-place attach raw_data on the unwrapped list
        _attach_raw_data_from_curated(raw_assignments, curated)
        finalized = _assign_ids_and_slugs(raw_assignments, run_date)

        return run_bus.model_copy(update={"editor_assignments": finalized})


# ---------------------------------------------------------------------------
# Wrapper: ResearcherPlanStage  (topic-stage)
# ---------------------------------------------------------------------------


class ResearcherPlanStage(_AgentStageBase):
    """Researcher Plan agent wrapper.

    Reads `editor_selected_topic`. Sends `{title, selection_reason,
    raw_data}` as context. Unwraps `{"queries": [...]}` envelope. Writes
    the parsed query list into `researcher_plan_queries`.
    """

    stage_kind = "topic"
    reads = ("editor_selected_topic",)
    writes = ("researcher_plan_queries",)
    agent_role = "researcher_plan"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        assignment = topic_bus.editor_selected_topic
        message = (
            "Generate multilingual web-search queries to research this topic. "
            "Return the queries as a JSON array."
        )
        context = {
            "title": assignment.title,
            "selection_reason": assignment.selection_reason,
            "raw_data": dict(assignment.raw_data or {}),
        }
        result = await self.agent.run(message, context=context)
        parsed = _parse_agent_output(result)
        queries = _unwrap_list(parsed, "queries")

        return topic_bus.model_copy(
            update={"researcher_plan_queries": queries}
        )


__all__ = [
    "CuratorStage",
    "EditorStage",
    "ResearcherPlanStage",
]
