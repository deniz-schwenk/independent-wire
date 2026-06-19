#!/usr/bin/env python3
"""Production wrapper for the German translation feature — standalone, post-pipeline.

After the daily production run completes, this translates all of the day's Topic Packages
into German and persists German JSON. It is a SEPARATE feature for German reach: it reads
the finished production run state READ-ONLY and is never imported by scripts/run.py, never
a Stage, never wired into the Bus. It does NOT render HTML and does NOT push a site — that
is the next task (German renderer + label map + DE/EN switch).

What it does, per day:
  1. Guard — find the day's COMPLETED TPs in output/<date>/ (a TP is complete when both
     its tp-*.json and tp-*.html exist; HTML is written last). Exit cleanly if none.
  2. Per-TP fallback chain (transport.build_chain) — try providers in order; if one fails
     the WHOLE TP (transport error / HTTP 5xx / guard cannot clean after ladder retries),
     restart the WHOLE TP on the next provider. Never mix providers within one TP.
       1 ollama-cloud (flat-rate, $0)  2 deepseek-direct (strict tools)
       3 openrouter:deepseek           4 openrouter:atlas-cloud
     A TP that exhausts all four is a hard failure: left untranslated (never half-done),
     surfaced in the summary.
  3. Bracket-normalization post-pass (deterministic) — a Policy-A gloss in round parens
     directly after a closing quote becomes square brackets. Logged per conversion.
  4. Parallel TPs — the day's TPs run concurrently, staggered a few seconds apart to avoid
     provider rate-limit bursts; wall-clock ~ the slowest single TP. Per-TP logs separate.
  5. Persist — output/<date>/de/<tp_id>.de.json (translation) + de/logs/<tp_id>.log.json
     (per-TP attempt trace) + de/_summary.json (the day's run summary). $0 unless a
     fallback past Ollama actually fires.

Usage:
  translate_de.py                      # translate today's completed run
  translate_de.py --date 2026-06-19    # a specific date
  translate_de.py --only tp-2026-06-19-002
  translate_de.py --force              # re-translate even if a de.json already exists
  # smoke fault-injection (prove the chain at $0, no real billed call):
  translate_de.py --force-fail ollama-cloud --dry-billed --only tp-2026-06-19-002
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date as _date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))

from src.translate import brackets, transport               # noqa: E402
from src.translate.run import translate_tp                  # noqa: E402

OUTPUT_DIR = REPO / "output"
STAGGER_S = 3.0       # seconds between firing each TP, to avoid provider bursts


def log(msg: str) -> None:
    print(f"[translate_de {time.strftime('%Y-%m-%dT%H:%M:%S')}] {msg}", flush=True)


def completed_tps(date: str) -> list[Path]:
    """TPs in output/<date>/ that have BOTH json and html (production finished that TP)."""
    daydir = OUTPUT_DIR / date
    if not daydir.is_dir():
        return []
    out = []
    for jp in sorted(daydir.glob(f"tp-{date}-*.json")):
        if jp.with_suffix(".html").exists():
            out.append(jp)
    return out


def apply_brackets(result) -> list[dict]:
    """Run the deterministic gloss bracket post-pass over the winning provider's finals,
    mutating each item's `final` in place. Returns the list of conversions for logging."""
    conversions = []
    for it in result.items:
        new_final, conv = brackets.normalize_glosses(it.get("final") or "")
        if conv:
            it["final"] = new_final
            for c in conv:
                conversions.append({"key": it["key"], "path": it["path"], **c})
    return conversions


