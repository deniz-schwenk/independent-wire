"""Independent Wire — Pipeline orchestration.

A Pipeline calls Agents in a defined sequence, passes data between steps,
persists state to disk, and continues on individual topic failures.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from src.agent import Agent
from src.models import PipelineState, TopicAssignment, TopicPackage

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output."""
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?\s*```$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _extract_list(result: object) -> list[dict] | None:
    """Extract a list from an AgentResult (structured or content)."""
    if result.structured and isinstance(result.structured, list):
        return result.structured
    try:
        cleaned = _strip_code_fences(result.content)
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        # Some LLMs wrap lists in an object: {"findings": [...]}
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
    except (json.JSONDecodeError, ValueError):
        pass
    # Last resort: find JSON array in prose
    try:
        cleaned = _strip_code_fences(result.content)
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _extract_dict(result: object) -> dict | None:
    """Extract a dict from an AgentResult (structured or content)."""
    if result.structured and isinstance(result.structured, dict):
        return result.structured
    try:
        cleaned = _strip_code_fences(result.content)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _deduplicate_search_results(search_results: list[dict]) -> list[dict]:
    """Deduplicate search results by URL, merging query sources.

    Parses URLs from the raw plaintext search results (format: "N. title\\n   url\\n   snippet").
    If the same URL appears in results from multiple queries, keeps the entry with the
    longest snippet and records all queries that found it.
    """
    # Parse individual results from each search result block
    url_pattern = re.compile(r"^\s{3}(https?://\S+)", re.MULTILINE)
    # Pattern to extract numbered entries: "N. title\n   url\n   snippet"
    entry_pattern = re.compile(
        r"^\d+\.\s+(.+)\n\s{3}(https?://\S+)\n\s{3}(.+?)(?=\n\d+\.\s|\nResults for:|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    # Map URL → best entry info
    url_map: dict[str, dict] = {}  # url → {title, snippet, found_by}

    for sr in search_results:
        raw = sr.get("results", "")
        query_str = sr.get("query", "")

        for match in entry_pattern.finditer(raw):
            title = match.group(1).strip()
            url = match.group(2).strip()
            snippet = match.group(3).strip()

            if url in url_map:
                url_map[url]["found_by"].append(query_str)
                # Keep the longer snippet
                if len(snippet) > len(url_map[url]["snippet"]):
                    url_map[url]["snippet"] = snippet
                    url_map[url]["title"] = title
            else:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "found_by": [query_str],
                }

    # Rebuild search results with deduplicated entries
    deduped: list[dict] = []
    seen_urls: set[str] = set()

    for sr in search_results:
        raw = sr.get("results", "")
        query_str = sr.get("query", "")

        # Rebuild the results text, skipping URLs already emitted
        new_lines = []
        entry_num = 1
        for match in entry_pattern.finditer(raw):
            url = match.group(2).strip()
            if url in seen_urls:
                continue
            seen_urls.add(url)
            info = url_map.get(url, {})
            title = info.get("title", match.group(1).strip())
            snippet = info.get("snippet", match.group(3).strip())
            found_by = info.get("found_by", [query_str])
            found_by_note = ""
            if len(found_by) > 1:
                other_queries = [q for q in found_by if q != query_str]
                found_by_note = f"\n   [Also found by: {'; '.join(other_queries)}]"
            new_lines.append(f"{entry_num}. {title}\n   {url}\n   {snippet}{found_by_note}")
            entry_num += 1

        if new_lines:
            header = f"Results for: {query_str}"
            new_entry = dict(sr)
            new_entry["results"] = header + "\n\n" + "\n\n".join(new_lines)
            deduped.append(new_entry)
        elif not entry_pattern.search(raw):
            # No parseable entries (e.g., "No results" or error) — keep as-is
            deduped.append(sr)

    duplicates_removed = sum(len(v["found_by"]) - 1 for v in url_map.values() if len(v["found_by"]) > 1)
    if duplicates_removed:
        logger.info("Deduplication: removed %d duplicate URLs across queries", duplicates_removed)

    return deduped


def _build_bias_card(
    article: dict,
    perspective_analysis: dict,
    qa_analysis: dict,
    research_dossier: dict,
) -> dict:
    """Build the deterministic portion of the Bias Transparency Card.

    Pure data aggregation from existing pipeline outputs — no LLM calls.
    """
    writer_sources = article.get("sources", [])
    researcher_sources = research_dossier.get("sources", [])
    stakeholders = perspective_analysis.get("stakeholders", [])

    # Source balance — count by language and country
    by_language: dict[str, int] = {}
    by_country: dict[str, int] = {}
    for s in writer_sources:
        lang = s.get("language", "unknown")
        by_language[lang] = by_language.get(lang, 0) + 1
        country = s.get("country", "unknown")
        by_country[country] = by_country.get(country, 0) + 1

    # Geographic coverage — compare writer vs researcher sources
    writer_countries = {s.get("country", "") for s in writer_sources}
    researcher_countries = {s.get("country", "") for s in researcher_sources}
    missing_countries = sorted(researcher_countries - writer_countries - {""})

    return {
        "source_balance": {
            "total": len(writer_sources),
            "by_language": by_language,
            "by_country": by_country,
        },
        "geographic_coverage": {
            "represented": sorted(writer_countries - {""}),
            "missing_from_dossier": missing_countries,
        },
        "perspectives": {
            "total_identified": len(stakeholders),
            "missing_voices": perspective_analysis.get("missing_voices", []),
        },
        "framing_divergences": perspective_analysis.get("framing_divergences", []),
        "factual_divergences": qa_analysis.get("divergences", []),
        "coverage_gaps": research_dossier.get("coverage_gaps", []),
    }


class PipelineError(Exception):
    """Base exception for pipeline errors."""


class PipelineGateRejected(PipelineError):
    """Raised when a gate handler rejects the pipeline."""


class PipelineStepError(PipelineError):
    """Raised when a critical pipeline step fails (collect, curate, etc.)."""


class Pipeline:
    """Orchestrates agents in a defined sequence with data flow and gating."""

    STEPS = ["collect", "curate", "editorial_conference", "produce", "verify"]

    def __init__(
        self,
        name: str,
        agents: dict[str, Agent],
        output_dir: str = "./output",
        state_dir: str = "./state",
        max_topics: int = 7,
        mode: str = "full",
        gate_handler: Callable | None = None,
    ) -> None:
        self.name = name
        self.agents = agents
        self.output_dir = output_dir
        self.state_dir = state_dir
        self.max_topics = max_topics
        self.mode = mode
        self.gate_handler = gate_handler
        self.state: PipelineState | None = None
        self._agent_stats: list[dict] = []

    def _track_agent(self, result: object, agent_name: str, topic_slug: str | None = None) -> None:
        """Record agent metrics for the run stats."""
        self._agent_stats.append({
            "agent": agent_name,
            "topic": topic_slug,
            "tokens_used": result.tokens_used,
            "duration_seconds": result.duration_seconds,
            "model": result.model,
        })

    # Map CLI step names to internal pipeline step names
    _STEP_TO_INTERNAL = {
        "collector": "collect",
        "curator": "curate",
        "editor": "editorial_conference",
        "researcher": "produce",
        "perspektiv": "produce",
        "writer": "produce",
        "qa_analyze": "produce",
    }

    STEP_ORDER = ["collector", "curator", "editor", "researcher", "perspektiv", "writer", "qa_analyze", "bias_detector"]

    async def run(self, date: str | None = None, to_step: str | None = None) -> list[TopicPackage]:
        """Execute the full pipeline. Returns completed TopicPackages.

        If to_step is given, stop after that step (inclusive).
        """
        date = date or datetime.now().strftime("%Y-%m-%d")

        # Check for incomplete state
        existing = self._load_incomplete_state(date)
        if existing:
            logger.info("Resuming incomplete run: %s", existing.run_id)
            self.state = existing
        else:
            run_id = f"run-{date}-{uuid4().hex[:6]}"
            self.state = PipelineState(
                run_id=run_id,
                date=date,
                current_step="collect",
                started_at=datetime.now().isoformat(),
            )

        # Determine stop point
        to_idx = self.STEP_ORDER.index(to_step) if to_step else len(self.STEP_ORDER) - 1

        # Execute steps in order, skipping already completed ones
        raw_findings: list[dict] = self.state.raw_findings
        curated_topics: list[dict] = self.state.curated_topics
        assignments: list[TopicAssignment] = [
            TopicAssignment(**a) for a in self.state.assignments
        ]
        packages: list[TopicPackage] = [
            TopicPackage(**p) for p in self.state.packages
        ]

        if "collect" not in self.state.completed_steps:
            self.state.current_step = "collect"
            await self._save_state()
            raw_findings = await self.collect()
            self.state.raw_findings = raw_findings
            self.state.completed_steps.append("collect")
            await self._save_state()
            self._write_debug_output("01-collector-raw.json", raw_findings)

        if to_idx <= self.STEP_ORDER.index("collector"):
            logger.info("Stopping after step 'collector' as requested.")
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "curate" not in self.state.completed_steps:
            self.state.current_step = "curate"
            await self._save_state()
            curated_topics = await self.curate(raw_findings)
            self.state.curated_topics = curated_topics
            self.state.completed_steps.append("curate")
            await self._save_state()
            self._write_debug_output("02-curator-topics.json", curated_topics)

        if to_idx <= self.STEP_ORDER.index("curator"):
            logger.info("Stopping after step 'curator' as requested.")
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "editorial_conference" not in self.state.completed_steps:
            self.state.current_step = "editorial_conference"
            await self._save_state()
            assignments = await self.editorial_conference(curated_topics)
            self.state.assignments = [asdict(a) for a in assignments]
            self.state.completed_steps.append("editorial_conference")
            await self._save_state()
            self._write_debug_output(
                "03-editor-assignments.json",
                [asdict(a) for a in assignments],
            )

            # Gate check after editorial conference (full mode only)
            gate_ok = await self.gate("editorial_conference", assignments)
            if not gate_ok:
                raise PipelineGateRejected(
                    "Gate rejected after editorial_conference"
                )

        if to_idx <= self.STEP_ORDER.index("editor"):
            logger.info("Stopping after step 'editor' as requested.")
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "produce" not in self.state.completed_steps:
            self.state.current_step = "produce"
            await self._save_state()
            packages = await self.produce(assignments, to_step=to_step)
            self.state.packages = [asdict(p) for p in packages]
            self.state.completed_steps.append("produce")
            await self._save_state()

        # If --to stops before qa_analyze, skip verify and write_output
        if to_step and self.STEP_ORDER.index(to_step) < self.STEP_ORDER.index("qa_analyze"):
            if to_step in ("researcher", "perspektiv", "writer"):
                logger.info("Stopping after step '%s' as requested.", to_step)
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "verify" not in self.state.completed_steps:
            self.state.current_step = "verify"
            await self._save_state()
            packages = await self.verify(packages)
            self.state.completed_steps.append("verify")
            await self._save_state()

        # Mark as done
        self.state.current_step = "done"
        await self._save_state()

        # Write output
        await self._write_output(packages)

        return packages

    async def collect(self) -> list[dict]:
        """Two-phase collection: plan queries, execute in Python, assemble findings."""
        from src.tools import web_search_tool

        planner = self.agents.get("collector_plan")
        assembler = self.agents.get("collector_assemble")

        if not planner and not assembler and "collector" not in self.agents:
            logger.info("No collector configured, skipping collection step")
            return []

        if not planner or not assembler:
            logger.error("No 'collector_plan' or 'collector_assemble' agent configured")
            return []

        # Phase 1: Plan search queries
        plan_result = await planner.run(
            f"Plan search queries for today's global news scan. Today is {self.state.date}.",
            output_schema={"type": "array", "items": {"type": "object"}},
        )
        self._track_agent(plan_result, "collector_plan")

        queries = plan_result.structured
        if not queries or not isinstance(queries, list):
            queries = _extract_list(plan_result) or []
        if not queries:
            logger.warning("Collector planner returned no queries")
            return []

        logger.info("Collector plan: %d queries", len(queries))
        self._write_debug_output("01-collector-plan.json", queries)

        # Phase 2: Execute searches in Python (no LLM)
        search_results = []
        for q in queries:
            query_str = q.get("query", "")
            if not query_str:
                continue
            try:
                result_text = await web_search_tool.execute(query=query_str)
                search_results.append({"query": q, "results": result_text})
            except Exception as e:
                logger.warning("Collector search failed for '%s': %s", query_str, e)
                search_results.append({"query": q, "results": f"Error: {e}"})

        logger.info("Collector search: %d/%d queries returned results",
                     len([r for r in search_results if not r["results"].startswith("Error")]),
                     len(search_results))

        # Deduplicate by URL
        search_results = _deduplicate_search_results(search_results)

        self._write_debug_output("01-collector-search.json", search_results)

        # Phase 3: Assemble findings (one LLM call, no tools)
        try:
            assemble_result = await assembler.run(
                "Compile these search results into a JSON array of news findings.",
                context={"search_results": search_results},
            )
            self._track_agent(assemble_result, "collector_assemble")
            parsed = _extract_list(assemble_result)
            if parsed is not None:
                return parsed
            logger.warning("Collector assembler returned non-list output")
            return []
        except Exception as e:
            logger.error("Collector assembly failed: %s", e)
            return []

    def _load_feed_findings(self) -> list[dict]:
        """Load feed findings from raw/{date}/feeds.json if available."""
        if not self.state:
            return []
        feeds_path = Path("raw") / self.state.date / "feeds.json"
        if not feeds_path.exists():
            return []
        try:
            data = json.loads(feeds_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                logger.info("Loaded %d feed findings from %s", len(data), feeds_path)
                return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Could not load feed findings: %s", e)
        return []

    def _prepare_curator_input(self, raw_findings: list[dict]) -> list[dict]:
        """Compress all findings for the Curator. Pure Python, no LLM.

        Keeps ALL findings (no filtering, no dedup beyond URL).
        Strips fields the Curator doesn't need (url, region, language, feed_source).
        Only includes summary if it exists AND differs from the title.
        """
        # URL dedup (safety net — already done in fetch_feeds.py)
        seen_urls: set[str] = set()
        unique: list[dict] = []
        for f in raw_findings:
            url = f.get("source_url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            unique.append(f)

        url_dupes = len(raw_findings) - len(unique)
        if url_dupes:
            logger.info("Curator prep: removed %d URL duplicates", url_dupes)

        # Compress: only title + summary (if useful) + source_name + index
        compressed: list[dict] = []
        for i, f in enumerate(unique):
            title = f.get("title", "").strip()
            if not title:
                continue

            entry: dict = {
                "id": f"finding-{i}",
                "title": title,
                "source_name": f.get("source_name", ""),
            }

            # Include summary only if it exists and adds information beyond the title
            summary = f.get("summary", "").strip()
            if summary and summary.lower() != title.lower() and not title.lower().startswith(summary.lower()[:50]):
                entry["summary"] = summary

            compressed.append(entry)

        logger.info(
            "Curator prep: %d raw → %d unique → %d with titles (compressed)",
            len(raw_findings), len(unique), len(compressed),
        )

        return compressed

    def _enrich_curator_output(
        self, topics: list[dict], raw_findings: list[dict]
    ) -> list[dict]:
        """Add geographic_coverage, missing_perspectives, languages deterministically.

        The Curator only clusters and scores. This function computes metadata
        from the original finding fields (region, language, source_name) that
        the Curator never sees. Pure Python, 0 LLM tokens.
        """
        # Load source metadata for tier/editorial_independence
        sources_path = Path("config") / "sources.json"
        source_meta: dict[str, dict] = {}
        if sources_path.exists():
            data = json.loads(sources_path.read_text(encoding="utf-8"))
            source_meta = {s["name"]: s for s in data.get("feeds", [])}

        # Build index: finding-N → original finding dict
        finding_index: dict[str, dict] = {}
        for i, f in enumerate(raw_findings):
            finding_index[f"finding-{i}"] = f

        # All regions and languages across ALL findings (for gap detection)
        all_regions: set[str] = set()
        all_languages: set[str] = set()
        for f in raw_findings:
            r = f.get("region", "")
            if r:
                all_regions.add(r)
            lang = f.get("language", "")
            if lang:
                all_languages.add(lang)

        for topic in topics:
            source_ids = topic.get("source_ids", [])

            # Collect metadata from clustered findings
            topic_regions: set[str] = set()
            topic_languages: set[str] = set()
            topic_sources: list[dict] = []

            for sid in source_ids:
                finding = finding_index.get(sid)
                if not finding:
                    continue
                r = finding.get("region", "")
                if r:
                    topic_regions.add(r)
                lang = finding.get("language", "")
                if lang:
                    topic_languages.add(lang)

                sname = finding.get("source_name", "")
                meta = source_meta.get(sname, {})
                topic_sources.append({
                    "name": sname,
                    "tier": meta.get("tier"),
                    "editorial_independence": meta.get("editorial_independence"),
                })

            # Deterministic enrichment
            topic["geographic_coverage"] = sorted(topic_regions)
            topic["languages"] = sorted(topic_languages)
            topic["source_count"] = len(source_ids)

            # Missing regions: all regions in the full feed set minus this topic's regions
            missing_regions = sorted(all_regions - topic_regions)
            topic["missing_regions"] = missing_regions

            # Missing languages
            missing_langs = sorted(all_languages - topic_languages)
            topic["missing_languages"] = missing_langs

            # Source diversity
            topic["source_diversity"] = topic_sources

            # Build missing_perspectives string (human-readable)
            parts: list[str] = []
            if missing_regions:
                parts.append(f"No sources from: {', '.join(missing_regions)}")
            if missing_langs:
                parts.append(f"No coverage in: {', '.join(missing_langs)}")

            # Keep LLM-generated missing_perspectives if present, append deterministic data
            existing = topic.get("missing_perspectives", "")
            deterministic = ". ".join(parts) if parts else ""
            if existing and deterministic:
                topic["missing_perspectives"] = f"{existing} [Deterministic: {deterministic}]"
            elif deterministic:
                topic["missing_perspectives"] = deterministic

        return topics

    async def curate(self, raw_findings: list[dict]) -> list[dict]:
        """Select the most newsworthy topics from raw findings."""
        agent = self.agents.get("curator")
        if not agent:
            logger.error("No 'curator' agent configured")
            return []

        # Merge feed findings with collector findings
        feed_findings = self._load_feed_findings()
        if feed_findings:
            logger.info(
                "Merged %d feed findings with %d collector findings",
                len(feed_findings), len(raw_findings),
            )
            raw_findings = raw_findings + feed_findings

        # Prepare compressed input (all findings, no filtering)
        prepared = self._prepare_curator_input(raw_findings)
        self._write_debug_output("01b-curator-prepared.json", {
            "raw_count": len(raw_findings),
            "prepared_count": len(prepared),
            "sources_represented": len(set(f.get("source_name", "") for f in prepared)),
            "token_estimate": sum(len(json.dumps(f)) for f in prepared) // 4,
        })

        message = (
            "Review these findings. Cluster related findings into topics. "
            "Score each topic's newsworthiness on a 1-10 scale. "
            "For each topic provide: title, topic_slug, relevance_score, "
            "summary, source_ids."
        )

        # Curator output is a small JSON array (~2-5K tokens).
        # Reduce max_tokens to fit within context window with large input.
        saved_max_tokens = agent.max_tokens
        agent.max_tokens = min(agent.max_tokens, 16384)

        try:
            result = await agent.run(
                message, context={"findings": prepared}
            )
            self._track_agent(result, "curator")
            topics = _extract_list(result) or []

            # Deterministic enrichment (geographic_coverage, missing_perspectives, etc.)
            topics = self._enrich_curator_output(topics, raw_findings)

            # Sort by relevance_score (descending) and limit
            topics.sort(
                key=lambda t: t.get("relevance_score", 0), reverse=True
            )
            return topics[: self.max_topics]
        except Exception as e:
            logger.error("Curator failed: %s", e)
            return []
        finally:
            agent.max_tokens = saved_max_tokens

    async def editorial_conference(
        self, curated_topics: list[dict]
    ) -> list[TopicAssignment]:
        """Prioritize topics and create assignments."""
        agent = self.agents.get("editor")
        if not agent:
            logger.error("No 'editor' agent configured")
            return []

        message = (
            "Prioritize these topics for today's report. For each: assign "
            "priority (1-10), provide selection_reason, assign topic_id. "
            f"Today's date is {self.state.date}. Use this date in topic_id "
            "format: tp-YYYY-MM-DD-NNN (e.g. tp-" + self.state.date + "-001)."
        )

        try:
            result = await agent.run(
                message, context={"topics": curated_topics}
            )
            self._track_agent(result, "editor")
            raw_assignments = _extract_list(result) or []

            assignments = []
            for a in raw_assignments:
                assignments.append(
                    TopicAssignment(
                        id=a.get("id", a.get("topic_id", "")),
                        title=a.get("title", ""),
                        priority=a.get("priority", 5),
                        topic_slug=a.get("topic_slug", ""),
                        selection_reason=a.get("selection_reason", ""),
                        raw_data=a.get("raw_data", {}),
                    )
                )
            return assignments
        except Exception as e:
            logger.error("Editor failed: %s", e)
            return []

    async def gate(self, step_name: str, data: object) -> bool:
        """Gate check — only in full mode, calls gate_handler if provided."""
        if self.mode != "full":
            return True
        if not self.gate_handler:
            return True
        return await self.gate_handler(step_name, data)

    async def produce(
        self, assignments: list[TopicAssignment], to_step: str | None = None,
    ) -> list[TopicPackage]:
        """Produce TopicPackages for all assignments sequentially."""
        import asyncio

        packages: list[TopicPackage] = []
        for i, assignment in enumerate(assignments):
            # Delay between topics to avoid upstream rate limits (429s)
            if i > 0:
                logger.info("Waiting 30s before next topic to avoid rate limits...")
                await asyncio.sleep(30)
            try:
                pkg = await self._produce_single(assignment, to_step=to_step)
                packages.append(pkg)
                slug = assignment.topic_slug or assignment.id
                self._write_debug_output(
                    f"05-writer-{slug}.json", pkg.to_dict()
                )
            except Exception as e:
                logger.error(
                    "Failed to produce topic '%s': %s", assignment.id, e
                )
                pkg = TopicPackage(
                    id=assignment.id,
                    metadata={
                        "title": assignment.title,
                        "date": self.state.date if self.state else "",
                        "status": "failed",
                        "topic_slug": assignment.topic_slug,
                    },
                    status="failed",
                    error=str(e),
                )
                packages.append(pkg)
        return packages

    async def _produce_single(
        self,
        assignment: TopicAssignment,
        preloaded_dossier: dict | None = None,
        preloaded_article: dict | None = None,
        skip_perspektiv: bool = False,
        to_step: str | None = None,
    ) -> TopicPackage:
        """Produce a single TopicPackage from an assignment.

        Optional preloaded data skips the corresponding step:
        - preloaded_dossier: skip researcher
        - preloaded_article: skip writer (and researcher and perspektiv)
        - skip_perspektiv: skip perspektiv even when dossier is available
        - to_step: stop after this step (inclusive)
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
            logger.info("Using preloaded researcher dossier for '%s'", assignment.title)
        else:
            research_dossier = await self._research_two_phase(assignment_data, slug)

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

        # 10s delay between researcher and perspektiv/writer to avoid rate limits
        if research_dossier and preloaded_dossier is None:
            logger.info("Waiting 10s after researcher...")
            await asyncio.sleep(10)

        # 2b. Perspective Agent (stakeholder mapping, no tools)
        perspective_analysis: dict = {}
        if not skip_perspektiv and preloaded_article is None and research_dossier:
            if perspektiv := self.agents.get("perspektiv"):
                perspektiv_context = {
                    **assignment_data,
                    "research_dossier": research_dossier,
                }
                result = await perspektiv.run(
                    "Analyze the research dossier. Map all stakeholders, identify missing voices, "
                    "and surface framing divergences between regions and language groups.",
                    context=perspektiv_context,
                )
                perspective_analysis = _extract_dict(result) or {}
                self._track_agent(result, "perspektiv", slug)
                self._write_debug_output(f"04b-perspektiv-{slug}.json", perspective_analysis)

                # 5s delay before writer
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
            logger.info("Using preloaded writer output for '%s'", assignment.title)
        else:
            writer = self.agents.get("writer")
            if not writer:
                raise PipelineStepError(
                    f"No 'writer' agent for topic '{assignment.id}'"
                )

            writer_context = {
                **assignment_data,
                "perspective_analysis": perspective_analysis,
                "research_dossier": research_dossier,
            }
            result = await writer.run(
                "Write a multi-perspective article on this topic.",
                context=writer_context,
            )
            self._track_agent(result, "writer", slug)
            article = _extract_dict(result) or {
                "headline": assignment.title,
                "body": result.content,
            }

        # Compute word_count in Python (never trust LLM counting)
        body_text = article.get("body", "")
        article["word_count"] = len(body_text.split())

        # Fix meta-transparency source/language counts (Writer miscounts systematically)
        body = article.get("body", "")
        writer_sources = article.get("sources", [])
        if body and writer_sources:
            actual_count = len(writer_sources)
            langs = {s.get("language", "") for s in writer_sources if s.get("language")}
            actual_langs = len(langs)
            meta_pattern = re.compile(
                r"(This (?:report|article|analysis) draws on )\d+( sources in )\d+( languages?)"
            )
            new_body = meta_pattern.sub(
                rf"\g<1>{actual_count}\g<2>{actual_langs}\3",
                body,
            )
            if new_body != body:
                article["body"] = new_body
                logger.info(
                    "Fixed meta-transparency: %d sources in %d languages for '%s'",
                    actual_count,
                    actual_langs,
                    assignment.title,
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

        # 4. QA-Analyze (find errors, divergences, gaps)
        qa_analysis: dict = {}
        if qa_analyze := self.agents.get("qa_analyze"):
            qa_context = {
                "article": article,
                "research_dossier": research_dossier,
            }
            qa_schema = {
                "type": "object",
                "properties": {
                    "corrections": {"type": "array"},
                    "divergences": {"type": "array"},
                },
                "required": ["corrections", "divergences"],
            }
            result = await qa_analyze.run(
                "Review this article against the available sources. Find factual errors, "
                "source divergences the article doesn't reflect, and coverage gaps.",
                context=qa_context,
                output_schema=qa_schema,
            )
            qa_analysis = _extract_dict(result) or {}
            self._track_agent(result, "qa_analyze", slug)
            self._write_debug_output(f"06-qa-analyze-{slug}.json", qa_analysis)

            if not qa_analysis or not any(
                qa_analysis.get(k) is not None for k in ("corrections", "divergences")
            ):
                logger.warning(
                    "QA-Analyze for '%s' returned no usable fields — "
                    "output may be truncated. Check debug file.",
                    assignment.title,
                )

        # 5. Writer-Correction with retry (only if corrections needed)
        corrections = qa_analysis.get("corrections", [])
        article_original = article.get("body", "")
        applied = 0
        max_correction_attempts = 3

        if corrections and (writer := self.agents.get("writer")):
            pending_corrections = corrections
            for attempt in range(1, max_correction_attempts + 1):
                await asyncio.sleep(10)  # Rate limit

                if attempt == 1:
                    message = (
                        "You wrote this article. QA found factual errors that need correction. "
                        "Apply ONLY the listed corrections to the article. Return the complete "
                        "article JSON (headline, subheadline, body, summary, sources) with the "
                        "corrections applied. Do not change anything else."
                    )
                else:
                    message = (
                        "These corrections were not applied in your previous attempt. "
                        "The flagged text still appears in the article. You MUST rewrite or "
                        "remove the flagged passages. Do not keep the original text."
                    )

                logger.info(
                    "Writer-Correction attempt %d/%d for '%s' (%d corrections)",
                    attempt, max_correction_attempts, assignment.title, len(pending_corrections),
                )

                correction_context = {
                    "task": "correction",
                    "original_article": article,
                    "corrections": pending_corrections,
                }
                result = await writer.run(message, context=correction_context)
                corrected = _extract_dict(result) or {}
                self._track_agent(result, "writer", slug)
                self._write_debug_output(f"07-writer-correction-{slug}.json", corrected)

                # Merge corrected fields into article
                if corrected.get("body"):
                    article["body"] = corrected["body"]
                if corrected.get("headline"):
                    article["headline"] = corrected["headline"]
                if corrected.get("subheadline"):
                    article["subheadline"] = corrected["subheadline"]
                if corrected.get("summary"):
                    article["summary"] = corrected["summary"]

                # 6. Deterministic verification — check corrections were applied
                still_unapplied = []
                applied = 0
                for correction in corrections:
                    excerpt = correction.get("article_excerpt", "")
                    if excerpt and excerpt not in article.get("body", ""):
                        applied += 1
                    elif excerpt:
                        still_unapplied.append(correction)

                if not still_unapplied:
                    logger.info(
                        "Writer-Correction for '%s': all %d corrections applied (attempt %d/%d).",
                        assignment.title, len(corrections), attempt, max_correction_attempts,
                    )
                    break

                if attempt < max_correction_attempts:
                    logger.info(
                        "Writer-Correction for '%s': %d/%d corrections still unapplied, retrying...",
                        assignment.title, len(still_unapplied), len(corrections),
                    )
                    pending_corrections = still_unapplied
                else:
                    logger.warning(
                        "Writer-Correction for '%s': %d/%d corrections NOT applied after %d attempts: %s",
                        assignment.title,
                        len(still_unapplied),
                        len(corrections),
                        max_correction_attempts,
                        [c.get("article_excerpt", "")[:80] for c in still_unapplied],
                    )

        # Compute word_count in Python (never trust LLM counting)
        article["word_count"] = len(article.get("body", "").split())

        # Fix meta-transparency again after corrections (may re-introduce wrong counts)
        body = article.get("body", "")
        writer_sources = article.get("sources", [])
        if body and writer_sources:
            actual_count = len(writer_sources)
            langs = {s.get("language", "") for s in writer_sources if s.get("language")}
            actual_langs = len(langs)
            meta_pattern = re.compile(
                r"(This (?:report|article|analysis) draws on )\d+( sources in )\d+( languages?)"
            )
            new_body = meta_pattern.sub(
                rf"\g<1>{actual_count}\g<2>{actual_langs}\3",
                body,
            )
            if new_body != body:
                article["body"] = new_body
                logger.info(
                    "Fixed meta-transparency: %d sources in %d languages for '%s'",
                    actual_count,
                    actual_langs,
                    assignment.title,
                )

        # 7. Bias Transparency Card (hybrid: Python aggregation + LLM language analysis)
        bias_card = _build_bias_card(article, perspective_analysis, qa_analysis, research_dossier)

        if bias_language := self.agents.get("bias_language"):
            result = await bias_language.run(
                "Analyze this article text for linguistic bias patterns. "
                "Then write a reader note that synthesizes the bias card data "
                "with your language findings.",
                context={"article_body": article.get("body", ""), "bias_card": bias_card},
            )
            self._track_agent(result, "bias_language", slug)
            llm_result = _extract_dict(result) or {}
            bias_card["language_bias"] = llm_result.get("language_bias", {})
            bias_card["reader_note"] = llm_result.get("reader_note", "")

        self._write_debug_output(f"08-bias-card-{slug}.json", bias_card)
        bias_analysis = bias_card

        # Assemble TopicPackage
        return TopicPackage(
            id=assignment.id,
            metadata={
                "title": assignment.title,
                "date": self.state.date if self.state else "",
                "status": "review",
                "topic_slug": assignment.topic_slug,
                "priority": assignment.priority,
            },
            sources=article.get("sources", []),
            perspectives=perspective_analysis.get("stakeholders", []),
            divergences=qa_analysis.get("divergences", []),
            gaps=perspective_analysis.get("missing_voices", []),
            article=article,
            bias_analysis=bias_analysis,
            transparency={
                "selection_reason": assignment.selection_reason,
                "confidence": "medium",
                "pipeline_run": {
                    "run_id": self.state.run_id if self.state else "",
                    "date": self.state.date if self.state else "",
                },
                "article_original": article_original if corrections else None,
                "qa_corrections": corrections,
                "qa_corrections_applied": applied if corrections else 0,
                "framing_divergences": perspective_analysis.get("framing_divergences", []),
            },
            status="review",
        )

    async def _research_two_phase(self, assignment_data: dict, slug: str) -> dict:
        """Two-phase research: plan queries, execute in Python, assemble dossier."""
        from src.tools import web_search_tool

        planner = self.agents.get("researcher_plan")
        assembler = self.agents.get("researcher_assemble")
        if not planner or not assembler:
            logger.error("No 'researcher_plan' or 'researcher_assemble' agent configured")
            return {}

        # Phase 1: Plan multilingual queries
        plan_result = await planner.run(
            f"Plan multilingual research queries for this topic. Today is {self.state.date}.",
            context=assignment_data,
            output_schema={"type": "array", "items": {"type": "object"}},
        )
        self._track_agent(plan_result, "researcher_plan", slug)

        queries = plan_result.structured
        if not queries or not isinstance(queries, list):
            queries = _extract_list(plan_result) or []
        if not queries:
            logger.warning("Researcher planner for '%s' returned no queries", slug)
            return {}

        languages = {q.get("language", "en") for q in queries}
        logger.info("Researcher plan: %d queries across %d languages for '%s'",
                     len(queries), len(languages), slug)
        self._write_debug_output(f"04-researcher-plan-{slug}.json", queries)

        # Phase 2: Execute searches in Python (no LLM)
        search_results = []
        for q in queries:
            query_str = q.get("query", "")
            if not query_str:
                continue
            try:
                result_text = await web_search_tool.execute(query=query_str)
                search_results.append({
                    "query": query_str,
                    "language": q.get("language", "en"),
                    "results": result_text,
                })
            except Exception as e:
                logger.warning("Research search failed for '%s': %s", query_str, e)
                search_results.append({
                    "query": query_str,
                    "language": q.get("language", "en"),
                    "results": f"Error: {e}",
                })

        successful = len([r for r in search_results if not r["results"].startswith("Error")])
        logger.info("Researcher search: %d/%d queries returned results for '%s'",
                     successful, len(search_results), slug)

        # Deduplicate by URL
        search_results = _deduplicate_search_results(search_results)

        self._write_debug_output(f"04-researcher-search-{slug}.json", search_results)

        # Phase 3: Assemble dossier (one LLM call, no tools)
        assemble_result = await assembler.run(
            "Build a research dossier from these search results. "
            "Extract sources, actors, divergences, and coverage gaps.",
            context={
                "assignment": assignment_data,
                "search_results": search_results,
            },
        )
        self._track_agent(assemble_result, "researcher_assemble", slug)

        dossier = _extract_dict(assemble_result) or {}

        # Write debug output (raw content if parsing failed)
        if dossier:
            self._write_debug_output(f"04-researcher-{slug}.json", dossier)
        else:
            logger.warning(
                "Researcher assembler for '%s' returned unparseable output (%d tokens). "
                "Saving raw content to debug file.",
                slug,
                assemble_result.tokens_used,
            )
            self._write_debug_output(
                f"04-researcher-{slug}-RAW.json",
                {"_raw_content": assemble_result.content[:5000], "_tokens_used": assemble_result.tokens_used},
            )

        return dossier

    async def verify(
        self, packages: list[TopicPackage]
    ) -> list[TopicPackage]:
        """Verify integrity: count completed vs failed packages."""
        total = len(packages)
        completed = len([p for p in packages if p.status != "failed"])
        failed = len([p for p in packages if p.status == "failed"])

        if completed + failed != total:
            logger.error(
                "Verify: count mismatch! completed(%d) + failed(%d) != total(%d)",
                completed,
                failed,
                total,
            )

        logger.info(
            "Verify: %d/%d topics completed, %d failed",
            completed,
            total,
            failed,
        )

        # Check source language diversity per topic
        for pkg in packages:
            if pkg.status == "failed":
                continue
            sources = pkg.article.get("sources", []) if isinstance(pkg.article, dict) else []
            langs = {s.get("language", "") for s in sources if s.get("language")}
            if len(langs) == 1:
                lang = next(iter(langs))
                logger.warning(
                    "Verify: topic '%s' has sources in only one language (%s). "
                    "Consider adding non-English sources.",
                    pkg.id,
                    lang,
                )

        return packages

    # ------------------------------------------------------------------
    # Partial run support
    # ------------------------------------------------------------------

    def _load_debug_output(self, date: str, filename: str) -> dict | list | None:
        """Load a debug output file from a previous run."""
        path = Path(self.output_dir) / date / filename
        if not path.exists():
            logger.error("Debug file not found: %s", path)
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _find_latest_output_date(self) -> str | None:
        """Find the most recent date directory in output/."""
        out = Path(self.output_dir)
        if not out.exists():
            return None
        dates = sorted(
            [d.name for d in out.iterdir() if d.is_dir() and d.name[:4].isdigit()]
        )
        return dates[-1] if dates else None

    async def run_partial(
        self,
        from_step: str,
        topic_filter: int | None = None,
        reuse_date: str | None = None,
        to_step: str | None = None,
    ) -> list[TopicPackage]:
        """Run pipeline from a specific step, loading earlier data from debug output.

        If to_step is given, stop after that step (inclusive).
        """
        import asyncio

        # Resolve which date to load debug data from
        reuse = reuse_date or self._find_latest_output_date()
        if not reuse:
            raise PipelineError("No previous output found to reuse")

        date = datetime.now().strftime("%Y-%m-%d")
        run_id = f"run-{date}-{uuid4().hex[:6]}"
        self.state = PipelineState(
            run_id=run_id,
            date=date,
            current_step=from_step,
            started_at=datetime.now().isoformat(),
        )

        logger.info(
            "Partial run: starting from '%s'%s, reusing data from %s",
            from_step,
            f" to '{to_step}'" if to_step else "",
            reuse,
        )

        # Determine which steps to skip/run based on from_step and to_step
        step_order = self.STEP_ORDER
        from_idx = step_order.index(from_step)
        to_idx = step_order.index(to_step) if to_step else len(step_order) - 1

        # --- Load assignments (needed for researcher onward) ---
        assignments: list[TopicAssignment] = []
        if from_idx >= step_order.index("researcher"):
            raw_assignments = self._load_debug_output(reuse, "03-editor-assignments.json")
            if not raw_assignments or not isinstance(raw_assignments, list):
                raise PipelineError(
                    f"Could not load 03-editor-assignments.json from {reuse}"
                )
            for a in raw_assignments:
                assignments.append(
                    TopicAssignment(
                        id=a.get("id", a.get("topic_id", "")),
                        title=a.get("title", ""),
                        priority=a.get("priority", 5),
                        topic_slug=a.get("topic_slug", ""),
                        selection_reason=a.get("selection_reason", ""),
                        raw_data=a.get("raw_data", {}),
                    )
                )
            logger.info("Loaded %d assignments from %s", len(assignments), reuse)

        # Apply topic filter (1-based index)
        if topic_filter is not None:
            if topic_filter < 1 or topic_filter > len(assignments):
                raise PipelineError(
                    f"--topic {topic_filter} out of range (have {len(assignments)} topics)"
                )
            assignments = [assignments[topic_filter - 1]]
            logger.info("Filtered to topic %d: %s", topic_filter, assignments[0].title)

        # --- Load per-topic data for later steps ---
        dossiers: dict[str, dict] = {}
        writer_outputs: dict[str, dict] = {}

        # Load researcher dossiers (needed for --from perspektiv onward)
        if from_idx >= step_order.index("perspektiv"):
            for assignment in assignments:
                slug = assignment.topic_slug or assignment.id
                filename = f"04-researcher-{slug}.json"
                dossier = self._load_debug_output(reuse, filename)
                if dossier and isinstance(dossier, dict):
                    dossiers[slug] = dossier
                    logger.info("Loaded researcher dossier: %s", filename)
                else:
                    logger.warning("No researcher dossier found: %s", filename)

        # Load writer outputs (needed for --from qa_analyze onward)
        if from_idx >= step_order.index("qa_analyze"):
            for assignment in assignments:
                slug = assignment.topic_slug or assignment.id
                filename = f"05-writer-{slug}.json"
                writer_data = self._load_debug_output(reuse, filename)
                if writer_data and isinstance(writer_data, dict):
                    # Writer debug output is a full TopicPackage — extract the article
                    writer_outputs[slug] = writer_data.get("article", writer_data)
                    logger.info("Loaded writer output: %s", filename)
                else:
                    logger.warning("No writer output found: %s", filename)

        # --- Execute remaining steps ---
        packages: list[TopicPackage] = []

        if from_step in ("collector", "curator", "editor"):
            # Load raw findings for curator/editor starts
            raw_findings: list[dict] = []
            if from_idx >= step_order.index("curator"):
                raw_findings = self._load_debug_output(reuse, "01-collector-raw.json") or []
                logger.info("Loaded %d raw findings from %s", len(raw_findings), reuse)

            curated_topics: list[dict] = []
            if from_idx >= step_order.index("editor"):
                curated_topics = self._load_debug_output(reuse, "02-curator-topics.json") or []
                logger.info("Loaded %d curated topics from %s", len(curated_topics), reuse)

            # Run the steps that weren't skipped
            if from_step == "collector":
                raw_findings = await self.collect()
                self._write_debug_output("01-collector-raw.json", raw_findings)
                if to_step == "collector":
                    logger.info("Stopping after step 'collector' as requested.")
                    self.state.current_step = "done"
                    await self._save_state()
                    return packages

            if from_idx <= step_order.index("curator"):
                curated_topics = await self.curate(raw_findings)
                self._write_debug_output("02-curator-topics.json", curated_topics)
                if to_idx <= step_order.index("curator"):
                    logger.info("Stopping after step 'curator' as requested.")
                    self.state.current_step = "done"
                    await self._save_state()
                    return packages

            if from_idx <= step_order.index("editor"):
                assignments = await self.editorial_conference(curated_topics)
                self._write_debug_output(
                    "03-editor-assignments.json",
                    [asdict(a) for a in assignments],
                )
                if topic_filter is not None:
                    assignments = [assignments[topic_filter - 1]]
                if to_idx <= step_order.index("editor"):
                    logger.info("Stopping after step 'editor' as requested.")
                    self.state.current_step = "done"
                    await self._save_state()
                    return packages

            # Fall through to produce
            packages = await self.produce(assignments, to_step=to_step)

        elif from_step == "researcher":
            packages = await self.produce(assignments, to_step=to_step)

        elif from_step in ("perspektiv", "writer", "qa_analyze"):
            # Run from perspektiv/writer/qa_analyze with preloaded data
            for i, assignment in enumerate(assignments):
                if i > 0:
                    logger.info("Waiting 30s before next topic to avoid rate limits...")
                    await asyncio.sleep(30)
                slug = assignment.topic_slug or assignment.id
                try:
                    pkg = await self._produce_single(
                        assignment,
                        preloaded_dossier=dossiers.get(slug),
                        preloaded_article=writer_outputs.get(slug) if from_idx >= step_order.index("qa_analyze") else None,
                        skip_perspektiv=from_step in ("writer", "qa_analyze"),
                        to_step=to_step,
                    )
                    packages.append(pkg)
                    self._write_debug_output(f"05-writer-{slug}.json", pkg.to_dict())
                except Exception as e:
                    logger.error("Failed to produce topic '%s': %s", assignment.id, e)
                    packages.append(TopicPackage(
                        id=assignment.id,
                        metadata={
                            "title": assignment.title,
                            "date": self.state.date,
                            "status": "failed",
                            "topic_slug": assignment.topic_slug,
                        },
                        status="failed",
                        error=str(e),
                    ))

        elif from_step == "bias_detector":
            # Run only the bias card step with all data loaded from debug output
            for i, assignment in enumerate(assignments):
                slug = assignment.topic_slug or assignment.id

                # Load article — prefer corrected version, fall back to writer output
                correction_file = f"07-writer-correction-{slug}.json"
                writer_file = f"05-writer-{slug}.json"
                article_data = self._load_debug_output(reuse, correction_file)
                if not article_data or not isinstance(article_data, dict):
                    article_data = self._load_debug_output(reuse, writer_file)
                if not article_data or not isinstance(article_data, dict):
                    logger.error("No article found for '%s'", slug)
                    continue
                # Writer debug output may be a full TopicPackage — extract the article
                article = article_data.get("article", article_data)

                # Load supporting data
                perspective_analysis = self._load_debug_output(reuse, f"04b-perspektiv-{slug}.json") or {}
                qa_analysis = self._load_debug_output(reuse, f"06-qa-analyze-{slug}.json") or {}
                research_dossier = self._load_debug_output(reuse, f"04-researcher-{slug}.json") or {}

                # Build bias card (Python, 0 tokens)
                bias_card = _build_bias_card(article, perspective_analysis, qa_analysis, research_dossier)

                # LLM language analysis
                if bias_language := self.agents.get("bias_language"):
                    result = await bias_language.run(
                        "Analyze this article text for linguistic bias patterns. "
                        "Then write a reader note that synthesizes the bias card data "
                        "with your language findings.",
                        context={"article_body": article.get("body", ""), "bias_card": bias_card},
                    )
                    self._track_agent(result, "bias_language", slug)
                    llm_result = _extract_dict(result) or {}
                    bias_card["language_bias"] = llm_result.get("language_bias", {})
                    bias_card["reader_note"] = llm_result.get("reader_note", "")

                self._write_debug_output(f"08-bias-card-{slug}.json", bias_card)

                packages.append(TopicPackage(
                    id=assignment.id,
                    metadata={
                        "title": assignment.title,
                        "date": self.state.date,
                        "status": "review",
                        "topic_slug": slug,
                    },
                    sources=article.get("sources", []),
                    article=article,
                    bias_analysis=bias_card,
                    status="review",
                ))

        # Skip verify and write_output if we stopped before writer
        writer_idx = step_order.index("writer")
        if to_idx < writer_idx:
            logger.info("Stopping after step '%s' as requested.", to_step)
            self.state.current_step = "done"
            await self._save_state()
            return packages

        # Verify and write output
        packages = await self.verify(packages)
        await self._write_output(packages)

        if to_step:
            logger.info("Stopping after step '%s' as requested.", to_step)

        self.state.current_step = "done"
        await self._save_state()

        return packages

    def _write_debug_output(self, filename: str, data: object) -> None:
        """Write intermediate step output as JSON for debugging."""
        out = Path(self.output_dir) / self.state.date
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Debug output: %s", filename)

    async def _save_state(self) -> None:
        """Save current pipeline state to disk."""
        path = Path(self.state_dir) / f"{self.state.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self.state)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load_incomplete_state(self, date: str) -> PipelineState | None:
        """Check for incomplete runs from the same date."""
        state_path = Path(self.state_dir)
        if not state_path.exists():
            return None
        for f in state_path.glob(f"run-{date}-*.json"):
            data = json.loads(f.read_text())
            state = PipelineState(**data)
            if state.current_step != "done":
                return state
        return None

    async def _write_output(self, packages: list[TopicPackage]) -> None:
        """Write completed TopicPackages as JSON to output_dir."""
        out = Path(self.output_dir) / self.state.date
        out.mkdir(parents=True, exist_ok=True)
        for pkg in packages:
            if pkg.status == "failed":
                continue
            path = out / f"{pkg.id}.json"
            path.write_text(
                json.dumps(pkg.to_dict(), indent=2, ensure_ascii=False)
            )
        # Also write a run summary
        summary_path = out / f"{self.state.run_id}-summary.json"
        summary = {
            "run_id": self.state.run_id,
            "date": self.state.date,
            "total_topics": len(packages),
            "completed": len([p for p in packages if p.status != "failed"]),
            "failed": len([p for p in packages if p.status == "failed"]),
            "packages": [p.id for p in packages],
        }
        summary_path.write_text(json.dumps(summary, indent=2))

        # Write agent stats (token usage, durations)
        if self._agent_stats:
            stats_path = out / f"{self.state.run_id}-stats.json"
            stats = {
                "run_id": self.state.run_id,
                "date": self.state.date,
                "agents": self._agent_stats,
                "total_tokens": sum(s["tokens_used"] for s in self._agent_stats),
                "total_duration_seconds": sum(s["duration_seconds"] for s in self._agent_stats),
            }
            stats_path.write_text(json.dumps(stats, indent=2))
