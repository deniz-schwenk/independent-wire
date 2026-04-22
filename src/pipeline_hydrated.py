"""Independent Wire — Hydrated pipeline (Etappe 2).

Parallel subclass of :class:`src.pipeline.Pipeline`. Produces Topic Packages
using the same downstream agents as production (Perspektiv, Writer, QA+Fix,
Bias Language) but constructs the research dossier from two paths, merged:

1. **Hydration path.** Direct HTTP fetch of Curator-clustered article URLs via
   ``src.hydration.hydrate_urls``, followed by the Hydration Aggregator LLM
   and the pre-dossier shaping in ``src.hydration_aggregator``.
2. **Gap-aware web-search path.** The same two-phase Researcher as production,
   driven by ``agents/researcher_hydrated/PLAN.md`` (which sees the
   pre-dossier's coverage summary) and with search results filtered to
   exclude URLs already captured by hydration.

The two dossiers are merged via ``src.hydration_aggregator.merge_dossiers``
before the merged dossier is handed to Perspektiv. All other steps are
inherited unchanged.

**Input convention.** The caller (typically
``scripts/test_hydration_pipeline.py``) attaches per-topic URL lists to
``assignment.raw_data["hydration_urls"]`` — a list of dicts with at least
``url``, ``outlet``, ``language``, ``country``. Resolving those from the
Curator clusters and feeds.json is the orchestrator's job, not the pipeline's.

**Debug output.** All per-topic artifacts produced by this pipeline — fetch
results, pre-dossier, coverage summary, queries, filtered search results,
merged dossier, plus the downstream Perspektiv / Writer / QA / Bias dumps —
are written under ``output/{date}/test_hydration/`` rather than
``output/{date}/`` so production debug outputs are never clobbered.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from src.agent import Agent
from src.hydration import hydrate_urls
from src.hydration_aggregator import (
    build_coverage_summary,
    build_prepared_dossier,
    merge_dossiers,
    run_aggregator,
)
from src.models import TopicAssignment, TopicPackage
from src.pipeline import (
    Pipeline,
    PipelineStepError,
    _build_bias_card,
    _convert_rsrc_to_src_in_perspectives,
    _deduplicate_search_results,
    _extract_date_from_url,
    _extract_dict,
    _extract_list,
    _merge_writer_sources,
    _normalise_country,
    _normalise_language,
    _renumber_and_prune_sources,
    _sanitize_null_strings,
    _strip_internal_fields_from_sources,
    _substitute_coverage_statement,
)
from dataclasses import asdict

logger = logging.getLogger(__name__)


# Numbered-plaintext format emitted by the Brave/DDG branches of
# ``web_search_tool`` via ``_format_results``:
#     1. title
#        url
#        snippet
# One entry per block, separated by blank lines. Title and snippet are
# single-line (no embedded newlines) — ``[^\n]+`` avoids the greedy-DOTALL
# trap that would swallow whole entries into one match.
_NUMBERED_ENTRY = re.compile(
    r"^(\d+)\.\s+([^\n]+)\n\s{3}(https?://\S+)(?:\n\s{3}([^\n]+))?",
    re.MULTILINE,
)


def _canonical_url(url: str) -> str:
    """Normalise a URL for blocklist membership checks.

    Perplexity-returned URLs frequently lack querystrings that the original
    RSS URL carried, or vice versa; YouTube / social-media links are
    distinguishable by scheme+host+path. We compare on
    scheme+netloc+path+query (no fragment) — exact by default, with a
    fallback to scheme+netloc+path for near-misses.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    base = f"{parts.scheme}://{parts.netloc.lower()}{parts.path}"
    if parts.query:
        return f"{base}?{parts.query}"
    return base


def _blocklist_keys(urls: set[str]) -> set[str]:
    """Build the membership set with canonical and path-only variants."""
    keys: set[str] = set()
    for url in urls:
        if not url:
            continue
        keys.add(url)
        canon = _canonical_url(url)
        keys.add(canon)
        # Path-only fallback: same host + path, query stripped. Handles
        # cases where Perplexity drops "?traffic_source=rss" style suffixes.
        parts = urlsplit(canon)
        if parts.scheme and parts.netloc:
            keys.add(f"{parts.scheme}://{parts.netloc.lower()}{parts.path}")
    return keys


def _is_blocked(url: str, keys: set[str]) -> bool:
    if not url:
        return False
    if url in keys:
        return True
    canon = _canonical_url(url)
    if canon in keys:
        return True
    parts = urlsplit(canon)
    if parts.scheme and parts.netloc:
        path_only = f"{parts.scheme}://{parts.netloc.lower()}{parts.path}"
        if path_only in keys:
            return True
    return False


