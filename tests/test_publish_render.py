"""Tests for scripts/render.py and scripts/publish.py — V2-schema path
correctness and HTML emission.

Stubbed minimal TP dicts exercise the public render functions without a
full pipeline run.
"""

from __future__ import annotations

from scripts.publish import extract_metadata
from scripts.render import (
    build_actors_section,
    build_bias_card,
    build_meta_bar,
    build_perspectives,
    build_mentioned_actors_section,
    build_sources_table,
    build_transparency,
    build_what_is_missing_section,
    render,
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


# ---------------------------------------------------------------------------
# Zero-actor position cards: editorial-outlet attribution block
# ---------------------------------------------------------------------------


def test_cluster_card_editorial_attribution_when_no_actors_and_sources_present():
    """When a position cluster has zero actors across all tiers but its
    source_ids reference outlets in tp["sources"], the card renders an
    "Editorial position attributed to: <outlets>" block in place of the
    missing tier sub-lists."""
    tp = {
        "sources": [
            {"id": "src-001", "outlet": "Le Monde",
             "title": "t", "summary": "x", "actors_quoted": []},
            {"id": "src-002", "outlet": "Süddeutsche Zeitung",
             "title": "t", "summary": "x", "actors_quoted": []},
            {"id": "src-003", "outlet": "Reuters",
             "title": "t", "summary": "x", "actors_quoted": []},
        ],
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-001",
                    "position_label": "Editorial framing",
                    "position_summary": "Sources interpret events through ...",
                    "actor_ids": [],
                    "stated": [],
                    "reported": [],
                    "mentioned": [],
                    "source_ids": ["src-001", "src-002", "src-003"],
                    "n_actors": 0,
                    "n_sources": 3,
                    "n_regions": 3,
                    "n_languages": 2,
                }
            ],
            "missing_positions": [],
        },
    }
    html = build_perspectives(tp)
    assert "Editorial position attributed to:" in html
    assert 'class="cluster-editorial-attribution"' in html
    assert "<strong>Le Monde</strong>" in html
    assert "<strong>Süddeutsche Zeitung</strong>" in html
    assert "<strong>Reuters</strong>" in html


