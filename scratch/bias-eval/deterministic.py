"""Deterministic layer — machine checks applied to any bias output.

Given the article_body and a bias output (structured dict), returns:
  - schema_valid: matches BIAS_DETECTOR_SCHEMA (strict)
  - verbatim: every flagged excerpt appears VERBATIM in article_body
  - category_valid: every issue is one of the 6 allowed categories
  - counts: total / valid / retracted findings, per-category histogram
  - empty_emission: True when findings == [] AND reader_note == ""

Used both to police Phase-0 outputs (precondition) and to build the
Phase-1 deterministic table. No LLM, no judgment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

CATS = {"evaluative_adjective", "emotionalizing", "passive_obscuring",
        "loaded_term", "hedging", "intensifier"}

_FIND_KEYS = {"excerpt", "issue", "explanation", "finding_valid"}


def _schema_valid(s: dict) -> bool:
    """Minimal strict validator for BIAS_DETECTOR_SCHEMA (no jsonschema dep).
    Mirrors the strict/additionalProperties:false contract exactly."""
    if not isinstance(s, dict):
        return False
    if set(s.keys()) != {"language_bias", "reader_note"}:
        return False
    if not isinstance(s.get("reader_note"), str):
        return False
    lb = s.get("language_bias")
    if not isinstance(lb, dict) or set(lb.keys()) != {"findings"}:
        return False
    fs = lb.get("findings")
    if not isinstance(fs, list):
        return False
    for f in fs:
        if not isinstance(f, dict) or set(f.keys()) != _FIND_KEYS:
            return False
        if not isinstance(f.get("excerpt"), str):
            return False
        if not isinstance(f.get("issue"), str):
            return False
        if not isinstance(f.get("explanation"), str):
            return False
        if not isinstance(f.get("finding_valid"), bool):
            return False
    return True


def check(structured: dict, article_body: str) -> dict:
    r = {"schema_valid": False, "verbatim": None, "category_valid": None,
         "total": 0, "valid": 0, "retracted": 0, "hist": {},
         "bad_spans": [], "bad_cats": [], "empty_emission": None}
    if not isinstance(structured, dict):
        r["schema_valid"] = False
        return r
    r["schema_valid"] = _schema_valid(structured)
    lb = (structured.get("language_bias") or {})
    fs = lb.get("findings") or []
    r["total"] = len(fs)
    bad_spans, bad_cats, hist = [], [], {}
    valid = 0
    for f in fs:
        ex = f.get("excerpt", "")
        iss = f.get("issue", "")
        is_valid = f.get("finding_valid") is not False
        if is_valid:
            valid += 1
            hist[iss] = hist.get(iss, 0) + 1
        # verbatim + category checked on VALID findings (retracted ones
        # are audit trail; a retraction whose excerpt is absent is exactly
        # the legitimate finding_valid=false escape hatch).
        if is_valid and ex not in article_body:
            bad_spans.append(ex[:60])
        if is_valid and iss not in CATS:
            bad_cats.append(iss)
    r["valid"] = valid
    r["retracted"] = r["total"] - valid
    r["hist"] = hist
    r["bad_spans"] = bad_spans
    r["bad_cats"] = bad_cats
    r["verbatim"] = len(bad_spans) == 0
    r["category_valid"] = len(bad_cats) == 0
    note = (structured.get("reader_note") or "").strip()
    r["empty_emission"] = (r["total"] == 0 and note == "")
    return r


if __name__ == "__main__":
    # Smoke: check the stored incumbent output for one snapshot round-trips.
    import glob, os
    from src.bus import TopicBus
    date, n = "2026-06-13", 0
    run = glob.glob(f"{REPO}/output/{date}/_state/run-*")[0]
    d = json.load(open(os.path.join(run, f"topic_buses.BiasLanguageStage.{n}.json")))
    tb = TopicBus.model_validate(d)
    body = tb.qa_corrected_article.body
    structured = {"language_bias": {"findings": tb.bias_language_findings},
                  "reader_note": tb.bias_reader_note}
    print(json.dumps(check(structured, body), indent=1, ensure_ascii=False))
