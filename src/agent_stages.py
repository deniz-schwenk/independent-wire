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
- _enrich_curator_output            src/pipeline.py:1698-1792
- _attach_raw_data_from_curated     src/pipeline.py:1928-1988
- editorial_conference id/slug      src/pipeline.py:2042-2102

Brief 5 cutover removed three helpers tied to the single-pass V1
``CuratorStage``: ``_prepare_curator_input``,
``_recover_truncated_cluster_assignments``, ``_rebuild_curator_source_ids``.
The triple-stage Curator (pre-cluster → discovery → gravitational →
assemble) doesn't need them — input compression is the pre-cluster
top-K-by-centroid step, and source-id attachment is the gravitational-
assign output. The five V1-era calibration scripts that imported them
(``smoke_curator``, ``smoke_curator_preprod_2026-05-12``,
``curator_shadow``, ``audit_v4pro_variance``, ``eval_curator_models``)
were deleted in the same commit.
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
from typing import Any, Callable, Optional

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
    WhatIsMissing,
    WriterArticle,
)
from src.outlet_registry import lookup_outlet
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

    async def _call_with_empty_retry(
        self,
        *,
        message: str,
        context: dict[str, Any],
        is_empty: Callable[[Any], bool],
        log_label: str,
        max_attempts: int = 3,
    ) -> tuple[Any, int, float, int]:
        """Call ``self.agent.run()`` up to ``max_attempts``; retry when the
        parsed output satisfies the ``is_empty`` predicate.

        Mitigation for DeepSeek's cache-cold empty-emission mode
        (originally surfaced on `dskflash-t05-rmedium` in the Curator
        stage). Each retry is a fresh OpenRouter call so provider
        routing varies between attempts. No sleep — the empty mode is
        cache-cold-correlated and the mitigation we want is
        provider-routing re-roll, not cache warm-up.

        Returns ``(last_result, attempts_used, total_cost_usd, total_tokens_used)``.
        The caller parses ``last_result`` and decides the downstream
        action (write to bus, fall through with empty payload so a
        postcondition downstream fires loud, etc.).
        """
        return await _call_agent_with_empty_retry(
            agent=self.agent,
            message=message,
            context=context,
            is_empty=is_empty,
            log_label=log_label,
            max_attempts=max_attempts,
        )


async def _call_agent_with_empty_retry(
    *,
    agent: Agent,
    message: str,
    context: dict[str, Any],
    is_empty: Callable[[Any], bool],
    log_label: str,
    max_attempts: int = 3,
) -> tuple[Any, int, float, int]:
    """Module-level twin of ``_AgentStageBase._call_with_empty_retry``.

    Same semantics, but takes ``agent`` as an explicit argument so
    non-method callers (e.g. the parallel per-chunk helpers in
    `HydrationPhase1Stage`) can use it without binding to a stage
    instance.
    """
    total_cost = 0.0
    total_tokens = 0
    last_result: Any = None
    attempts_used = 0
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        result = await agent.run(message, context=context)
        total_cost += float(getattr(result, "cost_usd", 0.0) or 0.0)
        total_tokens += int(getattr(result, "tokens_used", 0) or 0)
        last_result = result

        parsed = _parse_agent_output(result)
        if not is_empty(parsed):
            break

        if attempt < max_attempts:
            logger.warning(
                "%s: empty output on attempt %d/%d "
                "(response_id=%s, tokens=%d) — retrying",
                log_label,
                attempt,
                max_attempts,
                getattr(result, "response_id", None) or "?",
                int(getattr(result, "tokens_used", 0) or 0),
            )
        else:
            logger.error(
                "%s: empty output on all %d attempts "
                "(last response_id=%s) — downstream gate will fire loud",
                log_label,
                max_attempts,
                getattr(result, "response_id", None) or "?",
            )
    return last_result, attempts_used, total_cost, total_tokens


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