def test_cluster_card_no_editorial_attribution_when_actors_present():
    """When the cluster has at least one actor in a tier sub-list, the
    tier blocks own the surface — no editorial-attribution block."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "X", "role": "r", "type": "government",
             "source_ids": ["src-001"], "quotes": []},
        ],
        "sources": [
            {"id": "src-001", "outlet": "Le Monde",
             "title": "t", "summary": "x", "actors_quoted": []},
        ],
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-001",
                    "position_label": "L",
                    "position_summary": "s",
                    "actor_ids": ["actor-001"],
                    "stated": ["actor-001"],
                    "source_ids": ["src-001"],
                    "n_actors": 1,
                    "n_sources": 1,
                    "n_regions": 1,
                    "n_languages": 1,
                }
            ],
            "missing_positions": [],
        },
    }
    html = build_perspectives(tp)
    assert "Editorial position attributed to:" not in html
    assert 'class="cluster-editorial-attribution"' not in html


def test_cluster_card_no_editorial_attribution_when_zero_actors_and_zero_sources():
    """Defensive edge case: card with 0 actors and 0 sources renders
    label + summary + counts line only — no attribution block (would
    produce 'Editorial position attributed to:' with nothing after)."""
    tp = {
        "sources": [],
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
                }
            ],
            "missing_positions": [],
        },
    }
    html = build_perspectives(tp)
    assert "Editorial position attributed to:" not in html
    assert 'class="cluster-editorial-attribution"' not in html


def test_cluster_card_editorial_attribution_deduplicates_outlets():
    """Two source_ids pointing to the same outlet name produce one
    entry in the attribution block (preserving order from tp["sources"])."""
    tp = {
        "sources": [
            {"id": "src-001", "outlet": "Reuters",
             "title": "t", "summary": "x", "actors_quoted": []},
            {"id": "src-002", "outlet": "Reuters",
             "title": "t", "summary": "x", "actors_quoted": []},
            {"id": "src-003", "outlet": "Le Monde",
             "title": "t", "summary": "x", "actors_quoted": []},
        ],
        "perspectives": {
            "position_clusters": [
                {
                    "id": "pc-001",
                    "position_label": "Editorial framing",
                    "position_summary": "...",
                    "actor_ids": [],
                    "source_ids": ["src-001", "src-002", "src-003"],
                    "n_actors": 0,
                    "n_sources": 3,
                    "n_regions": 1,
                    "n_languages": 1,
                }
            ],
            "missing_positions": [],
        },
    }
    html = build_perspectives(tp)
    assert "Editorial position attributed to:" in html
    # Outlet appears exactly once even though two source_ids point to it
    assert html.count("<strong>Reuters</strong>") == 1
    assert html.count("<strong>Le Monde</strong>") == 1
    # Order matches tp["sources"] order: Reuters first, then Le Monde
    reuters_pos = html.find("<strong>Reuters</strong>")
    lemonde_pos = html.find("<strong>Le Monde</strong>")
    assert reuters_pos < lemonde_pos


# ---------------------------------------------------------------------------
# Mentioned-actors section (build_mentioned_actors_section + Actors-section row)
# ---------------------------------------------------------------------------


def test_mentioned_actors_section_renders_with_full_shape():
    """Acceptance criterion: the section renders inside a default-closed
    `<details class="mentioned-actors-wrapper">` collapsible with a
    summary line of the form ``Mentioned Actors — N noted``. The inner
    card retains its bracket-specific CSS class (`single-voices-bracket`)
    and the `mentioned-actors` DOM anchor."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Health Minister",
             "role": "Minister", "type": "government",
             "source_ids": ["src-001", "src-002"], "quotes": []},
            {"id": "actor-002", "name": "WHO Spokesperson",
             "role": "Spokesperson", "type": "international_org",
             "source_ids": ["src-003"], "quotes": []},
        ],
        "perspectives": {
            "position_clusters": [],
            "mentioned_actors": {
                "position_label": "Mentioned actors",
                "summary": "Actors named in the corpus who are not grouped ...",
                "actors_stated": ["actor-001"],
                "actors_reported": ["actor-002"],
                "actors_mentioned": [],
                "actor_ids": ["actor-001", "actor-002"],
                "source_ids": ["src-001", "src-002", "src-003"],
                "counts": {
                    "actors": 2, "sources": 3, "regions": 2, "languages": 2,
                },
            },
        },
    }
    html = build_mentioned_actors_section(tp)
    # Collapsible wrapper present, default closed (no `open` attribute).
    assert '<details class="mentioned-actors-wrapper">' in html
    assert '<details class="mentioned-actors-wrapper" open' not in html
    # Summary line uses the "N noted" pattern (plural for N != 1).
    assert "Mentioned Actors" in html
    assert "2 noted" in html
    # Inner card retains the bracket-specific CSS class and the
    # `mentioned-actors` DOM anchor.
    assert 'class="card single-voices-bracket"' in html
    assert 'id="mentioned-actors"' in html
    # Header carries the position-label and the "Bracket" tag.
    assert "Mentioned actors" in html
    assert 'class="single-voices-bracket-tag"' in html
    assert "Bracket" in html
    # Position summary surfaces.
    assert "not grouped" in html
    # Tier sub-blocks render with the expected labels and actors.
    assert ">Stated<" in html
    assert ">Reported<" in html
    assert "Health Minister" in html
    assert "WHO Spokesperson" in html
    # Counts line uses the bracket's `counts` dict, not derived from
    # `actor_ids` length, so a mismatch would surface.
    assert "2 actors" in html
    assert "3 sources" in html
    assert "2 regions" in html
    assert "2 languages" in html


