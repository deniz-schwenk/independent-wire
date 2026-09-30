# TASK-EXTRACTOR-FALLBACK-DETECTION-FIX — false fallback markers after the channel pin

## 1. Repro, before the fix

Production rows, both days since the pin (`output/2026-09-2{0,1}/_state/run-*/run_stage_log.jsonl`):

```
bias t0/t1/t2 (09-20 and 09-21, six rows):
  extractor_fallback_passes [1, 2, 3]      extractor_fallback_used true
  bias_candidate_extractor_model_used     ["deepseek/deepseek-v4.1-flash"] x3
  bias_candidate_extractor_provider_used  ["DeepSeek"] x3
```

Every pass served by the PRIMARY, no failed call anywhere — and every pass
marked as a fallback. 18 false markers in two days.

`repro.py` replays the 09-20 t0 row deterministically and for free (the defect
is in detection, not in the call), with the BEFORE arm imported verbatim from
`git show HEAD:src/bias_composite.py`:

```
BEFORE (HEAD, pre-fix): extractor_fallback_passes=[1, 2, 3] used=True | primary calls=3 rung calls=0
AFTER  (this branch)  : extractor_fallback_passes=[]        used=False | primary calls=3 rung calls=0
```

`rung calls=0` in both arms is the proof that BEFORE was lying: the fallback
agent was never invoked.

The old warning line reproduces too, self-contradiction included:

> bias extractor FALLBACK: pass(es) [1, 2, 3] were served by the channel-A
> route, not openrouter.

## 2. Root cause — confirmed, and narrower than "channel names changed"

`BiasComposite._channel_report` decided the rung with:

```python
primary_channel = self._primary_channel()      # primary.provider  -> CONFIGURED key
r.provider != primary_channel                  # result.provider   -> SERVED label
```

Those are two different kinds of string. `result.provider` is what the route
reports served the call — for OpenRouter, the upstream vendor (`DeepSeek`); the
configured value is the channel we asked *through* (`openrouter`). They were
equal only while the primary was `deepseek_direct`, a channel that echoes its
own key, so the comparison silently encoded "primary == channel C". When
TASK-FLASH-CHANNEL-PIN moved the primary to OpenRouter the test inverted:
`"DeepSeek" != "openrouter"` is true for every healthy pass, forever.

So the pin did not break a correct check; it exposed a check that had never
been more than a coincidence.

## 3. Fix

**The rung is now reported by the wrapper that made the call, not reconstructed
from the response.**

- `FlashStageWithFallback.run_reporting()` → `(result, fallback_used)`, with
  `escalate_to_fallback_reporting()` beside it. `run()` and
  `escalate_to_fallback()` delegate, so every existing caller is unchanged.
- `BiasComposite._run_leg(agent, ...)` calls `run_reporting` when the leg has
  it and falls back to `run()` otherwise — a bare `Agent` has no second rung, so
  `False` there is the only possible answer, not a guess.
- `_channel_report(results, rungs)` keeps served labels and rung facts apart:
  labels describe the vendor's routing, rungs describe the ladder's.
- `_fallback_indices(rungs)` replaces `_judge_fallback_votes(models)`.
- Deleted: `_primary_channel()`. Kept, explicitly marked display-only:
  `_judge_primary_model()`, used in one warning string.

This also removes the concurrency workaround the old inference existed to solve.
The composite issues 3–4 extraction passes and 2 judge votes concurrently
against ONE wrapper, so `last_fallback_used` is last-writer-wins and cannot say
which call fell back. A per-call return value can.

### Warning text

```
bias extractor FALLBACK: pass(es) [2] of 3 fell through to the rung-2 agent
deepseek-v4-flash after the primary deepseek/deepseek-v4.1-flash failed;
served by ['deepseek-flash'].
```

## 4. Sibling audit

- **Judge legs** — same class of assumption (`_judge_fallback_votes` compared
  served MODEL ids and relied on "both legs share one provider"). It was not
  producing false positives in production, because the two judge rungs really
  are different models, but it was inference of the same kind and is now on the
  reported rung. Fixed uniformly, as asked.
- **`editor_fallback`, `qa_fallback`, `writer_fallback`, `perspective_fallback`,
  `hydration_phase2_fallback`, `PerspectiveDraftVerifyChain`** — all set
  `last_fallback_used` from their own control flow and are called once per
  stage, never concurrently against one instance. No topology inference, no
  change needed.
- `src/agent.py:961` compares `self.provider` for provider LABELLING, not
  fallback detection. Out of scope and correct.

## 5. Tests

`tests/test_extractor_fallback_detection.py` (new, 6) runs the composite in the
CURRENT production topology — extractor nested inside `BiasComposite`, both legs
real `FlashStageWithFallback` wrappers, primary on OpenRouter first-party
reporting `provider="DeepSeek"`, rung on channel C:

1. healthy run → `[]` / `false`, no FALLBACK line, served ids still reported;
2. compound `model_used` marker unchanged;
3. pass 2's primary fails → `[2]` only, rung's served id at position 2, warning
   names both agents and no longer says "channel-A route";
4. all passes fail over → `[1, 2, 3]` (the honest version of the false row);
5. judge vote 1 falls back, vote 2 does not → `[1]`, extractor unaffected;
6. **the invariant**: give the primary a provider label from another planet —
   detection is unchanged, and the odd id is still reported verbatim, which is
   how a genuine provider-side substitution stays visible.

`tests/test_dsv4_swaps_bundle.py::test_composite_reports_the_fallback_even_though_passes_race`
was rewritten: it used to fake the rung with provider STRINGS, which is the
mechanism being removed. It now uses a real wrapper whose primary fails on pass
2 — still deliberately not the last pass to finish.

Suite: **1263 passed, 4 failed** — the standing baseline four.

## 6. Two observations outside the fix

- **The 09-20 run was not clean.** `ResolveActorAliasesStage` t1 is
  `status: degraded` — "no aliases resolved across 29 actors after 4 attempts
  across every rung, despite merge-candidate signals [...]" — so 98 success + 1
  degraded, plus a real resolve rung serve on t1 and a real qa fallback on t2
  (Sonnet-5, $0.274). The brief describes 09-20 as "99-stage success"; it wasn't.
  Today's 2026-09-21 run is: 99/99 success, 0 degraded, no fallback outside the
  false bias markers. The gate holds on today's run, not on 09-20's.
- **The pin's ledger claim checks out.** Both days: zero rows carrying a
  `model_used` at $0.00, 15/15 and 16/16 flash rows priced, totals $1.1605 and
  $1.2414 — just under the $1.40–1.55 I projected, so the warm-cache caveat in
  that estimate was the conservative direction.
- Minor, noted not fixed: `load_lexicon` resolves `config/bias_lexicon.json`
  relative to the CWD, so any harness run from another directory loses the
  lexicon with only a warning. Production runs from the repo root, so this is
  latent, not live.
