# Full Code Review — 2026-07-02

**Scope:** all production Python under `src/` and the operational scripts under `scripts/` (run/render/publish/fetch/translate/monitor + shell runners), config consistency, and the test suite — ~34.5k lines. One-off eval/sweep/smoke/audit research scripts and prompt *content* under `agents/` were skimmed for imports only, not deep-reviewed.

**Method:** nine parallel subsystem reviews (core abstractions, runner, agent stages, topic stages, clustering, render, publish/feeds, tools/hydration, translation), each reading its files completely and verifying findings against callers, bus schema, tests, and live on-disk data (all 111 TP JSONs, live `site/` pages, real `_state/` snapshots). All high-severity findings were independently re-verified against the source before inclusion. Two findings (H6, H9) were reproduced by execution.

**Test baseline:** `uv run --extra dev pytest` → **3 failed, 736 passed, 8 skipped** (failures analyzed in §Tests below; all are test-hermeticity issues, not product regressions).

---

## Executive summary

The architecture does most of what CLAUDE.md promises: deterministic merging keyed on Python-assigned IDs, disciplined HTML escaping, schema-constrained decoding with layered fallback parsing, honest token accounting, a correctly implemented read-only-proxy mechanism, and a solid deterministic clustering core (thresholds, caps, tie-breaks, and the fastembed singleton all check out). No delta-semantics (`"field" in delta`) violations and no LLM-delegated counting were found anywhere.

The defects cluster at **seams**, in four recurring patterns:

1. **Valid-empty LLM output vs. postcondition gates.** Four wrapper stages can legitimately emit empty output ("no missing voices", "no bias found", "no divergences", "all fetches failed"), but their bus slots never got `optional_write` — so a *correct* answer kills the whole topic package after most of the LLM spend (H1–H3, M-AS4).
2. **Resume/publish state fragility.** The resume path silently falls back to wrong-stage state (H4); a publish crash can permanently brick the daily launchd runner via a dirty worktree (H7); one corrupt historical TP JSON aborts the whole publish (H8); snapshots and outputs are written non-atomically in a crash-recovery subsystem.
3. **Decode-before-parse encoding bugs** that silently mangle exactly the non-Latin streams just onboarded (H6, M-P4), plus size-only change detection that can pin a stale/wrong report on the public site forever (M-P3).
4. **Documented invariants that aren't enforced.** The single-writer/slot-ownership rule CLAUDE.md calls "structurally enforced" is not checked anywhere (H5); an `internal`-visibility slot ships in every public TP (H10).

Rough totals: **10 high**, ~35 medium, ~50 low findings. Highs first.

---

## High-severity findings

### H1. Empty `missing_positions` from the Perspective agent kills the topic
`src/agent_stages.py:1348,1387-1396` + `src/bus.py:717` — `PerspectiveStage` declares `writes = ("perspective_clusters", "perspective_missing_positions")`, but `perspective_missing_positions` lacks `optional_write=True`. The comment at `bus.py:693-694` says the flag "covers the case where the agent produced no clusters (empty list passes **both writes** through)" — but it was only applied to `perspective_clusters`. A well-covered topic where the agent correctly finds no missing voices fails `validate_postconditions` (`src/stage.py:271-275`) and the topic package is lost. *(Verified directly.)*

### H2. Zero bias findings on a clean article kills the topic
`src/agent_stages.py:1661,1694-1699` + `src/bus.py:805` — `bias_language_findings` has no `optional_write`, unlike the QA slots directly above it (which got the flag with the rationale "on clean runs the V2 QA prompt produces empty arrays"). A genuinely neutral article → `findings: []` (schema-valid) → `StagePostconditionError` at the second-to-last agent stage, destroying the topic after nearly all LLM spend. *(Verified directly.)*

