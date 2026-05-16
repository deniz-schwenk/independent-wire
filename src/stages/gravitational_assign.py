"""Gravitational topic-assignment stage — deterministic finding→topic
assignment by cosine threshold + per-finding cap.

Authoritative references:
- docs/ADR-CURATOR-TRIPLE-STAGE.md         (architectural rationale)
- TASK-GRAVITATIONAL-ASSIGN-STAGE.md       (this stage's contract)
- docs/gravitational-assign/_calibration-2026-05-15.md
                                            (threshold + cap calibration)

Runs AFTER Brief 1's ``pre_cluster_findings`` and AFTER the eventual
Stage-2 LLM Topic-Discovery Curator, BEFORE the Editor in the triple-
stage Curator architecture. Embeds the ``title + summary`` of every
``curator_topics_unsliced`` entry into a topic-centre vector, embeds
every ``curator_finding``, and assigns each finding to **every**
topic-centre whose cosine similarity meets ``GRAVITATIONAL_THRESHOLD``
— capped at ``PER_FINDING_CAP`` topics per finding. Findings that
match no topic become orphans.

Multi-assignment is the honest model — a Strait-of-Hormuz attack
genuinely belongs to both "Iran-US diplomacy" and "global energy
crisis"; forcing one would be the editorial simplification the
project exists to make visible.

Tie-break (load-bearing): when the cap binds, top-K by similarity
descending, with topic-index ascending as the deterministic
tie-break. Implemented as a single ``np.lexsort`` call so a future
numpy / sklearn change cannot silently shift assignments.

The stage is declared but NOT YET WIRED into
``build_production_stages`` / ``build_hydrated_stages``. The
integration brief later in the triple-stage sequence wires it.

**Calibration is provisional** pending Brief 4's real Stage-2 output.
The V1 Curator headlines used as topic-centre proxies during
calibration are tighter than the eventual Stage-2 topic-centres will
be; the threshold will be revisited then. See the calibration report
for the F1 / orphan-rate / cap-fit evidence behind the pinned values.
"""

from __future__ import annotations

import logging
import resource
import sys
import time
from typing import Any, Callable, Optional

import numpy as np

from src.bus import RunBus
from src.stage import run_stage_def
from src.stages.coherence import (
    FASTEMBED_VERSION_REQUIRED,
    MODEL_NAME,
    _cosine_normalized,
    _get_default_embedder,
)

logger = logging.getLogger(__name__)


# ── Pinned calibration constants ────────────────────────────────────────
GRAVITATIONAL_THRESHOLD: float = 0.30
"""Cosine-similarity floor that separates a topic match from an orphan.
Calibrated against the 504-label ground-truth set on 2026-05-15 —
pooled F1 = 0.768 at T=0.30 (within the F1 ≥ 0.75 plateau spanning
T=0.30–0.40), 49.7 % orphan rate, ~18 % multi-assignment rate, cap
binds for only 1.7 % of findings. See
``docs/gravitational-assign/_calibration-2026-05-15.md`` for the
evidence. **Provisional** pending Brief 4's real Stage-2 topic-centre
output."""

PER_FINDING_CAP: int = 3
"""Maximum number of topics a single finding can be assigned to.
Architect-decided range is 2–3; 3 chosen at calibration because at the
production threshold only 45/2606 findings (~1.7 %) have ≥4 matches —
the cap rarely binds, and 3 honours genuine cross-topic findings
(e.g., a Strait-of-Hormuz attack between Iran-US-diplomacy and
energy-crisis topics)."""

TIE_BREAK_RULE: str = "similarity desc, topic-index asc"
"""Deterministic tie-break rule when the cap binds. Implemented via
``np.lexsort((topic_indices, -similarities))`` — primary key
similarity descending, secondary key topic-index ascending. The
synthetic tied-similarity test in
``tests/test_gravitational_assign_stage.py`` is load-bearing — without
it, a future numpy / sklearn change could silently shift
assignments."""

ALGORITHM: str = "cosine-threshold-topk"


# ── Pure helpers ────────────────────────────────────────────────────────
def _topic_text(topic: dict) -> str:
    """Topic-centre text — ``title + summary`` of the Stage-2 (or V1
    proxy) Curator topic. Must stay aligned with the rule the
    calibration harness used or production drifts from the calibrated
    threshold."""
    return ((topic.get("title") or "") + " " + (topic.get("summary") or "")).strip()


def _finding_text(finding: dict) -> str:
    """Same concatenation rule as the pre-cluster stage and the
    clustering / gravitational eval harnesses — keeps finding
    embeddings comparable across stages."""
    return (
        (finding.get("title") or "")
        + " "
        + (finding.get("summary") or "")
        + " "
        + (finding.get("description") or "")
    ).strip()


