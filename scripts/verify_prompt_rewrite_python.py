#!/usr/bin/env python3
"""Offline verification for the prompt-rewrite Python follow-ups.

Exercises the deterministic Python paths added by
WP-PROMPT-REWRITE-PYTHON-FOLLOWUPS — no LLM calls. Each check runs a
synthetic input through the relevant helper and asserts the expected
shape of the output.

Exits 0 on all-pass, 1 on any failure.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.pipeline import (  # noqa: E402
    Pipeline,
    _collect_cited_writer_refs,
    _enrich_position_clusters,
    _INTERNAL_RSRC_ID_KEY,
    _INTERNAL_WEB_ID_KEY,
    _merge_writer_sources,
    _renumber_and_prune_sources,
    _slugify,
    _strip_internal_fields_from_sources,
)
from src.pipeline_hydrated import merge_perspektiv_deltas


failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"[PASS] {label}")
    else:
        msg = f"{label}: {detail}" if detail else label
        failures.append(msg)
        print(f"[FAIL] {msg}")


# --- Item 2: _slugify ---

check(
    "slugify: basic title",
    _slugify("Hello, World!") == "hello-world",
    f"got {_slugify('Hello, World!')!r}",
)
check(
    "slugify: ASCII-fold",
    _slugify("Café Résumé") == "cafe-resume",
    f"got {_slugify('Café Résumé')!r}",
)
check(
    "slugify: long title truncates at word boundary",
    len(_slugify("a" * 80)) <= 60,
)
check(
    "slugify: empty title returns empty",
    _slugify("") == "",
)


# --- Item 1: _rebuild_curator_source_ids ---

class _StubResult:
    def __init__(self, content: str, structured: object | None = None) -> None:
        self.content = content
        self.structured = structured


pipeline = Pipeline(name="verify", agents={}, output_dir="/tmp/verify-prompt-rewrite-py")
raw_findings = [{"title": f"finding-{i}"} for i in range(5)]
new_shape = {
    "topics": [
        {"title": "Topic A", "relevance_score": 7, "summary": "..."},
        {"title": "Topic B", "relevance_score": 5, "summary": "..."},
        {"title": "Topic C", "relevance_score": 3, "summary": "..."},
    ],
    # Flat array: position = finding_index, value = topic_index (or null).
    # finding-0 → A, finding-1 → B, finding-2 → A, finding-3 → none, finding-4 → A.
    "cluster_assignments": [0, 1, 0, None, 0],
}
import json as _json
result = _StubResult(_json.dumps(new_shape), structured=new_shape)
topics = pipeline._rebuild_curator_source_ids(result, raw_findings)
check(
    "curator rebuild: topic 0 source_ids",
    topics[0]["source_ids"] == ["finding-0", "finding-2", "finding-4"],
    f"got {topics[0]['source_ids']}",
)
check(
    "curator rebuild: topic 1 source_ids",
    topics[1]["source_ids"] == ["finding-1"],
    f"got {topics[1]['source_ids']}",
)
check(
    "curator rebuild: topic 2 source_ids (no findings assigned)",
    topics[2]["source_ids"] == [],
    f"got {topics[2]['source_ids']}",
)

# Legacy (list) shape passes through
legacy = [{"title": "T", "source_ids": ["finding-0"]}]
result_legacy = _StubResult(_json.dumps(legacy), structured=legacy)
topics_legacy = pipeline._rebuild_curator_source_ids(result_legacy, raw_findings)
check(
    "curator rebuild: legacy list shape passes through",
    topics_legacy and topics_legacy[0]["source_ids"] == ["finding-0"],
)

# Truncation recovery: brace-extraction repair drops cluster_assignments
# (the actual failure mode observed in production with Gemini Flash). The
# pipeline must regex-recover the array from the raw content. Simulate by
# pairing a structured dict with only ``topics`` and a content string that
# still carries the (truncated) ``cluster_assignments`` key.
truncated_content = (
    '{"topics": [{"title": "Topic A"}, {"title": "Topic B"}, {"title": "Topic C"}], '
    '"cluster_assignments": [\n    0,\n    1,\n    0,\n    null,\n    0,\n    null,'
)
truncated_struct = {"topics": [
    {"title": "Topic A", "relevance_score": 7, "summary": "..."},
    {"title": "Topic B", "relevance_score": 5, "summary": "..."},
    {"title": "Topic C", "relevance_score": 3, "summary": "..."},
]}
result_truncated = _StubResult(truncated_content, structured=truncated_struct)
topics_truncated = pipeline._rebuild_curator_source_ids(result_truncated, raw_findings)
check(
    "curator rebuild: truncation recovery — topic 0 source_ids",
    topics_truncated[0]["source_ids"] == ["finding-0", "finding-2", "finding-4"],
    f"got {topics_truncated[0]['source_ids']}",
)
check(
    "curator rebuild: truncation recovery — topic 1 source_ids",
    topics_truncated[1]["source_ids"] == ["finding-1"],
    f"got {topics_truncated[1]['source_ids']}",
)
check(
    "curator rebuild: truncation recovery — topic 2 (null/short)",
    topics_truncated[2]["source_ids"] == [],
    f"got {topics_truncated[2]['source_ids']}",
)


# --- Item 4: _enrich_position_clusters assigns pc-NNN ---

dossier = {"sources": [
    {"id": "rsrc-001", "country": "United States", "language": "en", "actors_quoted": []},
    {"id": "rsrc-002", "country": "Germany", "language": "de", "actors_quoted": []},
]}
perspectives = {
    "position_clusters": [
        {"position_label": "A", "position_summary": "...", "source_ids": ["rsrc-001"]},
        {"position_label": "B", "position_summary": "...", "source_ids": ["rsrc-002"]},
    ],
    "missing_positions": [],
}
enriched = _enrich_position_clusters(perspectives, dossier)
check(
    "perspektiv: pc-001 assigned to first cluster",
    enriched["position_clusters"][0]["id"] == "pc-001",
)
check(
    "perspektiv: pc-002 assigned to second cluster",
    enriched["position_clusters"][1]["id"] == "pc-002",
)


# --- Item 5: _merge_writer_sources with rsrc/web shapes ---

writer_refs = [
    {"rsrc_id": "rsrc-001"},
    {"web_id": "web-1", "url": "https://example.com", "outlet": "Example",
     "title": "T", "language": "en", "country": "United States"},
]
research_dossier = {"sources": [
    {"id": "rsrc-001", "url": "https://r.example.com", "title": "RT",
     "outlet": "RO", "language": "en", "country": "UK", "estimated_date": "2026-01-01"},
]}
merged = _merge_writer_sources(writer_refs, research_dossier)
check(
    "merge: rsrc source has dossier metadata + rsrc_id stash",
    merged[0].get("url") == "https://r.example.com"
    and merged[0].get(_INTERNAL_RSRC_ID_KEY) == "rsrc-001",
)
check(
    "merge: web source carries web_id stash and metadata",
    merged[1].get(_INTERNAL_WEB_ID_KEY) == "web-1"
    and merged[1].get("url") == "https://example.com",
)
check(
    "merge: no `id` set yet (renumbering owns that)",
    "id" not in merged[0] and "id" not in merged[1],
)


# --- Item 5: _collect_cited_writer_refs reads both forms ---

article = {
    "headline": "Headline",
    "subheadline": "",
    "body": "Body cites [rsrc-001] and [web-1] and [rsrc-002].",
    "summary": "Sum [web-2].",
}
cited = _collect_cited_writer_refs(article)
check(
    "collect: rsrc tokens are zero-padded",
    "rsrc-001" in cited and "rsrc-002" in cited,
)
check(
    "collect: web tokens are un-padded",
    "web-1" in cited and "web-2" in cited,
)


# --- Item 5: _renumber_and_prune_sources ---

article = {
    "headline": "H",
    "body": "Body [rsrc-001] [web-1] [rsrc-002]",
    "summary": "S",
}
sources = [
    {_INTERNAL_RSRC_ID_KEY: "rsrc-001", "url": "u1", "outlet": "o1"},
    {_INTERNAL_RSRC_ID_KEY: "rsrc-002", "url": "u2", "outlet": "o2"},
    {_INTERNAL_RSRC_ID_KEY: "rsrc-003", "url": "u3", "outlet": "o3"},  # uncited
    {_INTERNAL_WEB_ID_KEY: "web-1", "url": "w1", "outlet": "w_o"},
]
new_article, new_sources, rename_map = _renumber_and_prune_sources(article, sources, slug="test")
check(
    "renumber: dropped uncited sources",
    len(new_sources) == 3,
    f"got {len(new_sources)}",
)
check(
    "renumber: survivors get sequential src-NNN ids",
    [s["id"] for s in new_sources] == ["src-001", "src-002", "src-003"],
)
check(
    "renumber: body citations rewritten to src-NNN",
    "[src-001]" in new_article["body"] and "[src-002]" in new_article["body"],
)
check(
    "renumber: web_id stash dropped on survivor",
    _INTERNAL_WEB_ID_KEY not in new_sources[2],
)
check(
    "renumber: rsrc_id stash kept on dossier survivors (Fix-3 needs it)",
    new_sources[0].get(_INTERNAL_RSRC_ID_KEY) == "rsrc-001",
)
check(
    "renumber: rename_map keyed by stash token",
    rename_map.get("rsrc-001") == "src-001"
    and rename_map.get("web-1") == "src-003",
)


# --- _strip_internal_fields_from_sources strips both stashes ---

src_with_both = [
    {"id": "src-001", _INTERNAL_RSRC_ID_KEY: "rsrc-001", "url": "u"},
    {"id": "src-002", _INTERNAL_WEB_ID_KEY: "web-1", "url": "u2"},
]
stripped = _strip_internal_fields_from_sources(src_with_both)
check(
    "strip: rsrc_id removed",
    _INTERNAL_RSRC_ID_KEY not in stripped[0],
)
check(
    "strip: web_id removed",
    _INTERNAL_WEB_ID_KEY not in stripped[1],
)


# --- Item 8: merge_perspektiv_deltas V2 shape ---

original = {
    "position_clusters": [
        {"id": "pc-001", "position_label": "A", "position_summary": "old A summary",
         "actors": [], "regions": [], "languages": [], "representation": "marginal",
         "source_ids": ["rsrc-001"]},
        {"id": "pc-002", "position_label": "B", "position_summary": "B summary",
         "actors": [], "regions": [], "languages": [], "representation": "marginal",
         "source_ids": ["rsrc-002"]},
    ],
    "missing_positions": [{"type": "civil_society", "description": "..."}],
}
delta = {
    "position_cluster_updates": [
        {"id": "pc-001", "position_summary": "new A summary"},
        {"id": "pc-002", "position_label": None, "position_summary": "B updated"},  # null label skipped
        {"id": "pc-999", "position_label": "ghost"},  # unknown id skipped
    ],
}
merged_p = merge_perspektiv_deltas(original, delta, slug="test")
check(
    "sync V2: pc-001 summary overwritten",
    merged_p["position_clusters"][0]["position_summary"] == "new A summary",
)
check(
    "sync V2: pc-001 label unchanged (absent in delta)",
    merged_p["position_clusters"][0]["position_label"] == "A",
)
check(
    "sync V2: pc-002 null label NOT applied (V2 forbids null overrides)",
    merged_p["position_clusters"][1]["position_label"] == "B",
)
check(
    "sync V2: pc-002 summary overwritten",
    merged_p["position_clusters"][1]["position_summary"] == "B updated",
)
check(
    "sync V2: missing_positions pass through",
    merged_p["missing_positions"] == original["missing_positions"],
)


if failures:
    print(f"\n{len(failures)} failure(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"\nAll checks passed.")
sys.exit(0)
