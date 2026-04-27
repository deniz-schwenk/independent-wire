# Agent IO Map (post-S13)

## Grundprinzip (Deniz, Session 6)

> Für jeden Agent bestimmen: A) was braucht er, B) was soll er erzeugen. Den Rest leiten wir immer mit Python weiter. Wenn ein Agent "durchreicht", erzeugt er Tokens ohne Mehrwert.

The S13 prompt rewrite hardened this principle into prompt-design discipline: every deterministic field — IDs, slugs, dates, counts, source enrichment, citation rewriting — moved out of the LLM output and into Python. Each section below lists what the agent now emits (LLM column) and what Python adds downstream (Python column). A ✅ in the **Originär** column means only the LLM can produce the field (judgement, prose, classification); a ❌ would flag a leftover that should be moved to Python.

---

## 1. Curator (Gemini 3 Flash, 1×/Run)

### INPUT

```
{
  findings: [
    {id: "finding-N", title, source_name, summary?}
  ]
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `topics[].title` | ✅ | ✅ | Topic label (not headline) |
| `topics[].relevance_score` | ✅ | ✅ | 1-10 editorial judgement |
| `topics[].summary` | ✅ | ✅ | 1-3 sentences derived from input findings |
| `cluster_assignments[].finding_index` | ✅ | ✅ | Maps each finding to its target topic |
| `cluster_assignments[].topic_index` | ✅ | ✅ | Topic position in `topics[]` |

### Python adds (downstream of Curator)

| Field | Where computed |
| --- | --- |
| `topics[].source_ids` (e.g. `["finding-3","finding-7"]`) | `Pipeline._rebuild_curator_source_ids` (collapses cluster_assignments per topic) |
| `topics[].geographic_coverage`, `languages`, `source_count`, `missing_regions`, `missing_languages`, `source_diversity`, `missing_perspectives` | `Pipeline._enrich_curator_output` |

**Status:** ✅ Pass-through clean. No Python-derivable field in the LLM output.

---

## 2. Editor (Opus 4.6, 1×/Run)

### INPUT

```
{
  topics: [<Curator output, fully enriched>],
  previous_coverage: [{tp_id, date, headline, slug, summary}]   # last 7 days
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `[].title` | ✅ | ✅ | May refine the Curator title |
| `[].priority` | ✅ | ✅ | 0-10. 0 = rejected (kept in output for transparency) |
| `[].selection_reason` | ✅ | ✅ | Editorial justification |
| `[].follow_up_to` | ✅ (optional) | ✅ | `tp_id` of prior TP this follows up on |
| `[].follow_up_reason` | ✅ (optional) | ✅ | What's materially new since the prior TP |

### Python adds (downstream of Editor)

| Field | Where computed |
| --- | --- |
| `[].id = "tp-{date}-NNN"` | `Pipeline.editorial_conference` — assigned 1-based seq after priority-zero filter + sort |
| `[].topic_slug` | `_slugify(title)` — NFKD ASCII-fold, non-`\w` to `-`, max 60 chars at word boundary |

**Status:** ✅ Pass-through clean. `id` and `topic_slug` are entirely Python-owned post-S13.

---

## 3. Researcher Plan (Gemini 3 Flash, 3×/Run)

### INPUT

```
{
  title, selection_reason, raw_data
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `[].query` | ✅ | ✅ | Multilingual query string |
| `[].language` | ✅ | ✅ | ISO 639-1 code, lowercase |

**Status:** ✅ Pass-through clean. Web-search execution and URL-based date extraction are deterministic Python.

---

## 4. Researcher Assemble (Gemini 3 Flash, 3×/Run)

### INPUT

```
{
  assignment: {title, selection_reason},
  date,
  search_results: [{query, language, results, url_dates?}]
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `sources[].url, title, outlet, language, country, summary` | ✅ | ✅ | Per-source structured extraction |
| `sources[].actors_quoted[]` | ✅ | ✅ | `{name, role, type, position, verbatim_quote}` — five fields exact |
| `preliminary_divergences[]` | ✅ | ✅ | One sentence each, cross-regional |
| `coverage_gaps[]` | ✅ | ✅ | One sentence each |

### Python adds (downstream of Researcher Assemble)

| Field | Where computed |
| --- | --- |
| `sources[].id = "rsrc-NNN"` | `_research_two_phase` — assigned by array index |
| `sources[].estimated_date` (when extractable) | `_extract_date_from_url(source.url)` |

**Status:** ✅ Pass-through clean. The pre-S13 `research_queries[]` and `languages_searched[]` fields are gone.

---

## 5. Researcher Hydrated Plan (Gemini 3 Flash, 3×/Run, hydrated only)

### INPUT

```
{
  title, selection_reason, raw_data,
  coverage_summary: {total_sources, languages_covered, countries_covered,
                     stakeholder_types_present, coverage_gaps}
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `[].query` | ✅ | ✅ | Same shape as Researcher Plan |
| `[].language` | ✅ | ✅ | ISO 639-1, lowercase |

The planner reads `coverage_summary` to focus queries on languages and stakeholder types the pre-dossier did not reach.

**Status:** ✅ Pass-through clean.

---

## 6. Hydration Aggregator Phase 1 (Gemini 3 Flash, parallel chunks, hydrated only)

### INPUT

```
{
  assignment: {title, selection_reason},
  articles: [{url, title, outlet, language, country, extracted_text, estimated_date}]
}
```

Articles are chunked to 5–10 per call; chunks fire in parallel via `asyncio.gather`.

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `article_analyses[].article_index` | ✅ | ✅ | Per-chunk 0-based index |
| `article_analyses[].summary` | ✅ | ✅ | Per-article extraction |
| `article_analyses[].actors_quoted[]` | ✅ | ✅ | `{name, role, type, position, verbatim_quote}` — five fields exact |

### Python adds (downstream of Phase 1)

| Operation | Where |
| --- | --- |
| Chunk-local `article_index` rewritten to global index | `_merge_phase1_results` |
| Rule 1 / Rule 6 validation + per-chunk retry of missing indices | `_validate_phase1_output`, `_run_phase1_chunk` |

---

## 7. Hydration Aggregator Phase 2 (Opus 4.6 @ 0.1, single call, hydrated only)

### INPUT

```
{
  assignment: {title, selection_reason},
  article_analyses: [<merged Phase 1 output>],
  article_metadata: [{article_index, language, country, outlet}]
}
```

Cross-corpus reduction. Phase 2 input is compact (summaries, not full text), so attention load stays low even on large N.

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `preliminary_divergences[]` | ✅ | ✅ | Cross-language / cross-region one-sentence statements |
| `coverage_gaps[]` | ✅ | ✅ | Specific missing regions, stakeholder types, or dimensions |

### Python adds (downstream of Phase 2)

| Operation | Where |
| --- | --- |
| Pre-dossier shaping (`build_prepared_dossier`): joins Phase 1 analyses with hydration records into `sources[]` with `rsrc-NNN` ids | `src/hydration_aggregator.py` |
| Coverage summary (`build_coverage_summary`) for the hydrated planner | same |
| Merge with web-search dossier (`merge_dossiers`): re-assigns `rsrc-NNN` across the concatenated source list | same |

---

## 8. Perspektiv (Opus 4.6 @ 0.1, 3×/Run) — V2

### INPUT

```
{
  title, selection_reason,
  sources: [<dossier with rsrc-NNN ids and actors_quoted[]>],
  preliminary_divergences: [...],
  coverage_gaps: [...]
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `position_clusters[].position_label` | ✅ | ✅ | Thesis sentence |
| `position_clusters[].position_summary` | ✅ | ✅ | One-to-two-sentence elaboration |
| `position_clusters[].source_ids` | ✅ | ✅ | List of `rsrc-NNN` ids backing the cluster |
| `missing_positions[].type` | ✅ | ✅ | One of the ten actor-type enum values |
| `missing_positions[].description` | ✅ | ✅ | Concrete sentence on what is missing and why it matters |

### Python adds (`_enrich_position_clusters`)

| Field | How computed |
| --- | --- |
| `position_clusters[].id = "pc-NNN"` | Assigned by array index, 1-based |
| `position_clusters[].actors[]` | Walked from `actors_quoted[]` on each cited source; carries name/role/type/region/source_ids/quote |
| `position_clusters[].regions[]` | Sorted, deduplicated normalised country values from cited sources |
| `position_clusters[].languages[]` | Sorted, deduplicated normalised language codes from cited sources |
| `position_clusters[].representation` | `dominant` (≥40%), `substantial` (≥15%), or `marginal` (<15%) — ratio of cited sources to total dossier sources |

### Python rewrites (downstream)

| Operation | Where |
| --- | --- |
| `position_clusters[].source_ids` rewritten from `rsrc-NNN` → `src-NNN` after Writer renumbering | `_convert_rsrc_to_src_in_perspectives` |
| Empty clusters dropped after rewrite | same |

**Status:** ✅ Pass-through clean. The pre-S13 `stakeholders[]`, `missing_voices[]`, `framing_divergences[]` shape is gone.

---

## 9. Writer (Opus 4.6, 3×/Run, with `web_search` tool)

### INPUT

```
{
  title, selection_reason,
  perspective_analysis: {position_clusters: [...], missing_positions: [...]},
  position_clusters: [...],     # mirrored for convenience
  missing_positions: [...],
  sources: [<merged research dossier>],
  coverage_gaps: [...],
  follow_up?: {previous_headline, reason}    # only when assignment.follow_up_to set
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `headline` | ✅ | ✅ | Factual, ≤12 words |
| `subheadline` | ✅ | ✅ | One sentence |
| `body` | ✅ | ✅ | 600–1200 words; citations as `[rsrc-NNN]` for dossier sources and `[web-N]` for web-search sources; contains literal `[[COVERAGE_STATEMENT]]` placeholder |
| `summary` | ✅ | ✅ | 2-3 sentences |
| `sources[]` (dossier ref) | ✅ | ✅ | Single field: `{rsrc_id: "rsrc-NNN"}` |
| `sources[]` (web-search ref) | ✅ | ✅ | Six fields: `{web_id: "web-N", url, outlet, title, language, country}` |

### Python adds (downstream of Writer)

| Operation | Where |
| --- | --- |
| `_merge_writer_sources` — resolve `rsrc_id` → full dossier metadata; pass through web-search sources; stash `rsrc_id` / `web_id` internally | `src/pipeline.py` |
| `_renumber_and_prune_sources` — drop unreferenced sources, renumber survivors to gapless `src-001..src-NNN`, atomically rewrite `[rsrc-N]` and `[web-N]` to `[src-NNN]` across `headline`, `subheadline`, `body`, `summary` | runs **before** QA+Fix so the agent sees one consistent ID scheme |
| `_substitute_coverage_statement` — replace `[[COVERAGE_STATEMENT]]` placeholder with Python-rendered "drawn from N sources in M languages" sentence | runs after QA+Fix |
| `article["word_count"] = len(body.split())` | Never trust LLM counting |

### Writer FOLLOWUP.md (addendum)

Loaded into `writer_addendum` and passed via `Agent.run(..., instructions_addendum=writer_addendum)` when `assignment.follow_up_to` is truthy. Appended **inside** the `<instructions>` block of the User turn, separated from INSTRUCTIONS.md by exactly one blank line. Changes Writer behaviour (lead with new development, self-contained, brief context) but does not change the output schema.

**Status:** ✅ Pass-through clean. Final `src-NNN` numbering is entirely Python-owned.

---

## 10. QA+Fix (Sonnet 4.6 @ 0.1, 3×/Run)

### INPUT

```
{
  article: {headline, subheadline, body, summary, sources[]},     # all citations [src-NNN] (renumbered before this call)
  sources: [<dossier with rsrc-NNN ids>],
  preliminary_divergences: [...],
  position_clusters: [...],
  missing_positions: [...]
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `problems_found[]` | ✅ | ✅ | `{article_excerpt, problem, explanation}` per identified issue |
| `proposed_corrections[]` | ✅ | ✅ | One one-liner per problem, in the same order |
| `article` | ✅ | ✅ | Complete corrected article (`headline`, `subheadline`, `body`, `summary`, `sources` — sources passed through unchanged) |
| `divergences[]` | ✅ | ✅ | `{type, description, source_ids, resolution, resolution_note}` |

### Pipeline integration

| Behaviour | Where |
| --- | --- |
| `qa_article["sources"]` is **NOT** copied back over `article["sources"]` — pre-QA renumbered sources carry the `rsrc_id` stash that Fix-3 needs | `src/pipeline.py` `_produce_single`, `src/pipeline_hydrated.py` `_produce_single` |
| `transparency.qa_proposed_corrections` carries `proposed_corrections[]` (renamed from `corrections_applied`) | TP assembly |
| `transparency.article_original` carries the pre-QA body **only when `proposed_corrections` is non-empty** | TP assembly |

**Status:** ✅ Pass-through clean. The pre-S13 `corrections_applied[]` field name is gone everywhere — log line, transparency block, and renderer.

---

## 11. Perspektiv-Sync (Opus 4.6 @ 0.1, hydrated only) — V2

Eligibility-gated step that runs after QA+Fix in the hydrated pipeline. Skipped when `qa_analysis.proposed_corrections` is empty.

### INPUT

```
{
  original_perspectives: <Perspektiv V2 output, fully enriched (pc-NNN ids, actors[], regions[], languages[], representation, source_ids)>,
  corrected_article: {headline, subheadline, body, summary},
  qa_corrections: {problems_found, proposed_corrections}
}
```

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `position_cluster_updates[].id` (mandatory) | ✅ | ✅ | `pc-NNN` of the affected cluster |
| `position_cluster_updates[].position_label` (optional) | ✅ | ✅ | Updated label string. Omitted when unchanged |
| `position_cluster_updates[].position_summary` (optional) | ✅ | ✅ | Updated summary string. Omitted when unchanged |

Field-presence semantics: presence with a string value overwrites; absence leaves untouched. `null` on either field is rejected with a WARNING (V2 has no semantic for null overrides).

### Pass-through fields (never appear in the output)

`actors`, `regions`, `languages`, `representation`, `source_ids`, cluster `id`, and the entire `missing_positions[]` block. Python's `merge_perspektiv_deltas` pulls them through from `original_perspectives`.

**Status:** ✅ Pass-through clean. The pre-S13 `stakeholder_updates[]` (with V1 `position_quote` semantics) is gone.

---

## 12. Bias Detector (Opus 4.6 @ 0.1, 3×/Run, registered as `bias_language`)

### INPUT

```
{
  article_body,
  bias_card: {
    source_balance: {total, by_language, by_country},
    geographic_coverage: {represented, missing_from_dossier},
    perspectives: {cluster_count, distinct_actor_count,
                   representation_distribution, missing_positions},
    factual_divergences: [...],
    coverage_gaps: [...]
  }
}
```

The `bias_card` is built by `_build_bias_card` in Python — pure aggregation from the article sources, the Perspektiv V2 enriched clusters, the QA divergences, and the research dossier coverage_gaps. **Counts, distributions, and lists are pre-aggregated**; the agent reads them for synthesis but does not recompute or restate them mechanically.

### OUTPUT

| Field | LLM emits | Originär? | Notes |
| --- | --- | --- | --- |
| `language_bias.findings[]` | ✅ | ✅ | `{excerpt, issue, explanation}` per linguistic bias pattern |
| `language_bias.severity` | ✅ | ✅ | Overall severity classification |
| `reader_note` | ✅ | ✅ | 2-3 plain-language sentences synthesizing structural facts + language findings |

**Status:** ✅ Pass-through clean. The pre-S13 `framing_divergences` and `missing_voices` field names are gone — replaced by `factual_divergences` (from QA) and `perspectives.missing_positions` (from Perspektiv V2).

---

## 13. Collector (DISABLED)

Two prompt files (`agents/collector/PLAN.md` + `ASSEMBLE.md`) are present in the working tree but their load sites in `scripts/run.py` are commented out. RSS feeds via `scripts/fetch_feeds.py` cover the current scale.

Reactivation criterion: 200+ RSS feeds, where the Collector would act as a Curator pre-filter. The disabled blocks reference the two-file convention (`PLAN-SYSTEM.md`, `PLAN-INSTRUCTIONS.md`, etc.) which would need to be created at reactivation time.

The legacy `agents/collector/AGENTS.md` is retained as a fixture for `tests/test_tools.py`.
