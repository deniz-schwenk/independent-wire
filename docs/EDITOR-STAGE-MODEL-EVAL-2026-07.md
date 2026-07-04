# Editor-stage model eval (2026-07) — complete (phases 1-7)

**Status: DECISION INPUT, not a cutover.** This document reports the
reconstruction, paid shadow, deterministic layer, consensus filter, blind
Architect digest, subagent panels (phases 1-6), and — appended below — the
**unblinded final decision** after the Architect returned the filled verdict
sheet (phase 7). The qualitative arbiter for editorial selection is the
**Architect**, via the blind digest. Nothing in production changed;
`scripts/run.py` and `src/` are untouched — a swap, if taken, is a separate task.

Same eval family as `docs/WRITER-STAGE-MODEL-EVAL-2026-07.md` (protocol
discipline — byte-faithful reconstruction through the production Agent path,
strict schema held at production values, leak-proof anonymization, deterministic
before qualitative), adapted to the editor's nature: it runs **once per run** (N
counts in days), topic selection has **no ground truth** (it is editorial
judgment), and its prompts last changed 2026-06-11 → the usable window is
2026-06-12 onward.

## Arms + operating points

The editor selects which of the day's candidate topics become published dossiers
(accept + priority 1-10) and writes a `selection_reason` for each. All arms ran
the **identical** production editor prompts (`agents/editor/SYSTEM.md` +
`INSTRUCTIONS.md`, unchanged across the window) and the strict `EDITOR_SCHEMA`,
on the byte-faithful reconstructed input. Only the model / reasoning / routing
differ.

| Arm | Model | Reasoning | Temp | Routing | Role |
|---|---|---|---|---|---|
| **Incumbent** | `anthropic/claude-opus-4.6` | none | 0.3 | prod | stored production editor output |
| **GLM** | `z-ai/glm-5.2` | effort `xhigh` | 0.3 | fp8 `[baidu, ambient, venice]` | challenger |
| **DeepSeek** | `deepseek/deepseek-v4-pro` | effort `xhigh` | 0.3 | fp8 `[baidu, wandb, parasail]` | challenger |
| **Sonnet-5** | `anthropic/claude-sonnet-5` | `{enabled, effort:high}` | — (omitted) | Azure | challenger |
| **Golden** | Opus-4.8 subagent | max care | — | — | quality ceiling (cost-neutral) |

Provider pins are the binding, empirically-verified fp8 sets from
`docs/GLM-PROVIDER-VERIFICATION-2026-07.md` and `docs/DEEPSEEK-FP8-PIN-2026-07.md`
(`allow_fallbacks:false` — never fp4/unverified). Golden is one fresh Opus-4.8
subagent per day executing the editor task at maximum care — a ceiling, spawned
not billed.

## Phase 1 — reconstruction (coverage)

The editor is a run-stage; its whole input is `curator_topics` (projected to the
prompt-declared allow-list `_EDITOR_AGENT_TOPIC_FIELDS`) + the `previous_coverage`
window, both frozen in each day's `run_bus.EditorStage.json` snapshot exactly as
the editor read them. The reconstructed `agent.run(message, context=...)` call is
byte-identical to `EditorStage.__call__` (message string with the day's date;
`{topics, previous_coverage}` context; no addendum), assembled by the production
Agent's own prompt builder.

**Coverage: 22 / 22 window days reconstructed (2026-06-12 … 2026-07-03), 0
excluded, 0 field-leak** — every day has exactly 10 candidate topics, 21
previous-coverage entries, and one incumbent assignment per topic. Floor was 15.
Each day carries a projection self-check (only allow-list fields reach the agent)
and the context wire length; all clean.

## Phase 2 + provider verification — paid shadow

Before spend, each pinned provider was probed once under the real `EDITOR_SCHEMA`
(forced single-provider, `require_parameters:true`) on a representative day; the
probe doubled as the cost sample. **Printed cost projection before the paid
phase: $2.92** (GLM $0.84 + DeepSeek $0.62 + Sonnet-5 $1.47), within the $12 cap.

