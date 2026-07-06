# Workstream — Multilingual Source Expansion + Translate-to-English Clustering

Living tracker for a multi-session workstream. Last updated: 2026-07-01.

## What this is
One coupled workstream, two threads:
1. **Source expansion** — grow the feed pool from a research-validated list, in small
   reversible batches, to reduce Western/English over-representation (a core Vision goal).
2. **Multilingual clustering (MADLAD sidecar)** — translate each finding's title+summary to
   English *before embedding*, so non-Latin / low-resource languages cluster reliably. The
   pinned multilingual embedder bridges European languages fine but under-serves scripts like
   Bengali/Zulu/Uzbek natively.

They are coupled: the new feeds bring exactly the languages the clustering exists to serve.

## Current state (2026-07-01)
- **Batch 1 — LIVE** (commit `dcf5be6`): 7 non-Latin feeds added to `config/sources.json` +
  `config/outlet_registry.json`, native pipeline, MADLAD flag OFF. All verified live from the
  Mini runner. Feeds: ar Al-Masry Al-Youm · bn Prothom Alo · ne Online Khabar · th Prachatai ·
  zu Isolezwe · sw Mwananchi · uz Kun.uz.
- **Batch 2 — LIVE** (2026-07-06, this commit): 7 more independent non-Latin feeds
  (ar/th/zh/ja), same additive pattern, MADLAD flag OFF. All 7 re-verified live from this
  machine via the real fetch path (207 entries/24h, 0 encoding warnings). Feeds:
  ar Al-Sumaria (Iraq) · ar Mosaique FM (Tunisia) · th Khaosod (supplements Prachatai's
  low volume; nothing removed) · zh Liberty Times (Taiwan, pan-green lean recorded) ·
  ja Mainichi Shimbun · ja Asahi Shimbun (registry entry pre-existed — left unchanged;
  feed added on the verified `https://rss.asahi.com/...` URL) · zh Initium Media (HK).
  `LANGUAGE_NAMES` gap closed for ne/zu/uz (ja/zh/th were already present). Landed after the
  2026-07-06 06:00 run verified the HydrationPhase2 GLM-5.2 swap green (one production change
  per day). Observation window: 3 days, same checklist as Batch 1.
- **MADLAD sidecar** — built (commit `7e920b1`; flag `IW_CLUSTER_TRANSLATE`, default OFF; slot
  `curator_findings_clustering`), validated, 7-day shadow-tested (stable), requirements spec
  complete. **NOT enabled.** Model self-converted (Apache-2.0, CT2-int8, ~2.8 GB) on the Mini.

## Key decisions & learnings (do not re-litigate)
- **MT backend = MADLAD-400 (Apache-2.0)** via CTranslate2 int8 on CPU. NLLB-200 REJECTED
  (CC-BY-NC / Meta "not for production" — breaks the "anyone can self-host" value). OPUS-MT
  rejected (regresses low-resource; `mul-en` unusable on zu/uz/sw/bn).
- **No threshold recalibration needed.** The feared "English cosines shift up → more off-topic"
  is backwards: the embedder is already cross-lingually aligned, so the shift is *downward* and
  off-topic separation *improves* (off-topic rate 8.23% → 6.81% at T=0.55). Keep T=0.55 / 0.7.
  (Caveat: validated on European/Cyrillic labels only — see blocker 5.)
- **Runtime deps are light**: `ctranslate2` + `sentencepiece` only (no torch/transformers —
  those are conversion-only, proven byte-identical). Ships as an optional `[multilingual]` extra.
- **Latency**: CT2-int8/CPU beats transformers/MPS on every axis on the M4 (full-day cold ≈33
  vs ≈85 min). CT2 is the production path.
- **Operational cost is real and recurring**: ~35 min + ~24.7 GB peak RAM *per day*. The
  content-hash cache does NOT amortize across days (news rarely repeats verbatim). 24.7 GB sits
  near the Mini's 32 GB ceiling → needs CT2 batch-chunking before any enablement. Idea on the
  table (Deniz): spread *translation only* across the day (e.g. every 6 h) to quarter the peak —
  same total work, lower peak, no end-of-day block; clustering + publish stay once-daily.
- **The value is real for non-Latin langs** (batch-1 eval: bn 0→~10 attach, etc.); European
  langs already cluster fine natively, where MADLAD is ~neutral. So MADLAD only earns its cost
  once low-resource feeds actually flow — which is what the source-expansion thread delivers.

## Enablement blockers (before any flag flip) — src: scratch/MADLAD-INTEGRATION-REQUIREMENTS.md
1. Rewrite the sidecar backend to a transformers-free MADLAD `<2en>` sentencepiece path (the
   in-repo backend is NLLB/FLORES-specific; a working `madlad_backend.py` exists in scratch).
