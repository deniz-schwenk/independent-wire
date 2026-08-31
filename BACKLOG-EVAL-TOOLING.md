# BACKLOG — Eval tooling: transliteration-aware actor gate + curator rubric

From GLM53-SCREEN (2026-08-31). Both are independent of GLM; the GLM
question itself is closed (owner, 2026-08-31): GLM-5.3-flash ties the
retired April-pro incumbent, sits below the new flash-0731 champion on both
judged stages, and reproduced the family's fabrication signals (invented
actor on phase1, fabricated gap on consolidator, 1.7× incumbent fabrication
rate on assemble). Standing GLM-5 synthesis-role disqualification stands
for 5.3.

## 1. Transliteration-aware actor fabrication gate (deterministic)
Naive substring matching of emitted actor names against inputs flags the
INCUMBENT on 19.6% of names — the corpus is multilingual, models emit
Latin-script names for Cyrillic/CJK/Arabic sources (Putin vs Путин),
outlets appear as names vs domains. Needed: a Python-side matcher with
script-aware normalization/transliteration (unidecode-class, plus
outlet-registry name↔domain lookup) so "actor exists in inputs" becomes a
usable hard gate for any synthesis-stage eval AND a candidate production
QA check. Deterministic-before-LLM; no judge in the loop.

## 2. Curator rubric
curator_topic_discovery has never been judged — only structurally gated
(T2, GLM screen). Topic selection quality is the pipeline's first editorial
decision. Needed before any future curator model eval: an anchor-free
rubric (relevance, diversity, coverage-gap awareness, transparency of
selection_reason) reviewed at the Architect gate like the T3b rubrics.

## 3. Note carried from the bundle shadow run
resolve_actor_aliases fell back C→A on 2/3 topics in the hydrated shadow
— first live firing of that path. Check production logs from 2026-09-01
on; if the rate holds, the 16k cap / channel-C sizing needs its own slot.