| Arm | Provider | strict schema | $ | latency |
|---|---|---|---|---|
| GLM | **Baidu** ✓ / Ambient ✓ / Venice ✓ | clean JSON | 0.038 / 0.028 / 0.046 | 104 / 150 / 160 s |
| DeepSeek | **Baidu** ✓ / Parasail ✓ / **WandB ✗** | Baidu+Parasail clean; **WandB empty (n=0)** | 0.028 / 0.070 / 0.068 | **230 / 635 / 830 s** |
| Sonnet-5 | Azure ✓ | clean JSON | 0.067 | 49 s |

Two provider findings: **DeepSeek/WandB returned empty/invalid output under the
editor schema** (830 s, 23 k tokens wasted) — it is the 2nd provider in the pin,
but the primary **Baidu is sound**, so the run was unaffected; and **DeepSeek V4
Pro @ xhigh is markedly slow at every endpoint** (Baidu 230 s, Parasail 635 s).

## Reliability — the headline finding

The editor output is tiny (10 short assignments). Under the strict
`response_format` at `xhigh`, **both OpenRouter reasoning models intermittently
emit `structured=None`** — an empty / unparseable final message that survives the
Agent's built-in corrective-retry parse loop. First-attempt schema-validity, on
the 22 days:

| Arm | first-attempt valid | final valid (after ≤6 retries) | mean latency | provider |
|---|---|---|---|---|
| Incumbent (Opus-4.6, none) | **22 / 22** | 22 / 22 | — (not persisted) | prod |
| Golden (Opus-4.8) | **22 / 22** | 22 / 22 | — (subagent) | — |
| **Sonnet-5** (effort high) | **22 / 22** | 22 / 22 | ~55 s (max 68) | Azure |
| **GLM-5.2** (xhigh) | **12 / 22 (55 %)** | 22 / 22 | ~103 s (max 161) | Baidu |
| **DeepSeek V4 Pro** (xhigh) | **5 / 22 (23 %)** | **17 / 22** | ~179 s (max 223) | Baidu |

The retry sweep needed **62 attempts to recover 22 of 27 invalid cells; 5
DeepSeek days never produced valid output even after 6 attempts** (2026-06-12,
-17, -18, -25, -28). Attempts-to-valid: GLM `{1:12, 2:7, 3:1, 4:1, 5:1}`,
DeepSeek `{1:5, 2:6, 3:4, 4:1, 5:1}` (+5 unrecoverable) — a pure-intermittency
signature, not day-specific difficulty.

**The harness is exonerated:** Sonnet-5 ran through the *identical* Agent path
(strict schema + parse-retry) and was 22/22; a raw single-provider probe returned
clean JSON when GLM succeeded. This is a **GLM/DeepSeek-at-xhigh generation
reliability** problem, not a decode artifact. It matters acutely here because
**the editor runs once per day with no model fallback** — an invalid output is a
broken editorial run that day. (Contrast the writer/QA swaps, which added a 4th-
line model fallback precisely for this failure mode.)

## Phase 3 — deterministic layer

Every **valid** output is structurally clean — for all arms, on all valid days:
schema-valid, a clean bijection to the 10 candidate topics (0 invented, 0
dropped), `selection_reason` present on every entry, all priorities integer in
[0,10], and the prompt rule "no more than two accepts share a priority" upheld.
Canonical topic identity is a greedy exact→slug→token-Jaccard bijection (editors
reword titles, so the canonical index — not the title — is the cross-arm join
key).

