# Workstream — Pipeline Simplification & Review Remediation

Status: **active** · Created 2026-07-02 · Owner: Architect sessions
Finding IDs reference `docs/CODE-REVIEW-2026-07-02.md`.

## Principle

The measure of this workstream is **seams, not stage count**. The code
review confirmed empirically what the strategy session concluded:
defects cluster at stage boundaries and operational seams, not in the
load-bearing invariants. Complexity is multiplicative — two pipeline
variants × two source paths × mirror/repair seams. Remove the
multiplicative dimensions; the linear deterministic stages are cheap.

## Target architecture (Zielbild)

One variant (hydrated), one source path (curated feeds → hydration),
no mirror stages: **~21 topic stages, 8 LLM calls per topic** (from
29 / 10). Unchanged by design: Curator four-step, hydration core,
Consolidator, the transparency chain (balance → bias → card).

Cuts and collapses:
- production variant + `build_production_stages_llm_assignment` (Stufe 0)
- researcher trio + Brave + `src/tools/web_search.py` (Stufe 1)
- `merge_sources` / `renumber_sources` / `normalize_pre_research` —
  die with the single source path (Stufe 1)
- token-overlap hydration-URL attach → ID-based pass-through
  (structurally resolves M-AS3, M-C1, M-C2; replaces the Unicode
  tokenizer stopgap from Wave C)
- `mirror_perspective_synced` / `mirror_qa_corrected` via coordinated
  slot renames (Stufe 2 — renames are breaking schema events; all
  consumers in one commit)
- `prune_unused` / `cleanup_stale_references`: instrument what they
  still change post-Stufe-1 → degrade to assertions, or replace
  deletion with a "consulted, uncited" section in the TP (more
  transparent, removes the dangling-reference bug class; TP-schema
  decision) (Stufe 3)
- `resolve_actor_aliases` (LLM): data-driven review — measure what the
  LLM merges that fuzzy matching cannot. Caution: cross-script
  aliasing matters with the non-Latin feeds live (Stufe 4)

## Done

- 2026-07-02 — Full code review committed as
  `docs/CODE-REVIEW-2026-07-02.md` (12 high / ~35 medium / ~50 low;
  spot-verified by Architect at H1, H2, M-P3).
- 2026-07-02 — **Wave A merged** (`cb07af8`): `optional_write` for the
  four topic-scoped valid-empty slots (H1/H2/H3/M-AS4) + 5 regression
  tests. Zero-topics run case deliberately deferred (see backlog);
  deferral pinned by `test_zero_topics_run_cascade_is_deferred_not_fixed`.
- 2026-07-02 — **Wave C merged** (`6d8f2a6`): H6 bytes-level charset
  detection in hydration, M-P4 feedparser on bytes, M-P5 undated
  seen-set (`raw/undated_seen.json`, 30-day retention), Unicode-bigram
  tokenizer stopgap.
- Batch-1 observation window **restarted**: 3–4 days from 2026-07-03.
  Daily manual check via Architect/DC ("prüf mal"): mojibake = 0 in
  newest `topic_buses.json`; fetch log shows repeat-undated
  suppression from day 2.

## Pending (in order)

1. **Wave B — runner robustness**: H7 (autostash / rebase-abort
   recovery in `daily_run.sh`), H8 (per-TP tolerance in publish), H11
   (per-TP isolation for the German publish), M-P2, M-P3
   (content-hash instead of size-only change detection).
2. **Wave D — resume correctness**: H4 (wrong-stage fallback → hard
   error), M-R1 (`--reuse` force-gate), M-R2 (`--topic` bounds), M-R3,
   M-R4 (atomic snapshot writes). Prerequisite before Stufe 1 touches
   the stage lists.
3. **Stufe 0** — delete legacy production variant + llm_assignment
   builder (pure deletion, no hydrated behavior change).
4. **Stufe 1** — researcher removal + merge-seam collapse + `src/tools`
   teardown (resolves H9, M-P7, most of H12) + ID-based URL attach.
   Compensation track: feed harmonization from the validated research
   list (76 live candidates; list is Air-only, not git-tracked).
5. **H5 enforcement** — undeclared-write diff in
   `validate_postconditions`; cheap once Stufe 1 reduced the writers.
6. **Stufe 2** — mirror-stage removal via slot renames.
7. **Wave E — published-output integrity**: M-TS1, M-TS2, M-AS2, H10,
   M-RND1.
8. **Stufe 3 / Stufe 4** — as described under Zielbild.
9. **M-CORE1** retry taxonomy → fold into WP-OPUS-4.7-MIGRATION.

