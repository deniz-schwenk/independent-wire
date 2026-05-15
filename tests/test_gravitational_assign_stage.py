"""Tests for ``src/stages/gravitational_assign.py`` — the gravitational
topic-assignment stage.

Required behavioural assertions per TASK-GRAVITATIONAL-ASSIGN-STAGE §Tests:

- Determinism (bit-identical labels on identical input)
- Pass-through of ``curator_findings`` AND ``curator_topics_unsliced``
- Synthetic single-assignment (3 well-separated topics × 3 findings each)
- Multi-assignment (one finding above threshold for two topics)
- Cap enforcement + tie-break (hand-crafted equal-similarity case)
- Orphan (one finding below threshold for every topic)
- Empty topics → all orphans
- Empty findings → empty record
- Single topic, single finding (above and below threshold)
- Multilingual sanity (real fastembed model)
- Stage + slot metadata

The tied-similarity test is **load-bearing** — without it, a future
numpy / sklearn change to the sort behaviour could silently shift
assignments when the cap binds. The test constructs the tied case from
hand-crafted unit vectors that produce mathematically exact equal dot
products, not "two close values".
"""

from __future__ import annotations

import asyncio
import copy
import json
from typing import Sequence

import numpy as np

from src.bus import RunBus
from src.stage import get_stage_meta
from src.stages.gravitational_assign import (
    ALGORITHM,
    GRAVITATIONAL_THRESHOLD,
    PER_FINDING_CAP,
    TIE_BREAK_RULE,
    _assign,
    _finding_text,
    _select_eligible_topics,
    _topic_text,
    gravitational_assign,
    make_gravitational_assign,
)


# ---------------------------------------------------------------------------
# Fake embedder: three well-separated topic groups in 4-dim space.
# ---------------------------------------------------------------------------