def test_mentioned_actors_section_summary_singular_when_one_actor():
    """Singular `1 noted` for the N=1 case (the only edge that needs the
    pluralisation rule)."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Sole Witness",
             "role": "r", "type": "government",
             "source_ids": ["src-001"], "quotes": []},
        ],
        "perspectives": {
            "position_clusters": [],
            "mentioned_actors": {
                "position_label": "Mentioned actors",
                "summary": "...",
                "actors_stated": ["actor-001"],
                "actors_reported": [],
                "actors_mentioned": [],
                "actor_ids": ["actor-001"],
                "source_ids": ["src-001"],
                "counts": {
                    "actors": 1, "sources": 1, "regions": 0, "languages": 0,
                },
            },
        },
    }
    html = build_mentioned_actors_section(tp)
    assert "1 note</strong>" in html
    # Singular `note` is NOT followed by 'd' or 's' here — guard
    # against accidental "1 noted" / "1 notes" emission.
    assert "1 noted" not in html
    assert "1 notes" not in html


def test_mentioned_actors_section_omitted_when_actor_ids_empty():
    """Acceptance criterion: section omitted entirely (no empty
    `<details>` shell) when the slot carries zero qualifying actors."""
    tp = {
        "actors": [],
        "perspectives": {
            "position_clusters": [],
            "mentioned_actors": {
                "position_label": "Mentioned actors",
                "summary": "...",
                "actors_stated": [],
                "actors_reported": [],
                "actors_mentioned": [],
                "actor_ids": [],
                "source_ids": [],
                "counts": {
                    "actors": 0, "sources": 0, "regions": 0, "languages": 0,
                },
            },
        },
    }
    assert build_mentioned_actors_section(tp) == ""


def test_mentioned_actors_section_omitted_when_slot_absent():
    """Acceptance criterion: legacy-permissive. A TP JSON without the
    `mentioned_actors` slot (pre-this-change publish) renders the rest
    of the page unchanged — the function returns empty string."""
    tp = {
        "actors": [],
        "perspectives": {"position_clusters": []},
    }
    assert build_mentioned_actors_section(tp) == ""


def test_actors_section_card_for_bracket_actor_shows_mentioned_actors_box():
    """An actor in the mentioned-actors bracket sees a ``Mentioned actors``
    cluster-ref box on their card, anchored at ``#mentioned-actors``.
    The box carries the bracket-variant CSS class."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Orphan Protagonist",
             "role": "Minister", "type": "government",
             "source_ids": ["src-001", "src-002"], "quotes": []},
        ],
        "perspectives": {
            "position_clusters": [],
            "mentioned_actors": {
                "actors_stated": ["actor-001"],
                "actors_reported": [],
                "actors_mentioned": [],
                "actor_ids": ["actor-001"],
                "source_ids": ["src-001", "src-002"],
                "counts": {
                    "actors": 1, "sources": 2, "regions": 0, "languages": 0,
                },
            },
        },
    }
    html = build_actors_section(tp)
    assert (
        '<a class="actor-card-cluster-box actor-card-cluster-box--bracket"'
        ' href="#mentioned-actors">Mentioned actors</a>'
    ) in html
    # No spurious Cluster/Position-N box for this orphan.
    assert 'href="#pc-' not in html
    # Legacy vocab should no longer surface anywhere in the section.
    assert "Single voices" not in html


