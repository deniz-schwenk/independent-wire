# BACKLOG — Intraday Collector (fetch + translate in 4h windows)

**Status:** Architect diagnosis + design sketch. NOT execution-ready.
**Date:** 2026-07-06
**Gate:** parked behind MADLAD enablement blockers and Batch-2/Ollama-search
validation (07-07 onwards). Nothing here lands before those are green.

## Problem

Two independent pressures point at the same mechanism:

1. **MADLAD RAM peak.** Translating the full non-Latin corpus in one pass at
   06:00 peaks at ~24.7 GB on the Mini (32 GB) — too close to the ceiling once
   `IW_CLUSTER_TRANSLATE` is enabled. This is the "RAM chunking" blocker in the
   MADLAD enablement gate.
2. **RSS has no archive.** Fast-rolling feeds drop items between fetches
   (backtest lesson 07-06). A single 06:00 fetch structurally loses coverage,
   especially on high-volume Batch-2 feeds.

## Decision (Deniz, 2026-07-06)

- Publication stays 1x/day. Intraday states have NO consumer — we build none.
- Curation (LLM topic discovery) stays a single pass at 06:00.
- Only deterministic pre-work is spread across the day: fetch delta,
  dedup-on-append, MADLAD translation of new non-Latin titles.
- Iterative/incremental clustering is explicitly rejected for now:
  order-dependent merges can freeze mistakes a full pass would not make; a
  single re-cluster at 06:00 over the accumulated, already-translated corpus
  is simpler and at least as good (clustering itself is cheap — fastembed,
  seconds). Revisit only if a product reason appears (intraday publishing,
  narrative tracking / Phase 3).

## Design sketch

- **Schedule:** 4h grid, aligned so the main run occupies one slot.
  Collector windows: 10:00, 14:00, 18:00, 22:00, 02:00 local.
  06:00 = main run, which performs the final delta fetch itself.
  No collector/main-run collision, no special-casing.
- **Own LaunchAgent**, separate from daily_run.sh — a collector failure must
  never endanger the main run. Missed windows are self-healing: the next
  window (or the 06:00 final delta) picks up the items.
- **Append-only day store** with timestamps. Dedup is deterministic Python
  at append time (URL/GUID based). Store is the single source the 06:00 run
  reads; the rest of the pipeline is unchanged and unaware.
- **MADLAD translates only the delta** per window — spreads the translation
  load across ~6 small windows instead of one ~24.7 GB peak. Per-window
  model load (2.8 GB CT2-int8) is seconds; acceptable overhead.
- Night windows with thin deltas are cheap no-ops by construction.

## Invariants (must hold in any implementation)

- Deterministic-before-LLM: dedup, ordering, counting live in Python.
  No LLM touches the store.
- 06:00 pipeline behaviour is bit-for-bit compatible when the collector has
  never run (cold-start / all windows missed): the final delta fetch at 06:00
  degrades gracefully to today's single-fetch behaviour.
- Store is append-only; no window rewrites prior entries. Timestamps recorded
  per item (first-seen), enabling future narrative tracking without redesign.
- **Store is scoped to exactly ONE production run** (keyed by target run date,
  not calendar day). After the 06:00 run consumes it, a fresh store begins —
  no feed items carry over between production runs. The 22:00 and 02:00
  windows collect into the NEXT morning's store. In-store dedup is per-store
  only; cross-day dedup stays where it lives today (pipeline), unchanged.
- Loud logging per window: items fetched, items new after dedup, items
  translated, wall time, peak RSS if cheaply measurable.
- One production change per 06:00 run still applies: collector enablement is
  its own landing window with its own signature.

## Open questions (before cutting a TASK)

1. Store format/location: extend raw/{date}/feeds.json semantics vs. a new
   store file consumed by fetch step — decide with a look at fetch_feeds.py
   seams (avoid touching the bus schema; this is pre-pipeline).
2. Interaction with MADLAD enablement order: collector can land BEFORE the
   translate flag flips (fetch-delta only, translation step dormant), which
   de-risks both landings. Recommended sequencing.
3. Whether the 02:00 window is worth it vs. letting 06:00 absorb the night —
   measure delta sizes after a few days, drop the window if consistently ~0.

## References

- MADLAD gate: 5 blockers + RAM chunking (handoff 2026-07-06)
- RSS-no-archive backtest lesson (handoff 2026-07-06, Tageslektion 4)
- Vision Paper Part 11 Phase 3 (narrative tracking = future consumer of
  timestamped store)