def _filter_json_array(raw: str, keys: set[str]) -> tuple[str, int] | None:
    """If ``raw`` is a JSON array of {title, url, content}, filter in place."""
    stripped = raw.strip()
    # Strip leading/trailing code fences if present.
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    try:
        items = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(items, list):
        return None
    kept = [
        item for item in items
        if isinstance(item, dict) and not _is_blocked(item.get("url", ""), keys)
    ]
    dropped = len(items) - len(kept)
    if dropped == 0:
        return raw, 0
    return json.dumps(kept, indent=2, ensure_ascii=False), dropped


def _filter_numbered(raw: str, keys: set[str]) -> tuple[str, int] | None:
    """If ``raw`` is numbered-plaintext search output, filter in place."""
    matches = list(_NUMBERED_ENTRY.finditer(raw))
    if not matches:
        return None
    header_match = re.match(r"^(Results for:[^\n]*)", raw)
    header = header_match.group(1) if header_match else "Results for:"
    kept: list[str] = []
    dropped = 0
    entry_num = 1
    for match in matches:
        url = match.group(3).strip()
        if _is_blocked(url, keys):
            dropped += 1
            continue
        title = match.group(2).strip()
        snippet = (match.group(4) or "").strip()
        block = f"{entry_num}. {title}\n   {url}"
        if snippet:
            block += f"\n   {snippet}"
        kept.append(block)
        entry_num += 1
    if dropped == 0:
        return raw, 0
    if not kept:
        return f"{header}\n\nNo results after blocklist filter.", dropped
    return f"{header}\n\n" + "\n\n".join(kept), dropped


def _filter_blocklisted_urls(
    search_results: list[dict],
    blocklist: set[str],
) -> tuple[list[dict], int]:
    """Drop entries whose URL matches anything in ``blocklist``.

    Handles both the JSON-array format produced by Perplexity (the default
    web-search provider) and the numbered-plaintext format produced by
    Brave/DuckDuckGo. For unrecognised formats, passes the block through
    unchanged — ``merge_dossiers`` is the structural backstop.

    Returns the rewritten search_results list plus the total number of
    entries dropped across all blocks.
    """
    keys = _blocklist_keys(blocklist)
    filtered: list[dict] = []
    total_dropped = 0
    for sr in search_results:
        raw = sr.get("results", "")
        if not isinstance(raw, str) or not raw.strip():
            filtered.append(sr)
            continue

        outcome = _filter_json_array(raw, keys)
        if outcome is None:
            outcome = _filter_numbered(raw, keys)
        if outcome is None:
            # Unknown format — keep as-is so the assembler still sees it.
            filtered.append(sr)
            continue

        new_raw, dropped = outcome
        total_dropped += dropped
        new_entry = dict(sr)
        new_entry["results"] = new_raw
        filtered.append(new_entry)
    return filtered, total_dropped


def merge_perspektiv_deltas(
    original_perspectives: dict,
    sync_output: dict,
    slug: str = "",
) -> dict:
    """Apply ``stakeholder_updates`` deltas into a deep copy of the map.

    Perspektiv-Sync V3 emits only deltas. Python owns the merge so
    ``missing_voices`` and ``framing_divergences`` pass through from
    ``original_perspectives`` untouched.

    Delta semantics, per the Perspektiv-Sync V3 prompt:

    * Field **present** in a delta entry (even with value ``None``) →
      overwrite on the matched stakeholder. ``position_quote: null``
      removes the quote.
    * Field **absent** → leave the stakeholder field unchanged. Presence
      is tested with ``in``, not ``.get() is None``.
    * Delta ``id`` with no match in the original map → log a warning and
      skip that entry. Do not raise.
    """
    synced = copy.deepcopy(original_perspectives)
    updates = sync_output.get("stakeholder_updates") or []

    stakeholders_by_id: dict[str, dict] = {}
    for sh in synced.get("stakeholders", []) or []:
        if isinstance(sh, dict):
            sid = sh.get("id")
            if isinstance(sid, str) and sid:
                stakeholders_by_id[sid] = sh

    for entry in updates:
        if not isinstance(entry, dict):
            logger.warning(
                "PipelineHydrated[%s]: skipping non-dict delta entry %r",
                slug, entry,
            )
            continue
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            logger.warning(
                "PipelineHydrated[%s]: skipping delta entry with no id: %r",
                slug, entry,
            )
            continue
        target = stakeholders_by_id.get(entry_id)
        if target is None:
            logger.warning(
                "PipelineHydrated[%s]: delta id=%s not found in original "
                "stakeholder map; skipping",
                slug, entry_id,
            )
            continue
        if "position_quote" in entry:
            target["position_quote"] = entry["position_quote"]
        if "position_summary" in entry:
            target["position_summary"] = entry["position_summary"]

    return synced


