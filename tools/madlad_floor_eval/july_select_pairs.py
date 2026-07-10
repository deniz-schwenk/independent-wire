#!/usr/bin/env python3
"""july_select_pairs.py — build (finding, topic) candidate pairs for labelling.

TASK-MADLAD-FLOOR-LABELSET Phase 1, step 3. Runs in the PRODUCTION .venv.

For each sampled target-language finding, forms candidate (finding, topic) pairs
against its OWN day's discovered topics. Candidate topics = the union of the
finding's top-K nearest topics by NATIVE cosine and by MADLAD-ENGLISH cosine —
so the pool spans both the precision-risk region (off-topic pairs English might
falsely lift over the floor) and the recall-gain region (on-topic pairs native
ranks low but English recovers). Selection uses cosines only; the on/off LABEL
is assigned later strictly from native text (circularity guard: pair selection
!= labelling path).

Both native_cos and english_cos are stored per pair so the Phase-2 gate is a pure
threshold afterwards. Deterministic (seed); per-language pair cap keeps labelling
within budget while clearing >=100 pairs/language.

Inputs : july_findings.json, july_topics.json, july_translation_map.json.
Output : july_pairs.json — list of {pair_id, uid, day, language, finding_id,
         finding_text, topic_idx, topic_title, topic_text, native_cos,
         english_cos, selected_by}.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from src.stages.coherence import _cosine_normalized, _get_default_embedder  # noqa: E402
from src.stages.gravitational_assign import _finding_text  # noqa: E402

TOP_K = 3
PAIR_CAP_PER_LANG = 130
SEED = 20260707


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", default=str(REPO / "scratch/floor-eval/july_findings.json"))
    ap.add_argument("--topics", default=str(REPO / "scratch/floor-eval/july_topics.json"))
    ap.add_argument("--translation-map", default=str(REPO / "scratch/floor-eval/july_translation_map.json"))
    ap.add_argument("--out", default=str(REPO / "scratch/floor-eval/july_pairs.json"))
    args = ap.parse_args()

    findings = json.loads(Path(args.findings).read_text(encoding="utf-8"))
    topics_by_day = json.loads(Path(args.topics).read_text(encoding="utf-8"))
    tmap = json.loads(Path(args.translation_map).read_text(encoding="utf-8"))

    def native_text(f):
        return _finding_text({"title": f["title"], "summary": f["summary"], "description": ""})

    def english_text(f):
        tr = tmap.get(f["uid"]) or {}
        return _finding_text({"title": tr.get("title_en") or "",
                              "summary": tr.get("summary_en") or "", "description": ""})

    # Embed everything once (unique texts)
    nat_texts = {native_text(f) for f in findings}
    eng_texts = {english_text(f) for f in findings}
    top_texts = {t["topic_text"] for day in topics_by_day.values() for t in day}
    embedder = _get_default_embedder()
    print(f"embedding {len(nat_texts)} native + {len(eng_texts)} english findings + "
          f"{len(top_texts)} topics")

    def emap(texts):
        u = sorted(texts)
        m = _cosine_normalized(embedder.embed_batch(u))
        return {t: m[i] for i, t in enumerate(u)}
    nat_emb, eng_emb, top_emb = emap(nat_texts), emap(eng_texts), emap(top_texts)

    rng = random.Random(SEED)
    by_lang: dict[str, list] = {}
    for f in findings:
        by_lang.setdefault(f["language"], []).append(f)

    pairs: list[dict] = []
    for lang, recs in by_lang.items():
        recs = sorted(recs, key=lambda r: r["uid"])
        rng.shuffle(recs)
        lang_pairs: list[dict] = []
        for f in recs:
            day_topics = topics_by_day.get(f["day"]) or []
            if not day_topics:
                continue
            nvec, evec = nat_emb[native_text(f)], eng_emb[english_text(f)]
            ncos = np.array([float(nvec @ top_emb[t["topic_text"]]) for t in day_topics])
            ecos = np.array([float(evec @ top_emb[t["topic_text"]]) for t in day_topics])
            k = min(TOP_K, len(day_topics))
            top_n = set(np.argsort(-ncos)[:k].tolist())
            top_e = set(np.argsort(-ecos)[:k].tolist())
            for ti in sorted(top_n | top_e):
                t = day_topics[ti]
                by = ("native" if ti in top_n else "") + ("english" if ti in top_e else "")
                lang_pairs.append({
                    "pair_id": f"{lang}:{f['uid']}:t{ti}",
                    "uid": f["uid"], "day": f["day"], "language": lang,
                    "finding_id": f["finding_id"],
                    "finding_text": native_text(f),
                    "topic_idx": ti, "topic_title": t["title"],
                    "topic_text": t["topic_text"],
                    "native_cos": round(float(ncos[ti]), 6),
                    "english_cos": round(float(ecos[ti]), 6),
                    "selected_by": by,
                })
        # deterministic cap per language (keeps labelling in budget)
        if len(lang_pairs) > PAIR_CAP_PER_LANG:
            rng.shuffle(lang_pairs)
            lang_pairs = sorted(lang_pairs[:PAIR_CAP_PER_LANG], key=lambda p: p["pair_id"])
        pairs.extend(lang_pairs)

    Path(args.out).write_text(json.dumps(pairs, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    counts: dict[str, int] = {}
    for p in pairs:
        counts[p["language"]] = counts.get(p["language"], 0) + 1
    print(f"\n{len(pairs)} candidate pairs:")
    for lg in ("ar", "zh", "ja", "th", "bn", "ne"):
        print(f"  {lg}: {counts.get(lg, 0)} pairs")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
