# Wave 2 Sweep #3 — `editor` (Opus replacement, V4 Pro grid)

## Setup

- **Substrate:** `output/2026-05-18/_state/run-2026-05-18-c26864b2/run_bus.assemble_curator_topics.json` — `curator_topics[]` carries 10 candidates with full per-topic enrichment (sources, geography, languages, missing-perspectives, etc.); `previous_coverage[]` carries 3 prior topics.
- **Baseline:** Opus 4.6, t=0.3, r=none, max_tokens default. Today's output: **10 assignments** in this priority order: (1) Trump Iran ultimatum, (2) Ukraine drones, (3) UAE Barakah, (4) WHO Ebola, (5) Israel-Lebanon, plus 5 lower-priority.
- **Schema:** `EDITOR_SCHEMA` strict (`{assignments: [{title, priority, selection_reason, follow_up_to, follow_up_reason}]}`).
- **max_tokens=160000** on every candidate.
- **Harness:** Wave-1 Option B (`scripts/eval_common.py`). 6 variants × 1 call, streaming for r∈{medium, high}.

## Metrics

| label | model | temp | reasoning | streaming | cost | tokens | wall | n_topics | top3 overlap | any overlap | log_len | valid | provider |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **baseline** | claude-opus-4.6 | 0.3 | none | no | n/a | n/a | n/a | 10 | n/a | n/a | n/a | 100 % | Anthropic |
| dskpro-t05-rnone | dsk-v4-pro | 0.5 | none | no | $0.0228 | 12,438 | 26.5 s | 10 | 1/3 | **9/10** | 3,066 | 100 % | AtlasCloud |
| dskpro-t05-rmedium | dsk-v4-pro | 0.5 | medium | yes | $0.0171 | 15,843 | 82.9 s | 10 | 1/3 | **9/10** | 2,904 | 100 % | AtlasCloud |
| dskpro-t05-rhigh | dsk-v4-pro | 0.5 | high | yes | $0.0161 | 15,538 | 60.4 s | 10 | 1/3 | **9/10** | 3,592 | 100 % | AtlasCloud |
| dskpro-t07-rnone | dsk-v4-pro | 0.7 | none | no | **$0.0059** | 12,571 | 28.6 s | 10 | 1/3 | **9/10** | 3,912 | 100 % | AtlasCloud |
| dskpro-t07-rmedium | dsk-v4-pro | 0.7 | medium | yes | $0.0193 | 16,498 | 80.3 s | 10 | **2/3** | **9/10** | 3,052 | 100 % | AtlasCloud |
| dskpro-t07-rhigh | dsk-v4-pro | 0.7 | high | yes | $0.0132 | 14,698 | 68.7 s | 10 | **2/3** | **9/10** | 3,468 | 100 % | AtlasCloud |

**Sweep total cost: $0.0944** (well under $15 per-sweep cap). Cumulative wave-2 spend so far: $0.105.

## Top-3 selection comparison

Baseline picks (in priority order): **(1) Trump Iran**, **(2) Ukraine drones**, **(3) UAE Barakah**.

Every candidate variant agrees on (1) Ukraine drones and (2) Trump Iran — same two topics but reversed priority order vs baseline. The variation is at (3):

| variant | (1) | (2) | (3) | (4) | (5) |
|---|---|---|---|---|---|
| baseline | Trump-Iran | Ukraine drones | UAE Barakah | WHO Ebola | Israel-Lebanon |
| dskpro-t05-rnone | Ukraine drones | Trump-Iran | WHO Ebola | Israel-Lebanon | UAE Barakah |
| dskpro-t05-rmedium | Ukraine drones | Trump-Iran | Israel-Lebanon | WHO Ebola | UAE Barakah |
| dskpro-t05-rhigh | Ukraine drones | Trump-Iran | WHO Ebola | Israel-Lebanon | UAE Barakah |
| dskpro-t07-rnone | Ukraine drones | Trump-Iran | Israel-Lebanon | UAE Barakah | WHO Ebola |
| **dskpro-t07-rmedium** | Ukraine drones | Trump-Iran | **UAE Barakah** | Israel-Lebanon | WHO Ebola |
| **dskpro-t07-rhigh** | Ukraine drones | Trump-Iran | **UAE Barakah** | Israel-Lebanon | WHO Ebola |

All five "top-3-relevant" baseline themes (Trump, Ukraine, UAE, WHO, Israel) appear within the top-5 of every variant; what varies is **the slot order**. The same 9 baseline titles also appear in the candidate's full 10 (only the 10th rank slot varies — one of Modena attack / Eurovision / G7 Paris / Andalusia / Kim border falls in or out depending on the candidate). The diversification rules from the editor prompt (mix categories, attend to follow-up-to chains, balance geography) appear to be applied: every variant rotates between hard-news (military escalation) and broader (international health/diplomacy/elections) categories rather than stacking the top-5 with one category.

## Observation

Six DeepSeek V4 Pro variants of the Editor stage all returned **100 % schema-valid** output, **10 topics selected** matching the baseline count, and **9/10 same-topic overlap** with the baseline assignment list. Top-3 overlap is 1/3 on the t=0.5 variants and 2/3 on the t=0.7 reasoning variants — the underlying disagreement is purely **priority order** within the top-5: every candidate flips baseline's `(1) Trump, (2) Ukraine` to `(1) Ukraine, (2) Trump`, and four of the six promote `WHO Ebola` or `Israel-Lebanon` ahead of `UAE Barakah` (which the baseline placed at #3). Cost range $0.006-$0.023 vs an estimated Opus 4.6 baseline cost of ~$0.10-0.30 for this run-phase stage (Opus pricing $5/$25 M tokens; ~16k tokens here yields ~$0.13-0.40) — i.e. roughly **10-25× cheaper** per editorial decision. The cheapest variant `dskpro-t07-rnone` at $0.0059 still produced a defensible 10-topic list with 9/10 baseline overlap; `dskpro-t07-rhigh` at $0.0132 produces the best baseline-priority match at 2/3 top-3 overlap. Zero streaming failures across the four reasoning variants on this small-payload run-phase substrate. No production-swap recommendation in this report.
