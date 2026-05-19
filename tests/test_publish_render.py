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
    build_missing_coverage_section,
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
    """Perspectives is a dict with `position_clusters`, not a flat list.
    The section renders the position_label, position_summary, and a
    counts line — no inline actor list, no representation badge."""
    tp = {
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-001",
                    "position_label": "US administration",
                    "position_summary": "Imposes transit fees as economic pressure.",
                    "actor_ids": ["actor-001"],
                    "source_ids": ["src-001"],
                    "n_actors": 1,
                    "n_sources": 1,
                    "n_regions": 1,
                    "n_languages": 1,
                }
            ],
            "missing_positions": [],
        }
    }
    html = build_perspectives(tp)
    assert "US administration" in html
    assert 'class="card-position"' in html
    assert "Imposes transit fees as economic pressure." in html
    # Counts line replaces representation badge + inline actors
    assert 'class="cluster-counts"' in html
    assert "1 actor" in html
    assert "1 source" in html
    assert "1 region" in html
    assert "1 language" in html
    # The actor count is a clickable link to the cluster's filter hash
    # (the JS shim in build_actors_section listens for #cluster-{id})
    assert 'href="#cluster-pc-001"' in html
    # The cluster card itself is anchorable by its canonical id
    assert 'id="pc-001"' in html
    # No inline actor list anymore
    assert 'class="cluster-actors"' not in html
    assert 'class="badge"' not in html
    assert "dominant" not in html


def test_cluster_card_counts_use_singular_plural_correctly():
    """Singular forms for n=1, plural for n=0 / n>=2. Same for sources,
    regions, languages."""
    tp = {
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-001",
                    "position_label": "Empty",
                    "position_summary": "",
                    "actor_ids": [],
                    "source_ids": [],
                    "n_actors": 0,
                    "n_sources": 0,
                    "n_regions": 0,
                    "n_languages": 0,
                },
                {
                    "id": "pc-002",
                    "position_label": "Plural",
                    "position_summary": "",
                    "actor_ids": ["a", "b", "c"],
                    "source_ids": ["s", "t"],
                    "n_actors": 3,
                    "n_sources": 2,
                    "n_regions": 4,
                    "n_languages": 5,
                },
            ],
            "missing_positions": [],
        }
    }
    html = build_perspectives(tp)
    # Empty cluster: still renders "0 actors" plural form (n=0 → plural)
    assert "0 actors" in html
    assert "0 sources" in html
    assert "0 regions" in html
    assert "0 languages" in html
    # Multi cluster
    assert "3 actors" in html
    assert "2 sources" in html
    assert "4 regions" in html
    assert "5 languages" in html