2. Swap `MODEL_NAME` NLLB→MADLAD (cache self-invalidates cleanly).
3. Stage the full runtime artifact (CT2 dir + `spiece.model`, which is NOT inside the CT2 dir)
   + Apache-2.0 compliance (LICENSE, statement of changes, attribution). Distribution: host the
   CT2 artifact (e.g. HF Hub) with the pinned conversion script as reproducible fallback.
4. Add the `multilingual` optional extra to pyproject.
5. **Decide low-resource off-topic gating** — the off-topic safety re-audit only has labels for
   European/Cyrillic. ar/bn/ne (and future th/zu/…) are unvalidated (no labeled set). Product
   decision: scope to validated langs, or gate the new ones behind a future labeled re-audit.
- Plus: the ~25 GB RAM chunking fix; a client read-timeout on the OpenRouter Curator (hung once).

## Roadmap
- **Now:** batch 1 is live → let it run several days → read the MADLAD shadow to see it work on
  real live ar/bn/ne data for the first time (previously never observed — those langs weren't in
  production). Confirms whether the batch-1 lift holds on live data.
- **Next batches:** ~69 more validated feeds remain (76 live of 83), added batch-by-batch, each
  only once the prior is stable. Prioritize non-Latin scripts (the langs the clustering serves);
  ru (11) + European feeds are lower priority (already cluster natively).
- **Then:** the MADLAD enablement decision — needs the 5 blockers resolved + the shadow showing
  real value on live low-resource data.

## Follow-ups / small fixes
- `ne`/`zu`/`uz` missing from `LANGUAGE_NAMES` → display shows the bare code, not the language
  name. Cosmetic; complete the table (it grows with each batch).
- Prachatai (th) low volume (~1/24 h) — watch; Khaosod (th, tier-2) is the fallback outlet.
- Stray untracked `.env.bak-1781940769` in the repo root — deletable.
- An-Nahar (ar) timed out at research verification (Cloudflare vs the checker, not dead — it
  ingested fine in batch-1 testing) — candidate for a runner-side recheck if a 2nd Arabic source
  is wanted.

## Where things live (cross-machine map — this has bitten us repeatedly)
- **Validated feed research list: Air only** — `~/Documents/independent-wire/research/
  feed-expansion-2026-06/final_verified.json` (83 candidates, 76 live). NOT in the repo → does
  not travel via git. To integrate a feed: extract its data on the Air and bake it into the brief.
- **MADLAD scratch reports (finalize / requirements / shadow): Mini only** — under `scratch/`
  (untracked). Their key findings are summarized in this doc so they survive if scratch is lost.
- **Production repo (live): Mini** `~/iw/independent-wire`. **Dev clone: Air**
  `~/Documents/independent-wire/repo-clone`.
- **Model artifact: Mini** `scratch/madlad/` (CT2-int8, ~2.8 GB).

## Session log
- 2026-07-01 — MADLAD finalized (convert/latency/control sweep, all pass); requirements spec +
  off-topic re-audit done (no recalibration); 7-day shadow = stable; batch 1 (7 feeds) integrated
  and pushed (`dcf5be6`); this tracker created.
- 2026-07-06 — Batch 2 integrated (7 feeds ar/th/zh/ja) after the 06:00 run validated the
  HydrationPhase2 GLM-5.2 swap green. Re-verified all 7 live from this machine via the real
  fetch path (Al-Sumaria 20 · Mosaique FM 40 · Khaosod 50 · Liberty Times 40 · Mainichi 20 ·
  Asahi 35 · Initium 2 = 207 entries/24h; 0 mojibake, 0 encoding warnings; Asahi on verified
  https URL; Liberty Times spans news./ec./sports.ltn.com.tw → all fold to `ltn.com.tw`).
  asahi.com registry entry pre-existed (tier-1 independent) — left unchanged. `LANGUAGE_NAMES`
  ne/zu/uz added. `sources.json` +7, `outlet_registry.json` +6 (asahi already present),
  `_helpers.py` +3 langs. Full suite: 880 passed, 4 skipped, 1 pre-existing env-only failure
  (`test_curator_monitor`, missing 05-11 baseline fixture). MADLAD flag stays OFF.

## Pre-enable additions from CODE-REVIEW-2026-07-02 (added 2026-07-02)

Fold into the enablement checklist before flipping `IW_CLUSTER_TRANSLATE`:

- **M-T6** — empty segments are sent to NLLB and its hallucinations are
  cached permanently (`translate_sidecar.py:449-451,481-485,517-521`);
  the skip guard is only both-empty. Title-only findings hit this.
- **Cache key excludes backend** (`translate_sidecar.py:191-196,295-336`)
  — CT2 (no truncation) and transformers (128-token truncation) produce
  different English for the same key; backend switches silently serve
  the other backend's cached outputs.
- **`LANGUAGE_NAMES` missing ne/zu/uz** (`src/stages/_helpers.py:35-45`)
  — confirmed consequence-free today; becomes live once the sidecar
  normalizes name-form language inputs.