def test_actors_section_card_for_non_bracket_actor_omits_mentioned_actors_box():
    """An actor NOT in the bracket must not see a Mentioned actors box on
    their card, even when a bracket exists in the TP."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Clustered",
             "role": "r", "type": "government",
             "source_ids": ["src-001"], "quotes": []},
            {"id": "actor-002", "name": "Bracketed",
             "role": "r", "type": "government",
             "source_ids": ["src-001", "src-002"], "quotes": []},
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"],
                 "source_ids": ["src-001"]},
            ],
            "mentioned_actors": {
                "actors_stated": ["actor-002"],
                "actors_reported": [],
                "actors_mentioned": [],
                "actor_ids": ["actor-002"],
                "source_ids": ["src-001", "src-002"],
                "counts": {
                    "actors": 1, "sources": 2, "regions": 0, "languages": 0,
                },
            },
        },
    }
    html = build_actors_section(tp)
    # actor-001's card carries the Position 1 box but no Mentioned actors.
    actor1_start = html.find('id="actor-001"')
    actor1_end = html.find('</article>', actor1_start)
    actor1_card = html[actor1_start:actor1_end]
    assert 'href="#pc-001">Position 1' in actor1_card
    assert "Mentioned actors" not in actor1_card
    # actor-002's card carries Mentioned actors (and no cluster ref).
    actor2_start = html.find('id="actor-002"')
    actor2_end = html.find('</article>', actor2_start)
    actor2_card = html[actor2_start:actor2_end]
    assert 'href="#mentioned-actors">Mentioned actors' in actor2_card
    # Legacy vocab gone everywhere.
    assert "Cluster 1" not in html
    assert "Single voices" not in html


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


# ---------------------------------------------------------------------------
# What is missing — Consolidator output section
# ---------------------------------------------------------------------------


def test_what_is_missing_section_renders_both_lists():
    """Both voices and topics populated → section renders with the
    "What is missing" H2 and both sub-headers. Voices come first."""
    tp = {
        "what_is_missing": {
            "voices_missing": [
                "Iraqi government and media voices",
                "International humanitarian organizations",
            ],
            "topics_missing": [
                "Humanitarian dimension of the US oil blockade",
            ],
        },
    }
    html = build_what_is_missing_section(tp)
    assert "<h2>What is missing</h2>" in html
    assert "Voices missing" in html
    assert "Topics missing" in html
    assert "Iraqi government and media voices" in html
    assert "International humanitarian organizations" in html
    assert "Humanitarian dimension of the US oil blockade" in html
    # Voices section comes before Topics section in the rendered HTML.
    assert html.find("Voices missing") < html.find("Topics missing")


def test_what_is_missing_section_only_voices():
    """Topics empty → only the Voices sub-header renders."""
    tp = {
        "what_is_missing": {
            "voices_missing": ["A missing voice"],
            "topics_missing": [],
        },
    }
    html = build_what_is_missing_section(tp)
    assert "<h2>What is missing</h2>" in html
    assert "Voices missing" in html
    assert "A missing voice" in html
    assert "Topics missing" not in html


def test_what_is_missing_section_only_topics():
    """Voices empty → only the Topics sub-header renders."""
    tp = {
        "what_is_missing": {
            "voices_missing": [],
            "topics_missing": ["A missing topic"],
        },
    }
    html = build_what_is_missing_section(tp)
    assert "<h2>What is missing</h2>" in html
    assert "Topics missing" in html
    assert "A missing topic" in html
    assert "Voices missing" not in html


def test_what_is_missing_section_both_empty_omits_section():
    """Both lists empty → empty string (section omitted from page)."""
    tp = {
        "what_is_missing": {
            "voices_missing": [],
            "topics_missing": [],
        },
    }
    assert build_what_is_missing_section(tp) == ""


def test_what_is_missing_section_key_absent_omits_section():
    """Legacy TP rendered before the Consolidator landed — no
    `what_is_missing` key in the JSON; section is omitted."""
    tp = {"perspectives": {"position_clusters": []}}
    assert build_what_is_missing_section(tp) == ""


def test_what_is_missing_section_non_dict_value_omits_section():
    """Defensive — `what_is_missing` value must be a dict; non-dict
    types (None, string, list, int) return empty so a malformed legacy
    TP cannot crash the renderer."""
    assert build_what_is_missing_section({"what_is_missing": None}) == ""
    assert build_what_is_missing_section({"what_is_missing": "x"}) == ""
    assert build_what_is_missing_section({"what_is_missing": []}) == ""


def test_what_is_missing_section_filters_non_string_entries():
    """Defensive — only non-empty string entries surface; null/empty/
    non-string entries are silently dropped rather than crashing or
    rendering as ``None``."""
    tp = {
        "what_is_missing": {
            "voices_missing": ["valid voice", "", None, 42, "another voice"],
            "topics_missing": [None, "valid topic", ""],
        },
    }
    html = build_what_is_missing_section(tp)
    assert "valid voice" in html
    assert "another voice" in html
    assert "valid topic" in html
    # The non-string entries must not appear as their str() rendering.
    assert ">None<" not in html
    assert ">42<" not in html
    # Empty <li></li> entries are not emitted.
    assert "<li></li>" not in html


def test_what_is_missing_section_escapes_html_in_entries():
    """Defensive — entries containing HTML special chars are escaped
    (no raw ``<``, ``&``, etc. surface into the output)."""
    tp = {
        "what_is_missing": {
            "voices_missing": ["A voice with <script>alert(1)</script>"],
            "topics_missing": ["Topic with & ampersand"],
        },
    }
    html = build_what_is_missing_section(tp)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "& ampersand" not in html  # raw `&` would mean `&` then space
    assert "&amp; ampersand" in html


def test_what_is_missing_section_renders_before_sources_in_full_page():
    """Integration: in the full rendered page, the new "What is
    missing" section appears directly before the Sources section."""
    tp = {
        "id": "tp-2026-05-27-001",
        "metadata": {
            "title": "Test Topic", "date": "2026-05-27", "topic_slug": "t",
            "priority": 5, "selection_reason": "r",
        },
        "article": {"headline": "H", "body": "B", "summary": "S"},
        "sources": [
            {"id": "src-001", "outlet": "Reuters", "url": "https://r/", "title": "t"},
        ],
        "actors": [],
        "final_actors": [],
        "perspectives": {"position_clusters": [], "missing_positions": []},
        "what_is_missing": {
            "voices_missing": ["MARKER_VOICE_FROM_CONSOLIDATOR"],
            "topics_missing": ["MARKER_TOPIC_FROM_CONSOLIDATOR"],
        },
        "divergences": [],
        "transparency": {"selection_reason": "r"},
        "bias_analysis": {
            "language": [], "source": {"by_country": {}, "by_language": {}, "represented": [], "total": 1},
            "geographical": {"represented": [], "by_country": {}, "missing_from_dossier": []},
            "selection": {"missing_positions": [], "qa_problems_found": []},
            "framing": {"position_clusters_summary": [], "cross_source_divergences": [], "cluster_count": 0, "distinct_actor_count": 0},
            "reader_note": "",
        },
    }
    page = render(tp)
    voice_marker_idx = page.find("MARKER_VOICE_FROM_CONSOLIDATOR")
    topic_marker_idx = page.find("MARKER_TOPIC_FROM_CONSOLIDATOR")
    sources_h2_idx = page.find("<h2>Sources</h2>")

    assert voice_marker_idx >= 0, "voice entry must appear in the page"
    assert topic_marker_idx >= 0, "topic entry must appear in the page"
    assert sources_h2_idx >= 0, "Sources H2 must appear in the page"
    # The new section's content sits before the Sources H2.
    assert voice_marker_idx < sources_h2_idx, (
        "Voices entry from what_is_missing must render before Sources"
    )
    assert topic_marker_idx < sources_h2_idx, (
        "Topics entry from what_is_missing must render before Sources"
    )


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