## Spawned backlog items

- **Zero-topics guard**: a schema-valid zero-topics Curator answer must
  end the run via an explicit deterministic guard with a clear message
  — NOT via `optional_write` (that would turn an anomalous empty day
  into a silent empty publish). Cascade documented in the pinned test.
- **MADLAD pre-enable additions**: see addendum in
  `docs/WORKSTREAM-MULTILINGUAL-EXPANSION.md` (M-T6, backend-less
  sidecar cache key, `LANGUAGE_NAMES` missing ne/zu/uz).
- **Translation track** (M-T1–M-T5): separate, after the MADLAD
  enablement decision.

## Cross-stream unification (added 2026-07-02, evening)

Three parallel streams merged into one queue (sources: this doc,
WORKSTREAM-MULTILINGUAL-EXPANSION.md, docs/QA-STAGE-MODEL-EVAL-* handoff):

0. **Passive clocks (running, Mini)**: batch-1 feed observation (3–4 days
   from 07-03, daily Architect check) → Batch-2 decision ~07-05; GLM-5.2
   qa_analyze shadow run (~5 days, `scratch/qa-shadow/`, read-only) →
   QA-swap decision ~07-07 (latency + values call, not quality).
1. **DeepSeek fp8 pin** (TASK-DEEPSEEK-FP8-PIN) — NEW, front of queue:
   fp4 provably causes DeepSeek fabrications; 5 production stages are
   unpinned. Requires ≥3 empirically verified fp8+structured-outputs
   providers per model. Note: Stufe 1 will later delete researcher_assemble
   (pin list shrinks to 4) — pin now anyway.
2. Wave B → Wave D → Stufe 0 → Stufe 1 → rest as listed under Pending.

Cross-notes: uncommitted guarded eval change in `src/agent.py` on the Air
is deliberate (pending QA-swap decision) — do not clean up. Backlog add:
bias-stage quant follow-up (DeepSeek bias rejection ran at unknown quant,
possible fp4 confound; GLM's fp8 rejection stands).

## QA-swap → GLM-5.2 — DECIDED + LANDED (2026-07-03)

Passive-clock item 0's "QA-swap decision ~07-07" is **closed early, no
observation gate**: eval v2 (`QA-STAGE-MODEL-EVAL-SHADOW-BACKFILL.md` — GLM
beats incumbent 19/21, 1 vs 11 confirmed fabrications, at the golden ceiling)
+ provider verification (`GLM-PROVIDER-VERIFICATION-2026-07.md` —
Baidu/Ambient/Venice fp8-verified) made it binding (TASK-QA-SWAP-GLM). Landed
on branch `qa-swap-glm` (not pushed): `qa_analyze` → GLM-5.2 @ xhigh, temp 0.1,
`max_tokens=120000`, fp8-pinned `[baidu,ambient,venice]`; 4th-line Sonnet-5
model fallback (`reasoning.enabled`, no temperature) fires only on GLM's final
failure (transport across all providers OR schema-invalid/truncated output) —
loud, never silent (`model_used`/`provider_used`/`qa_fallback_used` in
`run_stage_log.jsonl`). Stage-isolated smoke (topic 1, 2026-07-03 reuse):
schema-valid, served provider Baidu, fallback NOT triggered, $0.08, ~191s
(xhigh latency ~3–6 min/topic is the standing caveat). Rollback = the single
`create_agents` revert to Sonnet-4.6 documented in the swap commit.

## Writer-swap → GLM-5.2 — DECIDED + LANDED (2026-07-04)

The authoritative full-21 writer eval (`WRITER-STAGE-MODEL-EVAL-2026-07.md`,
FINAL section — GLM leads pooled correctness 3.75 vs incumbent 3.30 and rubric,
is deterministically clean 21/21 with 0 invented/phantom/orphan ids, and is the
cheapest arm) made GLM-5.2 @ xhigh binding — swapped immediately, no observation
gate (TASK-WRITER-SWAP-GLM). Landed on branch `feat/writer-swap-glm` (not
pushed): `writer` → GLM-5.2 @ xhigh, temp 0.3, `max_tokens=120000`, fp8-pinned
`[baidu,ambient,venice]`; 4th-line model fallback fires only on GLM's final
failure (transport across all pinned providers OR schema-invalid/truncated
output) — loud, never silent (`model_used`/`provider_used`/`writer_fallback_used`
in `run_stage_log.jsonl`). ONE deliberate difference from the QA swap: the
fallback is the **pre-swap incumbent Opus 4.6** (reasoning `none`), NOT Sonnet-5
— Sonnet-5's citation hygiene proved unstable twice in the eval (empty
`sources[]` with inline cites on 1/3 of the completion window). Stage-isolated
smoke (topic 1, 2026-07-03 reuse): schema-valid, served provider Baidu, fallback
NOT triggered, 26 inline citations all resolving against `final_sources`, $0.07,
~172s (production state backed up + restored byte-identical). Rollback = the
single `create_agents` revert to Opus-4.6 documented in the swap commit.

