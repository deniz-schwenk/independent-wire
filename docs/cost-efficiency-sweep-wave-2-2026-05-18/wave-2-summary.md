# Wave 2 cost-efficiency sweep — consolidated summary

Six stage-isolated DeepSeek sweeps against today's 2026-05-18 substrate (`run-2026-05-18-c26864b2`). Executed autonomously in one CC session per `TASK-COST-EFFICIENCY-SWEEP-WAVE-2.md`; six per-sweep commits plus this summary as the seventh and final commit. **No production-swap recommendations** — the architect's next-morning review decides which (if any) candidates proceed to a downstream production-swap brief.

## Setup recap

- **Substrate:** today's V2 hydrated run snapshot at `output/2026-05-18/_state/run-2026-05-18-c26864b2/`. Per-sweep substrate file named in each report's §Setup.
- **Harness:** Wave-1 Option B reused verbatim (`scripts/eval_common.py`). Bypasses `Agent.run()` and calls OpenRouter via `AsyncOpenAI` directly; mirrors the production three-block User turn (`<context>` + `<instructions>`); streaming wired for DeepSeek V4 Pro `reasoning ∈ {medium, high}`. New runner files only at `scripts/eval_wave2_*.py`.
- **`max_tokens = 160000`** for every DeepSeek variant in this wave (architect's wave-2 override; Wave 1 used 64000).
- **Provider routing:** `extra_body.provider = {order: ["deepseek"], allow_fallbacks: True, require_parameters: True}` — `provider_served` was AtlasCloud on every successful call.
- **Output paths:** `output/eval/wave-2/{sweep-name}/{label}[-topic{N}].json` plus `_metrics.json` per sweep (gitignored under `output/`).

## Per-sweep best-variant table

| sweep | stage | baseline model | best variant (gating metric) | best-variant cost / call | best-variant gating value vs baseline | schema validity |
|---|---|---|---|---|---|---|
| #1 | curator_topic_discovery (run-phase) | gemini-3-flash (t=1.0) | dskflash-t05-rnone | $0.0048 | **41 topics emitted vs baseline 20** — list contains ~20 near-duplicate pairs; unique-theme coverage matches baseline (drops 2, adds 2) | 100 % (1/1) |
| #2 | resolve_actor_aliases (topic-phase) | gemini-3-flash (t=1.0, r=medium) | dskflash-t05-rnone | $0.0018 / topic | 7 / 48 / 12 alias pairs (baseline 6 / 41 / 7); every baseline pair reproduced; 4/7/3 anonymous-flag entries baseline left empty; 0 uncovered input IDs | 100 % (3/3) |
| #3 | editor (run-phase) | claude-opus-4.6 (t=0.3) | dskpro-t07-rhigh (top-3 best) **or** dskpro-t07-rnone (cheapest viable) | $0.0132 / $0.0059 | All variants 9/10 topic overlap with baseline; top-3 overlap 1/3 (t=0.5) or 2/3 (t=0.7 reasoning); same 5 themes within top-5 of every variant | 100 % (6/6) |
| #4 | hydration_phase2 re-run at 160k (topic-phase) | claude-opus-4.6 (t=0.1, max_tokens=32k) | dskpro-t07-rhigh | $0.0160 / topic | **mean 5.3 divs/topic vs baseline 8.3** — IDENTICAL to Wave-1 64k best (5.3). Lifting max_tokens 64k→160k did NOT close the gap | 100 % (18/18) |
| #5 | perspective (topic-phase) | claude-opus-4.6 (t=0.1) | dskpro-t05-rnone (most baseline-aligned) **or** dskpro-t07-rnone (cheapest equivalent) | $0.0553 / $0.0205 | mean 7.3 clusters/topic vs baseline 9.0 (~19 % short); actor coverage 76/64/78 % on best; cluster labels verbatim-equivalent to baseline editorial divisions | 88.9 % (16/18) — two content-moderation rejections at r=high on Ukraine substrate |
| #6 | bias_language (topic-phase) | claude-opus-4.6 (t=0.1) | dskpro-t05-rhigh (best quote-anchoring) **or** dskpro-t07-rmedium (most exhaustive) | $0.0188 / $0.0161 | 17 / 20 findings totals across 3 topics (baseline 15); quote-presence rate 80–100 % across variants; t05-rhigh 100/100/80 % across topics | 100 % (18/18) |

## Three-axis verdict per sweep `(viable | conditional | not-viable)`

| sweep | viability | quality delta | cost delta | one-line reason |
|---|---|---|---|---|
| #1 curator_topic_discovery | **conditional** | unique-theme parity, duplicate over-emission | 4× cheaper | candidate doubles ~20 themes into 41 emissions; downstream needs dedup before Editor consumes the list |
| #2 resolve_actor_aliases | **viable** | matches or exceeds baseline coverage | ~10-15× cheaper / topic | alias pairs identical to baseline groupings, plus anonymous-flag set baseline left empty |
| #3 editor | **viable** | 9/10 topic-set overlap; priority-order variance within top-5 | ~10-25× cheaper | every variant 100 % schema-valid, 10 topics each, same 5 themes within top-5; selection logic appears intact |
| #4 hydration_phase2 (160k re-run) | **conditional** | 36 % divergence shortfall persists at 160k | ~6× cheaper / topic | ceiling is model-capacity-bound, not budget-bound; 160k tokens didn't move the needle on best-variant mean |
| #5 perspective | **conditional** | ~19 % cluster-count short; verbatim label equivalence on top clusters | ~3-10× cheaper / topic | 2 streaming-high content-moderation rejections on Ukraine substrate (Sweep-specific failure mode); rnone variants stay clean |
| #6 bias_language | **viable** | matches or exceeds baseline findings; 80-100 % quote anchoring | ~3-6× cheaper / topic | 18/18 schema-valid; 5 of 6 variants meet/exceed baseline finding count; high quote-anchoring rate |

## Cumulative spend + skip-resume

- **Total wave-2 spend: $1.24** across 64 calls (1 + 3 + 6 + 18 + 18 + 18). 1.4 % of the $90 wave hard cap. No per-sweep $15 cap warning was triggered.
- **Skip-resume not exercised** in this wave — no interruption / restart occurred. The harness `_has_usable_cache` path is the same that successfully skip-resumed in Wave-1 Phase-3 of the Researcher-Assemble sweep (re-run added 4 streaming variants and reloaded the 6 cached `r=none` outputs). Implementation: present and unchanged.
- **Per-sweep spend:**
  - Sweep 1 curator_topic_discovery: $0.0048
  - Sweep 2 resolve_actor_aliases: $0.0053
  - Sweep 3 editor: $0.0944
  - Sweep 4 hydration_phase2: $0.3028
  - Sweep 5 perspective: $0.5900
  - Sweep 6 bias_language: $0.2426
  - **Total: $1.2399**

## Streaming-reliability notes

Across the four Pro-class sweeps (Editor, Phase 2, Perspective, Bias Language) the streaming wiring handled **48 reasoning streams** (4 sweeps × 2 reasoning levels × {1 run-call OR 3 topics}):

- **Editor:** 4 streaming calls — 0 failures.
- **Hydration Phase 2:** 12 streaming calls — 0 failures (no `buffer-then-silent` issues at 160k either).
- **Perspective:** 12 streaming calls — **2 failures**, both `reasoning=high` on **topic 1** (Ukraine drone-strikes-on-Moscow substrate, civilian-casualty / war content). Failure mode: synchronous `APIError: Upstream error from Alibaba: Output data may contain inappropriate content` — distinct from Wave-1's silent-buffer issue; AtlasCloud's content filter rejected the output before any tokens streamed. Returned in 0 s with $0.00 cost — clean fail-fast that the harness logged and continued past. `reasoning ∈ {none, medium}` on the same topic-1 substrate succeeded; the filter is sensitive to the high-reasoning trace content specifically.
- **Bias Language:** 12 streaming calls — 0 failures on the same overall substrate (Bias Language operates on the QA-corrected article body + bias_card, not the raw source dossier).

Wave-1 had 0 streaming failures on V4 Pro. Wave 2 introduces **1 new failure class** — provider-level content moderation on high-reasoning-trace output for civilian-casualty / war content. The mitigation if a swap proceeds: cap `reasoning` at `medium` on production Perspective for war / casualty topics, OR use a non-AtlasCloud DeepSeek route (the `provider.order` config makes this a one-line change).

## Cross-sweep observations

- **Sweep #4 result is the load-bearing finding for downstream architecture work.** Lifting `max_tokens` from 64 k to 160 k did **not** change the best Phase-2 variant's mean divergence count (5.3 → 5.3). The Wave-1 36 % shortfall vs Opus baseline is **model-capacity-bound on V4 Pro**, not reasoning-budget-bound. The architect's "two-pass cheaper reducer" architectural option that motivated this wave (separate from the brief but referenced in §Why) now has empirical grounding: more reasoning tokens alone don't fix the enumeration ceiling, so an architecture-level change (chained reducers, multi-call aggregation, or a model swap to a higher-capacity reducer) is what would lift the ceiling.
- **Pro-sweep ceilings are stage-specific, not uniformly capacity-bound.** Sweep #4 (Phase 2 reducer) hits a hard 5.3-mean ceiling; Sweep #3 (Editor) sees 9/10 topic overlap with baseline — essentially full quality parity; Sweep #5 (Perspective) sees 7.3-vs-9.0 cluster count (19 % shy) but verbatim-equivalent labels on top clusters; Sweep #6 (Bias Language) meets or exceeds baseline finding count on 5 of 6 variants. The Phase-2 reducer's gap therefore looks like a **role-specific** issue with cross-source-enumeration depth, not a generic Pro-class shortfall.
- **The two Flash-class sweeps both look swap-ready** by these metrics. Curator Topic Discovery has a quality wart (over-emission of near-duplicate themes — 41 vs 20) that needs a downstream dedup pass or a prompt clarification before swap. Resolve Actor Aliases is clean on every measured dimension.
- **DeepSeek prompt-cache anomaly persists across waves.** Wave-1 noted `dskpro-t07-rnone` consistently coming in dramatically cheaper than `dskpro-t05-rnone` on identical inputs (cache hit after the t05 streaming variants warmed the cache). Wave 2 reproduces the pattern: Sweep #6 `dskpro-t07-rnone` at $0.0076 vs `dskpro-t05-rnone` at $0.0311 on the same 3-topic substrate (4× cheaper). Any production-swap cost projection must be validated cache-cold; cached costs are not reachable in steady-state production.
- **Wall-time profile:** Pro-class sweeps with reasoning streaming continue to run 60-180 s per call at 160 k max_tokens (longer than at 64 k); rnone variants stay in baseline-comparable territory (~10-30 s). Topic-1 substrate (densest) consistently slowest. Production SLAs need to weigh wall-time against cost on any swap.

## Output index

Per-sweep reports + commits:

| sweep | report | commit |
|---|---|---|
| #1 | `curator_topic_discovery-report.md` | `733bd01` |
| #2 | `resolve_actor_aliases-report.md` | `3f2303f` |
| #3 | `editor-report.md` | `d8f992c` |
| #4 | `hydration_phase2-report.md` | `8c6211f` |
| #5 | `perspective-report.md` | `df97f23` |
| #6 | `bias_language-report.md` | `a346546` |
| (this summary) | `wave-2-summary.md` | (this commit) |

Per-sweep metrics + raw outputs at `output/eval/wave-2/{sweep-name}/` (gitignored). Production code untouched: `git diff main~7..main src/ agents/ src/schemas.py scripts/run.py` is empty.
