"""Passive cluster-coherence measurement stage.

Authoritative reference: TASK-COHERENCE-FILTER-PASSIVE.md.
Dependency rationale: docs/ADR-COHERENCE-STAGE-DEPENDENCY.md.

Runs after CuratorStage, before EditorStage. Embeds each cluster's
``title + summary`` (the cluster headline) and each finding's
``title + summary``, then computes the cosine similarity between every
finding and its cluster's headline embedding. Per-cluster aggregates and
threshold-band counts are written to the ``curator_coherence_scores``
slot; the upstream ``curator_findings`` and ``curator_topics_unsliced``
slots pass through byte-identical.

Determinism: fastembed runs ONNX inference single-threaded at
``batch_size=32`` — bit-deterministic. The fastembed version is pinned in
``pyproject.toml`` and the model name is pinned at module level — both
are load-bearing for reproducibility (the mean-pooling change in
fastembed >=0.6 silently shifted every score for this model).
"""

from __future__ import annotations

import logging
import resource
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Protocol, Sequence

import numpy as np

from src.bus import RunBus
from src.stage import run_stage_def

logger = logging.getLogger(__name__)


# ── Pinned configuration ─────────────────────────────────────────────────
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
"""Multilingual sentence-embedding model. ~50 languages covering the full
production set (EN, DE, ES, FR, IT, PT, TR, KO, FA, RU, ZH, AR, HE, ID,
VI). Pinned together with fastembed==0.8.0 in pyproject.toml because
fastembed >=0.6 switched this model from CLS-token to mean-pooled output
— a silent fastembed upgrade would invalidate every historic coherence
score."""

FASTEMBED_VERSION_REQUIRED = "0.8.0"
"""Pinned fastembed version. Runtime mismatch logs a WARNING; scores
remain reproducible only at this exact version."""

DEFAULT_BATCH_SIZE = 32
"""ONNX inference batch size. Empirically optimal on Apple Silicon
M-series (32 < 64 < 128 on the V1-baseline 1201-finding workload). Larger
batches add memory pressure and slow overall throughput. Single-process
single-threaded; ``parallel`` multiprocess inference is slower than the
single-process path on this workload due to spawn overhead."""

THRESHOLD_BANDS: tuple[float, ...] = (
    0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70,
)
"""Candidate coherence thresholds. The stage counts how many findings in
each cluster fall below each band — gives the calibration step the data
to pick one threshold (or interpolate). The future active-filter brief
chooses based on the V1 ROC analysis."""


# ── Embedder protocol ────────────────────────────────────────────────────
class Embedder(Protocol):
    """Production: ``FastembedEmbedder``. Tests inject deterministic stubs."""

    model_name: str

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        """Return an array of shape ``(len(texts), dim)`` — caller normalizes."""


class FastembedEmbedder:
    """Lazy-loaded fastembed ``TextEmbedding`` wrapper. The wrapper holds
    the ONNX session for the process lifetime; a single instance is shared
    across pipeline runs in the same process."""

    model_name: str

    def __init__(
        self,
        *,
        model_name: str = MODEL_NAME,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import fastembed as _fastembed
        except ImportError as exc:
            raise RuntimeError(
                "fastembed not installed. Run `pip install -e .` to pull "
                "the pinned dependency from pyproject.toml."
            ) from exc
        installed = getattr(_fastembed, "__version__", "unknown")
        if installed != FASTEMBED_VERSION_REQUIRED:
            logger.warning(
                "fastembed version mismatch: installed=%s, pinned=%s — "
                "coherence scores may not be bit-identical to historic runs.",
                installed,
                FASTEMBED_VERSION_REQUIRED,
            )
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=self.model_name)

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        self._ensure_loaded()
        vecs: Iterable[np.ndarray] = self._model.embed(
            list(texts), batch_size=self.batch_size
        )
        return np.vstack(list(vecs))


_default_embedder: Optional[FastembedEmbedder] = None