def test_cluster_card_actor_entry_omits_source_list():
    """An actor entry inside a cluster's tier-block renders the
    name/role/type header but no source-anchor row. The full source
    attribution lives in the Actors-section card now; cluster cards
    stay scannable."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Araghchi",
                "role": "Foreign Minister",
                "type": "government",
                "source_ids": ["src-007", "src-012", "src-019"],
                "quotes": [
                    {"source_id": "src-007", "position": "p", "verbatim": None},
                    {"source_id": "src-012", "position": "p", "verbatim": None},
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-001",
                    "position_label": "Iranian government",
                    "position_summary": "Tehran's diplomatic posture.",
                    "actor_ids": ["actor-001"],
                    "stated": ["actor-001"],
                    "source_ids": ["src-007", "src-012"],
                    "n_actors": 1,
                    "n_sources": 2,
                    "n_regions": 1,
                    "n_languages": 1,
                }
            ],
            "missing_positions": [],
        },
    }
    html = build_perspectives(tp)
    # Tier-block actor entry renders the actor's anchor, role, type.
    assert 'class="cluster-tier-actor"' in html
    assert "Araghchi" in html
    assert "Foreign Minister" in html
    # The per-actor source-anchor row that used to live on the cluster
    # card is gone. The CSS span class is no longer emitted there,
    # and none of the actor's source ids appear as anchors within the
    # cluster-tier-actor markup.
    assert 'class="cluster-actor-srcs"' not in html
    # Slice to the tier-actor <li> block specifically — the cluster
    # card has no other reason to emit a `#src-NNN` link for this
    # actor, so we assert the tier-actor block carries none of them.
    block_start = html.find('class="cluster-tier-actor"')
    block_end = html.find("</li>", block_start)
    assert block_start != -1
    block = html[block_start:block_end]
    assert 'href="#src-007"' not in block
    assert 'href="#src-012"' not in block
    assert 'href="#src-019"' not in block


def test_cluster_card_actor_count_is_clickable_when_id_present():
    tp = {
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-007",
                    "position_label": "X",
                    "position_summary": "y",
                    "n_actors": 2,
                    "n_sources": 1,
                    "n_regions": 1,
                    "n_languages": 1,
                }
            ],
            "missing_positions": [],
        }
    }
    html = build_perspectives(tp)
    # Actor count wrapped in anchor to the cluster's filter hash
    assert '<a href="#cluster-pc-007">2 actors</a>' in html
    # Cluster card itself anchorable by canonical id
    assert 'id="pc-007"' in html


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


def test_bias_card_filters_self_retracted_findings():
    """`finding_valid: false` is the agent's self-retraction marker.
    Retracted findings stay in the TP JSON (audit trail) but the
    renderer drops them from the HTML. Surviving findings render in
    order of first appearance, and the count line reflects only the
    valid ones."""
    tp = {
        "bias_analysis": {
            "language": [
                {
                    "issue": "loaded_term",
                    "excerpt": "regime",
                    "explanation": "Politically charged.",
                    "finding_valid": True,
                },
                {
                    "issue": "intensifier",
                    "excerpt": "utterly",
                    "explanation": "Adds rhetorical force; not a "
                                   "real bias on review.",
                    "finding_valid": False,
                },
                {
                    "issue": "evaluative_adjective",
                    "excerpt": "controversial",
                    "explanation": "Value-laden modifier.",
                    "finding_valid": True,
                },
                {
                    "issue": "hedging",
                    "excerpt": "perhaps",
                    "explanation": "Not actually loaded.",
                    "finding_valid": False,
                },
            ],
            "source": {"by_language": {"en": 5}},
        }
    }
    html = build_bias_card(tp)
    # Count line reflects only the valid findings.
    assert "2 language bias findings" in html
    # Retracted excerpts must not appear anywhere in the rendered HTML.
    assert "utterly" not in html
    assert "perhaps" not in html
    assert "Adds rhetorical force" not in html
    assert "Not actually loaded" not in html
    # Valid findings render in order of first appearance.
    regime_idx = html.find("regime")
    controversial_idx = html.find("controversial")
    assert 0 <= regime_idx < controversial_idx


def test_bias_card_legacy_findings_without_finding_valid_all_render():
    """Pre-2026-05-19 TP JSONs do not carry `finding_valid` on findings.
    The renderer is legacy-permissive at this boundary — missing field
    is treated as valid, so all such findings still render."""
    tp = {
        "bias_analysis": {
            "language": [
                {
                    "issue": "loaded_term",
                    "excerpt": "regime",
                    "explanation": "Politically charged.",
                },
                {
                    "issue": "intensifier",
                    "excerpt": "utterly",
                    "explanation": "Adds rhetorical force.",
                },
            ],
            "source": {"by_language": {"en": 5}},
        }
    }
    html = build_bias_card(tp)
    assert "2 language bias findings" in html
    assert "regime" in html
    assert "utterly" in html


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


# ---------------------------------------------------------------------------
# Unified "What this dossier does not cover" + legacy fallback
# ---------------------------------------------------------------------------


def test_missing_coverage_unified_section_renders_both_sub_sections():
    """When `consolidated_missing_coverage` is present and populated,
    the unified section is emitted with both sub-section headings; the
    legacy builders self-skip."""
    tp = {
        "consolidated_missing_coverage": {
            "missing_stakeholder_voices": [
                {
                    "type": "industry",
                    "description": "oil traders, shipping companies, "
                                   "and insurance underwriters",
                }
            ],
            "missing_topic_dimensions": [
                "European Union diplomatic response to the crisis",
            ],
        },
        # Audit-trail source fields still carry data; the unified
        # renderer reads the consolidated slot, not these.
        "perspectives": {
            "missing_positions": [
                {"type": "industry", "description": "oil traders..."},
            ],
        },
        "gaps": ["oil traders, shipping companies, insurance underwriters",
                 "European Union diplomatic response to the crisis"],
    }
    unified = build_missing_coverage_section(tp)
    legacy_voices = build_missing_voices(tp)
    legacy_gaps = build_coverage_gaps(tp)

    # Unified section emitted with the new header.
    assert "<h2>What this dossier does not cover</h2>" in unified
    # Both sub-sections render with their `h3` headings.
    assert "Missing stakeholder voices" in unified
    assert "Missing topic dimensions" in unified
    # Voice and dimension content surface within the unified section.
    assert "oil traders" in unified
    assert "European Union diplomatic response" in unified
    # Legacy builders self-skip when the consolidated slot is present.
    assert legacy_voices == ""
    assert legacy_gaps == ""


def test_missing_coverage_legacy_fallback_when_slot_absent():
    """Pre-2026-05-20 TP JSONs do not carry the consolidated slot. The
    unified renderer returns empty, and the legacy
    `build_missing_voices` + `build_coverage_gaps` render in their
    original positions, unchanged."""
    tp = {
        "perspectives": {
            "missing_positions": [
                {"type": "civil_society", "description": "Affected communities"},
            ],
        },
        "gaps": [
            "European Union diplomatic response to the crisis",
        ],
    }
    unified = build_missing_coverage_section(tp)
    legacy_voices = build_missing_voices(tp)
    legacy_gaps = build_coverage_gaps(tp)

    # Unified is empty — no consolidated slot present.
    assert unified == ""
    # Legacy renderers fire with their original headings + content.
    assert "What's missing" in legacy_voices
    assert "Affected communities" in legacy_voices
    assert "<h2>Coverage Gaps</h2>" in legacy_gaps
    assert "European Union diplomatic response" in legacy_gaps


def test_missing_coverage_unified_section_omits_empty_sub_section():
    """An empty list in one of the two axes drops only that sub-section;
    the other still renders. Both empty → whole section omitted."""
    # Only voices populated.
    tp_voices_only = {
        "consolidated_missing_coverage": {
            "missing_stakeholder_voices": [
                {"type": "industry", "description": "oil traders"},
            ],
            "missing_topic_dimensions": [],
        }
    }
    html = build_missing_coverage_section(tp_voices_only)
    assert "Missing stakeholder voices" in html
    assert "Missing topic dimensions" not in html

    # Only dimensions populated.
    tp_dims_only = {
        "consolidated_missing_coverage": {
            "missing_stakeholder_voices": [],
            "missing_topic_dimensions": ["A topic dimension"],
        }
    }
    html = build_missing_coverage_section(tp_dims_only)
    assert "Missing topic dimensions" in html
    assert "Missing stakeholder voices" not in html

    # Both empty.
    tp_empty = {
        "consolidated_missing_coverage": {
            "missing_stakeholder_voices": [],
            "missing_topic_dimensions": [],
        }
    }
    assert build_missing_coverage_section(tp_empty) == ""


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
    """The stat line surfaces cluster_count, distinct_actor_count,
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


