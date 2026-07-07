# MADLAD-400-3B — CTranslate2-int8 (translation sidecar artifact)

This directory is the **license + provenance packaging** for the MADLAD-400-3B
CTranslate2-int8 translation model used by Independent Wire's optional clustering
translate-to-English sidecar (`src/stages/translate_sidecar.py`, flag
`IW_CLUSTER_TRANSLATE`, **default OFF**).

The model weights themselves are **not stored in this repository** — they are a
~2.8 GB Apache-2.0 *data artifact*, fetched or reconverted separately (see
"Obtaining the weights" below) and dropped into this directory at deploy time.
Only this `LICENSE`, this card, and `.gitignore` are tracked in git.

## What it is

- **Base model:** [`google/madlad400-3b-mt`](https://huggingface.co/google/madlad400-3b-mt)
  — a T5 multilingual machine-translation model. The English target is selected
  by a `<2en>` **source-prefix** token; the source language is auto-detected.
- **This build:** the base weights **format-converted to CTranslate2 and
  quantized to int8**. Runtime inference needs only `ctranslate2` +
  `sentencepiece` (no torch, no transformers — those are conversion-only).

## License — Apache-2.0

`google/madlad400-3b-mt` is licensed **Apache-2.0**; it is itself a community
conversion (by Juarez Bochi) of Google's original Apache-2.0 MADLAD-400 T5X
weights. A CTranslate2-int8 build is a redistributable Apache-2.0 **Derivative
Work**. The full license is in [`LICENSE`](./LICENSE).

### Apache-2.0 §4 redistribution compliance

- **§4(a) — copy of the License:** included ([`LICENSE`](./LICENSE)).
- **§4(b) — statement of changes:** the upstream `google/madlad400-3b-mt` weights
  were **format-converted from the Hugging Face safetensors checkpoint to the
  CTranslate2 model format and quantized to int8**. No fine-tuning, distillation,
  or weight editing was performed — the change is a lossy numeric-format
  conversion only. Conversion environment (pinned): `ctranslate2==4.5.0` +
  `transformers==4.46.3`, `ct2-transformers-converter … --quantization int8`.
  (transformers ≥ 5.x silently mis-ties MADLAD's embeddings and corrupts the
  weights; the pinned pair is required for a correct conversion.)
- **§4(c) — attribution:** the upstream copyright and attribution notices are
  retained. Original weights © Google LLC (Apache-2.0); HF safetensors
  conversion by Juarez Bochi.
- **§4(d) — NOTICE:** the upstream `google/madlad400-3b-mt` repository ships **no
  `NOTICE` file**, and Google's original MADLAD-400 release carries no NOTICE
  attribution beyond the Apache-2.0 license text. Per §4(d) a NOTICE is therefore
  **not reproduced and not fabricated**. If a future upstream revision adds a
  NOTICE, carry it forward here verbatim.
- **§6 — trademarks:** host any published copy under your own account; this
  packaging does not imply endorsement by Google or Hugging Face.

### Relationship to Independent Wire's AGPL-3.0 license

The model is a **separately-licensed Apache-2.0 data artifact** (runtime
auto-download / a separate file on disk), not a work "based on" the AGPL-3.0
codebase. AGPL copyleft (and its network-source clause) reach the AGPL program's
Corresponding Source, not an independent data artifact; conversely this project's
AGPL does not extend onto the Apache-2.0 model. This is mere aggregation.

## Provenance (verify before trusting a copy)

| artifact | sha256 | size |
|---|---|---|
| source `model.safetensors` (pre-conversion) | `66ff5f8fcaf92291da486fdfbd4d5233cec90e1359348a56e3172c978b3a76d4` | 11,761,587,872 B |
| `spiece.model` (256000-piece tokenizer) | `ef11ac9a22c7503492f56d48dce53be20e339b63605983e9f27d2cd0e0f3922c` | 4.43 MB |
| converted `model.bin` (int8, ct2 4.5.0) | `890ed3b7…ca702` (local build; deterministic given the pins) | 2.95 GB |

Correct-conversion marker: the HF `config.json` has `tie_word_embeddings: false`.

## Runtime artifact set (the deployment gap)

A sentencepiece-only runtime needs the CT2 directory **and** `spiece.model`, which
is **not** part of the CT2 dir by default:

| file | provided by |
|---|---|
| `config.json` (CT2, ~224 B) | CT2 conversion |
| `model.bin` (int8, ~2.95 GB) | CT2 conversion |
| `shared_vocabulary.json` (~5.5 MB) | CT2 conversion |
| `spiece.model` (~4.43 MB) | **staged separately** from the source repo |

Stage all four into this directory (or any dir), then point the sidecar at it:

```bash
export IW_CLUSTER_TRANSLATE=1
export IW_CLUSTER_TRANSLATE_CT2_DIR=/path/to/models/madlad400-3b-mt-ct2-int8
# spiece.model resolves from IW_CLUSTER_TRANSLATE_SPIECE, else <CT2_DIR>/spiece.model
export IW_CLUSTER_TRANSLATE_SPIECE=/path/to/spiece.model   # optional if inside the dir
uv sync --extra multilingual                               # ctranslate2 + sentencepiece
```

## Obtaining the weights

1. **Download a published CT2-int8 build** (recommended once hosted) and drop the
   four files above into this directory. Verify the sha256s in the provenance
   table.
2. **Reconvert from source** (air-gapped / trustless): in a throwaway venv with
   the pinned pair `ctranslate2==4.5.0` + `transformers==4.46.3`, run
   `ct2-transformers-converter --model google/madlad400-3b-mt --quantization int8
   --output_dir <this dir>`, then copy `spiece.model` from the HF snapshot into
   `<this dir>`. Confirm `tie_word_embeddings: false` in the source `config.json`.

Full integration spec and enablement gates:
`scratch/MADLAD-INTEGRATION-REQUIREMENTS.md`.