def _get_default_embedder() -> FastembedEmbedder:
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = FastembedEmbedder()
    return _default_embedder


# ── Pure helpers ─────────────────────────────────────────────────────────
def _cluster_text(cluster: dict) -> str:
    return ((cluster.get("title") or "") + " " + (cluster.get("summary") or "")).strip()


def _finding_text(finding: dict) -> str:
    title = finding.get("title") or ""
    summary = finding.get("summary") or finding.get("description") or ""
    return (title + " " + summary).strip()


def _finding_index_from_source_id(source_id: str) -> Optional[int]:
    """Cluster ``source_ids`` carry the ``finding-NNN`` prefix referring
    to ``run_bus.curator_findings[NNN]`` — same convention as V1
    hydration_urls."""
    try:
        return int(str(source_id).split("finding-")[-1])
    except (ValueError, IndexError):
        return None


def _cosine_normalized(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize each row in place-safe form. Zero-norm rows pass
    through unchanged (cosine sim to anything = 0)."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return matrix / norms


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), p * 100.0))


def _aggregate_cluster_scores(scores: list[float]) -> dict[str, float]:
    if not scores:
        return {
            "mean": 0.0, "median": 0.0,
            "p10": 0.0, "p25": 0.0, "p75": 0.0, "p90": 0.0,
            "min": 0.0, "max": 0.0,
        }
    return {
        "mean": float(np.mean(scores)),
        "median": float(np.median(scores)),
        "p10": _percentile(scores, 0.10),
        "p25": _percentile(scores, 0.25),
        "p75": _percentile(scores, 0.75),
        "p90": _percentile(scores, 0.90),
        "min": float(min(scores)),
        "max": float(max(scores)),
    }


def _below_threshold_counts(scores: list[float]) -> dict[str, int]:
    return {f"{t:.2f}": sum(1 for s in scores if s < t) for t in THRESHOLD_BANDS}


def _rss_mb_now() -> float:
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    unit = 1.0 if sys.platform == "darwin" else 1024.0  # macOS=bytes, Linux=KB
    return raw * unit / 1e6