def test_sources_section_third_level_renders_per_actor_entries():
    """Acceptance criterion: each source's third-level disclosable
    block carries one entry per actor whose quote.source_id matches.
    Entry shape: anchor + role + position summary + verbatim italics."""
    tp = {
        "sources": [
            {
                "id": "src-001",
                "outlet": "Al Jazeera",
                "title": "Iran-Israel war update",
                "summary": "Coverage of the day.",
                "language": "en",
                "actors_quoted": [{"name": "Trump"}, {"name": "Pezeshkian"}],
            },
        ],
        "actors": [
            {
                "id": "actor-001",
                "name": "Trump",
                "role": "United States President",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [
                    {"source_id": "src-001",
                     "position": "Suspended a planned attack on Iran.",
                     "verbatim": "We will respond if necessary."},
                ],
            },
            {
                "id": "actor-002",
                "name": "Pezeshkian",
                "role": "Iranian President",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [
                    {"source_id": "src-001",
                     "position": "Iran will not surrender.",
                     "verbatim": None},
                ],
            },
        ],
    }
    html = build_sources_table(tp)
    # The disclosable block is present.
    assert 'class="source-quotes"' in html
    assert "<summary>Quote details</summary>" in html
    # Per-actor entries with anchor + role.
    assert '<a href="#actor-001">Trump</a>' in html
    assert '<a href="#actor-002">Pezeshkian</a>' in html
    assert "United States President" in html
    assert "Iranian President" in html
    # Position summaries surface.
    assert "Suspended a planned attack on Iran." in html
    assert "Iran will not surrender." in html
    # Verbatim quote wraps in <em> with quotation marks.
    assert 'class="source-quote-verbatim"' in html
    assert "We will respond if necessary." in html


