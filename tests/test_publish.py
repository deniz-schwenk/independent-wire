"""Tests for ``scripts/publish.py`` covering the per-date numbering reset
and the publication-cutoff filter from TASK-PUBLISH-NUMBERING-AND-CUTOFF.

The tests exercise the three pure helpers (``build_index``,
``filter_jsons_by_cutoff``, ``remove_pre_cutoff_reports``) and one
integration test that drives ``publish.py main()`` as a subprocess to
verify the ``--date`` cutoff guard.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_publish_module():
    """Import ``scripts/publish.py`` as a module — it lives outside the
    package path because ``scripts/`` is not a Python package."""
    spec = importlib.util.spec_from_file_location(
        "scripts_publish", REPO_ROOT / "scripts" / "publish.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_meta(tp_id: str, date: str, *, headline: str = "H") -> dict:
    """Synthetic meta record — matches the shape produced by
    ``extract_metadata`` for ``build_index`` to consume."""
    return {
        "id": tp_id,
        "date": date,
        "headline": headline,
        "subheadline": "sub",
        "summary": "summary",
        "html_filename": f"reports/{tp_id}.html",
        "sources_count": 5,
        "languages_count": 3,
        "stakeholders_count": 4,
        "divergences_count": 2,
        "word_count": 800,
        "follow_up": None,
    }


# ---------------------------------------------------------------------------
# 1. Per-date numbering reset
# ---------------------------------------------------------------------------


def test_card_index_resets_per_date():
    """Two dates × three TPs each — each date block must start at TOPIC 01."""
    publish = _load_publish_module()
    metas = [
        _make_meta("tp-2026-05-08-001", "2026-05-08"),
        _make_meta("tp-2026-05-08-002", "2026-05-08"),
        _make_meta("tp-2026-05-08-003", "2026-05-08"),
        _make_meta("tp-2026-05-07-001", "2026-05-07"),
        _make_meta("tp-2026-05-07-002", "2026-05-07"),
        _make_meta("tp-2026-05-07-003", "2026-05-07"),
    ]
    html = publish.build_index(metas)

    # Each TP gets a `TOPIC NN / tp-...` label. With per-date reset, both
    # dates produce 01/02/03; without reset the second date would emit
    # 04/05/06.
    for tp_id in [
        "tp-2026-05-08-001", "tp-2026-05-07-001",
    ]:
        assert f'TOPIC 01 / {tp_id}' in html, (
            f"expected first card of each date to read TOPIC 01; missing for {tp_id}"
        )
    for tp_id in [
        "tp-2026-05-08-002", "tp-2026-05-07-002",
    ]:
        assert f'TOPIC 02 / {tp_id}' in html
    for tp_id in [
        "tp-2026-05-08-003", "tp-2026-05-07-003",
    ]:
        assert f'TOPIC 03 / {tp_id}' in html

    # Negative assertion: the bug-shape labels must not appear.
    assert 'TOPIC 04' not in html
    assert 'TOPIC 05' not in html
    assert 'TOPIC 06' not in html


def test_follow_up_link_degrades_to_text_when_target_missing(tmp_path):
    """Follow-up references whose target HTML doesn't exist in
    ``reports_dir`` render as plain text rather than as a dead
    ``<a href>``. Catches the regression where the cutoff cleanup
    removes a pre-cutoff TP's HTML while a post-cutoff TP still
    references it via ``metadata.follow_up``."""
    publish = _load_publish_module()
    reports = tmp_path / "reports"
    reports.mkdir()
    # Only the post-cutoff TP exists in reports/; the pre-cutoff target
    # does not — simulating the post-cleanup state.
    (reports / "tp-2026-05-08-001.html").write_text("dummy", encoding="utf-8")

    meta = _make_meta("tp-2026-05-08-001", "2026-05-08")
    meta["follow_up"] = {
        "previous_tp_id": "tp-2026-05-05-001",
        "previous_headline": "Earlier dossier",
        "previous_date": "2026-05-05",
    }

    html = publish.build_index([meta], reports_dir=reports)
    # Plain-text follow-up — no `<a href>` for the missing target.
    assert "Earlier dossier" in html
    assert 'href="reports/tp-2026-05-05-001.html"' not in html
    # The label and date still render.
    assert "Follow-up to:" in html
    assert "May 5, 2026" in html


def test_follow_up_link_renders_anchor_when_target_present(tmp_path):
    publish = _load_publish_module()
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "tp-2026-05-05-001.html").write_text("dummy", encoding="utf-8")

    meta = _make_meta("tp-2026-05-08-001", "2026-05-08")
    meta["follow_up"] = {
        "previous_tp_id": "tp-2026-05-05-001",
        "previous_headline": "Earlier dossier",
        "previous_date": "2026-05-05",
    }

    html = publish.build_index([meta], reports_dir=reports)
    assert 'href="reports/tp-2026-05-05-001.html"' in html
    assert "Earlier dossier" in html


# ---------------------------------------------------------------------------
# 2. Cutoff filter excludes pre-cutoff TPs
# ---------------------------------------------------------------------------


def test_cutoff_filters_pre_cutoff_dates(tmp_path):
    """``filter_jsons_by_cutoff`` splits TPs by the cutoff date — pre-cutoff
    paths land in the ``excluded`` list and must not appear in ``kept``."""
    publish = _load_publish_module()
    paths = [
        tmp_path / "tp-2026-05-05-001.json",
        tmp_path / "tp-2026-05-06-001.json",
        tmp_path / "tp-2026-05-07-001.json",
        tmp_path / "tp-2026-05-08-001.json",
    ]
    for p in paths:
        p.touch()

    kept, excluded = publish.filter_jsons_by_cutoff(paths, "2026-05-07")
    assert sorted(p.name for p in kept) == [
        "tp-2026-05-07-001.json", "tp-2026-05-08-001.json",
    ]
    assert sorted(p.name for p in excluded) == [
        "tp-2026-05-05-001.json", "tp-2026-05-06-001.json",
    ]


def test_remove_pre_cutoff_reports_cleans_stale_html(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    for name in [
        "tp-2026-04-15-001.html",
        "tp-2026-05-05-001.html",
        "tp-2026-05-07-001.html",
        "tp-2026-05-08-001.html",
    ]:
        (reports / name).write_text("dummy", encoding="utf-8")

    publish = _load_publish_module()
    removed = publish.remove_pre_cutoff_reports(reports, "2026-05-07")

    assert removed == 2
    surviving = sorted(p.name for p in reports.iterdir())
    assert surviving == [
        "tp-2026-05-07-001.html", "tp-2026-05-08-001.html",
    ]


# ---------------------------------------------------------------------------
# 3. Missing config disables the cutoff
# ---------------------------------------------------------------------------


def test_cutoff_missing_config_no_filter(tmp_path):
    """``filter_jsons_by_cutoff`` with ``cutoff=None`` is a no-op — every
    path is kept regardless of date. This is the backwards-compat path
    when ``config/site_config.json`` is absent."""
    publish = _load_publish_module()
    paths = [
        tmp_path / "tp-2026-04-15-001.json",
        tmp_path / "tp-2026-05-08-001.json",
    ]
    for p in paths:
        p.touch()

    kept, excluded = publish.filter_jsons_by_cutoff(paths, None)
    assert sorted(p.name for p in kept) == [p.name for p in paths]
    assert excluded == []


def test_load_site_config_returns_empty_when_missing(tmp_path, monkeypatch):
    """When ``config/site_config.json`` does not exist on disk,
    ``load_site_config`` returns ``{}`` so callers degrade to no cutoff."""
    publish = _load_publish_module()
    fake_root = tmp_path  # no `config/` subdir → load returns {}
    monkeypatch.setattr(publish, "ROOT", fake_root)
    assert publish.load_site_config() == {}


# ---------------------------------------------------------------------------
# 4. --date guard refuses pre-cutoff dates with a clear error
# ---------------------------------------------------------------------------


def test_date_flag_before_cutoff_errors(tmp_path):
    """Driving ``publish.py`` as a subprocess with ``--date 2026-05-05``
    against the live ``config/site_config.json`` (cutoff 2026-05-07) must
    exit non-zero with the explanatory error message on stderr."""
    config_path = REPO_ROOT / "config" / "site_config.json"
    if not config_path.exists():
        pytest.skip("config/site_config.json not present — guard inactive")
    cutoff = json.loads(config_path.read_text(encoding="utf-8")).get(
        "published_from_date"
    )
    if not cutoff:
        pytest.skip("published_from_date missing from config — guard inactive")

    # Pick a date that's strictly before the cutoff; if cutoff is the
    # earliest possible, skip.
    pre_cutoff_date = "2026-01-01"
    if pre_cutoff_date >= cutoff:
        pytest.skip("cutoff is earlier than 2026-01-01 — no valid pre-cutoff date")

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "publish.py"),
            "--date", pre_cutoff_date,
            "--output-dir", str(tmp_path),  # empty output dir; guard fires first
        ],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    assert result.returncode == 1, (
        f"expected exit 1 (cutoff guard) — got {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "Cutoff date in config/site_config.json" in result.stderr
    assert pre_cutoff_date in result.stderr
    assert cutoff in result.stderr
