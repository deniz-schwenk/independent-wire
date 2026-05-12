# ADR — Coherence stage dependency: accepting a fourth production package

- **Status:** Accepted
- **Date:** 2026-05-12
- **Decision-maker:** Architect, on the back of the empirical footprint survey in TASK-COHERENCE-FILTER-PASSIVE
- **Author of record:** Engineering (CC), prompted by the brief's "surface before installing" gate
- **Affects:** `pyproject.toml` (adds `fastembed==0.8.0`), `src/stages/coherence.py` (new), the runtime install footprint of the project

## Context

The Independent Wire project was launched with the explicit commitment to a minimal production-dependency surface — three production-required packages (`openai`, `httpx`, `feedparser`, `json-repair`, `pydantic`; the last two are stdlib-shaped utilities and were never the controversy). The Vision Paper documents this as a stance about reproducibility, supply-chain risk, and the editorial cost of every transitive package the project pulls in.

TASK-COHERENCE-FILTER-PASSIVE proposed adding a deterministic stage between Curator and Editor that measures finding↔cluster coherence via multilingual sentence embeddings. The brief encoded the dependency-cost stance as a hard ceiling: total install footprint plus cached model weights ≤ 200 MB.

When engineering surveyed `fastembed`'s multilingual-model registry the ceiling did not fit any candidate. The empirical survey:

| Model | Size on disk | Languages | License |
|---|---:|---|---|
| paraphrase-multilingual-MiniLM-L12-v2 | 220 MB declared / 240 MB measured | ~50 (covers all 15 production langs) | Apache-2.0 |
| paraphrase-multilingual-mpnet-base-v2 | 1.0 GB | ~50 | Apache-2.0 |
| onnx-community/embeddinggemma-300m | 1.24 GB | multilingual | Apache-2.0 |
| multilingual-e5-large | 2.24 GB | ~100 | MIT |
| jina-embeddings-v3 | 2.29 GB | ~100 | CC-BY-NC-4.0 (incompatible) |

The smallest multilingual model on its own exceeded the ceiling by 10 %. Adding the runtime (`onnxruntime` 71 MB, `fastembed` and its other dependencies ~40 MB beyond what the project already pulls in) brought the total to **~351 MB measured** — 75 % over the original 200 MB ceiling.

Engineering surfaced this to the architect per the brief's "surface before installing" gate. The architect's decision: raise the ceiling to 400 MB and ship the stage. This ADR is the durable record of that decision.

## Decision

1. **Add `fastembed==0.8.0`** as a production dependency in `pyproject.toml`. Version pinned exactly; not a `>=` constraint. The pin is load-bearing: `fastembed >= 0.6` silently switched the chosen model from CLS-token to mean-pooled output, which would shift every historic coherence score on upgrade. A floating constraint would make calibration non-reproducible across environments.

2. **Use `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`** as the embedding model. Pinned as a string constant in `src/stages/coherence.py::MODEL_NAME` and documented in the Bus-slot docstring on `curator_coherence_scores`. The model name is referenced in any future runtime check that needs to validate the production environment matches the calibration environment.

3. **Raise the install-footprint ceiling from 200 MB to 400 MB.** The measured footprint at ~351 MB is the smallest path consistent with honest multilingual coverage of the production language set.

## Why a ~350 MB floor is unavoidable for honest multilingual coverage

The production language set is fifteen languages: EN, DE, ES, FR, IT, PT, TR, KO, FA, RU, ZH, AR, HE, ID, VI. Five of these (KO, FA, AR, HE, ZH) use non-Latin scripts. A coherence signal that cannot rank content in these languages would be invisible exactly where most of our editorial uncertainty lives — cross-language disagreement is one of the things the pipeline exists to surface.

Multilingual sentence-embedding models are dominated by XLM-RoBERTa-family backbones. The cheapest path that still covers the full set in one bundle is the 12-layer 384-dim MiniLM trained on 50-language paraphrase pairs (the 220 MB option). Smaller "distilled multilingual" candidates with reasonable coverage do not exist in the `fastembed` registry; what does exist (English-only models at 13–67 MB; bilingual EN/DE or EN/ZH at 320–640 MB) does not cover the production set. Outside `fastembed`, smaller candidates exist but they require introducing a different inference runtime (sentence-transformers + PyTorch — substantially larger overall — or HuggingFace Transformers, same).

The ONNX runtime itself is 71 MB and accounts for ~20 % of the total. Any path that uses pre-quantized ONNX-format multilingual embeddings will carry that overhead. Removing it would mean either switching to pure-numpy embedding (none exists for the language set) or to a model server (more dependencies, more deployment complexity).

The ~350 MB floor is therefore not a sloppy implementation. It is what honest multilingual coverage on commodity infrastructure currently costs.

## Alternatives considered and rejected

### Stay at three dependencies; do not add coherence at all

