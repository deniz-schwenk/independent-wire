# ADR — Coherence dependency ceiling: addendum for scikit-learn promotion

- **Status:** Accepted
- **Date:** 2026-05-15
- **Decision-maker:** Architect
- **Author of record:** Engineering (CC), on the back of the footprint gate in `TASK-EMBED-PRE-CLUSTER-STAGE.md` watch-item 1
- **Affects:** `pyproject.toml` (promotes `scikit-learn>=1.3` to a production dependency), the runtime install footprint, the install-footprint ceiling
- **Amends:** `docs/ADR-COHERENCE-STAGE-DEPENDENCY.md` (raises the 400 MB ceiling to 600 MB)

## Context

The original ADR (`docs/ADR-COHERENCE-STAGE-DEPENDENCY.md`, 2026-05-12) raised the project's install-footprint ceiling from 200 MB to 400 MB to accommodate `fastembed==0.8.0` plus the cached weights of `paraphrase-multilingual-MiniLM-L12-v2`. The measured footprint at the time was ~351 MB ("total install footprint plus cached model weights ≤ 400 MB").

`TASK-EMBED-PRE-CLUSTER-STAGE.md` introduces a new deterministic run-stage that embeds all `curator_findings` and groups them into ~250 micro-clusters via Agglomerative clustering. The eval that calibrated the clustering parameters (`docs/CLUSTERING-EVAL-2026-05-14.md`) used `sklearn.cluster.AgglomerativeClustering(distance_threshold=0.7, linkage='average', metric='cosine')`. The brief's watch-item 1 gates promoting `scikit-learn` to a production dependency on measuring the post-install footprint and surfacing the result to the architect.

Two findings emerged from the gate measurement:

1. **The 400 MB ceiling has drifted by ~50 MB at HEAD without any architectural decision.** Re-measured 2026-05-15 in a clean Python 3.12.9 venv installing only the current `pyproject.toml [project] dependencies` (no eval extras), the production install footprint is ~210 MB on disk for `site-packages` and ~450 MB with the cached MiniLM model. The ADR's "~351 MB measured" baseline three days ago is now ~450 MB on the same dependency set. The drift is attributable to pip's resolver pulling more transitives over time — `pillow` (14 MB), `pip` itself (12 MB), `pygments` (9 MB), `hf_xet` (7 MB) all show up in the install today and account for most of the ~100 MB gap. The drift is not the result of any architectural decision we made; it is the cost of running on a pip ecosystem that evolves.

2. **Promoting `scikit-learn` adds ~146 MB.** The transitive set is `scikit-learn` 46 MB, `scipy` 97 MB, `joblib` 2.4 MB, `threadpoolctl` 0.1 MB. The clean-install simulation puts the post-promotion footprint at ~356 MB site-packages and ~596 MB with the cached model.

The two facts compound: HEAD already exceeds the 400 MB ceiling, and the promotion pushes the install to ~600 MB.

## Decision

1. **Promote `scikit-learn>=1.3` to a production dependency** in `pyproject.toml`. Floor-pinned (not exact-pinned) — the cosine-metric path used by `AgglomerativeClustering` is stable across recent releases, and a floor pin lets routine point releases through without an upper bound that would force CI failures on every minor sklearn upgrade. Comment lines on the dependency mirror the `fastembed==0.8.0` style.

2. **Raise the install-footprint ceiling from 400 MB to 600 MB.** Measured post-promotion total of ~596 MB is the new floor consistent with running both the coherence stage and the embed-pre-cluster stage on the production language set.

3. **Acknowledge the pre-promotion drift explicitly.** HEAD on 2026-05-15 measures ~450 MB on the original (no-sklearn) dependency set — already ~50 MB over the prior 400 MB ceiling. The drift is a consequence of pip-ecosystem evolution unrelated to any decision documented in an ADR. We do not roll it back; we record it.

## Why a ~600 MB total is the smallest path consistent with the eval

### Why sklearn (not scipy-only)

`docs/CLUSTERING-EVAL-2026-05-14.md` calibrated the production parameters (`distance_threshold=0.7`, `linkage='average'`, `metric='cosine'`) using `sklearn.cluster.AgglomerativeClustering`. The 504-finding ground-truth set's F1 score and the cross-dataset stability of the `agg-permissive` configuration are both anchored to sklearn's specific implementation of average-linkage agglomerative clustering on cosine distance. Using the same library in production guarantees bit-identical reproduction of the eval — no porting-correctness question to resolve before integration.