def test_representation_pills_section_removed():
    """The dominant/substantial/marginal pills section is gone — UX1/UX2/UX3
    in Task E will redesign the bias-card body."""
    tp = {
        "sources": [],
        "bias_analysis": {
            "language": [],
            "source": {"by_language": {}, "total": 0},
            "framing": {
                "cluster_count": 0,
                "distinct_actor_count": 0,
            },
        },
    }
    html = build_bias_card(tp)
    assert 'class="representation-pills"' not in html
    assert "pill-dominant" not in html
    assert "pill-substantial" not in html
    assert "pill-marginal" not in html


def test_sources_section_renders_outlet_block_with_full_meta():
    """Outlet has both Country and editorial_independence: meta line
    shows {Country} · {editorial_independence}."""
    tp = {
        "sources": [
            {
                "id": "src-001", "outlet": "Al Jazeera", "title": "T",
                "url": "https://example.com/a", "language": "en",
                "country": "Qatar",
                "editorial_independence": "publicly_funded_autonomous",
                "summary": "Lead.", "estimated_date": "2026-05-04",
                "actors_quoted": [],
            }
        ],
        "actors": [],
    }
    html = build_sources_table(tp)
    assert 'id="sources-section"' in html
    assert 'class="outlet-block"' in html
    assert "Al Jazeera" in html
    # Outlet meta shows both Country and editorial_independence
    assert "Qatar" in html
    assert "publicly_funded_autonomous" in html
    # No "not yet categorized" when both fields populated
    assert "not yet categorized" not in html
    # Source [N] label
    assert ">[1]<" in html
    # <li id="src-001"> for direct anchor
    assert 'id="src-001"' in html
    # Headline links to the source URL
    assert 'href="https://example.com/a"' in html


