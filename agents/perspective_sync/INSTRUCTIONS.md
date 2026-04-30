# TASK

You receive `original_perspectives` containing the position-cluster map (`position_clusters[]` with cluster-level `id`, `position_label`, `position_summary`, plus pass-through `actors`, `regions`, `languages`, `representation`, and `source_ids`; plus `missing_positions[]`), a `corrected_article` containing the four article fields after QA+Fix, and a `qa_corrections` block carrying `problems_found[]` and `proposed_corrections[]` that describe what QA changed and why. Identify clusters whose `position_label` or `position_summary` no longer matches the corrected article body, and emit a narrow delta for each affected cluster — the cluster's `id` plus only the changed field or fields.

You do not rebuild the cluster map. You do not decide which clusters to keep. You do not emit unchanged clusters, `missing_positions`, or any pass-through cluster fields. The output lists only changes — unchanged clusters and unchanged fields are simply omitted.

## Field semantics

- `position_label` — the one-sentence position statement at the head of a cluster. Update it when the original wording misrepresents the position as the corrected article body now states it, or when QA flagged the wording as misleading framing.
- `position_summary` — the elaboration of the position. Update it when the summary describes the position in terms that conflict with the corrected article body.
- All other cluster fields — `id`, `actors[]`, `regions[]`, `languages[]`, `representation`, `source_ids[]` — are pass-through. Do not modify them and do not include them in the output.
- `missing_positions[]` is also pass-through. Do not modify, add to, or remove entries from it.

## Identifying affected clusters

- A cluster is affected when its `position_label` or `position_summary` references a fact, framing, or attribution that QA changed.
- Use `qa_corrections.problems_found[].article_excerpt` to locate the original wording, and `qa_corrections.proposed_corrections[]` to understand what changed and how. The corrected article body is the authoritative state — when in doubt, the cluster's label and summary must match what the body now says.
- A cluster whose label and summary remain accurate after the corrections does not appear in the output. Many corrections are local (a corrected number in a single sentence) and affect no cluster at all.
- When `qa_corrections.problems_found[]` is empty, the cluster map is already in sync. Return `{"position_cluster_updates": []}`.

# OUTPUT FORMAT

A single JSON object with exactly one top-level field. Example:

```json
{
  "position_cluster_updates": [
    {
      "id": "pc-002",
      "position_label": "The fees impose disproportionate costs on smaller shipping operators",
      "position_summary": "Industry-association voices argue the per-vessel fee structure penalises mid-size operators while leaving the largest carriers unaffected."
    },
    {
      "id": "pc-005",
      "position_summary": "Iranian state media frames the fees as a violation of international maritime law and a deliberate economic-coercion measure."
    }
  ]
}
```

Field notes:

- `position_cluster_updates[]` — array of delta objects. Empty array when no clusters needed updates.
- `position_cluster_updates[].id` (mandatory) — the cluster's `pc-NNN` identifier from `original_perspectives.position_clusters[].id`.
- `position_cluster_updates[].position_label` (optional) — the updated label string. Omit entirely when the label is unchanged.
- `position_cluster_updates[].position_summary` (optional) — the updated summary string. Omit entirely when the summary is unchanged.
- Each entry must carry `id` plus at least one of `position_label` or `position_summary`.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Output only deltas for clusters whose `position_label` or `position_summary` changed. Unchanged clusters do not appear; unchanged fields on a changed cluster do not appear. Omission means "do not touch this field"; presence means "overwrite with this value."
2. Each delta entry carries the cluster's `id` plus only `position_label` and/or `position_summary`. The other cluster fields (`actors`, `regions`, `languages`, `representation`, `source_ids`) and `missing_positions[]` never appear in the output.
3. Focus on clusters whose label or summary references a fact, framing, or attribution that QA changed. Do not re-analyze or second-guess clusters untouched by QA.
4. All updates rest on the QA reasoning chain (`problems_found`, `proposed_corrections`) and the corrected article body. Do not introduce facts, quotes, or attributions from outside knowledge. When QA removed an attribution the original cluster summary depended on, rewrite the summary to match the corrected article body rather than fabricating an alternative.