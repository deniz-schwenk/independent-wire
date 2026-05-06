"""Tests for scripts/render.py and scripts/publish.py — V2-schema path
correctness and HTML emission.

Stubbed minimal TP dicts exercise the public render functions without a
full pipeline run.
"""

from __future__ import annotations

from scripts.publish import extract_metadata
from scripts.render import (
    build_bias_card,
    build_coverage_gaps,
    build_meta_bar,
    build_missing_voices,
    build_perspectives,
)


# ---------------------------------------------------------------------------
# Commit 1 — six bug fixes (tests 1–6)
# ---------------------------------------------------------------------------


def test_position_clusters_section_renders_when_data_present():
    """Bug 1: perspectives is a dict with `position_clusters`, not a flat
    list. The section must render the cluster's position_label."""
    tp = {
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-001",
                    "position_label": "US administration",
                    "position_summary": "Imposes transit fees as economic pressure.",
                    "representation": "dominant",
                    "actors": [{"name": "Doe", "role": "Spokesperson"}],
                }
            ],
            "missing_positions": [],
        }
    }
    html = build_perspectives(tp)
    assert "US administration" in html
    assert 'class="card-position"' in html


def test_bias_card_renders_findings():
    """Bug 2: V2 path is `bias_analysis.language` (a list), not
    `language_bias.findings`. Severity has no V2 emission and is dropped."""
    tp = {
        "bias_analysis": {
            "language": [
                {
                    "issue": "loaded_term",
                    "excerpt": "regime",
                    "explanation": "Politically charged.",
                }
            ],
            "source": {"by_language": {"en": 5}},
        }
    }
    html = build_bias_card(tp)
    assert "1 language bias finding" in html
    assert "No language bias findings" not in html
    # Severity removed in V2 schema.
    assert "Severity:" not in html


def test_bias_card_no_findings_path():
    """Empty `language` list shows the "No language bias findings" string
    with no Severity badge."""
    tp = {"bias_analysis": {"language": [], "source": {"by_language": {}}}}
    html = build_bias_card(tp)
    assert "No language bias findings" in html
    assert "Severity:" not in html


def test_missing_voices_section_renders_when_data_present():
    """Bug 3: V2 path is `perspectives.missing_positions`, not nested
    under `bias_analysis.perspectives`."""
    tp = {
        "perspectives": {
            "position_clusters": [],
            "missing_positions": [
                {
                    "type": "affected_community",
                    "description": "Civilians in the strait region.",
                }
            ],
        }
    }
    html = build_missing_voices(tp)
    assert "Civilians in the strait region." in html
    assert "affected_community" in html


def test_coverage_gaps_section_renders_when_data_present():
    """Bug 4: V2 path is `bias_analysis.selection.coverage_gaps`."""
    tp = {
        "bias_analysis": {
            "selection": {
                "coverage_gaps": ["No on-the-ground reporting from Yemen."]
            }
        }
    }
    html = build_coverage_gaps(tp)
    assert "No on-the-ground reporting from Yemen." in html
    assert "<h2>Coverage Gaps</h2>" in html


def test_coverage_gaps_falls_back_to_top_level_gaps():
    """Bug 4 fallback: top-level `gaps` carries the same content."""
    tp = {"gaps": ["Statement from the affected ministry was not available."]}
    html = build_coverage_gaps(tp)
    assert "Statement from the affected ministry was not available." in html


def test_meta_bar_languages_count_correct():
    """Bug 5: V2 path is `bias_analysis.source.by_language`, not
    `source_balance.by_language`."""
    tp = {
        "sources": [{"id": "src-001"}],
        "bias_analysis": {
            "source": {"by_language": {"en": 4, "de": 3, "fa": 2}},
            "framing": {"distinct_actor_count": 0},
        },
        "divergences": [],
    }
    html = build_meta_bar(tp)
    # Stat line containing "3" in the Languages cell.
    assert ">3</span><span class=\"meta-label\">Languages<" in html


def test_meta_bar_stakeholders_uses_distinct_actor_count():
    """Bug 6: stakeholder count must read
    `bias_analysis.framing.distinct_actor_count`. The old bug returned 2
    (the count of dict keys in `perspectives`) — guard against it."""
    tp = {
        "sources": [],
        "bias_analysis": {
            "source": {"by_language": {}},
            "framing": {"distinct_actor_count": 18},
        },
        "perspectives": {"position_clusters": [], "missing_positions": []},
        "divergences": [],
    }
    html = build_meta_bar(tp)
    assert ">18</span><span class=\"meta-label\">Stakeholders<" in html
    # Regression guard: the old bug emitted 2 (the count of perspective dict keys).
    assert ">2</span><span class=\"meta-label\">Stakeholders<" not in html


def test_publish_extract_metadata_uses_v2_paths(tmp_path):
    """Index-card metadata extraction also needs the V2-schema paths.
    Languages count from `bias_analysis.source.by_language` and
    stakeholders from `bias_analysis.framing.distinct_actor_count`."""
    import json
    tp = {
        "id": "tp-2026-05-05-001",
        "metadata": {"date": "2026-05-05"},
        "article": {"headline": "h", "subheadline": "s", "summary": "x", "word_count": 100},
        "sources": [{"id": "src-001"}, {"id": "src-002"}],
        "perspectives": {"position_clusters": [], "missing_positions": []},
        "divergences": [],
        "bias_analysis": {
            "source": {"by_language": {"en": 1, "de": 1, "fa": 1, "ru": 1}},
            "framing": {"distinct_actor_count": 12},
        },
    }
    path = tmp_path / "tp.json"
    path.write_text(json.dumps(tp))
    meta = extract_metadata(path)
    assert meta["languages_count"] == 4
    assert meta["stakeholders_count"] == 12