class PipelineHydrated(Pipeline):
    """Hydration-first parallel pipeline. See module docstring."""

    # ---- agent auto-registration -------------------------------------

    def __init__(self, *args, **kwargs) -> None:
        """Ensure a ``perspektiv_sync`` Agent is present in ``self.agents``.

        The hydrated pipeline inserts a Perspektiv-Sync step between QA+Fix
        and coverage-statement substitution to re-align the stakeholder map
        with the QA-corrected article body. If the orchestrator already
        registered a ``perspektiv_sync`` agent, the pre-registered instance
        wins; otherwise an Opus-4.6 default matching the Perspektiv /
        Bias-Language configuration is constructed here.
        """
        super().__init__(*args, **kwargs)
        if "perspektiv_sync" not in self.agents:
            agents_dir = Path(__file__).resolve().parent.parent / "agents"
            self.agents["perspektiv_sync"] = Agent(
                name="perspektiv_sync",
                model="anthropic/claude-opus-4.6",
                prompt_path=str(agents_dir / "perspektiv_sync" / "AGENTS.md"),
                tools=[],
                temperature=0.1,
                provider="openrouter",
                reasoning="none",
            )

    # ---- debug-output routing ----------------------------------------

    def _write_debug_output(self, filename: str, data: object) -> None:
        """Route all debug writes under ``output/{date}/test_hydration/``."""
        if self.state is None:
            return
        out = Path(self.output_dir) / self.state.date / "test_hydration"
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---- overridden research step ------------------------------------

    async def _research_two_phase(
        self,
        assignment_data: dict,
        slug: str,
    ) -> dict:
        """Hydration + gap-aware web search, merged into one dossier."""
        raw_data = assignment_data.get("raw_data") or {}
        hydration_urls: list[dict] = list(raw_data.get("hydration_urls") or [])
        if not hydration_urls:
            logger.warning(
                "PipelineHydrated[%s]: no hydration_urls provided; "
                "pre-dossier will be empty",
                slug,
            )

        # --- 1. T1: fetch + extract -----------------------------------
        logger.info(
            "PipelineHydrated[%s]: hydrating %d URLs",
            slug, len(hydration_urls),
        )
        hydration_results = (
            await hydrate_urls(hydration_urls) if hydration_urls else []
        )
        self._write_debug_output(
            f"04a-hydration-fetch-{slug}.json", hydration_results,
        )
        successes = sum(1 for r in hydration_results if r.get("status") == "success")
        logger.info(
            "PipelineHydrated[%s]: %d/%d hydration successes",
            slug, successes, len(hydration_results),
        )

        # --- 2. T2: aggregator → prepared dossier → coverage ----------
        aggregator_agent = self.agents.get("hydration_aggregator")
        aggregator_output = await run_aggregator(
            {
                "title": assignment_data.get("title", ""),
                "selection_reason": assignment_data.get("selection_reason", ""),
            },
            hydration_results,
            agent=aggregator_agent,
        )
        # run_aggregator encapsulates the Agent.run() call, so token usage is
        # logged by the Agent itself but not surfaced to _agent_stats here.

        pre_dossier = build_prepared_dossier(hydration_results, aggregator_output)
        self._write_debug_output(
            f"04b-hydration-pre-dossier-{slug}.json", pre_dossier,
        )
        coverage_summary = build_coverage_summary(pre_dossier)
        self._write_debug_output(
            f"04c-hydration-coverage-{slug}.json", coverage_summary,
        )
        logger.info(
            "PipelineHydrated[%s]: pre-dossier has %d sources, %d divergences, %d gaps",
            slug,
            len(pre_dossier.get("sources", [])),
            len(pre_dossier.get("preliminary_divergences", [])),
            len(pre_dossier.get("coverage_gaps", [])),
        )

        # --- 3. Hydrated planner --------------------------------------
        planner = self.agents.get("researcher_hydrated_plan")
        if not planner:
            logger.error(
                "PipelineHydrated[%s]: no 'researcher_hydrated_plan' agent "
                "configured; returning pre-dossier only",
                slug,
            )
            self._write_debug_output(f"04-researcher-{slug}.json", pre_dossier)
            self._write_debug_output(
                f"04d-hydration-merged-{slug}.json", pre_dossier,
            )
            return pre_dossier

        plan_context = {
            "title": assignment_data.get("title", ""),
            "selection_reason": assignment_data.get("selection_reason", ""),
            "raw_data": raw_data,
            "coverage_summary": coverage_summary,
        }
        plan_result = await planner.run(
            f"Plan multilingual research queries for this topic. "
            f"Today is {self.state.date}.",
            context=plan_context,
            output_schema={"type": "array", "items": {"type": "object"}},
        )
        self._track_agent(plan_result, "researcher_hydrated_plan", slug)
        queries = plan_result.structured
        if not queries or not isinstance(queries, list):
            queries = _extract_list(plan_result) or []
        if not queries:
            logger.warning(
                "PipelineHydrated[%s]: hydrated planner returned no queries; "
                "returning pre-dossier only",
                slug,
            )
            self._write_debug_output(f"04-researcher-{slug}.json", pre_dossier)
            self._write_debug_output(
                f"04d-hydration-merged-{slug}.json", pre_dossier,
            )
            return pre_dossier

        languages = {q.get("language", "en") for q in queries}
        logger.info(
            "PipelineHydrated[%s]: %d queries across %d languages",
            slug, len(queries), len(languages),
        )
        self._write_debug_output(f"04-researcher-plan-{slug}.json", queries)

        # --- 4. Web search (Python, no LLM) ---------------------------
        from src.tools import web_search_tool

        search_results: list[dict] = []
        for q in queries:
            query_str = q.get("query", "")
            if not query_str:
                continue
            try:
                text = await web_search_tool.execute(query=query_str)
                search_results.append({
                    "query": query_str,
                    "language": q.get("language", "en"),
                    "results": text,
                })
            except Exception as exc:
                logger.warning(
                    "PipelineHydrated[%s]: web-search failed for %r: %s",
                    slug, query_str, exc,
                )
                search_results.append({
                    "query": query_str,
                    "language": q.get("language", "en"),
                    "results": f"Error: {exc}",
                })
        successful_searches = sum(
            1 for r in search_results
            if not r["results"].startswith("Error")
        )
        logger.info(
            "PipelineHydrated[%s]: %d/%d queries returned web results",
            slug, successful_searches, len(search_results),
        )

        # Deduplicate by URL (same as production).
        search_results = _deduplicate_search_results(search_results)

        # --- 5. Blocklist filter: drop URLs already in pre-dossier ----
        blocklist: set[str] = {
            s.get("url") for s in pre_dossier.get("sources", [])
            if s.get("url")
        }
        search_results, dropped = _filter_blocklisted_urls(
            search_results, blocklist,
        )
        if dropped:
            logger.info(
                "PipelineHydrated[%s]: blocklist filter dropped %d web-search "
                "entries already in pre-dossier",
                slug, dropped,
            )

        # Enrich with url_dates (mirrors production behavior).
        url_pattern = re.compile(r"^\s{3}(https?://\S+)", re.MULTILINE)
        for sr in search_results:
            raw = sr.get("results", "")
            urls_with_dates: list[dict] = []
            for match in url_pattern.finditer(raw):
                url = match.group(1)
                est_date = _extract_date_from_url(url)
                if est_date:
                    urls_with_dates.append({
                        "url": url,
                        "estimated_date": est_date,
                    })
            if urls_with_dates:
                sr["url_dates"] = urls_with_dates

        self._write_debug_output(
            f"04-researcher-search-{slug}.json", search_results,
        )

        # --- 6. Researcher Assembler (unchanged prompt) ---------------
        assembler = self.agents.get("researcher_assemble")
        if not assembler:
            logger.error(
                "PipelineHydrated[%s]: no 'researcher_assemble' agent "
                "configured; returning pre-dossier only",
                slug,
            )
            self._write_debug_output(f"04-researcher-{slug}.json", pre_dossier)
            self._write_debug_output(
                f"04d-hydration-merged-{slug}.json", pre_dossier,
            )
            return pre_dossier

        assemble_result = await assembler.run(
            "Build a research dossier from these search results. "
            "Extract sources, actors, divergences, and coverage gaps.",
            context={
                "assignment": {
                    "title": assignment_data.get("title", ""),
                    "selection_reason": assignment_data.get("selection_reason", ""),
                },
                "date": self.state.date,
                "search_results": search_results,
            },
        )
        self._track_agent(assemble_result, "researcher_assemble", slug)
        web_dossier = _extract_dict(assemble_result) or {}

        # Old-source check (mirrors production's warning behavior).
        if web_dossier and self.state:
            try:
                run_date = datetime.strptime(self.state.date, "%Y-%m-%d")
            except ValueError:
                run_date = None
            if run_date is not None:
                for source in web_dossier.get("sources", []):
                    url = source.get("url", "")
                    est_date_str = (
                        source.get("estimated_date")
                        or _extract_date_from_url(url)
                    )
                    if not est_date_str:
                        continue
                    try:
                        est_date = datetime.strptime(est_date_str, "%Y-%m-%d")
                    except ValueError:
                        continue
                    age_days = (run_date - est_date).days
                    if age_days > 30:
                        logger.warning(
                            "Old web-search source in '%s': %s (%s, %d days old)",
                            slug, source.get("outlet", ""),
                            est_date_str, age_days,
                        )
                    if not source.get("estimated_date"):
                        source["estimated_date"] = est_date_str

        logger.info(
            "PipelineHydrated[%s]: web-search dossier has %d sources",
            slug, len(web_dossier.get("sources", [])),
        )

        # --- 7. Merge via T2 -----------------------------------------
        merged = merge_dossiers(pre_dossier, web_dossier)

        # Normalise None → "" on fields that production's inherited
        # ``_build_bias_card`` sorts across sources. T1 / T2 intentionally
        # allow ``country`` and ``language`` to be None when the feed
        # catalogue (config/sources.json) has no entry, but Python can't
        # compare None to str in a sorted() call. Coerce here, at the
        # seam, rather than changing T1/T2 contracts or production code.
        for source in merged.get("sources", []):
            if source.get("country") is None:
                source["country"] = ""
            if source.get("language") is None:
                source["language"] = ""

        self._write_debug_output(f"04-researcher-{slug}.json", merged)
        self._write_debug_output(f"04d-hydration-merged-{slug}.json", merged)
        logger.info(
            "PipelineHydrated[%s]: merged dossier has %d sources "
            "(%d pre-dossier + %d web-search after blocklist)",
            slug,
            len(merged.get("sources", [])),
            len(pre_dossier.get("sources", [])),
            len(merged.get("sources", []))
            - len(pre_dossier.get("sources", [])),
        )
        return merged

    # ---- perspektiv-sync step ---------------------------------------

    async def _run_perspektiv_sync(
        self,
        perspective_analysis: dict,
        article: dict,
        qa_analysis: dict,
        slug: str,
    ) -> dict:
        """Re-align the stakeholder map with the QA-corrected article body.

        Eligibility gate: skipped when ``qa_analysis.corrections_applied``
        is empty — the map is already in sync with the article. Any
        agent-call failure, parse failure, or schema-violation falls back
        to the original ``perspective_analysis`` so TP assembly continues.
        """
        corrections = qa_analysis.get("corrections_applied") or []
        if not corrections:
            logger.info(
                "PipelineHydrated[%s]: perspektiv-sync skipped — "
                "QA applied no corrections",
                slug,
            )
            return perspective_analysis

        sync_agent = self.agents.get("perspektiv_sync")
        if not sync_agent:
            logger.warning(
                "PipelineHydrated[%s]: perspektiv-sync agent not registered; "
                "keeping original perspectives map",
                slug,
            )
            return perspective_analysis

        sync_context = {
            "original_perspectives": perspective_analysis,
            "corrected_article": {
                "headline": article.get("headline", ""),
                "subheadline": article.get("subheadline", ""),
                "body": article.get("body", ""),
                "summary": article.get("summary", ""),
            },
            "qa_corrections": {
                "problems_found": qa_analysis.get("problems_found", []),
                "corrections_applied": corrections,
            },
        }

        try:
            result = await sync_agent.run(
                "Synchronize the stakeholder map with the QA-corrected article. "
                "Update position_quote and position_summary for stakeholders "
                "affected by QA corrections; pass every other field through "
                "unchanged.",
                context=sync_context,
            )
        except Exception as exc:
            logger.warning(
                "PipelineHydrated[%s]: perspektiv-sync call raised %s; "
                "keeping original perspectives map",
                slug, exc,
            )
            return perspective_analysis

        self._track_agent(result, "perspektiv_sync", slug)
        delta = _extract_dict(result)
        if not delta:
            if getattr(result, "content", None):
                self._log_raw_on_parse_failure(
                    result, "Perspektiv-Sync", slug, "04c-perspektiv-sync",
                )
            logger.warning(
                "PipelineHydrated[%s]: perspektiv-sync returned "
                "unparseable response; keeping original perspectives map",
                slug,
            )
            return perspective_analysis

        if "stakeholder_updates" not in delta:
            logger.warning(
                "PipelineHydrated[%s]: perspektiv-sync output missing "
                "'stakeholder_updates'; keeping original perspectives map",
                slug,
            )
            return perspective_analysis

        updates = delta.get("stakeholder_updates")
        if not isinstance(updates, list):
            logger.warning(
                "PipelineHydrated[%s]: perspektiv-sync 'stakeholder_updates' "
                "is %s, not a list; keeping original perspectives map",
                slug, type(updates).__name__,
            )
            return perspective_analysis

        if not updates:
            logger.info(
                "PipelineHydrated[%s]: perspektiv-sync ran but reported "
                "no stakeholder changes (%d corrections considered)",
                slug, len(corrections),
            )
            return perspective_analysis

        delta = _sanitize_null_strings(delta)
        synced = merge_perspektiv_deltas(
            perspective_analysis, delta, slug=slug,
        )
        self._write_debug_output(f"04c-perspektiv-sync-{slug}.json", synced)
        logger.info(
            "PipelineHydrated[%s]: perspektiv-sync applied "
            "(%d stakeholder updates merged, %d corrections considered)",
            slug,
            len(delta.get("stakeholder_updates") or []),
            len(corrections),
        )
        return synced

    # ---- overridden per-topic production ----------------------------

    async def _produce_single(
        self,
        assignment: TopicAssignment,
        preloaded_dossier: dict | None = None,
        preloaded_article: dict | None = None,
        skip_perspektiv: bool = False,
        to_step: str | None = None,
        preloaded_perspectives: dict | None = None,
    ) -> TopicPackage:
        """Hydrated-pipeline variant of :meth:`Pipeline._produce_single`.

        The body mirrors the parent implementation verbatim except for one
        inserted step: after QA+Fix applies corrections and before the
        ``[[COVERAGE_STATEMENT]]`` placeholder is substituted, the
        Perspektiv-Sync agent re-aligns the stakeholder map with the
        corrected article. The synchronized map replaces
        ``perspective_analysis`` for downstream use (bias card, TP
        assembly). Any change to the parent ``_produce_single`` must be
        mirrored here.
        """
        import asyncio

        assignment_data = asdict(assignment)
        article: dict = {}
        bias_analysis: dict = {}

        slug = assignment.topic_slug or assignment.id

        # 2. Research Agent — two-phase: plan → search → assemble
        research_dossier: dict = {}
        if preloaded_dossier is not None:
            research_dossier = preloaded_dossier
            logger.info(
                "Using preloaded researcher dossier for '%s'",
                assignment.title,
            )
        else:
            research_dossier = await self._research_two_phase(
                assignment_data, slug,
            )

        if to_step == "researcher":
            return TopicPackage(
                id=assignment.id,
                metadata={
                    "title": assignment.title,
                    "date": self.state.date if self.state else "",
                    "status": "partial",
                    "topic_slug": assignment.topic_slug,
                    "stopped_at": "researcher",
                },
                status="partial",
            )

        if research_dossier and preloaded_dossier is None:
            logger.info("Waiting 10s after researcher...")
            await asyncio.sleep(10)

        # 2b. Perspective Agent (stakeholder mapping, no tools)
        perspective_analysis: dict = preloaded_perspectives or {}
        if preloaded_perspectives:
            logger.info(
                "Using preloaded perspektiv data for '%s'",
                assignment.title,
            )
        elif (
            not skip_perspektiv
            and preloaded_article is None
            and research_dossier
        ):
            if perspektiv := self.agents.get("perspektiv"):
                perspektiv_context = {
                    "title": assignment.title,
                    "selection_reason": assignment.selection_reason,
                    "sources": research_dossier.get("sources", []),
                    "preliminary_divergences": research_dossier.get(
                        "preliminary_divergences", []
                    ),
                    "coverage_gaps": research_dossier.get("coverage_gaps", []),
                }
                result = await perspektiv.run(
                    "Analyze the research dossier. Map all stakeholders, "
                    "identify missing voices, and surface framing "
                    "divergences between regions and language groups.",
                    context=perspektiv_context,
                )
                perspective_analysis = _extract_dict(result) or {}
                if perspective_analysis:
                    perspective_analysis = _sanitize_null_strings(
                        perspective_analysis
                    )
                self._track_agent(result, "perspektiv", slug)
                if not perspective_analysis and result.content:
                    self._log_raw_on_parse_failure(
                        result, "Perspektiv", slug, "04b-perspektiv",
                    )
                self._write_debug_output(
                    f"04b-perspektiv-{slug}.json", perspective_analysis,
                )

                await asyncio.sleep(5)

        if to_step == "perspektiv":
            return TopicPackage(
                id=assignment.id,
                metadata={
                    "title": assignment.title,
                    "date": self.state.date if self.state else "",
                    "status": "partial",
                    "topic_slug": assignment.topic_slug,
                    "stopped_at": "perspektiv",
                },
                perspectives=perspective_analysis.get("stakeholders", []),
                gaps=perspective_analysis.get("missing_voices", []),
                status="partial",
            )

        # 3. Writer (required, unless preloaded)
        if preloaded_article is not None:
            article = preloaded_article
            logger.info(
                "Using preloaded writer output for '%s'", assignment.title,
            )
        else:
            writer = self.agents.get("writer")
            if not writer:
                raise PipelineStepError(
                    f"No 'writer' agent for topic '{assignment.id}'"
                )

            writer_context = {
                "title": assignment.title,
                "selection_reason": assignment.selection_reason,
                "perspective_analysis": perspective_analysis,
                "sources": research_dossier.get("sources", []),
                "coverage_gaps": research_dossier.get("coverage_gaps", []),
            }

            writer_addendum = None
            if assignment.follow_up_to:
                followup_path = Path("agents/writer/FOLLOWUP.md")
                if followup_path.exists():
                    writer_addendum = followup_path.read_text(encoding="utf-8")
                    logger.info(
                        "Loaded follow-up addendum for '%s' (follows %s)",
                        assignment.title, assignment.follow_up_to,
                    )
                else:
                    logger.warning(
                        "Follow-up topic '%s' but FOLLOWUP.md not found",
                        assignment.title,
                    )

                writer_context["follow_up"] = {
                    "previous_headline": self._get_previous_headline(
                        assignment.follow_up_to
                    ),
                    "reason": assignment.follow_up_reason or "",
                }

            result = await writer.run(
                "Write a multi-perspective article on this topic.",
                context=writer_context,
                system_addendum=writer_addendum,
            )
            self._track_agent(result, "writer", slug)
            article = _extract_dict(result)
            if not article:
                self._log_raw_on_parse_failure(
                    result, "Writer", slug, "05-writer",
                )
                article = {
                    "headline": assignment.title,
                    "body": result.content,
                }
            self._write_debug_output(f"05-writer-{slug}.json", article)

        body_text = article.get("body", "")
        article["word_count"] = len(body_text.split())

        article["sources"] = _merge_writer_sources(
            article.get("sources", []) or [], research_dossier,
        )

        if to_step == "writer":
            return TopicPackage(
                id=assignment.id,
                metadata={
                    "title": assignment.title,
                    "date": self.state.date if self.state else "",
                    "status": "partial",
                    "topic_slug": assignment.topic_slug,
                    "stopped_at": "writer",
                },
                sources=article.get("sources", []),
                perspectives=perspective_analysis.get("stakeholders", []),
                gaps=perspective_analysis.get("missing_voices", []),
                article=article,
                status="partial",
            )

        # 4. QA+Fix (single call: find errors + apply corrections)
        qa_analysis: dict = {}
        article_original = article.get("body", "")
        if qa_analyze := self.agents.get("qa_analyze"):
            qa_context = {
                "article": article,
                "sources": research_dossier.get("sources", []),
                "preliminary_divergences": research_dossier.get(
                    "preliminary_divergences", []
                ),
            }
            result = await qa_analyze.run(
                "Check this article against the source material. Find "
                "errors and divergences. Apply corrections directly in the "
                "article. Return the corrected article.",
                context=qa_context,
            )
            qa_analysis = _extract_dict(result) or {}
            self._track_agent(result, "qa_analyze", slug)
            if not qa_analysis and result.content:
                self._log_raw_on_parse_failure(
                    result, "QA+Fix", slug, "06-qa-analyze",
                )
            self._write_debug_output(
                f"06-qa-analyze-{slug}.json", qa_analysis,
            )

            qa_article = qa_analysis.get("article")
            if qa_article and isinstance(qa_article, dict) and qa_article.get("body"):
                article["body"] = qa_article["body"]
                if qa_article.get("headline"):
                    article["headline"] = qa_article["headline"]
                if qa_article.get("subheadline"):
                    article["subheadline"] = qa_article["subheadline"]
                if qa_article.get("summary"):
                    article["summary"] = qa_article["summary"]
                if qa_article.get("sources"):
                    article["sources"] = qa_article["sources"]

                corrections_applied = qa_analysis.get("corrections_applied", [])
                logger.info(
                    "QA+Fix for '%s': %d problems found, %d corrections applied",
                    assignment.title,
                    len(qa_analysis.get("problems_found", [])),
                    len(corrections_applied),
                )
            else:
                logger.warning(
                    "QA+Fix for '%s' returned no usable article — keeping original",
                    assignment.title,
                )

        # 4b. Perspektiv-Sync — re-align stakeholder map with QA-corrected
        # article body. Skipped when QA made no corrections; non-fatal on
        # failure (falls back to the unsynced map). This step is specific
        # to the hydrated pipeline; production uses the unsynced map.
        perspective_analysis = await self._run_perspektiv_sync(
            perspective_analysis, article, qa_analysis, slug,
        )

        article["word_count"] = len(article.get("body", "").split())

        if article.get("body") and "[[COVERAGE_STATEMENT]]" in article["body"]:
            _substitute_coverage_statement(article)
            article["word_count"] = len(article.get("body", "").split())
            logger.info(
                "Coverage statement: rendered for '%s' (%d sources)",
                assignment.title, len(article.get("sources", [])),
            )
        elif article.get("body"):
            logger.warning(
                "Coverage statement: [[COVERAGE_STATEMENT]] missing in "
                "article body for '%s' (Writer omitted it, or QA+Fix "
                "dropped it)",
                assignment.title,
            )

        # Fix 1 — Source-ID renumbering. Drops unreferenced sources and
        # renames survivors to a gapless src-001, src-002, … sequence.
        new_article, new_sources, _rename_map = _renumber_and_prune_sources(
            article, article.get("sources", []) or [], slug=slug,
        )
        article = new_article
        article["sources"] = new_sources
        article["word_count"] = len(article.get("body", "").split())

        # Fix 3 — rewrite stakeholder source_ids from rsrc-NNN to
        # post-Fix-1 src-NNN via the internal rsrc_id stash.
        perspective_analysis = _convert_rsrc_to_src_in_perspectives(
            perspective_analysis, article.get("sources", []), slug=slug,
        )

        # 7. Bias Transparency Card
        bias_card = _build_bias_card(
            article, perspective_analysis, qa_analysis, research_dossier,
        )

        if bias_language := self.agents.get("bias_language"):
            result = await bias_language.run(
                "Analyze this article text for linguistic bias patterns. "
                "Then write a reader note that synthesizes the bias card "
                "data with your language findings.",
                context={
                    "article_body": article.get("body", ""),
                    "bias_card": bias_card,
                },
            )
            self._track_agent(result, "bias_language", slug)
            llm_result = _extract_dict(result) or {}
            if not llm_result and result.content:
                self._log_raw_on_parse_failure(
                    result, "Bias Language", slug, "08-bias-language",
                )
            bias_card["language_bias"] = llm_result.get("language_bias", {})
            bias_card["reader_note"] = llm_result.get("reader_note", "")

        self._write_debug_output(f"08-bias-card-{slug}.json", bias_card)
        bias_analysis = bias_card

        # Follow-up object assembly
        follow_up_data = None
        if assignment.follow_up_to:
            prev_headline = self._get_previous_headline(
                assignment.follow_up_to
            )
            parts = assignment.follow_up_to.split("-")
            prev_date = (
                f"{parts[1]}-{parts[2]}-{parts[3]}"
                if len(parts) >= 5 else ""
            )
            follow_up_data = {
                "previous_tp_id": assignment.follow_up_to,
                "previous_headline": prev_headline,
                "previous_date": prev_date,
                "previous_slug": "",
                "reason": assignment.follow_up_reason or "",
            }
            tp_path = (
                Path(self.output_dir) / prev_date
                / f"{assignment.follow_up_to}.json"
            )
            if tp_path.exists():
                try:
                    prev_data = json.loads(
                        tp_path.read_text(encoding="utf-8")
                    )
                    follow_up_data["previous_slug"] = (
                        prev_data.get("metadata", {}).get("topic_slug", "")
                    )
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning(
                        "Could not read follow-up TP %s: %s",
                        assignment.follow_up_to, exc,
                    )

        # Restore actors_quoted from the research dossier onto the final
        # sources. The Writer doesn't need actors_quoted in its source-ref
        # contract (it reads them from the dossier context directly), and
        # QA+Fix's sources[] replacement drops them. The final TP is the
        # only place they need to be present.
        dossier_actors = {
            s["url"]: s.get("actors_quoted", [])
            for s in research_dossier.get("sources", []) or []
            if s.get("url")
        }
        for src in article.get("sources", []):
            url = src.get("url")
            if url and url in dossier_actors:
                src["actors_quoted"] = dossier_actors[url]
            src["country"] = _normalise_country(src.get("country"))
            src["language"] = _normalise_language(src.get("language"))

        # Restore estimated_date from research dossier onto sources.
        dossier_dates = {
            s["url"]: s.get("estimated_date")
            for s in research_dossier.get("sources", [])
            if s.get("estimated_date")
        }
        for src in article.get("sources", []):
            url = src.get("url", "")
            if url in dossier_dates:
                src["estimated_date"] = dossier_dates[url]
            elif url:
                est = _extract_date_from_url(url)
                if est:
                    src["estimated_date"] = est

        # Strip the internal rsrc_id stash before TP serialization.
        article["sources"] = _strip_internal_fields_from_sources(
            article.get("sources", [])
        )

        return TopicPackage(
            id=assignment.id,
            metadata={
                "title": assignment.title,
                "date": self.state.date if self.state else "",
                "status": "review",
                "topic_slug": assignment.topic_slug,
                "priority": assignment.priority,
                "follow_up": follow_up_data,
            },
            sources=article.get("sources", []),
            perspectives=perspective_analysis.get("stakeholders", []),
            divergences=qa_analysis.get("divergences", []),
            gaps=research_dossier.get("coverage_gaps", []) or [],
            article=article,
            bias_analysis=bias_analysis,
            transparency={
                "selection_reason": assignment.selection_reason,
                "pipeline_run": {
                    "run_id": self.state.run_id if self.state else "",
                    "date": self.state.date if self.state else "",
                },
                "article_original": (
                    article_original
                    if qa_analysis.get("corrections_applied") else None
                ),
                "qa_problems_found": qa_analysis.get("problems_found", []),
                "qa_corrections_applied": qa_analysis.get(
                    "corrections_applied", []
                ),
            },
            status="review",
        )
