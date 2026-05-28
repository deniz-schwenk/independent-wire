"""Audit outlet_registry coverage against the published run set.

Walks every ``output/<date>/_state/run-*/topic_buses.propagate_outlet_metadata.*.json``
state snapshot — the cleanest source of the (url, display-name) pairs the
renderer actually consumes — and runs the REAL ``lookup_outlet`` from
``src/outlet_registry.py`` against each source's ``url``. Reports the
unmatched outlets only, sorted by occurrence frequency, with the date set
each was seen in.

Read-only. Writes nothing. No registry mutation, no schema change.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.outlet_registry import _normalise_hostname, lookup_outlet  # noqa: E402


def _iter_propagate_snapshots(output_dir: Path):
    """Every ``output/<date>/_state/run-*/topic_buses.propagate_outlet_metadata.*.json``.

    Date dirs match the renderer's strict format (10 chars, leading digits)
    so the survey aligns with the publication set the pipeline actually
    consumes.
    """
    for date_dir in sorted(output_dir.iterdir()):
        if not (date_dir.is_dir() and len(date_dir.name) == 10 and date_dir.name[:4].isdigit()):
            continue
        state_dir = date_dir / "_state"
        if not state_dir.is_dir():
            continue
        for run_dir in sorted(state_dir.iterdir()):
            if not run_dir.is_dir() or not run_dir.name.startswith("run-"):
                continue
            for snap in sorted(run_dir.glob("topic_buses.propagate_outlet_metadata.*.json")):
                yield date_dir.name, snap


def main() -> int:
    output_dir = ROOT / "output"
    if not output_dir.is_dir():
        print(f"No output/ directory at {output_dir}", file=sys.stderr)
        return 2

    # hostname (normalised) -> {
    #   "raw_urls": set of raw URLs seen,
    #   "display_names": set of `outlet` field values seen,
    #   "occurrences": int (per-source-entry count, not per-date),
    #   "dates": set of date strings,
    # }
    misses: dict[str, dict] = defaultdict(
        lambda: {"raw_urls": set(), "display_names": set(), "occurrences": 0, "dates": set()}
    )

    total_sources = 0
    total_matched = 0
    snapshot_count = 0

    for date, snap in _iter_propagate_snapshots(output_dir):
        snapshot_count += 1
        try:
            doc = json.loads(snap.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARN: failed to read {snap}: {exc}", file=sys.stderr)
            continue
        for src in doc.get("final_sources") or []:
            if not isinstance(src, dict):
                continue
            total_sources += 1
            url = src.get("url")
            display = src.get("outlet") or ""
            hit = lookup_outlet(url) if isinstance(url, str) and url else None
            if hit is not None:
                total_matched += 1
                continue
            host = _normalise_hostname(url) if isinstance(url, str) else ""
            entry = misses[host]
            entry["raw_urls"].add(url or "")
            entry["display_names"].add(display)
            entry["occurrences"] += 1
            entry["dates"].add(date)

    distinct_unmatched_hosts = len(misses)
    total_unmatched = sum(e["occurrences"] for e in misses.values())

    print("=" * 72)
    print(f"Outlet registry coverage audit")
    print("=" * 72)
    print(f"snapshots scanned                : {snapshot_count}")
    print(f"sources total                    : {total_sources}")
    print(f"matched by lookup_outlet         : {total_matched}")
    print(f"unmatched (rows)                 : {total_unmatched}")
    print(f"unmatched distinct hostnames     : {distinct_unmatched_hosts}")
    print()

    if not misses:
        print("No unmatched outlets. Registry coverage is complete on the audited set.")
        return 0

    print("UNMATCHED OUTLETS (sorted by occurrence count desc):")
    print()
    ordered = sorted(
        misses.items(),
        key=lambda kv: (-kv[1]["occurrences"], kv[0]),
    )
    for host, info in ordered:
        display_names = ", ".join(sorted(d for d in info["display_names"] if d)) or "(none)"
        dates = sorted(info["dates"])
        date_summary = (
            f"{dates[0]} .. {dates[-1]}" if len(dates) > 1 else (dates[0] if dates else "?")
        )
        print(f"  [{info['occurrences']:3d}x]  host={host!r}")
        print(f"           display_name(s): {display_names}")
        print(f"           dates ({len(dates)}): {date_summary}")
        # Show one example URL for context — full URLs help when picking
        # the right registry key (parent-domain fallback decisions).
        example_url = next(iter(sorted(info["raw_urls"])), "")
        if example_url:
            print(f"           example_url: {example_url}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
