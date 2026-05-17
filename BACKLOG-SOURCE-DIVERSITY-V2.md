# BACKLOG-SOURCE-DIVERSITY-V2

**Status:** architect-level sketch, not yet briefed.
**Triggered by:** `docs/SOURCE-CAP.md` V1 known limitations.
**Activation criteria:** see `docs/SOURCE-CAP.md` §Re-evaluation triggers.

## Problem with V1

V1 (outlet round-robin, max 3 per outlet, cap 40) solves the cost-cascade and is decent at outlet-diversity. It does not actively diversify across:

- Country (emergent from outlet pool composition only)
- Language (same)
- Editorial tier / state-vs-independent (selector ignores `tier` and `editorial_independence` metadata in `config/outlet_registry.json`)
- Substantive position (positions only visible post-Perspective; V1 can't see them)

The 72-outlet source pool is itself geographically skewed (Vision Paper acknowledges: "Hebrew-language media is more accessible via RSS than Lebanese or Palestinian sources"). V1 selection inherits this skew.

## V2 direction candidates (not yet a decision)

### Option A: Multi-key stratified round-robin

Extend the selector from single-key (outlet) to a priority chain:

1. First pass: one URL per outlet
2. Second pass: one URL per (outlet, country) pair not yet represented
3. Third pass: one URL per (outlet, language) pair not yet represented
4. Fourth pass: fill remaining cap slots with hard `max_per_outlet=3` ceiling

Effort: ~2-3h plus unit tests. Risk: low. Improvement: marginal-to-moderate — depends heavily on the candidate pool.

### Option B: Tier-aware quotas

Set explicit minima per `tier` class:

- ≥ 30% from tier-1 outlets (peer-reviewed, independent journalism)
- ≤ 20% from tier-3 outlets (state media)
- Rest from tier-2

Combined with round-robin within each quota bucket. Effort: ~3-4h. Risk: medium (tier definitions in `config/outlet_registry.json` may not be calibrated for this use). Improvement: addresses a specific failure mode (state-media-dominant clusters), but may exacerbate Western-tier-1 bias if not paired with country-balance.

### Option C: Cluster-internal sub-clustering

Before capping, run a lightweight sub-clustering on the candidate findings (e.g., embedding-based or LLM-driven topic decomposition). Identify sub-topics (e.g., for "US-Iran": "Trump's rejection statement", "Hormuz oil prices", "Hezbollah warnings", "Houthi mediation"). Cap per sub-cluster, not per outlet.

Effort: ~8-12h (new LLM stage or embedding pipeline). Risk: high (adds cost, adds latency, calibration unclear). Improvement: addresses substantive coverage rather than outlet shape — closer to the project's actual goal. Maybe the right long-term direction.

### Option D: Embedding-based diverse subset selection

Compute embeddings for all candidates, select a subset of `cap` that maximises minimum pairwise distance (DPP — Determinantal Point Processes — or greedy farthest-point sampling). Skips structural metadata entirely; relies on semantic content.

Effort: ~6-8h, requires an embedding model (could be small/local). Risk: medium-high (calibration, validation, embedding-model choice). Improvement: pure semantic diversity, ignores outlet/country bias of the source pool entirely.

### Option E: Position-aware feedback loop

Run a cheap "position-detection" pass on candidates (small LLM on titles + summaries only, not full hydration). Identify N distinct positions. Select a covering subset of candidates that represents each position with at least one source. Then cap any over-represented positions.

Effort: ~6-10h, new lightweight LLM stage. Risk: medium. Improvement: directly addresses position-diversity rather than proxies (outlet, country). Conceptually closer to what the project is about — the question "how is this being reported" — but adds a cost/latency layer.

## Decision criteria for choosing between options

When activating this backlog:

- **If failure mode is mostly geographic monotony** → Option A is sufficient, cheapest.
- **If failure mode is tier-skew (too much state media / too much aggregator)** → Option B, possibly combined with A.
- **If failure mode is "missed substantive angles within a single hot story"** → Option C or E.
- **If failure mode is harder to characterise than outlet/country/tier categories** → Option D worth a try.

In practice, V2 is likely a combination, not a single option. Most likely starting point: A (cheap, low-risk), with the option to layer C or E if A doesn't move the metrics enough.

## Not in scope for V2

- Re-thinking the 72-source feed list. That is its own multi-week workstream, acknowledged in Vision Paper §Phase 2. Source diversification at the Collector level is a different problem from source selection at the Curator/Hydration level.
- Changing Curator's clustering behaviour. Curator over-clustering is the *trigger* for this work, but the architectural fix lives downstream at the URL-attachment layer where we still have outlet metadata available.

## Implementation cadence (when activated)

A V2 should:

1. Run unchanged against the V1 cap as control. Capture baseline `source_balance` distributions over 3-5 TPs.
2. Implement the chosen option as additive to V1, not replacement.
3. Run again, measure delta in `source_balance` country/language counts and `coverage_gaps_validated`.
4. Promote to default only if measurable improvement on the failure-mode metric without cost regression beyond +20%.

V2 is not a Big Bang. Incremental, measured, reversible.
