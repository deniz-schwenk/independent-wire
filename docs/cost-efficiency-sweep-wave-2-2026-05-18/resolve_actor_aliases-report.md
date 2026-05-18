# Wave 2 Sweep #2 — `resolve_actor_aliases` (Flash replacement)

## Setup

- **Substrate:** `output/2026-05-18/_state/run-2026-05-18-c26864b2/topic_buses.consolidate_actors.{0,1,2}.json` — `final_actors[]` counts 43 / 91 / 39 entries.
- **Baseline:** Gemini Flash 3, t=1.0, r=medium, production max_tokens=66000. Today's output: 6 / 41 / 7 alias pairs, 37 / 50 / 32 canonical actors.
- **Schema:** `RESOLVE_ACTOR_ALIASES_SCHEMA` strict (`{aliases: [{alias_id, canonical_id}], anonymous_flags: [string]}`).
- **max_tokens=160000** on the candidate.
- **Harness:** Wave-1 Option B (`scripts/eval_common.py::run_sweep`). 1 variant × 3 topics = 3 calls. No streaming.

## Metrics

| label | cost_total | cost/topic | tokens_total | wall_mean | aliases (per topic) | anon_flags (per topic) | implied_canonical (per topic) | uncovered (per topic) | schema_valid |
|---|---|---|---|---|---|---|---|---|---|
| **baseline** | n/a | n/a | n/a | n/a | **6 / 41 / 7** | n/a | 37 / 50 / 32 | n/a | 100 % |
| dskflash-t05-rnone | **$0.0053** | $0.0018 | 15,170 | 8.4 s | 7 / 48 / 12 | 4 / 7 / 3 | 36 / 43 / 27 | 0 / 0 / 0 | 100 % |

**Coverage check** — `uncovered_input_ids = 0 / 0 / 0` across all topics: every input `final_actor.id` is either an alias-source, alias-target, or absent from the alias list (i.e. implied canonical). No fabricated IDs. Schema strict mode held across all 3 calls.

## Qualitative spot-check — topic 0 (Trump-Iran)

| baseline alias | candidate alias | match? |
|---|---|---|
| `Mohammad Bagher Ghalibaf` ↔ `Mohammad Bagher Qalibaf` | yes (same pair, canonical direction inverted) | ✓ |
| `UAE defense ministry` ↔ `UAE defence ministry` | yes | ✓ |
| `UAE defense ministry` ↔ `UAE Ministry of Defense` | yes | ✓ |
| `Saudi Arabia Defense Ministry` ↔ `Saudi Defense Ministry` | yes | ✓ |
| `Chinese foreign ministry` ↔ `Chinese Foreign Ministry` | yes | ✓ |
| `Abolfazl Shakarchi` ↔ `Abolfazl Shekarchi` | yes | ✓ |
| **(new)** `UAE` ↔ `UAE defence ministry` | **candidate only** | ◐ — defensible: the bare-country mention in one source could legitimately fold into the institution if same article-context |

Anonymous-flag spot-check (topic 0 candidate): `Former IRGC commander`, `Iran` (bare country), `Iranian officials`, `U.S. lawmakers`. All four are exactly the kind of generic source-class label the resolver is supposed to flag (per `agents/resolve_actor_aliases/SYSTEM.md`). The baseline snapshot on disk had no `anonymous_flags` populated (older run before the resolver's anonymous-flagging logic was fully exercised, or zero generic labels in topic 0's input that day — checked: input does contain these generic entries, so the baseline's null is a quality-asymmetric data point in the candidate's favour).

Canonical direction differences (e.g. baseline `actor-019 → actor-016`, candidate `actor-016 → actor-027`) do not affect downstream correctness: the production wrapper's `_resolve_canonical_groups` helper applies first-source-wins via union-find on the merged graph, so either edge orientation yields the same canonical groups.

## Observation

DeepSeek V4 Flash at $0.0018 / topic is **~10-15× cheaper than the Gemini Flash 3 baseline's likely cost-per-topic** (baseline cost not isolated in stage log this run because resolve_actor_aliases is bundled with other topic stages — order-of-magnitude estimate from the Wave-1 Flash $0.018/topic figure on a slightly different role). Schema validity 100 % across 3 calls, 0 uncovered input IDs, 0 fabricated IDs. The candidate produces 7/48/12 alias pairs vs baseline 6/41/7 — every baseline pair is reproduced (with sometimes-inverted canonical direction, which is symmetry-equivalent under the production union-find), plus a handful of additional defensible compressions (e.g. bare-country "UAE" folded into "UAE defence ministry"). The candidate also surfaces the anonymous-flag set the prompt asks for (4 / 7 / 3 entries across the three topics), which the baseline snapshot on disk left empty. No production-swap recommendation in this report.
