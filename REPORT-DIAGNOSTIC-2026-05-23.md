# Diagnostic Report — 2026-05-23

Three issues surfaced in the 2026-05-21 .. 2026-05-23 dossier audit. This report traces each back to the producing stage / agent, identifies the responsible code location, classifies the problem (deterministic vs LLM-produced), and lays out remediation options with trade-offs. **No code or prompt changes have been made.** Targeted fix briefs are deferred to the architect.

## TL;DR

| Issue | Where | What | Class |
|---|---|---|---|
| **A** | `validate_coverage_gaps` (`src/stages/_helpers.py:130`) | Substring keyword-match falsified **5 of 7** Cuba gaps as false-positives (architect's manual count was 4; replay surfaces 5). Two stages from commit `f6a4c14` (`validate_coverage_gaps` and `strip_stale_quantifiers`) are keyword-substring matchers masquerading as semantic validators; the rest of the deterministic surface is structurally sound. | deterministic, over-aggressive |
| **B** | `HydrationPhase1Stage` + `ResearcherAssembleStage` → `consolidate_actors` | Both producer prompts have **no English-output directive** on `role` / `position` (only on `verbatim_quote`, where original language is correctly mandated). Result: `role` strictly tracks the **first quoting source's language** under `consolidate_actors`' first-wins dedup. Same defect affects `position` at ~3× the volume. | LLM-produced, prompt-level |
| **C** | `PerspectiveStage` (LLM, claude-opus-4.6) | Clusters with `n_actors==0` are **born empty** at PerspectiveStage. Sub-lists `stated/reported/mentioned` are explicitly licensed as optionally empty by the schema (`src/schemas.py:218-219`) and the prompt (`agents/perspective/INSTRUCTIONS.md:5-11`) for source-level (framing / outlet) claims. Downstream is innocent — `actor_ids` is derived from sub-lists at `enrich_perspective_clusters` and propagated verbatim through every later stage. | LLM-produced **or** rendering choice |

---

## Issue A — `validate_coverage_gaps` over-aggressive falsification + audit of deterministic-semantic stages

### A.1 Origin and intent

The validator originates from V1 commit **`f6a4c14`** (2026-04-29), titled `fix(pipeline): close five audit findings via deterministic data routing`. It was finding **#2 of five** in a post-King-Charles audit (`tp-2026-04-28-002`). The commit message verbatim for that fix:

> **#2 Coverage-gap validation against final source balance**
> `_validate_coverage_gaps` drops pre-research gap statements falsified by the post-research source balance ("no UK domestic outlets" with The Independent UK present in `by_country`; "no non-English sources" with multiple languages present; etc.) plus near-duplicates via Jaccard similarity > 0.7. Genuinely qualitative gaps survive verbatim. Smoke evidence: 7 stale gaps dropped on the King-Charles topic; 1 qualitative gap retained.

The helper file `src/stages/_helpers.py` itself was first committed in **`a91ac48`** (V2-03b — `feat(stages): add deterministic topic-stages for V2 pipeline`) as a verbatim port from `src/pipeline.py:1019-1109` (V1). The `_helpers.py` header docstring itself names the source range: "Logic preserved verbatim where possible" (`src/stages/_helpers.py:3-18`). The V1-removal commit `19348f3` deleted the original; the V2 port is what runs today.

**Original rationale (paraphrased):** the Curator/Editor emitted *pre-research* coverage-gap statements about what the dossier wouldn't cover; after Researcher and Hydration ran, some of those statements were demonstrably falsified by the actual `final_sources` (e.g. the Editor said "no UK outlets" and the post-research source balance had two UK outlets). The helper is a defensive Python check that drops gaps the source balance contradicts. With HydrationPhase2 now the single source of truth for `merged_coverage_gaps` (commit `2f46bd5`, 2026-05-21), gaps are now generated *after* research with full knowledge of sources — so the original mismatch the helper guards against can no longer occur by construction. The "near-duplicate" Jaccard>0.7 dedup also exists; it is empirically not triggering on the Cuba dossier (every gap is killed by the country-name path before dedup runs). Doc refs: `docs/ARCHITECTURE.md:269`, `docs/SOURCE-CAP.md:59`, `docs/handoffs/RERUN-TP001-2026-05-11.md:106` (which already flags spurious "missing global south" emissions as a watch-item), `docs/archive/TASK-V2-03b-TOPIC-DETERMINISTIC-STAGES.md:111-189` (port spec).

### A.2 Falsification-path walkthrough on the 7 Cuba gaps

Stage callsite: `src/stages/topic_stages.py:1115-1125`. The stage reads `merged_coverage_gaps` + `source_balance` and writes `coverage_gaps_validated`. The helper at `src/stages/_helpers.py:130-203` has **three sequential falsification branches** inside an outer `if no_pattern.search(gap):` guard (line 165) — branches abort on first match:

- **Branch L** (lang aliases) at `_helpers.py:166-170` — iterates `_LANGUAGE_ALIASES` (e.g. "russian"→"ru"); falsifies if the alias is `\b`-word-bounded in `gap_lower` AND `by_language[code]>0`.
- **Branch C-alias** (country aliases) at `_helpers.py:172-176` — iterates `_COUNTRY_ALIASES_GAP` (only six entries: `uk`, `u.k.`, `us`, `u.s.`, `usa`, `u.s.a.` — see `_helpers.py:108-112`); falsifies if the alias is `\b`-word-bounded AND the canonical (`United Kingdom` / `United States`) has count > 0 in `by_country`.
- **Branch C-literal** (literal country name) at `_helpers.py:178-181` — iterates `by_country.items()`; falsifies if the country name (e.g. `cuba`, `mexico`) is `\b`-word-bounded anywhere in the gap text AND count > 0.

Replay of the input snapshot `output/2026-05-23/_state/run-2026-05-23-4e29191a/topic_buses.merge_sources.1.json` (7 gaps) and `topic_buses.compute_source_balance.1.json` (`by_country` includes `Cuba=1, Mexico=2, United States=2`; `by_language` includes `ru=2, zh=1`, etc.) against the exact helper logic. Output snapshot `topic_buses.validate_coverage_gaps_stage.1.json` confirms `coverage_gaps_validated == []`. All 7 falsifications:

| # | gap text (~80c) | falsification path | matched token | classification | why |
|---|---|---|---|---|---|
| 0 | "No US domestic media outlet is represented in the corpus, leaving the perspectives of US policymakers, Cuban-American…" | C-alias `_helpers.py:172-176` | `'us'` → United States cnt=2 | **true-positive** | Two US outlets in `by_country`; gap claims none. Correct kill. |
| 1 | "No Cuban independent or dissident media operating inside Cuba is included, meaning the views of internal opposition…" | C-literal `_helpers.py:178-181` | `'cuba'` cnt=1 | **false-positive** | The single Cuban source is the state outlet *Granma* (Cuban official press). The gap is specifically about *dissident/independent* media. Country presence ≠ outlet-type presence. |
| 2 | "No coverage from other Caribbean or Central American nations despite their geographic proximity and direct exposure to any escalation in US-Cuba tensions…" | C-alias `_helpers.py:172-176` | `'us'` → United States cnt=2 | **false-positive** | The "US" hit is from the phrase "US-Cuba tensions" — descriptive context, not a coverage claim. The gap is about Caribbean/Central American outlets. |
| 3 | "No international legal experts or human rights organizations are quoted anywhere in the corpus, leaving unaddressed the legal viability and precedent of indicting a former foreign head of state and the human rights conditions inside Cuba…" | C-literal `_helpers.py:178-181` | `'cuba'` cnt=1 | **false-positive** | "Cuba" appears in the phrase "conditions inside Cuba" — a topic referent, not a coverage claim. Gap is about *actor types* (legal experts, NGOs), not country sources. |
| 4 | "No article addresses the humanitarian dimension of the ongoing US oil blockade and sanctions on the Cuban civilian population…" | C-alias `_helpers.py:172-176` | `'us'` → United States cnt=2 | **false-positive** | "US oil blockade" is the policy being described; the gap is about *coverage of the humanitarian dimension*. Country-of-source presence doesn't address the missing framing. |
| 5 | "No Russian or Chinese media perspectives are included despite both governments being quoted as reacting to the situation…" | Branch L `_helpers.py:166-170` | `'russian'` → `ru` cnt=2 | **true-positive** | Two Russian-language sources exist in `by_language[ru]`; gap claims none. Correct kill. (Side note: `by_language['zh']=1` is also present, which would have killed it via "chinese" if Russian hadn't matched first.) |
| 6 | "No coverage from other Latin American governments beyond Mexico (e.g., Brazil, Colombia, Venezuela) despite the story's implications for hemispheric diplomacy…" | C-literal `_helpers.py:178-181` | `'mexico'` cnt=2 | **false-positive** | The gap is explicitly *beyond Mexico* — Mexico's presence is *consistent with*, not falsifying, the claim. The helper has no "beyond X" / "other than X" / "apart from" exception. |

**Summary: 2 true-positives (gaps 0 + 5), 5 false-positives (gaps 1 + 2 + 3 + 4 + 6).** No gap was killed by the Jaccard>0.7 dedup branch (`_helpers.py:188-198`) — the country-name branches fired first.

Note on the original framing: the user-facing issue text described 4 false-positives but the actual replay surfaces **5** (gap 4 — "US oil blockade" — also falsifies on the `us` alias, with the same wrong-claim-mode as gap 2). The architect's "no Caribbean/Central American … beyond Mexico" is gap 6 (which uses "Latin American … beyond Mexico" wording) plus arguably gap 2 ("Caribbean or Central American"). Both are killed, both are false-positives.

The root structural defect is that the helper is doing **substring keyword matching** ("does this gap text mention any country we have in `by_country`?") and treating that as evidence that the gap is *about* that country's coverage being missing. It has no notion of (a) gap-vs-context referents, (b) "beyond X" qualifiers, (c) actor-type vs country-type gaps, (d) outlet-stance qualifiers ("dissident", "independent"). With HydrationPhase2 now writing source-aware gaps, the kill list is structurally biased toward false-positives.

### A.3 Inventory of semantic-deterministic stages

| Stage (file:line) | Classification | Reasoning + concrete-TP evidence |
|---|---|---|
| `validate_coverage_gaps` (`_helpers.py:130`, callsite `topic_stages.py:1115`) | **already broken** | The issue under investigation. 5 of 7 gaps falsified on `tp-2026-05-23-002`, leaving `coverage_gaps_validated=[]` in `_state/run-2026-05-23-4e29191a/topic_buses.validate_coverage_gaps_stage.1.json`. Substring keyword match has no concept of context-vs-claim. |
| `consolidate_missing_coverage` (`topic_stages.py:1187`) | **risky** | Token-Jaccard ≥ 0.5 between `perspective_missing_positions[].description` and `coverage_gaps_validated[]`. Stopword list at `topic_stages.py:1138-1143` is small (~30 entries) and tuned against one dossier (2026-05-19 Iran). The 3-char floor + small stopword set can over-merge two pages talking about the same domain (oil/shipping). Inverse failure mode is the same class as A.2: literal token overlap is a proxy for semantic match. On the Cuba TP this is *not* triggering (because `coverage_gaps_validated` is empty); on a healthy TP it would. Comment at `topic_stages.py:1145-1151` itself notes "hand-tuned against the 2026-05-19 Iran dossier" — i.e. n=1 calibration. No TP example of over-merge surfaces in the audit corpus, but on this issue it cannot help recover: the gaps it would dedup against are already gone. |
| `derive_mentioned_actors` (`topic_stages.py:1302`) | **safe** | Pure set arithmetic over actor IDs: `clustered_ids = ∪ cluster.actor_ids`, then `actors[i].id ∉ clustered_ids → orphan` (`topic_stages.py:1337-1369`). Tier classification at `topic_stages.py:1259-1291` is structural (any `verbatim.strip()`? then "stated"; else any `position.strip()`?). No string-content interpretation. Region/language counts use `normalise_country` / `normalise_language` against `final_sources` (table lookups, not similarity). |
| `prune_unused_sources_and_clusters` (`topic_stages.py:1502`) | **safe** | Drop rule is reference-counting on `src-NNN` IDs (`topic_stages.py:1428-1483`) — scans `perspective_clusters_synced[].source_ids[]`, `qa_divergences[].source_ids[]`, `merged_preliminary_divergences[].source_ids[]`, and inline `[src-NNN]` matches in article bodies via fixed regex `_SRC_CITATION_RE = re.compile(r"\[(src-\d+)\]")`. No semantic interpretation; the cluster drop rule (`topic_stages.py:1561-1583`) is the binary "both `actor_ids` and `source_ids` empty". `bias_language_findings` + `coverage_gaps_validated` are deliberately not scanned, codified by contract test `test_bias_and_gaps_emit_no_inline_src_markers` (`topic_stages.py:1440-1449`). |
| `gravitational_assign` (`src/stages/gravitational_assign.py:1`) | **safe** (within its own contract) | Cosine threshold T=0.55 on fastembed embeddings, per-finding cap=3, `np.lexsort` tie-break. Empirically validated at 8.23 % aggregate off-topic across 30 audited top-10 topics (post-Brief-5b, `docs/cluster-quality-audit/audit-2026-05-16-recalibrated/`). Its calibration is the most disciplined of all semantic-deterministic stages. The risk floor is the embedding model + threshold; both are pinned. Off-topic drift is the visible failure mode and it is regularly re-audited. |
| `cluster_to_finding_assignments` (`src/stages/cluster_to_finding_assignments.py:64`) | **safe** | Pure ID propagation: takes LLM cluster→topic mapping, looks up each cluster's `source_ids[]` in `curator_pre_clusters`, propagates them to topic assignments, applies `PER_FINDING_CAP=3` in LLM emit-order. No semantic decisions of its own. |
| `pre_cluster_findings` (`src/stages/pre_cluster.py:154`) | **safe** | Agglomerative clustering at `T=0.7`, `linkage=average`, `metric=cosine`. Same fastembed singleton. Audited in Brief 5b at the recalibrated configuration. |
| `resolve_actor_aliases` *consumer code* (`src/agent_stages.py:2589-2655`, post-LLM merge) | **safe** | The LLM emits `{aliases: {alias_id: canonical_id, ...}, anonymous_flags}`. The consumer is pure ID arithmetic: union `source_ids` and `quotes` from each `alias_id` into the canonical record (`agent_stages.py:2620-2630`); build audit trail sorted by numeric alias_id (`agent_stages.py:2644-2655`). The LLM is the semantic decision; the consumer just merges. Risk lives in the LLM call, not the deterministic apply. |
| `consolidate_actors` (`topic_stages.py:357`) | **risky-but-known** | Dedup is **exact case-sensitive string match** on `actor.name` (`topic_stages.py:367-370`): "Donald Trump" / "President Trump" / "Trump" yield three entries — the docstring explicitly flags this and points to alias-resolution as the deferred fix. The under-merge is intentional pre-resolve; over-merge is impossible by construction. Once `ResolveActorAliasesStage` runs downstream, names collapse via LLM judgment, so this stage's over-conservative dedup is corrected. No corruption risk. |
| `merge_sources` (`topic_stages.py:79-106`) | **safe** | Pure list concatenation `list(hpd.sources) + list(rad.sources)` (no dedup, no semantic match). Coverage gaps now come solely from HydrationPhase2 (`topic_stages.py:94-98`, refactor `2f46bd5`). |
| `enrich_perspective_clusters` (`topic_stages.py:954`, logic at `topic_stages.py:725-952`) | **safe** | Three structural checks: (1) sub-list IDs must be in `canonical_actors[]`; (2) pool-source consistency `cluster.stated ⊂ canonical_actors_stated`; (3) cross-tier dedup with priority `stated > reported > mentioned`. All set arithmetic on IDs. Region/language counts via `normalise_country` / `normalise_language` lookups. |
| `cleanup_stale_references` (`topic_stages.py:1625`) | **safe** | Same reference-counting pattern as prune: filter `source_ids[]` against `cited_src_ids = {final_sources[i].id}` (`topic_stages.py:1662-1667`). For divergences/gaps `_filter_src_id_collection` (`topic_stages.py:1784-1801`) drops entries whose `source_ids` field is empty post-filter — note this can drop a **gap** when its `source_ids` list ends up empty after prune-driven src loss. Not a semantic decision; an integrity decision. |
| `propagate_outlet_metadata` (`topic_stages.py:289`) | **safe** | Lookup-table copy from `config/sources.json` onto sources by exact outlet-name match (`topic_stages.py:321-336`). No string interpretation. |
| `normalize_pre_research` (`topic_stages.py:624`) | **safe** | Recursive exact-string ID rewriter using `id_rename_map`. `_rewrite_ids_in_value` at `topic_stages.py:599-613` is deliberately exact-match-only ("not regex sub-token") — the docstring calls out the false-positive risk explicitly. |
| `partition_canonical_actors_by_evidence` (`topic_stages.py:487`) | **safe** | Splits actors by the `evidence_type` field already on `quotes[i]`. No new semantic decision; just routing. |
| `filter_media_actors_quoted` (`topic_stages.py:170`) | **safe** | Drops `actors_quoted[i].type=='media'` entries. Field-equality check; no string interpretation. |
| `strip_stale_quantifiers` (`_helpers.py:235`) | **risky** | Same lineage as the broken validator — commit `f6a4c14`, also keyword-pattern-based. Operates on `selection_reason` text via regex patterns at `_helpers.py:210-232` ("only N outlets", "few sources", "limited coverage", "single source", "narrow coverage"). Has an "all sentences stripped → return original" safety net (`_helpers.py:266-272`). False-negatives (missed stale phrasing) are likely; false-positives (stripping a legitimate use of "limited reach") possible but lower stakes than the validator's silent total drop. No TP-level failure has been logged for this stage in the audit corpus that I found. |

**Tail observation:** the two stages from commit `f6a4c14` (`validate_coverage_gaps`, `strip_stale_quantifiers`) are both **keyword-substring-pattern matchers** masquerading as semantic validators. Every other deterministic stage either (a) operates on structural IDs / set arithmetic / lookup tables, (b) does numeric similarity with audited thresholds (`gravitational_assign`, `pre_cluster_findings`), or (c) does exact-string dedup with downstream alias resolution as the backstop (`consolidate_actors`). The class of "semantic claim → substring keyword check → silent drop" is unique to `validate_coverage_gaps` (and to a milder degree `strip_stale_quantifiers`); the rest of the deterministic surface is structurally sound.

---

## Issue B — Actor descriptions in source language instead of English

### B.1 Producer agent + exact prompt+schema location

**Two producers feed `final_actors[].role` in the canonical hydrated pipeline:** `HydrationPhase1Stage` and `ResearcherAssembleStage`. Both emit a per-source `actors_quoted[].role` string that is propagated downstream LLM-untouched. The producer is decided by which dossier-half the source originated from; both halves merge into one bus slot.

**Origin schemas (LLM-emitted, strict-mode):**

- `RESEARCHER_ASSEMBLE_SCHEMA` — `src/schemas.py:162` declares `actors_quoted[].role` as `{"type": "string"}` (no `description`, no language constraint). Required at `src/schemas.py:168`.
- `HYDRATION_PHASE1_SCHEMA` — `src/schemas.py:456` declares `actors_quoted[].role` identically as `{"type": "string"}` with no description. Required at `src/schemas.py:470`.

**Producer wrappers:**

- `HydrationPhase1Stage` at `src/agent_stages.py:2181-2242` — chunked + parallel Phase-1 calls (model `deepseek/deepseek-v4-pro`); writes `hydration_phase1_analyses[].actors_quoted[]` (which includes `role`).
- `ResearcherAssembleStage` at `src/agent_stages.py:1261` (model `deepseek/deepseek-v4-flash`); writes `researcher_assemble_dossier.sources[].actors_quoted[]` (which includes `role`).

**Pass-through chain (LLM-untouched once emitted):**

1. `assemble_hydration_dossier` at `src/stages/topic_stages.py:1982` walks each Phase-1 article-analysis and threads `role` straight onto `hydration_pre_dossier.sources[].actors_quoted[].role` — line `2025`: `"role": actor.get("role", "")`. ResearcherAssemble's roles already sit on `researcher_assemble_dossier.sources[].actors_quoted[].role` as emitted.
2. `merge_sources` at `src/stages/topic_stages.py:79` concatenates both dossier source lists into `merged_sources_pre_renumber`.
3. `renumber_sources` at `src/stages/topic_stages.py:118` re-IDs only the source-level `id` field; `actors_quoted[].role` is preserved verbatim inside the deep-copied source dicts.
4. `filter_media_actors_quoted` at `src/stages/topic_stages.py:170` drops `type=media` entries but does not touch `role` on retained entries.
5. `propagate_outlet_metadata` at `src/stages/topic_stages.py:289` only adds outlet-level metadata; never touches `role`.
6. `consolidate_actors` at `src/stages/topic_stages.py:357` flattens `final_sources[].actors_quoted[]` into `final_actors[]` and propagates `role` as-is — line `415`: `role = entry.get("role") or ""`, line `436`: `"role": role,` inside the new record. First-encountered value wins on dedup collisions, the comment at line `372` is explicit: "For role/type conflicts (the same actor name classified differently across sources) the first encountered value wins."
7. `src/render.py:168` emits `"final_actors": list(topic_bus.final_actors)` into the rendered TP, unaltered.

**Confirmation that no stage mutates `role` between emission and rendering:** zero hits for `role.{lower,translate,replace}` between the LLM-emit point and `render.py`. Empirical verification on the three sample TPs shows every quoted `evidence_type` is `stated` or `reported`, both of which only HydrationPhase1 sets — so the three architect-listed examples originated from HydrationPhase1; the same pipeline shape applies symmetrically to ResearcherAssemble-emitted roles. The value flows LLM-untouched.

### B.2 Current prompt language-handling

Both candidate producer prompt-pairs read end-to-end and grepped for `English`, `language`, `translate`, `respond in`, `output language`.

**`agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md`:**

- **No English-output directive anywhere.** The single `language` references are: input articles carry a `language` field (informational), and one directive on `verbatim_quote`: line 18 — *"the actor's words exactly as they appear in the article, in the original language, with the article's quotation marks"* — and line 84 (Rule 3) — *"`verbatim_quote` contains the actor's direct speech exactly as it appears in the article, in the original language, with the article's quotation marks."* That is the only language directive in the prompt, and it scopes to `verbatim_quote` only.
- The `role` field's only description, line 14: *"`role` — the actor's role or title."* No language guidance.
- The examples at lines 45 / 59 happen to be in English (*"German Federal Minister for Economic Affairs and Climate Action"*, *"Prime Minister of Pakistan"*) — illustrating intent by example, but not constraining behavior. With `verbatim_quote` immediately below explicitly mandating "original language", a Flash-class model has every reason to read the absence of a parallel English directive on `role`/`position` as licence to mirror the source.

**`agents/researcher/ASSEMBLE-SYSTEM.md` + `ASSEMBLE-INSTRUCTIONS.md`:**

- **No English-output directive anywhere.** SYSTEM.md is a single sentence; INSTRUCTIONS.md mentions "language" only on (a) input snippets having a `language` field, (b) `sources[].language` is an ISO 639-1 code, (c) `verbatim_quote` rule at line 22 — *"the actor's words in the original language if the snippet contains a direct quote, otherwise `null`."*
- `role` description at line 19: *"`role` — the actor's role or title."* Identical wording to Phase-1, no language guidance.
- Example role at line 47: *"French Minister for Digital Affairs"* — exemplifies English-output by demonstration but not by directive.

**Schema field descriptions:** `src/schemas.py` around both `role` fields (lines 161-172, 455-471). Neither schema attaches a `description` to `role` at all. There is no schema-level English constraint.

**Conclusion:** Both prompts treat `verbatim_quote` explicitly (must stay in source language) and treat `role`/`position` as unconstrained free strings. There is no directive — system, instruction, schema, or example-tag — telling the agent that `role` and `position` should be English. The behavior observed in the affected TPs is the model defaulting to source-language pass-through for these unconstrained string fields, which is consistent with the architect's hypothesis.

### B.3 Source-language pattern check

For three architect-recommended examples (rendered actor → source language lookup):

- **tp-2026-05-20-001 / actor-014 — "Porte-parole du Kremlin":** `source_ids = ["src-011"]`. `sources[]` lookup: `src-011` is RFI (`outlet="RFI"`, `country="France"`, `language="fr"`). Russian-speaking entity (Kremlin spokesperson), but the *quoting* source is French-language RFI — role is rendered in French = quoting-source language.
- **tp-2026-05-21-001 / actor-043 — "Chef de la diplomatie italienne" (Antonio Tajani):** `source_ids = ["src-009", "src-010"]`. `src-009` is RFI (`fr`), `src-010` is Tagesschau (`de`). Italian minister quoted via FR and DE outlets; role is in French — matches the **first** `source_id` (`src-009`, `fr`). Consistent with `consolidate_actors`' first-encountered-wins rule (line 372).
- **tp-2026-05-22-003 / actor-001 — "Coordenadora de Saúde da Coordenadoria de Controle de Doenças de São Paulo":** `source_ids = ["src-001"]`. `src-001` is Agencia Brasil (`outlet="Agencia Brasil"`, `country="Brazil"`, `language="pt"`). Brazilian official quoted via PT outlet; role is in Portuguese = source language.

**Pattern (one sentence):** `final_actors[i].role` strictly tracks the **language of the first quoting source** (per `consolidate_actors`' insertion-order first-wins dedup), not the actor's nationality or the outlet's country — i.e., the producing LLM writes `role` in the article's source language, and the deterministic consolidation locks in the language of whichever source happened to surface the actor first.

This pattern applies symmetrically to `position` strings inside `quotes[]`: a broader scan across the eight affected TPs in 2026-05-2[0-3] flags non-Latin-1-clean role strings on **most** of the listed examples *and* an additional ~70 `position` entries across the same files (e.g. tp-20-001 actor-003 position *"Affirme que les deux pays ont approfondi sans cesse la confiance politique mutuelle..."*; tp-21-002 actor-005 *"Annonce que l'Iran a reçu les vues américaines..."*; tp-22-003 actor-001 position text begins in English but quotes Portuguese verbatim mid-sentence). `position` and `role` both ride the same producer-language pass-through; the same fix surface covers both.

### B.4 Remediation options with trade-offs

**(a) Add an English-output directive to producer prompts (PHASE1-INSTRUCTIONS.md + ASSEMBLE-INSTRUCTIONS.md).**
- *One-time effort:* PE drafts one or two sentences, CC writes verbatim. Smallest possible change surface. Two files to touch (both producers). Zero test churn.
- *Per-run cost:* ~zero — a handful of additional prompt tokens, amortized across all topics. No new LLM call.
- *Reliability:* depends on model compliance. Flash-class (Phase 1 = deepseek-v4-pro; ResearcherAssemble = deepseek-v4-flash) tends to follow explicit positive directives well, especially when the directive is contrasted against the existing "original language" rule on `verbatim_quote`. Past empty-output-mode evidence (CLAUDE.md §empty-retry) shows these models can be brittle on edge cases, so compliance is high-but-not-perfect; a fraction of roles may still leak source language on cache-cold paths.
- *Side-effects:* the same directive can address `position` simultaneously (one rule covering both fields). Risk of over-translating proper-noun titles that are best left untranslated (e.g. "Bundeskanzler" vs "Federal Chancellor of Germany" — both are defensible). PE judgment needed on whether to demand translation or accept English-form equivalents.

**(b) Add a deterministic post-stage that detects and acts on non-English role/position strings.**
- *One-time effort:* high. There is no clean Python primitive for "is this string English." Options: (i) language-detect library like `langdetect` or `fasttext-lid` — adds a dependency (CLAUDE.md §Dependencies: "no new dependencies without explicit approval"); (ii) heuristic on non-ASCII characters — false positives on "São Paulo", "Médecins Sans Frontières", and any English text with accented loanwords; (iii) LLM-based language tag — defeats the purpose of "deterministic post-stage" and reintroduces an LLM call. None are clean.
- *Per-run cost:* (i) free CPU; (ii) free CPU; (iii) ~one extra cheap LLM call per actor — non-trivial at ~60 actors per TP. Auto-translate-if-non-English variant adds a translation call per offending entry.
- *Reliability:* low. The detection step is the bottleneck — under-detect (heuristics miss roles that happen to be cognates like "Ministro" vs "Minister") and over-detect (every accented English string flagged). A drop-or-flag policy loses information; an auto-translate policy can introduce semantic drift in titles that have no clean English equivalent.
- *Side-effects:* if implemented as a separate stage on `consolidate_actors`'s output, the same logic applies symmetrically to `position` and could later extend to `final_sources[].title` (which is intentionally original-language per ASSEMBLE-INSTRUCTIONS.md line 65) — risk of accidentally translating fields that *should* stay original. Stage-ordering would have to be careful.

**(c) Require both `role_original` and `role_english` (and symmetrically for `position`).**
- *One-time effort:* high. Schema migration in two schemas (`RESEARCHER_ASSEMBLE_SCHEMA`, `HYDRATION_PHASE1_SCHEMA`), both producer prompts (PE-authored), `consolidate_actors` (route both fields), `render.py` (decide which to expose), all snapshot/fixture tests, and a renderer-level decision about whether the public TP exposes one or both forms. Cascades into `position` symmetrically, doubling actor-record field count from {name, role, type, position} to {name, role_original, role_english, type, position_original, position_english}.
- *Per-run cost:* approximately doubles the output-token budget for the per-actor extraction block. With 60 actors per TP, this is non-trivial; estimate +15-25% on Phase-1 and ResearcherAssemble output tokens.
- *Reliability:* high, structurally. The model is forced to think in both languages and the consumer can pick. Compliance on populating both fields tends to be strong when both are `required` in strict-mode JSON.
- *Side-effects:* much richer downstream — perspective clusters, source maps, and bias cards can reference the original-language form for audit while showing the English form to readers. Cleanest schema. But it is a meaningful migration with downstream consumer churn, and it does not solve the issue retroactively for the eight already-shipped TPs (which the cheaper options also don't, but for option (c) the cost-benefit window is narrower against re-rendering, since re-rendering won't backfill `role_original` for existing TPs without a re-run).

**Cross-cutting note on `position`:** all three options should be evaluated against the joint `role`+`position` surface. The B.3 scan confirms `position` exhibits the identical pattern at higher volume (~70 vs ~25 entries), so any chosen remediation should explicitly cover both fields, not just `role`. Options (a) and (c) handle this naturally; option (b) needs the detection step extended to both fields.

---

## Issue C — Position cards with `n_actors == 0`

### C.1 Data-flow trace of `position_cluster.actor_ids` across the hydrated pipeline

`build_hydrated_stages` lives at `src/runner/stage_lists.py:250-345`. The relevant slice of the hydrated topic-stage list (in execution order) and the read/write contract for `perspective_clusters` / `perspective_clusters_synced` and any field whose entries carry `actor_ids[]`:

| # | Stage | Reads `actor_ids`? | Writes `actor_ids`? | What it does to them | file:line |
|---|---|---|---|---|---|
| 1 | `consolidate_actors` | no | no (writes `final_actors[]`) | Flattens `final_sources[].actors_quoted[]` into `actor-NNN` entries. No `actor_ids[]` involved yet. | `src/stages/topic_stages.py` consolidate region |
| 2 | `ResolveActorAliasesStage` | no | no (writes `canonical_actors[]` + `actor_alias_mapping[]`) | Merges aliased `actor-NNN` IDs first-source-wins; **runs BEFORE** PerspectiveStage. | `src/agent_stages.py:2477-2672` |
| 3 | `partition_canonical_actors_by_evidence` | no | no (writes `canonical_actors_{stated,reported,mentioned}[]`) | Splits canonical actors into three pools by per-quote `evidence_type`. PerspectiveStage reads these pools. | `src/stages/run_stages.py` (partition stage) |
| 4 | `PerspectiveStage` (LLM, claude-opus-4.6) | reads the three canonical-actor pools | no (does **not** emit `actor_ids[]` — emits only `stated/reported/mentioned` sub-lists) | LLM emits raw cluster shape `{position_label, position_summary, source_ids, stated, reported, mentioned}`. Sub-lists may be empty. | `src/agent_stages.py:1342-1416`; schema `src/schemas.py:195-256` |
| 5 | `enrich_perspective_clusters` | reads each cluster's `stated/reported/mentioned` | **derives** `actor_ids = sorted(set(stated) ∪ set(reported) ∪ set(mentioned))` and writes back into `perspective_clusters` | Cleans sub-lists against `canonical_actors`, enforces pool-source consistency, deduplicates cross-tier with priority `stated > reported > mentioned`, then computes the flat union. **Empty sub-lists produce empty `actor_ids`.** | `src/stages/topic_stages.py:725-999` (write at `:929`; computation at `:914`) |
| 6 | `mirror_perspective_synced` (1st pass) | reads `perspective_clusters` | mirrors verbatim into `perspective_clusters_synced` (1:1 copy because second slot is empty) | `mirror_stage(..., granularity="element")`. Pure copy at this stage. | `src/stages/topic_stages.py:1007-1029` |
| 7 | `WriterStage` | reads `perspective_clusters_synced` (passes verbatim to writer agent) | no (writes `writer_article`) | Article writer; no cluster mutation. | `src/agent_stages.py:1424-1536` |
| 8 | `QaAnalyzeStage` | no | no (writes `qa_*` slots only) | QA on the article body, not clusters. | `src/agent_stages.py` QA region |
| 9 | `mirror_qa_corrected` | no | no | Slot-level mirror on `qa_corrected_article` only. | `src/stages/topic_stages.py:1041-1057` |
| 10 | `PerspectiveSyncStage` (LLM, hydrated only) | reads `perspective_clusters` | emits **deltas** that may set `position_label` / `position_summary` (does **not** emit `actor_ids` per schema) | Gated: only fires when `qa_corrections[].correction_needed` is truthy. Delta-merges into `perspective_clusters_synced`. Sub-lists and `actor_ids[]` pass through unchanged from upstream (`src/bus.py:709-723`). | `src/agent_stages.py:2313-2391` |
| 11 | `mirror_perspective_synced` (2nd pass) | reads `perspective_clusters` | element-merges deltas back into `perspective_clusters_synced` | Idempotent for the no-delta path. Preserves `actor_ids` already in place. | `src/stages/topic_stages.py:1007-1029` |
| 12 | `prune_unused_sources_and_clusters` | reads `cluster.actor_ids` AND `cluster.source_ids` | rewrites `perspective_clusters_synced` (drops clusters where **both** `actor_ids` AND `source_ids` are empty) | A cluster with empty `actor_ids` but non-empty `source_ids` (exactly our case) is **kept**. | `src/stages/topic_stages.py:1486-1592` (drop condition at `:1569`) |
| 13 | `cleanup_stale_references` | reads `cluster.actor_ids`, `cluster.source_ids`, sub-lists | rewrites `perspective_clusters_synced` (filters `actor_ids[]` and sub-lists against `surviving_actor_ids`; drops clusters whose `source_ids` becomes empty after filtering) | Only mutation that touches `actor_ids` post-PerspectiveStage. Filters but cannot create. Source-id–driven drop. | `src/stages/topic_stages.py:1600-1781` (filter at `:1767-1781`) |
| 14 | `compute_source_balance` | no | no | Aggregates language/country from sources only. | `src/stages/topic_stages.py:1065-…` |
| 15 | `derive_mentioned_actors` | reads `perspective_clusters_synced[].actor_ids` | no (writes `mentioned_actors` bracket) | Collects every canonical actor whose ID does **not** appear in any cluster's `actor_ids`. Pure consumer. | `src/stages/topic_stages.py:1302-1417` |
| 16 | `BiasLanguageStage` / `compose_transparency_card` | irrelevant — no cluster mutation | no | – | – |

**Key observations:**
- The agent never emits `actor_ids[]` directly. The flat field is computed by `enrich_perspective_clusters` (`src/stages/topic_stages.py:914`) as `sorted(set(stated) ∪ set(reported) ∪ set(mentioned))`. If the agent emits all three sub-lists empty, `actor_ids` is empty by construction — there is no "loss" downstream.
- The resolver runs BEFORE PerspectiveStage. Dangling alias IDs from canonical resolution cannot be the cause.
- `prune` only drops a cluster when `actor_ids` **and** `source_ids` are both empty. Affected clusters survive prune because their `source_ids` are populated.
- `cleanup_stale_references` filters `actor_ids[]` against surviving canonical actors but cannot create new ones.

### C.2 Snapshot walk for tp-23-001 affected clusters

Topic 0 of `output/2026-05-23/_state/run-2026-05-23-4e29191a/`. Walked snapshot files in hydrated stage order. Counts shown are `len(actor_ids)`; `(stated/reported/mentioned)` shown to confirm origin.

| Snapshot file | Stage | pc-003 | pc-005 | pc-007 | pc-008 |
|---|---|---|---|---|---|
| `topic_buses.PerspectiveStage.0.json` | `PerspectiveStage` (LLM out) | sub-lists [], [], [] | sub-lists [], [], [] | sub-lists [], [], [] | sub-lists [], [], [] |
| `topic_buses.enrich_perspective_clusters.0.json` | `enrich_perspective_clusters` | `actor_ids=[]` (0) | `actor_ids=[]` (0) | `actor_ids=[]` (0) | `actor_ids=[]` (0) |
| `topic_buses.mirror_perspective_synced.0.json` | `mirror_perspective_synced` (1st) | sync 0 / raw 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `topic_buses.WriterStage.0.json` | `WriterStage` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `topic_buses.QaAnalyzeStage.0.json` | `QaAnalyzeStage` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `topic_buses.mirror_qa_corrected.0.json` | `mirror_qa_corrected` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `topic_buses.PerspectiveSyncStage.0.json` | `PerspectiveSyncStage` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `topic_buses.prune_unused_sources_and_clusters.0.json` | `prune` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `topic_buses.cleanup_stale_references.0.json` | `cleanup_stale_references` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `topic_buses.derive_mentioned_actors.0.json` | `derive_mentioned_actors` | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

**Born-empty signature.** The PerspectiveStage raw output snapshot (`topic_buses.PerspectiveStage.0.json`) shows the four affected clusters with explicitly empty sub-lists:

```
pc-003: stated=[]  reported=[]  mentioned=[]   n_src=4
  label: "China's coal mines remain among the world's deadliest due to ..."
pc-005: stated=[]  reported=[]  mentioned=[]   n_src=4
  label: "China's dependence on coal as a strategic energy source ..."
pc-007: stated=[]  reported=[]  mentioned=[]   n_src=1
  label: "Chinese authorities use rapid compensation to silence ..."
pc-008: stated=[]  reported=[]  mentioned=[]   n_src=1
  label: "Media transparency around Chinese mining disasters ..."
```

For comparison, sibling clusters in the same snapshot have populated sub-lists: `pc-001: stated=['actor-001'] reported=['actor-001','actor-003','actor-004','actor-005']`, `pc-002: reported=['actor-006']`, `pc-004: stated=['actor-002']`, `pc-006: reported=['actor-004']`. Canonical actors `actor-001` … `actor-008` are all present in `topic_buses.partition_canonical_actors_by_evidence.0.json` (`canonical_actors_stated=2`, `canonical_actors_reported=7`, `canonical_actors_mentioned=0`). So the actors **exist** in the input pools; the Perspective agent simply chose to assign none of them to these four clusters.

**Transition stage:** there is none. The clusters are born empty at `PerspectiveStage`. Every downstream snapshot is consistent with the upstream raw output.

**Cross-topic confirmation:**

- `output/2026-05-22/_state/run-2026-05-22-5d9a1bb7/topic_buses.PerspectiveStage.1.json` — tp-22-002 pc-007: `stated=[] reported=[] mentioned=[]`. Born empty.
- `output/2026-05-20/_state/run-2026-05-20-7d509f17/topic_buses.PerspectiveStage.0.json` — tp-20-001 pc-008: `stated=[] reported=[] mentioned=[]`. Born empty.

The pattern holds across all three audited topics: the Perspective agent emits these clusters with empty actor sub-lists at the very first stage that touches them.

### C.3 Root cause classification + one-sentence remediation sketch

**Classification: (a) the Perspective agent emits clusters with all three actor sub-lists empty — the clusters are born empty.**

Mechanism: the Perspective system prompt (`agents/perspective/INSTRUCTIONS.md:5-11`) explicitly licenses source-level clusters — positions grounded in a source's `summary`/`title` rather than in any `actors_quoted[]` entry. The schema `src/schemas.py:218-219` echoes this: "Sub-lists may be empty when no actor falls into that tier for the cluster." The four affected pc clusters on tp-23-001 are framing/structural-claim positions — "China's coal mines remain among the world's deadliest", "Media transparency around Chinese mining disasters has improved" — that the agent grounds in 1–4 source headlines/summaries (`source_ids` non-empty) but cannot bind to any specific canonical actor's stated/reported/mentioned position. Same pattern on tp-22-002 pc-007 ("severe financial market instability requiring emergency central bank intervention", source-level claim from market reporting) and tp-20-001 pc-008 ("Russia-China axis poses direct security threats", analytic-frame claim from outlet editorial framing).

This is not (b) — the resolver runs before PerspectiveStage and the agent already operates on the post-resolution `canonical_actors_*` pools, so cross-stage alias drift cannot strip `actor_ids`. It is not (c) — `prune_unused_sources_and_clusters` only drops a cluster when both `actor_ids` and `source_ids` are empty (`src/stages/topic_stages.py:1569`); these clusters have non-empty `source_ids` and survive. `cleanup_stale_references` only filters against survivors; it cannot empty an already-empty list.

**Remediation sketch:** the legitimate root-cause fix is **at the Perspective agent prompt level** — either tighten the prompt so source-level clusters are required to surface the outlet/media canonical-actor IDs (which would migrate "the outlet itself" into the `reported` sub-list, populating `actor_ids` deterministically), or accept zero-actor source-level clusters as legitimate and update the renderer (`src/render.py:388-393`) to treat `n_actors==0` as a "source-grounded position (no individual speaker)" annotation rather than a defect; no downstream code change is needed because the data flow is already correct.
