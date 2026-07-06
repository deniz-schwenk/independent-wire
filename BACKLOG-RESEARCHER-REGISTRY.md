# BACKLOG — Researcher arm: replace Sonar-Pro search with a curated public-endpoint registry

Status: DIAGNOSED + decision path agreed (Deniz + Architect, 2026-07-05). Not activated.
Prerequisite in flight: TASK-SEARCH-COST-LOGGING (cost visibility first).

## The two diagnoses this consolidates
- Prior session (structural): the entire merge seam (`merge_sources`, `renumber_sources`,
  `normalize_pre_research`, the hydrate-rsrc/research-rsrc ID rename map) exists only to
  unify two source paths; proposal was to delete the researcher arm and collapse the seam.
- This session (measured, 2026-07-03..05 published TPs): the researcher contributes 41-44
  of ~80-95 published sources per day (~half), including languages absent from the feed
  pool entirely (fa, uk, he, ko, ur, hi, pl, el) and topic-specific primary sources
  (amnesty.org, government sites, regional agencies). Deleting it outright degrades the
  product's core promise (gaps, who-speaks/who-is-silent).

## Why the current search must go anyway (all three verified 2026-07-05)
1. **Invisible cost:** `researcher_search` (perplexity/sonar-pro via OpenRouter) logs no
   cost/tokens. Real arm cost ≈ $1.75/day (~half the daily bill), not the $0.35 the stage
   log suggested.
2. **Undated majority:** 26-28 of ~42 researcher sources/day carry no `estimated_date` —
   unverifiable freshness in a daily-news product; 3-8/day are older than 7 days.
3. **Values breach:** Sonar Pro is an UNDOCUMENTED commercial dependency and returns
   sources readers cannot open (paywalled content via Perplexity's licensing deals,
   e.g. Reuters) — violates "commercial dependencies only documented and justified" and
   "source citations are part of the product".

## The middle path (agreed): keep the arm, replace the search
The swap-in point already exists: `src/tools/web_search.py` has a provider abstraction
(`IW_SEARCH_PROVIDER`, provider map). Build a `registry` backend beside `perplexity`:

1. **Registry** — curated, publicly accessible endpoints (RSS/APIs): institutions
   (UN, NGOs, governments, central banks), regional outlets, agencies. Per entry:
   endpoint, language, country/region, topic/beat tags, `access: public`, outlet hostname
   (outlet_registry-compatible). Seed: the validated 83-candidate research list +
   institutional endpoints. Growth path: the community source catalog (Vision Phase 2).

   **Design refinement (Deniz, 2026-07-05): ONE catalog, two access patterns.** The
   registry is not a second catalog beside `config/sources.json` — it is the same source
   catalog with an access flag per entry: `daily` (fetched unconditionally, feeds the
   Curator = discovery; cost scales with catalog size) vs `on_demand` (fetched only when
   a selected topic matches, feeds the researcher = retrieval; cost scales with topic
   count, 3/day). Same fetch machinery, same outlet metadata, one community maintenance
   path. Promotion `on_demand` -> `daily` becomes data-driven: an entry repeatedly pulled
   by topics has empirically earned a daily slot (config flip, logged). The
   Collector-as-prefilter roadmap item covers the case where the daily slice itself
   grows past ~200 feeds.

2. **Deterministic topic matching** — Python preselects registry entries by
   region/language/tags from `editor_selected_topic`; fetch via the existing
   encoding-safe `fetch_feeds` machinery.
3. **LLM-free relevance ranking** — score fetched items against the topic with the
   pinned multilingual embedder (existing clustering infra), take top-N.
4. **Assemble stage unchanged** — receives full, dated articles instead of undated
   Sonar snippets (strictly better input).

Expected effect: search cost ~$1.4/day → ~$0; 100% dated sources; 100% publicly
accessible; commercial search dependency eliminated. Cost: no open-web discovery —
only what the registry knows. Mitigation: targeted registry growth in exactly the
regions/languages the Sonar arm was finding (fa, uk, he, ko, ...).

## Migration path (reversible; each phase its own gate)
- **Phase A — build + shadow:** registry v1 + `registry` backend; run in shadow against
  Sonar on the same topics for several days (read-only). Compare: sources/topic,
  language coverage, datedness, overlap with what Sonar found.
- **Phase B — gate:** decide on numbers. Draft thresholds: registry reaches ≥70% of the
  Sonar arm's per-topic source count AND covers the topic's primary region/language in
  ≥90% of topics. (Tune at gate time — these are starting points, not dogma.)
- **Phase C — flip:** `IW_SEARCH_PROVIDER=registry`; Sonar code stays for rollback.
  Document the dependency removal in ARCHITECTURE.md + ROADMAP.
- **If the gate fails:** the prior session's stage-1 (delete arm + collapse merge seam)
  becomes the honest next step — with real numbers to justify it.

## Related but independent: source-ID unification
Regardless of the outcome above, both assemblers should draw canonical `src-NNN` IDs from
one shared deterministic Python counter, making `merge_sources` trivial concatenation and
retiring `renumber_sources` + the ID rename map + `normalize_pre_research` write-back
(~80% of the seam complexity) while keeping both source paths. This is a breaking schema
event (bus-as-contract) — own workstream entry, sequenced separately, not a 1-3h task.

## Not before
- TASK-SEARCH-COST-LOGGING landed (visibility first).
- The 2026-07 landing queue is clear (GLM swap validated, Batch-2, loud-logging, legend).
- MADLAD shadow verdict read (same shadow-then-gate pattern; don't run two
  shadow-migrations of the sourcing layer at once).