| arm | days | schema | bijection | invented | dropped | reasons | pri∈[0,10] | ≤2 share | mean accepts | region~ | lang~ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| incumbent | 22 | 22 | 22 | 0 | 0 | 22 | 22 | 22 | 7.95 | 8.77 | 8.77 |
| glm | 22 | 22 | 22 | 0 | 0 | 22 | 22 | 22 | 7.45 | 8.59 | 8.68 |
| deepseek | 17 | 17 | 17 | 0 | 0 | 17 | 17 | 17 | 6.71 | 8.53 | 8.47 |
| sonnet5 | 22 | 22 | 22 | 0 | 0 | 22 | 22 | 22 | 7.77 | 8.77 | 8.73 |
| golden | 22 | 22 | 22 | 0 | 0 | 22 | 22 | 22 | 7.55 | 8.68 | 8.77 |

So the valid outputs do not separate on structural quality — the differentiators
are **reliability** (above) and **which topics get selected** (below). "Category"
is not a curator-metadata field; region and language spread (both present) are
the diversity axes. DeepSeek accepts the fewest topics (mean 6.71 vs incumbent
7.95) — it is the most selective / rejects most.

### Selection overlap (mean pairwise Jaccard of accepted sets)

|  | incumbent | glm | deepseek | sonnet5 | golden |
|---|---|---|---|---|---|
| **incumbent** | — | 0.885 | 0.847 | **0.934** | **0.923** |
| **glm** | | — | 0.891 | 0.896 | 0.879 |
| **deepseek** | | | — | 0.830 | 0.886 |
| **sonnet5** | | | | — | 0.893 |
| **golden** | | | | | — |

Sonnet-5 and Golden track the incumbent's selections closest (0.934 / 0.923);
**DeepSeek is the selection outlier** (lowest overlaps, 0.83-0.85). No two arms
are identical — editorial selection genuinely diverges.

## Phase 4 — consensus filter

A day is **consensus** iff all present arms choose the identical accepted set.
**Only 2 of 22 days are consensus** (2026-06-23, -29); over the 17 days where all
five arms are valid the 5-arm consensus rate is **2/17 = 11.8 %**. The remaining
**20 days are divergence** and go to the qualitative layers. (5 of those 20 are
DeepSeek-abstention days — the other four arms still diverge; DeepSeek renders as
`∅`.) Low consensus is the expected result: which 1-4 of 10 topics to drop, and
the priority ordering, is exactly the editorial judgment under test.

## Phase 5 — blind Architect digest (the core deliverable)

`scratch/editor-eval/ARCHITECT-DIGEST.md` (**184 lines**, under the 300 cap) is
the blind deliverable. Five arms are anonymized **V/W/X/Y/Z** by a fixed-seed
shuffle; the label→arm map is sealed in `scratch/editor-eval/_label_map.json`,
which the digest never references. Per divergence day it shows the candidate pool
(one-line titles), the consensus accept/reject index lists, and — for the
**contested slots only** — each arm's accept(`＋`)/reject(`−`)/abstain(`∅`) vote
plus the divergent arms' `selection_reason` trimmed to ≤25 words, verbatim. The
answer sheet `ARCHITECT-VERDICTS.md` has one line per divergence day (best
label(s) + optional note).

