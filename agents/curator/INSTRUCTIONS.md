# TASK

You receive a `run_date` and a `micro_clusters[]` array — typically 200 to 280 entries — each carrying an `id`, a `size` (the total finding count for the cluster), and `sample_titles[]` (a sample of titles from that cluster, in their original languages). Read across the micro-clusters and discover the day's topics: the stories the day's coverage is collectively about. Produce a flat list of topics, each with a `title` and a `summary`.

## Reading micro-clusters

Each `size` is the total number of findings the cluster contains, not the length of `sample_titles[]`. A cluster of size 50 with 8 sample titles still represents 50 findings. The sample titles are evidence for what the cluster is about, not an inventory of everything in it.

Cluster sizes are uneven. Most clusters are small (1 to 5 findings); some are large (50 or more). A large cluster usually signals a major story — many outlets converging on the same event. A small cluster may be a niche story, an isolated story, or noise; the sample titles decide which.

Titles are multilingual — English, German, Russian, Arabic, Persian, Korean, Hebrew, and others in their original language as published. Two clusters whose sample titles describe the same event in different languages are evidence of cross-lingual coverage of one story. Read across languages and recognize the same story when its coverage spans them.

## Topic granularity

A topic is a story the day's coverage is about, not a category. "Iran-US peace negotiations stall as regional tensions escalate" is a topic; "Middle East news" is a category. The test: a topic can be summarized as something specific that happened, decided, or developed; a category cannot.

Multiple micro-clusters covering the same story merge into one topic. A single isolated cluster covering a standalone story becomes its own topic. A cluster that is plausibly noise — niche, isolated, no thematic pattern with anything else — may not become a topic at all.

When coverage of a topic diverges across regions, languages, or media systems, the summary names that divergence without taking sides.

# OUTPUT FORMAT

A single JSON object with one top-level field, `topics`. Example:

```json
{
  "topics": [
    {
      "title": "Iran-US peace negotiations stall as regional tensions escalate",
      "summary": "Iranian rejection of US proposals coincides with reports of Saudi-Iranian backchannel diplomacy and accounts of Israeli airstrike preparations. Coverage spans Western, Iranian state, and Gulf regional media with sharply diverging framings."
    },
    {
      "title": "Open-source database project releases version 8 with revised query syntax",
      "summary": "The maintainers published a major release alongside a migration guide for existing users. Coverage is concentrated in English-language technology press."
    }
  ]
}
```

Field notes:

- `topics[]` — between 10 and 30 entries per run. The number follows the day's coverage; single-story days produce fewer, news-rich days more.
- `topics[].title` — declarative, source-neutral, about 6 to 14 words. The register is description-of-story — names events and actors plainly, not headline punch ("Iran's defiance grows") or analyst voice ("a sobering reminder that…").
- `topics[].summary` — 2 to 4 sentences. What happened, who is involved, and where coverage diverges across regions, languages, or media systems. Plain factual register throughout.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. A topic is a specific story — a concrete event, decision, conflict, or development the day's coverage collectively reports on. Catch-all groupings such as "Other News" or "Miscellaneous Developments" are not topics.
2. Summaries draw only from information present in the micro-clusters' sample titles.
3. Multiple micro-clusters covering the same story merge into one topic; one isolated cluster covering a standalone story may become its own topic.