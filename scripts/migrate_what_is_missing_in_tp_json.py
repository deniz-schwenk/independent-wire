"""Backfill `perspectives.what_is_missing` into historical TP JSON files.

The 2026-05-27 Consolidator refactor (commit ``3f59ab9``) introduced a
new bus slot — ``what_is_missing`` — written by a single LLM-backed
``ConsolidatorStage`` that replaces three earlier post-QA stages. The
slot is the single source of truth for the dossier's "what the corpus
lacks" surface, exposed under ``perspectives.what_is_missing`` in the
published TP JSON.

Historical TPs published before that commit lack the slot. This script
walks every ``output/2026-*/tp-*.json``, and for each TP that lacks a
non-empty ``what_is_missing``, derives it by invoking the Consolidator
agent once with the same input shape the live stage produces. Inputs
are read from the legacy fields that survive in published TPs:

- ``perspectives.missing_positions``  (the perspective agent's structured output)
- ``bias_analysis.selection.coverage_gaps``  (the bias agent's free-text gap strings)

The script also removes those two legacy keys plus the redundant
top-level ``consolidated_missing_coverage`` block, matching the
hard-cut policy applied to live data in the Consolidator commit.

Idempotent: a TP that already carries a non-empty
``perspectives.what_is_missing`` is skipped without an LLM call. Run
with ``--dry-run`` to preview actions without writing or invoking the
LLM. Errors on individual TPs log and continue; they do not halt the
run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Literal

# Repo root on sys.path so the script runs as `python scripts/migrate_...py`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run import create_agents  # noqa: E402

logger = logging.getLogger(__name__)

Status = Literal["skip", "migrated", "skip-empty", "error", "migrated-dry"]


def _extract_inputs(tp: dict) -> tuple[list[dict], list[str]]:
    """Return the two Consolidator inputs from a published TP, defensively
    typed. Missing or malformed fields yield empty lists."""
    perspectives = tp.get("perspectives")
    if not isinstance(perspectives, dict):
        return [], []

    missing_positions_raw = perspectives.get("missing_positions") or []
    perspective_missing_positions: list[dict] = [
        m for m in missing_positions_raw if isinstance(m, dict)
    ]

    bias = tp.get("bias_analysis")
    selection = bias.get("selection") if isinstance(bias, dict) else None
    coverage_gaps_raw = (
        selection.get("coverage_gaps") if isinstance(selection, dict) else None
    ) or []
    merged_coverage_gaps: list[str] = [
        g for g in coverage_gaps_raw if isinstance(g, str) and g
    ]

    return perspective_missing_positions, merged_coverage_gaps


def _already_migrated(tp: dict) -> bool:
    """True iff `perspectives.what_is_missing` is present and non-empty.

    Matches the brief's idempotency rule: a TP with a populated
    `what_is_missing` is treated as migrated and skipped. An empty
    `{voices_missing: [], topics_missing: []}` is treated as NOT yet
    migrated — the inputs may yield content the empty placeholder lacks.
    """
    pers = tp.get("perspectives")
    if not isinstance(pers, dict):
        return False
    wim = pers.get("what_is_missing")
    if not isinstance(wim, dict):
        return False
    voices = wim.get("voices_missing") or []
    topics = wim.get("topics_missing") or []
    return bool(voices) or bool(topics)


def _strip_legacy(tp: dict) -> None:
    """Hard-cut: remove the now-stale legacy gap fields from the TP."""
    tp.pop("consolidated_missing_coverage", None)
    bias = tp.get("bias_analysis")
    if isinstance(bias, dict):
        selection = bias.get("selection")
        if isinstance(selection, dict):
            selection.pop("coverage_gaps", None)


async def migrate_tp_file(
    path: Path,
    *,
    consolidator_agent: Any,
    dry_run: bool = False,
) -> tuple[Status, str]:
    """Migrate one TP JSON file in place. Returns (status, message).

    Status values:
      - ``skip``         : already migrated; no change
      - ``skip-empty``   : no legacy inputs to feed the Consolidator
      - ``migrated``     : LLM called, file written
      - ``migrated-dry`` : would have migrated; dry-run, no LLM call
      - ``error``        : exception during migration; file untouched
    """
    try:
        tp = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - log and continue
        return "error", f"read/parse failed: {exc}"

    if _already_migrated(tp):
        return "skip", "what_is_missing already populated"

    perspective_missing_positions, merged_coverage_gaps = _extract_inputs(tp)
    if not perspective_missing_positions and not merged_coverage_gaps:
        return "skip-empty", "no legacy inputs to migrate"

    if dry_run:
        n_mp = len(perspective_missing_positions)
        n_cg = len(merged_coverage_gaps)
        return "migrated-dry", f"would call Consolidator with mp={n_mp} cg={n_cg}"

    try:
        result = await consolidator_agent.run(
            "Classify each gap entry as a missing voice or a missing "
            "topic, deduping semantic overlaps across the two inputs.",
            context={
                "perspective_missing_positions": perspective_missing_positions,
                "merged_coverage_gaps": merged_coverage_gaps,
            },
        )
    except Exception as exc:  # noqa: BLE001 - log and continue
        return "error", f"consolidator agent raised: {exc}"

    parsed = getattr(result, "structured", None)
    if not isinstance(parsed, dict):
        content = getattr(result, "content", "") or ""
        try:
            parsed = json.loads(content) if content else None
        except Exception:  # noqa: BLE001
            parsed = None
    if not isinstance(parsed, dict):
        return "error", "consolidator returned non-dict structured output"

    voices_raw = parsed.get("voices_missing") or []
    topics_raw = parsed.get("topics_missing") or []
    voices = [s for s in voices_raw if isinstance(s, str) and s]
    topics = [s for s in topics_raw if isinstance(s, str) and s]

    pers = tp.setdefault("perspectives", {})
    if not isinstance(pers, dict):
        return "error", "tp.perspectives is not a dict"
    pers["what_is_missing"] = {
        "voices_missing": voices,
        "topics_missing": topics,
    }

    _strip_legacy(tp)

    path.write_text(
        json.dumps(tp, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return "migrated", f"wrote what_is_missing voices={len(voices)} topics={len(topics)}"


def _iter_tp_files(root: Path) -> list[Path]:
    """Every published TP JSON under output/2026-*/tp-*.json, sorted."""
    return sorted(root.glob("2026-*/tp-*.json"))


async def _async_main(dry_run: bool) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    agents = create_agents()
    consolidator = agents.get("consolidator")
    if consolidator is None:
        print("ERROR: consolidator agent not found in create_agents()", file=sys.stderr)
        return 2

    output_root = ROOT / "output"
    tp_files = _iter_tp_files(output_root)
    print(f"Migrating {len(tp_files)} TP files (dry_run={dry_run})")

    n_migrated = n_skip = n_skip_empty = n_dry = n_error = 0
    for path in tp_files:
        rel = path.relative_to(ROOT)
        status, msg = await migrate_tp_file(
            path, consolidator_agent=consolidator, dry_run=dry_run
        )
        tag = {
            "migrated": "[migrated]",
            "skip": "[skip]",
            "skip-empty": "[skip empty]",
            "migrated-dry": "[would-migrate]",
            "error": "[error]",
        }[status]
        print(f"{tag} {rel} — {msg}")
        if status == "migrated":
            n_migrated += 1
        elif status == "skip":
            n_skip += 1
        elif status == "skip-empty":
            n_skip_empty += 1
        elif status == "migrated-dry":
            n_dry += 1
        elif status == "error":
            n_error += 1

    print(
        f"\nSummary: migrated={n_migrated} skip={n_skip} "
        f"skip-empty={n_skip_empty} dry-would={n_dry} error={n_error}"
    )

    if n_error >= 3 and not dry_run:
        print(
            "\nWARN: 3 or more errors. Halt requested by brief — review "
            "before committing partial output.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill perspectives.what_is_missing into historical TPs."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report intended actions without writing or invoking the LLM.",
    )
    args = parser.parse_args()
    return asyncio.run(_async_main(dry_run=args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