`scipy.cluster.hierarchy.linkage(method='average', metric='cosine')` + `fcluster(t=0.7, criterion='distance')` implements the same algorithm and would save ~49 MB (scipy 97 MB only vs sklearn + scipy + joblib + threadpoolctl, +145.5 MB). The numerical output should be mathematically equivalent — both compute average-link agglomerative clustering on the same condensed cosine-distance matrix. The reasons sklearn wins anyway:

- The eval is anchored on sklearn; reproducibility is by construction. The scipy port would require a side-by-side bit-equality test we do not need to run.
- The smoke harness ran today produces Δ=+0.0 % on cluster count and identical max-cluster sizes across all three eval datasets (2026-05-08: 246/100, 2026-05-11: 241/66, 2026-05-13: 279/77). Substituting scipy at this point would be voluntary churn against a known-good reproduction.
- Brief 2 (Gravitational Assignment) and Brief 4 (Curator rebuild) in the same triple-stage sequence may reach for additional sklearn primitives — `sklearn.metrics.pairwise.cosine_similarity` for the topic-centre similarity computation, possibly `sklearn.cluster.KMeans` for centroid-based representative selection. Deferring the sklearn promotion would fragment the dependency decision across the sequence.

The 49 MB saving is real, but it is small relative to the 596 MB total and does not change the structural situation that the ceiling needs to rise.

### Why scipy was unavoidable regardless

`scipy` is not currently a transitive dependency of `fastembed` (its declared deps are `huggingface-hub, loguru, mmh3, numpy, onnxruntime, pillow, py-rust-stemmers, requests, tokenizers, tqdm` — no scipy). Either path forward — sklearn or scipy-only — pulls scipy from scratch. The 97 MB scipy cost is shared by both options.

### Why we accept the drift

The ~50 MB pre-promotion drift over the original 400 MB ceiling is not a regression we caused. It is the cost of running on a pip ecosystem that evolves. Documenting it here means the next "surface before installing" measurement starts from an honest baseline.

## Measured numbers (Python 3.12.9, clean venv, 2026-05-15)

| State | site-packages | + MiniLM cache | vs 400 MB | vs 600 MB |
|---|---:|---:|---:|---:|
| HEAD (production deps only) | 210 MB | ~450 MB | +50 MB over | comfortable |
| + sklearn promotion (this addendum) | 356 MB | ~596 MB | n/a (ceiling raised) | barely under |
| + scipy-only (rejected) | 308 MB | ~548 MB | n/a | comfortable |

Headroom under the new 600 MB ceiling is **modest** — ~4 MB. Any future production-dependency addition must apply the same "surface before installing" gate the original ADR introduced, and is likely to require another ceiling reassessment.

## The principle the ceiling enforces stands

The original ADR's framing was that every dependency is a deliberate cost paid for with editorial value, and the ceiling exists to make growth visible rather than to prevent it. This addendum is the ceiling doing its job — the embed-pre-cluster stage's value (replacing the V4-Pro single-pass Curator's structural over-clustering pathology with a deterministic micro-cluster decomposition) was evidenced in the eval and the smoke, and the dependency cost is being paid against that evidence rather than waved through.

The substance of "every dependency is a deliberate choice paid for with editorial value" is preserved. The cost line goes up; the principle does not.

## Notes for Vision Paper

The previous edit suggested the Vision Paper update to "four production dependencies: openai, httpx, feedparser, json-repair, pydantic (utility), fastembed". With this addendum, the line becomes:

> "five production dependencies: openai, httpx, feedparser, json-repair, pydantic (utility), fastembed, scikit-learn. The fifth was added in 2026-05 to enable deterministic micro-cluster formation for the triple-stage Curator architecture; see `docs/ADR-COHERENCE-STAGE-DEPENDENCY-ADDENDUM-2026-05-15.md` and `docs/ADR-CURATOR-TRIPLE-STAGE.md`."

## Related

- `docs/ADR-COHERENCE-STAGE-DEPENDENCY.md` — the original 400 MB ceiling and the rationale this addendum amends
- `docs/ADR-CURATOR-TRIPLE-STAGE.md` — the architectural rationale this stage implements
- `docs/CLUSTERING-EVAL-2026-05-14.md` — the parameter calibration the production stage reproduces
- `TASK-EMBED-PRE-CLUSTER-STAGE.md` — the brief whose watch-item 1 triggered this addendum
- `src/stages/pre_cluster.py` — the stage itself
- `src/bus.py::curator_pre_clusters` — the new RunBus slot
- `docs/pre-cluster/smoke-2026-05-15/` — bit-identical reproduction of the eval's `agg-permissive` numbers via the production stage
