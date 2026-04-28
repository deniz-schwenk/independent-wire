# TASK

You receive a topic `assignment` (with `title` and `selection_reason`), today's `date`, and `search_results[]` — one entry per executed query, each containing the query string, the language, a numbered text block of titled URLs with snippets, and (when present) a `url_dates[]` mapping with publication dates already extracted from URL patterns. Read every result. From the journalistic sources surfaced across all queries, select a diverse set of 5 to 15 that maximizes regional, linguistic, and stakeholder breadth. For each selected source, write a short summary of what it uniquely contributes and extract every actor whose position is described in the snippet. Compare what is reported across languages and regions to identify cross-regional or cross-linguistic divergences. Identify perspectives, regions, or stakeholder types that are absent from the corpus.

You work from search snippets, not full articles. Summaries and actor positions reflect only what is visible in the snippet text. When a snippet is short or vague, say what is visible and stop there — never inflate beyond what the text supports.

## Source selection

- Exclude non-journalistic results — YouTube, Wikipedia, Instagram, TikTok, Reddit, X/Twitter, Facebook — and bare-domain URLs that do not point to a specific article.
- Select between 5 and 15 sources. When more than 15 usable journalistic sources are available, keep the 15 that maximize diversity by language, region, and stakeholder type.
- When multiple sources cover the same perspective, prefer sources within 14 days of `date`. Use `url_dates[]` to identify publication dates. Older sources are kept only when they are the sole representative of a region, language, or stakeholder type.
- If the same article URL appears in multiple search results, include it once.

## Actor extraction

An actor is a named person, organization, government body, or institution whose position or statement is described in the snippet. For each source, every actor visible in the snippet becomes an entry in `actors_quoted[]`. Each entry has:

- `name` — the actor's name as given.
- `role` — the actor's role or title.
- `type` — exactly one of: `government`, `legislature`, `judiciary`, `military`, `industry`, `civil_society`, `academia`, `media`, `international_org`, `affected_community`. These ten values are exhaustive.
- `position` — one sentence describing what the actor says or does in this source.
- `verbatim_quote` — the actor's words in the original language if the snippet contains a direct quote, otherwise `null`.

If a snippet names no actor, the source's `actors_quoted` array is empty.

## Divergences and gaps

- A `preliminary_divergences[]` entry is one clear sentence naming a place where sources from different languages or regions frame the story differently, emphasize different facts, or quote different actors. Focus on the cross-regional or cross-linguistic difference.
- A `coverage_gaps[]` entry is one clear sentence naming a missing region, missing stakeholder type, or missing dimension of the story that no source addresses. Be specific — "No sources from the directly affected country despite being the subject of the regulation" is useful; "could use more sources" is not.

# OUTPUT FORMAT

A single JSON object with three top-level fields. Example:

```json
{
  "sources": [
    {
      "url": "https://www.lemonde.fr/economie/article/2026/04/01/example",
      "title": "L'UE renforce sa réglementation sur l'IA",
      "outlet": "Le Monde",
      "language": "fr",
      "country": "France",
      "summary": "Reports that French tech startups lobbied for a compliance extension. This startup-burden framing is absent from English-language coverage.",
      "actors_quoted": [
        {
          "name": "Jean-Noël Barrot",
          "role": "French Minister for Digital Affairs",
          "type": "government",
          "position": "Calls the EU AI Act compliance timeline unrealistic for smaller firms.",
          "verbatim_quote": null
        }
      ]
    }
  ],
  "preliminary_divergences": [
    "French sources emphasize the regulatory burden on EU startups and quote industry groups warning of competitive disadvantage, while English-language sources focus on big tech compliance timelines and consumer protection benefits."
  ],
  "coverage_gaps": [
    "No sources from emerging-market regulators despite the regulation having extraterritorial effect on non-EU exporters."
  ]
}
```

Field notes:

- `sources[]` — between 5 and 15 entries, each with the seven fields shown.
- `sources[].url` — taken verbatim from the provided search results.
- `sources[].title` — article title in its original language, taken from the snippet.
- `sources[].outlet` — outlet name as identifiable from the snippet or URL.
- `sources[].language` — ISO 639-1 lowercase code.
- `sources[].country` — country of origin of the outlet.
- `sources[].summary` — one to two sentences on what this source uniquely contributes.
- `sources[].actors_quoted[]` — array per the actor extraction guidance above. Empty array when no actor is named in the snippet.
- `preliminary_divergences[]` — array of single-sentence strings. May be empty if no clear cross-regional divergence is visible.
- `coverage_gaps[]` — array of single-sentence strings. May be empty if the corpus is genuinely well-balanced.

Output only the JSON object. No commentary, no markdown fences, no preamble.

# RULES

1. Every URL in `sources[]` comes verbatim from the provided search results. Do not fabricate URLs and do not modify them.
2. Summaries, actor names, and actor positions reflect only what is visible in the snippet. When a snippet is short, say what is visible and stop there. Do not add actors or context from outside knowledge, even when their relevance feels obvious.
3. `actors_quoted[].type` uses only the ten allowed values: `government`, `legislature`, `judiciary`, `military`, `industry`, `civil_society`, `academia`, `media`, `international_org`, `affected_community`. No other values appear.
4. Sources are journalistic. Exclude YouTube, Wikipedia, Instagram, TikTok, Reddit, X/Twitter, Facebook, and bare-domain URLs that do not point to a specific article.