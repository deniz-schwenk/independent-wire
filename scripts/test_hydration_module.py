"""Smoke test for src.hydration.hydrate_urls on the 51 Lauf-19 URLs.

Loads the canonical input set from Spike B's fetch_results.json, runs the
production module with default knobs, prints a summary, writes full results
to output/{today}/test_hydration_module/results.json, and checks the
acceptance-criteria invariants (success rate window, Anadolu recoveries).

No pipeline integration, no LLM calls. Pure validation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter
from datetime import date
from pathlib import Path

from src.hydration import STATUS_VALUES, hydrate_urls

REPO_ROOT = Path(__file__).resolve().parent.parent
SPIKE_B_RESULTS = (
    REPO_ROOT
    / "output/2026-04-19/test_hydration_spike_b/fetch_results.json"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hydration-smoke")


def load_input() -> list[dict]:
    data = json.loads(SPIKE_B_RESULTS.read_text())
    entries: list[dict] = []
    for row in data:
        entries.append(
            {
                "url": row["url"],
                "outlet": row.get("outlet", "unknown"),
                "language": row.get("language"),
                # Spike B records region, not country; pass it through under
                # the required country key so the module input contract holds.
                "country": row.get("region"),
                # Pass-through metadata to verify the module preserves it.
                "topic": row.get("topic"),
                "finding_id": row.get("finding_id"),
            }
        )
    return entries


def summarize(results: list[dict]) -> dict:
    counts = Counter(r["status"] for r in results)
    total = len(results)
    succ = [r for r in results if r["status"] == "success"]
    avg_success_ms = (
        sum(r["fetch_duration_ms"] for r in succ) / len(succ)
    ) if succ else 0.0
    return {
        "total": total,
        "by_status": {s: counts.get(s, 0) for s in STATUS_VALUES},
        "success_rate": (len(succ) / total) if total else 0.0,
        "avg_success_fetch_ms": avg_success_ms,
    }


def main() -> int:
    entries = load_input()
    log.info("Loaded %d URLs from Spike B results", len(entries))

    start = time.monotonic()
    results = asyncio.run(hydrate_urls(entries))
    wall = time.monotonic() - start

    summary = summarize(results)
    log.info("Completed in %.1fs", wall)
    log.info("By status:")
    for status in STATUS_VALUES:
        n = summary["by_status"][status]
        pct = (n / summary["total"] * 100) if summary["total"] else 0.0
        log.info("  %-18s %3d (%.1f%%)", status, n, pct)
    log.info(
        "Success rate: %.1f%%  (avg success fetch: %.0f ms)",
        summary["success_rate"] * 100,
        summary["avg_success_fetch_ms"],
    )

    # Acceptance-criteria invariants.
    problems: list[str] = []

    # Success rate within ±5 pp of 70.6% (i.e., 65.6% to 75.6%).
    rate = summary["success_rate"] * 100
    if rate < 65.6 or rate > 75.6:
        problems.append(
            f"success rate {rate:.1f}% outside ±5pp window around 70.6%"
        )

    # All 6 Anadolu URLs must be classified as success.
    anadolu = [r for r in results if r.get("outlet") == "Anadolu Agency"]
    anadolu_succ = sum(1 for r in anadolu if r["status"] == "success")
    if anadolu_succ != 6:
        problems.append(
            f"Anadolu Agency: {anadolu_succ}/6 success (expected 6/6)"
        )

    # Persist full results for inspection.
    today = date.today().isoformat()
    out_dir = REPO_ROOT / "output" / today / "test_hydration_module"
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.json"
    results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    log.info("Wrote %s", results_path)

    if problems:
        log.error("ACCEPTANCE CRITERIA FAILED:")
        for p in problems:
            log.error("  - %s", p)
        return 1

    log.info("Acceptance criteria: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
