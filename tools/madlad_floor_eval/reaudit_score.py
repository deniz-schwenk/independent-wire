#!/usr/bin/env python3
"""reaudit_score.py — production-venv fastembed cosines, native vs MADLAD-English.

TASK-MADLAD-FLOOR-LABELSET Phase 0, step 3. Runs in the PRODUCTION .venv so the
pinned fastembed singleton (paraphrase-multilingual-MiniLM-L12-v2, mean-pooled,
fastembed==0.8.0) makes the embeddings production-identical by construction.

For every labelled (finding, topic) pair, computes the finding<->topic-centre
cosine under two arms:
  * native   — the original-language finding text (_finding_text over title +
               summary + description);
  * english  — the sidecar's effective English finding text (_effective_finding:
               MADLAD title/summary, description blanked). Non-translated pairs
               (English / no-FLORES / empty) are bit-constant native = english.

Topic centres are English in BOTH arms (the Curator emits English topics), so
only the finding side moves — exactly the June re-audit design. Cosines use the
same embed -> L2-normalise -> dot rule as gravitational_assign.

Input : labelset.json + translation_map.json.
Output: scored.json = per-pair {day, topic_idx, finding_id, language, label,
        native_cos, english_cos}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.stages.coherence import _cosine_normalized, _get_default_embedder  # noqa: E402
from src.stages.gravitational_assign import _finding_text  # noqa: E402
from madlad_common import ENGLISH_LANGS, FLORES, norm_lang  # noqa: E402


def _english_text(pair: dict, tmap: dict) -> str:
    """The sidecar's effective English finding text for this pair, or native
    when the finding is not translated (English / no-FLORES / empty)."""
    uid = pair["uid"]
    lang = norm_lang(pair.get("language"))
    tr = tmap.get(uid)
    if lang in ENGLISH_LANGS or lang not in FLORES or tr is None:
        return pair["native_text"]  # bit-constant native passthrough
    # _effective_finding: English title/summary, description blanked
    return _finding_text({
        "title": tr.get("title_en") or "",
        "summary": tr.get("summary_en") or "",
        "description": "",
    })


def _embed_map(texts: list[str], embedder) -> dict[str, np.ndarray]:
    """Embed a unique text set once, L2-normalised; return text -> row vector."""
    uniq = sorted(set(texts))
    mat = _cosine_normalized(embedder.embed_batch(uniq))
    return {t: mat[i] for i, t in enumerate(uniq)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labelset", required=True)
    ap.add_argument("--translation-map", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pairs = json.loads(Path(args.labelset).read_text(encoding="utf-8"))
    tmap = json.loads(Path(args.translation_map).read_text(encoding="utf-8"))

    native_texts = [p["native_text"] for p in pairs]
    english_texts = [_english_text(p, tmap) for p in pairs]
    topic_texts = [p["topic_text"] for p in pairs]

    embedder = _get_default_embedder()
    print(f"embedding unique: {len(set(native_texts))} native + "
          f"{len(set(english_texts))} english findings + "
          f"{len(set(topic_texts))} topics")
    nat_emb = _embed_map(native_texts, embedder)
    eng_emb = _embed_map(english_texts, embedder)
    top_emb = _embed_map(topic_texts, embedder)

    scored = []
    for p, nt, et, tt in zip(pairs, native_texts, english_texts, topic_texts):
        tvec = top_emb[tt]
        scored.append({
            "day": p["day"],
            "topic_idx": p["topic_idx"],
            "finding_id": p["finding_id"],
            "language": norm_lang(p.get("language")),
            "label": int(p["label"]),
            "native_cos": round(float(nat_emb[nt] @ tvec), 6),
            "english_cos": round(float(eng_emb[et] @ tvec), 6),
        })

    Path(args.out).write_text(json.dumps(scored, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"scored {len(scored)} pairs -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
