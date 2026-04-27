# Pipeline Audit — S13 Post-Rewrite

**Date:** 2026-04-27
**Auditor:** Claude Code (audit task)
**Scope:** All thirteen active agents, the production and hydrated pipeline code, and the most recent debug output.
**Reference runs:** `output/2026-04-27/` (production, partial from `--from researcher --topic 1`); `output/2026-04-15/test_hydration/` (hydrated, today's smoke against 2026-04-15 cached assignments). Earlier full runs at `output/2026-04-19/` and `output/2026-04-20/` predate the S13 pipeline-code refactor and are referenced only for shape comparison.

---

## Executive summary

The S13 prompt rewrite produced cleaner, shorter prompts on disk than the pipeline had pre-rewrite. The pipeline code that consumes them, however, was rewritten on a different rhythm and is still partially out of sync with the prompts on two fronts. **First**, two of the thirteen prompts (Curator and Editor) on disk still describe the pre-S13 output shape. The pipeline code now expects the new shape *and* falls back to the old, so production runs do not break — but the agents are still being asked to emit fields Python is also producing (Curator `source_ids`, Editor `id` and `topic_slug`), which was the entire point of the S13 rewrite. Until those two prompts are rewritten to match the new pipeline contract, the rewrite hasn't actually shipped end-to-end for those two agents.

**Second**, the legacy `message=` parameter on `Agent.run()` is still being used as the per-call user message at three call sites (Perspektiv, Writer, QA+Fix, Bias Language). For Perspektiv this leaks V1 vocabulary ("stakeholders, missing voices, framing divergences") into the User turn alongside the V2 INSTRUCTIONS that ask for `position_clusters` and `missing_positions`. The other three are generic restatements of the prompt task — harmless tokens, but token-redundant.

Beyond those drift issues, the pipeline-Python boundary is in good shape. Every Python-computable deterministic field (rsrc-NNN, pc-NNN, src-NNN renumbering, slugs, dates, counts, representation classification) lives in Python after S13. The Hydration Aggregator's two-phase split is clean. The Bias Card aggregation is a textbook example of a Python pre-aggregation feeding an LLM that adds only originary content. Perspektiv-Sync V2 is structurally sound — V1 stub gone, eligibility gate uses `proposed_corrections`, null-defense in `merge_perspektiv_deltas`.

The most actionable backlog of findings is concentrated at three boundaries: the Curator/Editor prompts vs the pipeline contract, the Editor prompt's pipeline-architecture leaks (six separate sentences mentioning "downstream pipeline stages"), and a handful of unused or duplicated context fields at the Perspektiv/Writer/QA call sites that are wasting tokens at Opus rates without changing any output.

### Top findings (ranked by impact)

1. **Curator prompt still emits the legacy `topics[].source_ids` shape**; the new `cluster_assignments[]` envelope the pipeline expects is never produced. Python's fallback masks the issue at runtime but the rewrite is incomplete.
2. **Editor prompt still emits `id` and `topic_slug`**; Python overwrites both deterministically. The agent is paying for fields Python throws away.
3. **Editor prompt has six sentences referencing "downstream pipeline stages" or "the third agent"** — the prompt's largest source of pipeline-architecture leakage and a magnet for confusion on future model swaps.
4. **Perspektiv runtime user message says "Map all stakeholders, identify missing voices, surface framing divergences"** (V1 vocabulary) while INSTRUCTIONS asks for V2 cluster output.
5. **Writer context passes `position_clusters` and `missing_positions` twice** — once nested under `perspective_analysis` (where the prompt reads them) and once at the top level (unused). Pure token waste at Opus rates.
6. **QA+Fix prompt declares `coverage_gaps[]` in its input** but the call site doesn't pass it. Functionally harmless because the prompt never references it in steps, but a real input-contract drift.
7. **`TopicAssignment.raw_data` is always `{}` after the Editor**, because the Editor prompt doesn't carry `raw_data` in its output. Researcher Plan's prompt says `raw_data` carries the topic's metadata; in practice the planner runs on `title + selection_reason` only.
8. **Perspektiv prompt does not describe how `actors[]` get populated** — the prompt emits clusters with `source_ids[]` only, then Python's `_enrich_position_clusters` walks the dossier to add `actors`/`regions`/`languages`/`representation`. The actor field rename (`verbatim_quote` → `quote`) is also undocumented.
9. **Editor prompt rule "NEVER assign the same priority to more than two topics"** is a hard quantitative rule the LLM cannot self-enforce reliably across runs. Python should enforce it post-hoc or the rule should be relaxed to "differentiate priorities where possible."
10. **Bias Language INSTRUCTIONS rule 4 plus the long category description block (lines 5–15)** restate ground covered in the bias card structure. Largest-density redundancy in the bias prompt.

---

## Caveats

- The most recent **complete** production run on disk (`2026-04-20/`) predates the S13 pipeline refactor and uses the V1 perspective shape. The smoke run at `2026-04-27/` is a partial run started from `--from researcher --topic 1`, so the Curator and Editor stages were not exercised live in the post-S13 code path. Their input/output audit relies on prompt + pipeline-code reading, not a live debug snapshot.
- The post-S13 hydrated reference at `2026-04-15/test_hydration/` is one topic only (1/1 TPs). Cross-topic patterns (e.g. across the Editor's three-topic priority differentiation rule) cannot be observed.
- The prompt-engineer's INSTRUCTIONS.md content for Curator and Editor on disk is the **pre-S13 shape** (legacy `source_ids`, legacy `id`/`topic_slug`). The pipeline code has the new shape implemented with backward compatibility. This audit treats the disk state as authoritative for prompt content but flags every spot where prompt and code disagree.
- No Collector agent live run exists; the prompt files at `agents/collector/{AGENTS,PLAN,ASSEMBLE}.md` are still on the legacy single-file convention because the agent is disabled and only used as a fixture for `tests/test_tools.py`.

---

## Per-agent analysis

### 1. Curator

**Files:** `agents/curator/SYSTEM.md` + `agents/curator/INSTRUCTIONS.md`
**Model:** `google/gemini-3-flash-preview` @ 0.2, reasoning none, no tools.
**Role in pipeline:** Cluster ~1,400 RSS findings into topic candidates and score newsworthiness.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `findings[].id` | `_prepare_curator_input` (`finding-N` form) | Referenced by INSTRUCTIONS step 1 ("note each finding's index position") | Used (positional, not by id literal) |
| `findings[].title` | RSS feed | Required for clustering | Used |
| `findings[].source_name` | RSS feed | Read by Curator for outlet awareness | Context-only |
| `findings[].summary` | RSS feed (when distinct from title) | Read for clustering | Used |

The user-message string at the call site (`"Review these findings. Cluster related findings into topics. Score each topic's newsworthiness on a 1-10 scale."`) is appended inside the `<instructions>` block via the agent.py legacy-message migration safety net. It restates the INSTRUCTIONS task in one line — harmless but redundant.

#### Output audit

| Output field | Downstream consumer(s) | Originarity | Notes |
| --- | --- | --- | --- |
| `topics[].title` | Editor; `_enrich_curator_output` | Originary ✅ | Topic label |
| `topics[].relevance_score` | Curator's own sort; Editor | Originary ✅ | 1-10 |
| `topics[].summary` | Editor | Originary ✅ | 1-3 sentences |
| `topics[].source_ids` (`["finding-N",…]`) | Pipeline `_rebuild_curator_source_ids` (legacy fallback) | **Pass-through-potential** ❌ | Per the S13 brief and the Python helper, this field should be Python-rebuilt from `cluster_assignments[]`. The current prompt still emits `source_ids` directly — the new envelope `{topics, cluster_assignments}` is never produced |
| `cluster_assignments[]` | `_rebuild_curator_source_ids` (new path) | Originary ✅ | **Not currently emitted** by the Curator prompt — the new envelope is described in the S13 brief but the prompt on disk still says "Each object MUST have exactly these four fields … `source_ids`" |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length (INSTRUCTIONS) | 56 lines | Low | Within the 50–100 target |
| Negative listings | 8 (counts: "do not", "must not", "never") | Medium | Most negatives in any prompt outside `# RULES` |
| Mission-speech | 1 ("Independent Wire exists to make bias visible…") | Low | "Intent: Independent Wire exists to make bias visible and provide multi-perspective news analysis." (line 5) |
| Pipeline leaks | 0 | — | None |
| Redundancy | Output schema described twice (steps 1–6, then OUTPUT FORMAT, then RULES) | Medium | The `source_ids` requirement appears in step 6, the OUTPUT FORMAT field list, and rule 2 |
| Vagueness | 0 specific concerns | Low | The 1–10 scale is anchored with concrete bands ("Most topics should score between 3 and 7…") |
| Example density | One worked example object | Low | Concrete and well-structured |

The prompt is well-written prose that the rewrite hasn't actually finished. It still emits `topics[].source_ids` directly instead of the `{topics, cluster_assignments}` envelope the S13 design requires. The Python fallback in `_rebuild_curator_source_ids` keeps production unbroken, but the rewrite's stated benefit (Python owns deterministic clustering bookkeeping) hasn't shipped. A short, targeted rewrite that switches OUTPUT FORMAT to the dict envelope would close the gap.

#### Notable findings

- The user-message string (`"Review these findings. Cluster related findings into topics. Score each topic's newsworthiness on a 1-10 scale."`) restates the prompt and could be dropped — the legacy-message safety net in `agent.py` would log a deprecation warning, prompting a migration to no message at all.
- INSTRUCTIONS step 4 ("MUST be derived only from the title and summary fields") and rule 7 ("MUST NOT add information to the summary") restate the same constraint. Pick one.

---

### 2. Editor

**Files:** `agents/editor/SYSTEM.md` + `agents/editor/INSTRUCTIONS.md`
**Model:** `anthropic/claude-opus-4.6` @ 0.3, reasoning none, no tools.
**Role in pipeline:** Prioritise topics, decide what publishes today, justify each decision.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `topics[]` | Curator (enriched by `_enrich_curator_output`) | Editorial decision base | Used |
| `previous_coverage[]` | `_scan_previous_coverage` (last 7 days) | Follow-up detection | Used |

The Editor reads enriched Curator topics with `geographic_coverage`, `languages`, `source_diversity`, `missing_perspectives`, and counts. The prompt's RULES forbid surfacing those numerics in `selection_reason` text. The fields are still in the input — they steer the editorial decision but never come back out.

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `id` (`tp-YYYY-MM-DD-NNN`) | Pipeline (currently overwritten) | **Pass-through-potential** ❌ | Python's `editorial_conference` regenerates this deterministically by `tp-{date}-NNN` after priority-zero filter and sort. The prompt should stop emitting it |
| `topic_slug` | Pipeline (currently overwritten) | **Pass-through-potential** ❌ | Python's `_slugify(title)` regenerates this. The prompt should stop emitting it |
| `title` | Pipeline; later TP metadata | Originary ✅ | Editor may refine the Curator title |
| `priority` | `editorial_conference` filter+sort | Originary ✅ | 0 = rejected; 1–10 |
| `selection_reason` | TP transparency block | Originary ✅ | 2-4 sentences |
| `follow_up_to` (optional) | TP follow_up assembly | Originary ✅ | Cross-day continuity |
| `follow_up_reason` (optional) | Writer FOLLOWUP context, TP | Originary ✅ | What's new |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length (INSTRUCTIONS) | 77 lines | Low | Slightly above target |
| Negative listings | 9 | High | The most of any prompt. Six of them are in body prose, not RULES |
| Mission-speech | 2 | Medium | "Independent Wire produces transparency-first news coverage that makes bias visible. Your editorial decisions shape what the audience sees." (line 5) and "A weak editorial decision here cascades into weak journalism downstream." (line 5) |
| Pipeline leaks | 6 | High | "third agent in the pipeline" (line 3); "downstream pipeline stages" (lines 19, 49, 74); "downstream" (line 5); "The Writer agent consumes your output" (line 7) |
| Redundancy | The "no source counts in selection_reason" rule appears three times (line 19, line 49, line 74) | High | Same constraint stated as STEPS 4, OUTPUT FORMAT field note, and RULES item 7 |
| Vagueness | "Generic justifications like 'this is an important topic' are unacceptable" with no contrast | Low | Resolved by the Bad/Good example block in rule 7 |
| Example density | Three worked examples (accepted non-follow-up; accepted follow-up; rejected) | Strong | Best example density of any prompt |

The Editor's INSTRUCTIONS is the prompt with the highest signal density of pipeline-architecture leakage and the most repetition. Six separate sentences explain why selection_reason can't carry numerics — the architect's intent is clear (numerics become stale when downstream stages modify the source array) but stating it once with the Bad/Good example would suffice. The "third agent in the pipeline" line in IDENTITY is an explicit architecture leak that the agent does not need.

#### Notable findings

- Rule "NEVER assign the same priority to more than two topics" (line 77) is unenforceable at the LLM level across runs — the Editor sees only this run's topics and can't track historical distribution. Either Python should enforce post-hoc (re-rank ties) or the rule should be relaxed to a soft directive.
- The user-message string (`"Prioritize these topics for today's report. For each, assign a priority (1-10) and a selection_reason. Today's date is {date}."`) duplicates IDENTITY content; the date value could move into the context dict.
- The prompt's STEP 6 ("Assign each topic a unique id following the format tp-YYYY-MM-DD-NNN") is contradicted by the pipeline code, which generates the id deterministically. Drop the step.

---

### 3. Researcher Plan

**Files:** `agents/researcher/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md`
**Model:** `google/gemini-3-flash-preview` @ 0.5, reasoning none, no tools.
**Role in pipeline:** Generate 8–15 multilingual web-search queries per topic.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `title` | TopicAssignment | Anchor for query construction | Used |
| `selection_reason` | TopicAssignment | Editorial framing for queries | Used |
| `raw_data` | TopicAssignment | Per the prompt: "topic's metadata (summary, geographic coverage, languages already present in coverage, identified missing perspectives, source count)" | **Always empty `{}`** — see findings |
| Today's date (in user message) | Pipeline `f"…Today is {self.state.date}."` | Temporal anchor | Used |

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `[].query` | `web_search_tool.execute` | Originary ✅ | The actual search string |
| `[].language` | Pipeline grouping; URL-date enrichment | Originary ✅ | ISO 639-1 |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 62 lines | Low | Within target |
| Negative listings | 1 | Low | Excellent |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | Clean |
| Redundancy | 0 | Low | Clean |
| Example density | 8 worked queries across 6 languages | Strong | One of the best |
| Vagueness | "These pairings are heuristics, not a rigid map" — the language-region mappings | Low | Acceptable framing |

The cleanest prompt of the thirteen. Clear task, concrete heuristics, language-specific guidance, and a strong example block.

#### Notable findings

- The `raw_data` field documented in the prompt is **never populated** by the pipeline. The Editor's output doesn't carry `raw_data`, so `TopicAssignment.raw_data == {}` always. The Curator's enrichment (geographic_coverage, languages, missing_perspectives) — which the prompt explicitly calls out — is silently dropped by the time it reaches the planner. Either fix Python to thread the enrichment through, or remove the `raw_data` field from the prompt's input description.
- The user-message string (`f"Plan multilingual research queries for this topic. Today is {self.state.date}."`) is the only place `today's date` enters the agent's context. Moving the date into the context dict (`{"date": ...}`) would let the prompt reference it cleanly without the legacy-message safety net.

---

### 4. Researcher Assemble

**Files:** `agents/researcher/ASSEMBLE-SYSTEM.md` + `ASSEMBLE-INSTRUCTIONS.md`
**Model:** `google/gemini-3-flash-preview` @ 0.2, reasoning none, no tools.
**Role in pipeline:** Build a structured research dossier from multilingual web-search results.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `assignment.title`, `assignment.selection_reason` | TopicAssignment | Topic context | Used |
| `date` | Pipeline | Currency check | Context-only (the prompt does not use it explicitly) |
| `search_results[]` | `_deduplicate_search_results` output | The corpus | Used |
| `search_results[].url_dates` | `_extract_date_from_url` (pipeline pre-pass) | Optional date hint per URL | Used (referenced by the prompt) |

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `sources[].url, title, outlet, language, country, summary` | Perspektiv input; Writer dossier | Originary ✅ | Per-source extraction |
| `sources[].actors_quoted[]` | Perspektiv enrichment; bias card via `_build_bias_card` | Originary ✅ | Five fields exact: name/role/type/position/verbatim_quote |
| `preliminary_divergences[]` | Perspektiv input; QA+Fix input; bias card | Originary ✅ | One sentence each |
| `coverage_gaps[]` | Perspektiv input; bias card; TP `gaps[]` | Originary ✅ | One sentence each |

The pipeline assigns `rsrc-NNN` ids and backfills `estimated_date` after parsing, so neither field is in the agent's output schema — clean Python-side ownership.

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 84 lines | Low | Within target |
| Negative listings | 5 | Low | Reasonable |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | Clean |
| Redundancy | The "actors_quoted shape: five fields" rule is in the body, the field notes, and rule 3 | Low | Tolerable for a load-bearing schema |
| Vagueness | "When more than 15 usable journalistic sources are available, keep the 15 that maximize diversity" — the diversity criterion is named (language/region/stakeholder type) but not how to break ties | Low | Acceptable |
| Example density | One worked source object with full actor entry | Strong | |

#### Notable findings

- The exclude-list ("YouTube, Wikipedia, Instagram, TikTok, Reddit, X/Twitter, Facebook") in source selection (line 9) and rule 4 is duplicated. One of them suffices.

---

### 5. Researcher Hydrated Plan

**Files:** `agents/researcher_hydrated/PLAN-SYSTEM.md` + `PLAN-INSTRUCTIONS.md`
**Model:** `google/gemini-3-flash-preview` @ 0.5, reasoning none, no tools.
**Role in pipeline:** Same as Researcher Plan but gap-aware: takes a `coverage_summary` from the pre-dossier and targets queries at missing languages/regions/stakeholder types.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `title`, `selection_reason`, `raw_data` | TopicAssignment | Same as base planner | Same caveat: `raw_data == {}` |
| `coverage_summary.{total_sources, languages_covered, countries_covered, stakeholder_types_present, coverage_gaps}` | `build_coverage_summary(pre_dossier)` | Gap targeting | Used heavily |
| Today's date (user message) | Pipeline | Temporal anchor | Used |

#### Output audit

Same shape as Researcher Plan.

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 70 lines | Low | Within target |
| Negative listings | 1 | Low | Excellent |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | Clean |
| Redundancy | The language-region pairing block (lines 18–25) duplicates the base planner's pairings exactly | Low | Sensible to keep both prompts self-contained, but tracking divergence is now two-doc work |

#### Notable findings

- The "When `coverage_summary.total_sources` is below 3, the summary is too thin to inform planning" guidance is well-placed. It anticipates the empty-pre-dossier failure mode the base planner doesn't have to handle.
- The rule "Gap targeting takes priority over redundant coverage" (rule 5) is excellent — it's load-bearing for the hydrated path's value proposition.

---

### 6. Hydration Aggregator Phase 1

**Files:** `agents/hydration_aggregator/PHASE1-SYSTEM.md` + `PHASE1-INSTRUCTIONS.md`
**Model:** `google/gemini-3-flash-preview` @ 0.3, reasoning none, no tools.
**Role in pipeline:** Per-chunk article extraction. Run in parallel across chunks of 5–10 articles via `asyncio.gather`.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `assignment.{title, selection_reason}` | Pipeline | Topic context | Used |
| `articles[].{url, title, outlet, language, country, extracted_text, estimated_date}` | T1 hydration (`hydrate_urls`) | Source material | `extracted_text` is the load-bearing field; the others are pass-through metadata for the analyser |

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `article_analyses[].article_index` | `_validate_phase1_output`; `_merge_phase1_results` (chunk-local → global rewrite) | Originary ✅ | Validation rule 1 |
| `article_analyses[].summary` | `build_prepared_dossier` (pre-dossier `sources[].summary`) | Originary ✅ | Two-three sentences |
| `article_analyses[].actors_quoted[]` | `build_prepared_dossier`; Phase 2 reducer; Perspektiv | Originary ✅ | Five-field actor shape |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 69 lines | Low | Within target |
| Negative listings | 3 | Low | Clean |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | Clean |
| Example density | Two worked analyses across two languages | Strong | Includes a non-Latin verbatim quote |

#### Notable findings

- The fact that the prompt does **not** ask the LLM to count its outputs — that's Python's job (`_validate_phase1_output`) — is a textbook application of the "Deterministic before LLM" principle. Architectural reference for any future agent that produces structured arrays.

---

### 7. Hydration Aggregator Phase 2

**Files:** `agents/hydration_aggregator/PHASE2-SYSTEM.md` + `PHASE2-INSTRUCTIONS.md`
**Model:** `anthropic/claude-opus-4.6` @ 0.1, reasoning none, no tools.
**Role in pipeline:** Cross-corpus reducer. Single call over all merged Phase 1 analyses + per-article metadata.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `assignment.{title, selection_reason}` | Pipeline | Topic context | Used |
| `article_analyses[]` | `_merge_phase1_results` | The corpus | Used |
| `article_metadata[].{article_index, language, country, outlet}` | `_build_article_metadata` | Group articles by language/region | Used |

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `preliminary_divergences[]` | `build_prepared_dossier`; merged dossier; bias card | Originary ✅ | Cross-language sentences |
| `coverage_gaps[]` | `build_prepared_dossier`; merged dossier; bias card; TP `gaps[]` | Originary ✅ | Cross-corpus absences |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 56 lines | Low | Tight |
| Negative listings | 1 | Low | Excellent |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | Clean |
| Example density | One worked output with two divergences and two gaps | Strong | |

#### Notable findings

- Rule 1 ("Differences between two articles within the same language group are not divergences in this sense") is the single most important constraint in the prompt. Without it the Phase 2 reducer would surface trivial article-level diffs and pollute the divergences list.

---

### 8. Perspektiv

**Files:** `agents/perspektiv/SYSTEM.md` + `agents/perspektiv/INSTRUCTIONS.md`
**Model:** `anthropic/claude-opus-4.6` @ 0.1, reasoning none, no tools.
**Role in pipeline:** Group actor positions across the dossier into clusters; identify missing perspective types.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `title`, `selection_reason` | TopicAssignment | Topic context | Used |
| `sources[]` (with `id`, `outlet`, `language`, `country`, `actors_quoted[]`) | Research dossier | Position-source mapping | Used |
| `sources[].url, title, summary` | Research dossier | Per-source identity | **Unused** — the prompt steps and rules reference only `id`, `outlet`, `language`, `country`, and `actors_quoted[]` |
| `preliminary_divergences[]` | Research dossier | "for context" per the prompt | Context-only |
| `coverage_gaps[]` | Research dossier | "for context" per the prompt | Context-only |

The pipeline call site **also** sends a hard-coded user-message string: `"Analyze the research dossier. Map all stakeholders, identify missing voices, and surface framing divergences between regions and language groups."` That sentence uses **V1 vocabulary** (stakeholders, missing voices, framing divergences) while the INSTRUCTIONS prompt asks for V2 outputs (`position_clusters[]`, `missing_positions[]`). The legacy-message safety net in `agent.py` appends this string inside the `<instructions>` block, producing a User turn with two contradictory specifications. Live runs work because INSTRUCTIONS dominates, but the user-turn text is internally inconsistent.

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `position_clusters[].position_label` | Writer; Perspektiv-Sync | Originary ✅ | Thesis sentence |
| `position_clusters[].position_summary` | Writer; QA+Fix; Perspektiv-Sync | Originary ✅ | One-to-two-sentence elaboration |
| `position_clusters[].source_ids` | `_enrich_position_clusters`; `_convert_rsrc_to_src_in_perspectives` | Originary ✅ | `rsrc-NNN` references |
| `missing_positions[].type` | Writer COVERAGE_STATEMENT; bias card | Originary ✅ | Actor-type enum |
| `missing_positions[].description` | Writer; bias card | Originary ✅ | Concrete sentence |

Python's `_enrich_position_clusters` adds `id` (`pc-NNN`), `actors[]`, `regions[]`, `languages[]`, and `representation`. Clean Python ownership.

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 62 lines | Low | Tight |
| Negative listings | 2 | Low | Excellent |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | Clean — prompt does not mention what Python does after |
| Example density | One worked cluster + one worked missing position | Adequate | |
| Concreteness | Strong: "Two actors in different countries, different languages, or different outlets making the same claim belong in the same cluster" gives a real decision rule | — | |

#### Notable findings

- The user-message string at the call site is V1 vocabulary. **Either** delete the legacy `message=` argument (let INSTRUCTIONS speak alone) **or** rewrite the message to V2 vocabulary. Today's state confuses readers and confuses log analyses.
- The prompt does not document that Python adds `id`, `actors[]`, `regions[]`, `languages[]`, `representation` to the cluster downstream. That's intentional (prompts shouldn't know about Python work) but a downstream reader of the output JSON might wonder where `representation: dominant` came from. Documentation belongs in `docs/AGENT-IO-MAP.md` — already there post-reconcile.
- Source-level `url`, `title`, `summary` fields in the input dossier are unread. Pruning them out of the Perspektiv `<context>` payload would shrink Opus tokens at the largest agent input the production pipeline has. Estimated saving: 15–25% of the dossier payload.

---

### 9. Writer

**Files:** `agents/writer/SYSTEM.md` + `agents/writer/INSTRUCTIONS.md` + (conditional) `agents/writer/FOLLOWUP.md`
**Model:** `anthropic/claude-opus-4.6` @ 0.3, reasoning none, `web_search` tool enabled.
**Role in pipeline:** Produce headline/subheadline/body/summary with inline citations. Largest token cost in the pipeline.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `title`, `selection_reason` | TopicAssignment | Topic anchor | Used |
| `perspective_analysis` | Perspektiv (enriched) | Cluster-driven structure | Used (the prompt reads `perspective_analysis.position_clusters` and `.missing_positions`) |
| `position_clusters` (top-level) | Pipeline (duplicated from `perspective_analysis`) | — | **Unused** — duplicate of `perspective_analysis.position_clusters` |
| `missing_positions` (top-level) | Pipeline (duplicated) | — | **Unused** — same |
| `sources[]` (full dossier) | Research dossier | Citation pool | Used |
| `coverage_gaps[]` | Research dossier | COVERAGE_STATEMENT prose | Used |
| `follow_up.{previous_headline, reason}` (conditional) | Pipeline; loaded only when `follow_up_to` is set | FOLLOWUP addendum trigger | Used |

The user-message string at the call site is `"Write a multi-perspective article on this topic."` — generic, restates IDENTITY.

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `headline` | TP `article.headline` | Originary ✅ | Factual |
| `subheadline` | TP `article.subheadline` | Originary ✅ | One sentence |
| `body` | TP `article.body`; QA+Fix; bias_language; renderer | Originary ✅ | 600–1200 words; `[rsrc-NNN]` / `[web-N]` citations |
| `summary` | TP `article.summary` | Originary ✅ | 2-3 sentences |
| `sources[].rsrc_id` (dossier shape) | `_merge_writer_sources` | Originary ✅ | Single field |
| `sources[].web_id, url, outlet, title, language, country` (web-search shape) | `_merge_writer_sources` | Originary ✅ | Six fields |

Python's `_merge_writer_sources` fills in dossier metadata and `_renumber_and_prune_sources` rewrites all citations to `[src-NNN]` before QA+Fix.

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 85 lines | Low | Within budget |
| Negative listings | 2 | Low | Excellent |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | The prompt does not describe what Python does after the citation rewrite — it uses the form the LLM emits, not the post-renumber form |
| Redundancy | The "no numerics in headline/body/summary" rule is in body prose AND rule 2 (an inversion via examples) | Low | Acceptable — load-bearing |
| Example density | One worked output with mixed `[rsrc-NNN]` and `[web-N]` citations | Strong | Best illustration of the dual citation convention |

#### Notable findings

- Top-level `position_clusters` and `missing_positions` keys in `writer_context` are duplicates of the same fields under `perspective_analysis`. The Writer prompt only reads them via `perspective_analysis.position_clusters[]` and `.missing_positions[]`. The two top-level keys are pure token waste — at Opus pricing on a typical 12-cluster topic, that's the same cluster array sent twice in input.
- FOLLOWUP.md is well-scoped (18 lines) and integrates cleanly with the User-turn `<instructions>` block via `instructions_addendum`. The mention of `<memory>` in FOLLOWUP.md anticipates the future Editor-memory feature; for now `<memory>` never renders because no Writer call passes a `memory_path`.

---

### 10. QA+Fix

**Files:** `agents/qa_analyze/SYSTEM.md` + `agents/qa_analyze/INSTRUCTIONS.md`
**Model:** `anthropic/claude-sonnet-4.6` @ 0.1, reasoning none, no tools.
**Role in pipeline:** Find factual problems in the Writer's article, propose specific corrections, apply them, return the corrected article. Largest single-call token cost after Writer.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `article` (post-renumber) | Pipeline (after `_renumber_and_prune_sources`) | The article under review | Used |
| `sources[]` (rsrc-NNN dossier) | Research dossier | The cited evidence pool | Used |
| `preliminary_divergences[]` | Research dossier | Source disagreement context | Used |
| `position_clusters[]` | Perspective analysis | Position context for misframing checks | Used |
| `missing_positions[]` | Perspective analysis | Coverage check | Used |
| `coverage_gaps[]` (declared in INSTRUCTIONS) | — | — | **Not passed by the pipeline** — the prompt mentions `coverage_gaps[]` from research but the call site doesn't include it |

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `problems_found[]` | TP `transparency.qa_problems_found`; renderer | Originary ✅ | Per-issue triplet |
| `proposed_corrections[]` | TP `transparency.qa_proposed_corrections`; perspektiv-sync eligibility; renderer | Originary ✅ | One-liner per problem |
| `article` | Pipeline `article["body"]/headline/subheadline/summary` replacement | Originary ✅ | Pipeline deliberately ignores `qa_article["sources"]` to preserve the `rsrc_id` stash on the pre-QA sources |
| `divergences[]` | TP `divergences[]`; bias card `factual_divergences` | Originary ✅ | Five-field disagreement records |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 98 lines | Low | At the upper end of the 70–100 budget |
| Negative listings | 2 | Low | Excellent |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | The prompt does not say "Perspektiv-Sync runs after you" or similar |
| Redundancy | The "Wikipedia is unsupported_claim" rule appears in problem types description, in working from sources, AND rule 4 | Medium | One mention would suffice |
| Example density | One worked output with all four top-level fields | Strong | |

#### Notable findings

- Input contract drift on `coverage_gaps[]`: the prompt declares it; the pipeline doesn't pass it. Either fix the pipeline (one-line addition to `qa_context`) or remove the line from the prompt.
- The QA agent passes through `article.sources[]` from input to output. The pipeline deliberately discards the QA-output sources to keep the pre-QA `rsrc_id` internal stash. The prompt could be tightened to NOT emit `article.sources` in the corrected article (Python keeps its own copy), saving a meaningful token chunk on the Sonnet call.

---

### 11. Perspektiv-Sync

**Files:** `agents/perspektiv_sync/SYSTEM.md` + `agents/perspektiv_sync/INSTRUCTIONS.md`
**Model:** `anthropic/claude-opus-4.6` @ 0.1, reasoning none, no tools.
**Role in pipeline:** **Hydrated only.** Re-align the position-cluster map with the QA-corrected article body. Eligibility-gated by QA reporting `proposed_corrections`.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `original_perspectives` | Pipeline | The pre-QA enriched cluster map | Used (read by id) |
| `corrected_article.{headline, subheadline, body, summary}` | Pipeline (post-QA) | Authoritative state | Used |
| `qa_corrections.{problems_found, proposed_corrections}` | Pipeline (post-QA) | Reasoning chain | Used |

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `position_cluster_updates[].id` | `merge_perspektiv_deltas` | Originary ✅ | `pc-NNN` |
| `position_cluster_updates[].position_label` (optional) | `merge_perspektiv_deltas` | Originary ✅ | Field-presence merge |
| `position_cluster_updates[].position_summary` (optional) | `merge_perspektiv_deltas` | Originary ✅ | Field-presence merge |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 55 lines | Low | Tight |
| Negative listings | 7 | Medium | Several "do not" lines spelling out what's NOT in the output (correct emphasis but heavy) |
| Mission-speech | 0 | Low | Clean |
| Pipeline leaks | 0 | Low | Does not name `merge_perspektiv_deltas` |
| Redundancy | Field-presence-vs-absence semantics described in body, in field notes, and rule 1 | Low | Load-bearing — tolerable |
| Example density | One worked output | Adequate | |

#### Notable findings

- The prompt is well-scoped to V2 cluster shape. Rule 4's "When QA removed an attribution the original cluster summary depended on, rewrite the summary to match the corrected article body rather than fabricating an alternative" handles the sharp edge case cleanly.
- Live evidence (today's hydrated smoke): the agent emitted 1 cluster update for 9 corrections — appropriate selectivity. The `_run_perspektiv_sync` log line "1 position cluster updates merged, 9 corrections considered" confirms the V2 path is wired.

---

### 12. Bias Detector (registered as `bias_language`)

**Files:** `agents/bias_detector/SYSTEM.md` + `agents/bias_detector/INSTRUCTIONS.md`
**Model:** `anthropic/claude-opus-4.6` @ 0.1, reasoning none, no tools.
**Role in pipeline:** Scan article body for linguistic bias patterns. Synthesise reader note from pre-aggregated bias card + language findings.

#### Input audit

| Input field | Source | Purpose | Categorisation |
| --- | --- | --- | --- |
| `article_body` | Article body post-QA, post-coverage-statement | Lexical scan | Used |
| `bias_card.source_balance` | `_build_bias_card` | Reader note structural facts | Context-only — rule 4 forbids re-aggregating |
| `bias_card.geographic_coverage` | `_build_bias_card` | Reader note context | Context-only |
| `bias_card.perspectives.{cluster_count, distinct_actor_count, representation_distribution, missing_positions}` | `_build_bias_card` (V2 fields) | Reader note context; missing_positions explicitly named | Used (read for synthesis) |
| `bias_card.factual_divergences` | `_build_bias_card` (from QA divergences) | Reader note context | Used |
| `bias_card.coverage_gaps` | `_build_bias_card` (from research) | Reader note context | Used |

#### Output audit

| Output field | Downstream consumer | Originarity | Notes |
| --- | --- | --- | --- |
| `language_bias.findings[].excerpt` | TP `bias_analysis.language_bias`; renderer | Originary ✅ | Verbatim from article body |
| `language_bias.findings[].issue` | TP; renderer | Originary ✅ | Six-value enum |
| `language_bias.findings[].explanation` | TP; renderer | Originary ✅ | One sentence |
| `language_bias.severity` | TP `bias_analysis`; renderer | Originary ✅ | low/moderate/high |
| `reader_note` | TP `bias_analysis.reader_note`; renderer | Originary ✅ | 2–3 plain-language sentences |

#### Prompt quality

| Signal | Count / finding | Severity | Example |
| --- | --- | --- | --- |
| Length | 77 lines | Low | Within budget |
| Negative listings | 8 | Medium | Several in the "Distinguishing bias from legitimate practice" block, framed as "must not be flagged" |
| Mission-speech | 0 | Low | Clean — quoted "Independent Wire" only as "useful candidates" example, not as motivation |
| Pipeline leaks | 0 | Low | The `bias_card` source is pre-aggregated by Python; the prompt explicitly tells the agent NOT to recompute, but doesn't name `_build_bias_card` |
| Redundancy | Rule 4 ("Do not re-analyze the bias card") restates the body's "do not recompute or restate them mechanically" | Low | One mention suffices |
| Example density | One worked finding × 2 + one worked reader note | Strong | Reader note example is exemplary plain-language style |

#### Notable findings

- The six-category classification with worked-example phrases (e.g. *"Devastating", "landmark", "alarming", "historic", "controversial"*) is concrete and tight — strongest categorical guidance of any prompt. Reuse pattern.
- Rule 6's explicit-permission for empty findings ("When the article body has no meaningful language bias, `findings` is an empty array and `severity` is `low`. Do not invent findings to appear thorough.") prevents a known model failure mode where Claude invents findings to seem useful. Carry this rule into any future quality-checking agent.

---

### 13. Collector (DISABLED)

**Files:** `agents/collector/AGENTS.md` + `agents/collector/PLAN.md` + `agents/collector/ASSEMBLE.md` (single-file legacy convention).
**Model:** declared as `z-ai/glm-5` in the commented-out `scripts/run.py` block.
**Status:** Commented out at load site. Used only as a fixture path by `tests/test_tools.py` (six sites).

Not analysed in this audit because the agent is not on the production code path. If reactivated for the 200+ feed scale-up, the prompts will need to be split into the SYSTEM/INSTRUCTIONS convention before they can be loaded by the post-S13 Agent constructor.

---

## Cross-agent observations

### Inter-agent contract drift

Three real drifts and one mostly-benign one:

1. **Curator → Pipeline shape mismatch.** The Curator INSTRUCTIONS still emits `topics[].source_ids: ["finding-N",…]` (legacy shape). The pipeline expects `{topics, cluster_assignments}` (new shape) and falls back to legacy. The agent is paying for a field Python is supposed to derive. This is the largest "rewrite not actually shipped" finding.
2. **Editor → Pipeline shape mismatch.** Editor INSTRUCTIONS emits `id` and `topic_slug`. Python regenerates both deterministically. Same kind of drift as Curator. Same fix shape.
3. **QA+Fix `coverage_gaps[]` declared but not passed.** Mostly benign — the prompt never references `coverage_gaps` in any STEP — but a real input-contract drift.
4. **TopicAssignment `raw_data` always `{}`.** Researcher Plan's prompt says raw_data carries Curator enrichment metadata. Editor doesn't carry raw_data forward. Functional impact: planner runs on title + selection_reason alone, which has not visibly degraded query quality in the smoke runs but represents a silent loss of editorial context.

The producer-consumer edges that are clean: Researcher Plan → Researcher Assemble (via Python search execution); Researcher Assemble → Perspektiv (`sources[]` + `actors_quoted[]`); Perspektiv → Writer (V2 clusters via `_enrich_position_clusters`); Writer → QA+Fix (post-renumber `[src-NNN]` everywhere); QA+Fix → Perspektiv-Sync (V2 `proposed_corrections` consumed cleanly). Every Hydration Aggregator boundary is clean.

### Pipeline-Python boundary

The post-S13 boundary is in good shape. Python owns: `_slugify`, `_extract_date_from_url`, `rsrc-NNN` assignment (in both production and hydrated paths), `pc-NNN` assignment, `src-NNN` renumbering, `_substitute_coverage_statement`, `_build_bias_card`, `_normalise_country`, `_normalise_language`, `merge_dossiers` source re-indexing, `merge_perspektiv_deltas`, and word counts.

LLM-side fields that **could still move to Python** but currently sit in agent output:

- **Curator `topics[].source_ids`**: should disappear once the prompt is rewritten to emit `cluster_assignments[]`.
- **Editor `id` and `topic_slug`**: should disappear from agent output once the prompt is rewritten.

Beyond those two, the boundary is clean.

### Prompt-style consistency

Every active prompt now follows the same structural skeleton: `# IDENTITY AND PURPOSE` (SYSTEM.md) + `# TASK` / sub-sections / `# OUTPUT FORMAT` / `# RULES` (INSTRUCTIONS.md). Heading levels are consistent. JSON examples are all rendered as fenced ` ```json ` blocks. Field-note bullet style is consistent.

The one exception is **Curator INSTRUCTIONS**, which uses `# STEPS` instead of the more common task body. Editor uses `# STEPS` numbered 1–8. Other prompts mostly skip explicit numbered steps. The inconsistency is mild but worth a pass once the Curator/Editor rewrite happens — picking one convention (`# TASK` body with implicit ordering, or `# STEPS` with numbered list) would improve style cohesion.

### Token-economy

Approximate per-agent token order of magnitude on a typical production topic (from the 2026-04-27 reference run, 1 topic):

| Agent | Tokens (input + output) | Notes |
| --- | --- | --- |
| Curator | not measured (full run not available post-S13) | ~1,400 findings input; cheap model |
| Editor | not measured | small input/output, cheap |
| Researcher Plan | 1,697 | Gemini Flash; cheap |
| Researcher Assemble | 20,375 | One call per topic, large input from search results |
| Perspektiv | 5,948 | Cluster work on dossier |
| Writer | 95,977 | Largest cost — 10 web_search tool calls + final article |
| QA+Fix | 20,404 | Sonnet; per-correction reasoning chain |
| Bias Language | 5,876 | Opus on bias_card + body |

**Total per-topic on production ≈ 150K tokens.** Hydrated path adds ~25K Phase 1 tokens (parallel 4 chunks of Gemini Flash) + ~10–15K Phase 2 tokens (Opus single call). Hydrated total ≈ 200K tokens per topic.

The two prompt-side savings opportunities:
- Drop the duplicated `position_clusters` + `missing_positions` top-level keys from `writer_context`. With ~12 clusters @ ~150 tokens each, plus 5 missing positions @ ~50 tokens, that's ~2K Opus tokens per Writer call — small in absolute terms but pure waste.
- Trim the dossier sources Perspektiv sees to omit `url`, `title`, `summary` (Perspektiv reads only `id`, `outlet`, `language`, `country`, `actors_quoted`). Estimated 15–25% saving on the 5,948-token Perspektiv call ≈ 1K tokens.

Combined per-topic savings: ~3K tokens. Modest, but a clean win.

---

## Recommendations

Ordered by severity then expected effort.

### High severity

1. **Rewrite Curator INSTRUCTIONS to emit `{topics, cluster_assignments}` envelope.** Drop `topics[].source_ids` from the OUTPUT FORMAT; replace step 6 with "produce `cluster_assignments[]` mapping each finding to its cluster's topic_index." Effort: small. Why: the S13 rewrite's stated goal hasn't actually shipped for the Curator until this lands.
2. **Rewrite Editor INSTRUCTIONS to drop `id` and `topic_slug` from OUTPUT FORMAT.** Remove step 6 ("Assign each topic a unique id…"). Effort: small. Why: same as above.
3. **Trim Editor INSTRUCTIONS pipeline-architecture leaks.** Six separate sentences mention "downstream pipeline stages", "third agent", "the Writer agent consumes your output". Reduce to zero. Effort: small. Why: the prompt's largest stylistic flaw and a concrete weak spot for future model swaps where the architecture context becomes wrong.

### Medium severity

4. **Migrate the per-call `message=` arguments into INSTRUCTIONS.md or drop them.** The legacy-message safety net in `agent.py` logs deprecation warnings; the safety net was meant as transition scaffolding. The Perspektiv call site in particular says V1 vocabulary against a V2 prompt — fix or delete. Effort: trivial (the Perspektiv message is the worst offender; the others can stay). Why: log noise and prompt inconsistency.
5. **Remove duplicated top-level `position_clusters` and `missing_positions` from `writer_context`.** The Writer prompt only reads `perspective_analysis.position_clusters[]` and `.missing_positions[]`. Effort: trivial (delete two lines in `pipeline.py` and `pipeline_hydrated.py`). Why: pure token waste at Opus rates.
6. **Decide and fix the `raw_data: {}` issue.** Either thread Curator enrichment through `TopicAssignment.raw_data` (so Researcher Plan's prompt is honest) or drop the `raw_data` reference from the planner prompt. Effort: small. Why: silent data loss vs honest schema.
7. **Pass `coverage_gaps[]` to QA+Fix or remove the line from the prompt.** Effort: trivial. Why: contract honesty.

### Low severity

8. **Consolidate Editor's "no numerics in selection_reason" rule into one statement.** Currently in body, OUTPUT FORMAT field note, and RULES item 7. Effort: trivial. Why: clarity.
9. **Drop QA+Fix's `article.sources[]` from the corrected-article output schema.** Pipeline ignores it anyway. Effort: trivial in the prompt. Why: ~1K Sonnet tokens saved per call.
10. **Consider a Perspektiv-context-trim helper** that strips `url`, `title`, `summary` from each dossier source before sending. Effort: small (helper + apply at one call site, two call sites if mirrored to hydrated). Why: ~15–25% token saving on the Perspektiv input — modest but free.
11. **Relax Editor rule "NEVER assign the same priority to more than two topics"** to a soft directive, or enforce it in Python post-hoc by re-ranking ties. Effort: small. Why: the LLM cannot self-verify across the topic set reliably.
12. **Document Python-added Perspektiv enrichment in `agents/perspektiv/INSTRUCTIONS.md`** as a one-line footnote in the OUTPUT FORMAT section. Effort: trivial. Why: future readers wonder where `representation: dominant` comes from. Alternative: leave the prompts ignorant by design and rely on `docs/AGENT-IO-MAP.md`.

### Not recommended (out of scope per the brief)

- Rewriting the Editor's STEPS into TASK body. Style preference, not bug.
- Switching JSON example formatting conventions across prompts. Already consistent.
- Adding a memory-feeding step before any agent. Future workstream.

---

## Findings index

| Agent | Finding type | Severity | Location | Recommendation |
| --- | --- | --- | --- | --- |
| Curator | Output shape drift (legacy `source_ids` vs new `cluster_assignments`) | High | `agents/curator/INSTRUCTIONS.md` (OUTPUT FORMAT, step 6, rule 2) | #1 |
| Editor | Output shape drift (`id`, `topic_slug` should be Python-only) | High | `agents/editor/INSTRUCTIONS.md` (step 6, OUTPUT FORMAT, examples) | #2 |
| Editor | Pipeline-architecture leak ×6 | High | `agents/editor/INSTRUCTIONS.md` (lines 3, 5, 19, 49, 74) | #3 |
| Editor | Mission-speech ×2 | Medium | `agents/editor/INSTRUCTIONS.md` (line 5) | #3 (same trim) |
| Editor | Hard quantitative rule the LLM cannot self-enforce ("NEVER assign same priority to more than two") | Low | `agents/editor/INSTRUCTIONS.md` (line 77) | #11 |
| Editor | Repetition of "no numerics in selection_reason" ×3 | Low | `agents/editor/INSTRUCTIONS.md` (lines 19, 49, 74) | #8 |
| Researcher Plan | `raw_data` declared in prompt, always `{}` in pipeline | Medium | `agents/researcher/PLAN-INSTRUCTIONS.md` (line 3); `src/pipeline.py:1669,1684,2150` | #6 |
| Researcher Hydrated Plan | Same `raw_data` issue | Low | `agents/researcher_hydrated/PLAN-INSTRUCTIONS.md` (line 3); `src/pipeline_hydrated.py:430` | #6 |
| Researcher Assemble | Exclude-list duplicated in body and rule 4 | Low | `agents/researcher/ASSEMBLE-INSTRUCTIONS.md` (lines 9, 84) | (cosmetic) |
| Perspektiv | V1 vocabulary user-message at call site | Medium | `src/pipeline.py:1801`; `src/pipeline_hydrated.py:836` | #4 |
| Perspektiv | Source-level `url`, `title`, `summary` unused in prompt | Low | `agents/perspektiv/INSTRUCTIONS.md` (input description) vs dossier shape | #10 |
| Writer | Top-level `position_clusters` + `missing_positions` duplicated under `perspective_analysis` | Medium | `src/pipeline.py:1844-1852`; `src/pipeline_hydrated.py:887-894` | #5 |
| QA+Fix | `coverage_gaps[]` declared in INSTRUCTIONS, not passed by pipeline | Medium | `agents/qa_analyze/INSTRUCTIONS.md` (line 3); `src/pipeline.py:1942-1948` | #7 |
| QA+Fix | `article.sources[]` round-trip serves no downstream purpose | Low | `agents/qa_analyze/INSTRUCTIONS.md` (article schema, line 56-69) | #9 |
| QA+Fix | Wikipedia rule duplicated ×3 | Low | `agents/qa_analyze/INSTRUCTIONS.md` (lines 11, 17, rule 4) | (cosmetic) |
| Perspektiv-Sync | Heavy negative-listing density (7 occurrences) | Low | `agents/perspektiv_sync/INSTRUCTIONS.md` | (cosmetic) |
| Bias Detector | Rule 4 restates body guidance | Low | `agents/bias_detector/INSTRUCTIONS.md` (line 76) | (cosmetic) |
| All call sites | Legacy `message=` parameter still in use | Low (per-call); Medium (for Perspektiv) | `src/pipeline.py` Perspektiv/Writer/QA+Fix/Bias call sites | #4 |

---

## Closing note

The S13 prompt rewrite delivered most of what it promised: prompts are tighter, the User-turn three-block layout is in place, and Python owns every deterministic field in the final TP. The unfinished business is concentrated in two of thirteen prompts (Curator, Editor) where the agent is still emitting fields the pipeline regenerates, and at three call sites where redundant or contradictory inputs leak in. None of it blocks production. All of it is small, surgical work — half a day for the architect to scope, a sequence of tiny prompt edits and a handful of pipeline.py one-liners to land.
