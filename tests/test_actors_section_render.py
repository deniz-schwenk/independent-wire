"""Tests for ``build_actors_section`` in ``scripts/render.py``.

After the 2026-05-20 navigation-bridge refactor, the section is a
four-column table — Actor / Role · Type / Cluster refs / Source refs.
Quotes and position summaries live in the Sources-section third level
now (and the cluster cards carry position labels), so this section is
strictly navigation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.render import build_actors_section


def test_empty_actors_renders_meta_only():
    """No actors → section emits the heading and a '0 actors' message,
    no <table>."""
    tp = {"actors": [], "perspectives": {"position_clusters": []}}
    html = build_actors_section(tp)
    assert 'id="actors-section"' in html
    assert "<h2>Actors</h2>" in html
    assert "0 actors quoted" in html
    assert "<table" not in html


def test_actors_section_renders_four_column_table():
    """Acceptance criterion: section is a four-column table with the
    expected headings."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Donald Trump",
                "role": "United States President",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"],
                 "source_ids": ["src-001"]},
            ],
        },
    }
    html = build_actors_section(tp)
    assert 'class="actors-table"' in html
    # Four <th> headings, in order.
    for heading in ("Actor", "Role", "Cluster refs", "Source refs"):
        assert f"<th>{heading}" in html or heading in html
    # Each row has four <td> cells.
    row_start = html.find('class="actor-row"')
    row_end = html.find("</tr>", row_start)
    row = html[row_start:row_end]
    assert row.count("<td") == 4


def test_actors_section_one_row_per_actor():
    """Acceptance criterion: one row per actor in actors[]."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "t",
             "source_ids": [], "quotes": []},
            {"id": "actor-002", "name": "B", "role": "r", "type": "t",
             "source_ids": [], "quotes": []},
            {"id": "actor-003", "name": "C", "role": "r", "type": "t",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert html.count('class="actor-row"') == 3
    # Each actor's row anchor matches its id.
    assert 'id="actor-001"' in html
    assert 'id="actor-002"' in html
    assert 'id="actor-003"' in html


def test_actors_section_row_anchor_is_actor_id():
    """Acceptance criterion: row anchor is id="actor-NNN" so jumps from
    cluster cards (href="#actor-NNN") land correctly."""
    tp = {
        "actors": [
            {"id": "actor-042", "name": "X", "role": "r", "type": "t",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert 'id="actor-042"' in html


def test_actors_section_role_type_concatenated_with_middle_dot():
    """Role · Type column renders as ``{role} · {type}`` (HTML middle dot
    entity). When one side is empty, the other stands alone."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Both",
             "role": "President", "type": "government",
             "source_ids": [], "quotes": []},
            {"id": "actor-002", "name": "RoleOnly",
             "role": "Spokesperson", "type": "",
             "source_ids": [], "quotes": []},
            {"id": "actor-003", "name": "TypeOnly",
             "role": "", "type": "ngo",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # Both: "President · government"
    assert "President &middot; government" in html
    # Role-only: just "Spokesperson", no trailing middle-dot
    assert "Spokesperson" in html
    assert "Spokesperson &middot;" not in html
    # Type-only: just "ngo"
    assert ">ngo<" in html


def test_actors_section_cluster_refs_in_emission_order():
    """Acceptance criterion: cluster refs render in cluster-emission
    order (the order the agent wrote the clusters), regardless of the
    order the actor appears in each cluster's actor_ids[].
    """
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Trump", "role": "r", "type": "t",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {
            "position_clusters": [
                # actor-001 appears in pc-003 first emission slot, then
                # pc-001, then pc-005. Render order must follow the
                # cluster-emission order — pc-003, pc-001, pc-005.
                {"id": "pc-003", "actor_ids": ["actor-001"], "source_ids": []},
                {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": []},
                {"id": "pc-005", "actor_ids": ["actor-001"], "source_ids": []},
            ],
        },
    }
    html = build_actors_section(tp)
    # Cluster anchors render with 1-based emission index in the link text.
    pc003_idx = html.find('href="#pc-003">Cluster 1</a>')
    pc001_idx = html.find('href="#pc-001">Cluster 2</a>')
    pc005_idx = html.find('href="#pc-005">Cluster 3</a>')
    assert 0 <= pc003_idx < pc001_idx < pc005_idx


def test_actors_section_source_refs_in_first_appearance_order():
    """Acceptance criterion: source refs in first-appearance order."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Macron",
                "role": "r",
                "type": "t",
                "source_ids": [
                    "src-007", "src-001", "src-024", "src-007",  # dup
                ],
                "quotes": [],
            },
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    src007_idx = html.find('href="#src-007">src-007</a>')
    src001_idx = html.find('href="#src-001">src-001</a>')
    src024_idx = html.find('href="#src-024">src-024</a>')
    # First-appearance order: src-007, src-001, src-024
    assert 0 <= src007_idx < src001_idx < src024_idx
    # Duplicate src-007 collapses to a single anchor.
    assert html.count('href="#src-007">src-007</a>') == 1


def test_actors_section_zero_clusters_renders_empty_cluster_cell():
    """Acceptance criterion: row for an actor with zero cluster
    memberships renders with an empty Cluster-refs cell — no label,
    no muted text, just an empty <td>."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Orphan", "role": "r", "type": "t",
             "source_ids": ["src-001"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # Cluster-refs cell is empty for this actor.
    assert '<td class="actor-cluster-refs"></td>' in html


def test_actors_section_no_quotes_no_position_lines():
    """Verification of the navigation-bridge end-state: the section
    must not carry quote text, verbatim italics, or position-line
    markup."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Trump",
                "role": "President",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [
                    {"source_id": "src-001",
                     "position": "Stated something newsworthy.",
                     "verbatim": "Very verbatim quote here."},
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"],
                 "source_ids": ["src-001"]},
            ],
        },
    }
    html = build_actors_section(tp)
    assert "Stated something newsworthy." not in html
    assert "Very verbatim quote here." not in html
    assert 'class="actor-verbatim"' not in html
    assert 'class="actor-position-line"' not in html


def test_actors_section_anonymous_marker_preserved():
    """Actors flagged ``is_anonymous`` keep their ``(anonymous)`` marker
    in the Actor cell — sourcing transparency, not biographical text."""
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Senior US officials", "role": "r",
             "type": "government", "is_anonymous": True,
             "source_ids": [], "quotes": []},
            {"id": "actor-002", "name": "Donald Trump", "role": "r",
             "type": "government", "is_anonymous": False,
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert 'class="actor-anonymous"' in html
    assert html.count("(anonymous)") == 1
