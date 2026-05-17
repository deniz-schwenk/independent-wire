# TASK

You receive a `topics[]` array — the day's discovered topics, each with a `title` and a `summary` — and a `micro_clusters[]` array — typically 200 to 280 entries, each with an `id`, a `size` (the total finding count for the cluster), and `sample_titles[]` (a sample of titles from that cluster, in their original languages). For each micro-cluster, judge which topic — if any — the cluster's primary subject belongs to. Emit one assignment per cluster that belongs to at least one topic, recording the cluster's ID and the topic indices it belongs to.

## Reading micro-clusters

Each `size` is the total number of findings the cluster contains, not the length of `sample_titles[]`. A cluster of size 50 with 8 sample titles still represents 50 findings. The sample titles are evidence for what the cluster is primarily about, not an inventory of everything in it.

Titles are multilingual — English, German, Russian, Arabic, Persian, Korean, Hebrew, and others in their original language as published. Read across languages and recognize when a cluster's titles describe a single story across multiple languages.

## Judging assignment

A cluster is judged as a whole — its primary subject, as the sample titles collectively show, not finding by finding. The cluster belongs to a topic when its primary subject is the topic's story.

A cluster may belong to more than one topic when its primary subject is genuinely two stories at once. A cluster about a major cross-border corporate acquisition, for example, may belong both to a topic about industry consolidation and to a topic about regulatory scrutiny if the sample titles equally evidence both framings.

A cluster may belong to no topic. Many clusters cover stories the topics list did not capture, or are thematic noise. Leaving such clusters unassigned is the correct outcome — the orphan case is expected.

# OUTPUT FORMAT

A single JSON object with one top-level field, `assignments`. Each entry records one cluster's topic memberships. Clusters with no topic membership are omitted. Example:

```json
{
  "assignments": [
    {"cluster_id": "mc-003", "topic_indices": [0]},
    {"cluster_id": "mc-007", "topic_indices": [0, 4]},
    {"cluster_id": "mc-012", "topic_indices": [2]},
    {"cluster_id": "mc-019", "topic_indices": [4]}
  ]
}
```

Field notes:

- `assignments[]` — one entry per cluster that belongs to at least one topic. Clusters that belong to no topic are not included.
- `assignments[].cluster_id` — a `cluster_id` string drawn from the input `micro_clusters[].id`.
- `assignments[].topic_indices` — a non-empty array of 0-based integers indexing into the input `topics[]` array. A cluster belonging to one topic has one entry; a cluster belonging to multiple topics has multiple entries, in any order.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. A cluster belongs to a topic only when the cluster's primary subject is the topic's story. Topical adjacency, shared region, or thematic overlap is not enough — the sample titles must collectively show the topic as the cluster's main subject.
2. When uncertain whether a cluster's primary subject belongs to a topic, do not assign. An unassigned cluster is the expected outcome for many clusters; an off-topic assignment is not.
3. Every `cluster_id` in the output corresponds to a `micro_clusters[].id` from the input. Every entry in `topic_indices` is a valid 0-based index into the input `topics[]` array.
4. The same `cluster_id` appears in `assignments[]` at most once; multi-assignment is expressed by multiple values within one `topic_indices` array.