def _select_eligible_topics(
    similarities: np.ndarray,
    *,
    threshold: float,
    cap: int,
) -> list[tuple[int, float]]:
    """Given the per-topic similarity row for one finding, return up to
    ``cap`` (topic_index, similarity) tuples sorted by similarity
    descending with topic-index ascending as the documented tie-break.

    Pure function exposed for unit tests — the tie-break determinism
    test constructs deliberately tied similarities and asserts the
    selected indices are the lowest-numbered ones."""
    eligible_mask = similarities >= threshold
    eligible_indices = np.nonzero(eligible_mask)[0]
    if eligible_indices.size == 0:
        return []
    eligible_sims = similarities[eligible_indices]
    # np.lexsort sorts by the LAST key as primary, earlier keys as
    # tie-breakers. We want primary=similarity desc, secondary=topic-
    # index asc → keys=(topic_indices, -similarities).
    order = np.lexsort((eligible_indices, -eligible_sims))
    sorted_ti = eligible_indices[order]
    sorted_sims = eligible_sims[order]
    keep = min(cap, sorted_ti.size)
    return [(int(sorted_ti[i]), float(sorted_sims[i])) for i in range(keep)]


def _assign(
    similarity_matrix: np.ndarray,
    *,
    threshold: float,
    cap: int,
) -> tuple[dict[int, list[tuple[int, float]]], list[tuple[int, float, int]]]:
    """Walk the (n_findings, n_topics) similarity matrix and produce:

    - ``topic_buckets``: ``{topic_index: [(finding_index, similarity), ...]}``
      sorted within each topic by (similarity desc, finding-index asc).
    - ``orphans``: ``[(finding_index, best_similarity, best_topic_index), ...]``
      — one entry per finding with no above-threshold match. ``best_*``
      is the highest-scoring topic for the finding, useful as a
      diagnostic in the rendered report. ``best_topic_index == -1``
      when there are no topics at all.

    Pure function — no embedder dependency, fully test-driven."""
    n_findings, n_topics = similarity_matrix.shape
    topic_buckets: dict[int, list[tuple[int, float]]] = {
        ti: [] for ti in range(n_topics)
    }
    orphans: list[tuple[int, float, int]] = []

    for fi in range(n_findings):
        sims = similarity_matrix[fi]
        selected = _select_eligible_topics(sims, threshold=threshold, cap=cap)
        if not selected:
            if n_topics:
                best_ti = int(np.argmax(sims))
                best_sim = float(sims[best_ti])
            else:
                best_ti = -1
                best_sim = 0.0
            orphans.append((fi, best_sim, best_ti))
            continue
        for ti, sim in selected:
            topic_buckets[ti].append((fi, sim))

    # Sort each topic's assignments deterministically
    for ti in topic_buckets:
        topic_buckets[ti].sort(key=lambda kv: (-kv[1], kv[0]))

    return topic_buckets, orphans


def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0  # macOS=bytes, Linux=KB
    return raw * unit / 1e6


def _sklearn_version() -> str:
    try:
        import sklearn

        return getattr(sklearn, "__version__", "unknown")
    except ImportError:
        return "not-installed"


