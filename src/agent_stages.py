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

import asyncio
import json
import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from src.agent import Agent
from src.bus import (
    Correction,
    EditorAssignment,
    HydrationPhase2Corpus,
    HydrationPreDossier,
    ResearcherAssembleDossier,
    RunBus,
    RunBusReadOnly,
    TopicBus,
    WriterArticle,
)
from src.stage import StageMeta
from src.stages._helpers import normalise_country

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
            "today": run_bus.run_date,
        }
        result = await self.agent.run(message, context=context)
        parsed = _parse_agent_output(result)
        queries = _unwrap_list(parsed, "queries")

        return topic_bus.model_copy(
            update={"researcher_plan_queries": queries}
        )


# ---------------------------------------------------------------------------
# Helpers reused by V2-06 wrappers
# ---------------------------------------------------------------------------


def _extract_date_from_url(url: str) -> Optional[str]:
    """Extract publication date from common news URL patterns. V1:
    src/pipeline.py:71-103."""
    if not url:
        return None
    m = re.search(r"/(\d{4})[/-](\d{2})[/-](\d{2})(?:/|[^0-9])", url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"/(\d{4})(\d{2})(\d{2})(?:/|[^0-9]|$)", url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.search(r"/(\d{4})[/-](\d{2})(?:/|[^0-9])", url)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 2020 <= y <= 2030 and 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-01"
    return None


def _build_bias_card_for_agent_input(topic_bus: TopicBus) -> dict:
    """Compute the deterministic bias_card data structure that the
    bias_language LLM consumes as context. V1: src/pipeline.py:870-944
    `_build_bias_card` (the perspectives + coverage_gaps subsections; the
    source/geographic blocks come from source_balance which is computed
    by V2-03b's compute_source_balance stage).
    """
    article = topic_bus.qa_corrected_article
    sources = list(topic_bus.final_sources or [])
    clusters = list(topic_bus.perspective_clusters_synced or [])
    missing_positions = list(topic_bus.perspective_missing_positions or [])

    by_language: dict[str, int] = {}
    by_country: dict[str, int] = {}
    for s in sources:
        if not isinstance(s, dict):
            continue
        lang = s.get("language") or "unknown"
        by_language[lang] = by_language.get(lang, 0) + 1
        country = normalise_country(s.get("country")) or "unknown"
        by_country[country] = by_country.get(country, 0) + 1

    article_countries = {
        normalise_country(s.get("country")) for s in sources if isinstance(s, dict)
    }
    article_countries.discard("")

    distinct_actors: set[tuple] = set()
    representation_distribution: dict[str, int] = {
        "dominant": 0,
        "substantial": 0,
        "marginal": 0,
    }
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        rep = cluster.get("representation", "marginal")
        if rep in representation_distribution:
            representation_distribution[rep] += 1
        for actor in cluster.get("actors") or []:
            if not isinstance(actor, dict):
                continue
            key = (actor.get("name", ""), actor.get("role", ""))
            if any(key):
                distinct_actors.add(key)

    return {
        "article_summary": article.summary,
        "source_balance": {
            "total": len(sources),
            "by_language": by_language,
            "by_country": by_country,
        },
        "geographic_coverage": {
            "represented": sorted(article_countries),
        },
        "perspectives": {
            "cluster_count": len(clusters),
            "distinct_actor_count": len(distinct_actors),
            "representation_distribution": representation_distribution,
            "missing_positions": missing_positions,
        },
        "factual_divergences": list(topic_bus.qa_divergences or []),
        "coverage_gaps": list(topic_bus.coverage_gaps_validated or []),
    }


def _merge_perspective_deltas(
    original_perspectives: dict, sync_output: dict, slug: str = ""
) -> dict:
    """Apply position_cluster_updates deltas into a deep copy of the map.
    V1 reference: src/pipeline_hydrated.py:233-305 `merge_perspektiv_deltas`.
    Ported here to avoid coupling V2 agent_stages to V1 pipeline_hydrated.
    """
    import copy as _copy

    synced = _copy.deepcopy(original_perspectives)
    updates = sync_output.get("position_cluster_updates") or []
    clusters_by_id: dict[str, dict] = {}
    for cluster in synced.get("position_clusters", []) or []:
        if isinstance(cluster, dict):
            cid = cluster.get("id")
            if isinstance(cid, str) and cid:
                clusters_by_id[cid] = cluster

    mergeable_fields = ("position_label", "position_summary")
    for entry in updates:
        if not isinstance(entry, dict):
            logger.warning(
                "perspective_sync[%s]: skipping non-dict delta entry %r",
                slug, entry,
            )
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            logger.warning(
                "perspective_sync[%s]: skipping delta entry with no id: %r",
                slug, entry,
            )
            continue
        target = clusters_by_id.get(entry_id)
        if target is None:
            logger.warning(
                "perspective_sync[%s]: delta id=%s not found; skipping",
                slug, entry_id,
            )
            continue
        for field in mergeable_fields:
            if field not in entry:
                continue
            value = entry[field]
            if value is None:
                logger.warning(
                    "perspective_sync[%s]: delta id=%s has %s=null; "
                    "treating as absent (V2 forbids null overrides)",
                    slug, entry_id, field,
                )
                continue
            if isinstance(value, str):
                target[field] = value
    return synced


# ---------------------------------------------------------------------------
# Wrapper: ResearcherAssembleStage  (topic, production + hydrated)
# ---------------------------------------------------------------------------


class ResearcherAssembleStage(_AgentStageBase):
    """Researcher Assemble agent wrapper.

    Reads `editor_selected_topic`, `researcher_search_results`. Calls agent
    to build a research dossier. Writes `researcher_assemble_dossier` with
    sources carrying `research-rsrc-NNN` ids per ARCH §4B.3 (V1 used bare
    `rsrc-NNN`; V2 uses the prefixed form so merge_sources can disambiguate
    from `hydrate-rsrc-NNN` when both dossiers exist in the hydrated variant).
    """

    stage_kind = "topic"
    reads = ("editor_selected_topic", "researcher_search_results")
    writes = ("researcher_assemble_dossier",)
    agent_role = "researcher_assemble"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        assignment = topic_bus.editor_selected_topic
        message = (
            "Build a research dossier from these search results. "
            "Extract sources, actors, divergences, and coverage gaps."
        )
        result = await self.agent.run(
            message,
            context={
                "assignment": {
                    "title": assignment.title,
                    "selection_reason": assignment.selection_reason,
                },
                "date": run_bus.run_date,
                "search_results": list(topic_bus.researcher_search_results),
            },
        )
        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        sources = parsed.get("sources") or []
        for idx, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            source["id"] = f"research-rsrc-{idx + 1:03d}"
            if not source.get("estimated_date"):
                est = _extract_date_from_url(source.get("url", "") or "")
                if est:
                    source["estimated_date"] = est

        dossier = ResearcherAssembleDossier(
            sources=sources,
            preliminary_divergences=list(parsed.get("preliminary_divergences") or []),
            coverage_gaps=list(parsed.get("coverage_gaps") or []),
        )
        return topic_bus.model_copy(update={"researcher_assemble_dossier": dossier})


# ---------------------------------------------------------------------------
# Wrapper: PerspectiveStage  (topic, production + hydrated)
# ---------------------------------------------------------------------------


class PerspectiveStage(_AgentStageBase):
    """Perspective agent wrapper.

    Reads `editor_selected_topic`, `final_sources`, `merged_preliminary_
    divergences`, `merged_coverage_gaps`. Calls agent. Writes the **raw**
    cluster output `[{position_label, position_summary, source_ids}]` to
    `perspective_clusters` plus `perspective_missing_positions` verbatim.

    The deterministic enrichment that attaches `pc-NNN`, actors, regions,
    languages, and representation lives in the
    `enrich_perspective_clusters` topic-stage (in
    `src/stages/topic_stages.py`), which runs immediately after this
    wrapper. Keeping the wrapper raw matches V2's pattern of separating
    LLM output from deterministic post-processing.
    """

    stage_kind = "topic"
    reads = (
        "editor_selected_topic",
        "final_sources",
        "merged_preliminary_divergences",
        "merged_coverage_gaps",
    )
    writes = ("perspective_clusters", "perspective_missing_positions")
    agent_role = "perspective"  # V1 folder name; V2-07 anglicises

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        assignment = topic_bus.editor_selected_topic
        message = (
            "Identify the position clusters in this dossier. Map missing "
            "voices the dossier could not source."
        )
        result = await self.agent.run(
            message,
            context={
                "title": assignment.title,
                "selection_reason": assignment.selection_reason,
                "sources": list(topic_bus.final_sources),
                "preliminary_divergences": list(
                    topic_bus.merged_preliminary_divergences
                ),
                "coverage_gaps": list(topic_bus.merged_coverage_gaps),
            },
        )
        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        return topic_bus.model_copy(
            update={
                "perspective_clusters": list(
                    parsed.get("position_clusters") or []
                ),
                "perspective_missing_positions": list(
                    parsed.get("missing_positions") or []
                ),
            }
        )


# ---------------------------------------------------------------------------
# Wrapper: WriterStage  (topic, production + hydrated)
# ---------------------------------------------------------------------------


class WriterStage(_AgentStageBase):
    """Writer agent wrapper.

    Reads `editor_selected_topic`, `final_sources`, `perspective_clusters_
    synced`, `perspective_missing_positions`, `merged_coverage_gaps`. Plus
    optional follow-up addendum loaded from `agents/writer/FOLLOWUP.md` when
    `editor_selected_topic.follow_up_to` is truthy.

    Writes `writer_article`. The Writer agent has `tools=[web_search_tool]`
    configured at construction; the agent's tool-call loop handles invocation
    transparently. Per V2-03b stage order, final_sources already carries
    `src-NNN` ids, so the Writer emits `[src-NNN]` citations directly — V1's
    post-Writer `_merge_writer_sources` is structurally redundant in V2.
    """

    stage_kind = "topic"
    reads = (
        "editor_selected_topic",
        "final_sources",
        "perspective_clusters_synced",
        "perspective_missing_positions",
        "merged_coverage_gaps",
    )
    writes = ("writer_article",)
    agent_role = "writer"

    DEFAULT_FOLLOWUP_PATH = Path("agents/writer/FOLLOWUP.md")

    def __init__(
        self, agent: Agent, *, followup_path: Path | None = None
    ) -> None:
        self.agent = agent
        self.followup_path = followup_path or self.DEFAULT_FOLLOWUP_PATH

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        assignment = topic_bus.editor_selected_topic

        # Re-shape perspective_clusters_synced as the V1 perspective_analysis
        # dict the Writer prompt expects.
        perspective_analysis = {
            "position_clusters": list(topic_bus.perspective_clusters_synced),
            "missing_positions": list(topic_bus.perspective_missing_positions),
        }

        writer_context: dict[str, Any] = {
            "title": assignment.title,
            "selection_reason": assignment.selection_reason,
            "perspective_analysis": perspective_analysis,
            "sources": list(topic_bus.final_sources),
            "coverage_gaps": list(topic_bus.merged_coverage_gaps),
        }

        writer_addendum: Optional[str] = None
        if assignment.follow_up_to:
            if self.followup_path.exists():
                writer_addendum = self.followup_path.read_text(encoding="utf-8")
                logger.info(
                    "Loaded follow-up addendum for '%s' (follows %s)",
                    assignment.title,
                    assignment.follow_up_to,
                )
            else:
                logger.warning(
                    "Follow-up topic '%s' but FOLLOWUP.md not found at %s",
                    assignment.title,
                    self.followup_path,
                )
            previous_headline = ""
            for entry in run_bus.previous_coverage or []:
                if isinstance(entry, dict) and entry.get("tp_id") == assignment.follow_up_to:
                    previous_headline = entry.get("headline", "") or ""
                    break
            if not previous_headline:
                logger.warning(
                    "Follow-up: no previous_coverage match for tp_id=%s",
                    assignment.follow_up_to,
                )
            writer_context["follow_up"] = {
                "previous_headline": previous_headline,
                "reason": assignment.follow_up_reason or "",
            }

        result = await self.agent.run(
            "Write a multi-perspective article on this topic.",
            context=writer_context,
            instructions_addendum=writer_addendum,
        )
        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        article = WriterArticle(
            headline=parsed.get("headline", "") or "",
            subheadline=parsed.get("subheadline", "") or "",
            body=parsed.get("body", "") or "",
            summary=parsed.get("summary", "") or "",
        )
        return topic_bus.model_copy(update={"writer_article": article})


# ---------------------------------------------------------------------------
# Wrapper: QaAnalyzeStage  (topic, production + hydrated) — CRITICAL
# ---------------------------------------------------------------------------


class QaAnalyzeStage(_AgentStageBase):
    """QA-Analyze agent wrapper. Ships atomic with the schema change in
    src/schemas.py (`article` removed from QA_ANALYZE_SCHEMA's required
    list) and the V2-03b mirror_qa_corrected stage.

    Reads `writer_article`, `final_sources`, `perspective_clusters_synced`,
    `merged_preliminary_divergences`. Writes `qa_problems_found`,
    `qa_corrections`, `qa_corrected_article`, `qa_divergences`.

    Mirror integration: when QA finds no problems and the agent omits the
    `article` field per the V2 prompt, the wrapper leaves
    `qa_corrected_article` at its empty WriterArticle default. The slot
    has `mirrors_from="writer_article"` annotated in `bus.py`, so V2-02
    post-validation accepts the empty state. The downstream
    `mirror_qa_corrected` stage (V2-03b) then fills the slot from
    `writer_article`. This is the complete realisation of the V2 mirror
    pattern — schema + prompt + wrapper + mirror all aligned.

    V1 reference: src/pipeline.py:2349-2398 (the QA call + post-QA
    article-field merge in `_produce_single`).
    """

    stage_kind = "topic"
    reads = (
        "writer_article",
        "final_sources",
        "perspective_clusters_synced",
        "merged_preliminary_divergences",
    )
    writes = (
        "qa_problems_found",
        "qa_corrections",
        "qa_corrected_article",
        "qa_divergences",
    )
    agent_role = "qa_analyze"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        # Build the article context the agent expects (V1 shape).
        writer_article = topic_bus.writer_article
        article_for_qa = {
            "headline": writer_article.headline,
            "subheadline": writer_article.subheadline,
            "body": writer_article.body,
            "summary": writer_article.summary,
            "sources": list(topic_bus.final_sources),
        }

        message = (
            "Check this article against the source material. Find errors and "
            "divergences. Apply corrections directly in the article when "
            "needed. Return only the keys per the schema."
        )
        result = await self.agent.run(
            message,
            context={
                "article": article_for_qa,
                "sources": list(topic_bus.final_sources),
                "preliminary_divergences": list(
                    topic_bus.merged_preliminary_divergences
                ),
                "position_clusters": list(topic_bus.perspective_clusters_synced),
                "missing_positions": list(topic_bus.perspective_missing_positions),
            },
        )
        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        problems = list(parsed.get("problems_found") or [])
        raw_corrections = list(parsed.get("qa_corrections") or [])
        corrections: list[Correction] = []
        for entry in raw_corrections:
            if not isinstance(entry, dict):
                continue
            corrections.append(
                Correction(
                    proposed_correction=str(entry.get("proposed_correction", "") or ""),
                    correction_needed=bool(entry.get("correction_needed", False)),
                )
            )
        divergences = list(parsed.get("divergences") or [])

        update: dict[str, Any] = {
            "qa_problems_found": problems,
            "qa_corrections": corrections,
            "qa_divergences": divergences,
        }

        # Mirror-pattern semantics: only write qa_corrected_article when the
        # agent emitted an `article` object AND at least one entry warrants a
        # body change. When every entry is a retraction (or array empty), or
        # the agent omitted `article` per the V2 prompt, leave the slot at
        # its empty default and let mirror_qa_corrected fill it from
        # writer_article downstream.
        any_fix = any(c.correction_needed for c in corrections)
        article = parsed.get("article")
        if any_fix and isinstance(article, dict) and article:
            update["qa_corrected_article"] = WriterArticle(
                headline=article.get("headline", "") or "",
                subheadline=article.get("subheadline", "") or "",
                body=article.get("body", "") or "",
                summary=article.get("summary", "") or "",
            )

        return topic_bus.model_copy(update=update)


# ---------------------------------------------------------------------------
# Wrapper: BiasLanguageStage  (topic, production + hydrated)
# ---------------------------------------------------------------------------


class BiasLanguageStage(_AgentStageBase):
    """Bias Language agent wrapper.

    Reads the post-mirror `qa_corrected_article` plus the slots that compose
    the deterministic bias_card context. Writes `bias_language_findings` and
    `bias_reader_note`. The bias_card context is built per V1 §870-944 via
    `_build_bias_card_for_agent_input`.
    """

    stage_kind = "topic"
    reads = (
        "qa_corrected_article",
        "final_sources",
        "perspective_clusters_synced",
        "perspective_missing_positions",
        "qa_problems_found",
        "qa_corrections",
        "qa_divergences",
        "coverage_gaps_validated",
    )
    writes = ("bias_language_findings", "bias_reader_note")
    agent_role = "bias_language"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        bias_card = _build_bias_card_for_agent_input(topic_bus)
        message = (
            "Analyze this article for linguistic bias. Identify loaded "
            "language and produce a brief reader-note."
        )
        result = await self.agent.run(
            message,
            context={
                "article_body": topic_bus.qa_corrected_article.body,
                "bias_card": bias_card,
            },
        )
        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        language_bias = parsed.get("language_bias") or {}
        if isinstance(language_bias, dict):
            findings = language_bias.get("findings") or []
        else:
            findings = []
        if not isinstance(findings, list):
            findings = []

        return topic_bus.model_copy(
            update={
                "bias_language_findings": findings,
                "bias_reader_note": parsed.get("reader_note", "") or "",
            }
        )


# ---------------------------------------------------------------------------
# Hydration phase helpers (V2-11a — internalized from former external module)
# ---------------------------------------------------------------------------


_PHASE1_USER_MESSAGE = (
    "Analyze the articles in the provided context per the STEPS and RULES in "
    "your system prompt. Return a single JSON object with one field: "
    "article_analyses."
)
_PHASE2_USER_MESSAGE = (
    "Synthesize cross-article observations from the provided article_analyses "
    "and article_metadata. Return a single JSON object with "
    "preliminary_divergences and coverage_gaps."
)
_PHASE1_MAX_RETRIES = 2

# Rule-6 enum from PHASE1.md.
_ACTOR_TYPE_ENUM: frozenset[str] = frozenset({
    "government",
    "legislature",
    "judiciary",
    "military",
    "industry",
    "civil_society",
    "academia",
    "media",
    "international_org",
    "affected_community",
})


class _AggregatorValidationError(ValueError):
    """Raised when the Aggregator's response violates Rule 1 or Rule 6."""


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    # Descending count, ascending key for ties. dict in Python 3.7+ preserves
    # insertion order, so the returned dict iterates in the documented order.
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return {key: count for key, count in items}


def _prepare_article(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": record.get("url"),
        "title": record.get("title"),
        "outlet": record.get("outlet"),
        "language": record.get("language"),
        "country": record.get("country"),
        "extracted_text": record.get("extracted_text"),
        "estimated_date": None,
    }


def _distribute_chunks(articles: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split articles into chunks of 5–10 items (1 chunk of N when N<5).

    Formula: ``num_chunks = max(1, ceil(N / 10))``. Remainder (``extras``)
    placed on the trailing chunks so chunks grow monotonically: e.g. N=11
    → [5, 6]; N=25 → [8, 8, 9].
    """
    n = len(articles)
    if n == 0:
        return []
    num_chunks = max(1, math.ceil(n / 10))
    base_size = n // num_chunks
    extras = n % num_chunks
    chunks: list[list[dict[str, Any]]] = []
    start = 0
    for i in range(num_chunks):
        size = base_size + (1 if i >= num_chunks - extras else 0)
        chunks.append(articles[start:start + size])
        start += size
    return chunks


def _build_article_metadata(
    successful: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "article_index": i,
            "language": r.get("language"),
            "country": r.get("country"),
            "outlet": r.get("outlet"),
        }
        for i, r in enumerate(successful)
    ]


def _validate_phase1_output(
    output: dict[str, Any],
    *,
    expected_count: int,
) -> tuple[list[dict[str, Any]], set[int]]:
    """Extract valid analyses and report missing chunk-local indices.

    Returns ``(analyses, missing_indices)``. Rule 6 (actor type enum) still
    raises — it is a structural content error that retry cannot fix.
    """
    analyses_raw = output.get("article_analyses")
    if not isinstance(analyses_raw, list):
        raise _AggregatorValidationError(
            "article_analyses missing or not a list"
        )
    valid: list[dict[str, Any]] = []
    seen: set[int] = set()
    for entry in analyses_raw:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("article_index")
        if not isinstance(idx, int) or not (0 <= idx < expected_count):
            continue
        if idx in seen:
            continue
        for actor in entry.get("actors_quoted") or []:
            if not isinstance(actor, dict):
                continue
            actor_type = actor.get("type")
            if actor_type not in _ACTOR_TYPE_ENUM:
                raise _AggregatorValidationError(
                    f"Rule 6 violation: invalid actor type {actor_type!r} "
                    f"(article_index={idx}, actor={actor.get('name')!r})"
                )
        seen.add(idx)
        valid.append(entry)
    missing = set(range(expected_count)) - seen
    return valid, missing


async def _call_phase1(
    assignment: dict[str, Any],
    articles: list[dict[str, Any]],
    *,
    agent: Agent,
) -> dict[str, Any]:
    payload = {
        "assignment": {
            "title": assignment.get("title"),
            "selection_reason": assignment.get("selection_reason"),
        },
        "articles": articles,
    }
    result = await agent.run(
        _PHASE1_USER_MESSAGE,
        context=payload,
    )
    structured = result.structured
    if not isinstance(structured, dict):
        raise _AggregatorValidationError(
            f"Phase 1 chunk returned no parseable JSON object for assignment "
            f"{assignment.get('title')!r}"
        )
    return structured


async def _run_phase1_chunk(
    assignment: dict[str, Any],
    chunk_articles: list[dict[str, Any]],
    *,
    chunk_idx: int,
    agent: Agent,
) -> list[dict[str, Any]]:
    """Run one Phase-1 call with up to two intelligent-retry follow-ups.

    Retries re-request only the missing article indices (re-indexed from 0
    in the retry call). Returns per-chunk analyses sorted by chunk-local
    article_index (0..len(chunk_articles)-1).
    """
    analyses: list[dict[str, Any]] = []
    remaining_articles = list(chunk_articles)
    remaining_original_positions = list(range(len(chunk_articles)))

    for attempt in range(_PHASE1_MAX_RETRIES + 1):
        output = await _call_phase1(assignment, remaining_articles, agent=agent)
        returned, missing_local = _validate_phase1_output(
            output, expected_count=len(remaining_articles),
        )

        for a in returned:
            local_idx = a["article_index"]
            chunk_local_idx = remaining_original_positions[local_idx]
            a["article_index"] = chunk_local_idx
            analyses.append(a)

        if not missing_local:
            break

        if attempt < _PHASE1_MAX_RETRIES:
            missing_global = sorted(
                remaining_original_positions[i] for i in missing_local
            )
            logger.warning(
                "Phase 1 chunk %d retry %d: missing chunk-local indices %s",
                chunk_idx, attempt + 1, missing_global,
            )
            missing_sorted = sorted(missing_local)
            remaining_articles = [remaining_articles[i] for i in missing_sorted]
            remaining_original_positions = [
                remaining_original_positions[i] for i in missing_sorted
            ]

    if len(analyses) != len(chunk_articles):
        got = sorted(a["article_index"] for a in analyses)
        missing = sorted(set(range(len(chunk_articles))) - set(got))
        raise _AggregatorValidationError(
            f"Rule 1 violation: chunk {chunk_idx} of {len(chunk_articles)} "
            f"articles got only {len(analyses)} analyses after "
            f"{_PHASE1_MAX_RETRIES} retries; still missing {missing}"
        )

    analyses.sort(key=lambda a: a["article_index"])
    return analyses


def _merge_phase1_results(
    phase1_results: list[list[dict[str, Any]]],
    chunks: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten chunk outputs to a single globally-indexed analyses array.

    Each chunk's per-article ``article_index`` is in [0..chunk_size-1]; the
    merged output rewrites to [0..N-1] across the full input corpus,
    preserving chunk order as provided by ``_distribute_chunks``.
    """
    merged: list[dict[str, Any]] = []
    global_offset = 0
    for chunk_analyses, chunk_articles in zip(phase1_results, chunks):
        for a in chunk_analyses:
            rewritten = dict(a)
            rewritten["article_index"] = a["article_index"] + global_offset
            merged.append(rewritten)
        global_offset += len(chunk_articles)
    merged.sort(key=lambda a: a["article_index"])
    return merged


async def _run_phase2_reducer(
    assignment: dict[str, Any],
    all_analyses: list[dict[str, Any]],
    article_metadata: list[dict[str, Any]],
    *,
    agent: Agent,
) -> dict[str, Any]:
    if not all_analyses:
        return {"preliminary_divergences": [], "coverage_gaps": []}
    payload = {
        "assignment": {
            "title": assignment.get("title"),
            "selection_reason": assignment.get("selection_reason"),
        },
        "article_analyses": all_analyses,
        "article_metadata": article_metadata,
    }
    logger.info("Phase 2 reducer: %d analyses input", len(all_analyses))
    result = await agent.run(
        _PHASE2_USER_MESSAGE,
        context=payload,
    )
    structured = result.structured
    if not isinstance(structured, dict):
        raise _AggregatorValidationError(
            f"Phase 2 reducer returned no parseable JSON object for assignment "
            f"{assignment.get('title')!r}"
        )
    return {
        "preliminary_divergences": list(
            structured.get("preliminary_divergences") or []
        ),
        "coverage_gaps": list(structured.get("coverage_gaps") or []),
    }


def _build_coverage_summary(prepared_dossier: dict[str, Any]) -> dict[str, Any]:
    """Compute the compact coverage summary for the Hydrated Researcher Planner.

    Args:
        prepared_dossier: The return value of ``build_prepared_dossier``.

    Returns:
        A dict with exactly five keys:
        ``total_sources`` (int),
        ``languages_covered`` (mapping iso_code → count),
        ``countries_covered`` (mapping country name → count),
        ``stakeholder_types_present`` (mapping actor type → count),
        ``coverage_gaps`` (list of strings, pass-through).

        All three count-dicts are ordered by descending count, then
        alphabetically for ties. Output is deterministic for a given input.
    """
    sources = prepared_dossier.get("sources") or []

    languages: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    stakeholder_types: Counter[str] = Counter()

    for source in sources:
        language = source.get("language")
        if language:
            languages[language] += 1
        country = source.get("country")
        if country:
            countries[country] += 1
        for actor in source.get("actors_quoted") or []:
            if not isinstance(actor, dict):
                continue
            actor_type = actor.get("type")
            if actor_type:
                stakeholder_types[actor_type] += 1

    return {
        "total_sources": len(sources),
        "languages_covered": _sorted_counter(languages),
        "countries_covered": _sorted_counter(countries),
        "stakeholder_types_present": _sorted_counter(stakeholder_types),
        "coverage_gaps": list(prepared_dossier.get("coverage_gaps") or []),
    }


# ---------------------------------------------------------------------------
# Wrapper: ResearcherHydratedPlanStage  (topic, hydrated only)
# ---------------------------------------------------------------------------


class ResearcherHydratedPlanStage(_AgentStageBase):
    """Researcher-Plan-Hydrated agent wrapper. Identical to ResearcherPlan
    except the context includes a coverage_summary computed from
    `hydration_pre_dossier` so the planner can target gaps.

    V1 reference: pipeline_hydrated.py `_research_two_phase` planner half.
    """

    stage_kind = "topic"
    reads = ("editor_selected_topic", "hydration_pre_dossier")
    writes = ("researcher_plan_queries",)
    agent_role = "researcher_hydrated_plan"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        assignment = topic_bus.editor_selected_topic
        coverage_summary = _build_coverage_summary(
            topic_bus.hydration_pre_dossier.model_dump()
        )
        message = (
            "Plan multilingual queries to gap-fill the existing pre-dossier. "
            f"Today is {run_bus.run_date}."
        )
        result = await self.agent.run(
            message,
            context={
                "title": assignment.title,
                "selection_reason": assignment.selection_reason,
                "raw_data": dict(assignment.raw_data or {}),
                "coverage_summary": coverage_summary,
                "today": run_bus.run_date,
            },
        )
        parsed = _parse_agent_output(result)
        queries = _unwrap_list(parsed, "queries")
        return topic_bus.model_copy(update={"researcher_plan_queries": queries})


# ---------------------------------------------------------------------------
# Wrapper: HydrationPhase1Stage  (topic, hydrated only)
# ---------------------------------------------------------------------------


class HydrationPhase1Stage(_AgentStageBase):
    """Hydration Phase 1 wrapper — runs the chunked + parallel +
    intelligent-retry orchestration from `src/hydration_aggregator.py`.

    Reads `editor_selected_topic`, `hydration_fetch_results` (filtered to
    success-only). Writes `hydration_phase1_analyses` (per-article extraction
    sorted by article_index 0..N-1).

    The agent is dependency-injected; the chunking / parallel-call /
    retry logic is reused from the existing module-level helpers
    (`_distribute_chunks`, `_run_phase1_chunk`, `_prepare_article`) so this
    wrapper does NOT reimplement them.
    """

    stage_kind = "topic"
    reads = ("editor_selected_topic", "hydration_fetch_results")
    writes = ("hydration_phase1_analyses",)
    agent_role = "hydration_aggregator_phase1"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        assignment = topic_bus.editor_selected_topic
        fetch_results = list(topic_bus.hydration_fetch_results or [])
        successful = [
            r for r in fetch_results if isinstance(r, dict) and r.get("status") == "success"
        ]
        if not successful:
            return topic_bus.model_copy(update={"hydration_phase1_analyses": []})

        articles = [_prepare_article(r) for r in successful]
        chunks = _distribute_chunks(articles)

        assignment_dict = {
            "title": assignment.title,
            "selection_reason": assignment.selection_reason,
        }
        chunk_results = await asyncio.gather(
            *[
                _run_phase1_chunk(
                    assignment_dict, chunk, chunk_idx=i + 1, agent=self.agent
                )
                for i, chunk in enumerate(chunks)
            ]
        )
        all_analyses = _merge_phase1_results(chunk_results, chunks)
        return topic_bus.model_copy(update={"hydration_phase1_analyses": all_analyses})


# ---------------------------------------------------------------------------
# Wrapper: HydrationPhase2Stage  (topic, hydrated only)
# ---------------------------------------------------------------------------


class HydrationPhase2Stage(_AgentStageBase):
    """Hydration Phase 2 reducer wrapper — single agent call over the merged
    Phase 1 corpus + per-article metadata, producing preliminary_divergences
    and coverage_gaps.

    Reads `editor_selected_topic`, `hydration_phase1_analyses`,
    `hydration_fetch_results` (for metadata: language, country, outlet of
    successful fetches). Writes `hydration_phase2_corpus`.

    V1 reference: `src/hydration_aggregator._run_phase2_reducer` (lines
    397-430). The wrapper builds the article_metadata list from
    success-only fetches and delegates to the existing helper.
    """

    stage_kind = "topic"
    reads = (
        "editor_selected_topic",
        "hydration_phase1_analyses",
        "hydration_fetch_results",
    )
    writes = ("hydration_phase2_corpus",)
    agent_role = "hydration_aggregator_phase2"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        assignment = topic_bus.editor_selected_topic
        successful = [
            r
            for r in (topic_bus.hydration_fetch_results or [])
            if isinstance(r, dict) and r.get("status") == "success"
        ]
        all_analyses = list(topic_bus.hydration_phase1_analyses or [])
        if not all_analyses:
            return topic_bus.model_copy(
                update={"hydration_phase2_corpus": HydrationPhase2Corpus()}
            )

        metadata = _build_article_metadata(successful)
        out = await _run_phase2_reducer(
            {
                "title": assignment.title,
                "selection_reason": assignment.selection_reason,
            },
            all_analyses,
            metadata,
            agent=self.agent,
        )
        corpus = HydrationPhase2Corpus(
            preliminary_divergences=list(out.get("preliminary_divergences") or []),
            coverage_gaps=list(out.get("coverage_gaps") or []),
        )
        return topic_bus.model_copy(update={"hydration_phase2_corpus": corpus})


# ---------------------------------------------------------------------------
# Wrapper: PerspectiveSyncStage  (topic, hydrated only)
# ---------------------------------------------------------------------------


class PerspectiveSyncStage(_AgentStageBase):
    """Perspective-Sync agent wrapper. Eligibility-gated on QA having
    proposed corrections; if not, the agent is not called and the slot is
    left as-is.

    Reads `perspective_clusters`, `qa_corrected_article`, `qa_problems_found`,
    `qa_corrections`. Writes `perspective_clusters_synced` (the
    fully merged per-element list when corrections triggered the run; left
    untouched when the gate skipped the call).

    V1 reference: pipeline_hydrated.py `_run_perspektiv_sync` lines 720-836,
    `merge_perspektiv_deltas` line 233 (ported as `_merge_perspective_deltas`).

    Stage-order in the hydrated runner (V2-10): `mirror_perspective_synced`
    runs **twice** — first immediately after `enrich_perspective_clusters`
    (the slot is empty there; mirror produces a 1:1 copy of
    `perspective_clusters`), then again after this stage (element-delta
    merge over the now-modified slot). `mirror_stage` is idempotent for
    both granularities, so the double dispatch is safe — when this wrapper
    skips via the eligibility gate, the second mirror pass is a no-op.

    Slot has `mirrors_from="perspective_clusters"` annotation in bus.py
    plus `optional_write` on the upstream slot — both writes are safe.
    """

    stage_kind = "topic"
    reads = (
        "perspective_clusters",
        "qa_corrected_article",
        "qa_problems_found",
        "qa_corrections",
    )
    writes = ("perspective_clusters_synced",)
    agent_role = "perspective_sync"  # V1 folder name; V2-07 anglicises

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        # Eligibility gate: skip the call when no entry warrants a body fix
        # (empty array, or every entry is a retraction).
        active_fixes = [
            c.proposed_correction
            for c in (topic_bus.qa_corrections or [])
            if c.correction_needed
        ]
        if not active_fixes:
            return topic_bus  # mirror stage downstream produces 1:1 copy

        message = (
            "Re-align the position clusters with the QA-corrected article. "
            "Emit only deltas — id plus changed fields."
        )
        result = await self.agent.run(
            message,
            context={
                "position_clusters": list(topic_bus.perspective_clusters),
                "article_body": topic_bus.qa_corrected_article.body,
                "qa_problems_found": list(topic_bus.qa_problems_found),
                "qa_proposed_corrections": active_fixes,
            },
        )
        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        synced = _merge_perspective_deltas(
            {"position_clusters": list(topic_bus.perspective_clusters)},
            parsed,
        )
        return topic_bus.model_copy(
            update={
                "perspective_clusters_synced": list(
                    synced.get("position_clusters") or []
                )
            }
        )


__all__ = [
    "BiasLanguageStage",
    "CuratorStage",
    "EditorStage",
    "HydrationPhase1Stage",
    "HydrationPhase2Stage",
    "PerspectiveStage",
    "PerspectiveSyncStage",
    "QaAnalyzeStage",
    "ResearcherAssembleStage",
    "ResearcherHydratedPlanStage",
    "ResearcherPlanStage",
    "WriterStage",
]
