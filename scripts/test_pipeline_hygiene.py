"""Smoke test for the three post-processing hygiene fixes.

Loads the Lauf-19 T3 Topic Packages, re-runs ``_renumber_and_prune_sources``
(Fix 1), ``_convert_rsrc_to_src_in_perspectives`` (Fix 3), and the
Fix-2 duplicate-removal pattern in isolation, writes the fixed TPs under
``output/{today}/test_pipeline_hygiene/``, and asserts the structural
invariants promised by TASK-PIPELINE-HYGIENE.md.

No LLM calls. No pipeline re-run.

Usage::

    python scripts/test_pipeline_hygiene.py
    python scripts/test_pipeline_hygiene.py --date 2026-04-19

Finally, runs ``scripts/render.py`` on one of the post-fix TPs so a
render-regression shows up in the same invocation.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline import (  # noqa: E402
    _SRC_CITATION_RE,
    _collect_cited_src_ids,
    _convert_rsrc_to_src_in_perspectives,
    _renumber_and_prune_sources,
    _strip_internal_fields_from_sources,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pipeline-hygiene-smoke")

_CANONICAL_SRC_RE = re.compile(r"^src-(\d{3})$")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _inject_rsrc_id(
    tp_sources: list[dict],
    writer_refs: list[dict],
    dossier_sources: list[dict],
    slug: str,
) -> int:
    """Stash ``rsrc_id`` onto each TP source in place.

    Tries two mapping strategies in order:

    1. Writer refs. If the 05-writer debug file is the new {id, rsrc_id}
       shape (written after TASK-WRITER-SOURCES), the writer's id maps
       cleanly to the TP source id (before Fix 1 runs).
    2. Dossier by URL. T3 TPs predating TASK-WRITER-SOURCES store full
       source objects in 05-writer. The researcher dossier, available
       at ``04-researcher-{slug}.json``, carries the canonical rsrc-NNN
       ids; matching on ``url`` recovers the mapping.
    """
    refs_by_src = {
        ref["id"]: ref.get("rsrc_id")
        for ref in writer_refs or []
        if isinstance(ref, dict) and isinstance(ref.get("id"), str)
    }
    url_to_rsrc = {
        ds.get("url"): ds.get("id")
        for ds in dossier_sources or []
        if isinstance(ds, dict)
        and isinstance(ds.get("url"), str)
        and isinstance(ds.get("id"), str)
        and ds.get("id", "").startswith("rsrc-")
    }
    matched = 0
    for src in tp_sources:
        if not isinstance(src, dict):
            continue
        rsrc = None
        src_id = src.get("id")
        if src_id in refs_by_src and refs_by_src[src_id]:
            rsrc = refs_by_src[src_id]
        else:
            rsrc = url_to_rsrc.get(src.get("url"))
        if rsrc:
            src["rsrc_id"] = rsrc
            matched += 1
    log.info(
        "%s: mapped rsrc_id on %d/%d sources "
        "(writer refs + dossier URL match)",
        slug, matched, len(tp_sources),
    )
    return matched


def _apply_fixes(
    tp: dict,
    writer_refs: list[dict],
    dossier_sources: list[dict],
    slug: str,
) -> dict:
    """Run Fix 1 → Fix 3 → Fix 2 on a loaded TP. Returns a new dict."""
    fixed = copy.deepcopy(tp)

    # Inject rsrc_id onto the pre-fix sources so Fix 3 has its mapping.
    _inject_rsrc_id(
        fixed.get("sources", []), writer_refs, dossier_sources, slug,
    )

    # Fix 1 — run against the article dict (fields live under tp.article
    # in the final TP shape). The sources array is tp.sources.
    article = fixed.get("article", {})
    sources = fixed.get("sources", [])
    new_article, new_sources, rename_map = _renumber_and_prune_sources(
        article, sources, slug=slug,
    )
    fixed["article"] = new_article
    fixed["sources"] = new_sources
    # Keep article["sources"] in sync, since some renderers read from
    # article.sources[] rather than the top-level tp.sources[].
    fixed["article"]["sources"] = new_sources
    if new_article.get("body"):
        fixed["article"]["word_count"] = len(
            new_article.get("body", "").split()
        )

    # Fix 3 — convert rsrc-NNN → src-NNN in stakeholder source_ids.
    # tp.perspectives is the stakeholder list; wrap it so the helper's
    # dict-keyed API works.
    wrapped = {
        "stakeholders": fixed.get("perspectives", []),
        "missing_voices": [],
        "framing_divergences": [],
    }
    converted = _convert_rsrc_to_src_in_perspectives(
        wrapped, fixed.get("sources", []), slug=slug,
    )
    fixed["perspectives"] = converted.get("stakeholders", [])

    # Strip the internal rsrc_id stash so it does not leak into the
    # serialized TP.
    fixed["sources"] = _strip_internal_fields_from_sources(fixed["sources"])
    fixed["article"]["sources"] = _strip_internal_fields_from_sources(
        fixed["article"].get("sources", [])
    )

    # Fix 2 — duplicate-field removal. Top-level gaps becomes [];
    # transparency.framing_divergences drops out.
    fixed["gaps"] = []
    transparency = fixed.get("transparency") or {}
    if "framing_divergences" in transparency:
        transparency = {
            k: v for k, v in transparency.items()
            if k != "framing_divergences"
        }
        fixed["transparency"] = transparency

    return fixed


def _assert_post_fix_invariants(tp: dict, slug: str) -> list[str]:
    """Return a list of assertion-failure messages (empty if all pass)."""
    failures: list[str] = []

    sources = tp.get("sources") or []
    # Canonical sequential src-NNN beginning at src-001.
    expected_ids = [f"src-{i:03d}" for i in range(1, len(sources) + 1)]
    actual_ids = [s.get("id") for s in sources]
    if actual_ids != expected_ids:
        failures.append(
            f"[{slug}] source ids not sequential: got {actual_ids[:5]}... "
            f"expected {expected_ids[:5]}..."
        )

    # Canonical form check (matches src-NNN exactly).
    bad_shape = [sid for sid in actual_ids if not _CANONICAL_SRC_RE.match(sid or "")]
    if bad_shape:
        failures.append(f"[{slug}] non-canonical source ids: {bad_shape}")

    # Every cited src-NNN exists in the sources array.
    article = tp.get("article", {})
    cited = _collect_cited_src_ids(article)
    source_id_set = set(actual_ids)
    orphan_citations = sorted(cited - source_id_set)
    if orphan_citations:
        failures.append(
            f"[{slug}] citations with no source: {orphan_citations}"
        )

    # Every source is referenced at least once.
    uncited = sorted(source_id_set - cited)
    if uncited:
        failures.append(f"[{slug}] sources with no citation: {uncited}")

    # Fix 2 — no duplicates.
    transparency = tp.get("transparency") or {}
    if "framing_divergences" in transparency:
        failures.append(
            f"[{slug}] transparency.framing_divergences still present "
            f"(Fix 2 regression)"
        )
    if tp.get("gaps"):
        failures.append(
            f"[{slug}] top-level gaps non-empty (Fix 2 regression): "
            f"{len(tp['gaps'])} entries"
        )

    # Fix 3 — stakeholder source_ids use src-NNN, not rsrc-NNN.
    for stakeholder in tp.get("perspectives", []) or []:
        if not isinstance(stakeholder, dict):
            continue
        bad_rsrc = [
            sid for sid in stakeholder.get("source_ids") or []
            if isinstance(sid, str) and sid.startswith("rsrc-")
        ]
        if bad_rsrc:
            failures.append(
                f"[{slug}] stakeholder {stakeholder.get('id', '?')} "
                f"still has rsrc-NNN source_ids: {bad_rsrc}"
            )

    # Internal rsrc_id must not leak into final TP.
    leaked = [
        s.get("id") for s in sources
        if isinstance(s, dict) and "rsrc_id" in s
    ]
    if leaked:
        failures.append(
            f"[{slug}] internal rsrc_id leaked onto sources: {leaked}"
        )

    return failures


def _summarise(tp_before: dict, tp_after: dict, slug: str) -> dict:
    before_ids = [
        s.get("id") for s in tp_before.get("sources") or []
        if isinstance(s, dict)
    ]
    after_ids = [s.get("id") for s in tp_after.get("sources") or []]
    dropped = len(before_ids) - len(after_ids)
    renumbered = sum(
        1 for old, new in zip(before_ids, after_ids) if old != new
    )
    converted = 0
    total_source_ids = 0
    stakeholders_with_src = 0
    stakeholders_empty = 0
    for sh in tp_after.get("perspectives", []) or []:
        sids = sh.get("source_ids") or []
        total_source_ids += len(sids)
        if any(isinstance(s, str) and s.startswith("src-") for s in sids):
            stakeholders_with_src += 1
            converted += sum(
                1 for s in sids if isinstance(s, str) and s.startswith("src-")
            )
        if not sids:
            stakeholders_empty += 1
    return {
        "slug": slug,
        "sources_before": len(before_ids),
        "sources_after": len(after_ids),
        "dropped_unreferenced": dropped,
        "renumbered": renumbered,
        "stakeholders_total": len(tp_after.get("perspectives") or []),
        "stakeholders_with_src_ids": stakeholders_with_src,
        "stakeholders_empty_src_ids": stakeholders_empty,
        "total_source_ids_after": total_source_ids,
        "converted_to_src": converted,
    }


def _find_writer_refs(hydration_dir: Path, slug: str) -> list[dict]:
    path = hydration_dir / f"05-writer-{slug}.json"
    if not path.exists():
        log.warning(
            "%s: no 05-writer debug file; Fix 3 will have nothing to convert",
            slug,
        )
        return []
    raw = _load_json(path)
    refs = raw.get("sources", [])
    if not isinstance(refs, list):
        return []
    return refs


def _discover_tps(hydration_dir: Path) -> list[Path]:
    return sorted(hydration_dir.glob("tp-*.json"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline-hygiene smoke test on cached T3 TPs.",
    )
    parser.add_argument(
        "--date", default="2026-04-19",
        help="Source date under output/ holding the T3 TPs "
             "(default: 2026-04-19).",
    )
    args = parser.parse_args()

    hydration_dir = ROOT / "output" / args.date / "test_hydration"
    if not hydration_dir.is_dir():
        log.error("No hydrated TP dir at %s", hydration_dir)
        return 2

    tp_paths = _discover_tps(hydration_dir)
    if not tp_paths:
        log.error("No tp-*.json files under %s", hydration_dir)
        return 2
    log.info(
        "Discovered %d TP(s): %s",
        len(tp_paths), ", ".join(p.name for p in tp_paths),
    )

    today = datetime.now().strftime("%Y-%m-%d")
    output_dir = ROOT / "output" / today / "test_pipeline_hygiene"
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    all_failures: list[str] = []
    fixed_paths: list[Path] = []

    for tp_path in tp_paths:
        tp = _load_json(tp_path)
        slug = tp.get("metadata", {}).get("topic_slug") or tp_path.stem
        writer_refs = _find_writer_refs(hydration_dir, slug)
        dossier_path = hydration_dir / f"04-researcher-{slug}.json"
        dossier = _load_json(dossier_path) if dossier_path.exists() else {}
        dossier_sources = dossier.get("sources", []) if isinstance(dossier, dict) else []

        fixed = _apply_fixes(tp, writer_refs, dossier_sources, slug)

        out_path = output_dir / tp_path.name
        out_path.write_text(
            json.dumps(fixed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        fixed_paths.append(out_path)
        log.info("%s: wrote %s", slug, out_path.relative_to(ROOT))

        summaries.append(_summarise(tp, fixed, slug))
        failures = _assert_post_fix_invariants(fixed, slug)
        all_failures.extend(failures)

    # Summary
    log.info("=" * 80)
    log.info("Pipeline-hygiene smoke summary")
    log.info("=" * 80)
    for s in summaries:
        log.info("%s", s["slug"])
        log.info(
            "    sources: before=%d  after=%d  dropped=%d  renumbered=%d",
            s["sources_before"],
            s["sources_after"],
            s["dropped_unreferenced"],
            s["renumbered"],
        )
        log.info(
            "    stakeholders: total=%d  with_src_ids=%d  "
            "empty_src_ids=%d  converted_src_refs=%d",
            s["stakeholders_total"],
            s["stakeholders_with_src_ids"],
            s["stakeholders_empty_src_ids"],
            s["converted_to_src"],
        )

    if all_failures:
        log.error("=" * 80)
        log.error("STRUCTURAL ASSERTION FAILURES")
        log.error("=" * 80)
        for f in all_failures:
            log.error("  %s", f)
        return 3

    log.info("All structural assertions passed.")

    # Render at least one post-fix TP to catch regressions against the
    # schema changes (Fix 2 dropped duplicates).
    if fixed_paths:
        target = fixed_paths[0]
        log.info("Running scripts/render.py on %s", target.relative_to(ROOT))
        render_cmd = [
            sys.executable, str(ROOT / "scripts" / "render.py"), str(target),
        ]
        proc = subprocess.run(
            render_cmd, check=False, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            log.error(
                "render.py failed (rc=%d): stdout=%s stderr=%s",
                proc.returncode, proc.stdout, proc.stderr,
            )
            return 4
        html_path = target.with_suffix(".html")
        if not html_path.exists():
            log.error("render.py completed but no HTML found at %s", html_path)
            return 4
        log.info("render.py OK → %s", html_path.relative_to(ROOT))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
