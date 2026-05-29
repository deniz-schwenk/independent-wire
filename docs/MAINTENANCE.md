# Independent Wire — Maintenance Routines

Operational routines that keep the published Topic Packages accurate over time.
These are **not** pipeline stages — they run separately, on a human cadence, and
their output is Architect-reviewed edits to config, committed by hand.

One routine is documented here: the weekly outlet-registry audit. Two adjacent
concerns are tracked as backlog, not yet routines:
`docs/internal/BACKLOG-EDITORIAL-TIER-CRITERIA.md` and
`docs/internal/BACKLOG-OUTLET-ALIASES.md`.

---

## Weekly Outlet-Registry Audit

### Why

Independent Wire's bias-transparency premise depends on accurate outlet
classification. Every source in a Topic Package carries descriptive
(`country` / `language` / `type`) and editorial (`tier` /
`editorial_independence` / `bias_note`) metadata, attached deterministically by
`propagate_outlet_metadata` via hostname lookup against
`config/outlet_registry.json` — the single source of truth (`config/sources.json`
is feed mechanics only).

Researcher-hydrated third-party citations keep introducing hostnames not yet in
the registry. Until classified, those sources render "not classified yet" —
honest, but a permanent dent in the transparency promise if the share never
shrinks. This audit is the loop that shrinks it.

### Cadence

After the pipeline has accumulated new live runs — in practice weekly, or after
any run that brings a batch of new long-tail citations. Not on a fixed clock; on
accumulated new material.

### The routine (five steps)

1. **Audit.** Run the read-only survey:

   ```
   python3 scripts/audit_outlet_registry.py
   ```

   It walks every
   `output/<date>/_state/run-*/topic_buses.propagate_outlet_metadata.*.json`
   snapshot, runs the real `lookup_outlet` from `src/outlet_registry.py` against
   each source URL, and lists the unmatched hostnames sorted by occurrence
   frequency, with the date set each appeared in. Writes nothing.

2. **Classify.** For each unmatched hostname, **web-search first** — never from
   model memory, not even for "obvious" outlets. Propose all six fields
   (`country` / `language` / `type` / `tier` / `editorial_independence` /
   `bias_note`) with at least one cited URL backing the classification. The
   canonical vocabulary for `type` / `editorial_independence` / `tier` is the
   `_schema` block at the top of `config/outlet_registry.json` — stay inside the
   declared sets.

3. **Sibling-propagate.** Before writing, scan the registry for other hostnames
   sharing the same outlet identity (matching `outlet` field) — Al Jazeera
   EN/AR, BBC variants, Euronews subdomains. Apply the same classification,
   modulo per-host `language`. Deterministic, applied after classification, not
   during.

4. **Verify.** Three gates, all must pass:
   - **Ideological-language regex** returns zero hits across all `bias_note`
     values. `bias_note` describes ownership, funding source, charter, regional
     focus — structural facts. Never "left-leaning", "right-wing", "pro-X". This
     is load-bearing for project credibility, not a style preference. The strict
     gate also surfaces historical violations set before it existed.
   - **Vocabulary discipline** — every `type` / `editorial_independence` /
     `tier` value sits inside the `_schema`-declared set.
   - **Full test suite green.**

5. **Defer honestly.** Where ownership or charter cannot be confirmed, set the
   outlet to `needs_manual_check`. It renders "not classified yet" — that is the
   correct fallback. **Never guess.**

Output of one cycle: registry growth + classification growth, both visible in
the next week's TPs as fewer "not classified yet" labels. Architect reviews,
edits `config/outlet_registry.json` by hand, commits.

### Current deferrals

Five outlets are intentionally `needs_manual_check` and render "not classified
yet" honestly. Two of them are not news outlets at all (surfaced as Researcher
citations, not feeds):

- `elmarq.fr` — ownership/charter unconfirmed
- `kanuniesasi.com` — ownership/charter unconfirmed
- `vista.ir` — ownership/charter unconfirmed
- `perkinslawoffices.com` — Miami law firm, not a news outlet
- `timewell.jp` — Japanese software company, not a news outlet

The two non-news domains raise an open editorial question — should the Researcher
prompt skip non-news domains, or is that its own workstream? Tracked, not yet
decided.

### What this routine does NOT cover

- **Tier vocabulary definition.** The `tier` field exists (1–4) but the criteria
  for what each tier *means* are unwritten. The audit can flag a missing `tier`;
  filling it consistently requires the criteria first. See
  `docs/internal/BACKLOG-EDITORIAL-TIER-CRITERIA.md`.
- **Outlet aliasing.** Recognising outlets we never feed directly (e.g.
  "Channel 14" appearing only as a third-party citation) is a separate mechanism.
  See `docs/internal/BACKLOG-OUTLET-ALIASES.md`.