async def run_one_tp(tp_path: Path, date: str, chain, stagger_idx: int,
                     batch_size: int) -> dict:
    """Walk the fallback chain for one TP. Returns a per-TP record."""
    await asyncio.sleep(stagger_idx * STAGGER_S)
    tp = json.loads(tp_path.read_text(encoding="utf-8"))
    tp_id = tp.get("id", tp_path.stem)
    fallbacks: list[dict] = []
    attempts: list[dict] = []
    t0 = time.monotonic()

    for provider in chain:
        try:
            res = await translate_tp(provider, tp, batch_size=batch_size)
        except Exception as e:  # defensive: any unexpected provider error -> next provider
            cause = f"unexpected: {type(e).__name__}: {e}"
            res = None
        else:
            cause = res.reason
        attempts.append({"provider": provider.name,
                         "ok": bool(res and res.ok),
                         "cost_usd": round(res.cost_usd, 6) if res else 0.0,
                         "calls": res.calls if res else 0,
                         "repairs": res.repairs if res else 0,
                         "reason": (None if (res and res.ok) else cause)})
        if res and res.ok:
            conversions = apply_brackets(res)
            rec = write_success(tp_path, date, res, fallbacks, conversions, attempts, t0)
            note = f" (+{len(fallbacks)} fallback(s))" if fallbacks else ""
            log(f"{tp_id}: translated via {provider.name}{note} — "
                f"{len(res.items)} items, {len(conversions)} bracket fix(es), "
                f"${res.cost_usd:.4f}, {round(time.monotonic()-t0,1)}s")
            return rec
        # provider failed this TP -> log the fallback activation, try the next one
        fallbacks.append({"provider": provider.name, "cause": cause})
        log(f"FALLBACK {tp_id}: provider '{provider.name}' failed — {cause}")

    # all providers exhausted -> hard failure, leave untranslated
    total_cost = round(sum(a["cost_usd"] for a in attempts), 6)
    rec = {"tp_id": tp_id, "status": "hard_failure", "provider": None,
           "source_tp": str(tp_path), "fallbacks": fallbacks, "attempts": attempts,
           "items": 0, "bracket_normalizations": 0, "cost_usd": total_cost,
           "wall_clock_s": round(time.monotonic() - t0, 2)}
    write_log(date, tp_id, rec)
    log(f"HARD FAILURE {tp_id}: all {len(chain)} providers exhausted — left untranslated")
    return rec


def write_success(tp_path, date, res, fallbacks, conversions, attempts, t0) -> dict:
    de_dir = OUTPUT_DIR / date / "de"
    de_dir.mkdir(parents=True, exist_ok=True)
    exp, pres = res.src_tokens_expected, res.src_tokens_present
    de_doc = {
        "tp_id": res.tp_id,
        "source_tp": str(tp_path),
        "date": date,
        "feature": "translate_de",
        "schema": "de-v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "provider": res.provider,
        "fallbacks": fallbacks,
        "billed_usd": round(res.cost_usd, 6),
        "block_calls": res.calls,
        "repair_retries": res.repairs,
        "wall_clock_s": res.wall_s,
        "guard": {"items_total": len(res.items),
                  "items_clean": sum(1 for it in res.items if it["ok"]),
                  "degenerate": res.degenerate},
        "src_tokens": {"expected": exp, "present": pres,
                       "preserved_pct": round(100 * pres / exp, 1) if exp else 100.0},
        "bracket_normalizations": conversions,
        "entity_index": res.entity_index,
        # The renderer (next task) splices each `final` back into the TP by `path`.
        "items": [{"block": it.get("block"), "key": it["key"],
                   "path": it["path"], "final": it["final"]} for it in res.items],
    }
    out = de_dir / f"{res.tp_id}.de.json"
    out.write_text(json.dumps(de_doc, indent=2, ensure_ascii=False), encoding="utf-8")

    rec = {"tp_id": res.tp_id, "status": "translated", "provider": res.provider,
           "source_tp": str(tp_path), "fallbacks": fallbacks, "attempts": attempts,
           "items": len(res.items), "bracket_normalizations": len(conversions),
           "cost_usd": round(sum(a["cost_usd"] for a in attempts), 6),
           "wall_clock_s": round(time.monotonic() - t0, 2),
           "src_tokens_pct": de_doc["src_tokens"]["preserved_pct"],
           "out": str(out)}
    write_log(date, res.tp_id, {**rec, "blocks": res.blocks,
                                "bracket_conversions": conversions})
    return rec


