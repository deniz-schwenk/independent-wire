"""Deterministic translation of LLM cluster-level assignments into the
finding-level ``curator_topic_assignments`` slot — TASK-CLUSTER-LLM-
ASSIGNMENT.

Runs immediately after ``AssignClustersStage``. No LLM. Reads:

- ``curator_cluster_assignments_llm`` — the raw LLM output:
  ``{assignments[], orphan_cluster_ids[]}`` plus call metadata.
- ``curator_pre_clusters`` — for the cluster_id → source_ids[] lookup.
- ``curator_findings`` — for the orphan-list source_id construction.

Writes the existing ``curator_topic_assignments`` slot — same shape as
Brief 5b's ``gravitational_assign`` produces, so the downstream
``assemble_curator_topics`` stage consumes it unchanged. The
distinguishing fields:

- ``algorithm = "llm-cluster-assignment"`` (vs. ``"cosine-threshold-topk"``).
- ``params = {"llm_model", "temperature", "reasoning", "upstream_stage":
  "assign_clusters"}``.
- Per-assignment ``similarity = null`` and orphan ``best_similarity =
  null`` / ``best_topic_index = null`` — the LLM does not emit
  similarity scores; the field is preserved for shape compatibility.

Per-finding cap: the brief specifies ``PER_FINDING_CAP = 3`` applied
after cluster → finding propagation. With ``multi``-assignment from the
LLM (a cluster can land on multiple topics), a single finding can pick
up >1 topic; we keep the first ``PER_FINDING_CAP`` in the order topics
appeared in the LLM's ``topic_indices`` list (the LLM's emit order is
authoritative — no similarity-based tie-break exists).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.bus import RunBus
from src.stage import run_stage_def

logger = logging.getLogger(__name__)


ALGORITHM: str = "llm-cluster-assignment"

PER_FINDING_CAP: int = 3
"""Same cap as Brief 5b's deterministic ``gravitational_assign`` —
held at 3 so the cross-topic edge case is preserved. With the LLM
``single``-mode assignment the cap does not bind by construction
(every cluster lands on ≤ 1 topic so every finding inherits ≤ 1 topic).
``multi``-mode can in principle bind if a cluster lands on > 3 topics;
the prompt is conservative enough that this is rare in practice but the
cap is the architectural backstop."""


@run_stage_def(
    reads=(
        "curator_cluster_assignments_llm",
        "curator_pre_clusters",
        "curator_findings",
    ),
    writes=("curator_topic_assignments",),
)
async def cluster_to_finding_assignments(run_bus: RunBus) -> RunBus:
    """Translate cluster-level LLM assignments into the finding-level slot."""
    t0 = time.monotonic()

    llm_record = run_bus.curator_cluster_assignments_llm or {}
    assignments_in = list(llm_record.get("assignments") or [])
    orphan_cluster_ids = list(llm_record.get("orphan_cluster_ids") or [])
    llm_model = llm_record.get("llm_model", "")
    llm_params = llm_record.get("params") or {}

    pre_clusters_record = run_bus.curator_pre_clusters or {}
    pre_clusters = list(pre_clusters_record.get("clusters") or [])
    findings = list(run_bus.curator_findings or [])

    # Build cluster_id → list[source_id] index from the pre-cluster
    # record. The pre-cluster source_ids are already in the
    # ``finding-NNN`` convention shared across the Curator-side stages.
    cluster_index: dict[str, list[str]] = {}
    for c in pre_clusters:
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        sids = [s for s in (c.get("source_ids") or []) if isinstance(s, str)]
        cluster_index[cid] = sids

    n_topics_input = int(llm_record.get("n_topics_input", 0) or 0)

    meta_common: dict[str, Any] = {
        "algorithm": algo_name_for_metadata(),
        "params": {
            "llm_model": llm_model,
            "temperature": llm_params.get("temperature"),
            "reasoning": llm_params.get("reasoning"),
            "upstream_stage": "assign_clusters",
            "per_finding_cap": PER_FINDING_CAP,
        },
    }

    # Empty inputs → empty record with shape-compatible scaffolding
    if not assignments_in and not orphan_cluster_ids:
        run_bus.curator_topic_assignments = {
            **meta_common,
            "wall_seconds": round(time.monotonic() - t0, 3),
            "n_topics": n_topics_input,
            "n_findings": len(findings),
            "n_findings_assigned": 0,
            "n_orphans": 0,
            "mean_assignments_per_finding": 0.0,
            "topics": [
                {
                    "topic_index": ti,
                    "topic_title": "",
                    "n_assigned": 0,
                    "assignments": [],
                }
                for ti in range(n_topics_input)
            ],
            "orphans": [],
        }
        logger.info(
            "cluster_to_finding_assignments: empty record "
            "(assignments=0, orphans=0)"
        )
        return run_bus

    # Per-topic finding-id collection.
    # finding_to_topics[source_id] -> ordered list of topic_index in
    # LLM-emit order — cap enforcement reads off this list.
    finding_to_topics: dict[str, list[int]] = {}
    for entry in assignments_in:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("cluster_id")
        topic_indices = entry.get("topic_indices") or []
        if not isinstance(cid, str) or not isinstance(topic_indices, list):
            continue
        source_ids = cluster_index.get(cid, [])
        if not source_ids:
            continue
        for sid in source_ids:
            slot = finding_to_topics.setdefault(sid, [])
            for ti in topic_indices:
                if not isinstance(ti, int) or isinstance(ti, bool):
                    continue
                if ti in slot:
                    continue
                slot.append(ti)

    # Resolve the topic title strings from the source curator_discovered_topics
    # record so the per-topic dicts carry a human-readable title. The
    # gravitational-assign equivalent reads from curator_topics_unsliced
    # — but that slot is downstream of this stage, so we read the
    # discovered-topics record directly. Title is truncated to 200 chars
    # to match the gravitational equivalent.
    discovered_record = run_bus.curator_discovered_topics or {}
    discovered = list(discovered_record.get("topics") or [])

    def _topic_title(ti: int) -> str:
        if 0 <= ti < len(discovered):
            return (discovered[ti].get("title") or "")[:200]
        return ""

    # Apply the cap; bucket by topic_index.
    topic_buckets: dict[int, list[str]] = {ti: [] for ti in range(n_topics_input)}
    n_findings_with_assignment = 0
    n_assignments_total = 0
    for sid, topics in finding_to_topics.items():
        capped = topics[:PER_FINDING_CAP]
        if capped:
            n_findings_with_assignment += 1
        n_assignments_total += len(capped)
        for ti in capped:
            if ti in topic_buckets:
                topic_buckets[ti].append(sid)

    # Sort each topic's assignments by source_id ascending — purely
    # deterministic without a similarity score to sort by. The
    # gravitational stage sorts by similarity desc; here we sort by
    # finding-index asc as the only stable ordering available.
    def _finding_idx(sid: str) -> int:
        try:
            return int(sid.split("finding-")[-1])
        except (ValueError, IndexError):
            return 10**9

    topics_out: list[dict] = []
    for ti in range(n_topics_input):
        bucket = sorted(topic_buckets.get(ti, []), key=_finding_idx)
        topics_out.append({
            "topic_index": ti,
            "topic_title": _topic_title(ti),
            "n_assigned": len(bucket),
            "assignments": [
                {"source_id": sid, "similarity": None} for sid in bucket
            ],
        })

    # Orphans: findings whose cluster_id ended up in orphan_cluster_ids
    # become orphan entries. Findings whose cluster IS assigned but
    # whose specific (finding, topic) was capped out of every topic
    # never enter the orphan list — they are simply unassigned (still
    # better than orphan because the cluster did assign somewhere). The
    # brief's contract: every cluster in orphan_cluster_ids contributes
    # every member finding as orphan. Findings whose cluster has
    # neither assignment nor explicit orphan flag are an error in the
    # upstream LLM stage contract; we surface them in the log but emit
    # them as orphan to keep the population conserved.
    orphan_findings: set[str] = set()
    explicit_orphan_ids = set(orphan_cluster_ids)
    for cid in explicit_orphan_ids:
        for sid in cluster_index.get(cid, []):
            orphan_findings.add(sid)

    assigned_cluster_ids = {
        entry["cluster_id"]
        for entry in assignments_in
        if isinstance(entry, dict) and isinstance(entry.get("cluster_id"), str)
    }
    leaked_cluster_ids = set(cluster_index) - assigned_cluster_ids - explicit_orphan_ids
    if leaked_cluster_ids:
        logger.warning(
            "cluster_to_finding_assignments: %d cluster(s) appear in "
            "pre_clusters but neither assignments nor orphan_cluster_ids "
            "(treating as orphan): first few %s",
            len(leaked_cluster_ids), sorted(leaked_cluster_ids)[:5],
        )
        for cid in leaked_cluster_ids:
            for sid in cluster_index.get(cid, []):
                orphan_findings.add(sid)

    orphans_out: list[dict] = [
        {
            "source_id": sid,
            "best_similarity": None,
            "best_topic_index": None,
        }
        for sid in sorted(orphan_findings, key=_finding_idx)
    ]

    n_findings_total = len(findings)
    mean_assign = (
        n_assignments_total / n_findings_total if n_findings_total else 0.0
    )

    run_bus.curator_topic_assignments = {
        **meta_common,
        "wall_seconds": round(time.monotonic() - t0, 3),
        "n_topics": n_topics_input,
        "n_findings": n_findings_total,
        "n_findings_assigned": n_findings_with_assignment,
        "n_orphans": len(orphans_out),
        "mean_assignments_per_finding": round(mean_assign, 4),
        "topics": topics_out,
        "orphans": orphans_out,
    }
    logger.info(
        "cluster_to_finding_assignments: %d findings assigned across %d "
        "topics (mean=%.2f/find), %d orphans",
        n_findings_with_assignment, n_topics_input, mean_assign,
        len(orphans_out),
    )
    return run_bus


def algo_name_for_metadata() -> str:
    """Indirection so tests can monkeypatch without poking the module-
    level constant. The actual algorithm string is the module constant
    above."""
    return ALGORITHM


__all__ = [
    "ALGORITHM",
    "PER_FINDING_CAP",
    "cluster_to_finding_assignments",
]
