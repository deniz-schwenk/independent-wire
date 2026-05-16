# Phase 2 qualitative samples

Per brief Phase 2 — three topics from 2026-05-11 rendered across the three top configurations from Phase 1. Same topics across all configurations so the architect compares like-with-like.

## Configurations

- `T=0.55-V1/`
- `T=0.55-V2/`
- `T=0.50-V2/`

## Topics (same in every configuration)

- **gravity-trap-putin-schroeder** — 2026-05-11 · topic-02 — Vladimir Putin proposes Gerhard Schröder as mediator for Ukraine negotiations (baseline: 134 findings, 122 off-topic, **91.0% off**)
- **borderline-trump-iran-peace** — 2026-05-11 · topic-01 — Donald Trump rejects Iran's response to US peace proposal as unacceptable (baseline: 144 findings, 73 off-topic, **50.7% off**)
- **clean-hantavirus** — 2026-05-11 · topic-04 — Hantavirus outbreak on MV Hondius cruise ship triggers international health alerts (baseline: 65 findings, 9 off-topic, **13.8% off**)

## Comparison table (all 9 samples)

| Topic | Config | Retained | On | Off | Off % | Recall | Precision |
|---|---|---:|---:|---:|---:|---:|---:|
| gravity-trap-putin-schroeder | T=0.55 V1 | 14 | 11 | 3 | 21.4% | 0.917 | 0.786 |
| gravity-trap-putin-schroeder | T=0.55 V2 | 11 | 11 | 0 | 0.0% | 0.917 | 1.000 |
| gravity-trap-putin-schroeder | T=0.50 V2 | 15 | 11 | 4 | 26.7% | 0.917 | 0.733 |
| borderline-trump-iran-peace | T=0.55 V1 | 45 | 42 | 3 | 6.7% | 0.592 | 0.933 |
| borderline-trump-iran-peace | T=0.55 V2 | 36 | 34 | 2 | 5.6% | 0.479 | 0.944 |
| borderline-trump-iran-peace | T=0.50 V2 | 43 | 40 | 3 | 7.0% | 0.563 | 0.930 |
| clean-hantavirus | T=0.55 V1 | 33 | 33 | 0 | 0.0% | 0.589 | 1.000 |
| clean-hantavirus | T=0.55 V2 | 24 | 24 | 0 | 0.0% | 0.429 | 1.000 |
| clean-hantavirus | T=0.50 V2 | 33 | 33 | 0 | 0.0% | 0.589 | 1.000 |

## Files

- [`T=0.55-V1/gravity-trap-putin-schroeder.md`](T=0.55-V1/gravity-trap-putin-schroeder.md)
- [`T=0.55-V1/borderline-trump-iran-peace.md`](T=0.55-V1/borderline-trump-iran-peace.md)
- [`T=0.55-V1/clean-hantavirus.md`](T=0.55-V1/clean-hantavirus.md)
- [`T=0.55-V2/gravity-trap-putin-schroeder.md`](T=0.55-V2/gravity-trap-putin-schroeder.md)
- [`T=0.55-V2/borderline-trump-iran-peace.md`](T=0.55-V2/borderline-trump-iran-peace.md)
- [`T=0.55-V2/clean-hantavirus.md`](T=0.55-V2/clean-hantavirus.md)
- [`T=0.50-V2/gravity-trap-putin-schroeder.md`](T=0.50-V2/gravity-trap-putin-schroeder.md)
- [`T=0.50-V2/borderline-trump-iran-peace.md`](T=0.50-V2/borderline-trump-iran-peace.md)
- [`T=0.50-V2/clean-hantavirus.md`](T=0.50-V2/clean-hantavirus.md)
