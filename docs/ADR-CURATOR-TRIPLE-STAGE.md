# ADR — Curator Triple-Stage Architecture

**Status:** Implemented and empirically validated (2026-05-17)
**Date proposed:** 2026-05-14
**Date validated:** 2026-05-17 (Brief 5b re-audit confirms aggregate weighted off-topic rate 8.23 % across the 2,542-label audit set; zero topics above 50 % off-topic)
**Supersedes:** the single-pass LLM Curator (`CuratorStage` as it existed pre-Brief-5; removed in the Brief 5 cutover)

## Context

The Curator's job is to turn ~1200 daily findings into a small set of thematic topic candidates. The current implementation does this in one LLM pass: the model receives all findings and must simultaneously (a) define the thematic clusters and (b) assign every finding to one of them via a flat `cluster_assignments` array.

Three weeks of evidence show this single-pass approach is structurally broken:

- **Over-clustering pathology.** On diffuse hot-topic days the model collapses 80–92% of findings into one catch-all mega-cluster. Manual labelling confirmed 92% off-topic in the 2026-05-11 Iran cluster (1004 findings), 76% in the Trump-Xi cluster, 93% in the Sudan cluster.
- **Model swap does not fix it.** `AUDIT-CURATOR-V4PRO-VARIANCE-2026-05-13` tested DeepSeek-V4-Pro across 3 days × 3 temperatures × 3 repetitions. Inter-rep Jaccard mean 0.213 — three byte-identical runs of one cell produced top-cluster sizes of 2 / 1280 / 1337. The pathology is not model-specific; it is inherent to asking an LLM to assign 1200 items in one pass.
- **The root cause is the dual task.** When the model must produce one assignment *per finding*, the path of least resistance for an ambiguous finding is the largest existing cluster. Catch-all behaviour is the structural consequence of the per-finding output pressure.

`CLUSTERING-EVAL-2026-05-14` then established that embedding-based clustering can do the grouping deterministically: Agglomerative clustering on `paraphrase-multilingual-MiniLM-L12-v2` embeddings, `distance_threshold=0.7`, `linkage='average'`, `metric='cosine'`, isolates off-topic findings into separate micro-clusters with 94–100% physical separation from on-topic findings, no mega-clusters, aggregate F1 0.71 across the 504-finding ground-truth set.

## Decision

Replace the single-pass Curator with a three-stage pipeline that gives each stage the task it is structurally suited for. Two deterministic stages form the skeleton; the LLM is used only where embeddings cannot substitute — recognising semantically superordinate themes.

### Stage 1 — Embed-Pre-Cluster (deterministic)

Embeds all findings and groups them into ~250 micro-clusters via Agglomerative clustering with the parameters established by `CLUSTERING-EVAL-2026-05-14`. No LLM. Deterministic: identical input produces bit-identical micro-clusters. The micro-clusters are an intermediate compression artefact for Stage 2 — **not** the final cluster product.

### Stage 2 — Curator / Topic-Discovery (LLM, small input, small output)

The Curator LLM receives the ~250 micro-clusters in compressed representation (not 1200 individual findings) and identifies the 10–20 genuine superordinate topics of the day. Its only output is `{topics: [{title, summary}]}`. It performs **no finding assignment** and emits **no relevance score**. It is free to ignore micro-clusters whose theme does not rise to a top topic — there is no pressure to use all of them, which structurally eliminates catch-all behaviour.

The cognitive load is radically lower than today's: input drops from ~150k tokens to ~40k, output drops from "10–20 topics plus 1200 assignments" to "10–20 topics". The V4-Pro pathology came from the per-finding output pressure; removing it removes the failure mode.

### Stage 3 — Gravitational Assignment (deterministic, multi-assignment)

Embeds each Stage-2 topic's `title + summary` into a topic-centre vector. Embeds each finding. For every finding, computes cosine similarity to all topic centres. A finding is assigned to **every** topic centre it scores above the gravitational threshold for — capped at 2–3 topics per finding. A finding above the threshold for no topic centre becomes an orphan. No LLM. Deterministic.

"Off-topic" is no longer a junk bin — it is a measurable distance to every recognised topic. The threshold is a single, data-tunable knob; orphans are transparent and reproducible.

### Off-topic filtering happens in two independent stages

- Stage 2: a micro-cluster whose theme the LLM does not elevate to a top topic contributes nothing to the topic list.
- Stage 3: an individual finding too dissimilar from every topic centre becomes an orphan.