# ── Stage factory ────────────────────────────────────────────────────────
def make_measure_cluster_coherence(
    *,
    embedder: Optional[Any] = None,
    report_dir: Optional[Path] = None,
    write_report: bool = True,
) -> Callable:
    """Build the coherence-measure run-stage.

    Tests inject a fake embedder via ``embedder=...``. Production omits it,
    falling through to the module singleton (lazy-loaded fastembed model).

    ``report_dir`` defaults to ``docs/coherence-filter/`` when
    ``write_report=True``. Set ``write_report=False`` to skip the
    Markdown report entirely (test-friendly).
    """
    closure_embedder = embedder
    closure_report_dir = Path(report_dir) if report_dir is not None else None
    closure_write_report = write_report

    @run_stage_def(
        reads=("curator_findings", "curator_topics_unsliced", "run_date"),
        writes=("curator_coherence_scores",),
    )
    async def measure_cluster_coherence(run_bus: RunBus) -> RunBus:
        findings = list(run_bus.curator_findings or [])
        topics = list(run_bus.curator_topics_unsliced or [])

        emb = closure_embedder if closure_embedder is not None else _get_default_embedder()
        model_name = getattr(emb, "model_name", MODEL_NAME)

        if not topics:
            run_bus.curator_coherence_scores = {
                "model_name": model_name,
                "fastembed_version": FASTEMBED_VERSION_REQUIRED,
                "thresholds": list(THRESHOLD_BANDS),
                "wall_seconds": 0.0,
                "rss_delta_mb": 0.0,
                "n_clusters_scored": 0,
                "n_findings_scored": 0,
                "clusters": [],
            }
            logger.info("measure_cluster_coherence: no clusters; empty record")
            return run_bus

        cluster_texts = [_cluster_text(t) for t in topics]
        finding_texts = [_finding_text(f) for f in findings]

        rss_before = _rss_mb_now()
        t0 = time.monotonic()

        cluster_matrix = _cosine_normalized(emb.embed_batch(cluster_texts))
        finding_matrix = _cosine_normalized(emb.embed_batch(finding_texts))

        wall = time.monotonic() - t0
        rss_after = _rss_mb_now()
        rss_delta_mb = max(0.0, rss_after - rss_before)

        clusters_out: list[dict] = []
        n_findings_scored = 0
        for ci, cluster in enumerate(topics):
            cluster_vec = cluster_matrix[ci]
            scores: list[float] = []
            finding_scores: list[dict] = []
            for sid in cluster.get("source_ids") or []:
                idx = _finding_index_from_source_id(sid)
                if idx is None or not (0 <= idx < len(finding_matrix)):
                    continue
                score = float(np.dot(cluster_vec, finding_matrix[idx]))
                scores.append(score)
                finding_scores.append({"source_id": sid, "score": score})
            n_findings_scored += len(scores)
            clusters_out.append({
                "cluster_index": ci,
                "cluster_title": (cluster.get("title") or "")[:200],
                "n_findings": len(scores),
                "aggregates": _aggregate_cluster_scores(scores),
                "below_threshold_counts": _below_threshold_counts(scores),
                "finding_scores": finding_scores,
            })

        coherence: dict = {
            "model_name": model_name,
            "fastembed_version": FASTEMBED_VERSION_REQUIRED,
            "thresholds": list(THRESHOLD_BANDS),
            "wall_seconds": round(wall, 3),
            "rss_delta_mb": round(rss_delta_mb, 1),
            "n_clusters_scored": len(topics),
            "n_findings_scored": n_findings_scored,
            "clusters": clusters_out,
        }
        run_bus.curator_coherence_scores = coherence

        logger.info(
            "measure_cluster_coherence: %d clusters, %d findings scored "
            "in %.2fs (RSS Δ %.0f MB)",
            len(topics), n_findings_scored, wall, rss_delta_mb,
        )

        if closure_write_report:
            target = closure_report_dir or (Path("docs") / "coherence-filter")
            if run_bus.run_date:
                try:
                    write_daily_report(
                        target / f"{run_bus.run_date}.md",
                        coherence=coherence,
                        findings=findings,
                        topics=topics,
                    )
                except OSError as exc:
                    logger.warning(
                        "measure_cluster_coherence: report write failed at %s: %s",
                        target, exc,
                    )

        return run_bus

    return measure_cluster_coherence


measure_cluster_coherence = make_measure_cluster_coherence()


# ── Daily-report renderer ────────────────────────────────────────────────
def _all_scores(coherence: dict) -> list[float]:
    out: list[float] = []
    for c in coherence.get("clusters") or []:
        for fs in c.get("finding_scores") or []:
            s = fs.get("score")
            if s is None:
                continue
            out.append(float(s))
    return out


def _histogram_bars(scores: list[float], width: int = 40) -> list[str]:
    """ASCII histogram of the score distribution (-0.10 to 1.00, 0.05 bins)."""
    if not scores:
        return ["(no scores)"]
    edges = [round(-0.10 + 0.05 * i, 2) for i in range(23)]
    bins = [0] * (len(edges) - 1)
    for s in scores:
        if s < edges[0]:
            bins[0] += 1
            continue
        if s >= edges[-1]:
            bins[-1] += 1
            continue
        for i in range(len(edges) - 1):
            if edges[i] <= s < edges[i + 1]:
                bins[i] += 1
                break
    peak = max(bins) or 1
    return [
        f"[{edges[i]:>+.2f}, {edges[i+1]:>+.2f})  "
        f"{'█' * round(width * bins[i] / peak)} {bins[i]}"
        for i in range(len(bins))
    ]


