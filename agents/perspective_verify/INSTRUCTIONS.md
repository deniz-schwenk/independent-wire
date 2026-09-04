# TASK

You receive the topic inputs — `title`, `selection_reason`, `sources[]` (each with `id`, `outlet`, `language`, `country`, `title`, `summary`, `actors_quoted[]`), the three canonical-actor pools `canonical_actors_stated[]`, `canonical_actors_reported[]`, `canonical_actors_mentioned[]` (each entry with `id`, `name`, `role`, `type`, `is_anonymous`, `source_ids[]`, `quotes[]`), and `preliminary_divergences[]` and `coverage_gaps[]` — plus `draft`, a perspective object of `position_clusters[]` and `missing_positions[]` built from those inputs. Verify every reference and every attribution in the draft against the inputs and return the corrected object. The draft's clustering and prose stand; what changes is what the inputs cannot support.

# STEPS

1. For each cluster, check every actor ID in its `stated`, `reported`, and `mentioned` sub-lists. The ID must exist in the pool matching its sub-list, and that pool entry's `quotes[].position` texts must align with the cluster's `position_label`. An aligned actor sitting in the wrong sub-list moves to the sub-list of the pool that actually holds it. An ID found in no pool, or an actor whose recorded positions do not support the cluster's claim, is removed from the cluster.
2. For each cluster, check every entry in `source_ids`: the source exists in `sources[]` and its `actors_quoted[]`, `summary`, or `title` grounds the cluster's position. Entries without such grounding are removed.
3. Check each cluster as a whole: a cluster left with no supporting sources or no aligned actors after steps 1–2 is removed entirely. Check each `missing_positions[]` entry: the `type` is one of the ten actor-type values, and the described perspective is genuinely absent from the pools; an entry describing a perspective the pools demonstrably contain is removed.
4. Output the complete corrected object.

# OUTPUT FORMAT

A single JSON object with the same two top-level fields and the same field order as the draft. Example shape:

{"position_clusters": [{"position_label": "The new policy will stifle small-business innovation", "position_summary": "Industry voices argue the compliance burden falls disproportionately on smaller firms.", "source_ids": ["src-003", "src-007"], "stated": ["actor-004"], "reported": ["actor-009"], "mentioned": []}], "missing_positions": [{"type": "affected_community", "description": "No voices from the small-business owners the policy would directly affect."}]}

Field notes:

- The object is complete: every cluster and every `missing_positions[]` entry that survives verification appears in full, corrected material and untouched material alike. This is the analysis itself, not a report of changes.
- Draft material the inputs support is carried over unchanged, word for word.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Removal over invention, always: when the inputs cannot support a reference and no correction grounded in the inputs exists, delete it. A thinner honest spectrum beats an invented voice.
2. Verification never adds: no new clusters, no new actors, no new sources, no new missing-position entries. The one permitted move is relocating an aligned actor to the sub-list of the pool that holds them.
3. Every ID in the output exists in the inputs: `source_ids` entries in `sources[]`, sub-list entries in the pool matching the sub-list's name.
4. Judgment grounds in the inputs alone — what the pools and sources record, not what is plausible about the topic from outside knowledge.