# ── Stage factory ───────────────────────────────────────────────────────
def make_gravitational_assign(
    *,
    embedder: Optional[Any] = None,
    threshold: float = GRAVITATIONAL_THRESHOLD,
    cap: int = PER_FINDING_CAP,
) -> Callable:
    """Build the gravitational-assignment run-stage.

    Tests inject a fake ``embedder`` and a synthetic ``threshold`` /
    ``cap`` tuned for low-dim geometry. Production omits all three —
    the stage falls through to the fastembed singleton shared with
    ``src/stages/coherence.py`` and the calibrated constants."""
    closure_embedder = embedder
    closure_threshold = threshold
    closure_cap = cap

    @run_stage_def(
        reads=("curator_findings", "curator_discovered_topics"),
        writes=("curator_topic_assignments",),
    )
    async def gravitational_assign(run_bus: RunBus) -> RunBus:
        findings = list(run_bus.curator_findings or [])
        # Brief 5 cutover: topic-centres come from Brief 4's
        # curator_discovered_topics now, not from the legacy
        # curator_topics_unsliced (which is written by
        # assemble_curator_topics AFTER this stage runs in the new
        # pipeline order). The topic-shape contract is unchanged —
        # title + summary fields are present in both.
        topics = list(
            (run_bus.curator_discovered_topics or {}).get("topics") or []
        )

        emb = closure_embedder if closure_embedder is not None else _get_default_embedder()
        model_name = getattr(emb, "model_name", MODEL_NAME)

        meta_common: dict[str, Any] = {
            "model_name": model_name,
            "fastembed_version": FASTEMBED_VERSION_REQUIRED,
            "algorithm": ALGORITHM,
            "algorithm_library": "numpy",
            "algorithm_library_version": np.__version__,
            "params": {
                "gravitational_threshold": closure_threshold,
                "per_finding_cap": closure_cap,
                "tie_break": TIE_BREAK_RULE,
            },
        }

        # Empty-input fast paths
        if not findings and not topics:
            run_bus.curator_topic_assignments = {
                **meta_common,
                "wall_seconds": 0.0,
                "rss_delta_mb": 0.0,
                "n_topics": 0,
                "n_findings": 0,
                "n_findings_assigned": 0,
                "n_orphans": 0,
                "mean_assignments_per_finding": 0.0,
                "topics": [],
                "orphans": [],
            }
            logger.info("gravitational_assign: no findings, no topics; empty record")
            return run_bus

        if not findings:
            # Topics but no findings → empty assignments
            run_bus.curator_topic_assignments = {
                **meta_common,
                "wall_seconds": 0.0,
                "rss_delta_mb": 0.0,
                "n_topics": len(topics),
                "n_findings": 0,
                "n_findings_assigned": 0,
                "n_orphans": 0,
                "mean_assignments_per_finding": 0.0,
                "topics": [
                    {
                        "topic_index": ti,
                        "topic_title": (topics[ti].get("title") or "")[:200],
                        "n_assigned": 0,
                        "assignments": [],
                    }
                    for ti in range(len(topics))
                ],
                "orphans": [],
            }
            logger.info(
                "gravitational_assign: no findings; %d empty topic buckets",
                len(topics),
            )
            return run_bus

        if not topics:
            # No topics — every finding is an orphan with best_topic_index=-1
            orphans_out = [
                {"source_id": f"finding-{fi}", "best_similarity": 0.0, "best_topic_index": -1}
                for fi in range(len(findings))
            ]
            run_bus.curator_topic_assignments = {
                **meta_common,
                "wall_seconds": 0.0,
                "rss_delta_mb": 0.0,
                "n_topics": 0,
                "n_findings": len(findings),
                "n_findings_assigned": 0,
                "n_orphans": len(findings),
                "mean_assignments_per_finding": 0.0,
                "topics": [],
                "orphans": orphans_out,
            }
            logger.info(
                "gravitational_assign: no topics; %d findings all orphan",
                len(findings),
            )
            return run_bus

        rss_before = _rss_mb_now()
        t0 = time.monotonic()

        # Embed findings + topic-centres in one go (singleton holds ONNX session)
        finding_texts = [_finding_text(f) for f in findings]
        topic_texts = [_topic_text(t) for t in topics]
        finding_matrix = _cosine_normalized(emb.embed_batch(finding_texts))
        topic_matrix = _cosine_normalized(emb.embed_batch(topic_texts))

        # (n_findings, n_topics) cosine-similarity matrix
        similarity_matrix = (finding_matrix @ topic_matrix.T).astype(np.float64)

        topic_buckets, orphans = _assign(
            similarity_matrix,
            threshold=closure_threshold,
            cap=closure_cap,
        )

        # Materialise the bus shape
        topics_out: list[dict] = []
        n_assignments_total = 0
        for ti in range(len(topics)):
            bucket = topic_buckets.get(ti, [])
            topics_out.append({
                "topic_index": ti,
                "topic_title": (topics[ti].get("title") or "")[:200],
                "n_assigned": len(bucket),
                "assignments": [
                    {"source_id": f"finding-{fi}", "similarity": round(sim, 4)}
                    for fi, sim in bucket
                ],
            })
            n_assignments_total += len(bucket)

        orphans_out: list[dict] = [
            {
                "source_id": f"finding-{fi}",
                "best_similarity": round(best_sim, 4),
                "best_topic_index": best_ti,
            }
            for fi, best_sim, best_ti in sorted(orphans, key=lambda x: x[0])
        ]

        wall = time.monotonic() - t0
        rss_after = _rss_mb_now()
        rss_delta = max(0.0, rss_after - rss_before)

        n_findings_assigned = len(findings) - len(orphans)
        mean_assign = (
            n_assignments_total / len(findings) if len(findings) else 0.0
        )

        run_bus.curator_topic_assignments = {
            **meta_common,
            "wall_seconds": round(wall, 3),
            "rss_delta_mb": round(rss_delta, 1),
            "n_topics": len(topics),
            "n_findings": len(findings),
            "n_findings_assigned": n_findings_assigned,
            "n_orphans": len(orphans),
            "mean_assignments_per_finding": round(mean_assign, 4),
            "topics": topics_out,
            "orphans": orphans_out,
        }
        logger.info(
            "gravitational_assign: %d findings, %d topics → %d assignments, "
            "%d orphans (mean=%.2f/find) in %.2fs (RSS Δ %.0f MB)",
            len(findings), len(topics), n_assignments_total, len(orphans),
            mean_assign, wall, rss_delta,
        )
        return run_bus

    return gravitational_assign


gravitational_assign = make_gravitational_assign()


__all__ = [
    "ALGORITHM",
    "GRAVITATIONAL_THRESHOLD",
    "PER_FINDING_CAP",
    "TIE_BREAK_RULE",
    "gravitational_assign",
    "make_gravitational_assign",
]
