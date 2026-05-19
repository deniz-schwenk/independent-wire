"""Tests for ``build_actors_section`` in ``scripts/render.py``.

Covers TASK-RENDER-RESTRUCTURE-V2 Commit 2 contract:

- Section ID, header, meta line, show-all button, ordered list.
- Each actor renders id, name, role, type, data-clusters attribute.
- Multi-cluster actors: one position-line per cluster.
- Verbatim quote presence/absence handled correctly.
- Empty final_actors → "0 actors quoted" message and no JS.
- Cluster anchors (#cluster-pc-NNN style — wait, actually #pc-NNN
  since cluster cards are anchored by their canonical id).
- Source-id refs render as anchor links.
- Inline JS shim is emitted with the actor list.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow importing scripts.render from the test directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.render import build_actors_section


def test_empty_actors_renders_meta_only():
    """No actors → section emits the heading and a '0 actors' message,
    no <ol>, no JS. Same shape as other empty sections."""
    tp = {"actors": [], "perspectives": {"position_clusters": []}}
    html = build_actors_section(tp)
    assert 'id="actors-section"' in html
    assert "<h2>Actors</h2>" in html
    assert "0 actors quoted" in html
    assert "<ol" not in html
    assert "<script" not in html


def test_actor_renders_id_name_role_type_and_data_clusters():
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Donald Trump",
                "role": "United States President",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [
                    {
                        "source_id": "src-001",
                        "position": "Threatens action",
                        "verbatim": "We will respond.",
                    }
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-005", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
            ],
        },
    }
    html = build_actors_section(tp)
    assert 'id="actor-001"' in html
    assert "Donald Trump" in html
    assert "United States President" in html
    assert "government" in html
    # data-clusters carries the full cluster id with cluster- prefix
    assert 'data-clusters="cluster-pc-005"' in html


def test_multi_cluster_actor_renders_one_line_per_cluster():
    """An actor in two clusters gets two position-lines, each citing
    the cluster anchor and (when available) the relevant source quote."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Macron",
                "role": "President",
                "type": "government",
                "source_ids": ["src-001", "src-024"],
                "quotes": [
                    {"source_id": "src-001", "position": "calls for restraint",
                     "verbatim": None},
                    {"source_id": "src-024", "position": "refuses offensive role",
                     "verbatim": "no offensive operations"},
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
                {"id": "pc-009", "actor_ids": ["actor-001"], "source_ids": ["src-024"]},
            ],
        },
    }
    html = build_actors_section(tp)
    # Two distinct cluster anchors emitted in this actor's block
    assert 'href="#pc-001"' in html
    assert 'href="#pc-009"' in html
    # Both positions surface
    assert "calls for restraint" in html
    assert "refuses offensive role" in html
    # Verbatim from src-024 wraps in <em class="actor-verbatim">
    assert 'class="actor-verbatim"' in html
    assert "no offensive operations" in html
    # Source anchor for the verbatim case
    assert 'href="#src-024"' in html
    # data-clusters lists both
    assert 'data-clusters="cluster-pc-001 cluster-pc-009"' in html