def write_log(date: str, tp_id: str, rec: dict) -> None:
    logs = OUTPUT_DIR / date / "de" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{tp_id}.log.json").write_text(
        json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")


async def main_async(a) -> int:
    date = a.date or _date.today().isoformat()
    tps = completed_tps(date)
    if a.only:
        only = set(a.only)
        tps = [p for p in tps if p.stem in only or p.name in only]
    if not tps:
        log(f"GUARD: no completed production TPs for {date} — nothing to do, exiting clean.")
        return 0
    log(f"GUARD ok: {len(tps)} completed TP(s) for {date}: {[p.stem for p in tps]}")

    de_dir = OUTPUT_DIR / date / "de"
    todo = []
    for p in tps:
        existing = de_dir / f"{p.stem}.de.json"
        if existing.exists() and not a.force:
            log(f"SKIP {p.stem}: already translated ({existing.name}); use --force to redo")
            continue
        todo.append(p)
    if not todo:
        log("all completed TPs already translated — nothing to do.")
        return 0

    chain = transport.build_chain(force_fail=a.force_fail, dry_billed=a.dry_billed,
                                   ollama_host=a.ollama_host)
    log(f"fallback chain: {[p.name for p in chain]}"
        + (f"  [force-fail={sorted(set(a.force_fail))}]" if a.force_fail else "")
        + ("  [dry-billed]" if a.dry_billed else ""))

    t0 = time.monotonic()
    recs = await asyncio.gather(*[
        run_one_tp(p, date, chain, i, a.batch_size) for i, p in enumerate(todo)])
    wall = round(time.monotonic() - t0, 1)

    # ---- summary
    translated = [r for r in recs if r["status"] == "translated"]
    failed = [r for r in recs if r["status"] == "hard_failure"]
    total_cost = round(sum(r["cost_usd"] for r in recs), 6)
    brackets_total = sum(r["bracket_normalizations"] for r in translated)
    summary = {
        "date": date, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "completed_tps": len(tps), "translated": len(translated),
        "hard_failures": [r["tp_id"] for r in failed],
        "billed_usd": total_cost,
        "bracket_normalizations": brackets_total,
        "fallbacks_fired": sum(1 for r in recs if r["fallbacks"]),
        "wall_clock_s": wall,
        "tps": recs,
    }
    de_dir.mkdir(parents=True, exist_ok=True)
    (de_dir / "_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    log("=" * 60)
    log(f"SUMMARY {date}: {len(translated)}/{len(todo)} translated, "
        f"{len(failed)} hard failure(s), {brackets_total} bracket fix(es), "
        f"billed ${total_cost:.4f}, wall {wall}s")
    for r in translated:
        fb = f" via {len(r['fallbacks'])} fallback(s)" if r["fallbacks"] else ""
        log(f"  ✓ {r['tp_id']}: {r['provider']}{fb}, {r['items']} items, "
            f"{r['bracket_normalizations']} bracket fix(es), src-tokens {r.get('src_tokens_pct')}%")
    for r in failed:
        log(f"  ✗ {r['tp_id']}: HARD FAILURE — providers tried: "
            f"{[f['provider'] for f in r['fallbacks']]}")
    if total_cost == 0:
        log("billed $0 (Ollama-Cloud flat-rate; no fallback past Ollama fired) ✓")
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="German translation production wrapper")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--only", nargs="+", default=None, help="restrict to these TP id(s)")
    ap.add_argument("--force", action="store_true",
                    help="re-translate even if a de.json already exists")
    ap.add_argument("--batch-size", type=int, default=8, dest="batch_size")
    ap.add_argument("--ollama-host", default=transport.OLLAMA_HOST)
    # smoke fault-injection (prove the fallback chain at $0):
    ap.add_argument("--force-fail", nargs="+", default=None,
                    help="provider name(s) to force-fail (e.g. ollama-cloud)")
    ap.add_argument("--dry-billed", action="store_true",
                    help="stub ALL billed providers to a synthetic failure (no network call)")
    a = ap.parse_args()
    return asyncio.run(main_async(a))


if __name__ == "__main__":
    sys.exit(main())