class ThreeTopicEmbedder:
    """Deterministic 4-dim embedder for synthetic tests.

    - dim 0: ``iran`` tokens (across EN / KR / AR / FA)
    - dim 1: ``climate`` tokens (across EN / KR / AR / FA)
    - dim 2: ``sports`` tokens (across EN / KR / AR / FA)
    - dim 3: noise fallback

    L2-normalised. Cross-group cosine distance is √2 ≈ 1.41; within
    a group cosine distance is 0. With threshold tuned to 0.5, on-topic
    findings score 1.0 vs their topic-centre and 0.0 vs the others."""

    model_name = "fake-three-topic"

    _SIGNALS: dict[int, tuple[str, ...]] = {
        0: ("iran", "이란", "إيران", "ایران"),
        1: ("climate", "기후", "مناخ", "اقلیم"),
        2: ("sports", "축구", "كرة", "ورزش"),
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
            if v == [0.0, 0.0, 0.0, 0.0]:
                v[3] = 1.0  # noise fallback
            out.append(v)
        return np.asarray(out, dtype=np.float64)


class IranOnlyEmbedder:
    """Single-dim embedder for the cap + tie-break test. Findings and
    topics are encoded directly as raw vectors via the input text —
    ``vec:<dim>:<value>:<dim>:<value>:...`` style. Any other text is a
    zero vector. The 4-dim space gives us room for 3 topic-centres on
    distinct axes plus a finding that hits all three equally."""

    model_name = "fake-vector-explicit"

    def embed_batch(self, texts: Sequence[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for t in texts:
            v = [0.0, 0.0, 0.0, 0.0]
            if t.startswith("vec:"):
                tokens = t.split(":")[1:]
                for i in range(0, len(tokens), 2):
                    dim = int(tokens[i])
                    val = float(tokens[i + 1])
                    v[dim] = val
            rows.append(v)
        return np.asarray(rows, dtype=np.float64)


def _make_rb(
    *,
    findings: list[dict],
    topics: list[dict],
    run_date: str = "2026-05-15",
) -> RunBus:
    return RunBus(
        run_id="run-2026-05-15-test-grav",
        run_date=run_date,
        curator_findings=findings,
        curator_topics_unsliced=topics,
    )


def _run_stage(stage, rb: RunBus) -> RunBus:
    return asyncio.run(stage(rb))


# ---------------------------------------------------------------------------
# 1. Determinism
# ---------------------------------------------------------------------------


def test_determinism_two_runs():
    findings = [
        {"title": "Iran A", "summary": ""},
        {"title": "Iran B", "summary": ""},
        {"title": "Climate A", "summary": ""},
        {"title": "Climate B", "summary": ""},
        {"title": "Sports A", "summary": ""},
        {"title": "Sports B", "summary": ""},
    ]
    topics = [
        {"title": "Iran topic", "summary": "Iran news"},
        {"title": "Climate topic", "summary": "Climate news"},
        {"title": "Sports topic", "summary": "Sports news"},
    ]
    stage = make_gravitational_assign(
        embedder=ThreeTopicEmbedder(),
        threshold=0.5,
        cap=2,
    )
    rb1 = _make_rb(findings=copy.deepcopy(findings), topics=copy.deepcopy(topics))
    rb2 = _make_rb(findings=copy.deepcopy(findings), topics=copy.deepcopy(topics))
    out1 = _run_stage(stage, rb1)
    out2 = _run_stage(stage, rb2)

    def _stable(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in {"wall_seconds", "rss_delta_mb"}}

    assert _stable(out1.curator_topic_assignments) == _stable(out2.curator_topic_assignments)


# ---------------------------------------------------------------------------
# 2. Pass-through — curator_findings + curator_topics_unsliced byte-identical
# ---------------------------------------------------------------------------


def test_passthrough_byte_identical():
    findings = [
        {"title": "Iran rejects deal", "summary": "tensions"},
        {"title": "Climate accord", "summary": "Paris"},
    ]
    topics = [
        {"title": "Iran topic", "summary": "Iran headline"},
        {"title": "Climate topic", "summary": "Climate headline"},
    ]
    rb = _make_rb(findings=findings, topics=topics)
    findings_snapshot = copy.deepcopy(rb.curator_findings)
    topics_snapshot = copy.deepcopy(rb.curator_topics_unsliced)
    findings_json = json.dumps(findings_snapshot, sort_keys=True)
    topics_json = json.dumps(topics_snapshot, sort_keys=True)

    stage = make_gravitational_assign(
        embedder=ThreeTopicEmbedder(), threshold=0.5, cap=2
    )
    rb_out = _run_stage(stage, rb)

    assert json.dumps(rb_out.curator_findings, sort_keys=True) == findings_json
    assert json.dumps(rb_out.curator_topics_unsliced, sort_keys=True) == topics_json
    # JSON-serialisable
    json.dumps(rb_out.curator_topic_assignments)


# ---------------------------------------------------------------------------
# 3. Synthetic single-assignment — three topics × three findings each
# ---------------------------------------------------------------------------


def test_synthetic_single_assignment_three_topics():
    findings = [
        {"title": "Iran A"}, {"title": "Iran B"}, {"title": "Iran C"},
        {"title": "Climate A"}, {"title": "Climate B"}, {"title": "Climate C"},
        {"title": "Sports A"}, {"title": "Sports B"}, {"title": "Sports C"},
    ]
    topics = [
        {"title": "Iran topic", "summary": "Iran news"},
        {"title": "Climate topic", "summary": "Climate news"},
        {"title": "Sports topic", "summary": "Sports news"},
    ]
    stage = make_gravitational_assign(
        embedder=ThreeTopicEmbedder(), threshold=0.5, cap=2
    )
    out = _run_stage(stage, _make_rb(findings=findings, topics=topics))
    ca = out.curator_topic_assignments

    assert ca["n_findings"] == 9
    assert ca["n_topics"] == 3
    assert ca["n_findings_assigned"] == 9
    assert ca["n_orphans"] == 0
    # Each topic gets exactly 3 findings; each finding assigned to exactly 1 topic
    n_per_topic = sorted(t["n_assigned"] for t in ca["topics"])
    assert n_per_topic == [3, 3, 3]
    # mean assignments per finding = 1 exactly
    assert ca["mean_assignments_per_finding"] == 1.0

    # Verify per-topic groupings
    for ti, expected_finding_prefix in [(0, "Iran"), (1, "Climate"), (2, "Sports")]:
        topic_block = ca["topics"][ti]
        for a in topic_block["assignments"]:
            fi = int(a["source_id"].split("finding-")[-1])
            assert findings[fi]["title"].startswith(expected_finding_prefix)


# ---------------------------------------------------------------------------
# 4. Multi-assignment — finding above threshold for two topics
# ---------------------------------------------------------------------------


def test_multi_assignment_finding_between_two_topics():
    """Construct a finding whose embedding has high cosine sim to BOTH
    topic 0 and topic 1 (above threshold) but not topic 2. With cap=2
    it assigns to both."""
    # Topic 0: dim 0; Topic 1: dim 1; Topic 2: dim 2
    topics = [
        {"title": "vec:0:1.0"},  # ThreeTopicEmbedder won't see "vec:..." → it falls back to noise
        {"title": "vec:1:1.0"},
        {"title": "vec:2:1.0"},
    ]
    # Finding: roughly equal mass on dims 0 and 1, none on 2. Normalised
    # vector [1/√2, 1/√2, 0, 0] gives sim 1/√2 ≈ 0.707 to topics 0 and 1,
    # 0 to topic 2.
    findings = [{"title": "vec:0:1.0:1:1.0"}]
    # IranOnlyEmbedder parses these directly.
    stage = make_gravitational_assign(
        embedder=IranOnlyEmbedder(), threshold=0.5, cap=2
    )
    out = _run_stage(stage, _make_rb(findings=findings, topics=topics))
    ca = out.curator_topic_assignments

    assert ca["n_findings_assigned"] == 1
    assert ca["n_orphans"] == 0
    # Topic 0 and topic 1 each get the finding
    assert ca["topics"][0]["n_assigned"] == 1
    assert ca["topics"][1]["n_assigned"] == 1
    assert ca["topics"][2]["n_assigned"] == 0
    # Similarity should be 1/√2 ≈ 0.7071
    expected = round(1.0 / np.sqrt(2.0), 4)
    assert ca["topics"][0]["assignments"][0]["similarity"] == expected
    assert ca["topics"][1]["assignments"][0]["similarity"] == expected


# ---------------------------------------------------------------------------
# 5. Cap + tie-break — LOAD-BEARING
# ---------------------------------------------------------------------------


def test_cap_enforced_with_topic_index_tiebreak_on_exact_ties():
    """Hand-crafted exact tie: finding has IDENTICAL cosine similarity to
    three topics. With cap=2, only topics 0 and 1 (lowest indices) are
    assigned — topic 2 is dropped by the tie-break rule.

    The construction: topic_i is a unit vector along dim i; finding is
    [1, 1, 1, 0]/√3. Cosine sim is exactly 1/√3 to each of the three
    topics — mathematically tied, not 'two close values'. Without the
    documented tie-break, a future numpy / sklearn change could
    silently produce {1, 2} or {0, 2}."""
    topics = [
        {"title": "vec:0:1.0"},
        {"title": "vec:1:1.0"},
        {"title": "vec:2:1.0"},
    ]
    findings = [{"title": "vec:0:1.0:1:1.0:2:1.0"}]
    stage = make_gravitational_assign(
        embedder=IranOnlyEmbedder(), threshold=0.5, cap=2
    )
    out = _run_stage(stage, _make_rb(findings=findings, topics=topics))
    ca = out.curator_topic_assignments

    # Topic 0 and Topic 1 get the finding; Topic 2 dropped by tie-break
    assert ca["topics"][0]["n_assigned"] == 1, ca["topics"]
    assert ca["topics"][1]["n_assigned"] == 1, ca["topics"]
    assert ca["topics"][2]["n_assigned"] == 0, ca["topics"]
    # And the similarity is the exact mathematical value 1/√3
    expected = round(1.0 / np.sqrt(3.0), 4)
    assert ca["topics"][0]["assignments"][0]["similarity"] == expected
    assert ca["topics"][1]["assignments"][0]["similarity"] == expected


def test_select_eligible_topics_tiebreak_direct():
    """Direct unit test of _select_eligible_topics with tied
    similarities. Independent of the embedder + stage wiring — fails
    fast if the tie-break implementation drifts even before the
    stage-level test catches it."""
    sims = np.array([0.6, 0.6, 0.6, 0.1], dtype=np.float64)
    selected = _select_eligible_topics(sims, threshold=0.5, cap=2)
    assert [ti for ti, _ in selected] == [0, 1]
    # Reorder the tied values: cap=1 keeps only topic_index 0
    selected = _select_eligible_topics(sims, threshold=0.5, cap=1)
    assert [ti for ti, _ in selected] == [0]
    # Mixed: one higher value + two tied lower ones
    sims2 = np.array([0.3, 0.7, 0.7, 0.1], dtype=np.float64)
    selected = _select_eligible_topics(sims2, threshold=0.2, cap=2)
    # Two top tied at 0.7 → indices 1 and 2 (lowest indices among tied)
    assert [ti for ti, _ in selected] == [1, 2]
    # cap=1 with one higher: topic 1 wins (0.7 > 0.3)
    selected = _select_eligible_topics(sims2, threshold=0.2, cap=1)
    assert [ti for ti, _ in selected] == [1]


# ---------------------------------------------------------------------------
# 6. Orphan — finding below threshold for every topic
# ---------------------------------------------------------------------------


def test_orphan_below_threshold():
    topics = [
        {"title": "Iran topic", "summary": "Iran"},
        {"title": "Climate topic", "summary": "Climate"},
    ]
    findings = [
        {"title": "Random unrelated story about cooking"},  # noise dim
    ]
    stage = make_gravitational_assign(
        embedder=ThreeTopicEmbedder(), threshold=0.5, cap=2
    )
    out = _run_stage(stage, _make_rb(findings=findings, topics=topics))
    ca = out.curator_topic_assignments
    assert ca["n_findings_assigned"] == 0
    assert ca["n_orphans"] == 1
    assert ca["orphans"][0]["source_id"] == "finding-0"
    # best_topic_index records which topic was closest (tie-broken
    # internally by argmax) — value is observable even when below
    # threshold
    assert ca["orphans"][0]["best_similarity"] < 0.5


# ---------------------------------------------------------------------------
# 7. Empty topics → all orphans
# ---------------------------------------------------------------------------


def test_empty_topics_all_orphans():
    findings = [
        {"title": "Iran A"},
        {"title": "Climate A"},
        {"title": "Sports A"},
    ]
    stage = make_gravitational_assign(embedder=ThreeTopicEmbedder())
    out = _run_stage(stage, _make_rb(findings=findings, topics=[]))
    ca = out.curator_topic_assignments
    assert ca["n_topics"] == 0
    assert ca["n_findings"] == 3
    assert ca["n_findings_assigned"] == 0
    assert ca["n_orphans"] == 3
    assert ca["topics"] == []
    # best_topic_index == -1 for the no-topics case
    for orph in ca["orphans"]:
        assert orph["best_topic_index"] == -1


# ---------------------------------------------------------------------------
# 8. Empty findings → empty record
# ---------------------------------------------------------------------------


def test_empty_findings_empty_record():
    topics = [
        {"title": "Iran topic", "summary": "Iran"},
        {"title": "Climate topic", "summary": "Climate"},
    ]

    class _CrashEmbedder:
        model_name = "should-not-be-called"

        def embed_batch(self, texts):  # pragma: no cover
            raise AssertionError("embedder must not be called when no findings")

    stage = make_gravitational_assign(embedder=_CrashEmbedder())
    out = _run_stage(stage, _make_rb(findings=[], topics=topics))
    ca = out.curator_topic_assignments
    assert ca["n_findings"] == 0
    assert ca["n_orphans"] == 0
    assert ca["n_findings_assigned"] == 0
    # All declared topics appear with empty assignment lists
    assert all(t["n_assigned"] == 0 for t in ca["topics"])
    assert ca["orphans"] == []


# ---------------------------------------------------------------------------
# 9. Single topic, single finding
# ---------------------------------------------------------------------------


def test_single_topic_single_finding_above_threshold():
    findings = [{"title": "Iran finding"}]
    topics = [{"title": "Iran topic", "summary": "Iran"}]
    stage = make_gravitational_assign(
        embedder=ThreeTopicEmbedder(), threshold=0.5, cap=2
    )
    out = _run_stage(stage, _make_rb(findings=findings, topics=topics))
    ca = out.curator_topic_assignments
    assert ca["n_findings_assigned"] == 1
    assert ca["n_orphans"] == 0
    assert ca["topics"][0]["assignments"][0]["source_id"] == "finding-0"


def test_single_topic_single_finding_below_threshold():
    findings = [{"title": "Random off-topic story"}]
    topics = [{"title": "Iran topic", "summary": "Iran"}]
    stage = make_gravitational_assign(
        embedder=ThreeTopicEmbedder(), threshold=0.5, cap=2
    )
    out = _run_stage(stage, _make_rb(findings=findings, topics=topics))
    ca = out.curator_topic_assignments
    assert ca["n_findings_assigned"] == 0
    assert ca["n_orphans"] == 1


# ---------------------------------------------------------------------------
# 10. Multilingual sanity — real fastembed model
# ---------------------------------------------------------------------------


def test_multilingual_assignment_real_model():
    """A non-Latin-script finding (Korean) about Iran-US peace talks
    assigns to the Latin-script Iran-related topic-centre under the
    real fastembed model and the production threshold. The off-topic
    finding orphans."""
    stage = make_gravitational_assign()  # default singleton + production constants

    findings = [
        {
            "title": "이란, 미국의 평화 제안 거부",
            "summary": "트럼프의 제안에 강경 대응하며 긴장이 고조되고 있다.",
        },
        {
            "title": "Hantavirus cruise outbreak",
            "summary": "French passenger evacuated after symptoms onset.",
        },
    ]
    topics = [
        {
            "title": "US-Iran peace talks stall",
            "summary": "Trump rejects Iranian proposal as tensions rise across the Gulf",
        },
        {
            "title": "Sports match recap",
            "summary": "Football league updates and player transfers",
        },
    ]
    out = _run_stage(stage, _make_rb(findings=findings, topics=topics))
    ca = out.curator_topic_assignments

    # KR Iran finding (index 0) assigns to topic 0 (US-Iran)
    iran_topic_assignments = ca["topics"][0]["assignments"]
    assert any(a["source_id"] == "finding-0" for a in iran_topic_assignments), (
        f"KR-Iran did not assign to US-Iran topic: {ca['topics']}"
    )
    # Hantavirus (index 1) does not assign to topic 0
    assert not any(a["source_id"] == "finding-1" for a in iran_topic_assignments), (
        f"Hantavirus co-assigned to Iran topic: {ca['topics']}"
    )


# ---------------------------------------------------------------------------
# 11. Stage + slot metadata
# ---------------------------------------------------------------------------


def test_stage_metadata():
    meta = get_stage_meta(gravitational_assign)
    assert meta.kind == "run"
    assert set(meta.reads) == {"curator_findings", "curator_topics_unsliced"}
    assert meta.writes == ("curator_topic_assignments",)


def test_bus_slot_metadata():
    from src.bus import RunBus as _RB

    field = _RB.model_fields["curator_topic_assignments"]
    extra = field.json_schema_extra or {}
    assert extra.get("visibility") == ["internal"]
    assert extra.get("optional_write") is True


# ---------------------------------------------------------------------------
# 12. Pinned constants — calibration's chosen values
# ---------------------------------------------------------------------------


def test_pinned_calibration_constants():
    assert GRAVITATIONAL_THRESHOLD == 0.30
    assert PER_FINDING_CAP == 3
    assert ALGORITHM == "cosine-threshold-topk"
    assert "similarity desc" in TIE_BREAK_RULE
    assert "topic-index asc" in TIE_BREAK_RULE


# ---------------------------------------------------------------------------
# 13. Pure-helper unit tests
# ---------------------------------------------------------------------------


def test_topic_text_combines_title_and_summary():
    assert _topic_text({"title": "T", "summary": "S"}) == "T S"
    assert _topic_text({"title": "Only title"}) == "Only title"
    assert _topic_text({}) == ""


def test_finding_text_matches_pre_cluster_rule():
    """Same concatenation as Brief 1's pre_cluster stage and the
    clustering / calibration harnesses."""
    f = {"title": "T", "summary": "S", "description": "D"}
    assert _finding_text(f) == "T S D"
    assert _finding_text({"title": "T", "summary": "S"}) == "T S"


def test_assign_returns_topic_buckets_and_orphans():
    # 4 findings × 3 topics
    # finding 0: above thr for topic 0 only
    # finding 1: above thr for topics 0 and 1
    # finding 2: all below thr → orphan
    # finding 3: above thr for all three → cap binds
    sims = np.array([
        [0.8, 0.1, 0.1],
        [0.7, 0.6, 0.1],
        [0.1, 0.1, 0.1],
        [0.7, 0.6, 0.5],
    ], dtype=np.float64)
    topic_buckets, orphans = _assign(sims, threshold=0.4, cap=2)

    # finding 0 → topic 0
    assert (0, 0.8) in topic_buckets[0]
    # finding 1 → topics 0 and 1
    assert (1, 0.7) in topic_buckets[0]
    assert (1, 0.6) in topic_buckets[1]
    # finding 2 → orphan
    assert orphans[0][0] == 2
    # finding 3 → cap=2 picks topics 0 and 1 (highest similarity), drops 2
    assert (3, 0.7) in topic_buckets[0]
    assert (3, 0.6) in topic_buckets[1]
    # topic 2 should NOT contain finding 3
    assert all(fi != 3 for fi, _ in topic_buckets[2])


def test_assign_orders_assignments_within_topic_by_similarity_desc():
    sims = np.array([
        [0.3, 0.1],
        [0.7, 0.1],
        [0.5, 0.1],
    ], dtype=np.float64)
    topic_buckets, _ = _assign(sims, threshold=0.2, cap=2)
    bucket = topic_buckets[0]
    # Sorted by similarity descending: finding 1 (0.7), finding 2 (0.5), finding 0 (0.3)
    assert [fi for fi, _ in bucket] == [1, 2, 0]
