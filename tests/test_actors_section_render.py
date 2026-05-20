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
    """No actors → section emits the header (with "0 ACTORS" count) and
    the sub-line, no tab bar, no card grid."""
    tp = {"actors": [], "perspectives": {"position_clusters": []}}
    html = build_actors_section(tp)
    assert 'id="actors-section"' in html
    assert "Actors</h2>" in html
    assert "0 ACTORS" in html
    assert "0 actors quoted across this topic" in html
    assert 'class="actors-tabs"' not in html
    assert 'class="actor-card-grid"' not in html


def test_header_renders_actor_count_and_sub_line_no_type_count():
    """Acceptance criterion: header carries actor count only (no type
    count); sub-line "N actors quoted across this topic. Jump from any
    name above to find every cluster and source the actor figures in."
    """
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
    # Header count.
    assert "2 ACTORS" in html
    # Sub-line in full.
    assert (
        "2 actors quoted across this topic. Jump from any name above "
        "to find every cluster and source the actor figures in."
    ) in html
    # Type count must NOT appear in the header. The screenshot showed
    # "33 ACTORS · 6 TYPES" but the brief explicitly overrode that —
    # so the header must contain neither "TYPES" nor a count-X-TYPES
    # phrase.
    assert "TYPES" not in html
    assert "2 types" not in html.lower()


# ---------------------------------------------------------------------------
# Tab bar
# ---------------------------------------------------------------------------


def test_tab_bar_renders_all_first_then_enum_order_with_counts():
    """Acceptance criterion: tab bar carries ALL N then one tab per
    enum type in declared order, each with its count.

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
    # ALL tab first.
    idx_all = html.find('data-type-target="all"')
    idx_gov = html.find('data-type-target="government"')
    idx_leg = html.find('data-type-target="legislature"')
    idx_jud = html.find('data-type-target="judiciary"')
    idx_mil = html.find('data-type-target="military"')
    idx_ind = html.find('data-type-target="industry"')
    idx_cs = html.find('data-type-target="civil_society"')
    idx_aca = html.find('data-type-target="academia"')
    idx_med = html.find('data-type-target="media"')
    idx_intl = html.find('data-type-target="international_org"')
    idx_aff = html.find('data-type-target="affected_community"')
    assert idx_all >= 0
    # Enum order — strictly ascending positions in the HTML.
    order = [idx_all, idx_gov, idx_leg, idx_jud, idx_mil, idx_ind,
             idx_cs, idx_aca, idx_med, idx_intl, idx_aff]
    for prev, cur in zip(order, order[1:]):
        assert 0 <= prev < cur, f"tab order violated: {order}"
    # Per-tab counts on the populated types.
    assert "ALL" in html
    assert ">4</span>" in html or ">4 </span>" in html  # ALL = 4
    # GOVERNMENT 2
    block = html[idx_gov:idx_gov + 400]
    assert "GOVERNMENT" in block
    assert ">2</span>" in block
    # MILITARY 1
    block = html[idx_mil:idx_mil + 400]
    assert "MILITARY" in block
    assert ">1</span>" in block
    # CIVIL SOCIETY 1
    block = html[idx_cs:idx_cs + 400]
    assert "CIVIL SOCIETY" in block
    assert ">1</span>" in block


def test_tab_with_zero_count_rendered_disabled_no_click():
    """Acceptance criterion: a tab whose count is 0 is rendered in
    disabled style and carries the HTML `disabled` attribute (so the
    JS handler skips it). It has no `href`."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # The MILITARY tab has count 0 in this fixture. It must carry the
    # disabled attribute and the actor-tab--disabled CSS class.
    idx = html.find('data-type-target="military"')
    assert idx >= 0
    block = html[idx - 200:idx + 200]
    assert "disabled" in block
    assert "actor-tab--disabled" in block
    # Tab is a <button>, not an <a> — no href.
    assert "href=" not in block


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


def test_card_grid_group_header_carries_actor_and_source_ref_counts():
    """Each group's header shows ``N actors · M source refs``. M is the
    sum of per-actor source-ref counts (deduped per actor)."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "government",
             "source_ids": ["src-001", "src-002"], "quotes": []},
            {"id": "actor-002", "name": "B", "role": "r", "type": "government",
             "source_ids": ["src-001", "src-003", "src-003"], "quotes": []},  # dup
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # Group header carries "2 actors" and "4 source refs"
    # (actor-001: 2 unique; actor-002: 2 unique after dedup; sum 4).
    idx = html.find('data-actor-type="government"')
    block = html[idx:idx + 600]
    assert "2 actors" in block
    assert "4 source refs" in block


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


def test_card_renders_cluster_box_for_each_membership_with_pc_anchor():
    """Acceptance criterion: cluster-ref boxes use the existing
    ``Cluster N`` label and anchor at ``#pc-NNN``."""
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
    assert '<a class="actor-card-cluster-box" href="#pc-001">Cluster 1</a>' in html
    assert '<a class="actor-card-cluster-box" href="#pc-003">Cluster 2</a>' in html


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


def test_bracket_actor_card_renders_single_voices_box_to_single_voices():
    """Acceptance criterion: an actor in the single-voices bracket sees
    a cluster-ref box reading ``Single voices`` linking to
    ``#single-voices``. The box carries the bracket-variant CSS class
    (visually distinct from regular Cluster-N boxes)."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Orphan", "role": "r", "type": "government",
             "source_ids": ["src-001", "src-002"], "quotes": []},
        ],
        "perspectives": {
            "position_clusters": [],
            "single_voices": {
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
        ' href="#single-voices">Single voices</a>'
    ) in html


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
