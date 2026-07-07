# Registry A3a — THREE-ARM backtest: Sonar vs Registry vs Ollama

_Generated 2026-07-06 08:37 UTC · $0 (registry) + $0 marginal (ollama, flat-rate sub; 186 requests) · no LLM calls · registry + ollama code run from worktree `/Users/denizschwenk/iw-registry-shadow-worktree` · production tree read-only._

Amends the two-arm A3a report (`BACKTEST-REPORT.md`) by adding the **Ollama Web Search** arm — the interim `IW_SEARCH_PROVIDER` switch candidate for the 07-08 window, ahead of the registry endgame. Same 9 topics, same stored query strings.

**Spec note (deliberate deviation from the task).** The task specified `max_results=10`; Deniz overrode this to run the ollama arm with **no `max_results`** — Ollama's server default of **5** — because production `_search_ollama` sends `{"query": q}` and nothing else. The backtest therefore measures what the flip would *actually* deliver on 07-08, not an enhanced variant. (Result: ollama and the registry arm are now both ~5 items/query, so their breadth is directly comparable.)

## Interim-switch recommendation (ollama replaces Sonar): **QUALIFIED GO** — cost-driven, conditional on reach monitoring

**Mechanical gate: NO-GO — by a single point.** breadth 0.69 (OK @≥0.60); non-English reach 79% (SHORT @≥80% — a 1pp miss); datedness 22% url-recoverable vs Sonar 29% (OK @−10pp tol). The strict gate fails on reach alone, and by one point.

**Reasoned recommendation.** Across 9 topics ollama delivers **0.69× Sonar's host breadth** — near-Sonar, and **2.9× the registry's 0.24** — at **$0 marginal, 0/186 failed** requests, with **datedness at parity** (22% vs 29% url-recoverable; both weak, and the researcher dates from content regardless — Sonar's own dossier dated share is only 32%). The lone shortfall is reach, and it is soft in two ways. First, the 79% is measured over only the **43%** of ollama hosts that are in the outlet_registry — **57% are whole-web hosts whose language is unattributable** — so it is a *lower bound*. Second, part of the gap is real: at Ollama's default 5 results/query the arm returns fewer hosts/topic than uncapped Sonar, so it surfaces fewer languages on breadth-heavy topics — reach is **86–100% on the Russia/Iran topics but dips to 45%/60%** on NATO-t1 and the AfD-protest topic. Given Deniz cannot carry Sonar and the registry (0.24 breadth) is far too narrow to substitute for whole-web today, **ollama is the only viable interim bridge**, and on breadth + cost + reliability it is a good one. **GO for the interim 07-08 window, conditional on:** (1) **monitor non-English reach** after the flip — it is the pipeline's core value and the one metric genuinely at risk; (2) if reach proves thin, **raising `max_results` above the default 5** is the lever to recover it (still $0 marginal — note this would deviate from today's prod-parity default); (3) **watch subscription throttling** — search now stacks on translation + fetch (+ later GLM stages) with unquantified usage limits; (4) ship with **loud `provider_used` logging and a one-line revert**. This is *not* a clean quality-neutral swap — the source mix shifts hard (only **16% host overlap** with Sonar) — but it is an acceptable, reversible cost trade for an interim window, and the registry endgame is unchanged.

**Asymmetry caveat (unchanged from the 2-arm report):** the registry fetches *now* against each feed's rolling window, while Sonar (and now the ollama replay) search the whole web. Older topics (07-04/05) are structurally disadvantaged for the *registry*; the ollama and Sonar arms are both whole-web so their comparison is time-fair on every topic. The fresh slice (07-06) is the least-unfair for the registry.

## Aggregate gate-precursor numbers (three arms)

| Metric | Sonar (stored) | Registry | Ollama |
|---|---|---|---|
| Unique hosts ÷ Sonar hosts, mean | 1.00 (ref) | **0.24** | **0.69** |
| Overlap with Sonar hosts, mean | — | 5% | 16% |
| Datedness — url-recoverable share, mean | 29% | 100% (feed pubDate) | **22%** |
| Datedness — Sonar dossier `estimated_date`, mean | 32% | n/a | n/a |
| Language coverage of Sonar's languages, mean | 1.00 (ref) | see 2-arm report | **79%** |
| Ollama language-unknown share (hosts not in registry), mean | — | — | 57% |
| Requests (ollama; flat-rate, $0 marginal) | — | — | 186 (0 empty) |

_Datedness rows use the pipeline's own `_extract_date_from_url_local` on each arm's result URLs (like-for-like); the registry is 100% by construction (undated feed items dropped), so its 'url-recoverable' cell is n/a — it is dated from feed pubDates, a stronger guarantee. The Sonar dossier row is the LLM-assembled `estimated_date` share, kept for continuity with the 2-arm report._

## Per-topic — breadth & overlap

