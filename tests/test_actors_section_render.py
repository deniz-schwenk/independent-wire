"""Tests for ``build_actors_section`` in ``scripts/render.py``.

After the 2026-05-20 redesign (commit landing this brief), the
Actors-section is a grouped card grid with a type-tab filter, not a
flat table. The section continues to serve as navigation bridge —
cluster cards and the single-voices bracket back-link to
``#actor-NNN`` anchors that live on the cards.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.render import build_actors_section


# ---------------------------------------------------------------------------
# Header + sub-line
# ---------------------------------------------------------------------------


def test_empty_actors_renders_header_without_card_grid():
    """No actors → section emits the plain ``<h2>Actors</h2>`` header
    and the sub-line; no tab bar, no card grid."""
    tp = {"actors": [], "perspectives": {"position_clusters": []}}
    html = build_actors_section(tp)
    assert 'id="actors-section"' in html
    assert "<h2>Actors</h2>" in html
    assert "0 actors quoted across this topic" in html
    assert 'class="actors-tabs"' not in html
    assert 'class="actor-card-grid"' not in html


def test_header_is_plain_h2_no_section_number_no_right_count():
    """Header matches every other section heading: plain
    ``<h2>Actors</h2>``, left-aligned, no ``§03`` section number, no
    right-aligned ``N ACTORS`` count. The actor count is conveyed by
    the sub-line directly below."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": [], "quotes": []},
            {"id": "actor-002", "name": "B", "role": "r", "type": "military",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # Plain H2 (no nested span).
    assert "<h2>Actors</h2>" in html
    # No section-number, no actors-count, no actors-header flex
    # wrapper, no §-prefix in any form.
    assert "section-number" not in html
    assert "actors-count" not in html
    assert "actors-header" not in html
    assert "&sect;" not in html
    assert "§" not in html
    # Sub-line in full.
    assert (
        "2 actors quoted across this topic. Jump from any name above "
        "to find every position and source the actor figures in."
    ) in html
    # No type-count phrasing leaks in.
    assert "TYPES" not in html
    assert "2 types" not in html.lower()


# ---------------------------------------------------------------------------
# Tab bar
# ---------------------------------------------------------------------------


def test_tab_bar_renders_all_first_then_populated_types_in_enum_order():
    """Acceptance criterion: tab bar carries ALL N followed by one tab
    per populated enum type in declared order. Zero-count enum types
    are omitted entirely (no disabled placeholder).

    Enum order: government, legislature, judiciary, military, industry,
    civil_society, academia, media, international_org,
    affected_community.
    """
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": [], "quotes": []},
            {"id": "actor-002", "name": "B", "role": "r", "type": "government",
             "source_ids": [], "quotes": []},
            {"id": "actor-003", "name": "C", "role": "r", "type": "military",
             "source_ids": [], "quotes": []},
            {"id": "actor-004", "name": "D", "role": "r", "type": "civil_society",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # ALL tab first, then only the three populated enum types in
    # enum order: government, military, civil_society.
    idx_all = html.find('data-type-target="all"')
    idx_gov = html.find('data-type-target="government"')
    idx_mil = html.find('data-type-target="military"')
    idx_cs = html.find('data-type-target="civil_society"')
    assert 0 <= idx_all < idx_gov < idx_mil < idx_cs
    # Zero-count enum types do NOT appear as tabs.
    for empty in ("legislature", "judiciary", "industry", "academia",
                  "media", "international_org", "affected_community"):
        assert f'data-type-target="{empty}"' not in html
    # Per-tab counts on the populated types.
    assert ">4</span>" in html  # ALL = 4
    block = html[idx_gov:idx_gov + 400]
    assert "GOVERNMENT" in block
    assert ">2</span>" in block
    block = html[idx_mil:idx_mil + 400]
    assert "MILITARY" in block
    assert ">1</span>" in block
    block = html[idx_cs:idx_cs + 400]
    assert "CIVIL SOCIETY" in block
    assert ">1</span>" in block


def test_zero_count_enum_type_tab_omitted_entirely():
    """Correction 1 (2026-05-20): a tab whose count is 0 is not
    rendered at all — no disabled placeholder, no greyed-out shell.
    The tab simply does not exist."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # Military, civil_society, etc. all have count 0 in this fixture.
    for empty in ("military", "civil_society", "media", "academia",
                  "legislature", "judiciary", "industry",
                  "international_org", "affected_community"):
        assert f'data-type-target="{empty}"' not in html
    # No remnants of the disabled treatment.
    assert "actor-tab--disabled" not in html
    assert " disabled" not in html
    # ALL + government only.
    assert 'data-type-target="all"' in html
    assert 'data-type-target="government"' in html


def test_all_tab_is_active_by_default():
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # Find ALL button and confirm actor-tab--active is in its markup.
    idx = html.find('data-type-target="all"')
    block = html[idx - 200:idx + 200]
    assert "actor-tab--active" in block


# ---------------------------------------------------------------------------
# Card grid — grouping and sorting
# ---------------------------------------------------------------------------


def test_card_grid_groups_in_enum_order_government_before_military():
    """Acceptance criterion: groups render in enum order. Government
    comes before military because that is the enum declared order."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Soldier", "role": "r", "type": "military",
             "source_ids": ["src-001"], "quotes": []},
            {"id": "actor-002", "name": "Minister", "role": "r", "type": "government",
             "source_ids": ["src-002"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    gov_idx = html.find('data-actor-type="government"')
    mil_idx = html.find('data-actor-type="military"')
    assert 0 <= gov_idx < mil_idx


def test_card_grid_within_group_sorted_by_source_count_desc():
    """Acceptance criterion: within a group, cards are sorted by
    source-ref count desc."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Few", "role": "r", "type": "government",
             "source_ids": ["src-001"], "quotes": []},
            {"id": "actor-002", "name": "Many", "role": "r", "type": "government",
             "source_ids": ["src-001", "src-002", "src-003"], "quotes": []},
            {"id": "actor-003", "name": "Mid", "role": "r", "type": "government",
             "source_ids": ["src-001", "src-002"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    pos_many = html.find('id="actor-002"')
    pos_mid = html.find('id="actor-003"')
    pos_few = html.find('id="actor-001"')
    # Descending order of source counts: 3, 2, 1.
    assert 0 <= pos_many < pos_mid < pos_few


def test_card_grid_name_breaks_tie_when_source_counts_equal():
    """Tie-break is the actor name (case-insensitive ascending)."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Zelda", "role": "r", "type": "government",
             "source_ids": ["src-001"], "quotes": []},
            {"id": "actor-002", "name": "Aaron", "role": "r", "type": "government",
             "source_ids": ["src-002"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    pos_aaron = html.find('id="actor-002"')
    pos_zelda = html.find('id="actor-001"')
    assert 0 <= pos_aaron < pos_zelda


def test_card_grid_has_no_group_subheadings_or_meta_lines():
    """Correction 2 (2026-05-20): cards render as one continuous grid
    with no per-type sub-heading and no ``N actors · M source refs``
    meta line. The active tab is the only label naming the active
    group; ALL view shows the cards flat in enum order across the
    underlying type groups."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": ["src-001", "src-002"], "quotes": []},
            {"id": "actor-002", "name": "B", "role": "r", "type": "government",
             "source_ids": ["src-001", "src-003"], "quotes": []},
            {"id": "actor-003", "name": "C", "role": "r", "type": "military",
             "source_ids": ["src-001"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # No group sub-heading element of any flavour.
    assert "<h3" not in html
    assert "actor-group" not in html  # catches actor-group, -header, -name, -meta
    # No "N actors · M source refs" meta line in any case.
    assert "source ref" not in html
    # Humanised group names never appear as page text — only the
    # uppercase tab labels do (e.g. "GOVERNMENT" inside the tab span).
    assert ">Government<" not in html
    assert ">Military<" not in html


# ---------------------------------------------------------------------------
# Per-card content
# ---------------------------------------------------------------------------


def test_card_renders_name_src_count_role_and_anchor():
    """Acceptance criterion: card carries name, "N SRC", role, and
    ``id="actor-NNN"`` anchor."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Donald Trump",
                "role": "President of the United States",
                "type": "government",
                "source_ids": ["src-001", "src-002", "src-003"],
                "quotes": [],
            },
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert 'id="actor-001"' in html
    assert "Donald Trump" in html
    assert ">3 SRC<" in html
    assert "President of the United States" in html


def test_card_renders_position_box_for_each_membership_with_pc_anchor():
    """Acceptance criterion: cross-reference boxes use the ``Position N``
    label (renamed 2026-05-21 from ``Cluster N``) and anchor at
    ``#pc-NNN``. The internal CSS class name (`actor-card-cluster-box`)
    is unchanged — it's an internal identifier, not user-visible."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": ["src-001"], "quotes": []},
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
                {"id": "pc-003", "actor_ids": ["actor-001"], "source_ids": []},
            ],
        },
    }
    html = build_actors_section(tp)
    assert '<a class="actor-card-cluster-box" href="#pc-001">Position 1</a>' in html
    assert '<a class="actor-card-cluster-box" href="#pc-003">Position 2</a>' in html
    # Legacy "Cluster N" wording must no longer surface anywhere.
    assert "Cluster 1" not in html
    assert "Cluster 2" not in html


def test_card_renders_source_box_for_each_source_id_with_src_anchor():
    """Acceptance criterion: source-ref boxes labelled ``src-NNN``
    anchor at ``#src-NNN``. Duplicate source ids collapse."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": ["src-007", "src-001", "src-007"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert '<a class="actor-card-source-box" href="#src-007">src-007</a>' in html
    assert '<a class="actor-card-source-box" href="#src-001">src-001</a>' in html
    # Dedup: src-007 appears only once as a box.
    assert html.count(
        '<a class="actor-card-source-box" href="#src-007">src-007</a>'
    ) == 1


def test_bracket_actor_card_renders_mentioned_actors_box_to_mentioned_actors():
    """Acceptance criterion: an actor in the mentioned-actors bracket
    sees a cross-reference box reading ``Mentioned actors`` linking to
    ``#mentioned-actors``. The box carries the bracket-variant CSS class
    (visually distinct from regular Position-N boxes)."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Orphan", "role": "r", "type": "government",
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
                "counts": {"actors": 1, "sources": 2, "regions": 0, "languages": 0},
            },
        },
    }
    html = build_actors_section(tp)
    assert (
        '<a class="actor-card-cluster-box actor-card-cluster-box--bracket"'
        ' href="#mentioned-actors">Mentioned actors</a>'
    ) in html
    # Legacy vocab gone.
    assert "Single voices" not in html


def test_actor_anchor_id_present_on_each_card():
    """Acceptance criterion: ``id="actor-NNN"`` is present on each card,
    preserving the jump targets that cluster cards and the bracket
    back-link to."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": [], "quotes": []},
            {"id": "actor-002", "name": "B", "role": "r", "type": "military",
             "source_ids": [], "quotes": []},
            {"id": "actor-042", "name": "C", "role": "r", "type": "academia",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert 'id="actor-001"' in html
    assert 'id="actor-002"' in html
    assert 'id="actor-042"' in html


def test_card_renders_no_quotes_no_position_lines():
    """Verification of the navigation-bridge end-state: the section
    must not carry verbatim or position text. Tier markers belong on
    cluster cards, not here."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "X",
                "role": "President",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [
                    {"source_id": "src-001",
                     "position": "Verbatim-bearing position.",
                     "verbatim": "literal quote text"},
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"],
                 "source_ids": ["src-001"], "stated": ["actor-001"]},
            ],
        },
    }
    html = build_actors_section(tp)
    assert "Verbatim-bearing position." not in html
    assert "literal quote text" not in html
    assert 'class="actor-verbatim"' not in html
    assert 'class="actor-position-line"' not in html
    # Tier markers (Stated/Reported/Mentioned) belong to cluster cards
    # — they must not appear inside the Actors-section.
    section_start = html.find('id="actors-section"')
    section_end = html.find('</section>', section_start)
    section = html[section_start:section_end]
    assert "Stated" not in section
    assert "Reported" not in section
    assert "Mentioned" not in section


def test_card_anonymous_marker_preserved():
    """Actors flagged ``is_anonymous`` keep their ``(anonymous)`` marker
    inline on the name — sourcing transparency, not biographical text."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Senior US officials", "role": "r",
             "type": "government", "is_anonymous": True,
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert 'class="actor-anonymous"' in html
    assert "(anonymous)" in html


def test_actor_with_unknown_type_renders_under_extra_group():
    """Actors with a `type` value outside the canonical enum still
    render — under an extra group at the end of the card grid (not in
    the tab bar). Data preservation over schema-strictness."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Known", "role": "r", "type": "government",
             "source_ids": ["src-001"], "quotes": []},
            {"id": "actor-002", "name": "Unknown", "role": "r", "type": "individual",
             "source_ids": ["src-002"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # The unknown-type group is rendered.
    assert 'data-actor-type="individual"' in html
    assert 'id="actor-002"' in html
    # No tab targets it.
    assert 'data-type-target="individual"' not in html
