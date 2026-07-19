"""Acceptance tests for TASK-CLUSTER-ID-JOIN.

The deterministic ``topic_id`` join replaces two fragile title-text joins in
the run-level chain:

1. ``_attach_raw_data_from_curated`` — Curator enrichment onto Editor output.
2. ``attach_hydration_urls_to_assignments`` — hydration URLs onto assignments.

Failure the task fixes (run 2026-07-19): the Editor rewrote a topic title
beyond any token overlap with its source cluster
("U.S.-Iran conflict widens ..." vs "U.S. and Iran trade military strikes
across the Middle East"), and BOTH joins failed. With the Editor echoing the
deterministic ``topic_id``, both joins survive an arbitrary title rewrite;
the title/slug and token-overlap heuristics are demoted to loud fallbacks,
exercised only when a topic_id is missing or unknown.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from src.agent import AgentResult
from src.agent_stages import EditorStage
from src.bus import RunBus
from src.stages.run_stages import make_attach_hydration_urls_to_assignments


RUN_DATE = "2026-07-19"


class _FakeEditor:
    """Minimal Agent.run() stand-in returning a pre-baked structured output."""

    def __init__(self, structured: Any) -> None:
        self._structured = structured
        self.name = "editor"
        self.calls: list[dict] = []

    async def run(
        self, message: str = "", context: dict | None = None, **kw: Any
    ) -> AgentResult:
        self.calls.append({"message": message, "context": context, **kw})
        return AgentResult(content="", structured=self._structured)


# The two source clusters, keyed by deterministic topic_id. `source_ids` map
# finding-0/1 → cluster -00 and finding-2 → cluster -01.
def _curated_topics() -> list[dict]:
    return [
        {
            "topic_id": "ct-2026-07-19-00",
            "title": "U.S. and Iran trade military strikes across the Middle East",
            "summary": "Reciprocal strikes across the Gulf.",
            "source_ids": ["finding-0", "finding-1"],
            "source_count": 2,
            "geographic_coverage": ["ME", "NA"],
            "languages": ["en", "fa"],
        },
        {
            "topic_id": "ct-2026-07-19-01",
            "title": "Kuwait refinery fire",
            "summary": "A blaze at a Kuwaiti refinery.",
            "source_ids": ["finding-2"],
            "source_count": 1,
            "geographic_coverage": ["ME"],
            "languages": ["ar"],
        },
    ]


def _seed_feeds(tmp_path: Path) -> tuple[Path, Path]:
    """Seed raw/{date}/feeds.json + config/sources.json; return (raw_dir, sources)."""
    feeds = [
        {"source_name": "Reuters", "source_url": "https://reuters.example/a",
         "language": "en", "title": "Reuters strike report"},
        {"source_name": "BBC", "source_url": "https://bbc.example/b",
         "language": "en", "title": "BBC strike report"},
        {"source_name": "AFP", "source_url": "https://afp.example/c",
         "language": "en", "title": "AFP refinery fire"},
    ]
    raw_dir = tmp_path / "raw"
    (raw_dir / RUN_DATE).mkdir(parents=True)
    (raw_dir / RUN_DATE / "feeds.json").write_text(
        json.dumps(feeds), encoding="utf-8"
    )
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True)
    (cfg / "sources.json").write_text(
        json.dumps({"feeds": [
            {"name": "Reuters", "country": "GB"},
            {"name": "BBC", "country": "GB"},
            {"name": "AFP", "country": "FR"},
        ]}),
        encoding="utf-8",
    )
    return raw_dir, cfg / "sources.json"


def _run(stage, *args):
    return asyncio.run(stage(*args))


# ---------------------------------------------------------------------------
# Acceptance 1 — all titles rewritten, topic_ids correct → both joins succeed,
# no fallback warnings.
# ---------------------------------------------------------------------------


def test_all_titles_rewritten_but_ids_correct_both_joins_succeed(tmp_path, caplog):
    curated = _curated_topics()

    # Editor rewrites BOTH titles beyond any token overlap with the source
    # clusters, but echoes the correct topic_id for each (the ID-key pattern).
    editor_out = {
        "assignments": [
            {
                "topic_id": "ct-2026-07-19-00",
                "title": (
                    "U.S.-Iran conflict widens as Kuwaiti infrastructure "
                    "burns and Iranian currency hits new low"
                ),
                "priority": 9,
                "selection_reason": "Contested cross-regional escalation.",
                "follow_up_to": None,
                "follow_up_reason": None,
            },
            {
                "topic_id": "ct-2026-07-19-01",
                "title": "Gulf energy supply disruption after industrial blaze",
                "priority": 6,
                "selection_reason": "Energy-market ramifications.",
                "follow_up_to": None,
                "follow_up_reason": None,
            },
        ]
    }

    rb = RunBus()
    rb.run_date = RUN_DATE
    rb.run_variant = "hydrated"
    rb.curator_topics = curated
    rb.curator_topics_unsliced = curated

    # --- Join 1: raw_data attach inside EditorStage -------------------------
    with caplog.at_level(logging.WARNING):
        rb = _run(EditorStage(_FakeEditor(editor_out)), rb)

    assignments = rb.editor_assignments
    assert len(assignments) == 2
    by_tid = {a["topic_id"]: a for a in assignments}
    # Every assignment received raw_data via the topic_id join despite the
    # title rewrite.
    assert by_tid["ct-2026-07-19-00"]["raw_data"]["source_ids"] == [
        "finding-0", "finding-1",
    ]
    assert by_tid["ct-2026-07-19-01"]["raw_data"]["source_ids"] == ["finding-2"]
    # topic_id survived id/slug finalization onto editor_assignments.
    assert by_tid["ct-2026-07-19-00"]["id"] == "tp-2026-07-19-001"

    # --- Join 2: hydration-URL attach ---------------------------------------
    raw_dir, sources_path = _seed_feeds(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )
    with caplog.at_level(logging.WARNING):
        rb = _run(stage, rb)

    by_tid = {a["topic_id"]: a for a in rb.editor_assignments}
    urls_00 = by_tid["ct-2026-07-19-00"]["raw_data"]["hydration_urls"]
    urls_01 = by_tid["ct-2026-07-19-01"]["raw_data"]["hydration_urls"]
    # Cluster match by topic_id → the right feeds, despite zero title overlap.
    assert {u["outlet"] for u in urls_00} == {"Reuters", "BBC"}
    assert {u["outlet"] for u in urls_01} == {"AFP"}

    # No fallback fired anywhere in the chain.
    assert not any("falling back" in m for m in caplog.messages), caplog.messages


# ---------------------------------------------------------------------------
# Acceptance 2 — one assignment with a missing topic_id falls back (raw_data
# via title, cluster via token overlap), WARNING logged; the id-matched
# assignment is unaffected.
# ---------------------------------------------------------------------------


def test_missing_topic_id_falls_back_loudly_others_unaffected(tmp_path, caplog):
    curated = _curated_topics()

    editor_out = {
        "assignments": [
            {   # correct topic_id, rewritten title → id join, no fallback
                "topic_id": "ct-2026-07-19-00",
                "title": "Escalation across the Gulf reshapes the region",
                "priority": 9,
                "selection_reason": "Contested escalation.",
                "follow_up_to": None,
                "follow_up_reason": None,
            },
            {   # missing topic_id, but the title still overlaps its cluster →
                # fallback must recover it via title/slug + token overlap
                "topic_id": "",
                "title": "Kuwait refinery fire",
                "priority": 6,
                "selection_reason": "Energy ramifications.",
                "follow_up_to": None,
                "follow_up_reason": None,
            },
        ]
    }

    rb = RunBus()
    rb.run_date = RUN_DATE
    rb.run_variant = "hydrated"
    rb.curator_topics = curated
    rb.curator_topics_unsliced = curated

    with caplog.at_level(logging.WARNING):
        rb = _run(EditorStage(_FakeEditor(editor_out)), rb)

    by_pos = {a["title"]: a for a in rb.editor_assignments}
    id_matched = by_pos["Escalation across the Gulf reshapes the region"]
    fell_back = by_pos["Kuwait refinery fire"]
    # id-matched assignment unaffected — correct raw_data via topic_id.
    assert id_matched["raw_data"]["source_ids"] == ["finding-0", "finding-1"]
    # missing-id assignment recovered via the title fallback.
    assert fell_back["raw_data"]["source_ids"] == ["finding-2"]
    # A raw_data fallback WARNING names the missing id + title.
    raw_warn = [m for m in caplog.messages if "falling back to title/slug" in m]
    assert raw_warn and "Kuwait refinery fire" in raw_warn[0]
    # ...and the fallback fired only for the missing-id assignment.
    assert not any(
        "Escalation across the Gulf" in m
        for m in caplog.messages
        if "falling back" in m
    )

    caplog.clear()
    raw_dir, sources_path = _seed_feeds(tmp_path)
    stage = make_attach_hydration_urls_to_assignments(
        raw_dir=raw_dir, sources_path=sources_path
    )
    with caplog.at_level(logging.WARNING):
        rb = _run(stage, rb)

    by_pos = {a["title"]: a for a in rb.editor_assignments}
    id_urls = by_pos["Escalation across the Gulf reshapes the region"][
        "raw_data"]["hydration_urls"]
    fb_urls = by_pos["Kuwait refinery fire"]["raw_data"]["hydration_urls"]
    # id-matched assignment unaffected.
    assert {u["outlet"] for u in id_urls} == {"Reuters", "BBC"}
    # missing-id assignment recovered via token-overlap fallback.
    assert {u["outlet"] for u in fb_urls} == {"AFP"}
    # A token-overlap fallback WARNING fired, naming the fallen-back assignment.
    tok_warn = [
        m for m in caplog.messages if "falling back to token-overlap" in m
    ]
    assert tok_warn and "Kuwait refinery fire" in tok_warn[0]
    # The id-matched assignment did NOT trigger a hydration fallback.
    assert not any(
        "Escalation across the Gulf" in m
        for m in caplog.messages
        if "falling back" in m
    )