def test_verbatim_omitted_when_null():
    """Actor with paraphrased-only quotes — no <em class="actor-verbatim">
    tag in their position-line."""
    tp = {
        "actors": [
            {
                "id": "actor-002",
                "name": "Spokesperson",
                "role": "Press Sec",
                "type": "government",
                "source_ids": ["src-002"],
                "quotes": [
                    {"source_id": "src-002", "position": "states position",
                     "verbatim": None},
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-002", "actor_ids": ["actor-002"], "source_ids": ["src-002"]},
            ],
        },
    }
    html = build_actors_section(tp)
    assert "states position" in html
    assert 'class="actor-verbatim"' not in html


def test_actor_not_in_any_cluster_renders_fallback_line():
    """An actor whose ID does not appear in any cluster's actor_ids
    still renders, but the position-line falls back to a muted note."""
    tp = {
        "actors": [
            {"id": "actor-099", "name": "Orphan", "role": "r", "type": "t",
             "source_ids": ["src-099"], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    assert "Orphan" in html
    assert "actor-no-cluster" in html
    # data-clusters should be empty (no cluster memberships)
    assert 'data-clusters=""' in html


def test_inline_js_shim_emitted_with_non_empty_list():
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "t",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # JS shim presence — substring is enough; verify all three handlers
    assert "<script>" in html
    assert "hashchange" in html
    assert "actors-show-all" in html
    assert "history.pushState" in html


def test_per_actor_quote_dedup_single_quote_two_clusters_one_source():
    """One quote, both clusters share its source: first cluster emits
    the quote text; second cluster falls through to anchor-only (no
    duplicate quote text in the rendered HTML)."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Araghchi",
                "role": "Foreign Minister",
                "type": "government",
                "source_ids": ["src-007"],
                "quotes": [
                    {
                        "source_id": "src-007",
                        "position": "Tehran received messages from regional capitals",
                        "verbatim": None,
                    },
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-002", "actor_ids": ["actor-001"], "source_ids": ["src-007"]},
                {"id": "pc-003", "actor_ids": ["actor-001"], "source_ids": ["src-007"]},
            ],
        },
    }
    html = build_actors_section(tp)
    # The quote position appears exactly once across the actor's two
    # cluster-lines.
    assert html.count(
        "Tehran received messages from regional capitals"
    ) == 1
    # Both cluster anchors are still rendered (the dedup affects quote
    # text, not the cluster membership line).
    assert 'href="#pc-002"' in html
    assert 'href="#pc-003"' in html
    # The second cluster's anchor-only line carries no colon-separator
    # (which only appears when a quote is attached). Counted across the
    # actor block: one quote-bearing line ("anchor: position …") + one
    # anchor-only line.
    actor_block_start = html.find('id="actor-001"')
    actor_block_end = html.find("</li>", actor_block_start)
    block = html[actor_block_start:actor_block_end]
    quote_bearing_lines = block.count("</a>:")
    assert quote_bearing_lines == 1


def test_per_actor_quote_dedup_two_quotes_two_sources_happy_path():
    """Two quotes from two distinct sources, two clusters where each
    cluster's source_ids contains one of the two sources. Dedup must
    not break the happy path — each cluster gets its own
    source-matching quote."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Macron",
                "role": "President",
                "type": "government",
                "source_ids": ["src-001", "src-024"],
                "quotes": [
                    {
                        "source_id": "src-001",
                        "position": "calls for restraint",
                        "verbatim": None,
                    },
                    {
                        "source_id": "src-024",
                        "position": "refuses offensive role",
                        "verbatim": None,
                    },
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
                {"id": "pc-009", "actor_ids": ["actor-001"], "source_ids": ["src-024"]},
            ],
        },
    }
    html = build_actors_section(tp)
    assert "calls for restraint" in html
    assert "refuses offensive role" in html
    # Each appears exactly once — happy path is unchanged.
    assert html.count("calls for restraint") == 1
    assert html.count("refuses offensive role") == 1


def test_per_actor_quote_dedup_two_quotes_same_source_two_clusters():
    """Two quotes from the same source, both clusters reference that
    source. The first cluster picks the first quote; the second cluster
    picks the second quote (next-best match within the source overlap).
    Neither falls through to anchor-only — there is enough material to
    populate both lines."""
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Araghchi",
                "role": "Foreign Minister",
                "type": "government",
                "source_ids": ["src-007"],
                "quotes": [
                    {
                        "source_id": "src-007",
                        "position": "first position from src-007",
                        "verbatim": None,
                    },
                    {
                        "source_id": "src-007",
                        "position": "second position from src-007",
                        "verbatim": None,
                    },
                ],
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-002", "actor_ids": ["actor-001"], "source_ids": ["src-007"]},
                {"id": "pc-003", "actor_ids": ["actor-001"], "source_ids": ["src-007"]},
            ],
        },
    }
    html = build_actors_section(tp)
    assert "first position from src-007" in html
    assert "second position from src-007" in html
    # Each appears exactly once.
    assert html.count("first position from src-007") == 1
    assert html.count("second position from src-007") == 1
    # The first quote attaches to pc-002 (first cluster); the second
    # attaches to pc-003 (second cluster) — order of first appearance
    # in the rendered HTML.
    first_idx = html.find("first position from src-007")
    second_idx = html.find("second position from src-007")
    pc002_idx = html.find('href="#pc-002"')
    pc003_idx = html.find('href="#pc-003"')
    assert pc002_idx < first_idx < pc003_idx < second_idx


def test_show_all_button_starts_hidden_when_no_filter_active():
    tp = {
        "actors": [
            {"id": "actor-001", "name": "A", "role": "r", "type": "t",
             "source_ids": [], "quotes": []},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = build_actors_section(tp)
    # Button rendered with hidden attribute; JS un-hides it on filter
    assert 'id="actors-show-all"' in html
    assert "hidden>" in html or "hidden " in html