Blindness verified: no arm-identity token (model name / provider / `golden` /
`incumbent` as a label) appears in the digest; the only matches for a banned-word
scan were **topic content** ("the incumbent vows to fight"; news items about
Anthropic's AI-access order) — not arm labels. No latency/cost/provider appears
in the digest, so nothing leaks the challenger/reference split.

## Phase 6 — subagent panels (supporting signal, weighted BELOW deterministic + Architect)

Three independent blind judges (Sonnet-4.6 — distinct from every arm) each ruled
on all 20 divergence days, applying only the rubric transcribed from the editor
prompts (`RUBRIC.md`), seeing the same anonymized V-Z packets. Per contested
slot: which label(s) made the sounder call; per day: which label's set is best.

All 60 verdicts collected (0 missing). Blind day-win tally (a label wins a day
when it is the majority-or-plurality "best" across the 3 judges; ties share) and
the count of contested slots each label was judged the sounder decider on:

| label | day-wins (of 20) | contested slots judged sounder |
|---|---|---|
| V | **10** | 75 |
| Z | 8 | **85** |
| W | 6 | 71 |
| X | 3 | 56 |
| Y | 2 | 68 |

Inter-judge coherence is high: on **20/20 days ≥2 of the 3 judges named the same
best label**. Two labels (V, Z) clearly lead the panel and two (X, Y) trail — and
X additionally abstained on 5 days (no valid output), which structurally caps its
reach. **Labels map to arms only in phase 7** (after the Architect returns
verdicts); the table is presented blind here and is not read as a decision.

Panels are explicitly a **supporting** signal — the deterministic reliability
result and the Architect's editorial verdicts (pending) outrank them.

## Cost + latency

Total eval spend **$4.66 / $12 cap** (probe $0.34 + shadow pass-1 $2.88 + retry
$1.44). Per successful call: incumbent $0.085, Sonnet-5 $0.075 (~55 s), GLM
$0.035 (~103 s), DeepSeek $0.022 (~179 s). But GLM/DeepSeek's low per-call price
is misleading — their **effective** cost includes the retry multiplier (and, for
DeepSeek, days that never succeed), and their latency is 2-3× Sonnet-5 and far
above the incumbent.

## Decision reading (deferred to the Architect)

The deterministic layer alone is decisive on **operability**: for a once-per-day,
no-fallback stage, **DeepSeek V4 Pro @ xhigh is unusable** (23 % first-attempt
valid; 5/22 days unrecoverable; slowest; most divergent selections) and **GLM-5.2
@ xhigh is fragile** (55 % first-attempt valid). **Sonnet-5** is the only
challenger that is operationally sound (100 % first-attempt, fastest challenger,
cost ≈ incumbent) and its selections track the incumbent and golden most closely.
Whether Sonnet-5's editorial *judgment* is as good as or better than the
incumbent Opus-4.6 on the divergence days is the open question the **blind
Architect digest** exists to answer — that verdict is pending and will decide
the final section. This document is decision **input**, not a cutover.

## Reproduction

All under `scratch/editor-eval/` (untracked raw):
`reconstruct.py` (phase 1) → `provider_probe.py` (probes + projection) →
`shadow.py` (paid pass-1) → `retry_invalid.py --snapshot --retry` (first-attempt
snapshot + recover invalid cells) → `golden_setup.py` + Opus-4.8 subagents
(golden) → `score.py` (deterministic + consensus) → `stats.py` (reliability /
cost roll-up) → `prep_judge.py` (sealed map + digest + verdict sheet + judge
packets) → 3 judge subagents → `aggregate_panels.py` → `unblind.py` (phase 7).
Sealed label map: `_label_map.json`. Digest: `ARCHITECT-DIGEST.md`. Verdict
sheet: `ARCHITECT-VERDICTS.md`.

---

# FINAL — unblinded decision (2026-07-04, phase 7, AUTHORITATIVE)

The Architect returned `ARCHITECT-VERDICTS.md` — best label(s) on the contested
slots for each of the 20 divergence days (ties allowed). Unblinding via the
sealed `_label_map.json` (**V=incumbent, W=Sonnet-5, X=DeepSeek, Y=GLM,
Z=golden**), with the Architect's own blind tally cross-checked exactly against a
programmatic parse (`unblind.py`).

## Unblinded aggregate (all layers side by side)

Ordered by the Architect tally (the editorial arbiter). Weighting per the brief:
**deterministic layer > Architect verdicts > panels.**

| arm | Architect wins /20 | panel wins /20 | panel slot-sounder | **1st-attempt valid /22** | final /22 | Jaccard→incumbent | latency | $/call |
|---|---|---|---|---|---|---|---|---|
| **GLM-5.2** | **13** | 2 | 68 | **12 (55 %)** | 22 | 0.885 | 103 s | 0.035 |
| **Sonnet-5** | **12** | 6 | 71 | **22 (100 %)** | 22 | **0.934** | 55 s | 0.075 |
| Incumbent (Opus-4.6) | 8 | 10 | 75 | 22 | 22 | 1.000 | — | 0.085 |
| Golden (Opus-4.8) | 8 | 8 | 85 | 22 | 22 | 0.923 | — | — |
| DeepSeek V4 Pro | 3 | 3 | 56 | **5 (23 %)** | 17 | 0.847 | 179 s | 0.022 |

## Two arbiters disagree — and the disagreement is part of the result

The **Architect ranks the two challengers first** (GLM 13, Sonnet-5 12), **above**
the incumbent (8) and even the Opus-4.8 golden ceiling (8); the **panels rank the
incumbent and golden first** (10, 8) and put GLM near-last (2). The split is
sharpest on GLM. From the Architect's notes, the challengers win on *instinct +
craft* — GLM's under-reported-systemic catches (a Tatneft refinery strike read as
"the war biting Russia's domestic economy"; Beijing's information-control angle)
and Sonnet-5's delta / dedup / bundling arguments — while the incumbent "accepts
too loosely" and the panels rewarded the more conventional, complete calls. Per
the brief the Architect outweighs the panels, so the editorial signal favours the
challengers — **but that signal is not robust across arbiters**, itself a caution
against reading any single challenger as decisively "better."

## Decision reading (deterministic gate first, then Architect)

1. **DeepSeek V4 Pro — rejected, unanimously.** Fails the deterministic
   reliability gate outright (23 % first-attempt valid; **5/22 days produced no
   valid output even after 6 retries**; slowest ~179 s; most divergent
   selections) and is *last* on both the Architect (3) and panels (3). No path
   forward for the editor stage.

2. **GLM-5.2 — the Architect's top editorial pick, but blocked by the
   deterministic gate.** GLM leads the Architect tally (13), yet the deterministic
   layer — which **outranks** the Architect by the stated weighting — shows only
   **55 % first-attempt schema-validity** on a stage that **runs once per day with
   no model fallback**. Nearly half of days would need a silent retry or fail the
   publish. So GLM is **not swappable as-is** despite the editorial edge; it
   becomes viable only if the editor stage first gains a model fallback (the
   pattern the writer/QA stages adopted) *and* the retry latency/cost is accepted,
   or the xhigh structured-output fragility is resolved. A prerequisite, not a
   cutover.

3. **Sonnet-5 — the recommended candidate.** The **only arm that clears both
   bars**: deterministically sound (**100 % first-attempt valid**, fastest
   challenger ~55 s, cost ≈ incumbent) and the Architect's clear top **among the
   reliability-passing arms** (12 vs incumbent 8, golden 8), with selections
   closest to incumbent and golden (Jaccard 0.934). The low-risk, defensible
   improvement over the incumbent — no new fallback machinery required.

4. **Incumbent Opus-4.6 — reliable, but editorially bettered.** The Architect
   judged it "accepts too loosely" (8, below both challengers). A real editorial
   case to move off it; Sonnet-5 is the clean way. Staying put is the zero-risk
   status quo.

5. **Golden Opus-4.8 — the ceiling is not dominant.** Maximal-care Opus-4.8 tied
   the incumbent at 8 and drew an Architect flag for a vote/reason incoherence
   (2026-07-02). Even the ceiling does not clearly win topic selection —
   underlining that editorial selection is genuinely contested judgment.

## Recommendation

**Swap the editor to Sonnet-5** (`{enabled, effort:high}`, no temperature) — the
single arm that is both operationally sound and the Architect's strongest
*reliable* performer. **Do not swap to GLM-5.2 as-is**: its editorial edge is real
but gated by 55 % first-attempt validity on a no-fallback stage; revisit GLM only
behind a model fallback. **DeepSeek is out.** This remains **decision input** —
the swap itself is a separate task (mirroring `TASK-WRITER-SWAP-GLM`), and any
xhigh model would additionally require adding the editor's first model fallback
before it could be trusted for a once-a-day, no-retry stage.
