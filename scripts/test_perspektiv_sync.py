"""Smoke test for the Perspektiv-Sync agent.

Replays the hydrated pipeline's post-QA step on cached Lauf-19 debug
outputs — without re-running Research / Writer / QA. For each topic with a
non-empty ``corrections_applied`` list, invokes ``perspektiv_sync`` using
the same config the hydrated pipeline constructs, writes the synced map
under ``output/{today}/test_perspektiv_sync/``, and prints a per-topic
comparison summary (stakeholder count, structural-field drift,
position_quote / position_summary change counts).

Usage::

    source .venv/bin/activate && source .env && \
        python scripts/test_perspektiv_sync.py
    python scripts/test_perspektiv_sync.py --date 2026-04-19
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent import Agent
from src.pipeline import _extract_dict, _sanitize_null_strings
from src.pipeline_hydrated import merge_perspektiv_deltas

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("perspektiv-sync-smoke")

STRUCTURAL_FIELDS = (
    "id", "actor", "type", "region", "source_ids", "representation",
)


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _discover_topics(hydration_dir: Path) -> list[str]:
    """Find topic slugs that have all three required debug files."""
    slugs: list[str] = []
    for perspektiv_path in sorted(hydration_dir.glob("04b-perspektiv-*.json")):
        slug = perspektiv_path.stem[len("04b-perspektiv-"):]
        qa_path = hydration_dir / f"06-qa-analyze-{slug}.json"
        if qa_path.exists():
            slugs.append(slug)
    return slugs


def _make_sync_agent() -> Agent:
    """Mirror of the default registered in ``PipelineHydrated.__init__``."""
    agents_dir = ROOT / "agents"
    return Agent(
        name="perspektiv_sync",
        model="anthropic/claude-opus-4.6",
        prompt_path=str(agents_dir / "perspektiv_sync" / "AGENTS.md"),
        tools=[],
        temperature=0.1,
        max_tokens=16384,
        provider="openrouter",
        reasoning="none",
    )


def _diff_stakeholder(
    original: dict, synced: dict,
) -> tuple[list[str], bool, bool]:
    """Return (structural_field_mismatches, quote_changed, summary_changed)."""
    mismatched: list[str] = []
    for field in STRUCTURAL_FIELDS:
        if original.get(field) != synced.get(field):
            mismatched.append(field)
    quote_changed = (
        original.get("position_quote") != synced.get("position_quote")
    )
    summary_changed = (
        original.get("position_summary") != synced.get("position_summary")
    )
    return mismatched, quote_changed, summary_changed


async def _sync_topic(
    slug: str,
    hydration_dir: Path,
    output_dir: Path,
    agent: Agent,
) -> dict:
    """Run one topic through the sync agent. Returns a summary dict."""
    summary: dict = {"slug": slug, "status": "unknown"}

    original_map = _load_json(hydration_dir / f"04b-perspektiv-{slug}.json")
    qa_output = _load_json(hydration_dir / f"06-qa-analyze-{slug}.json")

    if not original_map or not isinstance(original_map, dict):
        log.warning("%s: missing or unreadable 04b-perspektiv file", slug)
        summary["status"] = "missing_perspektiv"
        return summary
    if not qa_output or not isinstance(qa_output, dict):
        log.warning("%s: missing or unreadable 06-qa-analyze file", slug)
        summary["status"] = "missing_qa"
        return summary

    corrections = qa_output.get("corrections_applied") or []
    problems = qa_output.get("problems_found") or []
    summary["corrections"] = len(corrections)
    summary["problems"] = len(problems)
    summary["stakeholders_original"] = len(
        original_map.get("stakeholders", [])
    )

    if not corrections:
        log.info(
            "%s: SKIP — QA applied no corrections (no sync call made)", slug,
        )
        summary["status"] = "skipped_no_corrections"
        return summary

    qa_article = qa_output.get("article") or {}
    if not qa_article.get("body"):
        log.warning(
            "%s: QA output has no article.body; cannot build sync input",
            slug,
        )
        summary["status"] = "missing_corrected_article"
        return summary

    sync_context = {
        "original_perspectives": original_map,
        "corrected_article": {
            "headline": qa_article.get("headline", ""),
            "subheadline": qa_article.get("subheadline", ""),
            "body": qa_article.get("body", ""),
            "summary": qa_article.get("summary", ""),
        },
        "qa_corrections": {
            "problems_found": problems,
            "corrections_applied": corrections,
        },
    }

    log.info(
        "%s: calling perspektiv_sync (corrections=%d, problems=%d)",
        slug, len(corrections), len(problems),
    )
    try:
        result = await agent.run(
            "Synchronize the stakeholder map with the QA-corrected article. "
            "Update position_quote and position_summary for stakeholders "
            "affected by QA corrections; pass every other field through "
            "unchanged.",
            context=sync_context,
        )
    except Exception as exc:
        log.error("%s: agent call raised %s", slug, exc)
        summary["status"] = "agent_error"
        summary["error"] = str(exc)
        return summary

    summary["tokens_used"] = getattr(result, "tokens_used", 0)
    summary["cost_usd"] = getattr(result, "cost_usd", None)

    delta = _extract_dict(result)
    if not delta:
        log.error("%s: sync output unparseable", slug)
        summary["status"] = "parse_error"
        return summary

    if "stakeholder_updates" not in delta:
        log.error("%s: sync output missing 'stakeholder_updates'", slug)
        summary["status"] = "schema_error"
        summary["missing_fields"] = ["stakeholder_updates"]
        return summary

    updates = delta.get("stakeholder_updates")
    if not isinstance(updates, list):
        log.error(
            "%s: sync output 'stakeholder_updates' is %s, not a list",
            slug, type(updates).__name__,
        )
        summary["status"] = "schema_error"
        summary["bad_type"] = type(updates).__name__
        return summary

    delta = _sanitize_null_strings(delta)
    summary["delta_entries"] = len(delta.get("stakeholder_updates") or [])

    delta_out = output_dir / f"04c-perspektiv-sync-{slug}-delta.json"
    delta_out.write_text(
        json.dumps(delta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("%s: wrote %s", slug, delta_out.relative_to(ROOT))

    synced = merge_perspektiv_deltas(original_map, delta, slug=slug)
    summary["stakeholders_synced"] = len(synced.get("stakeholders", []))

    sync_out = output_dir / f"04c-perspektiv-sync-{slug}.json"
    sync_out.write_text(
        json.dumps(synced, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("%s: wrote %s", slug, sync_out.relative_to(ROOT))

    # Comparison
    original_by_id = {
        sh.get("id"): sh
        for sh in original_map.get("stakeholders", [])
        if isinstance(sh, dict)
    }
    synced_by_id = {
        sh.get("id"): sh
        for sh in synced.get("stakeholders", [])
        if isinstance(sh, dict)
    }

    lost_ids = sorted(set(original_by_id) - set(synced_by_id))
    gained_ids = sorted(set(synced_by_id) - set(original_by_id))
    structural_drifts: list[tuple[str, list[str]]] = []
    quote_changes = 0
    summary_changes = 0
    for sh_id, original in original_by_id.items():
        synced_sh = synced_by_id.get(sh_id)
        if synced_sh is None:
            continue
        drifts, q_changed, s_changed = _diff_stakeholder(
            original, synced_sh,
        )
        if drifts:
            structural_drifts.append((sh_id, drifts))
        if q_changed:
            quote_changes += 1
        if s_changed:
            summary_changes += 1

    mv_identical = (
        original_map.get("missing_voices")
        == synced.get("missing_voices")
    )
    fd_identical = (
        original_map.get("framing_divergences")
        == synced.get("framing_divergences")
    )

    summary["status"] = "synced"
    summary["lost_ids"] = lost_ids
    summary["gained_ids"] = gained_ids
    summary["structural_drifts"] = structural_drifts
    summary["position_quote_changes"] = quote_changes
    summary["position_summary_changes"] = summary_changes
    summary["missing_voices_identical"] = mv_identical
    summary["framing_divergences_identical"] = fd_identical
    return summary


def _print_summary(topic_summaries: list[dict]) -> None:
    log.info("=" * 80)
    log.info("Perspektiv-Sync smoke summary")
    log.info("=" * 80)
    for s in topic_summaries:
        slug = s["slug"]
        status = s["status"]
        header = f"{slug}  [{status}]"
        log.info(header)
        if status == "skipped_no_corrections":
            log.info("    corrections=0; sync skipped as expected")
            continue
        if status == "synced":
            log.info(
                "    delta entries returned by agent: %d",
                s.get("delta_entries", 0),
            )
            log.info(
                "    stakeholders: original=%d  synced=%d  "
                "(lost=%d  gained=%d)",
                s["stakeholders_original"],
                s["stakeholders_synced"],
                len(s["lost_ids"]),
                len(s["gained_ids"]),
            )
            log.info(
                "    position_quote changes: %d   "
                "position_summary changes: %d",
                s["position_quote_changes"],
                s["position_summary_changes"],
            )
            log.info(
                "    structural field drifts: %d",
                len(s["structural_drifts"]),
            )
            if s["structural_drifts"]:
                for sh_id, fields in s["structural_drifts"]:
                    log.info("        %s: %s", sh_id, ", ".join(fields))
            log.info(
                "    missing_voices byte-identical: %s   "
                "framing_divergences byte-identical: %s",
                s["missing_voices_identical"],
                s["framing_divergences_identical"],
            )
            if s.get("cost_usd") is not None:
                log.info(
                    "    tokens=%d  cost_usd=%.4f",
                    s.get("tokens_used", 0), s["cost_usd"],
                )
            else:
                log.info("    tokens=%d", s.get("tokens_used", 0))
        else:
            log.info("    problem: %s", s)


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Perspektiv-Sync smoke test on cached hydrated debug outputs.",
    )
    parser.add_argument(
        "--date", default="2026-04-19",
        help="Source date directory under output/ (default: 2026-04-19).",
    )
    args = parser.parse_args()

    hydration_dir = ROOT / "output" / args.date / "test_hydration"
    if not hydration_dir.is_dir():
        log.error("No hydrated debug dir at %s", hydration_dir)
        return 2

    slugs = _discover_topics(hydration_dir)
    if not slugs:
        log.error("No topic slugs found under %s", hydration_dir)
        return 2
    log.info("Discovered %d topic(s): %s", len(slugs), ", ".join(slugs))

    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = ROOT / "output" / today / "test_perspektiv_sync"
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Writing synced outputs to %s", output_dir.relative_to(ROOT))

    agent = _make_sync_agent()

    topic_summaries: list[dict] = []
    for slug in slugs:
        summary = await _sync_topic(slug, hydration_dir, output_dir, agent)
        topic_summaries.append(summary)

    _print_summary(topic_summaries)

    # Non-zero exit if any structural drift is observed.
    hard_failures = [
        s for s in topic_summaries
        if s["status"] == "synced" and (
            s["lost_ids"]
            or s["gained_ids"]
            or s["structural_drifts"]
        )
    ]
    if hard_failures:
        log.error(
            "STRUCTURAL DRIFT detected on %d topic(s) — agent exceeded scope",
            len(hard_failures),
        )
        return 3

    any_changes = any(
        s["status"] == "synced"
        and (s["position_quote_changes"] or s["position_summary_changes"])
        for s in topic_summaries
    )
    if not any_changes:
        log.warning(
            "No position_quote / position_summary changes observed across "
            "any synced topic — investigate whether the agent is seeing "
            "qa_corrections correctly."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