def _enrich_curator_output(
    topics: list[dict],
    raw_findings: list[dict],
    *,
    sources_json_path: Path | None = None,
) -> list[dict]:
    """Add geographic_coverage / missing_perspectives / languages /
    source_diversity deterministically. V1: src/pipeline.py:1698-1792.

    Outlet metadata (``tier``, ``editorial_independence``) is looked up
    per finding via :func:`src.outlet_registry.lookup_outlet` against
    the finding's ``source_url`` — the registry is the single source of
    truth (migration 2026-05-29). ``sources_json_path`` is retained on
    the signature for backwards compatibility but no longer consulted;
    callers passing a tmp_path against the legacy shape will see fields
    default to ``None``.
    """
    del sources_json_path  # legacy parameter; retained for API stability

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
            url = finding.get("source_url", "") or ""
            entry = lookup_outlet(url) if isinstance(url, str) and url else None
            topic_sources.append(
                {
                    "name": sname,
                    "tier": (entry or {}).get("tier"),
                    "editorial_independence": (entry or {}).get(
                        "editorial_independence"
                    ),
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
        # `missing_perspectives` is the Curator's prose only. We deliberately do
        # NOT fold a deterministic geography string (missing_regions /
        # missing_languages) into it: the Editor runs before hydration/research/
        # source-merge, so that geography is provisional and was the vector for a
        # shipped "East Asian sources" hallucination. The field passes through
        # unchanged when the Curator provided prose, and is left unset otherwise.
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

# Fields the Editor *agent* is allowed to see — exactly the per-topic inputs the
# editor prompt declares. EditorStage projects each curator_topics entry down to
# this allow-list before handing it to the agent, so the agent cannot cite a
# provisional source_count or read outlet names out of source_diversity /
# source_ids. Allow-list (not deny-list): a future enrichment field is withheld
# by default until it is explicitly added here and to the prompt. The full
# curator_topics dicts are untouched — the deterministic pre-sort and
# _attach_raw_data_from_curated still see source_count / source_diversity /
# source_ids.
#
# missing_regions / missing_languages are withheld for the same "provisional"
# reason as source_count: the Editor runs BEFORE hydration/research/source-
# merge, so this geography is the Curator's provisional set, not the final TP
# source set. Feeding it to the agent caused a shipped hallucination ("East
# Asian sources" on a topic with none in the final set). geographic_coverage
# and languages stay — they are a legitimate breadth signal for the selection
# decision.
#
# topic_id is the exception to "originary output only": it is a pass-through
# identity the agent is expected to echo verbatim (the established ID-key
# pattern), so it must be in the agent view for the Editor to copy it back. The
# strict EDITOR_SCHEMA forces the field; Python then joins raw_data and
# hydration URLs on it, independent of any Editor title rewrite
# (TASK-CLUSTER-ID-JOIN).
_EDITOR_AGENT_TOPIC_FIELDS: tuple[str, ...] = (
    "topic_id",
    "title",
    "summary",
    "geographic_coverage",
    "languages",
    "missing_perspectives",
)


def _attach_raw_data_from_curated(
    raw_assignments: list[dict], curated_topics: list[dict]
) -> None:
    """Attach Curator's enrichment to Editor's assignments in place.

    Match by the deterministic ``topic_id`` join key first (echoed verbatim
    by the Editor, survives any title rewrite). The exact-title → slug path
    is retained only as a loud fallback, used when an assignment's topic_id
    is missing or unknown — see TASK-CLUSTER-ID-JOIN. V1: src/pipeline.py:
    1928-1988."""

    def _extract(t: dict) -> dict:
        return {k: t[k] for k in _CURATOR_RAW_DATA_FIELDS if k in t}

    id_lookup: dict[str, dict] = {}
    title_lookup: dict[str, dict] = {}
    slug_buckets: dict[str, list[dict]] = {}
    for t in curated_topics:
        if not isinstance(t, dict):
            continue
        title = t.get("title") or ""
        raw_data = _extract(t)
        tid = t.get("topic_id") or ""
        if tid and tid not in id_lookup:
            id_lookup[tid] = raw_data
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
        # Primary: deterministic topic_id join. No fallback warning fires
        # when this succeeds — the linkage is title-rewrite-proof.
        tid = a.get("topic_id") or ""
        if tid and tid in id_lookup:
            a["raw_data"] = id_lookup[tid]
            continue
        # Fallback: topic_id missing or unknown → demote to the fragile
        # title/slug join, loudly. Name the assignment (topic_id + title) so
        # the fallback is never silent.
        logger.warning(
            "editor assignment (topic_id=%r, title=%r) did not match a "
            "curated topic by topic_id; falling back to title/slug join",
            tid,
            title,
        )
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
                # Preserve the Curator join key echoed by the Editor so the
                # hydration-URL join (attach_hydration_urls_to_assignments)
                # can match on it after this stage. (TASK-CLUSTER-ID-JOIN)
                "topic_id": a.get("topic_id", "") or "",
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
                "topic_id": a.get("topic_id", "") or "",
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
# Top-K-by-Centroid compression helpers — shared with CuratorTopicDiscoveryStage
# (Brief 4 of docs/ADR-CURATOR-TRIPLE-STAGE.md).
# ---------------------------------------------------------------------------


SAMPLE_TITLES_PER_CLUSTER: int = 8
"""Top-K-by-Centroid compression parameter for
CuratorTopicDiscoveryStage. Pinned per TASK-CURATOR-TOPIC-DISCOVERY-
STAGE §"Top-K-by-Centroid compression": K=8 balances signal density
(≥5 titles to make a cluster's theme unambiguous) against tail
contamination (≥15 starts pulling in noisy tail titles) and total
input token budget (~250 clusters × 8 titles × ~20 tokens ≈ 40 K).
The cap binds only for clusters with >K findings; smaller clusters
pass through complete. Recalibration is a one-line change."""


def _topic_discovery_finding_text(finding: dict) -> str:
    """Same concatenation rule as Brief 1's pre_cluster and Brief 2's
    gravitational_assign — keeps finding embeddings comparable across
    the three stages sharing the fastembed singleton."""
    return (
        (finding.get("title") or "")
        + " "
        + (finding.get("summary") or "")
        + " "
        + (finding.get("description") or "")
    ).strip()


def _top_k_by_centroid(
    finding_indices: list[int],
    finding_matrix: "np.ndarray",  # type: ignore[name-defined]
    k: int,
) -> list[tuple[int, float]]:
    """Pure function — pick the ``k`` finding-indices closest to the
    cluster centroid. Returns ``[(finding_index, similarity), ...]``
    sorted by similarity descending with finding-index ascending as
    the deterministic tie-break.

    The cluster centroid is the mean of the cluster's finding
    embeddings, re-L2-normalised. Cosine similarity to the centroid is
    a single dot product per finding (vectors are already
    L2-normalised). If the cluster has ``≤ k`` findings, all are
    returned (no compression) — same ordering rule applies.

    Single-finding clusters: the centroid equals the lone vector, so
    cosine similarity is 1.0 and the function returns one entry.

    Test-friendly: the embedder is passed in as the matrix already, so
    fakes can construct deterministic vectors without going through
    fastembed."""
    import numpy as np

    n = len(finding_indices)
    if n == 0:
        return []
    sub = finding_matrix[finding_indices]
    centroid = sub.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    if norm > 0:
        centroid = centroid / norm
    sims = sub @ centroid  # (n,) cosine similarities

    # Sort by (sim desc, finding-index asc). The same np.lexsort
    # pattern Brief 2 uses for tie-break determinism — primary key
    # passed LAST.
    fi_arr = np.asarray(finding_indices, dtype=np.int64)
    order = np.lexsort((fi_arr, -sims))
    keep = min(k, n)
    selected = [(int(fi_arr[order[i]]), float(sims[order[i]])) for i in range(keep)]
    return selected


def _compress_pre_clusters_to_llm_input(
    pre_clusters: list[dict],
    findings: list[dict],
    finding_matrix: "np.ndarray",  # type: ignore[name-defined]
    *,
    k: int = SAMPLE_TITLES_PER_CLUSTER,
) -> list[dict]:
    """Build the ``micro_clusters[]`` array the new Curator prompt
    consumes. One entry per pre-cluster, in input order — the wrapper
    does not re-sort.

    Each entry: ``{id, size, sample_titles[]}``. ``sample_titles[]`` is
    the top-K-by-centroid sample drawn from the cluster's findings,
    titles only, in similarity-descending order with finding-index
    ascending tie-break. Findings whose ``title`` is empty after
    strip() are filtered out of the selection pool; if the entire
    cluster has no usable titles the entry still appears in the input
    with a single placeholder marker so the cluster is not silently
    dropped from the LLM's view."""
    PLACEHOLDER = "(no titles available)"
    micro_clusters: list[dict] = []
    for cluster in pre_clusters:
        source_ids = cluster.get("source_ids") or []
        # Resolve finding-NNN references and filter to non-empty titles
        candidates: list[int] = []
        for sid in source_ids:
            try:
                fi = int(str(sid).split("finding-")[-1])
            except (ValueError, IndexError):
                continue
            if not (0 <= fi < len(findings)):
                continue
            if not (findings[fi].get("title") or "").strip():
                continue
            candidates.append(fi)

        if not candidates:
            micro_clusters.append({
                "id": cluster.get("id", ""),
                "size": int(cluster.get("size", 0)),
                "sample_titles": [PLACEHOLDER],
            })
            continue

        selected = _top_k_by_centroid(candidates, finding_matrix, k)
        sample_titles = [findings[fi].get("title", "") for fi, _ in selected]
        micro_clusters.append({
            "id": cluster.get("id", ""),
            "size": int(cluster.get("size", 0)),
            "sample_titles": sample_titles,
        })
    return micro_clusters


class CuratorTopicDiscoveryStage(_AgentStageBase):
    """New LLM Topic-Discovery stage — Brief 4 of the triple-stage
    Curator (docs/ADR-CURATOR-TRIPLE-STAGE.md).

    Reads ``curator_findings`` and ``curator_pre_clusters`` (Brief 1's
    output). Compresses each micro-cluster into a top-K-by-centroid
    sample of titles, hands the compressed input to the LLM, and writes
    the discovered ``{topics: [{title, summary}]}`` to
    ``curator_discovered_topics``. No per-finding assignment, no
    relevance_score — assignment is Brief 2's job; enrichment is Brief
    5's job.

    The fastembed singleton is shared with the coherence stage, the
    pre-cluster stage, and the gravitational-assign stage (one ONNX
    session per process). Tests inject a fake embedder via the
    ``embedder`` keyword and a fake agent via the ``agent`` keyword;
    production omits both — singleton + production constants.

    Wired into ``build_production_stages`` and ``build_hydrated_stages``
    (Brief 5 cutover). The legacy single-pass ``CuratorStage`` and the
    passive ``measure_cluster_coherence`` were both removed at the
    same time."""

    stage_kind = "run"
    reads = ("curator_findings", "curator_findings_clustering", "curator_pre_clusters")
    writes = ("curator_discovered_topics",)
    agent_role = "curator_topic_discovery"

    def __init__(
        self,
        agent: Agent,
        *,
        embedder: Any = None,
        sample_titles_per_cluster: int = SAMPLE_TITLES_PER_CLUSTER,
    ) -> None:
        self.agent = agent
        self._embedder = embedder
        self.k = sample_titles_per_cluster

    def _get_embedder(self):
        if self._embedder is not None:
            return self._embedder
        # Lazy import to avoid pulling fastembed at module import time
        from src.stages.coherence import _get_default_embedder

        return _get_default_embedder()

    async def __call__(self, run_bus: RunBus) -> RunBus:
        import time

        import numpy as np

        from src.stages.coherence import _cosine_normalized
        from src.stages.translate_sidecar import clustering_findings

        findings = list(run_bus.curator_findings or [])
        # Translate-to-English sidecar (TASK-CLUSTER-TRANSLATE-SIDECAR): when the
        # flag-gated sidecar populated curator_findings_clustering, the Curator
        # discovers topics from English-normalised titles (both the centroid
        # embedding and the sample_titles handed to the LLM). Index-aligned with
        # curator_findings, so finding-NNN references stay correct. Default-off:
        # falls through to native text byte-for-byte.
        clustering_source = clustering_findings(run_bus)
        text_source = clustering_source if clustering_source is not None else findings
        pre_clusters_record = run_bus.curator_pre_clusters or {}
        pre_clusters = list(pre_clusters_record.get("clusters") or [])
        run_date = run_bus.run_date or ""

        agent_name = getattr(self.agent, "name", self.agent_role)
        model_name = getattr(self.agent, "model", "")
        temperature = getattr(self.agent, "temperature", None)
        max_tokens = getattr(self.agent, "max_tokens", None)
        reasoning = getattr(self.agent, "reasoning", None)

        meta_common: dict[str, Any] = {
            "agent_name": agent_name,
            "model_name": model_name,
            "params": {
                "temperature": temperature,
                "max_tokens": max_tokens,
                "reasoning": reasoning,
            },
            "sample_titles_per_cluster": self.k,
        }

        # Empty pre-clusters → no LLM call, empty record
        if not pre_clusters:
            run_bus.curator_discovered_topics = {
                **meta_common,
                "wall_seconds": 0.0,
                "llm_cost_usd": 0.0,
                "tokens_used": 0,
                "n_micro_clusters_input": 0,
                "n_topics": 0,
                "topics": [],
            }
            logger.info(
                "CuratorTopicDiscoveryStage: 0 pre-clusters → no LLM call"
            )
            return run_bus

        t0 = time.monotonic()
        emb = self._get_embedder()

        # Embed every finding once — cluster lookups operate on the
        # finding-index matrix. Empty-title findings still occupy a
        # row so finding-index → row-index is the identity (the
        # filter happens inside _compress_pre_clusters_to_llm_input).
        finding_texts = [_topic_discovery_finding_text(f) for f in text_source]
        finding_matrix = _cosine_normalized(emb.embed_batch(finding_texts))

        micro_clusters_input = _compress_pre_clusters_to_llm_input(
            pre_clusters, text_source, finding_matrix, k=self.k
        )

        message = (
            "Discover today's topics from the supplied micro-clusters. "
            "Output JSON: {topics: [{title, summary}]}."
        )
        context = {
            "run_date": run_date,
            "micro_clusters": micro_clusters_input,
        }

        # Empty-output retry: dskflash-t05-rmedium has a ~33 % cache-cold
        # empty-emission rate (observed 28/0/26 across 3 isolated live
        # invocations on 2026-05-19). The 27-rep variance smoke did not
        # surface the mode. Up to 3 attempts; each retry is a fresh
        # OpenRouter call so provider routing varies. After 3 empty
        # attempts, fall through with an empty list and let
        # assemble_curator_topics' postcondition fail loud.
        def _is_empty_topics(parsed: Any) -> bool:
            if isinstance(parsed, dict):
                topics_raw = parsed.get("topics", []) or []
            elif isinstance(parsed, list):
                topics_raw = parsed
            else:
                return True
            for entry in topics_raw:
                if isinstance(entry, dict) and (entry.get("title") or "").strip():
                    return False
            return True

        result, attempts_used, total_cost, total_tokens = (
            await self._call_with_empty_retry(
                message=message,
                context=context,
                is_empty=_is_empty_topics,
                log_label="CuratorTopicDiscoveryStage",
            )
        )

        parsed = _parse_agent_output(result)
        if isinstance(parsed, dict):
            topics_raw = parsed.get("topics", []) or []
        elif isinstance(parsed, list):
            # Defensive: fall back if the LLM emits a bare list
            topics_raw = parsed
        else:
            topics_raw = []

        topics_clean: list[dict] = []
        for entry in topics_raw:
            if not isinstance(entry, dict):
                continue
            title = (entry.get("title") or "").strip()
            summary = (entry.get("summary") or "").strip()
            if not title:
                continue
            topics_clean.append({"title": title, "summary": summary})

        wall = time.monotonic() - t0

        run_bus.curator_discovered_topics = {
            **meta_common,
            "wall_seconds": round(wall, 3),
            "llm_cost_usd": total_cost,
            "tokens_used": total_tokens,
            "n_micro_clusters_input": len(micro_clusters_input),
            "n_topics": len(topics_clean),
            "n_attempts": attempts_used,
            "topics": topics_clean,
        }
        logger.info(
            "CuratorTopicDiscoveryStage: %d micro-clusters → %d topics "
            "(%.2fs, $%.4f, %d attempt%s)",
            len(micro_clusters_input), len(topics_clean), wall,
            total_cost, attempts_used, "" if attempts_used == 1 else "s",
        )
        return run_bus


# ---------------------------------------------------------------------------
# Wrapper: AssignClustersStage  (run-stage) — TASK-CLUSTER-LLM-ASSIGNMENT
# ---------------------------------------------------------------------------


class AssignClustersStage(_AgentStageBase):
    """LLM-based cluster→topic assignment — Hypothesis 2 of the cluster-
    level pivot (docs/cluster-level-gravitation-2026-05-17/conclusion.md
    deferred Hypothesis 2 to a separate brief; this is that brief).

    Reads:
        - ``curator_pre_clusters`` — Brief 1 micro-clusters (id, size,
          source_ids[]) — for the cluster IDs and member finding lookup.
        - ``curator_findings`` — for finding-title text and embeddings
          used by the shared top-K-by-centroid sample-title helper.
        - ``curator_discovered_topics`` — Brief 4 topic list (title +
          summary) passed to the LLM as the universe of topic indices.

    Writes ``curator_cluster_assignments_llm`` — the raw LLM
    ``{assignments[]}`` plus call metadata + the deterministically-derived
    orphan list (every input cluster_id that does not appear in
    assignments[]).

    The sample-title compression reuses
    ``_compress_pre_clusters_to_llm_input`` (the same K=8 top-K-by-
    centroid helper as ``CuratorTopicDiscoveryStage``) so the LLM input
    is shape-consistent across the two stages.

    Coexists with the deterministic ``gravitational_assign`` in the
    codebase; only the opt-in evaluation stage list
    ``build_production_stages_llm_assignment`` wires this stage.
    Production keeps Brief 5b's pinned T=0.55 finding-level path until
    the architect picks Branch A in TASK-CLUSTER-LLM-ASSIGNMENT Phase 3.
    """

    stage_kind = "run"
    reads = (
        "curator_findings",
        "curator_pre_clusters",
        "curator_discovered_topics",
    )
    writes = ("curator_cluster_assignments_llm",)
    agent_role = "assign_clusters"

    def __init__(
        self,
        agent: Agent,
        *,
        embedder: Any = None,
        sample_titles_per_cluster: int = SAMPLE_TITLES_PER_CLUSTER,
    ) -> None:
        self.agent = agent
        self._embedder = embedder
        self.k = sample_titles_per_cluster

    def _get_embedder(self):
        if self._embedder is not None:
            return self._embedder
        from src.stages.coherence import _get_default_embedder

        return _get_default_embedder()

    async def __call__(self, run_bus: RunBus) -> RunBus:
        import time

        from src.stages.coherence import _cosine_normalized

        findings = list(run_bus.curator_findings or [])
        pre_clusters_record = run_bus.curator_pre_clusters or {}
        pre_clusters = list(pre_clusters_record.get("clusters") or [])
        discovered_record = run_bus.curator_discovered_topics or {}
        topics = list(discovered_record.get("topics") or [])

        model_name = getattr(self.agent, "model", "")
        temperature = getattr(self.agent, "temperature", None)
        max_tokens = getattr(self.agent, "max_tokens", None)
        reasoning = getattr(self.agent, "reasoning", None)
        top_p = getattr(self.agent, "top_p", None)

        meta_common: dict[str, Any] = {
            "llm_model": model_name,
            "params": {
                "temperature": temperature,
                "reasoning": reasoning,
                "top_p": top_p,
                "max_tokens": max_tokens,
            },
            "n_clusters_input": len(pre_clusters),
            "n_topics_input": len(topics),
        }

        # Empty inputs → no LLM call, empty record
        if not pre_clusters or not topics:
            run_bus.curator_cluster_assignments_llm = {
                **meta_common,
                "wall_seconds": 0.0,
                "llm_cost_usd": 0.0,
                "llm_input_tokens": 0,
                "llm_output_tokens": 0,
                "n_clusters_assigned": 0,
                "n_clusters_orphan": len(pre_clusters),
                "assignments": [],
                "orphan_cluster_ids": [
                    c.get("id", "") for c in pre_clusters if c.get("id")
                ],
            }
            logger.info(
                "AssignClustersStage: empty input "
                "(pre_clusters=%d, topics=%d) → no LLM call",
                len(pre_clusters), len(topics),
            )
            return run_bus

        t0 = time.monotonic()
        emb = self._get_embedder()

        # Re-embed findings once (singleton ONNX session is shared with
        # the other Curator-side stages). The matrix is per-finding-
        # index; the cluster compression helper handles the
        # finding-NNN → row-index resolution and the empty-title filter.
        finding_texts = [_topic_discovery_finding_text(f) for f in findings]
        finding_matrix = _cosine_normalized(emb.embed_batch(finding_texts))

        micro_clusters_input = _compress_pre_clusters_to_llm_input(
            pre_clusters, findings, finding_matrix, k=self.k
        )

        message = (
            "Assign each micro-cluster to the topic(s) it primarily belongs to. "
            "Output JSON: {assignments: [{cluster_id, topic_indices}]}."
        )
        context = {
            "topics": topics,
            "micro_clusters": micro_clusters_input,
        }
        result = await self.agent.run(message, context=context)

        parsed = _parse_agent_output(result)
        raw_assignments = _unwrap_list(parsed, "assignments")

        # Defensive normalisation — strict-mode schema enforces shape on
        # the model side, but parse-failure fallbacks can leak through.
        # Keep only entries that have a cluster_id mapping to an input
        # cluster and a non-empty integer topic_indices list within range.
        input_cluster_ids = {
            str(c.get("id", "")) for c in pre_clusters if c.get("id")
        }
        n_topics = len(topics)
        seen_cluster_ids: set[str] = set()
        assignments_out: list[dict] = []
        for entry in raw_assignments:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("cluster_id")
            if not isinstance(cid, str) or cid not in input_cluster_ids:
                continue
            if cid in seen_cluster_ids:
                continue
            raw_indices = entry.get("topic_indices") or []
            if not isinstance(raw_indices, list):
                continue
            indices: list[int] = []
            for ti in raw_indices:
                if isinstance(ti, bool):
                    continue
                if not isinstance(ti, int):
                    continue
                if 0 <= ti < n_topics and ti not in indices:
                    indices.append(ti)
            if not indices:
                continue
            seen_cluster_ids.add(cid)
            assignments_out.append({
                "cluster_id": cid,
                "topic_indices": indices,
            })

        orphan_cluster_ids = sorted(input_cluster_ids - seen_cluster_ids)

        wall = time.monotonic() - t0
        cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
        # AgentResult only carries `tokens_used` (the combined total) —
        # split between input/output isn't surfaced through the SDK call
        # chain, so we record the combined number in both slots and rely
        # on the LLM-provider invoice for the split when needed. The
        # explicit field names keep the smoke-summary table aligned with
        # the brief's contract.
        tokens_used = int(getattr(result, "tokens_used", 0) or 0)

        run_bus.curator_cluster_assignments_llm = {
            **meta_common,
            "wall_seconds": round(wall, 3),
            "llm_cost_usd": cost,
            "llm_input_tokens": tokens_used,
            "llm_output_tokens": tokens_used,
            "n_clusters_assigned": len(assignments_out),
            "n_clusters_orphan": len(orphan_cluster_ids),
            "assignments": assignments_out,
            "orphan_cluster_ids": orphan_cluster_ids,
        }
        logger.info(
            "AssignClustersStage: %d clusters × %d topics → %d assigned, "
            "%d orphan (%.2fs, $%.4f)",
            len(pre_clusters), n_topics, len(assignments_out),
            len(orphan_cluster_ids), wall, cost,
        )
        return run_bus


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

        # Project each candidate to the prompt-declared fields only. Build a
        # fresh copy — `curated` stays intact for the post-decision
        # _attach_raw_data_from_curated below (and the upstream pre-sort that
        # produced curator_topics). source_count / source_diversity /
        # source_ids are withheld so the agent's selection_reason cannot cite
        # provisional counts or outlet names.
        agent_topics = [
            {k: t[k] for k in _EDITOR_AGENT_TOPIC_FIELDS if k in t}
            for t in curated
            if isinstance(t, dict)
        ]

        message = (
            "Prioritize these topics for today's report. For each, assign a "
            "priority (1-10) and a selection_reason. Today's date is "
            f"{run_date}."
        )
        result = await self.agent.run(
            message,
            context={"topics": agent_topics, "previous_coverage": previous},
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
    bias_language LLM consumes as context.

    The cluster→actor mapping now lives in ``cluster.actor_ids`` (the
    canonical actor list is ``topic_bus.canonical_actors`` — the
    alias-resolved deduplicated list); ``distinct_actor_count``
    therefore reads ``len(canonical_actors)`` rather than walking a
    per-cluster leak loop. The prior ``representation_distribution``
    aggregate is gone — the bias-language brief does not reference it,
    and the bucket semantics it relied on were removed alongside the
    cluster ``representation`` field.
    """
    article = topic_bus.qa_corrected_article
    sources = list(topic_bus.final_sources or [])
    clusters = list(topic_bus.perspective_clusters_synced or [])
    actors = list(topic_bus.canonical_actors or [])

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

    distinct_actor_count = sum(
        1 for a in actors if isinstance(a, dict) and a.get("name")
    )

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
            "distinct_actor_count": distinct_actor_count,
        },
        "factual_divergences": list(topic_bus.qa_divergences or []),
    }


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
            "Extract sources, actors, and divergences."
        )
        context = {
            "assignment": {
                "title": assignment.title,
                "selection_reason": assignment.selection_reason,
            },
            "date": run_bus.run_date,
            "search_results": list(topic_bus.researcher_search_results),
        }

        # Empty-output retry: same defense-in-depth as the Curator stage
        # for DeepSeek's cache-cold empty-emission mode. Predicate is
        # `sources` empty — every researcher_assemble call is expected
        # to extract ≥1 source from the supplied search results;
        # 0 sources means the LLM dropped everything. After 3 empty
        # attempts the wrapper writes an empty dossier, and
        # merge_sources' downstream writes-postcondition on
        # `researcher_assemble_dossier` (no `optional_write`,
        # no `mirrors_from`) fires loud.
        def _is_empty_sources(parsed: Any) -> bool:
            if not isinstance(parsed, dict):
                return True
            return len(parsed.get("sources") or []) == 0

        result, attempts_used, _cost, _tokens = (
            await self._call_with_empty_retry(
                message=message,
                context=context,
                is_empty=_is_empty_sources,
                log_label="ResearcherAssembleStage",
            )
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

        # ``coverage_gaps`` deliberately not read from ``parsed`` —
        # the hydrated pipeline routes coverage_gaps through
        # HydrationPhase2 as the single source of truth. The field
        # stays on ``ResearcherAssembleDossier`` (defaults to empty
        # list) so the legacy non-hydrated stage list still
        # type-checks; if the LLM ignores the updated prompt and
        # still emits a ``coverage_gaps`` key, we drop it silently.
        dossier = ResearcherAssembleDossier(
            sources=sources,
            preliminary_divergences=list(parsed.get("preliminary_divergences") or []),
        )
        return topic_bus.model_copy(update={
            "researcher_assemble_dossier": dossier,
            "researcher_assemble_n_attempts": attempts_used,
        })


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
        "canonical_actors_stated",
        "canonical_actors_reported",
        "canonical_actors_mentioned",
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
                "canonical_actors_stated": list(
                    topic_bus.canonical_actors_stated
                ),
                "canonical_actors_reported": list(
                    topic_bus.canonical_actors_reported
                ),
                "canonical_actors_mentioned": list(
                    topic_bus.canonical_actors_mentioned
                ),
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

    Reads `editor_selected_topic`, `final_sources`, `canonical_actors`,
    `perspective_clusters_synced`, `perspective_missing_positions`,
    `merged_coverage_gaps`. Plus optional follow-up addendum loaded from
    `agents/writer/FOLLOWUP.md` when `editor_selected_topic.follow_up_to`
    is truthy.

    `canonical_actors` (populated upstream by resolve_actor_aliases via
    strict-merge) is the Writer's single source of speaker truth. The
    per-source `actors_quoted[]` field is dropped from the source projection
    before reaching the Writer because that field is pre-consolidation
    residue and re-introduces alias-name variant strings.

    Writes `writer_article`. The Writer agent has `tools=[]` configured at
    construction (V2-current). The Writer relies entirely on the pipeline-
    supplied input and does not perform any tool-mediated lookups. Per
    V2-03b stage order, final_sources already carries `src-NNN` ids, so
    the Writer emits `[src-NNN]` citations directly — V1's post-Writer
    `_merge_writer_sources` is structurally redundant in V2.
    """

    stage_kind = "topic"
    reads = (
        "editor_selected_topic",
        "final_sources",
        "canonical_actors",
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
            "sources": [
                {k: v for k, v in src.items() if k != "actors_quoted"}
                for src in topic_bus.final_sources
            ],
            "actors": list(topic_bus.canonical_actors),
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
    the deterministic bias_card context. Writes `bias_language_findings`,
    `bias_borderline_candidates` (the additive three-tier gray zone), and
    `bias_reader_note`. The bias_card context is built per V1 §870-944 via
    `_build_bias_card_for_agent_input`.
    """

    stage_kind = "topic"
    reads = (
        "qa_corrected_article",
        "final_sources",
        "canonical_actors",
        "perspective_clusters_synced",
        "qa_problems_found",
        "qa_corrections",
        "qa_divergences",
    )
    writes = (
        "bias_language_findings",
        "bias_borderline_candidates",
        "bias_reader_note",
    )
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
            borderline = language_bias.get("borderline") or []
        else:
            findings = []
            borderline = []
        if not isinstance(findings, list):
            findings = []
        if not isinstance(borderline, list):
            borderline = []

        return topic_bus.model_copy(
            update={
                "bias_language_findings": findings,
                "bias_borderline_candidates": borderline,
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


_PHASE1_EMPTY_MAX_ATTEMPTS = 3


def _phase1_chunk_is_empty(analyses: list[dict[str, Any]]) -> bool:
    """Empty-output predicate for one Phase-1 chunk response: every
    analysis returned with no quoted actors.

    Distinct from the missing-indices failure mode that
    `_run_phase1_chunk` retries internally. An all-empty chunk passes
    the missing-indices check (every article_index is present) but
    carries zero extracted content — the DeepSeek cache-cold empty-
    emission mode, mirroring what `dskflash-t05-rmedium` exhibited on
    the Curator stage. A chunk where even one article has at least one
    quoted actor is *not* empty here — legitimate articles can carry
    zero quotable actors (wire-feed factuals etc.), so we only retry
    when the ENTIRE chunk is content-empty.
    """
    if not analyses:
        return True
    return all(
        not (a.get("actors_quoted") or [])
        for a in analyses
        if isinstance(a, dict)
    )


async def _run_phase1_chunk_with_empty_retry(
    assignment: dict[str, Any],
    chunk_articles: list[dict[str, Any]],
    *,
    chunk_idx: int,
    agent: Agent,
    max_attempts: int = _PHASE1_EMPTY_MAX_ATTEMPTS,
) -> tuple[list[dict[str, Any]], int]:
    """Wrap `_run_phase1_chunk` with a per-chunk empty-output retry.

    The inner helper performs missing-index retries (an orthogonal
    failure mode: LLM dropped article indices from the response). The
    outer loop here retries the whole chunk when the *whole* response
    came back content-empty (every analysis with `actors_quoted=[]`).
    Each retry is a fresh OpenRouter call so provider routing varies.

    After `max_attempts` of all-empty output, the final attempt's
    analyses are returned and Phase-2 aggregation continues. Phase-2 is
    the downstream reducer and is robust to article-analyses with zero
    quoted actors — there is no postcondition gate inside Phase-1 that
    fires on this case; the ERROR log + the ``hydration_phase1_n_
    attempts_per_chunk`` slot on the bus are the loud signals.

    Returns ``(analyses, attempts_used)``. ``_AggregatorValidationError``
    from the inner helper propagates unchanged — truncation is a
    distinct failure that the empty-output retry does not address.
    """
    last_analyses: list[dict[str, Any]] = []
    attempts_used = 0
    for attempt in range(1, max_attempts + 1):
        attempts_used = attempt
        analyses = await _run_phase1_chunk(
            assignment, chunk_articles, chunk_idx=chunk_idx, agent=agent,
        )
        last_analyses = analyses

        if not _phase1_chunk_is_empty(analyses):
            break

        if attempt < max_attempts:
            logger.warning(
                "HydrationPhase1Stage: chunk %d empty output on attempt "
                "%d/%d (every article returned 0 quoted actors) — "
                "retrying",
                chunk_idx,
                attempt,
                max_attempts,
            )
        else:
            logger.error(
                "HydrationPhase1Stage: chunk %d empty output on all %d "
                "attempts — falling through with empty analyses",
                chunk_idx,
                max_attempts,
            )

    return last_analyses, attempts_used


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
            return topic_bus.model_copy(update={
                "hydration_phase1_analyses": [],
                "hydration_phase1_n_attempts_per_chunk": [],
            })

        articles = [_prepare_article(r) for r in successful]
        chunks = _distribute_chunks(articles)

        assignment_dict = {
            "title": assignment.title,
            "selection_reason": assignment.selection_reason,
        }
        chunk_results = await asyncio.gather(
            *[
                _run_phase1_chunk_with_empty_retry(
                    assignment_dict,
                    chunk,
                    chunk_idx=i + 1,
                    agent=self.agent,
                )
                for i, chunk in enumerate(chunks)
            ]
        )
        # Each gather element is (analyses, attempts_used).
        analyses_per_chunk = [r[0] for r in chunk_results]
        attempts_per_chunk = [r[1] for r in chunk_results]
        all_analyses = _merge_phase1_results(analyses_per_chunk, chunks)
        return topic_bus.model_copy(update={
            "hydration_phase1_analyses": all_analyses,
            "hydration_phase1_n_attempts_per_chunk": attempts_per_chunk,
        })


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
# Wrapper: ConsolidatorStage  (topic, production + hydrated)
# ---------------------------------------------------------------------------


class ConsolidatorStage(_AgentStageBase):
    """Consolidator agent wrapper. Owns the dossier's
    ``what_is_missing`` output — the deduplicated, classified view of
    what the corpus lacks.

    Reads ``perspective_missing_positions`` (structured, with
    ``type`` + ``description``) and ``merged_coverage_gaps`` (free-text
    strings). Calls the LLM once with both arrays as context; the agent
    classifies each entry as either a missing voice (stakeholder,
    region, language, or media sphere) or a missing topic (aspect,
    dimension, angle), and dedupes semantic overlaps across the two
    inputs. Writes ``what_is_missing`` (a :class:`WhatIsMissing` with
    two compact-English string arrays).

    Replaces three V1/V2 stages collapsed into one LLM call:
    ``PerspectiveSyncStage`` (LLM but produced no substantial deltas in
    practice), ``validate_coverage_gaps_stage`` (deterministic keyword
    matcher — over-aggressive on Cuba 2026-05-23), and
    ``consolidate_missing_coverage`` (Jaccard dedup — redundant once
    the LLM owns dedup). See ``REPORT-DIAGNOSTIC-2026-05-23.md`` for
    the underlying failure cases.

    Single LLM call, no chunking, no special retry logic — both inputs
    are small (typically <20 entries combined), output is a small
    two-array JSON object.
    """

    stage_kind = "topic"
    reads = ("perspective_missing_positions", "merged_coverage_gaps")
    writes = ("what_is_missing",)
    agent_role = "consolidator"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        message = (
            "Classify each gap entry as a missing voice or a missing "
            "topic, deduping semantic overlaps across the two inputs."
        )
        result = await self.agent.run(
            message,
            context={
                "perspective_missing_positions": list(
                    topic_bus.perspective_missing_positions or []
                ),
                "merged_coverage_gaps": list(
                    topic_bus.merged_coverage_gaps or []
                ),
            },
        )
        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        voices_raw = parsed.get("voices_missing") or []
        topics_raw = parsed.get("topics_missing") or []
        what = WhatIsMissing(
            voices_missing=[s for s in voices_raw if isinstance(s, str) and s],
            topics_missing=[s for s in topics_raw if isinstance(s, str) and s],
        )
        return topic_bus.model_copy(update={"what_is_missing": what})


# ---------------------------------------------------------------------------
# Wrapper: ResolveActorAliasesStage  (topic, production + hydrated)
# ---------------------------------------------------------------------------


def _actor_id_numeric_order(actor_id: str) -> int:
    """Return the numeric suffix of an `actor-NNN` ID, or a large
    sentinel for malformed IDs so they sort last and never beat a
    well-formed ID for canonical selection."""
    if not isinstance(actor_id, str):
        return 10**9
    if not actor_id.startswith("actor-"):
        return 10**9
    try:
        return int(actor_id[len("actor-"):])
    except ValueError:
        return 10**9


def _resolve_canonical_groups(
    valid_ids: set[str],
    aliases: list[dict[str, Any]],
) -> dict[str, str]:
    """Apply first-source-wins canonical selection over the agent's
    alias list. Builds a union-find over alias pairs (transitive
    closure) and picks the smallest numeric ID per group.

    Returns a mapping {actor_id -> canonical_id} that includes only
    aliased IDs (canonical IDs map to themselves and are NOT included).
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        # Iterative path-compression find.
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        # Compress.
        cur = x
        while parent.get(cur, cur) != cur:
            nxt = parent[cur]
            parent[cur] = root
            cur = nxt
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        # Smaller numeric ID becomes the new root (first-source-wins).
        if _actor_id_numeric_order(ra) <= _actor_id_numeric_order(rb):
            parent[rb] = ra
        else:
            parent[ra] = rb

    for entry in aliases:
        if not isinstance(entry, dict):
            continue
        a = entry.get("alias_id")
        b = entry.get("canonical_id")
        if not isinstance(a, str) or not isinstance(b, str):
            continue
        if a not in valid_ids or b not in valid_ids:
            # Defensive: drop pairs referencing IDs not in the input
            # final_actors[] list. Logged by the caller.
            continue
        if a == b:
            continue
        # Initialise both into the union-find before unioning.
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        union(a, b)

    # Build the alias_id -> canonical_id mapping. A node is "aliased"
    # iff its root is a different ID; canonical IDs are excluded.
    mapping: dict[str, str] = {}
    for node in parent:
        root = find(node)
        if node != root:
            mapping[node] = root
    return mapping


class ResolveActorAliasesStage(_AgentStageBase):
    """Actor-Alias Resolver wrapper. Reads `final_actors[]`, calls the
    Flash agent, applies first-source-wins canonical selection
    deterministically, and writes `canonical_actors[]` plus
    `actor_alias_mapping[]`.

    Per ARCH-V2 §7.2 (TASK-RESOLVE-ACTOR-ALIASES): the resolver is
    non-destructive — `final_actors[]` survives unchanged as the pre-
    resolution audit artifact. Aliased IDs disappear from
    `canonical_actors[]`, leaving gaps in the numeric sequence.
    `actor_alias_mapping[]` documents every merge decision.

    Anonymous source-class labels (e.g. "Iranian military-linked
    sources") are flagged with `is_anonymous: true` on the canonical
    entry. Named individuals and specific institutions retain
    `is_anonymous: false`.

    Stage-order: runs after `consolidate_actors` and before
    `PerspectiveStage`. Phase 1 of the alias-resolver task ships the
    resolver only; consumer migration to `canonical_actors[]` is
    deferred to Phase 2.
    """

    stage_kind = "topic"
    reads = ("final_actors",)
    writes = ("canonical_actors", "actor_alias_mapping")
    agent_role = "resolve_actor_aliases"

    def __init__(self, agent: Agent) -> None:
        self.agent = agent

    async def __call__(
        self, topic_bus: TopicBus, run_bus: RunBusReadOnly
    ) -> TopicBus:
        final_actors = list(topic_bus.final_actors or [])
        if not final_actors:
            # No actors to resolve. Both output slots stay at their
            # typed-empty defaults; optional_write covers the no-write.
            return topic_bus

        message = (
            "Identify which actor entries refer to the same real-world "
            "entity. Flag entries whose name is a generic source-class "
            "label."
        )
        context = {"final_actors": final_actors}

        # Empty-output retry: defense-in-depth for the DeepSeek cache-cold
        # empty-emission mode. The brief-suggested predicate
        # (`canonical_actors` empty) does not work here — the LLM's raw
        # output carries `aliases` and `anonymous_flags`, NOT
        # `canonical_actors` (the wrapper derives canonical_actors below).
        # The realistic empty signal is: BOTH raw arrays empty AND the
        # input is large enough that genuine merges/anonymous-flags would
        # be expected. With ≤2 input actors, empty raw output is the
        # correct answer (nothing to merge) and we must not retry.
        input_actor_count = len(final_actors)

        def _is_empty_resolver(parsed: Any) -> bool:
            if input_actor_count < 3:
                return False
            if not isinstance(parsed, dict):
                return True
            aliases = parsed.get("aliases") or []
            anon = parsed.get("anonymous_flags") or []
            return len(aliases) == 0 and len(anon) == 0

        result, attempts_used, _cost, _tokens = (
            await self._call_with_empty_retry(
                message=message,
                context=context,
                is_empty=_is_empty_resolver,
                log_label="ResolveActorAliasesStage",
            )
        )

        parsed = _parse_agent_output(result) or {}
        if not isinstance(parsed, dict):
            parsed = {}

        valid_ids = {
            a.get("id")
            for a in final_actors
            if isinstance(a, dict) and isinstance(a.get("id"), str)
        }

        aliases_raw = parsed.get("aliases") or []
        if not isinstance(aliases_raw, list):
            aliases_raw = []
        anonymous_raw = parsed.get("anonymous_flags") or []
        if not isinstance(anonymous_raw, list):
            anonymous_raw = []

        # Normalise alias pairs into {alias_id -> canonical_id} via
        # union-find, applying first-source-wins (smaller numeric ID).
        alias_map = _resolve_canonical_groups(valid_ids, aliases_raw)

        # Anonymous flag set: only IDs present in the input list count;
        # anonymous IDs that get aliased away resolve to the canonical
        # entry (the canonical entry inherits the flag).
        anon_canonical_ids: set[str] = set()
        for raw_id in anonymous_raw:
            if not isinstance(raw_id, str):
                continue
            if raw_id not in valid_ids:
                continue
            canonical = alias_map.get(raw_id, raw_id)
            anon_canonical_ids.add(canonical)

        # Build canonical_actors[] in the same order as final_actors[].
        # Aliased entries are skipped; canonical entries absorb the
        # source_ids and quotes of every alias that maps to them.
        actors_by_id: dict[str, dict] = {}
        for entry in final_actors:
            if not isinstance(entry, dict):
                continue
            aid = entry.get("id")
            if isinstance(aid, str):
                actors_by_id[aid] = entry

        # Pre-collect aliases per canonical so we can union-merge in
        # input order while preserving determinism.
        aliases_by_canonical: dict[str, list[str]] = {}
        for alias_id, canonical_id in alias_map.items():
            aliases_by_canonical.setdefault(canonical_id, []).append(alias_id)
        # Sort each canonical's alias list by numeric order so the
        # resulting source_ids / quotes order is deterministic.
        for canonical_id in aliases_by_canonical:
            aliases_by_canonical[canonical_id].sort(
                key=_actor_id_numeric_order
            )

        canonical_actors: list[dict] = []
        for entry in final_actors:
            if not isinstance(entry, dict):
                continue
            aid = entry.get("id")
            if not isinstance(aid, str):
                continue
            # Skip aliased entries.
            if aid in alias_map:
                continue
            # Build canonical record from this entry as the seed.
            merged_source_ids: list[str] = list(entry.get("source_ids") or [])
            merged_quotes: list = list(entry.get("quotes") or [])
            for alias_id in aliases_by_canonical.get(aid, []):
                alias_entry = actors_by_id.get(alias_id)
                if not isinstance(alias_entry, dict):
                    continue
                for sid in alias_entry.get("source_ids") or []:
                    if isinstance(sid, str) and sid not in merged_source_ids:
                        merged_source_ids.append(sid)
                for q in alias_entry.get("quotes") or []:
                    merged_quotes.append(q)
            canonical_record = {
                "id": aid,
                "name": entry.get("name", ""),
                "role": entry.get("role", ""),
                "type": entry.get("type", ""),
                "source_ids": merged_source_ids,
                "quotes": merged_quotes,
                "is_anonymous": aid in anon_canonical_ids,
            }
            canonical_actors.append(canonical_record)

        # Build the audit trail. Sort by alias_id numeric order for
        # deterministic output regardless of agent emission order.
        actor_alias_mapping: list[dict] = []
        for alias_id in sorted(alias_map.keys(), key=_actor_id_numeric_order):
            alias_entry = actors_by_id.get(alias_id, {})
            actor_alias_mapping.append(
                {
                    "alias_id": alias_id,
                    "alias_name": alias_entry.get("name", "")
                    if isinstance(alias_entry, dict)
                    else "",
                    "canonical_id": alias_map[alias_id],
                }
            )

        n_anonymous = sum(1 for a in canonical_actors if a.get("is_anonymous"))
        logger.info(
            "resolve_actor_aliases: %d aliases merged into %d canonical "
            "actors, %d flagged anonymous",
            len(actor_alias_mapping),
            len(canonical_actors),
            n_anonymous,
        )

        return topic_bus.model_copy(
            update={
                "canonical_actors": canonical_actors,
                "actor_alias_mapping": actor_alias_mapping,
                "resolve_actor_aliases_n_attempts": attempts_used,
            }
        )


__all__ = [
    "AssignClustersStage",
    "BiasLanguageStage",
    "ConsolidatorStage",
    "CuratorTopicDiscoveryStage",
    "EditorStage",
    "HydrationPhase1Stage",
    "HydrationPhase2Stage",
    "PerspectiveStage",
    "QaAnalyzeStage",
    "ResearcherAssembleStage",
    "ResearcherHydratedPlanStage",
    "ResearcherPlanStage",
    "ResolveActorAliasesStage",
    "SAMPLE_TITLES_PER_CLUSTER",
    "WriterStage",
    "_compress_pre_clusters_to_llm_input",
    "_top_k_by_centroid",
    "_topic_discovery_finding_text",
]
