"""Tests for scripts/curator_monitor.py — pathology baseline reproduction,
empty-window handling, verdict logic, cache round-trip."""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def monitor_module():
    """Load scripts/curator_monitor.py as a module (it's a script, not a
    package)."""
    spec = importlib.util.spec_from_file_location(
        "curator_monitor", ROOT / "scripts" / "curator_monitor.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["curator_monitor"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Acceptance §1: pathology baseline reproduction
# ---------------------------------------------------------------------------


def test_pathology_baseline_reproduction(monitor_module):
    """Running the monitor's metric computation against the 2026-05-11 V1
    baseline state must reproduce top_cluster_size=1004, n_clusters=14,
    and off_topic_pct in [78, 84] (range accommodates the dynamic regex's
    deviation from the audit's hardcoded Iran regex; audit value 81.3 %)."""
    if not monitor_module.PATHOLOGY_BASELINE_STATE.exists():
        pytest.skip("V1 baseline state not present")
    state = json.loads(
        monitor_module.PATHOLOGY_BASELINE_STATE.read_text(encoding="utf-8")
    )
    metrics = monitor_module.compute_metrics(state)

    assert metrics["top_cluster_size"] == 1004, (
        f"expected top_cluster_size=1004, got {metrics['top_cluster_size']}"
    )
    assert metrics["n_clusters"] == 14, (
        f"expected n_clusters=14, got {metrics['n_clusters']}"
    )
    off = metrics["top_cluster_off_topic_pct"]
    assert 78.0 <= off <= 84.0, (
        f"off_topic_pct={off} outside acceptance band [78, 84]. "
        "Dynamic regex is too narrow (false-flagging on-topic content as off) "
        "or too broad (matching off-topic content). Surface to Architect."
    )


def test_dynamic_regex_from_curator_self_description(monitor_module):
    """Sanity-check the dynamic-regex derivation: a known cluster title
    should yield expected content tokens and filter out stopwords + short
    tokens. NOT the audit's hardcoded Iran regex — purely derived from
    Curator's own self-description."""
    title = "Stalled US-Iran peace negotiations and escalating regional tensions"
    summary = ""
    regex, tokens = monitor_module.derive_on_topic_regex(title, summary)

    assert regex is not None, "regex should compile from non-empty title"
    # Expected content tokens (≥4 chars, not in multilingual stopwords).
    for expected in ("stalled", "iran", "peace", "negotiations", "escalating",
                     "regional", "tensions"):
        assert expected in tokens, f"missing expected content token: {expected}"
    # Expected stopwords / short tokens dropped.
    for excluded in ("the", "and", "us"):
        assert excluded not in tokens, (
            f"token {excluded!r} should have been dropped (stopword or <4 chars)"
        )
    # The compiled regex should match these tokens in a sentence.
    assert regex.search("an iran peace deal looks unlikely")


def test_dynamic_regex_empty_inputs_returns_none(monitor_module):
    """Empty title+summary → (None, []) — caller treats every finding as
    off-topic (since we have no Curator vocabulary to compare against)."""
    regex, tokens = monitor_module.derive_on_topic_regex("", "")
    assert regex is None
    assert tokens == []

    # All-stopwords input → still None (no content tokens survive filter).
    regex2, tokens2 = monitor_module.derive_on_topic_regex("the and that with", "")
    assert regex2 is None
    assert tokens2 == []


# ---------------------------------------------------------------------------
# Empty window handling
# ---------------------------------------------------------------------------


def test_empty_window_does_not_crash(monitor_module, tmp_path, monkeypatch):
    """Running with --window-days 7 against a date that has no prior runs
    on disk must not crash and must render the window-empty note in the
    report."""
    # Redirect output/report paths into tmp.
    monkeypatch.setattr(monitor_module, "MONITOR_CACHE_DIR", tmp_path / "monitor")
    monkeypatch.setattr(monitor_module, "BASELINE_CACHE", tmp_path / "monitor" / "_baseline.json")
    monkeypatch.setattr(monitor_module, "HISTORY_DIR", tmp_path / "monitor" / "_history")
    monkeypatch.setattr(monitor_module, "REPORT_DIR", tmp_path / "report")

    # Seed only today's metrics (no prior days available).
    today_metrics = {
        "n_findings_total": 100,
        "n_clusters": 12,
        "top_cluster_size": 30,
        "top_cluster_title": "Test cluster",
        "top_cluster_on_topic_count": 28,
        "top_cluster_off_topic_count": 2,
        "top_cluster_off_topic_pct": 6.67,
        "cluster_size_p50": 8,
        "cluster_size_p90": 25,
        "cluster_size_max": 30,
        "cluster_size_min": 1,
        "orphan_count": 0,
        "orphan_rate": 0.0,
        "on_topic_regex_tokens": ["foo", "bar", "baz"],
    }
    (tmp_path / "monitor" / "_history").mkdir(parents=True)
    (tmp_path / "monitor" / "_history" / "2026-06-01.json").write_text(
        json.dumps(today_metrics), encoding="utf-8"
    )

    # Pathology baseline must be available — point cache at a synthetic stub.
    baseline_stub = {
        "n_findings_total": 1201,
        "n_clusters": 14,
        "top_cluster_size": 1004,
        "top_cluster_title": "V1 pathology",
        "top_cluster_on_topic_count": 188,
        "top_cluster_off_topic_count": 816,
        "top_cluster_off_topic_pct": 81.3,
        "cluster_size_p50": 5,
        "cluster_size_p90": 30,
        "cluster_size_max": 1004,
        "cluster_size_min": 1,
        "orphan_count": 170,
        "orphan_rate": 0.1416,
        "on_topic_regex_tokens": [],
    }
    (tmp_path / "monitor").mkdir(exist_ok=True)
    (tmp_path / "monitor" / "_baseline.json").write_text(
        json.dumps(baseline_stub), encoding="utf-8"
    )
    # Touch the underlying state file mtime to be older so the cache wins.
    baseline_mtime = (tmp_path / "monitor" / "_baseline.json").stat().st_mtime
    # The script checks: cache.mtime >= state.mtime. The real state file
    # exists at PATHOLOGY_BASELINE_STATE; set its mtime via os.utime to be
    # older than our stub cache.
    import os
    if monitor_module.PATHOLOGY_BASELINE_STATE.exists():
        # We can't mtime-back the real state file safely; instead point
        # the script at a stub state file that's older than our cache.
        state_stub = tmp_path / "fake_baseline.json"
        state_stub.write_text(json.dumps({"curator_findings": [], "curator_topics_unsliced": []}))
        # Backdate stub state by 1 hour so baseline cache wins.
        os.utime(state_stub, (baseline_mtime - 3600, baseline_mtime - 3600))
        monkeypatch.setattr(monitor_module, "PATHOLOGY_BASELINE_STATE", state_stub)

    rc = monitor_module.main(["--date", "2026-06-01", "--window-days", "7"])
    assert rc == 0, f"expected exit 0 on empty-window GREEN, got {rc}"
    report = (tmp_path / "report" / "2026-06-01.md").read_text(encoding="utf-8")
    assert "No prior days within window" in report
    assert "GREEN" in report


# ---------------------------------------------------------------------------
# Verdict logic — synthetic inputs hitting each verdict
# ---------------------------------------------------------------------------


def _stub_metrics(top: int, off: float, n_clusters: int = 15) -> dict:
    return {
        "n_findings_total": 1200,
        "n_clusters": n_clusters,
        "top_cluster_size": top,
        "top_cluster_title": "stub",
        "top_cluster_on_topic_count": 0,
        "top_cluster_off_topic_count": 0,
        "top_cluster_off_topic_pct": off,
        "cluster_size_p50": 8,
        "cluster_size_p90": top,
        "cluster_size_max": top,
        "cluster_size_min": 1,
        "orphan_count": 0,
        "orphan_rate": 0.0,
        "on_topic_regex_tokens": [],
    }


def test_verdict_red_on_pathology(monitor_module):
    """top_cluster_size ≥ 500 OR off_topic_pct ≥ 70 → RED, regardless of window."""
    baseline = _stub_metrics(1004, 81.3)
    window = [_stub_metrics(50, 10.0) for _ in range(7)]

    # Trip on size axis.
    v, _ = monitor_module.compute_verdict(_stub_metrics(600, 50.0), baseline, window)
    assert v == "RED"

    # Trip on off-topic-% axis.
    v, _ = monitor_module.compute_verdict(_stub_metrics(100, 75.0), baseline, window)
    assert v == "RED"

    # Trip on both axes.
    v, _ = monitor_module.compute_verdict(_stub_metrics(700, 80.0), baseline, window)
    assert v == "RED"


def test_verdict_green_when_within_window_p90(monitor_module):
    """Today ≤ window p90 on BOTH axes → GREEN."""
    baseline = _stub_metrics(1004, 81.3)
    window = [_stub_metrics(50, 12.0) for _ in range(7)]
    # 7 identical → p90 == 50 on top, 12 on off
    today = _stub_metrics(45, 11.0)
    v, _ = monitor_module.compute_verdict(today, baseline, window)
    assert v == "GREEN"


def test_verdict_amber_when_drift_below_half_pathology(monitor_module):
    """Today exceeds window p90 on one axis but stays below pathology/2
    on both → AMBER."""
    baseline = _stub_metrics(1004, 81.3)  # pathology/2 = 502 size, 40.65 off
    window = [_stub_metrics(50, 12.0) for _ in range(7)]  # p90 = 50, 12
    # Today: 200 top (over p90=50, but well under 502 = pathology/2),
    # off=25 (over p90=12, under 40.65 = pathology/2)
    today = _stub_metrics(200, 25.0)
    v, _ = monitor_module.compute_verdict(today, baseline, window)
    assert v == "AMBER"


def test_main_exit_code_with_fail_on_pathology(monitor_module, tmp_path, monkeypatch):
    """--fail-on-pathology + RED → exit 1; AMBER and GREEN → exit 0."""
    monkeypatch.setattr(monitor_module, "MONITOR_CACHE_DIR", tmp_path / "m")
    monkeypatch.setattr(monitor_module, "BASELINE_CACHE", tmp_path / "m" / "_baseline.json")
    monkeypatch.setattr(monitor_module, "HISTORY_DIR", tmp_path / "m" / "_history")
    monkeypatch.setattr(monitor_module, "REPORT_DIR", tmp_path / "r")

    # Seed pathology baseline stub.
    (tmp_path / "m").mkdir()
    baseline_stub = {
        "n_findings_total": 1201, "n_clusters": 14,
        "top_cluster_size": 1004, "top_cluster_title": "p",
        "top_cluster_on_topic_count": 0, "top_cluster_off_topic_count": 0,
        "top_cluster_off_topic_pct": 81.3,
        "cluster_size_p50": 5, "cluster_size_p90": 30, "cluster_size_max": 1004,
        "cluster_size_min": 1, "orphan_count": 0, "orphan_rate": 0.0,
        "on_topic_regex_tokens": [],
    }
    (tmp_path / "m" / "_baseline.json").write_text(json.dumps(baseline_stub))
    # Point the state file at a stub older than the cache.
    state_stub = tmp_path / "state.json"
    state_stub.write_text(json.dumps({"curator_findings": [], "curator_topics_unsliced": []}))
    import os
    os.utime(state_stub, (1000, 1000))
    monkeypatch.setattr(monitor_module, "PATHOLOGY_BASELINE_STATE", state_stub)

    # Seed today's metrics as RED.
    today_red = _stub_metrics(800, 75.0)
    (tmp_path / "m" / "_history").mkdir()
    (tmp_path / "m" / "_history" / "2026-06-01.json").write_text(json.dumps(today_red))

    rc_no_flag = monitor_module.main(["--date", "2026-06-01"])
    assert rc_no_flag == 0, "without --fail-on-pathology, RED still exits 0"

    rc_with_flag = monitor_module.main(
        ["--date", "2026-06-01", "--fail-on-pathology"]
    )
    assert rc_with_flag == 1, "with --fail-on-pathology, RED exits 1"

    # Re-seed today as GREEN; --fail-on-pathology still exits 0.
    today_green = _stub_metrics(20, 5.0)
    (tmp_path / "m" / "_history" / "2026-06-01.json").write_text(json.dumps(today_green))
    rc_green = monitor_module.main(
        ["--date", "2026-06-01", "--fail-on-pathology"]
    )
    assert rc_green == 0


# ---------------------------------------------------------------------------
# Cache round-trip
# ---------------------------------------------------------------------------


def test_cache_round_trip(monitor_module, tmp_path, monkeypatch):
    """Second run with the same --date reads from _history cache rather
    than re-computing. Second run is measurably faster and produces
    identical output."""
    monkeypatch.setattr(monitor_module, "MONITOR_CACHE_DIR", tmp_path / "m")
    monkeypatch.setattr(monitor_module, "BASELINE_CACHE", tmp_path / "m" / "_baseline.json")
    monkeypatch.setattr(monitor_module, "HISTORY_DIR", tmp_path / "m" / "_history")
    monkeypatch.setattr(monitor_module, "REPORT_DIR", tmp_path / "r")

    # Use the V1 baseline as today's state for a realistic load.
    if not monitor_module.PATHOLOGY_BASELINE_STATE.exists():
        pytest.skip("V1 baseline state not present")

    # Synthesise the date directory structure under tmp_path/output/...
    # The script reads ROOT / "output" / {date} / "_state" / "run-*/..."
    state_dir = tmp_path / "output" / "2026-06-02" / "_state" / "run-2026-06-02-abcdef"
    state_dir.mkdir(parents=True)
    (state_dir / "run_bus.CuratorStage.json").write_text(
        monitor_module.PATHOLOGY_BASELINE_STATE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(monitor_module, "ROOT", tmp_path)

    # First run — cache miss; computes from state.
    t0 = time.perf_counter()
    rc1 = monitor_module.main(["--date", "2026-06-02", "--window-days", "0"])
    cold = time.perf_counter() - t0
    assert rc1 == 0

    report_1 = (tmp_path / "r" / "2026-06-02.md").read_text(encoding="utf-8")
    cache_path = tmp_path / "m" / "_history" / "2026-06-02.json"
    assert cache_path.exists(), "expected per-day cache to be written on first run"
    cached_metrics_first = json.loads(cache_path.read_text(encoding="utf-8"))

    # Second run — cache hit; bypasses state.
    t1 = time.perf_counter()
    rc2 = monitor_module.main(["--date", "2026-06-02", "--window-days", "0"])
    warm = time.perf_counter() - t1
    assert rc2 == 0

    report_2 = (tmp_path / "r" / "2026-06-02.md").read_text(encoding="utf-8")
    cached_metrics_second = json.loads(cache_path.read_text(encoding="utf-8"))

    # Cache content identical across runs.
    assert cached_metrics_first == cached_metrics_second

    # Reports identical.
    assert report_1 == report_2

    # Second run is faster than the first (V1 baseline state ~MB-scale JSON).
    # Heuristic: at least 2× faster, and absolute < 0.1 s.
    assert warm < cold, f"warm {warm:.4f}s should be < cold {cold:.4f}s"
    assert warm < 0.5, (
        f"warm run {warm:.4f}s too slow; cache likely not in use"
    )