| Day | T | Topic | Age h | Sonar hosts | Reg hosts | Oll hosts | Oll∩Sonar | Reg∩Sonar | Oll-only | Reg-only | Sonar items | Reg items | Oll items (raw) |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 07-04 | 0 | Russian strikes and Ukrainian coun | 51 | 96 | 22 | 60 | 13 | 5 | 47 | 17 | 15 | 77 | 68 (69) |
| 07-04 | 1 | NATO summit convenes with division | 51 | 78 | 19 | 51 | 6 | 4 | 45 | 15 | 15 | 44 | 60 (60) |
| 07-04 | 2 | Lebanon-Israel tensions escalate w | 51 | 66 | 10 | 44 | 14 | 7 | 30 | 3 | 15 | 35 | 53 (54) |
| 07-05 | 0 | Russia-Ukraine war: Zelensky denie | 27 | 79 | 21 | 60 | 13 | 3 | 47 | 18 | 15 | 71 | 65 (66) |
| 07-05 | 1 | Iran holds funeral for slain Supre | 27 | 90 | 19 | 56 | 8 | 6 | 48 | 13 | 15 | 59 | 67 (69) |
| 07-05 | 2 | Thousands protest in Germany again | 27 | 62 | 18 | 52 | 22 | 3 | 30 | 15 | 15 | 51 | 55 (57) |
| 07-06 | 0 | Russia launches deadly missile and | 3 | 74 | 19 | 47 | 10 | 3 | 37 | 16 | 15 | 53 | 57 (60) |
| 07-06 | 1 | NATO summit in Ankara: Trump to me | 3 | 84 | 24 | 58 | 10 | 3 | 48 | 21 | 15 | 71 | 69 (69) |
| 07-06 | 2 | Venezuela earthquakes: death toll  | 3 | 60 | 12 | 43 | 10 | 2 | 33 | 10 | 15 | 29 | 49 (54) |

## Per-topic — datedness, language, cost

| Day | T | Sonar url-dated | Oll url-dated | Sonar dossier-dated | Oll lang-cov | Oll lang-unknown | Oll langs | Oll req | Oll fail | Reg wall | Oll wall |
|---|---|--:|--:|--:|--:|--:|---|--:|--:|--:|--:|
| 07-04 | 0 | 32% | 31% | 53% | 100% | 51% | ar,en,es,fr,ko,ru,uk,zh | 23 | 0 | 143020ms | 21193ms |
| 07-04 | 1 | 34% | 22% | 20% | 45% | 72% | en,fr,it,tr,uk | 20 | 0 | 99213ms | 18334ms |
| 07-04 | 2 | 23% | 11% | 40% | 100% | 57% | ar,en,fa,fr,he,tr | 18 | 0 | 110534ms | 16015ms |
| 07-05 | 0 | 24% | 26% | 33% | 67% | 58% | en,fr,hi,ko,ru,tr,uk | 22 | 0 | 112881ms | 19322ms |
| 07-05 | 1 | 25% | 21% | 27% | 92% | 49% | ar,de,en,fa,fr,he,hi,ko,ru,tr,ur,zh | 23 | 0 | 108914ms | 19874ms |
| 07-05 | 2 | 31% | 22% | 33% | 60% | 55% | ar,de,en,it,ko,pl | 19 | 0 | 87359ms | 16474ms |
| 07-06 | 0 | 21% | 16% | 27% | 86% | 53% | ar,en,fr,ja,ru,tr,uk | 20 | 0 | 97008ms | 17123ms |
| 07-06 | 1 | 22% | 19% | 27% | 86% | 62% | ar,de,en,es,fa,ja,ko,pt,tr,uk | 23 | 0 | 114102ms | 19832ms |
| 07-06 | 2 | 52% | 35% | 27% | 78% | 57% | ar,de,en,es,pt,ru,tr | 18 | 0 | 57970ms | 15890ms |

### Column notes
- **Oll hosts** = unique domains over the ollama results (NO max_results → Ollama default 5/query, prod parity; deduped by URL). **Reg hosts** = registry top-5/query deduped. **Sonar hosts** = all domains in the stored raw results (whole-web, no cap). Ollama and registry are now both ~5/query so directly comparable; Sonar is uncapped whole-web.
- **Oll items (raw)** = deduped delivered items (sum of per-query results before URL-dedup). Each query is one request → `Oll req`; `Oll fail` = queries that returned nothing (transient error after one retry, or empty).
- **Oll url-dated** / **Sonar url-dated** = share of that arm's result URLs from which `_extract_date_from_url_local` recovers a date — the pipeline's real extractor, applied identically to both. Ollama results carry no native dates (title/url/content only), same as Sonar; this is the honest, non-fabricated datedness for both.
- **Oll lang-cov** = share of Sonar's languages (attributed to Sonar hosts via the same outlet_registry lookup) that ollama's hosts also cover. **Oll lang-unknown** = share of ollama result URLs whose host has no outlet_registry entry (language genuinely unknown — labelled, not guessed).

_Verdict inputs: breadth 0.69 (bar ≥0.60); reach 79% (bar ≥80%); datedness 22% vs Sonar 29% (tol −10pp). → **NO-GO**._
