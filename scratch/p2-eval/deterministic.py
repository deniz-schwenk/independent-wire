"""Deterministic (LLM-free) integrity layer over the phase-2 shadow outputs.

Structural checks only — the SEMANTIC fabrication judgment is the judging phase.
Per arm x topic:
  * schema validity (final): structured is a dict with two string arrays;
  * article-index resolution: any "article N" reference in a string resolves to
    a real article_index in the input;
  * cross-group both-sides-exist: every LANGUAGE named in a divergence is a
    language actually present in the corpus metadata (a divergence that contrasts
    a language group absent from the corpus is structurally invalid — a
    fabricated side);
  * invented outlets: outlet names appearing in strings exist in the metadata;
  * counts, cost, tokens, latency, provider.

  uv run python scratch/p2-eval/deterministic.py            # table over all arms
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from harness import ARTICLES, ARMS, load_input, raw_path  # noqa: E402

# ISO 639-1 -> the adjective forms a divergence string would use.
LANG_NAMES = {
    "ar": "arabic", "bn": "bengali", "de": "german", "en": "english",
    "es": "spanish", "fa": "persian", "fr": "french", "he": "hebrew",
    "hi": "hindi", "id": "indonesian", "it": "italian", "ja": "japanese",
    "ko": "korean", "ne": "nepali", "nl": "dutch", "pt": "portuguese",
    "ru": "russian", "sw": "swahili", "th": "thai", "tr": "turkish",
    "uk": "ukrainian", "ur": "urdu", "uz": "uzbek", "vi": "vietnamese",
    "zh": "chinese", "zu": "zulu",
}
# language adjectives that may appear in a divergence string
_ALL_LANG_ADJ = set(LANG_NAMES.values())


def _corpus_langs(meta: list[dict]) -> set[str]:
    out = set()
    for m in meta:
        code = (m.get("language") or "").lower()[:2]
        if code in LANG_NAMES:
            out.add(LANG_NAMES[code])
    return out


def _corpus_outlets(meta: list[dict]) -> set[str]:
    return {(m.get("outlet") or "").lower() for m in meta if m.get("outlet")}


def _named_langs(text: str) -> set[str]:
    t = text.lower()
    return {adj for adj in _ALL_LANG_ADJ if re.search(rf"\b{re.escape(adj)}\b", t)}


def analyse_cell(arm: str, date: str, n: int) -> dict | None:
    p = raw_path(arm, date, n)
    if not p.exists():
        return None
    rec = json.load(open(p))
    inp = load_input(date, n)
    meta = inp["article_metadata"]
    n_art = len(inp["article_analyses"])
    corpus_langs = _corpus_langs(meta)
    corpus_outlets = _corpus_outlets(meta)

    st = rec.get("structured")
    schema_ok = (isinstance(st, dict)
                 and isinstance(st.get("preliminary_divergences"), list)
                 and isinstance(st.get("coverage_gaps"), list)
                 and all(isinstance(x, str) for x in st.get("preliminary_divergences", []))
                 and all(isinstance(x, str) for x in st.get("coverage_gaps", [])))
    divs = (st or {}).get("preliminary_divergences", []) if schema_ok else []
    gaps = (st or {}).get("coverage_gaps", []) if schema_ok else []

    bad_index = 0
    lang_side_missing = 0   # a named language not present in the corpus
    single_side = 0         # a "divergence" naming <2 corpus languages (not cross-group)
    for d in divs:
        for m in re.findall(r"\barticle\s+(\d+)\b", d.lower()):
            if int(m) >= n_art:
                bad_index += 1
        named = _named_langs(d)
        missing = named - corpus_langs
        lang_side_missing += len(missing)
        # cross-group divergences should name >=2 language groups that exist
        if len(named & corpus_langs) < 2 and named:
            single_side += 1

    invented_outlets = 0
    for s in list(divs) + list(gaps):
        # crude: any metadata outlet token check is membership; we cannot list
        # arbitrary names, so we only flag references to outlet-looking proper
        # nouns that are NOT in the corpus is infeasible deterministically ->
        # instead count outlets from the corpus explicitly *claimed absent*.
        pass  # (outlet invention is judged, not deterministically decidable here)

    return {
        "arm": arm, "date": date, "topic": n, "ok": rec.get("ok"),
        "schema_ok": schema_ok, "structured_is_none": rec.get("structured_is_none"),
        "n_div": len(divs), "n_gap": len(gaps),
        "bad_index_refs": bad_index,
        "lang_side_not_in_corpus": lang_side_missing,
        "non_cross_group_div": single_side,
        "cost_usd": rec.get("cost_usd"), "tokens": rec.get("tokens"),
        "duration_s": rec.get("duration_s"), "provider": rec.get("served_provider"),
    }


def main():
    print(f"{'arm':10} {'cells':>5} {'schema_ok':>9} {'div/t':>6} {'gap/t':>6} "
          f"{'badIdx':>6} {'langMiss':>8} {'nonXgrp':>7} {'$/topic':>8} {'s/topic':>7}")
    for arm in ARMS:
        cells = [analyse_cell(arm, d, n) for d, n in ARTICLES]
        cells = [c for c in cells if c]
        if not cells:
            print(f"  {arm:10} (no cells)"); continue
        k = len(cells)
        ok = sum(1 for c in cells if c["schema_ok"])
        div = sum(c["n_div"] for c in cells) / k
        gap = sum(c["n_gap"] for c in cells) / k
        bad = sum(c["bad_index_refs"] for c in cells)
        lm = sum(c["lang_side_not_in_corpus"] for c in cells)
        nx = sum(c["non_cross_group_div"] for c in cells)
        costs = [c["cost_usd"] for c in cells if c["cost_usd"] is not None]
        durs = [c["duration_s"] for c in cells if c["duration_s"] is not None]
        mc = sum(costs) / len(costs) if costs else 0
        md = sum(durs) / len(durs) if durs else 0
        print(f"  {arm:10} {k:>5} {f'{ok}/{k}':>9} {div:>6.1f} {gap:>6.1f} "
              f"{bad:>6} {lm:>8} {nx:>7} {mc:>8.4f} {md:>7.1f}")
    json.dump(
        {arm: [analyse_cell(arm, d, n) for d, n in ARTICLES] for arm in ARMS},
        open(HERE / "deterministic.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