def test_sources_section_third_level_includes_lang_tag_for_non_english():
    """Acceptance criterion: the source-language tag appears inline
    near the verbatim quote when the source language is not English."""
    tp = {
        "sources": [
            {
                "id": "src-005",
                "outlet": "Tasnim",
                "title": "Iranian statement",
                "summary": "Persian-language coverage.",
                "language": "fa",
                "actors_quoted": [{"name": "Araghchi"}],
            },
        ],
        "actors": [
            {
                "id": "actor-001",
                "name": "Araghchi",
                "role": "Foreign Minister",
                "type": "government",
                "source_ids": ["src-005"],
                "quotes": [
                    {"source_id": "src-005",
                     "position": "Diplomatic channels remain open.",
                     "verbatim": "تهران آماده مذاکره است"},
                ],
            },
        ],
    }
    html = build_sources_table(tp)
    # Language tag rendered as <code class="source-quote-lang"> with the
    # source language, inline with the verbatim quote.
    assert 'class="source-quote-lang"' in html
    assert ">fa</code>" in html


def test_sources_section_third_level_omitted_when_no_usable_content():
    """Acceptance criterion: third-level block is omitted entirely when
    a source's actors have neither position text nor verbatim — the
    existing 'Actors quoted:' anchor row stays as today."""
    tp = {
        "sources": [
            {
                "id": "src-001",
                "outlet": "Al Jazeera",
                "title": "Headline only",
                "summary": "Brief coverage.",
                "language": "en",
                "actors_quoted": [{"name": "Trump"}],
            },
        ],
        "actors": [
            {
                "id": "actor-001",
                "name": "Trump",
                "role": "US President",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [
                    # Quote exists but neither position nor verbatim is
                    # populated. The third-level block must be omitted.
                    {"source_id": "src-001", "position": "", "verbatim": None},
                ],
            },
        ],
    }
    html = build_sources_table(tp)
    # The 'Actors quoted:' anchor row remains.
    assert 'class="source-actors-refs"' in html
    assert "Actors quoted:" in html
    # No third-level block.
    assert 'class="source-quotes"' not in html


def test_sources_section_third_level_omitted_when_no_matching_quote():
    """When the source's actors carry no quotes whose source_id matches
    the source's id, the third-level block is omitted (no entries to
    render)."""
    tp = {
        "sources": [
            {
                "id": "src-001",
                "outlet": "Outlet",
                "title": "T",
                "summary": "x",
                "language": "en",
                "actors_quoted": [{"name": "Person"}],
            },
        ],
        "actors": [
            {
                "id": "actor-001",
                "name": "Person",
                "role": "r",
                "type": "t",
                "source_ids": ["src-002"],
                "quotes": [
                    {"source_id": "src-002",
                     "position": "From another source.",
                     "verbatim": None},
                ],
            },
        ],
    }
    html = build_sources_table(tp)
    assert 'class="source-quotes"' not in html


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