## Editor-swap → GLM-5.2 + Sonnet-5 fallback — LANDED (2026-07-04)

The complete 5-arm editor eval (`EDITOR-STAGE-MODEL-EVAL-2026-07.md`, FINAL —
GLM won the blind Architect tally 13/20 and is the cheapest arm) made GLM-5.2 @
xhigh binding, but the eval also found GLM/DeepSeek **retry-fragile** under the
strict `EDITOR_SCHEMA` at xhigh (GLM 55 % / DeepSeek 23 % first-attempt validity;
Sonnet-5 22/22) and the editor runs **once per day with no native fallback**
(TASK-EDITOR-SWAP-GLM). Landed on branch `feat/editor-swap-glm`: `editor` →
`EditorWithFallback`, primary GLM-5.2 @ xhigh temp 0.3 `max_tokens=120000`
fp8-pinned `[baidu,ambient,venice]`, and exactly one **Sonnet-5** fallback
(`reasoning {enabled,effort:high}`, no temperature, `max_tokens=64000` — the
eval's 22/22 operating point) if GLM finally fails (transport across all pinned
providers OR a schema-invalid/`structured=None` output) — loud, never silent
(`model_used`/`provider_used`/`editor_fallback_used`, a run-level
`run_stage_log.jsonl` marker). Deliberate difference from writer/QA: the fallback
is **Sonnet-5** (the eval's perfectly-reliable, editorial-#2 arm — the validated
safety net for a no-native-fallback stage), not the Opus-4.6 incumbent. Shared
schema checker `qa_fallback._matches` gained additive union-type (`["string",
"null"]`) support for `EDITOR_SCHEMA`'s follow-up fields (writer/QA unaffected).
Rollback = the single `create_agents` revert to Opus-4.6 documented in the swap
commit.

## Perspective-swap → Sonnet-5 + Opus-4.6 fallback — LANDED on branch (2026-07-04)

The blind 5-arm perspective eval (`PERSPECTIVE-STAGE-MODEL-EVAL-2026-07.md`) made
Sonnet-5 binding for the perspective stage: it beats the incumbent Opus-4.6
**19–2** pairwise, matches the golden ceiling on the product-core criteria (R1
substance-cluster 0.98 / R5 0.84 / R9 spectrum-fidelity 0.95), emits the fewest
confirmed invented positions (2 vs the incumbent's 5), and is fully reliable
21/21. **Both** open-weight candidates (GLM-5.2, DeepSeek) *regressed below the
incumbent* on this stage — the opposite of the writer/QA/editor evals — so this
is a **pure quality call** (TASK-PERSPECTIVE-SWAP-SONNET5). Landed on branch
`feat/perspective-swap-sonnet5`: `perspective` → `PerspectiveWithFallback`,
primary Sonnet-5 at the eval's binding operating point — `reasoning
{enabled, effort:high}`, **no temperature** (the ONE documented config deviation:
the Claude 5-family rejects non-default temperature/top_p with a 400, so the
production 0.1 cannot carry over), `max_tokens=64000`, no provider pin
(Anthropic-served; served provider still recorded per call). Prompts and
`PERSPECTIVE_SCHEMA` unchanged, so the downstream deterministic enrichment
(`enrich_perspective_clusters`) is untouched. Exactly one fallback attempt if
Sonnet-5 finally fails (transport across retries OR a schema-invalid/truncated
output) on the **pre-swap incumbent VERBATIM** (Opus-4.6, temperature 0.1,
`reasoning="none"`, default `max_tokens=32000`) — a validated known-good safety
net; loud, never silent (`model_used`/`provider_used`/`perspective_fallback_used`
in `run_stage_log.jsonl`). Smoke (`--from/--to PerspectiveStage --topic 1` on the
largest 2026-07-04 topic, production state copied out and restored byte-identical):
Sonnet-5 served (provider Azure), fallback **not** triggered, schema-valid, 17
position clusters + 5 missing positions, **0 invented source_ids / 0 unresolved
actor refs**, $0.28, ~190s. Rollback = the single `create_agents` revert to
Opus-4.6 documented in the swap commit.
