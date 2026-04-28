"""Shared helpers for resolving Curator-clustered article URLs.

The hydrated pipeline expects each :class:`~src.models.TopicAssignment` to
carry a ``raw_data["hydration_urls"]`` list — the article URLs that the
Curator originally grouped into the cluster the Editor turned into this
topic. The Editor strict-mode schema (see :data:`src.schemas.EDITOR_SCHEMA`)
does not carry the URLs forward, so the hydrated pipeline reconstructs
them from ``02-curator-topics-unsliced.json`` and ``raw/{date}/feeds.json``
before research runs.

This module exposes the reconstruction logic so it can be invoked from
both ``scripts/test_hydration_pipeline.py`` (the spike orchestrator)
and ``scripts/run.py`` via :class:`PipelineHydrated`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable

from src.models import TopicAssignment

logger = logging.getLogger(__name__)


_STOPWORDS = frozenset({
    "the", "a", "an", "of", "in", "on", "and", "or", "to", "for", "as", "is",
    "by", "at", "with", "from", "after", "into", "that", "which", "it", "its",
    "be", "are", "was", "were", "this", "over", "amid", "against", "about",
    "near", "upon", "has", "have", "had", "been", "being", "will", "shall",
})


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]+", text.lower())
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS}


def match_cluster(assignment_title: str, clusters: list[dict]) -> dict | None:
    """Match an Editor assignment back to its originating Curator cluster.

    Returns the highest-scoring cluster by token overlap, or ``None`` when
    no cluster shares at least two non-stopword terms with the assignment
    title (a low score indicates a noisy match rather than a real one).
    """
    a_tokens = _tokens(assignment_title)
    best: dict | None = None
    best_score = 0
    for cluster in clusters:
        score = len(a_tokens & _tokens(cluster.get("title", "")))
        if score > best_score:
            best_score = score
            best = cluster
    if best_score < 2:
        return None
    return best


def _load_country_lookup(sources_path: Path) -> dict[str, str | None]:
    try:
        data = json.loads(sources_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    feeds = data.get("feeds", []) if isinstance(data, dict) else []
    return {entry["name"]: entry.get("country") for entry in feeds}


def _build_hydration_urls(
    cluster: dict,
    feeds: list[dict],
    country_by_outlet: dict[str, str | None],
) -> list[dict]:
    urls: list[dict] = []
    for sid in cluster.get("source_ids", []):
        try:
            idx = int(sid.split("finding-")[-1])
        except (ValueError, IndexError):
            continue
        if not 0 <= idx < len(feeds):
            continue
        entry = feeds[idx]
        outlet = entry.get("source_name", "unknown")
        urls.append({
            "url": entry.get("source_url", ""),
            "outlet": outlet,
            "language": entry.get("language", "en"),
            "country": country_by_outlet.get(outlet),
            "title": entry.get("title"),
        })
    return urls


def attach_hydration_urls(
    assignments: Iterable[TopicAssignment],
    reuse_date: str,
    repo_root: Path,
) -> list[TopicAssignment]:
    """Attach ``hydration_urls`` to each assignment's ``raw_data`` in place.

    Reads ``output/{reuse_date}/02-curator-topics-unsliced.json``,
    ``raw/{reuse_date}/feeds.json``, and ``config/sources.json`` to
    reconstruct the article URL list for each cluster, then matches each
    assignment to a cluster by title-token overlap.

    Assignments that cannot be matched to any cluster are returned with
    an empty ``hydration_urls`` list — the hydrated researcher then
    runs in fail-soft mode (web search alone, no pre-dossier).
    """
    curator_path = repo_root / "output" / reuse_date / "02-curator-topics-unsliced.json"
    feeds_path = repo_root / "raw" / reuse_date / "feeds.json"
    sources_path = repo_root / "config" / "sources.json"

    if not curator_path.exists():
        raise FileNotFoundError(
            f"hydration_urls: missing {curator_path}; cannot reconstruct URLs"
        )
    if not feeds_path.exists():
        raise FileNotFoundError(
            f"hydration_urls: missing {feeds_path}; cannot reconstruct URLs"
        )

    clusters = json.loads(curator_path.read_text(encoding="utf-8"))
    feeds = json.loads(feeds_path.read_text(encoding="utf-8"))
    country_by_outlet = _load_country_lookup(sources_path)

    assignment_list = list(assignments)
    for assignment in assignment_list:
        cluster = match_cluster(assignment.title, clusters)
        if cluster is None:
            logger.warning(
                "hydration_urls: no cluster match for assignment %r (title=%r); "
                "hydrated research will run web-search-only",
                assignment.id, assignment.title,
            )
            urls: list[dict] = []
        else:
            urls = _build_hydration_urls(cluster, feeds, country_by_outlet)
            logger.info(
                "hydration_urls: %s → cluster %r: %d URLs",
                assignment.id, cluster.get("title"), len(urls),
            )
        raw_data = dict(assignment.raw_data or {})
        raw_data["hydration_urls"] = urls
        raw_data["source_count"] = raw_data.get("source_count", len(urls))
        assignment.raw_data = raw_data

    return assignment_list
