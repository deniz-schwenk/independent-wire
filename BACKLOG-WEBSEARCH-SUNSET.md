# BACKLOG — Web search sunset criterion (fixed 2026-07-13, pre-measurement)

Status: backlog (diagnosis + fixed criterion; measurement brief follows
once merge mode is live). Origin: registry-a2 gate review
(scratch/registry-shadow/GATE-REVIEW-2026-07-13.md, decision D2).
This file is TRACKED so the criterion survives scratch/ and cannot be
adjusted after seeing results.

## Why web search must eventually go

Web search injects an unauditable editorial layer into a pipeline whose
thesis is auditable selection: result ranking is decided by a commercial
actor, and news agencies (AFP, Reuters, dpa) hold commercial deals with
search providers. IW can neither audit nor influence that selection —
it is structurally the same opaque filtering the project exists to make
visible. This is provider-independent (currently Ollama Cloud). The
curated registry (on_demand entries of config/sources.json) is also a
selection — but versioned, open, community-correctable: visible bias
instead of invisible bias. Secondary, measured defect: web results are
only 13-53% dated (shadow ledger, 17 rows); registry holds are
100%-dated by construction. Removing the web arm is also a genuine
complexity reduction (one external dependency and one seam fewer).

## The criterion (verbatim from D2 — do not reinterpret)

Web search is retired when a TP-level A/B (registry-only vs merge, same
topics, same day) shows NO material loss on:
  (i)   perspective spectrum breadth,
  (ii)  region coverage,
  (iii) count of independently verified claims.

Judging rules (standing, non-negotiable):
- Deterministic sub-metrics (region/language/source counts) are computed
  by Python, never judged.
- Qualitative comparison (perspective breadth): blind, anonymized,
  anchor-free against sources, strongest available model, ALWAYS as
  Claude-Code-spawned subagents — never direct API calls.
- Whoever produced the material cannot attest it; Architect review is
  blind, judgments fixed before seeing labels.
- Note statistical thinness explicitly if N is small.

Edge-case carve-out: web search may remain legitimate where the registry
structurally has nothing (breaking events with new actors, underserved
regions) — a measurable, shrinking delta to be closed by registry
growth (Phase-2 community workstream), not a permanent state. If the
A/B fails, the answer is registry expansion + re-measure, not criterion
relaxation.

## Sequencing

1. Merge mode lands (TASK-RESEARCH-MERGE-MODE.md), after the hydration
   selector swap.
2. Merge runs in production long enough for a same-day A/B corpus.
3. Measurement brief written by the Architect from this backlog.
4. On pass: provider flip to registry-only, web-search code retired,
   docs/ARCHITECTURE.md dependency entry removed.

## Related
- scratch/registry-shadow/GATE-REVIEW-2026-07-13.md (D1-D4)
- scratch/registry-shadow/LEDGER.md (shadow baseline, continues daily)
- BACKLOG-RESEARCHER-REGISTRY (phases A1/A2)
