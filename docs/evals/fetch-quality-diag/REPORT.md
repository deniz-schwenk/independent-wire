# Fetch quality diagnosis — ollama web_fetch vs direct HTTP + trafilatura

_Deterministic, $0 beyond the flat-rate ollama sub (30 ollama fetch calls). No LLM. Read-only on production; both arms fetched live, sequential, 15s timeout, no retries. Trafilatura arm = production `src.hydration.hydrate_urls` (raw-bytes trafilatura, runner UA, robots, pubdate=metadata>Last-Modified>URL). Ollama arm = production `_fetch_via_ollama` semantics (POST /api/web_fetch, title+content)._

## Part A — current reality from the code (no fetching)

### The premise is inverted: hydration does NOT use ollama
The task states *"Hydration's article fetch tries Ollama's web_fetch API first … and falls back to direct HTTP + trafilatura."* **In the current code this is not so.** The hydrated pipeline's fetch stage is built by `make_hydration_fetch(hydration_fetcher)` with `hydration_fetcher=None` in production:

- `scripts/run.py:849` → `build_hydrated_stages(web_search_tool=…)` passes **no** `hydration_fetcher`.
- `src/stages/topic_stages.py:1832-1837` → with no fetcher injected, the stage uses `_default_fetcher` → `src.hydration.hydrate_urls` (aiohttp + trafilatura, raw bytes).
- `src/hydration.py` contains **no** reference to ollama / web_fetch — it is trafilatura-only.
- The ollama fetch path lives solely in the **`web_fetch` tool** (`src/tools/web_fetch.py`: `_fetch_via_ollama` first, raw-`response.text` HTTP fallback — note: the tool's fallback is **not** trafilatura). That tool is only *registered* (`src/tools/__init__.py:14`); grep finds it **injected into no stage and executed by no agent**. It is dead/dormant in the production pipeline.

**Observed method split for hydration: 100% trafilatura / 0% ollama** — not by logging, but by construction (there is no ollama branch in the hydration path). This is *not* the silent-ollama-usage gap the task anticipated; hydration simply never calls the subscription for fetch, so **hydration imposes $0 ollama-sub load today.** (Logging note: hydration logs per-URL trafilatura status but no method marker — moot, as there is only one method. The `web_fetch` tool *does* log an ollama-vs-fallback marker, but it is unused.)

### Pubdate: the ollama path structurally loses dates
`src/hydration.py:350` `_extract_published_date` resolves the date from **trafilatura metadata > HTTP Last-Modified > URL pattern** (metadata covers `article:published_time`, JSON-LD `datePublished`, `<time>`):

```python
# src/hydration.py:356-374
meta = trafilatura.extract_metadata(html)      # article:published_time, JSON-LD, <time>
iso = _normalise_date_to_iso(getattr(meta, 'date', None))
if iso: return iso
iso = _extract_date_from_last_modified(last_modified)   # HTTP header
if iso: return iso
return _extract_date_from_url(url)              # weakest fallback
```

The ollama `web_fetch` API returns **only** `title` + `content` (`src/tools/web_fetch.py:32-37`) — no date field. Empirically confirmed here: across all 30 live calls the response keys were `['content', 'links', 'title']` (no date). So routing hydration through ollama would **collapse pubdate to the URL-pattern fallback alone**, discarding the two stronger signals. Since the hydration dossier carries `published_date` downstream, this is a real regression independent of text quality.

## Part B — head-to-head on 30 real workload URLs

Sample: 30 URLs seeded-random (seed 20260706) from the last 3 days of `hydration_fetch_results` (pool 180, deduped). No language quota. **Script split as drawn: 27 Latin / 3 non-Latin.**

### Aggregates (ollama / trafilatura), split by script

| Slice | Success | Median words | Len ratio (oll÷traf) | Nav-density /1k (↓ better) | % w/ enc. artifacts | Pubdate recovered | Median wall ms |
|---|---|---|---|---|---|---|---|
| All (n=30) | 73% / 77% | 538 / 306 | 1.47× | 0.0 / 0.0 | 0% / 0% | 57% / 93% | 2176 / 1195 |
| Latin (n=27) | 70% / 78% | 587 / 332 | 1.40× | 0.8 / 0.0 | 0% / 0% | 52% / 93% | 2254 / 1197 |
| non-Latin (n=3) | 100% / 67% | 430 / 138 | 2.93× | 0.0 / 0.0 | 0% / 0% | 100% / 100% | 1722 / 1099 |

_Success = usable main text (ollama: ≥120 words returned; trafilatura: status==success). Nav-density = boilerplate/nav tokens per 1000 words (lower = cleaner). Enc. artifacts = share of URLs whose extracted text contains U+FFFD replacement chars or classic UTF-8-as-Latin1 mojibake. Pubdate = trafilatura's full extractor vs the URL-pattern-only signal available on the ollama path._

> **Small-n caveat:** only 3 of the 30 drawn URLs are non-Latin (all Cyrillic/Russian). Despite batch-1/2's non-Latin feeds, the *hydrated* workload of the last 3 days is ~90% Latin — non-Latin sources are thin in what actually reaches the fetch stage. The non-Latin row is directional only; both arms were encoding-clean on it.

### Per-URL (30 rows)

| # | Script | Lang | Outlet | oll ok | traf ok | oll w | traf w | ratio | oll nav | traf nav | oll enc | traf enc | oll date | traf date | oll ms | traf ms |
|--:|---|---|---|:--:|:--:|--:|--:|--:|--:|--:|:--:|:--:|:--:|:--:|--:|--:|
| 1 | Lat | uz | Kun.uz | Y | Y | 462 | 359 | 1.29 | 4.33 | 0.0 | 0 | 0 | Y | Y | 467 | 1141 |
| 2 | Lat | en | Press TV | Y | Y | 907 | 512 | 1.77 | 7.72 | 0.0 | 0 | 0 | Y | Y | 402 | 2190 |
| 3 | Lat | es | El País | · | Y | 0 | 906 | 0.00 | 0.0 | 0.0 | 0 | 0 | Y | Y | 10315 | 1631 |
| 4 | Lat | es | Infobae | Y | Y | 1055 | 506 | 2.08 | 0.0 | 0.0 | 0 | 0 | Y | Y | 3582 | 1177 |
| 5 | Lat | en | ReliefWeb | · | Y | 0 | 60 | 0.00 | 0.0 | 0.0 | 0 | 0 | · | Y | 10332 | 1361 |
| 6 | non | ru | Novaya Gazeta  | Y | Y | 430 | 234 | 1.84 | 0.0 | 0.0 | 0 | 0 | Y | Y | 2208 | 2002 |
| 7 | Lat | en | Japan Today | Y | Y | 723 | 2001 | 0.36 | 2.77 | 0.0 | 0 | 0 | · | Y | 5947 | 2929 |
| 8 | Lat | en | Japan Today | Y | Y | 766 | 1672 | 0.46 | 2.61 | 0.0 | 0 | 0 | · | Y | 4927 | 2204 |
| 9 | Lat | fr | RFI | Y | Y | 707 | 518 | 1.36 | 1.41 | 1.93 | 0 | 0 | Y | Y | 4200 | 2529 |
| 10 | non | ru | Novaya Gazeta  | Y | Y | 556 | 138 | 4.03 | 0.0 | 0.0 | 0 | 0 | Y | Y | 1532 | 1099 |
| 11 | Lat | en | ReliefWeb | · | Y | 0 | 205 | 0.00 | 0.0 | 0.0 | 0 | 0 | · | Y | 7811 | 1958 |
| 12 | Lat | en | Moscow Times | Y | Y | 587 | 332 | 1.77 | 13.63 | 0.0 | 0 | 0 | Y | Y | 1929 | 1066 |
| 13 | Lat | en | Le Monde | · | · | 40 | 46 | 0.87 | 0.0 | 0.0 | 0 | 0 | Y | Y | 1325 | 1187 |
| 14 | Lat | en | The Guardian | Y | Y | 479 | 315 | 1.52 | 0.0 | 0.0 | 0 | 0 | · | Y | 1625 | 1118 |
| 15 | Lat | en | NDTV | Y | · | 371 | 0 | — | 8.09 | 0.0 | 0 | 0 | · | · | 5876 | 1073 |
| 16 | Lat | es | El Financiero | Y | Y | 814 | 386 | 2.11 | 0.0 | 0.0 | 0 | 0 | Y | Y | 1474 | 1847 |
| 17 | Lat | en | ReliefWeb | · | · | 0 | 49 | 0.00 | 0.0 | 0.0 | 0 | 0 | · | Y | 7780 | 1308 |
| 18 | Lat | en | Ukrinform | · | · | 0 | 0 | — | 0.0 | 0.0 | 0 | 0 | · | · | 1828 | 1079 |
| 19 | Lat | en | Moscow Times | Y | Y | 749 | 480 | 1.56 | 10.68 | 0.0 | 0 | 0 | Y | Y | 1540 | 1083 |
| 20 | Lat | en | The Guardian | Y | Y | 1082 | 614 | 1.76 | 1.85 | 0.0 | 0 | 0 | · | Y | 1624 | 1129 |
| 21 | Lat | en | Kyiv Independe | Y | Y | 1199 | 256 | 4.68 | 0.83 | 0.0 | 0 | 0 | · | Y | 2145 | 1171 |
| 22 | non | ru | Meduza | Y | · | 340 | 0 | — | 0.0 | 0.0 | 0 | 0 | Y | Y | 1722 | 1080 |
| 23 | Lat | fr | RFI | Y | Y | 601 | 426 | 1.41 | 1.66 | 2.35 | 0 | 0 | Y | Y | 4682 | 1215 |
| 24 | Lat | en | Le Monde | · | · | 40 | 46 | 0.87 | 0.0 | 0.0 | 0 | 0 | Y | Y | 1785 | 1193 |
| 25 | Lat | en | NPR | · | · | 0 | 0 | — | 0.0 | 0.0 | 0 | 0 | Y | Y | 10660 | 26483 |
| 26 | Lat | fr | RFI | Y | Y | 521 | 337 | 1.55 | 1.92 | 2.97 | 0 | 0 | Y | Y | 4954 | 1182 |
| 27 | Lat | it | ANSA | Y | Y | 924 | 96 | 9.62 | 12.99 | 10.42 | 0 | 0 | Y | Y | 1838 | 1138 |
| 28 | Lat | en | BBC | Y | Y | 173 | 189 | 0.92 | 0.0 | 0.0 | 0 | 0 | · | Y | 1832 | 1206 |
| 29 | Lat | en | Kyiv Independe | Y | Y | 1199 | 297 | 4.04 | 0.0 | 0.0 | 0 | 0 | · | Y | 2254 | 1197 |
| 30 | Lat | en | DW News | Y | Y | 3640 | 2613 | 1.39 | 3.3 | 0.38 | 0 | 0 | · | Y | 2357 | 1244 |

<!-- machine deltas for recommendation -->
<!-- success oll/traf: 73%/77%; nav oll/traf: 0.0/0.0; enc-bad oll/traf: 0%/0%; date oll/traf: 57%/93%; wall oll/traf: 2176/1195ms -->

## Recommendation: KEEP trafilatura — do NOT wire ollama into hydration

**The task's flip is already the state of the world, and its premise is moot.** Hydration fetch is trafilatura-only today (Part A) and imposes zero subscription load, so there is nothing to "flip to trafilatura-first to relieve the sub." The question Part B actually answers is the reverse — *is there a quality case to ADD ollama web_fetch to hydration?* — and on these 30 URLs the answer is no.

The two arms are at **parity** on the metrics that would justify a change: success (73% ollama / 77% trafilatura), boilerplate (both clean, 0 median nav-density), and encoding integrity (both 0% artifacts, including the Cyrillic URLs — trafilatura's raw-bytes charset path holds). Ollama's one real edge is **text completeness** — a median 1.47× more words, and it rescues cases where trafilatura badly under-extracts (Kyiv Independent 256→1199w; Kyiv Independent 297→1199w; ANSA 96→924w). But that edge is outweighed by three ollama costs: (1) **pubdate regression — 57% vs 93%** recovered: the API returns only title+content, so the ollama path is limited to the URL-pattern date fallback and loses every date trafilatura reads from metadata/Last-Modified (guardian `/jul/`, japantoday, bbc, dw, kyivindependent all lose it); (2) **~1.8× slower** (2176ms vs 1195ms median, with 10s outliers); (3) it fails on sites trafilatura handles (elpais, reliefweb) and adds a subscription dependency with unquantified limits. For a pipeline whose dossiers carry `published_date`, trading ~37 points of date recovery for more article text is a bad trade.

**KEEP trafilatura-first (i.e., trafilatura-only) for hydration.** Optional, non-blocking future work: ollama's completeness win on trafilatura's under-extraction failures suggests a narrow **ollama-as-fallback-only-when-trafilatura-under-extracts** path could recover a few long articles — but only if the date is still taken from trafilatura's metadata pass (never from the ollama text), and only weighed against added sub-load. That is a separate enhancement, not a flip. Broader budget note: hydration fetch is **not** a subscription dependent, and the ollama `web_fetch` tool is registered-but-dormant — so the "fetch" line in the accumulating-dependents worry is currently $0.