Cheapest. Sacrifices the entire coherence-measurement programme. The argument for paying the dependency cost is empirical: the V1-2026-05-11 baseline showed Curator producing a 1004-finding cluster with ~80 % off-topic content. Temperature alone (the swap shipped in `c9a39bd`) cuts the off-topic share to ~53 % but does not address the long-tail noise inside individual clusters. Coherence measurement is the next observability step. Postponing it means staying blind to the question.

Rejected: the editorial cost of staying blind is larger than the supply-chain cost of one well-maintained Apache-2.0 dependency.

### Smaller English-only embedding model (e.g. `BAAI/bge-small-en-v1.5`, 67 MB)

Cheap, would fit the original 200 MB ceiling.

Rejected: would silently down-rank every finding in non-Latin scripts. The model has no representation for Korean, Persian, or Arabic text — these would score uniformly near zero, suggesting *all* such findings are off-topic regardless of content. The brief explicitly forbids this trade-off: "Multilingual coverage including English, German, [...] Arabic, Hebrew, Indonesian, Vietnamese (the active production language set)" is in the dependency requirements section, not the nice-to-haves.

### Multilingual TF-IDF / token-overlap (no model dependency)

Cheap. Zero install footprint beyond stdlib + `numpy` (already a transitive dep).

Rejected for two reasons. First, the brief explicitly forbids it: "Multilingual TF-IDF as a fallback is explicitly out of scope." Second, the architectural reason behind that forbid: TF-IDF measures surface lexical overlap, not semantic similarity. The whole point of an embedding-based signal is to catch findings that are about the same event but phrased differently — exactly the case where TF-IDF fails. The dynamic-regex check from `src/curator_metrics.py` is already the lexical-overlap baseline, and the calibration report uses it as the regex ROC. Replacing the embedding stage with another lexical-overlap signal would produce a measurement we already have.

### Larger multilingual model with better coverage (e.g. `multilingual-e5-large`, 2.24 GB)

Higher ceiling (10×). Better cross-lingual semantics on long-tail languages.

Rejected: the marginal coverage gain (~100 vs ~50 languages) does not buy production-relevant capability — all 15 production languages are in the 50-language set of the smaller model. The wall-clock and memory cost of the larger model would push the stage well past any reasonable single-run budget, and the dependency-cost argument that made 351 MB controversial would be much harder at 2.4 GB. Reserved for future consideration if calibration ROC shows the small-model embedding fails on a specific language family — in which case a targeted swap is preferable to a permanent upgrade.

### Hosted embedding API (OpenAI, Cohere, etc.)

Avoids the on-disk footprint entirely.

Rejected on principle. The project's editorial commitment is to deterministic, on-premise, hermetic operation. A hosted embedding API would: (1) introduce a third party in the cost of measuring our own data, (2) tie coherence reproducibility to a vendor's model versioning, (3) leak the full Curator dataset to that vendor every run. None of these are acceptable trade-offs for what is fundamentally an observability signal we should produce ourselves.

## Consequences accepted

**Positive:**

- The pipeline gains a deterministic, on-premise, multilingual coherence signal that can be measured every run without per-token spend or external dependencies.
- The signal feeds the calibration report; if the three-day production data + V1 ROC justify it, the same dependency carries an active-filter stage with no additional cost.
- Reproducibility is preserved by pinning both the library and the model name.

**Negative — accepted:**

- Install footprint grows from ~150 MB to ~500 MB. CI cache, Docker image size, and developer-laptop disk all pay this once.
- `onnxruntime` is now a transitive dependency. Its supply chain is mature and Apache-2.0, but it is an addition to the trust surface.
- A `fastembed` upgrade can silently shift every coherence score. The pin in `pyproject.toml` is the durable mitigation; the warning-on-mismatch check at stage init is the runtime guard.
- The stage currently exceeds the brief's 20-second wall-clock budget on MacBook hardware (measured 30 s at batch_size=32). The architect's rollback path for this case (per the dispatch message that approved this work) is to keep the stage in place and retest after the Mac Mini hardware migration — a hardware-bound breach is not a code problem.

## Notes for Vision Paper

This ADR commits a specific change to the project's dependency surface. The Vision Paper currently lists three production dependencies as a value statement. The four-dependency reality should be reflected there separately. The substance of the statement — "every dependency is a deliberate choice paid for with editorial value" — is preserved; the count is wrong.

Suggested edit (Vision Paper, dependency section): "four production dependencies: openai, httpx, feedparser, json-repair, pydantic (utility), fastembed. The fourth was added in 2026-05 to enable multilingual coherence measurement on the Curator output; see `docs/ADR-COHERENCE-STAGE-DEPENDENCY.md`."

## Related

- `TASK-COHERENCE-FILTER-PASSIVE.md` — the brief that triggered this decision
- `docs/coherence-filter/_calibration-v1-baseline.md` — first calibration ROC against V1-2026-05-11 data
- `src/stages/coherence.py` — the stage itself
- `src/bus.py::curator_coherence_scores` — the new Bus slot