Two unrelated filters, both deterministic at the points that matter.

## Parameters (from completed evals)

| Parameter | Value | Source |
|---|---|---|
| Embedding model | `paraphrase-multilingual-MiniLM-L12-v2` | `EMBEDDING-MODEL-EVAL-2026-05-13` (kept Model A; macro-F1 0.84 vs candidate 0.78) |
| Pre-cluster algorithm | Agglomerative | `CLUSTERING-EVAL-2026-05-14` (refuted the HDBSCAN hypothesis) |
| Pre-cluster params | `distance_threshold=0.7`, `linkage='average'`, `metric='cosine'` | same |
| Multi-assignment cap | 2–3 topics per finding | architect decision, 2026-05-14 |
| Gravitational threshold | **open — calibration brief** | — |
| Micro-cluster representation for Stage 2 | **open — calibration brief** | — |

## What changes

### Schemas (`src/schemas.py`)

- `CURATOR_SCHEMA`: `cluster_assignments` removed (no LLM assignment), `relevance_score` removed (Editor's call). New shape: `{topics: [{title, summary}]}`. The Curator's *input* also changes — from `findings` to micro-cluster representations.
- `EDITOR_SCHEMA`: **unchanged.** Editor output stays `{assignments: [{title, priority, selection_reason, follow_up_to, follow_up_reason}]}`.

The `src/schemas.py` header states the schema tracks the prompt's OUTPUT-FORMAT section field-for-field. Therefore the `CURATOR_SCHEMA` change and the Curator prompt rewrite must land in the same brief — strict-mode validation breaks if they diverge.

### Prompts

- `agents/curator/INSTRUCTIONS.md` + `SYSTEM.md`: rewritten for Topic-Discovery. The old versions move to `agents/_archive/` per the existing convention (`<source-dir>-<source-file>-YYYY-MM-DD.md`, "Files here are dead. Do not edit.").
- `agents/editor/INSTRUCTIONS.md`: input description revised — drop `missing perspectives` and `relevance score` from the list of fields the Editor receives. Editor output and logic unchanged. Old version archived.
- Prompt-writing principle for the PE briefs and the resulting prompts: **not granular.** No enumerated edge-case lists with prescribed handling. General principles pitched at a level that absorbs edge cases, rather than a catalogue of specific cases and instructions.

### Deterministic helpers (`src/agent_stages.py`)

- `_enrich_curator_output`: `missing_perspectives` removed entirely. It was a redundant string summarising `missing_regions` + `missing_languages`, and the word "perspectives" misrepresents it as content analysis. The genuine content-gap analysis is `perspective_missing_positions`, produced later by the Perspective agent — a separate mechanism, untouched by this work.
- `_CURATOR_RAW_DATA_FIELDS`: `relevance_score` removed (the LLM no longer emits it).
- The remaining deterministic enrichment — `geographic_coverage`, `languages`, `source_count`, `missing_regions`, `missing_languages`, `source_diversity` — stays. These are facts computed from assigned findings. With multi-assignment, this enrichment runs after Stage 3 (source assignment now happens there, not in the Curator wrapper).

### New stages

Embed-Pre-Cluster and Gravitational-Assignment are both new deterministic stages in the run-stage chain. Stage order: `fetch_findings → Embed-Pre-Cluster → Curator/Topic-Discovery → Gravitational-Assignment → (curator enrichment) → EditorStage → ...`.

### `measure_cluster_coherence`

The passive coherence stage shipped recently becomes architecturally redundant — Stage 3's gravitational threshold *is* the coherence measurement, applied as a clustering decision rather than a passive diagnostic. The fastembed infrastructure it introduced (embedder singleton, pinned model, pinned fastembed version) is inherited by the new stages. Whether the old stage is removed outright or retained as a diagnostic is a decision for the integration brief, not this ADR.

## What this does NOT change

- **Editor output.** `priority` is already the editorial relevance judgement (0 = reject, 1–10 = accepted by urgency). No new field, no schema change. The Curator simply stops supplying a `relevance_score` the Editor was meant to override anyway.
- **Perspective agent.** `perspective_missing_positions` — the genuine content-gap analysis — is produced downstream and is entirely independent of this work.
- **Downstream TP isolation.** Each Topic Package is processed independently of the others. Agents see one TP; they do not need to know a source also appears in another TP. Only the Editor sees all topics at once, and only as aggregated topic metadata, never as individual findings.

## Consequences

### Multi-assignment

A finding can belong to 2–3 topics. This is the honest model — a Strait-of-Hormuz attack genuinely belongs to both "Iran-US diplomacy" and "global energy crisis"; forcing it into one would be exactly the editorial simplification the project exists to make visible. The transformed bus form (`topic.source_ids[]` lists) already carries multi-assignment without change — a finding can sit in multiple `source_ids[]` lists. It is the LLM-output form (`cluster_assignments` flat array) that disappears, and it disappears anyway because Stage 2 makes no assignments.

### Duplicate hydration

If a finding appears in two TPs, its URL is hydrated in both. This is a cost question, not a correctness question — accepted for now, flagged as a future optimisation, not a blocker.

### Determinism restored to clustering

Stages 1 and 3 are deterministic — identical input produces bit-identical clusters. Stochasticity is confined to Stage 2 (topic-title generation on a ~40k-token input), where the output is small and the variance is observable. The V4-Pro variance pathology is structurally impossible in this architecture.

## Calibration points (resolved)

All three open calibration points from the original ADR have been resolved by the brief sequence. Each is now pinned in code; the brief that resolved it, the parameter, and the validating artefact are listed below. See `docs/AUDIT-TIMELINE.md` for the full chronology.

1. **Pre-cluster algorithm and parameters.** ✅ **Resolved in Brief 1** (`TASK-EMBED-PRE-CLUSTER-STAGE`). Algorithm: **Agglomerative clustering**. Parameters: `distance_threshold = 0.7`, `linkage = 'average'`, `metric = 'cosine'`. Pinned in `src/stages/pre_cluster.py`. Validated against `docs/CLUSTERING-EVAL-2026-05-14.md::agg-permissive` — zero pathology runs across the three-day eval set, aggregate F1 0.71 on the 504-label ground-truth set.

2. **Gravitational threshold + per-finding cap.** ✅ **First calibrated in Brief 2** (`TASK-GRAVITATIONAL-ASSIGN-STAGE`, provisional T = 0.30, cap = 3, V1 topic-centre = title+summary, against the 504-label V1-headline set — `docs/gravitational-assign/_calibration-2026-05-15.md`). The Brief-5 cutover then surfaced empirically that the Stage-2 LLM topic-centres are broader than the V1 headlines used for calibration; the cluster-quality audit (`docs/cluster-quality-audit/audit-2026-05-16/`) measured 69.59 % aggregate weighted off-topic rate at the provisional T = 0.30. ✅ **Recalibrated in Brief 5b** (`TASK-GRAVITATIONAL-RECALIBRATION`) against the 2,542-label audit set via a 12-configuration sweep over T ∈ {0.30 … 0.55} × V ∈ {title+summary, title-only}: pinned `GRAVITATIONAL_THRESHOLD = 0.55`, `PER_FINDING_CAP = 3` unchanged (cap does not bind at T = 0.55), topic-centre text unchanged at title + summary. Validation: `docs/cluster-quality-audit/audit-2026-05-16-recalibrated/` — aggregate 8.23 %, zero topics above 50 % off-topic. The Brief-2 calibration at T = 0.30 is **superseded**; the historical calibration report is retained as audit-trail.

3. **Micro-cluster representation for Stage 2.** ✅ **Resolved in Brief 4** (`TASK-CURATOR-TOPIC-DISCOVERY-STAGE`). Representation: **top-K-by-centroid sample titles**, K pinned at `SAMPLE_TITLES_PER_CLUSTER = 8`. Selection: for each pre-cluster, embed the members via the shared fastembed singleton, compute the centroid, take the top-K findings by cosine similarity to centroid (sim desc, finding-index asc tie-break), extract their titles. Clusters with size ≤ K pass through complete. Pinned in `src/agent_stages.py::CuratorTopicDiscoveryStage`. Validation: `docs/curator-topic-discovery/smoke-2026-05-16/` — 15/15/18 topics across the three eval days, $0.057 total LLM cost, zero category-shapes, zero catch-all titles.

## Empirical validation

The end-to-end V2 Curator architecture has been validated against ground truth at two points: at provisional calibration (Brief 5 cutover, 2026-05-16) and at the recalibrated state (Brief 5b, 2026-05-17).

The recalibrated cluster-quality re-audit (`docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`) shows:

- **Aggregate weighted off-topic rate:** 8.23 % across 486 retained findings from 30 audited top-10 topics across three eval days (2026-05-08, 2026-05-11, 2026-05-13). Baseline at the provisional T = 0.30 was 69.59 %.
- **Per-day breakdown:** 2026-05-08 → 11.69 %, 2026-05-11 → 7.98 %, 2026-05-13 → 5.33 %.
- **Topics above 50 % off-topic:** zero. The highest residual is the China-former-defense-ministers topic at 40 % (2 off of 5 retained — small absolute counts).
- **Gravity-trap movement:** Ramaphosa 93.3 % → 0.0 %, Yermak 93.5 % → 0.0 %, Putin/Schröder 91.0 % → 21.4 %, Nunes Marques 91.4 % → 0.0 %.
- **Multilingual coverage preserved on clean topics:** Hantavirus (clean reference cluster, 14 % baseline off) drops from 65 retained findings to 33 — the recall trade-off that drove the architect's pick of V1 (title+summary) over V2 (title-only) in the Phase-2 qualitative samples.

The V4-Pro variance pathology that motivated the original ADR is structurally impossible in this architecture: the LLM no longer assigns findings, so the per-finding output pressure that produced the over-clustering catch-all is gone.

## Implementation sequence (shipped)

The brief sequence below was executed against this ADR in order. Each brief's commits and validation evidence are linked from `docs/AUDIT-TIMELINE.md`.

1. **Brief 1 — Embed-Pre-Cluster stage** (`TASK-EMBED-PRE-CLUSTER-STAGE`). Deterministic Agglomerative clustering, fastembed singleton infrastructure, smoke at `docs/pre-cluster/smoke-2026-05-15/`. Commits end at `9cc2957`.
2. **Brief 2 — Gravitational-Assignment stage** (`TASK-GRAVITATIONAL-ASSIGN-STAGE`). Deterministic cosine-threshold assignment, provisional calibration at T = 0.30 against the 504-label set. Commits end at `5189cec`. Calibration superseded in Brief 5b.
3. **Brief 3 — PE round: Curator + Editor prompt rewrites** (`feat(prompts): triple-stage Curator + Editor prompt rewrites`, commit `03103e8`). Architect-drafted PE brief, PE returns SYSTEM.md + INSTRUCTIONS.md, CC writes to disk; old V1 Curator prompts archived under `agents/_archive/`.
4. **Brief 4 — Curator Topic-Discovery stage** (`TASK-CURATOR-TOPIC-DISCOVERY-STAGE`). New LLM stage with the rewritten prompt, top-K-by-centroid compression at K = 8, `CURATOR_TOPIC_DISCOVERY_SCHEMA`. Commits end at `3ab766c`.
5. **Brief 5 — Triple-stage cutover** (`TASK-TRIPLE-STAGE-CUTOVER`). Old `CuratorStage` removed, `gravitational_assign` rerouted to read `curator_discovered_topics`, `assemble_curator_topics` composes the legacy `curator_topics_unsliced` shape from the new slot trio. Commits end at `0135c8f`.
6. **Cluster-quality audit** (`TASK-CLUSTER-QUALITY-AUDIT`, commit `6d8ffc4`). 2,542 (finding, topic) labels across the top-10 topics of three eval days; surfaced 69.59 % aggregate weighted off-topic rate at the provisional T = 0.30. Motivated Brief 5b.
7. **Brief 5b — Gravitational recalibration** (`TASK-GRAVITATIONAL-RECALIBRATION`). 12-config sweep, qualitative samples at the top-three configurations, architect's pick T = 0.55 V1, pinned constants + re-audit confirming 8.23 % aggregate / 0 topics > 50 %. Commits end at `310a55d`.
8. **Brief 6 — Doc reconcile** (`TASK-DOC-RECONCILE`, this commit's parent sequence). ADR-CURATOR-TRIPLE-STAGE moved to *Implemented and empirically validated*, ARCHITECTURE.md updated to V2, AUDIT-TIMELINE.md created.

## Calibration anchor (historical)

The 504-finding manual-label ground-truth set (`docs/coherence-filter/manual-labels/`) was the evaluation anchor for Brief 2's provisional calibration. It is **no longer the validation set** — it was built against V1 cluster headlines that turned out tighter than the eventual Stage-2 LLM topic-centres in the new architecture, and that mismatch is what surfaced as the 69.59 % drift in the cluster-quality audit. The current validation set is the 2,542-label set built during the audit (`docs/cluster-quality-audit/audit-2026-05-16/`), with the recalibrated outcome at `docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`. The 504-label set is retained as audit-trail and as the historical record of how the provisional calibration came to be.
