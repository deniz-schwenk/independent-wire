"""Tests for Phase 2 of TASK-RESOLVE-ACTOR-ALIASES — every consumer
of the actor list reads from ``canonical_actors[]`` instead of
``final_actors[]``.

Covered consumers:

- ``PerspectiveStage`` — agent context carries ``canonical_actors``.
- ``enrich_perspective_clusters`` — cluster ``actor_ids[]`` validated
  against ``canonical_actors``; counts (``n_actors``) match the post-
  resolution membership.
- ``BiasLanguageStage`` — bias-card ``distinct_actor_count`` reads
  ``len(canonical_actors)``.
- ``WriterStage`` — agent context carries ``actors`` (canonical) and
  ``actor_aliases`` (alias mapping).
- Render Actors-Section — emits canonical entries only; aliased IDs
  do not appear.
- Render Sources-Section — per-source actor refs resolve source-side
  name variants to canonical IDs via the alias mapping.
- Non-mutation invariant: the resolver does not modify
  ``final_actors[]``.
- Resolver agent registration carries the verified Y-config
  (``temp=1.0``, ``reasoning="medium"``, ``max_tokens=66000``).
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from typing import Any

import pytest

from src.agent import AgentResult
from src.agent_stages import (
    BiasLanguageStage,
    PerspectiveStage,
    ResolveActorAliasesStage,
    WriterStage,
    _build_bias_card_for_agent_input,
)
from src.bus import EditorAssignment, RunBus, TopicBus, WriterArticle
from src.stages.topic_stages import enrich_perspective_clusters


# ---------------------------------------------------------------------------
# Fake Agent — minimal surface for wrapper tests
# ---------------------------------------------------------------------------


class FakeAgent:
    def __init__(self, *, structured: Any = None, name: str = "fake") -> None:
        self._structured = structured
        self.name = name
        self.calls: list[dict] = []

    async def run(
        self, message: str = "", context: dict | None = None, **kwargs: Any
    ) -> AgentResult:
        self.calls.append({"message": message, "context": context or {}})
        return AgentResult(
            content="",
            structured=self._structured,
            tool_calls=[],
        )


def _run(stage, *args, **kwargs):
    return asyncio.run(stage(*args, **kwargs))


def _ro(rb: RunBus | None = None):
    return (rb or RunBus()).as_readonly()


# ---------------------------------------------------------------------------
# 1. PerspectiveStage receives canonical_actors[] in agent context
# ---------------------------------------------------------------------------


def test_perspective_stage_passes_canonical_actors_to_agent():
    fake = FakeAgent(
        structured={"position_clusters": [], "missing_positions": []}
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.final_sources = [
        {"id": "src-001", "country": "US", "language": "en"},
    ]
    tb.final_actors = [
        {"id": "actor-001", "name": "Russia's Defense Ministry"},
        {"id": "actor-002", "name": "Russian Defense Ministry"},
    ]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "Russian Defense Ministry"},
    ]
    tb.actor_alias_mapping = [
        {"alias_id": "actor-002", "alias_name": "Russia's Defense Ministry",
         "canonical_id": "actor-001"},
    ]
    stage = PerspectiveStage(fake)
    _run(stage, tb, _ro())

    ctx = fake.calls[0]["context"]
    assert "canonical_actors" in ctx
    assert "final_actors" not in ctx, (
        "PerspectiveStage must read canonical_actors, not final_actors"
    )
    assert len(ctx["canonical_actors"]) == 1
    assert ctx["canonical_actors"][0]["name"] == "Russian Defense Ministry"


def test_perspective_stage_reads_tuple_lists_canonical_actors():
    from src.stage import get_stage_meta

    fake = FakeAgent(
        structured={"position_clusters": [], "missing_positions": []}
    )
    meta = get_stage_meta(PerspectiveStage(fake))
    assert "canonical_actors" in meta.reads
    assert "final_actors" not in meta.reads


# ---------------------------------------------------------------------------
# 2. enrich_perspective_clusters joins against canonical_actors[]
# ---------------------------------------------------------------------------


def test_enrich_clusters_validates_actor_ids_against_canonical_only():
    """An actor_id present in final_actors but NOT in canonical_actors
    (i.e. an aliased ID) must be dropped — the validator now joins
    against canonical_actors, not final_actors."""
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "X",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-002"],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    # final_actors carries both — the pre-resolution snapshot
    tb.final_actors = [
        {"id": "actor-001", "name": "Russian Defense Ministry"},
        {"id": "actor-002", "name": "Russia's Defense Ministry"},
    ]
    # canonical_actors carries only the canonical entry; actor-002 was
    # merged into actor-001 by the resolver
    tb.canonical_actors = [
        {"id": "actor-001", "name": "Russian Defense Ministry"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    cluster = tb_after.perspective_clusters[0]
    assert cluster["actor_ids"] == ["actor-001"]
    assert cluster["n_actors"] == 1


def test_enrich_clusters_n_actors_reflects_canonical_membership():
    tb = TopicBus()
    tb.perspective_clusters = [
        {
            "position_label": "X",
            "source_ids": ["src-001"],
            "actor_ids": ["actor-001", "actor-002", "actor-003"],
        },
    ]
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
        {"id": "actor-003", "name": "C"},
    ]
    tb_after = _run(enrich_perspective_clusters, tb, _ro())
    assert tb_after.perspective_clusters[0]["n_actors"] == 3


# ---------------------------------------------------------------------------
# 3. BiasLanguageStage distinct_actor_count reads canonical_actors
# ---------------------------------------------------------------------------


def test_bias_card_distinct_actor_count_reads_canonical_actors():
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.qa_corrected_article = WriterArticle(summary="s", body="b")
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
    ]
    # final_actors has 4 (pre-resolution: includes 3 alias variants)
    tb.final_actors = [
        {"id": "actor-001", "name": "Russian Defense Ministry"},
        {"id": "actor-002", "name": "Russia's Defense Ministry"},
        {"id": "actor-003", "name": "Russian Ministry of Defense"},
        {"id": "actor-004", "name": "Putin"},
    ]
    # canonical_actors collapses the 3 alias variants into 1
    tb.canonical_actors = [
        {"id": "actor-001", "name": "Russian Defense Ministry"},
        {"id": "actor-004", "name": "Putin"},
    ]
    bc = _build_bias_card_for_agent_input(tb)
    # distinct_actor_count must reflect the canonical (post-merge) count
    assert bc["perspectives"]["distinct_actor_count"] == 2


def test_bias_language_stage_reads_canonical_actors():
    fake = FakeAgent(
        structured={
            "language_bias": {"findings": []},
            "reader_note": "n",
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.qa_corrected_article = WriterArticle(headline="h", body="b", summary="s")
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
    ]
    tb.final_actors = [
        {"id": "actor-001", "name": "A"},
        {"id": "actor-002", "name": "B"},
    ]
    # Only one survives canonicalisation
    tb.canonical_actors = [{"id": "actor-001", "name": "A"}]
    stage = BiasLanguageStage(fake)
    _run(stage, tb, _ro())
    bias_card_ctx = fake.calls[0]["context"]["bias_card"]
    assert bias_card_ctx["perspectives"]["distinct_actor_count"] == 1


# ---------------------------------------------------------------------------
# 4. WriterStage receives canonical_actors[] and actor_alias_mapping[]
# ---------------------------------------------------------------------------


def test_writer_stage_passes_canonical_actors_and_alias_mapping(tmp_path: Path):
    fake = FakeAgent(
        structured={
            "headline": "H", "subheadline": "S", "body": "B",
            "summary": "Sm", "sources": [],
        }
    )
    tb = TopicBus(editor_selected_topic=EditorAssignment(title="t"))
    tb.final_sources = [{"id": "src-001", "country": "X", "language": "en"}]
    tb.canonical_actors = [
        {"id": "actor-001", "name": "Russian Defense Ministry"},
    ]
    tb.actor_alias_mapping = [
        {"alias_id": "actor-002", "alias_name": "Russia's Defense Ministry",
         "canonical_id": "actor-001"},
    ]
    tb.perspective_clusters_synced = [
        {"id": "pc-001", "actor_ids": ["actor-001"], "source_ids": ["src-001"]},
    ]
    # Use a non-existent FOLLOWUP path to avoid file-system coupling.
    stage = WriterStage(fake, followup_path=tmp_path / "no-such-file.md")
    _run(stage, tb, _ro())

    ctx = fake.calls[0]["context"]
    assert "actors" in ctx
    assert "actor_aliases" in ctx
    assert ctx["actors"] == [
        {"id": "actor-001", "name": "Russian Defense Ministry"},
    ]
    assert ctx["actor_aliases"] == [
        {"alias_id": "actor-002", "alias_name": "Russia's Defense Ministry",
         "canonical_id": "actor-001"},
    ]


def test_writer_stage_reads_tuple_lists_canonical_actors_and_alias_mapping():
    from src.stage import get_stage_meta

    fake = FakeAgent()
    meta = get_stage_meta(WriterStage(fake))
    assert "canonical_actors" in meta.reads
    assert "actor_alias_mapping" in meta.reads


# ---------------------------------------------------------------------------
# 5. Render Actors-Section emits canonical actors only
# ---------------------------------------------------------------------------


def _load_render_module():
    """Import scripts/render.py as a module (it's not on the package
    path because scripts/ is not a Python package)."""
    spec = importlib.util.spec_from_file_location(
        "scripts_render",
        Path(__file__).resolve().parents[1] / "scripts" / "render.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_actors_section_renders_canonical_only_via_actors_key():
    """Phase 2: ``tp["actors"]`` carries canonical_actors content. The
    Actors-Section builder reads ``tp["actors"]`` and therefore renders
    canonical entries only."""
    render = _load_render_module()
    tp = {
        "actors": [
            {
                "id": "actor-001",
                "name": "Russian Defense Ministry",
                "role": "Government Ministry",
                "type": "government",
                "source_ids": ["src-001"],
                "quotes": [
                    {"source_id": "src-001",
                     "position": "denies escalation",
                     "verbatim": None},
                ],
                "is_anonymous": False,
            },
        ],
        "perspectives": {
            "position_clusters": [
                {"id": "pc-001", "actor_ids": ["actor-001"],
                 "source_ids": ["src-001"]},
            ],
        },
    }
    html = render.build_actors_section(tp)
    assert 'id="actor-001"' in html
    assert "Russian Defense Ministry" in html
    # Aliased name from final_actors must NOT appear (it is not in
    # tp["actors"]).
    assert "Russia&rsquo;s Defense Ministry" not in html
    assert "Russia's Defense Ministry" not in html


def test_actors_section_emits_anonymous_marker():
    """Actors with is_anonymous=True render with the ``(anonymous)``
    italic suffix; named individuals/specific institutions do not."""
    render = _load_render_module()
    tp = {
        "actors": [
            {"id": "actor-001", "name": "Senior US officials",
             "role": "Unnamed officials", "type": "government",
             "source_ids": ["src-001"], "quotes": [],
             "is_anonymous": True},
            {"id": "actor-002", "name": "Donald Trump",
             "role": "US President", "type": "government",
             "source_ids": ["src-002"], "quotes": [],
             "is_anonymous": False},
        ],
        "perspectives": {"position_clusters": []},
    }
    html = render.build_actors_section(tp)
    # Anonymous actor carries the marker
    assert 'class="actor-anonymous"' in html
    assert "(anonymous)" in html
    # The marker must sit inside the anonymous actor's <li>, not the
    # named one. A coarse check: the markup appears once in total
    # (one anonymous actor).
    assert html.count("(anonymous)") == 1


# ---------------------------------------------------------------------------
# 6. Render Sources-Section actor-refs link to canonical anchor IDs
# ---------------------------------------------------------------------------


def test_sources_section_resolves_alias_to_canonical_anchor():
    """When a source's actors_quoted carries the alias name (e.g.
    ``Russia's Defense Ministry``), the rendered link text shows the
    canonical name (``Russian Defense Ministry``) and the anchor target
    is the canonical ``actor-NNN`` ID."""
    render = _load_render_module()
    tp = {
        "sources": [
            {
                "id": "src-001",
                "outlet": "Reuters",
                "url": "https://example.com/reuters",
                "title": "Headline",
                "country": "US",
                "language": "en",
                "summary": "...",
                "actors_quoted": [
                    {"name": "Russia's Defense Ministry"},
                ],
            },
        ],
        "actors": [
            {"id": "actor-001", "name": "Russian Defense Ministry",
             "role": "Government Ministry", "type": "government",
             "source_ids": ["src-001"], "quotes": [],
             "is_anonymous": False},
        ],
        "actor_alias_mapping": [
            {"alias_id": "actor-002",
             "alias_name": "Russia's Defense Ministry",
             "canonical_id": "actor-001"},
        ],
    }
    html = render.build_sources_section(tp)
    # Anchor target is the canonical ID
    assert 'href="#actor-001"' in html
    # Link text is the canonical name (escaped)
    assert "Russian Defense Ministry" in html


def test_sources_section_direct_canonical_name_match_still_works():
    """If a source quotes the canonical name directly (no alias
    resolution needed), the link still resolves to the canonical
    anchor."""
    render = _load_render_module()
    tp = {
        "sources": [
            {
                "id": "src-001",
                "outlet": "Reuters",
                "url": "https://example.com/reuters",
                "title": "Headline",
                "country": "US",
                "language": "en",
                "summary": "...",
                "actors_quoted": [{"name": "Donald Trump"}],
            },
        ],
        "actors": [
            {"id": "actor-001", "name": "Donald Trump",
             "role": "US President", "type": "government",
             "source_ids": ["src-001"], "quotes": [],
             "is_anonymous": False},
        ],
        "actor_alias_mapping": [],
    }
    html = render.build_sources_section(tp)
    assert 'href="#actor-001"' in html
    assert "Donald Trump" in html


# ---------------------------------------------------------------------------
# 7. Non-mutation invariant: resolver does not modify final_actors[]
# ---------------------------------------------------------------------------


def test_resolver_does_not_mutate_final_actors():
    """``ResolveActorAliasesStage`` is non-destructive on
    ``final_actors[]``. The pre-resolution snapshot survives the
    stage byte-identical so it remains usable as the audit artifact."""
    fake = FakeAgent(
        structured={
            "aliases": [
                {"alias_id": "actor-002", "canonical_id": "actor-001"},
            ],
            "anonymous_flags": [],
        }
    )
    tb = TopicBus()
    tb.final_actors = [
        {"id": "actor-001", "name": "Russian Defense Ministry",
         "role": "Government Ministry", "type": "government",
         "source_ids": ["src-001"],
         "quotes": [{"source_id": "src-001", "position": "p", "verbatim": None}]},
        {"id": "actor-002", "name": "Russia's Defense Ministry",
         "role": "Government Ministry", "type": "government",
         "source_ids": ["src-002"],
         "quotes": [{"source_id": "src-002", "position": "p", "verbatim": None}]},
    ]
    pre = [dict(a) for a in tb.final_actors]
    pre = [
        {**a, "source_ids": list(a["source_ids"]),
         "quotes": [dict(q) for q in a["quotes"]]}
        for a in tb.final_actors
    ]

    stage = ResolveActorAliasesStage(fake)
    tb_after = _run(stage, tb, _ro())

    assert tb_after.final_actors == pre, (
        "final_actors[] must be byte-identical to the pre-resolution "
        "snapshot — the resolver is non-destructive."
    )
    # The merge happened on canonical_actors, not on final_actors.
    assert len(tb_after.canonical_actors) == 1
    assert len(tb_after.actor_alias_mapping) == 1


# ---------------------------------------------------------------------------
# 8. Resolver Y-config: scripts/run.py registration
# ---------------------------------------------------------------------------


def test_resolver_agent_registration_carries_y_config():
    """Production registration ships the verified diagnostic-V2 Y-config:
    ``temperature=1.0``, ``reasoning="medium"``, ``max_tokens=66000``.
    This regression-guards against accidental reverts to the Iter-1
    baseline (``temperature=0.2`` + ``reasoning="none"``)."""
    run_py = (
        Path(__file__).resolve().parents[1] / "scripts" / "run.py"
    ).read_text(encoding="utf-8")
    # Locate the resolve_actor_aliases agent registration block.
    needle = '"resolve_actor_aliases": Agent('
    start = run_py.find(needle)
    assert start != -1, "resolve_actor_aliases agent registration not found"
    # Slice from the resolver registration to the next agent registration
    # so we don't catch values from neighboring blocks.
    after = run_py.find('"perspective": Agent(', start)
    assert after > start
    block = run_py[start:after]
    assert "temperature=1.0" in block
    assert 'reasoning="medium"' in block
    assert "max_tokens=66000" in block
    # Defensive: the deprecated Iter-1 baseline values must NOT be in
    # this block.
    assert "temperature=0.2" not in block
    assert 'reasoning="none"' not in block