def test_sources_section_outlet_meta_country_only_falls_back():
    """Country present but editorial_independence missing: meta line
    shows {Country} · not yet categorized."""
    tp = {
        "sources": [
            {
                "id": "src-001", "outlet": "Al-Bayan", "title": "T",
                "language": "ar", "country": "Iran",
                "summary": "x",
                "actors_quoted": [],
            }
        ],
        "actors": [],
    }
    html = build_sources_table(tp)
    assert "Iran" in html
    assert "not yet categorized" in html


def test_sources_section_outlet_meta_neither_field_present():
    """Both Country and editorial_independence missing: meta line is
    just 'not yet categorized'."""
    tp = {
        "sources": [
            {
                "id": "src-001", "outlet": "ZZZ Unknown Site",
                "title": "T", "summary": "x", "actors_quoted": [],
            }
        ],
        "actors": [],
    }
    html = build_sources_table(tp)
    assert "not yet categorized" in html


def test_sources_section_bias_note_renders_when_present():
    tp = {
        "sources": [
            {
                "id": "src-001", "outlet": "Al Jazeera", "title": "T",
                "language": "en", "country": "Qatar",
                "editorial_independence": "publicly_funded_autonomous",
                "bias_note": "Qatar-funded, strong Global South coverage",
                "summary": "x", "actors_quoted": [],
            }
        ],
        "actors": [],
    }
    html = build_sources_table(tp)
    assert 'class="source-bias-note"' in html
    assert "Qatar-funded" in html


def test_sources_section_bias_note_omitted_when_absent():
    tp = {
        "sources": [
            {
                "id": "src-001", "outlet": "Al Jazeera", "title": "T",
                "language": "en", "country": "Qatar",
                "summary": "x", "actors_quoted": [],
            }
        ],
        "actors": [],
    }
    html = build_sources_table(tp)
    assert 'class="source-bias-note"' not in html


def test_sources_section_actors_refs_with_anchor_links():
    tp = {
        "sources": [
            {
                "id": "src-001", "outlet": "Al Jazeera", "title": "T",
                "language": "en", "country": "Qatar", "summary": "x",
                "actors_quoted": [
                    {"name": "Donald Trump", "role": "P", "type": "government",
                     "position": "p"},
                    {"name": "Hakan Fidan", "role": "FM", "type": "government",
                     "position": "p"},
                ],
            }
        ],
        "actors": [
            {"id": "actor-001", "name": "Donald Trump"},
            {"id": "actor-007", "name": "Hakan Fidan"},
        ],
    }
    html = build_sources_table(tp)
    assert 'class="source-actors-refs"' in html
    assert 'href="#actor-001">Donald Trump' in html
    assert 'href="#actor-007">Hakan Fidan' in html


def test_sources_section_actors_refs_dedup_same_canonical():
    """Three actors_quoted entries that all resolve to the same canonical
    actor render exactly one link. Two distinct canonicals quoted by the
    same source render as two links in order of first appearance.

    The dedup key is canonical id, so name variants ("Trump" via the
    alias_mapping vs "Donald Trump" canonical) collapse as well."""
    tp = {
        "sources": [
            {
                "id": "src-001", "outlet": "Reuters", "title": "T",
                "language": "en", "country": "US", "summary": "x",
                "actors_quoted": [
                    {"name": "Donald Trump", "role": "P", "type": "government",
                     "position": "p"},
                    # Same canonical, second quote — must collapse.
                    {"name": "Donald Trump", "role": "P", "type": "government",
                     "position": "p2"},
                    # Distinct canonical — must render as a separate link.
                    {"name": "Hakan Fidan", "role": "FM", "type": "government",
                     "position": "p"},
                    # Name variant resolved via actor_alias_mapping — same
                    # canonical id as the first two entries, must collapse.
                    {"name": "Trump", "role": "P", "type": "government",
                     "position": "p3"},
                    # Third raw-name duplicate — must collapse.
                    {"name": "Donald Trump", "role": "P", "type": "government",
                     "position": "p4"},
                ],
            }
        ],
        "actors": [
            {"id": "actor-001", "name": "Donald Trump"},
            {"id": "actor-007", "name": "Hakan Fidan"},
        ],
        "actor_alias_mapping": [
            {"alias_id": "actor-002", "alias_name": "Trump",
             "canonical_id": "actor-001"},
        ],
    }
    html = build_sources_table(tp)
    # Trump link appears exactly once; Hakan Fidan link appears exactly once.
    assert html.count('href="#actor-001">') == 1
    assert html.count('href="#actor-007">') == 1
    # Order of first appearance: Trump comes before Fidan in the rendered
    # actor-refs line.
    refs_idx = html.find('class="source-actors-refs"')
    assert refs_idx != -1
    trump_idx = html.find('href="#actor-001">', refs_idx)
    fidan_idx = html.find('href="#actor-007">', refs_idx)
    assert 0 <= trump_idx < fidan_idx


