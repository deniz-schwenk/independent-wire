#!/usr/bin/env python3
"""reaudit_translate.py — MADLAD-English-normalise the non-English findings.

TASK-MADLAD-FLOOR-LABELSET Phase 0, step 2. Runs in a SCRATCH venv with
`ctranslate2` + `sentencepiece` (NOT the production .venv, which stays clean).

Translates every unique non-English, FLORES-mapped finding in labelset.json
(title and summary as separate segments — matching the sidecar's per-segment
translation) with the local CT2-int8 MADLAD-400 model via the `<2en>`
sentencepiece path. This path is byte-identical to the transformers AutoTokenizer
path used by the lost June harness / madlad_common.MadladCT2 (proven across the
whole production + non-Latin language pool by the enable-prep tok-equiv golden,
tests/data/madlad_tok_equiv_golden.json), and needs no conversion-only
transformers dep. madlad_common.py is reused for the FLORES / norm_lang gate.

Output: translation_map.json = {finding_id: {lang, title_en, summary_en}}.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from madlad_common import ENGLISH_LANGS, FLORES, norm_lang  # noqa: E402

TARGET_PREFIX = "<2en>"
EOS, PAD = "</s>", "<pad>"
NUM_BEAMS, MAX_LEN = 4, 200


class MadladSP:
    """CT2-int8 MADLAD, sentencepiece-only `<2en>` decode (transformers-free)."""

    def __init__(self, model_dir: str, spiece: str) -> None:
        import ctranslate2
        import sentencepiece

        self.sp = sentencepiece.SentencePieceProcessor()
        self.sp.Load(spiece)
        self.tr = ctranslate2.Translator(model_dir, device="cpu")

    def translate(self, texts: list[str], batch: int = 32) -> list[str]:
        out = [""] * len(texts)
        idx = [i for i, t in enumerate(texts) if (t or "").strip()]
        for b in range(0, len(idx), batch):
            bi = idx[b:b + batch]
            tok = [self.sp.encode(TARGET_PREFIX + " " + texts[i], out_type=str) + [EOS]
                   for i in bi]
            res = self.tr.translate_batch(
                tok, beam_size=NUM_BEAMS, max_decoding_length=MAX_LEN,
                max_batch_size=batch)
            for i, r in zip(bi, res):
                ids = [self.sp.piece_to_id(p) for p in r.hypotheses[0]
                       if p not in (EOS, PAD)]
                out[i] = self.sp.decode(ids).strip()
        return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labelset", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ct2-dir", default=os.environ.get(
        "IW_CLUSTER_TRANSLATE_CT2_DIR", ""))
    ap.add_argument("--spiece", default=os.environ.get(
        "IW_CLUSTER_TRANSLATE_SPIECE", ""))
    ap.add_argument("--batch", type=int, default=32)
    args = ap.parse_args()

    pairs = json.loads(Path(args.labelset).read_text(encoding="utf-8"))

    # Unique non-English findings needing translation, keyed by uid
    # (day:finding_id) — finding_id alone collides across days.
    todo: dict[str, dict] = {}
    for p in pairs:
        lang = norm_lang(p.get("language"))
        if lang in ENGLISH_LANGS or lang not in FLORES:
            continue
        title, summary = p.get("title") or "", p.get("summary") or ""
        if not (title.strip() or summary.strip()):
            continue
        todo.setdefault(p["uid"], {"lang": lang, "title": title,
                                   "summary": summary})

    fids = list(todo)
    print(f"unique non-English findings to translate: {len(fids)} "
          f"({sum(1 for f in todo.values() if 1)} segments x2)")

    # One flat segment list (title then summary per finding); MADLAD auto-detects
    # source, so no per-language grouping is needed.
    segs, owners = [], []
    for fid in fids:
        segs.append(todo[fid]["title"]); owners.append((fid, "title_en"))
        segs.append(todo[fid]["summary"]); owners.append((fid, "summary_en"))

    m = MadladSP(args.ct2_dir, args.spiece)
    t0 = time.time()
    translated = m.translate(segs, batch=args.batch)
    dt = time.time() - t0

    out: dict[str, dict] = {fid: {"lang": todo[fid]["lang"]} for fid in fids}
    for (fid, slot), text in zip(owners, translated):
        out[fid][slot] = text

    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(f"translated {len(segs)} segments in {dt:.1f}s "
          f"({len(segs)/dt:.2f} seg/s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
