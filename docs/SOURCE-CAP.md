# Source Cap — Decision Record V1

**Status:** DECIDED, in implementation via `TASK-SOURCE-CAP-2026-05-11.md`.
**Date:** 2026-05-11.
**Successor:** none yet. This is V1. See `BACKLOG-SOURCE-DIVERSITY-V2.md` (gitignored) for the planned V2 direction.

## Context

The 2026-05-11 baseline hydrated pipeline run cost $13.91, of which $11.91 (86%) came from a single Topic Package (TP-001, US-Iran). The cause was a Curator cluster with 1004 cluster_assignments for that topic, which propagated through `attach_hydration_urls_to_assignments` into ~600 hydration URLs, into Phase-1 hydration costs of $2.27 on 1.06M tokens, and cascaded oversized inputs through Phase-2, Perspective, Writer, and QA.

A Curator-only smoke against the same `curator_findings` reproduced the failure mode (979-finding Iran cluster vs 1004 baseline, 2.5% variation) confirming the behaviour is structural, not stochastic. Curator clusters everything topically adjacent into a single cluster without size constraints. The pipeline downstream has no cap and amplifies the bloat at every stage.

The Independent Wire Vision Paper commits to "Pipeline cost under $1 per run." Operating cost is meant to be ~$30/month at three TPs/day. Without a cap, a single hot topic can blow the monthly budget in one run.

## Decision

Add a hard cap of **40 hydration URLs per Editor assignment** in `attach_hydration_urls_to_assignments` (run-stage). Selection under the cap is **stratified round-robin by outlet, recency-tiebreak within outlet, hard ceiling of 3 URLs per outlet**.

Cap layer: `attach_hydration_urls_to_assignments`. Editor sees the full unsliced cluster for its priority assessment; only downstream hydration is capped.

Implementation: `select_diverse_hydration_urls(candidates, cap=40, max_per_outlet=3)` as a pure function, wired into the existing token-overlap matcher.

## Considered alternatives

**Naive top-N** (`urls[:40]` or sort by `relevance_score`): rejected. Replicates the structural bias of the source feed mix — a westernly-skewed candidate set would stay westernly-skewed after selection. Cost-problem solved, bias-problem amplified.

**Random sampling**: rejected. Statistically unbiased but allows multiple URLs from a single outlet, which gives no diversity guarantee on small samples.

**Cap at Curator output level**: rejected. Editor would only see the Cap-selected findings, biasing its priority assessment. Better to let Editor see full cluster scale (which itself is a relevance signal) and cap one stage later.

**Cap at `merge_sources`** (after Researcher merge): rejected. Phase-1 + Phase-2 would already have run on the bloated input — the cost cascade isn't stopped, only the downstream is. ~40-50% cost reduction vs. ~80% at the URL-attachment layer.

**Multi-key round-robin (outlet + country + language) for V1**: rejected for complexity. V1 ships single-key (outlet). V2 candidate.

## Known limitations

This is intentionally a defensive quick-fix. It is not the architecturally-clean diversity mechanism the project deserves. Specific weaknesses:

- **Outlet-diversity is a proxy for position-diversity, not a guarantee.** If a hot topic's candidate set is dominated by outlets that share editorial leaning, round-robin selection preserves that. The 72-outlet pool in `config/sources.json` is broad enough that this is unlikely in practice but not impossible.

- **`cap=40` is arbitrary.** Tuned to bring TP-001 from 640 sources back into the normal 30-60 range. For a genuinely globe-spanning story with substantial multi-angle coverage, 40 may under-represent. For a small story, 40 may be unnecessary headroom (in practice cap is min(cap, total), so this matters less).

- **`max_per_outlet=3` is arbitrary.** Some outlets carry substantively different multi-angle coverage of one event (Al Jazeera covering Iran from politics, economics, humanitarian, regional-security angles each separately). Hard ceiling drops most of that.

- **Recency-tiebreak is operationally active as of the `feat(fetch-feeds): persist published_at on findings` commit landing alongside V1.** The selector's `published_at` sort key was contractually specified at design time and operationally activated by extending `scripts/fetch_feeds.py` to persist `published_at` (ISO 8601, both RSS and GDELT paths) into `raw/{date}/feeds.json`. Old `raw/{date}/feeds.json` files (pre-activation) carry no `published_at`; the selector falls back to input order for those, no migration required.

- **Recency-tiebreak even when active ignores substantive value.** Within an outlet, newer wins. A two-week-old in-depth investigative piece would lose to a 4-hour-old wire update. (24h RSS cutoff filter limits this in practice to hour-level differences.)

- **No tier-awareness.** State media, independent peer-reviewed sources, and aggregators are treated equally by the selector. The pipeline has `tier` and `editorial_independence` metadata available via `config/outlet_registry.json` — V1 doesn't use it.

- **Single-axis diversity.** Country, language, and tier-balance are emergent from the outlet pool composition, not enforced by the selector. If the outlet pool itself is geographically skewed (and it is — the Vision Paper acknowledges "Hebrew-language media is more accessible via RSS than Lebanese or Palestinian sources"), the selector inherits that skew.

## Re-evaluation triggers

This decision should be revisited when any of the following occur:

1. **Re-baseline run shows geographic monotony.** After the Source-Cap is live and the next baseline produces three TPs, inspect `source_balance` per TP. If any TP shows > 70% of sources from a single country (excluding TPs that are inherently country-specific by topic), the outlet-only round-robin isn't enough.

2. **Coverage gaps flag systematic regional absence.** If `validate_coverage_gaps_stage` repeatedly emits "missing global south perspective" or equivalent as a gap, the cap is filtering out voices it should be preserving.

3. **Bias Detector reader-notes flag source-bias.** If `bias_language_findings` or `bias_reader_note` repeatedly cites under-represented regions or perspectives, the selection layer is contributing.

4. **A TP after Cap has < 20 sources.** Indicates the candidate pool itself was small and the cap is irrelevant — but also that we have a separate problem (under-coverage at the Curator/feed level).

5. **A TP after Cap still costs > €3.** Means the cascade is starting somewhere else (likely Researcher merging in many additional sources, or per-source actor counts being very high), and cap at a different layer is needed.

6. **Two weeks of production operation, no specific issue.** Default re-evaluation cadence. Take a snapshot of `source_balance` and `coverage_gaps_validated` across all TPs produced, look for patterns.

## References

- `TASK-SOURCE-CAP-2026-05-11.md` — implementation brief
- `TASK-FETCH-FEEDS-PUBLISHED-AT.md` — small follow-up to persist `published_at` and activate recency-tiebreak
- `docs/handoffs/BASELINE-2026-05-11.md` — failure mode evidence
- `docs/handoffs/CURATOR-SMOKE-2026-05-11.md` — confirmation of structural behaviour
- `docs/AGENT-IO-MAP.md` §2.5 — current Stage I/O contract (will be updated to reflect cap)
- `BACKLOG-SOURCE-DIVERSITY-V2.md` (gitignored) — V2 direction