def test_sources_section_outlets_sorted_alphabetically():
    tp = {
        "sources": [
            {"id": "src-001", "outlet": "Zeit", "title": "z", "summary": "x", "actors_quoted": []},
            {"id": "src-002", "outlet": "Al Jazeera", "title": "a", "summary": "x", "actors_quoted": []},
            {"id": "src-003", "outlet": "Middle East Eye", "title": "m", "summary": "x", "actors_quoted": []},
        ],
        "actors": [],
    }
    html = build_sources_table(tp)
    pos_aj = html.find("Al Jazeera")
    pos_mee = html.find("Middle East Eye")
    pos_z = html.find("Zeit")
    assert pos_aj < pos_mee < pos_z


def test_sources_section_source_id_label_matches_canonical():
    """The [N] label is derived from the source's id, stripping the
    src- prefix and leading zeros."""
    tp = {
        "sources": [
            {"id": "src-007", "outlet": "X", "title": "t", "summary": "x", "actors_quoted": []},
            {"id": "src-042", "outlet": "X", "title": "t", "summary": "x", "actors_quoted": []},
        ],
        "actors": [],
    }
    html = build_sources_table(tp)
    assert ">[7]<" in html
    assert ">[42]<" in html


def test_qa_correction_expandable_with_problem_detail():
    """Aligned qa_corrections / qa_problems_found arrays render
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
    assert "<details" in html
    # Summary contains the correction text (single quotes are HTML-escaped)
    # and the applied tag.
    assert "Replace " in html and "Council leadership" in html
    assert "tag-applied" in html
    # Detail block contains the problem fields.
    assert 'class="qa-detail"' in html
    assert "misleading_framing" in html
    assert "European Council leadership noted" in html
    assert "António Costa" in html


def test_qa_corrections_wrapper_renders_with_counts():
    """The outer <details> wrapper carries 'N applied · M retracted'
    in its summary, default closed."""
    tp = {
        "transparency": {
            "qa_corrections": [
                {"proposed_correction": "fix1", "correction_needed": True},
                {"proposed_correction": "fix2", "correction_needed": True},
                {"proposed_correction": "fix3", "correction_needed": True},
                {"proposed_correction": "skip1", "correction_needed": False},
                {"proposed_correction": "skip2", "correction_needed": False},
            ],
            "qa_problems_found": [],
        }
    }
    html = build_transparency(tp)
    assert 'class="qa-corrections-wrapper"' in html
    assert "3 applied" in html
    assert "2 retracted" in html
    # Default closed — the wrapper element has no `open` attribute. The
    # inner per-correction details may still render `open=False` too.
    assert 'class="qa-corrections-wrapper" open' not in html


def test_qa_corrections_wrapper_omitted_when_no_corrections():
    """Empty qa_corrections → wrapper not emitted; the QA Corrections
    <dt> doesn't appear at all (matches the strict-drop pattern)."""
    tp = {
        "transparency": {
            "qa_corrections": [],
            "qa_problems_found": [],
            "selection_reason": "x",
        }
    }
    html = build_transparency(tp)
    assert "qa-corrections-wrapper" not in html
    assert "QA Corrections" not in html


def test_qa_corrections_wrapper_all_applied():
    """All entries with correction_needed=True → '5 applied · 0 retracted'."""
    tp = {
        "transparency": {
            "qa_corrections": [
                {"proposed_correction": f"fix{i}", "correction_needed": True}
                for i in range(5)
            ],
            "qa_problems_found": [],
        }
    }
    html = build_transparency(tp)
    assert "5 applied" in html
    assert "0 retracted" in html


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
