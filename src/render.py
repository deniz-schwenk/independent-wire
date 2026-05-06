"""V2 rendering layer — visibility-driven selection from RunBus and TopicBus.

Five render functions plus a generic `select_by_visibility` helper that walks
`json_schema_extra["visibility"]` per slot. Render functions are pure — they
return dicts and do no disk I/O. The runner (TASK-V2-10) writes the output.

Authoritative references:
- ARCH-V2-BUS-SCHEMA.md §3.6 (render is selection), §3.7 (visibility metadata),
  §4B.12 (Bias Card multi-slot derived view), §6 (render functions).
- src/models.py:TopicPackage.to_dict() (V1 V1 structural target for
  render_tp_public).
- ARCH §9 / Vision §10 — visualizations are a future workstream and the
  field is omitted from V2 outputs.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel

from src.bus import (
    EditorAssignment,
    RunBus,
    RunBusReadOnly,
    SourceBalance,
    TopicBus,
    TransparencyCard,
    WriterArticle,
)

logger = logging.getLogger(__name__)

VisibilityTag = Literal["tp", "mcp", "rss", "internal"]

RSS_BASE_URL = "https://independentwire.org/"


# ---------------------------------------------------------------------------
# Generic visibility filter
# ---------------------------------------------------------------------------


def select_by_visibility(
    bus: BaseModel, target: VisibilityTag
) -> dict[str, Any]:
    """Return `{slot_name: value}` for every field on `bus` whose schema
    metadata declares `target` in its visibility list.

    Sub-model values are dumped via `model_dump()` so the result is plain
    JSON-compatible. Fields without `json_schema_extra` are skipped with
    a warning — every Bus slot in V2 uses `Slot()`, so the absence is a
    schema-drift signal worth surfacing.
    """
    out: dict[str, Any] = {}
    for name, field in type(bus).model_fields.items():
        extra = field.json_schema_extra
        if not isinstance(extra, dict):
            logger.warning(
                "select_by_visibility: %s.%s has no json_schema_extra; skipping",
                type(bus).__name__,
                name,
            )
            continue
        viz = extra.get("visibility", [])
        if isinstance(viz, str):
            tags = [viz]
        else:
            tags = list(viz)
        if target not in tags:
            continue
        value = getattr(bus, name)
        if isinstance(value, BaseModel):
            out[name] = value.model_dump()
        else:
            out[name] = value
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _follow_up_block(
    assignment: EditorAssignment, run_bus: RunBus | RunBusReadOnly
) -> dict | None:
    """Construct the metadata.follow_up block from the editor assignment.

    Looks up `previous_headline` and `previous_date` from
    `run_bus.previous_coverage` (populated by the `init_run` stage by
    scanning prior `tp-*.json` files). Returns
    `{previous_tp_id, reason, previous_headline, previous_date}` when
    `follow_up_to` is set, else `None`. Missing fields surface as empty
    strings — the renderer hides the DIV when `previous_headline` is empty.
    """
    if not assignment.follow_up_to:
        return None
    previous_headline = ""
    previous_date = ""
    for entry in run_bus.previous_coverage or []:
        if isinstance(entry, dict) and entry.get("tp_id") == assignment.follow_up_to:
            previous_headline = entry.get("headline", "") or ""
            previous_date = entry.get("date", "") or ""
            break
    return {
        "previous_tp_id": assignment.follow_up_to,
        "reason": assignment.follow_up_reason or "",
        "previous_headline": previous_headline,
        "previous_date": previous_date,
    }


def _runbus_for_render(run_bus: RunBus | RunBusReadOnly) -> RunBusReadOnly | RunBus:
    """Render functions accept either RunBus or RunBusReadOnly. Return the
    input unchanged — pure read access works on both."""
    return run_bus


# ---------------------------------------------------------------------------
# render_tp_public
# ---------------------------------------------------------------------------


def render_tp_public(
    topic_bus: TopicBus, run_bus: RunBus | RunBusReadOnly
) -> dict:
    """Default on-disk Topic Package render. Output structure is V1-compatible
    against `src/models.py:TopicPackage.to_dict()` modulo three documented
    reshapes (per task §3.2):

    - `perspectives` is a dict `{position_clusters, missing_positions}`,
      not V1's flat list.
    - `metadata.follow_up` is `{previous_tp_id, reason}` or `None` — no
      previous-headline lookup (anti-pattern in render).
    - `visualizations` is omitted entirely (no V2 slot; future workstream).

    `article` always reads `qa_corrected_article` — the mirror_qa_corrected
    stage guarantees the slot is fully populated regardless of QA outcome
    or pipeline variant.

    Top-level keys are ordered along the pipeline flow (Curator/Researcher
    sources → researcher gaps → perspective clusters → writer/QA article →
    QA divergences → bias-detector reflection → transparency trail) so a
    reader following the JSON top-to-bottom traces the agent sequence.
    """
    rb = _runbus_for_render(run_bus)
    assignment = topic_bus.editor_selected_topic

    metadata = {
        "title": assignment.title,
        "date": rb.run_date,
        "status": "review",
        "topic_slug": assignment.topic_slug,
        "priority": assignment.priority,
        "follow_up": _follow_up_block(assignment, rb),
        "selection_reason": topic_bus.transparency_card.selection_reason,
    }

    output = {
        "id": assignment.id,
        "version": "1.0",
        "status": "review",
        "metadata": metadata,
        "sources": list(topic_bus.final_sources),
        "gaps": list(topic_bus.coverage_gaps_validated),
        "perspectives": {
            "position_clusters": list(topic_bus.perspective_clusters_synced),
            "missing_positions": list(topic_bus.perspective_missing_positions),
        },
        "article": topic_bus.qa_corrected_article.model_dump(),
        "divergences": list(topic_bus.qa_divergences),
        "bias_analysis": compose_bias_card(topic_bus),
        "transparency": topic_bus.transparency_card.model_dump(),
    }

    _coverage_check(topic_bus, output)
    return output


# Slot names whose `tp` visibility is satisfied by reshaped output keys
# (the slot itself is not directly named in the output, but its content is).
_TP_RESHAPED_SLOTS: dict[str, str] = {
    # slot name → output key that carries its content (reshaped)
    "perspective_clusters_synced": "perspectives.position_clusters",
    "perspective_missing_positions": "perspectives.missing_positions",
    "qa_corrected_article": "article",
    "qa_divergences": "divergences",
    "coverage_gaps_validated": "gaps",
    "final_sources": "sources",
    "transparency_card": "transparency",
    # Bias-card-derived slots (composed via compose_bias_card)
    "bias_language_findings": "bias_analysis.language",
    "bias_reader_note": "bias_analysis.reader_note",
    "source_balance": "bias_analysis.source / bias_analysis.geographical",
    "qa_problems_found": "bias_analysis.selection.qa_problems_found",
    "qa_corrections": "bias_analysis.selection (or mcp top-level)",
}


def _coverage_check(topic_bus: TopicBus, output: dict) -> None:
    """Sanity check: every `tp`-visible TopicBus slot is represented in the
    rendered output, either directly or via a reshape entry. Drift surfaces
    as a single warning listing the missing slot names. Catches forgotten
    render mappings when the schema grows."""
    tp_visible = select_by_visibility(topic_bus, "tp")
    missing: list[str] = []
    for slot_name in tp_visible:
        if slot_name in _TP_RESHAPED_SLOTS:
            continue
        if slot_name in output:
            continue
        missing.append(slot_name)
    if missing:
        logger.warning(
            "render_tp_public: %d tp-visible slot(s) not in output: %s",
            len(missing),
            missing,
        )


# ---------------------------------------------------------------------------
# render_mcp_response
# ---------------------------------------------------------------------------


def render_mcp_response(
    topic_bus: TopicBus, run_bus: RunBus | RunBusReadOnly
) -> dict:
    """MCP server response — render_tp_public plus QA reasoning at top
    level for clients that want to consume the QA chain."""
    base = render_tp_public(topic_bus, run_bus)
    base["qa_problems_found"] = list(topic_bus.qa_problems_found)
    base["qa_corrections"] = [c.model_dump() for c in topic_bus.qa_corrections]
    return base


# ---------------------------------------------------------------------------
# render_rss_entry
# ---------------------------------------------------------------------------


def render_rss_entry(
    topic_bus: TopicBus, run_bus: RunBus | RunBusReadOnly
) -> dict:
    """Minimal RSS-feed entry per ARCH §6.3. Five keys."""
    rb = _runbus_for_render(run_bus)
    article = topic_bus.qa_corrected_article
    assignment = topic_bus.editor_selected_topic
    return {
        "title": article.headline,
        "description": article.summary,
        "link": f"{RSS_BASE_URL}{assignment.topic_slug}",
        "pubDate": rb.run_date,
        "guid": assignment.id,
    }


# ---------------------------------------------------------------------------
# render_internal_debug
# ---------------------------------------------------------------------------


def render_internal_debug(
    topic_bus: TopicBus, run_bus: RunBus | RunBusReadOnly
) -> dict:
    """Everything — full bus dumps, no filtering. For crash dumps and
    interactive debugging."""
    return {
        "topic_bus": topic_bus.model_dump(),
        "run_bus": run_bus.model_dump(),
    }


# ---------------------------------------------------------------------------
# compose_bias_card  (ARCH §4B.12 multi-slot derived view)
# ---------------------------------------------------------------------------


def compose_bias_card(topic_bus: TopicBus) -> dict:
    """Five Vision dimensions surfaced as one structured block, derived from
    existing TopicBus slots. No new state.

    Dimension mapping per ARCH §4B.12:
    - language: bias_language_findings (LLM-emitted linguistic findings)
    - source: source_balance.{by_country, by_language, represented} + total
    - geographical: source_balance.{represented, by_country, missing_from_dossier}
    - selection: coverage_gaps_validated + perspective_missing_positions +
                 qa_problems_found
    - framing: position_clusters_summary (high-level projection of
               perspective_clusters_synced) + qa_divergences plus two
               deterministic counts (cluster_count, distinct_actor_count).

    Plus the LLM-supplied reader_note from the bias_language agent.

    Operates entirely on TopicBus state — no run_bus, no other inputs.
    """
    sb = topic_bus.source_balance
    clusters = topic_bus.perspective_clusters_synced
    actors = topic_bus.final_actors
    aggregates = _cluster_aggregates(clusters, actors)

    return {
        "language": list(topic_bus.bias_language_findings),
        "source": {
            "by_country": dict(sb.by_country),
            "by_language": dict(sb.by_language),
            "represented": list(sb.represented),
            "total": len(topic_bus.final_sources),
        },
        "geographical": {
            "represented": list(sb.represented),
            "by_country": dict(sb.by_country),
            "missing_from_dossier": list(sb.missing_from_dossier),
        },
        "selection": {
            "coverage_gaps": list(topic_bus.coverage_gaps_validated),
            "missing_positions": list(topic_bus.perspective_missing_positions),
            "qa_problems_found": list(topic_bus.qa_problems_found),
        },
        "framing": {
            "position_clusters_summary": _summarise_clusters(clusters),
            "cross_source_divergences": list(topic_bus.qa_divergences),
            "cluster_count": aggregates["cluster_count"],
            "distinct_actor_count": aggregates["distinct_actor_count"],
        },
        "reader_note": topic_bus.bias_reader_note,
    }


def _cluster_aggregates(clusters: list[dict], actors: list) -> dict:
    """Compute the two deterministic aggregates surfaced in the bias-card
    framing block:

    - cluster_count: number of dict clusters.
    - distinct_actor_count: number of named entries in ``final_actors`` —
      the canonical deduped list. Replaces the prior per-cluster
      (name, role) walk over ``cluster.actors[]`` (the leak-shaped slot
      that no longer exists).
    """
    cluster_count = sum(1 for c in (clusters or []) if isinstance(c, dict))
    distinct_actor_count = sum(
        1 for a in (actors or []) if isinstance(a, dict) and a.get("name")
    )
    return {
        "cluster_count": cluster_count,
        "distinct_actor_count": distinct_actor_count,
    }


def _summarise_clusters(clusters: list[dict]) -> list[dict]:
    """Project each cluster to a high-level summary `{id, position_label,
    n_actors, n_sources}` for the framing block. Keeps the bias
    card readable without duplicating the full perspectives section."""
    summary: list[dict] = []
    for c in clusters or []:
        if not isinstance(c, dict):
            continue
        source_ids = c.get("source_ids") or []
        actor_ids = c.get("actor_ids") or []
        summary.append(
            {
                "id": c.get("id", ""),
                "position_label": c.get("position_label", ""),
                "n_actors": len(actor_ids) if isinstance(actor_ids, list) else 0,
                "n_sources": len(source_ids) if isinstance(source_ids, list) else 0,
            }
        )
    return summary


__all__ = [
    "RSS_BASE_URL",
    "VisibilityTag",
    "compose_bias_card",
    "render_internal_debug",
    "render_mcp_response",
    "render_rss_entry",
    "render_tp_public",
    "select_by_visibility",
]
