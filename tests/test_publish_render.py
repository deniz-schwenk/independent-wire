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
    build_sources_table,
    build_transparency,
)


# ---------------------------------------------------------------------------
# Strict-drop pruning collapsible
# ---------------------------------------------------------------------------


def test_transparency_renders_dropped_collapsible_when_non_empty():
    """When transparency.dropped_sources or dropped_clusters is non-empty,
    a collapsible section appears with a summary line containing the
    counts and an expandable body listing each drop."""
    tp = {
        "transparency": {
            "selection_reason": "x",
            "dropped_sources": [
                {"id": "src-007", "outlet": "Off-topic Daily",
                 "summary": "An unrelated story"},
                {"id": "src-009", "outlet": "Other", "summary": "Another"},
            ],
            "dropped_clusters": [
                {"id": "pc-002", "position_label": "Dropped position"}
            ],
            "pipeline_run": {"run_id": "r", "date": "2026-05-05"},
        }
    }
    html = build_transparency(tp)
    assert "Strict-drop Pruning" in html
    assert 'class="dropped-details"' in html
    assert "2 sources dropped" in html
    assert "1 cluster dropped" in html
    assert "src-007" in html
    assert "Off-topic Daily" in html
    assert "src-009" in html
    assert "pc-002" in html
    assert "Dropped position" in html


def test_transparency_no_dropped_section_when_arrays_empty():
    """Both dropped_sources and dropped_clusters empty → the collapsible
    is not emitted at all."""
    tp = {
        "transparency": {
            "selection_reason": "x",
            "dropped_sources": [],
            "dropped_clusters": [],
            "pipeline_run": {"run_id": "r", "date": "2026-05-05"},
        }
    }
    html = build_transparency(tp)
    assert "Strict-drop Pruning" not in html
    assert 'class="dropped-details"' not in html


def test_transparency_dropped_section_sources_only():
    """When only dropped_sources is non-empty, the summary mentions only
    sources and the body shows only the Sources sub-block."""
    tp = {
        "transparency": {
            "selection_reason": "x",
            "dropped_sources": [
                {"id": "src-007", "outlet": "Off-topic Daily", "summary": "..."}
            ],
            "dropped_clusters": [],
            "pipeline_run": {"run_id": "r", "date": "2026-05-05"},
        }
    }
    html = build_transparency(tp)
    assert "Strict-drop Pruning" in html
    assert "1 source dropped" in html
    assert "cluster" not in html.split("Strict-drop Pruning")[1].split("</details>")[0]


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


# ---------------------------------------------------------------------------
# Commit 2 — five data-gap renderings (tests 7–11)
# ---------------------------------------------------------------------------


def test_bias_stats_line_renders():
    """Item 2: stat line surfaces cluster_count, distinct_actor_count,
    source.total, and len(by_language)."""
    tp = {
        "sources": [],
        "bias_analysis": {
            "language": [],
            "source": {
                "by_language": {"en": 1, "de": 1, "fa": 1, "ru": 1},
                "total": 13,
            },
            "framing": {
                "cluster_count": 9,
                "distinct_actor_count": 18,
                "representation_distribution": {
                    "dominant": 0,
                    "substantial": 3,
                    "marginal": 6,
                },
            },
        },
    }
    html = build_bias_card(tp)
    assert 'class="bias-stats"' in html
    # All four numbers present in the bias-stats block.
    stats_start = html.find('class="bias-stats"')
    stats_end = html.find("</p>", stats_start)
    stats_block = html[stats_start:stats_end]
    assert "<strong>9</strong>" in stats_block
    assert "<strong>18</strong>" in stats_block
    assert "<strong>13</strong>" in stats_block
    assert "<strong>4</strong>" in stats_block


def test_representation_pills_render_with_zero_dominant():
    """Item 3: three pills in fixed order. Zero counts render at reduced
    opacity 0.4 — visible, not hidden."""
    tp = {
        "sources": [],
        "bias_analysis": {
            "language": [],
            "source": {"by_language": {}, "total": 0},
            "framing": {
                "cluster_count": 0,
                "distinct_actor_count": 0,
                "representation_distribution": {
                    "dominant": 0,
                    "substantial": 3,
                    "marginal": 6,
                },
            },
        },
    }
    html = build_bias_card(tp)
    assert 'class="representation-pills"' in html
    # All three pills render.
    assert "0 dominant" in html
    assert "3 substantial" in html
    assert "6 marginal" in html
    # Dominant pill (count 0) gets reduced opacity styling.
    pill_start = html.find("pill-dominant")
    pill_end = html.find("</span>", pill_start)
    dominant_pill = html[pill_start:pill_end]
    assert "opacity:0.4" in dominant_pill
    # Non-zero pills do not get reduced opacity.
    sub_start = html.find("pill-substantial")
    sub_end = html.find("</span>", sub_start)
    substantial_pill = html[sub_start:sub_end]
    assert "opacity:1" in substantial_pill


def test_source_row_expandable_actors_when_present():
    """Item 1: a source with actors_quoted gets a `<details>` expandable
    sibling row showing each actor's name."""
    tp = {
        "sources": [
            {
                "id": "src-001",
                "outlet": "Al Jazeera",
                "title": "T",
                "language": "en",
                "country": "Qatar",
                "actors_quoted": [
                    {
                        "name": "Hakan Fidan",
                        "role": "Foreign Minister",
                        "type": "government",
                        "position": "Discussed regional developments.",
                    },
                    {
                        "name": "Donald Trump",
                        "role": "United States President",
                        "type": "government",
                        "position": "Warned of escalation.",
                        "verbatim_quote": "blown off the face of the earth",
                    },
                ],
            }
        ]
    }
    html = build_sources_table(tp)
    assert 'class="source-actors"' in html
    assert "2 actors quoted" in html
    assert "Hakan Fidan" in html
    assert "Donald Trump" in html
    # Verbatim quote rendered as a blockquote.
    assert 'class="actor-verbatim"' in html
    assert "blown off the face of the earth" in html


def test_source_row_no_expandable_when_actors_empty():
    """Item 1 negative: source with empty actors_quoted gets no
    `<details>` block — the row stays as today."""
    tp = {
        "sources": [
            {
                "id": "src-001",
                "outlet": "Reuters",
                "title": "T",
                "language": "en",
                "country": "United Kingdom",
                "actors_quoted": [],
            }
        ]
    }
    html = build_sources_table(tp)
    assert 'class="source-actors"' not in html
    assert "actors quoted" not in html


def test_qa_correction_expandable_with_problem_detail():
    """Item 5: aligned qa_corrections / qa_problems_found arrays render
    expandable details containing the proposed correction in summary and
    the problem-type / excerpt / explanation in the detail block."""
    tp = {
        "transparency": {
            "qa_corrections": [
                {
                    "proposed_correction": "Replace 'Council leadership' with 'Council President António Costa'.",
                    "correction_needed": True,
                }
            ],
            "qa_problems_found": [
                {
                    "problem": "misleading_framing",
                    "article_excerpt": "European Council leadership noted that the forum was meeting...",
                    "explanation": "Source src-008 attributes the statement specifically to António Costa.",
                }
            ],
        }
    }
    html = build_transparency(tp)
    assert "<details>" in html
    # Summary contains the correction text (single quotes are HTML-escaped)
    # and the applied tag.
    assert "Replace " in html and "Council leadership" in html
    assert "tag-applied" in html
    # Detail block contains the problem fields.
    assert 'class="qa-detail"' in html
    assert "misleading_framing" in html
    assert "European Council leadership noted" in html
    assert "António Costa" in html


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
