"""Tests for ``src/stages/coherence.py`` — the passive cluster-coherence
measurement stage.

The passthrough test is load-bearing per TASK-COHERENCE-FILTER-PASSIVE:
the stage must not mutate ``curator_findings`` or ``curator_topics_unsliced``.

The real-model multilingual test loads fastembed
(``paraphrase-multilingual-MiniLM-L12-v2``) once per session. First run
downloads ~240 MB to the fastembed cache; subsequent runs load from
cache in ~3-5 s. The test is required by the brief — it confirms the
multilingual model ranks non-Latin-script findings correctly.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Sequence

import numpy as np

from src.bus import RunBus
from src.stage import get_stage_meta
from src.stages.coherence import (
    FASTEMBED_VERSION_REQUIRED,
    MODEL_NAME,
    THRESHOLD_BANDS,
    _all_scores,
    _cosine_normalized,
    _finding_index_from_source_id,
    make_measure_cluster_coherence,
    measure_cluster_coherence,
    write_daily_report,
)


# ---------------------------------------------------------------------------
# Fake embedder: deterministic, multilingual-aware, 4-dim
# ---------------------------------------------------------------------------


class IranPeaceTrumpEmbedder:
    """Deterministic 4-dim embedder. Each dim carries one signal:

    - dim 0: presence of ``Iran`` (across EN/KO/AR/FA spellings)
    - dim 1: presence of ``peace`` (across EN/KO/AR/FA/DE)
    - dim 2: presence of ``Trump`` (across EN/KO/AR/FA)
    - dim 3: presence of off-topic noise tokens

    Cosine similarity to a cluster headline that signals dims 0/1/2 will
    be ~1.0 for on-topic findings (matching at least one signal dim) and
    ~0.0 for purely off-topic findings (only dim 3 set).
    """

    model_name = "fake-iran-peace-trump"

    _SIGNALS: dict[int, tuple[str, ...]] = {
        0: ("iran", "이란", "إيران", "ایران", "iranian"),
        1: ("peace", "평화", "صلح", "سلام", "frieden", "صلح‌"),
        2: ("trump", "트럼프", "ترامب", "ترامپ"),
        3: ("hantavirus", "outbreak", "cruise", "ship", "weather"),
    }

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        out: list[list[float]] = []
        for t in texts:
            tl = t.lower()
            v = [0.0, 0.0, 0.0, 0.0]
            for dim, kws in self._SIGNALS.items():
                for kw in kws:
                    if kw.lower() in tl:
                        v[dim] = 1.0
                        break
            out.append(v)
        return np.asarray(out, dtype=np.float64)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rb(
    *,
    topics: list[dict],
    findings: list[dict],
    run_date: str = "2026-05-12",
) -> RunBus:
    return RunBus(
        run_id="run-2026-05-12-test1234",
        run_date=run_date,
        curator_findings=findings,
        curator_topics_unsliced=topics,
        curator_topics=topics,
    )


def _run_stage(stage, run_bus: RunBus) -> RunBus:
    return asyncio.run(stage(run_bus))


# ---------------------------------------------------------------------------
# 1. Passthrough — the load-bearing test
# ---------------------------------------------------------------------------


def test_passthrough_byte_identical(tmp_path: Path):
    """curator_findings and curator_topics_unsliced must be byte-identical
    to their pre-stage state. This is the load-bearing contract — the
    stage operates in passive mode and never mutates upstream slots."""
    findings = [
        {"title": "Iran rejects US peace deal", "summary": "tensions"},
        {"title": "Hantavirus outbreak on ship", "summary": "investigation"},
    ]
    topics = [
        {
            "title": "Iran peace negotiations",
            "summary": "Trump rejects Iran proposal",
            "source_ids": ["finding-0", "finding-1"],
        }
    ]

    rb = _make_rb(topics=topics, findings=findings)
    findings_snapshot = copy.deepcopy(rb.curator_findings)
    topics_snapshot = copy.deepcopy(rb.curator_topics_unsliced)
    findings_json_before = json.dumps(findings_snapshot, sort_keys=True)
    topics_json_before = json.dumps(topics_snapshot, sort_keys=True)

    stage = make_measure_cluster_coherence(
        embedder=IranPeaceTrumpEmbedder(),
        report_dir=tmp_path,
        write_report=False,
    )
    rb_out = _run_stage(stage, rb)

    # Bytes-identical: serialize and compare
    assert json.dumps(rb_out.curator_findings, sort_keys=True) == findings_json_before
    assert (
        json.dumps(rb_out.curator_topics_unsliced, sort_keys=True)
        == topics_json_before
    )
    # And the coherence slot is populated
    assert rb_out.curator_coherence_scores
    assert rb_out.curator_coherence_scores["n_clusters_scored"] == 1
    # Result is JSON-serialisable
    json.dumps(rb_out.curator_coherence_scores)


# ---------------------------------------------------------------------------
# 2. Ranking — on-topic findings score above off-topic ones
# ---------------------------------------------------------------------------


def test_ranking_on_vs_off_topic(tmp_path: Path):
    """Given a cluster about Iran/peace/Trump and a mix of on/off-topic
    findings, the on-topic finding scores above the off-topic ones with
    a healthy margin (>0.5 absolute on the toy embedder)."""
    topics = [
        {
            "title": "Iran peace negotiations stall",
            "summary": "Trump rejects Iranian peace proposal",
            "source_ids": ["finding-0", "finding-1", "finding-2", "finding-3"],
        }
    ]
    findings = [
        {"title": "Iran rejects US peace deal", "summary": "tensions rise"},
        {"title": "Trump statement on Iran", "summary": "demands lifted"},
        {"title": "Hantavirus outbreak", "summary": "cruise ship investigated"},
        {"title": "Weather report Pacific", "summary": "no shipping advisories"},
    ]
    rb = _make_rb(topics=topics, findings=findings)
    stage = make_measure_cluster_coherence(
        embedder=IranPeaceTrumpEmbedder(),
        report_dir=tmp_path,
        write_report=False,
    )
    out = _run_stage(stage, rb)

    scores = {
        fs["source_id"]: fs["score"]
        for fs in out.curator_coherence_scores["clusters"][0]["finding_scores"]
    }
    # On-topic > off-topic by a margin large enough to survive any
    # rounding inside the cosine computation
    margin = 0.50
    assert scores["finding-0"] - scores["finding-2"] > margin
    assert scores["finding-0"] - scores["finding-3"] > margin
    assert scores["finding-1"] - scores["finding-2"] > margin


# ---------------------------------------------------------------------------
# 3. Multilingual ranking — real fastembed model on non-Latin script
# ---------------------------------------------------------------------------


_real_embedder_cache: list = []


def _get_real_embedder():
    """Module-level singleton for the slow real-model test. fastembed
    caches the model on disk; first call may download ~240 MB."""
    if _real_embedder_cache:
        return _real_embedder_cache[0]
    from src.stages.coherence import FastembedEmbedder
    emb = FastembedEmbedder()
    emb._ensure_loaded()
    _real_embedder_cache.append(emb)
    return emb


def test_multilingual_ranking_real_model(tmp_path: Path):
    """The real fastembed multilingual model ranks non-Latin-script
    on-topic findings above Latin-script off-topic findings. Confirms
    the model covers the production language set in practice."""
    real = _get_real_embedder()
    topics = [
        {
            "title": "US-Iran peace negotiations stall as Trump rejects Iranian proposal",
            "summary": "Tehran's response deemed unacceptable; tensions rise",
            "source_ids": [
                "finding-0",  # KR on-topic
                "finding-1",  # FA on-topic
                "finding-2",  # AR on-topic
                "finding-3",  # EN off-topic
            ],
        }
    ]
    findings = [
        {"title": "이란, 미국의 평화 제안 거부", "summary": "트럼프의 제안에 강경 대응"},
        {"title": "ایران پیشنهاد صلح آمریکا را رد می‌کند", "summary": "تنش‌ها افزایش می‌یابد"},
        {"title": "إيران ترفض اقتراح السلام الأمريكي", "summary": "ردا على ترامب"},
        {
            "title": "Hantavirus outbreak on cruise ship",
            "summary": "French passenger develops symptoms after evacuation",
        },
    ]
    rb = _make_rb(topics=topics, findings=findings)
    stage = make_measure_cluster_coherence(
        embedder=real, report_dir=tmp_path, write_report=False
    )
    out = _run_stage(stage, rb)

    scores = {
        fs["source_id"]: fs["score"]
        for fs in out.curator_coherence_scores["clusters"][0]["finding_scores"]
    }
    # All three non-Latin on-topic findings rank above the off-topic finding.
    # Margin chosen to survive embedding stochasticity (the live smoke at
    # baseline showed ~0.7 vs -0.04 — 0.40 margin is conservative).
    margin = 0.40
    assert scores["finding-0"] - scores["finding-3"] > margin, scores
    assert scores["finding-1"] - scores["finding-3"] > margin, scores
    assert scores["finding-2"] - scores["finding-3"] > margin, scores


# ---------------------------------------------------------------------------
# 4. Determinism — two consecutive runs produce identical scores
# ---------------------------------------------------------------------------


def test_determinism_two_runs(tmp_path: Path):
    """Two consecutive runs on identical input produce identical scores
    (excluding wall-clock and RSS, which are timing-dependent)."""
    topics = [
        {
            "title": "Topic A",
            "summary": "Iran peace Trump",
            "source_ids": ["finding-0", "finding-1"],
        }
    ]
    findings = [
        {"title": "Iran peace deal", "summary": ""},
        {"title": "Hantavirus", "summary": ""},
    ]
    fake = IranPeaceTrumpEmbedder()
    stage = make_measure_cluster_coherence(
        embedder=fake, report_dir=tmp_path, write_report=False
    )

    rb1 = _make_rb(topics=topics, findings=findings)
    rb2 = _make_rb(topics=topics, findings=findings)

    out1 = _run_stage(stage, rb1)
    out2 = _run_stage(stage, rb2)

    def _stable(c: dict) -> dict:
        # strip timing fields so the comparison is over the score content
        return {k: v for k, v in c.items() if k not in {"wall_seconds", "rss_delta_mb"}}

    assert _stable(out1.curator_coherence_scores) == _stable(out2.curator_coherence_scores)


# ---------------------------------------------------------------------------
# 5. Edge cases — empty cluster, single-finding cluster, no clusters
# ---------------------------------------------------------------------------


def test_empty_cluster_no_crash(tmp_path: Path):
    """A cluster with an empty source_ids list produces an empty
    finding_scores entry but does not crash and emits zero aggregates."""
    topics = [
        {
            "title": "Empty cluster",
            "summary": "no findings inside",
            "source_ids": [],
        }
    ]
    findings = [{"title": "irrelevant", "summary": ""}]
    rb = _make_rb(topics=topics, findings=findings)
    stage = make_measure_cluster_coherence(
        embedder=IranPeaceTrumpEmbedder(), report_dir=tmp_path, write_report=False
    )
    out = _run_stage(stage, rb)

    cluster = out.curator_coherence_scores["clusters"][0]
    assert cluster["n_findings"] == 0
    assert cluster["finding_scores"] == []
    assert cluster["aggregates"]["mean"] == 0.0
    # All threshold bands report 0 below
    assert all(v == 0 for v in cluster["below_threshold_counts"].values())


def test_single_finding_cluster(tmp_path: Path):
    """A cluster with exactly one finding produces one finding_score and
    aggregates where min == max == mean == median."""
    topics = [
        {
            "title": "Iran peace",
            "summary": "single finding",
            "source_ids": ["finding-0"],
        }
    ]
    findings = [{"title": "Iran peace deal latest", "summary": ""}]
    rb = _make_rb(topics=topics, findings=findings)
    stage = make_measure_cluster_coherence(
        embedder=IranPeaceTrumpEmbedder(), report_dir=tmp_path, write_report=False
    )
    out = _run_stage(stage, rb)

    cluster = out.curator_coherence_scores["clusters"][0]
    assert cluster["n_findings"] == 1
    assert len(cluster["finding_scores"]) == 1
    agg = cluster["aggregates"]
    assert agg["min"] == agg["max"] == agg["mean"] == agg["median"]


def test_no_clusters_at_all(tmp_path: Path):
    """If curator_topics_unsliced is empty, the stage emits an empty
    record with zeros — no crash, no embedder call."""
    findings = [{"title": "Anything", "summary": ""}]
    rb = _make_rb(topics=[], findings=findings)

    class _CrashEmbedder:
        model_name = "should-not-be-called"

        def embed_batch(self, texts):  # pragma: no cover
            raise AssertionError("embedder must not be called when no clusters")

    stage = make_measure_cluster_coherence(
        embedder=_CrashEmbedder(), report_dir=tmp_path, write_report=False
    )
    out = _run_stage(stage, rb)

    coh = out.curator_coherence_scores
    assert coh["n_clusters_scored"] == 0
    assert coh["n_findings_scored"] == 0
    assert coh["clusters"] == []


def test_orphan_source_id_skipped(tmp_path: Path):
    """source_ids that reference indices outside the findings list are
    silently dropped from the per-cluster score record (defensive
    against curator-side index drift)."""
    topics = [
        {
            "title": "Iran peace",
            "summary": "test",
            "source_ids": ["finding-0", "finding-99"],  # 99 is out of bounds
        }
    ]
    findings = [{"title": "Iran peace deal", "summary": ""}]
    rb = _make_rb(topics=topics, findings=findings)
    stage = make_measure_cluster_coherence(
        embedder=IranPeaceTrumpEmbedder(), report_dir=tmp_path, write_report=False
    )
    out = _run_stage(stage, rb)

    cluster = out.curator_coherence_scores["clusters"][0]
    assert cluster["n_findings"] == 1
    assert cluster["finding_scores"][0]["source_id"] == "finding-0"


# ---------------------------------------------------------------------------
# 6. Stage metadata + Bus invariants
# ---------------------------------------------------------------------------


def test_stage_metadata():
    """The default stage closure carries the expected reads/writes
    metadata so the runner can introspect it."""
    meta = get_stage_meta(measure_cluster_coherence)
    assert meta.kind == "run"
    assert set(meta.reads) == {"curator_findings", "curator_topics_unsliced", "run_date"}
    assert meta.writes == ("curator_coherence_scores",)


def test_bus_slot_metadata():
    """The new Bus slot is internal-visibility and optional-write."""
    from src.bus import RunBus as _RB

    field = _RB.model_fields["curator_coherence_scores"]
    extra = field.json_schema_extra or {}
    assert extra.get("visibility") == ["internal"]
    assert extra.get("optional_write") is True


# ---------------------------------------------------------------------------
# 7. Daily report renderer
# ---------------------------------------------------------------------------


def test_write_daily_report_creates_file(tmp_path: Path):
    """The report writer creates a non-empty Markdown file with the
    expected section headers."""
    topics = [
        {
            "title": "Iran peace",
            "summary": "deal",
            "source_ids": ["finding-0", "finding-1"],
        }
    ]
    findings = [
        {"title": "Iran peace deal latest", "summary": ""},
        {"title": "Hantavirus outbreak", "summary": ""},
    ]
    rb = _make_rb(topics=topics, findings=findings)
    out = _run_stage(
        make_measure_cluster_coherence(
            embedder=IranPeaceTrumpEmbedder(), report_dir=tmp_path, write_report=False
        ),
        rb,
    )

    report = tmp_path / "report.md"
    write_daily_report(
        report,
        coherence=out.curator_coherence_scores,
        findings=findings,
        topics=topics,
    )
    body = report.read_text()
    assert "# Coherence-stage daily report" in body
    assert "Per-cluster aggregates" in body
    assert "Aggregate score histogram" in body
    assert "Qualitative samples" in body


def test_stage_writes_report_when_run_date_set(tmp_path: Path):
    """When write_report=True (default) and the RunBus carries a run_date,
    the stage writes ``{report_dir}/{run_date}.md`` automatically."""
    topics = [{"title": "Iran peace", "summary": "deal", "source_ids": ["finding-0"]}]
    findings = [{"title": "Iran peace latest", "summary": ""}]
    rb = _make_rb(topics=topics, findings=findings, run_date="2026-05-12")
    stage = make_measure_cluster_coherence(
        embedder=IranPeaceTrumpEmbedder(), report_dir=tmp_path, write_report=True
    )
    _run_stage(stage, rb)
    assert (tmp_path / "2026-05-12.md").exists()


# ---------------------------------------------------------------------------
# 8. Pure-helper unit tests
# ---------------------------------------------------------------------------


def test_cosine_normalized_unit_rows():
    m = np.array([[3.0, 4.0], [0.0, 0.0], [1.0, 0.0]])
    n = _cosine_normalized(m)
    # row 0: 3/5, 4/5
    assert np.allclose(n[0], [0.6, 0.8])
    # row 1: zero-norm row passes through unchanged
    assert np.allclose(n[1], [0.0, 0.0])
    # row 2: already unit
    assert np.allclose(n[2], [1.0, 0.0])


def test_finding_index_from_source_id():
    assert _finding_index_from_source_id("finding-0") == 0
    assert _finding_index_from_source_id("finding-42") == 42
    assert _finding_index_from_source_id("not-a-finding") is None
    assert _finding_index_from_source_id("") is None


def test_all_scores_flattens_clusters():
    coh = {
        "clusters": [
            {"finding_scores": [{"source_id": "finding-0", "score": 0.5}]},
            {"finding_scores": [{"source_id": "finding-1", "score": 0.3}]},
        ]
    }
    assert _all_scores(coh) == [0.5, 0.3]


def test_threshold_bands_pinned():
    """THRESHOLD_BANDS are load-bearing for the calibration ROC — they
    define the axis points downstream consumers iterate over."""
    assert THRESHOLD_BANDS[0] == 0.20
    assert THRESHOLD_BANDS[-1] == 0.70
    # monotonically increasing
    assert all(
        THRESHOLD_BANDS[i] < THRESHOLD_BANDS[i + 1]
        for i in range(len(THRESHOLD_BANDS) - 1)
    )


def test_pinned_model_name():
    """Model name pin is part of the reproducibility contract."""
    assert MODEL_NAME == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert FASTEMBED_VERSION_REQUIRED == "0.8.0"