def write_daily_report(
    path: Path,
    *,
    coherence: dict,
    findings: list[dict],
    topics: list[dict],
    qualitative_top_clusters: int = 3,
    qualitative_n: int = 5,
) -> None:
    """Render the human-readable daily report and write it to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)

    cluster_rows = coherence.get("clusters") or []
    thresholds = coherence.get("thresholds") or []
    all_scores = _all_scores(coherence)

    lines: list[str] = []
    lines.append("# Coherence-stage daily report")
    lines.append("")
    lines.append(f"- Model: `{coherence.get('model_name')}`")
    lines.append(
        f"- fastembed version (pinned): `{coherence.get('fastembed_version')}`"
    )
    lines.append(f"- Wall: {coherence.get('wall_seconds', 0.0):.2f} s")
    lines.append(f"- RSS Δ: {coherence.get('rss_delta_mb', 0.0):.0f} MB")
    lines.append(f"- Clusters scored: {coherence.get('n_clusters_scored', 0)}")
    lines.append(f"- Findings scored: {coherence.get('n_findings_scored', 0)}")
    lines.append("")

    lines.append("## Per-cluster aggregates")
    lines.append("")
    th_headers = " | ".join(f"<{t:.2f}" for t in thresholds)
    th_dashes = "|".join("---:" for _ in thresholds)
    lines.append(
        "| Cluster | n | mean | median | p10 | p90 | min | max | "
        + th_headers + " |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|" + th_dashes + "|")
    for c in cluster_rows:
        agg = c.get("aggregates") or {}
        btc = c.get("below_threshold_counts") or {}
        th_cells = " | ".join(str(btc.get(f"{t:.2f}", 0)) for t in thresholds)
        title = (c.get("cluster_title") or "").replace("|", "/")
        if len(title) > 80:
            title = title[:77] + "..."
        lines.append(
            f"| {title} | {c.get('n_findings', 0)} | "
            f"{agg.get('mean', 0.0):.3f} | {agg.get('median', 0.0):.3f} | "
            f"{agg.get('p10', 0.0):.3f} | {agg.get('p90', 0.0):.3f} | "
            f"{agg.get('min', 0.0):.3f} | {agg.get('max', 0.0):.3f} | "
            f"{th_cells} |"
        )
    lines.append("")

    lines.append("## Aggregate score histogram (all clusters, all findings)")
    lines.append("")
    lines.append("```")
    lines.extend(_histogram_bars(all_scores))
    lines.append("```")
    lines.append("")

    largest = sorted(
        cluster_rows, key=lambda c: c.get("n_findings", 0), reverse=True
    )[:qualitative_top_clusters]
    if largest:
        lines.append(
            f"## Qualitative samples (top-{qualitative_top_clusters} clusters by size)"
        )
        lines.append("")
    for c in largest:
        title = c.get("cluster_title") or ""
        sorted_scores = sorted(
            c.get("finding_scores") or [],
            key=lambda fs: fs.get("score", 0.0),
        )
        low = sorted_scores[:qualitative_n]
        high = list(reversed(sorted_scores))[:qualitative_n]
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"**Lowest-coherence findings** (n={len(low)})")
        lines.append("")
        for fs in low:
            idx = _finding_index_from_source_id(fs.get("source_id", ""))
            tl = ""
            if idx is not None and 0 <= idx < len(findings):
                tl = (findings[idx].get("title") or "")[:160]
            lines.append(f"- `{fs.get('source_id')}` ({fs.get('score', 0.0):.3f}) — {tl}")
        lines.append("")
        lines.append(f"**Highest-coherence findings** (n={len(high)})")
        lines.append("")
        for fs in high:
            idx = _finding_index_from_source_id(fs.get("source_id", ""))
            tl = ""
            if idx is not None and 0 <= idx < len(findings):
                tl = (findings[idx].get("title") or "")[:160]
            lines.append(f"- `{fs.get('source_id')}` ({fs.get('score', 0.0):.3f}) — {tl}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "Embedder",
    "FASTEMBED_VERSION_REQUIRED",
    "FastembedEmbedder",
    "MODEL_NAME",
    "THRESHOLD_BANDS",
    "make_measure_cluster_coherence",
    "measure_cluster_coherence",
    "write_daily_report",
]
