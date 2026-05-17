# BACKLOG-WEEKLY-OUTLET-AUDIT

## Status

Backlog. To be initialized approximately one week after the new pipeline begins regular live
runs. Not yet a TASK.

## Why

Independent Wire's bias-transparency premise depends on accurate outlet classification. The
render layer currently shows `not yet categorized` for ~10 of 13 outlets per TP — those are
researcher-hydrated third-party citations that don't appear in `config/sources.json` (which has
`tier`, `editorial_independence`, `bias_note` populated only for direct feeds).

Plus: 2 outlets in tp-001 (Yeni Şafak, n-tv) are missing from `outlet_registry.json` entirely,
so even Country/Type fall back to nothing.

Both gaps shrink monotonically over time only if we have a regular auditing loop. Without one,
the "not yet categorized" share is a permanent feature of every TP — undermining the
transparency promise.

Tier classification is also unsolved: the field exists in `sources.json` (values 1-4), but
without an editorial workstream defining what each tier means and applying it to all 67 active
feeds, the field is decorative. Tier visualization in the render is currently deferred for
exactly this reason.

The weekly outlet audit folds all three problems into one routine.

## Proposed mechanism

A small standalone script (NOT a pipeline stage — runs separately, on a weekly cadence). The
script:

1. Scans all TP JSONs published in the trailing 7 days under `output/{date}/`
2. Collects distinct outlets from every `final_sources[].outlet`
3. Compares against:
   - `config/sources.json` — has `editorial_independence`, `tier`, `bias_note`?
   - `config/outlet_registry.json` — has `outlet`, `country`, `language`, `type`?
4. Produces a structured audit report with three sections:
   - **Coverage gaps**: outlets present in the week's TPs but missing from
     `outlet_registry.json` (need new registry entries)
   - **Classification gaps**: outlets present in `outlet_registry.json` but with no
     `editorial_independence` / `tier` / `bias_note` in `sources.json` (need editorial
     classification — tier 1-4 + independence label + bias note)
   - **Frequency tally**: how often each gap appeared across the week's TPs (prioritization
     signal — frequent third-party citations matter more than one-off mentions)

Architect reviews the report, edits `outlet_registry.json` and/or `sources.json` manually,
commits.

Output of one weekly cycle: registry growth + classification growth, both visible in the next
week's TPs as fewer "not yet categorized" labels.

## Likely script location

`scripts/audit_outlets.py` (~100-150 lines). Standalone. No pipeline integration. Runs from CLI
with optional `--days N` parameter (default 7).

## Initialization timing

Not before the new pipeline has run live for ~7 days. With less than that, the audit input is
too thin to be meaningful. Architect kicks this off as a TASK once enough live TPs exist to
make the audit material substantial.

## Tier classification — caveat

Initializing this audit doesn't define the tier vocabulary itself. Tier 1-4 needs editorial
criteria written first (probably as a `docs/EDITORIAL-TIER-CRITERIA.md` document). The audit
script can flag missing tier values, but Architect needs to decide what each tier means before
filling them in.

This editorial work is the gating step. It can be done in parallel with the script itself, but
the script is useless until the criteria exist.

## Related future work

- `outlet_aliases.json` (mentioned during Task E discussion) — for outlets we want to recognize
  but never feed directly (e.g. "Channel 14" appearing as a third-party citation in many MENA
  reports). Audit script could surface these as a third-tier suggestion list.
- F2 actor-name alias dedup — separate problem domain (per-actor, not per-outlet), but follows
  similar editorial-pflege pattern.