### H3. HydrationPhase1's graceful zero-fetch path triggers its own postcondition crash
`src/agent_stages.py:2186-2193` + `src/bus.py:515` — when every hydration fetch failed, the stage deliberately returns `hydration_phase1_analyses: []` as a graceful early-out, but the slot has neither `optional_write` nor `mirrors_from`, so the runner immediately fails the topic with a misleading "promised to write" error. All-sources-paywalled/unreachable is a reachable production input (failed fetches are recorded as entries, so the upstream fetch stage's own postcondition passes).

### H4. Resume silently loads wrong-stage state when a per-topic snapshot is missing
`src/runner/state.py:184-193` (caller `src/runner/runner.py:362-370`) — if *any* per-topic snapshot for the requested prior stage is missing, the loader silently substitutes `topic_buses.json`, a mixed-progress "latest" collection at arbitrary stages. No log line. The docstring's justification is dead code (the only caller invokes it exclusively when `from_index_topic > 0`; the `== 0` case loads the collection directly). Concrete: prior run crashed with topic 2 failed at `PerspectiveStage`; resume `--from WriterStage` runs Writer on a bus with an empty `perspective_clusters` slot, and re-runs completed topics from the wrong state. Preconditions don't check slot emptiness, so nothing catches it. *(Verified directly.)*

### H5. The single-writer/slot-ownership invariant is not actually enforced
`src/stage.py:191-211,260-275` — CLAUDE.md claims "a stage that writes a slot it doesn't own fails precondition validation." Nothing checks that. `validate_preconditions` only verifies declared reads exist as fields; `validate_postconditions` only verifies *declared* writes are non-empty. A stage that writes an undeclared slot (or another stage's slot) passes both validators silently; no writer-uniqueness test exists. Today the discipline is upheld by convention only — and there is already contract drift (see M-AS9, M-TS7).

### H6. Hydration silently mojibakes non-UTF-8 articles whose charset is declared only in `<meta>`
`src/hydration.py:183-194,405,432` — the decode chain is header-charset → utf-8 → **latin-1**, which decodes *anything* without error; there is no HTML meta-charset sniff, and passing a pre-decoded `str` to `trafilatura.extract` bypasses trafilatura's own bytes-level encoding detection. Reproduced: windows-1256 Arabic → `'ÇáÃÎÈÇÑ...'`; TIS-620 Thai → garbage. Mojibake still splits into ≥50 "words", so the entry classifies `success` and corrupted text flows into the Aggregator. This hits exactly the ar/th feeds added in batch 1. *(Reproduced by execution.)*

### H7. A publish crash can permanently brick the daily runner
`scripts/daily_run.sh:34` + `scripts/publish.py:93,1164-1196` — `daily_run.sh` starts with `git pull --rebase origin main` (no autostash, no recovery), and `publish.py` has several paths that mutate tracked `site/` files and then abort non-zero (un-guarded `json.loads` per TP; `remove_pre_cutoff_reports` unlinks tracked HTML then can `sys.exit(1)`). One crash mid-loop → dirty worktree → every subsequent morning's pull fails at step 1 until a human intervenes. `translate_de_run.sh`'s swallowed rebase failure (`git pull --rebase || true`, line 57) can leave `.git/rebase-merge` behind with the same bricking effect.

### H8. One malformed historical TP JSON aborts the entire daily publish
`scripts/publish.py:1180,163-171` — `main()` re-reads *every* TP JSON in `output/` history each run with zero per-file error tolerance (`json.loads(...)`, bare `tp["id"]`/`tp["metadata"]["date"]`). A truncated file from any crashed run (TP writes are non-atomic) blocks publication of *today's* content forever until manually deleted — and per H7 can brick the runner. Render failures in the same loop *are* tolerated, so per-file tolerance was clearly intended.

### H9. `x_search` tool returns an unawaited-coroutine repr instead of results
`src/tools/web_search.py:349` — the handler is a plain lambda calling the async `_search_grok_x` without await; `Tool.execute` treats it as sync and `str()`s the coroutine. Any agent granted `x_search` receives `<coroutine object ...>` as its result. Latent (no agent currently wired) but the tool is registered. Fix is `handler=_search_grok_x`. *(Reproduced by execution; verified directly.)*

### H10. `perspective_missing_positions` is `visibility="internal"` but ships in every public TP
`src/bus.py:717` vs `src/render.py:172,338` — the slot is internal-tagged yet rendered into `tp` and `mcp` output (`perspectives.missing_positions`, confirmed populated in production TPs). Render's coverage check only detects under-inclusion, never over-inclusion, so the visibility contract is structurally unenforced in this direction. Either the annotation or the render is wrong — as shipped, the "render is pure selection filtered by visibility" principle is violated in every published dossier. Related: `_follow_up_block` (`src/render.py:98-112`) does a previous-headline lookup against internal-visibility `previous_coverage` that its own docstring calls an anti-pattern. *(Verified directly.)*

### H11. One hard-failed TP suppresses the whole day's German publish
`scripts/translate_de_run.sh:49` + `scripts/translate_de.py:249` — `translate_de.py` returns 1 if *any* TP hard-fails, and the wrapper gates the entire render+publish step on that exit code. Successfully translated `de/*.de.json` files sit on disk unpublished; the German site silently misses the day. This defeats the documented per-TP failure isolation ("hard-failed TP is left untranslated, surfaced in the summary" — per-TP, not day-wide). *(Verified directly.)*

### H12. `file_ops` tools have no sandbox root (latent)
`src/tools/file_ops.py:11-38` — `read_file`/`write_file` pass agent-supplied paths straight to `Path(...)` with no confinement; `write_file` even does `mkdir(parents=True)`. This pipeline feeds untrusted web/RSS content into agent contexts; a prompt-injected agent with these tools could read `.env` (API key) or write into `agents/*/SYSTEM.md`. Currently unexercised (every production agent has `tools=[]`), but both tools sit in the default registry — any future allow-list addition arms this instantly.

---

## Medium-severity findings

### Runner / CLI (`src/runner/`, `scripts/run.py`)

- **M-R1. `--reuse` force-gate contradicts the documented workflow.** `scripts/run.py:404-437` — the overwrite gate aborts whenever any `run-{date}-*` dir exists, but a valid `--reuse` *requires* prior state, so every CLAUDE.md-documented resume command exits 1 without `--force`. It also fires when nothing would be overwritten (`--reuse DATE` without `--from` mints a fresh run dir), and the exact-run-id form aborts on *any* run dir for the date. Separately, `_resolve_reuse` (:466-469) picks "latest" by mtime with no `run-` prefix filter — a stray dir inside `_state/` can be resolved as a run id.
- **M-R2. `--topic 0`/negative/out-of-range silently skips every topic.** `scripts/run.py:353-358` + `runner.py:385-389` — 1-based flag, no bounds validation; `--topic 0` matches nothing, all topics are "skipped", exit code 0 — after the run-stage LLM spend is already paid. The partial-run banner (`run.py:579`) uses truthiness, so `--topic 0` isn't even logged as partial.
- **M-R3. Filtered resume regresses shared state for untouched topics.** `runner.py:449-454,170-188,496-506` — `--from <stage> --topic N` rewrites `topic_buses.json` wholesale with the other topics at their Phase-B-loaded state (regressing their completed snapshots), and `FinalizeRunStage` clobbers the prior run's manifest, recording completed topics as `"skipped"`. A later resume that hits H4's fallback then consumes the regressed collection.
- **M-R4. Snapshots are not written atomically in a crash-recovery subsystem.** `src/runner/state.py:70-71,125,145,211-212` — truncate-and-write everywhere; SIGKILL/power-loss mid-write leaves unparseable JSON exactly where `--reuse` needs it. `topic_buses.json` (multi-MB, rewritten after every topic stage) has the widest window. Same pattern: `raw/*/feeds.json` (`fetch_feeds.py:219-223`) and `site/` outputs (`publish.py:1205-1218`).
- **M-R5. Failed topic-stage LLM cost never reaches the cost log.** `runner.py:397-406` — run-stage failures log agent metrics; topic-stage failures log `stage: "topic-{i}"` with no stage name, no `cost_usd`, no tokens. A paid Writer call whose stage then throws vanishes from `run_stage_log.jsonl`; the accumulated agent metrics are zeroed on the next topic.

### Agent stages (`src/agent_stages.py`)

- **M-AS1. Uncancelled `gather` siblings on chunk failure.** `:2202-2212` — a chunk raising `_AggregatorValidationError` propagates without cancelling sibling chunk coroutines: they keep making billed OpenRouter calls for a topic already marked failed and run concurrently with the next topic's stages. Same pattern at `src/hydration.py:539` and `scripts/translate_de.py:213` (there it also cancels *successful* sibling TP translations and skips the summary).
- **M-AS2. QA corrections claimed but silently not applied.** `:1624-1632` — `article` is deliberately not in `QA_ANALYZE_SCHEMA.required`; when the model emits `correction_needed: true` but omits the article, nothing is written, the mirror publishes the *uncorrected* article, and the TP still carries corrections claiming otherwise. No warning logged. Interacts with M-TS2.
- **M-AS3. Editor merge joins on LLM-echoed titles.** `:390-435,1086-1091` — `_attach_raw_data_from_curated` joins by echoed title, first-wins with no ambiguity detection on the exact-title path (the slug path has it); duplicate discovered titles silently give topic 2 topic 1's sources. Also no count reconciliation: an LLM dropping or duplicating an assignment is undetected. This is the file's one join keyed on pass-through data instead of a Python-assigned ID.
- **M-AS4. Legitimately-empty Phase-2 corpus crashes the topic.** `:2279-2283` + `bus.py:526-529` — schemas.py documents "both arrays may legitimately be empty", but the slot has no `optional_write` and `is_empty()` treats an all-empty sub-model as empty. Same class as H1–H3.
- **M-AS5. One hallucinated actor `type` aborts the topic with no retry.** `:1818-1826` — Rule 6 raises on the first out-of-enum `type`, bypassing both retry layers; yet the schema constrains `evidence_type` with an enum while leaving `type` a plain string. Either enum-constrain it at decode time or drop-and-log the single actor.

### Topic stages (`src/stages/topic_stages.py`)

- **M-TS1. Published cluster counts go stale after pruning.** `:1656-1670` (set at `:959-962`) — `cleanup_stale_references` filters `actor_ids`/`source_ids`/tier sub-lists but never recomputes `n_actors`/`n_sources`, so published TPs can carry counts contradicting the lists next to them. Violates "counting is Python's job" — the Python counts are wrong at publish time. *(Verified directly.)*
- **M-TS2. Transparency card gates `article_original` on the wrong predicate.** `:1768-1771` — preservation keys on `qa_problems_found` non-empty, but the QA stage writes the corrected article on `any(correction_needed)`. `problems_found: []` + a real correction ⇒ corrected article published with `article_original = None` — the transparency trail silently loses the original. Should reuse the same predicate (or diff the two articles).
- **M-TS3. URL date extraction drops the day for URLs ending in the date.** `:1968-1982` and its byte-identical twin `src/agent_stages.py:1145-1165` — the full-date pattern requires a trailing character (no `$`), so `.../2026/07/02` falls through to the year-month pattern → `2026-07-01`. The twin directly sets `estimated_date` in published `final_sources`. Related: the compact pattern (also `src/hydration.py:218`) matches 8-digit numeric article IDs as dates. Three copies of this helper need one fix. *(Verified directly.)*

### Clustering / run stages (`src/stages/run_stages.py`, `src/curator_metrics.py`)

- **M-C1. Hydration-URL attachment resolves finding indices against a re-readable file, not the bus.** `run_stages.py:597-617,638-640` — `finding-NNN` indices were minted against `run_bus.curator_findings`, but this stage re-reads `raw/{date}/feeds.json` from disk and indexes *that*. Re-run `fetch_feeds.py` between the original run and a resume and every index silently resolves to a different article — wrong URLs/outlets/countries attached, no error. The stage also doesn't declare `curator_findings` in `reads`.
- **M-C2. The recency tie-break shipped as "activated" is dead code.** `run_stages.py:461-471` vs `:524-534` — `_build_hydration_urls_for_cluster` never copies `published_at` into candidates, so `select_diverse_hydration_urls`' dated/undated partition always lands everything in `undated` and the outlet cap picks by input order, not newest. Commit `30775aa` claims activation; the docstring claims it too. (Bonus: the sort compares timestamps as raw strings, so mixed UTC offsets would order wrongly once the field does arrive.)
- **M-C3. Orphan metric undercounts under multi-assignment.** `curator_metrics.py:204-205,219-220` — `orphan = len(findings) − sum(cluster_sizes)` double-counts findings assigned to multiple topics (`PER_FINDING_CAP=3`); the `max(0, ...)` clamp hides the arithmetic going negative. Correct is `len(findings) − |union(source_ids)|`. The curator drift monitor consumes this, so the signal is biased low.
- **M-C4. `coherence_calibrate.py` is unrunnable; `coherence.py.__all__` exports removed names.** `src/stages/coherence.py:200-210`, `scripts/coherence_calibrate.py:35-42` — Brief 5 cutover leftovers: the calibration tool dies with ImportError at startup.
- **M-C5. `_scan_previous_coverage` is order-unstable within a date.** `run_stages.py:180,192,213` — final sort keys only on date; same-day TPs stay in filesystem order, which feeds the Editor's LLM context — a determinism violation. Fix: tie-break on `tp_id`.

### Publish / feeds (`scripts/publish.py`, `scripts/fetch_feeds.py`)

- **M-P1. (rolled into H7/H8.)**
- **M-P2. `translate_de_run.sh` swallows rebase/push failures and exits 0.** `:55-58` — `git pull --rebase || true` then unguarded push under `set -uo pipefail` (no `-e`); a rejected push silently unpublishes German for the day, and a conflicted rebase leaves `.git/rebase-merge` (→ H7 brick).
- **M-P3. Size-only change detection pins stale reports on the public site.** `publish.py:1189` — re-rendered HTML is copied only if byte length differs; a QA re-run correcting "3 killed"→"4 killed" leaves the wrong version published forever with no git diff. Needs content hash or unconditional copy. *(Verified directly.)*
- **M-P4. `feedparser.parse(resp.text)` bypasses XML-prolog encoding detection.** `fetch_feeds.py:95` — httpx decodes with header charset or utf-8+replace; feeds declaring encoding only in the XML prolog are silently garbled (`bozo` stays false). Fix: `feedparser.parse(resp.content)`.
- **M-P5. Undated feed entries bypass the 24-hour cutoff daily.** `fetch_feeds.py:52-58,83` — entries with unparseable dates (common for locale-formatted pubDates in the new non-Latin streams) re-dump their full backlog into `feeds.json` every day; dedup is per-run only, so the stale items reach the Curator daily.
- **M-P6. German index declares the English homepage as canonical.** `publish.py:446,451` via `publish_de.py:173-176` — `site/de/index.html` gets `canonical`/`og:url` = `SITE_BASE/`; search engines will de-index the German edition as a duplicate. Same defect on DE report pages (`scripts/render.py:2385-2386,751,2401`: canonical, og:url, and Share button all point at the EN URL).
- **M-P7. Perplexity (the default production search provider) has no timeout.** `src/tools/web_search.py:39-61` — every other provider passes 10–30s; the default inherits the openai SDK's 600s×3 attempts, and the researcher awaits queries sequentially — one stalled connection can hang a topic ~30 min. The per-call `AsyncOpenAI` client is also never closed.

### Translation (`src/translate/`, `scripts/translate_de.py`)

- **M-T1. Garbage-output providers trigger a several-hundred-call retry storm.** `transport.py:73-76,98-99,188` + `run.py:56-72` — the TransportError docstring lists "unparseable/empty response" as whole-TP-failing, but neither transport raises; every item then walks the full 8-rung temperature ladder per item (1 + 8×8 calls per block batch, each with a 600s Ollama timeout or billed tokens) before failover.
- **M-T2. Stale loader script can resurrect the retired double-run LaunchAgent.** `scripts/load_translate_de.sh` — still bootstraps the 07:30 plist the chain migration retired; two concurrent processes race the unlocked pending-entities read-modify-write and double bill. The script also lacks `-e` and always exits 0.
- **M-T3. No staleness binding between `de.json` and its source TP.** `translate_de.py:137-160` + `publish_de.py:43-97` — splice paths are positional (`divergences[3]`, `body#p7`) and only a source *path* is recorded. A `--reuse` re-run that reorders divergences or changes paragraph count makes the next publish overlay old German text onto the wrong elements — silent cross-item corruption. Needs a content hash echo.
- **M-T4. One corrupt TP JSON kills the whole day's translation run.** `translate_de.py:90,213` — `json.loads` outside the try block + `gather` without `return_exceptions` cancels in-flight sibling TPs and skips the summary.
- **M-T5. Retry asymmetry burns the free provider on any transient blip.** `transport.py:92,156-165,217-228` — Ollama gets zero retries (one connection reset → whole TP restarts on billed transport); billed transport retries only `APIStatusError`, so timeouts/connection errors also burn a provider immediately. Same taxonomy gap as the core agent (M-CORE1).
- **M-T6. Empty segments are sent to NLLB and its hallucinations cached permanently.** `translate_sidecar.py:449-451,481-485,517-521` — the skip guard is only both-empty; a title-only finding sends `""` to NLLB (documented hallucination case), and the garbage is cached by content key and embedded for clustering, flagged `translated: True`.

### Core (`src/agent.py`)

- **M-CORE1. Retry taxonomy: network faults never retried; status faults retried 12×.** `agent.py:394-430,208` — `_call_with_retry` catches only `APIStatusError`/`JSONDecodeError`; `APITimeoutError`/`APIConnectionError` propagate raw (the designed exponential backoff never engages; `AgentTimeoutError` at :97 is defined but raised nowhere). Conversely 429/5xx get the SDK's hidden 2 internal retries *inside* each of 4 agent attempts → up to 12 physical requests per logical call.

### Render (`scripts/render.py`)

- **M-RND1. `javascript:` URLs render as clickable source links.** `:1944-1947` — `_esc(url)` prevents attribute breakout but not scheme abuse; `final_sources[]` includes researcher-hydrated third-party citations harvested from arbitrary web content. The one unvalidated external-href sink (everything else traced and found escaped).
- **M-RND2. German pages render English UI strings whose German labels already exist.** `:902` (word count, plus English `1,002` thousands separator), `:1809-1814` ("not yet categorized" ×6), `:2401,782` (Share/Copied), `:1237-1248` (bracket counts "1 actor" directly above cards saying "2 Akteure") — all confirmed on the live DE page; the label map carries every needed key. `L()`'s silent-English fallback masks these wiring gaps.
- **M-RND3. Every position card's "N actors" anchor is dead.** `:1113` vs `:1140` — links point to `#cluster-pc-NNN`, but card ids are `pc-NNN` and no JS handles the fragment; the docstring-promised filtering does nothing, on every published dossier in both languages.

---

## Low-severity / latent findings (abridged)

**Core (`src/agent.py`, `src/schemas.py`, `src/bus.py`)**
- `agent.py:362,387-389` — `setdefault("provider", ...)` can permanently mutate the shared `_extra_body_override` dict across calls (latent aliasing trap; live only for scripts passing a `provider` key).
- `agent.py:180` — unknown provider string silently falls back to OpenRouter *while disabling* the `require_parameters` gate that keeps schema enforcement honest.
- `agent.py:477,631-647` — fallback parse can return a top-level `list` as `structured`, violating the `dict | None` contract and crashing consumers with `AttributeError` instead of a clean failure.
- `agent.py:588` — return annotation says 5-tuple; every return is a 6-tuple.
- `agent.py:707-710,765-771` — cost under-reporting is silent when *some* (not all) responses omit `usage.cost`; tokens have the missing-usage caveat mechanism, cost does not.
- `schemas.py:362-366` — stale "Perspective-Sync" comment on `CONSOLIDATOR_SCHEMA` references removed `merge_perspective_deltas` and asserts null-semantics contradicting CLAUDE.md. Same drift at `bus.py:752-760`.
- `schemas.py:8-11` — the module's own strict-mode rule ("every property in `required`") is violated by the *deliberate* `QA_ANALYZE_SCHEMA.article` omission; the docstring, not the schema, needs updating (a well-meaning "fix" would silently break the mirror semantics — and a stricter provider could 400 every QA call post-Opus-4.7 migration).
- `bus.py:477,503` — `validate_assignment=True` is mostly bypassed because stages write via `model_copy(update=...)`; type errors surface one stage later, attributed to the wrong stage.

**Runner**
- `runner.py:358-361` — resuming from the *first* topic stage of a completed run loads fully-finished buses and re-runs over populated slots; the "post-Phase-B collection" the docstring promises is never written at that point.
- `stage_lists.py:96-104` — `IW_CLUSTER_TRANSLATE` env mismatch between original run and resume silently shifts which snapshot `--from pre_cluster_findings` resolves to.
- `runner.py:537-541` — pre-`init_run` failures are logged into the *reused* run's `run_stage_log.jsonl`.
- `runner.py:233-245` vs `:300-302` — `--from init_run` demands `--reuse`+`--force`, then ignores both and starts a fresh run.

**Agent stages**
- `:1591,2192,2313,2633` — four stages read/write undeclared slots (`QaAnalyzeStage` reads `perspective_missing_positions`; three stages write undeclared `*_n_attempts` slots). Harmless at runtime; the I/O contract AGENT-IO-MAP relies on is wrong.
- `:1290-1310` — non-dict `sources` entries are skipped for ID assignment but kept in the dossier (fallback-parse path only).
- `:1439-1485` — `FOLLOWUP.md` path is CWD-relative; silent degradation when run outside repo root.
- `:947-951` vs `:690-698` — with the translate sidecar ON, `AssignClustersStage` embeds raw findings while discovery embedded English-normalised text (opt-in eval list only).

**Topic stages**
- `:1593-1611` — cleanup applies the missing-`evidence_type` default per-actor while partition applies it per-quote; mixed typed/untyped actors lose their "reported" pool entry (internal-only slots today; latent trap).
- `:840-842,960` — cluster `source_ids` neither deduped nor sanitized; `n_sources` double-counts duplicates in published output.
- `:1680-1686` — `_filter_src_id_collection` conflates was-always-empty with became-empty and deletes legitimate QA divergences emitted with `source_ids: []`.
- `cluster_to_finding_assignments.py:158` — reads undeclared `curator_discovered_topics`.
- `_helpers.py:76` — `normalise_country` blanks "Bosnia and Herzegovina" / "Trinidad and Tobago" (the `\band\b` multi-country marker) → mis-bucketed as "unknown" in the published bias card for researcher-emitted countries.
- `_helpers.py:35-45` — `LANGUAGE_NAMES` missing `ne`/`zu`/`uz` (batch-1 feeds). Confirmed consequence-free in all 111 on-disk TPs today (codes pass through unchanged); only *name-form* input ("Nepali") would create duplicate `by_language` keys. Cosmetic until the flag flips.

**Clustering / metrics**
- `run_stages.py:796-799` — a schema-valid zero-topics Topic Discovery answer crashes at the postcondition gate (test blesses the stage behavior; the bus slot contradicts it). Same class as H1–H3.
- `run_stages.py:405-408` — `_hydration_tokens` is ASCII-only; non-Latin cluster titles get zero tokens → silent loss of the entire hydration benefit for that cluster.
- `curator_metrics.py:124-136` — `\b`-anchored on-topic regex never matches inflected Korean/Turkish forms → false off-topic drift alarms.
- `run_stages.py:104-119` — element-granularity mirror silently discards deltas whose `identity_key` matches nothing (a dropped agent correction deserves a WARNING).

**Publish / feeds / registry**
- `fetch_feeds.py:96-104,191-196` — "failed" counter conflates hard failures with quiet news days; outage monitoring can't tell them apart.
- `fetch_feeds.py:138` — GDELT stuffs the raw timestamp into `summary`, which flows into embeddings/clustering as content.
- `daily_run.sh:16` — `TODAY` uses local time; fetch/runner use UTC. Wrong-directory checks for runs between 00:00–02:00 CET.
- `publish.py:439` — `og:image` is an SVG; every major social platform refuses to render it.
- `publish_de.py:89-97,121,153-176` — partial translation splices publish silently truncated German articles; bare `g["id"]` crash path; no pre-cutoff pruning for `site/de/`.
- `src/outlet_registry.py:109-114` — parent-domain walk has no public-suffix awareness (probes `co.uk`); one future shared-host registry key (e.g. `substack.com`) would attach one outlet's bias metadata to every unrelated outlet under it.

**Render**
- `:1659-1662` vs `:1705` — the filter deliberately passes legacy non-dict bias findings that the loop then crashes on (`'str' has no attribute 'get'`).
- `:1770-1774` — outlet registry read uses locale-default encoding (only file in the module without `encoding="utf-8"`) and catches only `FileNotFoundError`.
- `:812-814` — meta-bar mixes post-prune Sources with pre-prune Languages counts (three mutually inconsistent figures on one page).
- `:81-114` — `_detect_lang` labels all Arabic script `fa`, all Cyrillic `ru` (Ukrainian quotes tagged Russian is an editorial-credibility hazard); Hebrew/Thai/Devanagari unhandled, no `dir="rtl"` for Hebrew.
- `:806` — LLM-emitted `follow_up_to` interpolated raw into an HTML comment (`-->` breaks out); needs a `tp-…` format guard.
- `:1817-1820` — `_slugify` collapses fully non-Latin outlet names to the constant `"outlet"` → duplicate DOM ids once batch-1 feeds are enabled.
- `src/render.py:272-278` — `render_rss_entry` (no production caller) builds 404 links, non-RFC-822 dates, and reads an internal slot.
- `src/render.py:73-77` — `select_by_visibility` doesn't `model_dump()` `list[BaseModel]` slots; breaks its "JSON-compatible" promise (currently harmless).
- Dead code with an internal bug: `_wrap_non_latin` (`:117-138`, duplicate `‘` test), `_contains_rtl`, `COUNTRY_DISPLAY`, `COUNTRY_TO_ISO` — never referenced.

**Tools / hydration**
- `hydration.py:93-103,427-429` — bot-challenge substring match over full 200-OK bodies (`challenge-platform`, `Access denied`) discards legitimately extractable articles; Cloudflare injects that script into normal pages.
- `hydration.py:457,296-320` — error-page `Last-Modified` (often "today") overrides a valid URL-path publication date on 403/404/challenge responses — the exact wrong recency signal.
- `web_fetch.py:78-83` — fallback returns the first 10 kB of *raw HTML* (head/scripts/nav) as "page text"; no trafilatura pass despite it being a dependency. Empty-but-successful Ollama results also skip the fallback (`:52`, `is not None` vs truthiness).
- `registry.py:50-51` — allow-list typos silently yield a tool-less agent (no log).
- Cross-domain redirects bypass the target domain's robots.txt/rate limiter; `response.read()` has no body-size cap.

**Translation**
- `core.py:81` — `_PLACEHOLDER` regex matches legitimate German ("Ich muss die …") → unrepairable whole-TP hard failure with no override.
- `brackets.py:26` — "closing quote" class includes opening marks (`„«`); attributions like `"…" (Reuters)` get rewritten to citation-like `[Reuters]`.
- `core.py:107-111` — citation guard checks missing `[src-N]` tokens but never hallucinated extras.
- `translate_sidecar.py:191-196,295-336` — cache key excludes backend, but CT2 (no truncation) and transformers (128-token truncation) produce different English for one key; backend switches silently serve the other backend's outputs.
- `run.py:130-152` — in-flight block costs are lost on TransportError unwind → day summary under-reports billed spend of failed attempts.
- `render.py:990,1470,2033-2040` — actor `role` and quote `position` prose render in English on German pages (missed by the 5-block segmentation), while translated `missing_positions` descriptions are never rendered anywhere (dead translation cost).

---

## Tests & docs

- **3 failing tests, all hermeticity, not product bugs:**
  - `tests/test_run_cli.py` ×2 — construct agents and die without `OPENROUTER_API_KEY`; unit tests shouldn't need a live key to *construct* config.
  - `tests/test_curator_monitor.py::test_empty_window_does_not_crash` — the stub is installed only `if PATHOLOGY_BASELINE_STATE.exists()` (`:163`), so the test depends on an uncommitted historic artifact. Underlying product issue: `scripts/curator_monitor.py:89-108` checks the raw 2026-05-11 state file's existence *before* consulting the `_baseline.json` cache, so the cache can never satisfy the call and the monitor hard-fails on any machine without that artifact. _(Still live 2026-07-05 — reconfirmed env-only during TASK-HYDRATION-P2-GLM-SWAP: reproduces with changes stashed; the rest of the suite is green. Not a regression; do not re-triage.)_
- **CLAUDE.md drift:** (a) claims slot-ownership violations "fail precondition validation" — false today (H5); (b) documents `uv run pytest`, but pytest lives in the `dev` extra — a fresh `uv sync` can't run tests (`uv sync --extra dev` or move to `[dependency-groups] dev`); (c) the documented `--reuse` resume commands all exit 1 without `--force` (M-R1).
- `docs/`-adjacent drift: commit `30775aa`'s "activates recency-tiebreak" claim is false (M-C2); `state.py`'s fallback docstring describes dead code (H4).
- `coherence.py:113` warns about fastembed mean pooling on every embed — expected under the deliberate `0.8.0` pin, but worth a suppressing comment so nobody "fixes" it by unpinning.

---

## What was checked and found sound

Worth stating, because it's most of the codebase: delta-emitter semantics (`"field" in delta`) are respected everywhere; no counting is delegated to LLMs; the fastembed singleton invariant holds across all production paths; gravitational assignment (threshold `>=`, `PER_FINDING_CAP` via lexsort, tie-breaks, `mc-NNN` IDs) is correct and well-tested; chunk distribution and Phase-1 index remapping lose no remainders; union-find alias resolution is correct; the runner's read-only-proxy mutation detection genuinely works; `run_stage_log` cost accumulation across chunked multi-call stages is correct (except the failure path, M-R5); HTML escaping in `scripts/render.py` is disciplined across every feed-controlled string traced; `feed.xml`/sitemap escaping uses `saxutils` correctly; per-feed exception isolation in `fetch_feeds.py` works; `lookup_outlet` handles www/ports/case/bare-host correctly against a well-normalized 366-key registry (every configured feed's article domain resolves); hydration's concurrency (order-preserving gather, per-domain locks, timeout classification) is more careful than it first looks; and the translation core's guard→ladder→failover design is sound in the happy path with honest never-half-done semantics.

## Suggested priority order

1. **The four missing `optional_write` flags** (H1, H2, H3, M-AS4 + the zero-topics case) — one-line bus fixes, each currently a whole-topic loss on valid LLM output.
2. **Daily-runner robustness** (H7, H8, M-P2, M-P3): autostash/`rebase --abort` recovery in the shell runners, per-TP try/except in publish, content-hash copy detection.
3. **Resume correctness** (H4, M-R1, M-R2, M-R3): make the wrong-stage fallback an error, fix the force-gate and `--topic` bounds.
4. **Non-Latin text integrity before enabling batch-1 feeds** (H6, M-P4, M-P5, ASCII tokenizer, `_detect_lang`, `_slugify`) — these all silently corrupt exactly the streams being onboarded.
5. **Published-output integrity** (M-TS1, M-TS2, M-AS2, H10, M-RND1): stale counts, transparency-card predicate, visibility contract, URL scheme guard.
6. Fix `agent.py` retry taxonomy alongside the planned Opus 4.7 migration refactor (M-CORE1), and decide the H5 enforcement gap (a `bus_before`/`bus_after` diff over undeclared slots in `validate_postconditions` would make CLAUDE.md's claim true).
