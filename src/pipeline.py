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

    async def run(self, date: str | None = None) -> list[TopicPackage]:
        """Execute the full pipeline. Returns completed TopicPackages."""
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

        if "curate" not in self.state.completed_steps:
            self.state.current_step = "curate"
            await self._save_state()
            curated_topics = await self.curate(raw_findings)
            self.state.curated_topics = curated_topics
            self.state.completed_steps.append("curate")
            await self._save_state()

        if "editorial_conference" not in self.state.completed_steps:
            self.state.current_step = "editorial_conference"
            await self._save_state()
            assignments = await self.editorial_conference(curated_topics)
            self.state.assignments = [asdict(a) for a in assignments]
            self.state.completed_steps.append("editorial_conference")
            await self._save_state()

            # Gate check after editorial conference (full mode only)
            gate_ok = await self.gate("editorial_conference", assignments)
            if not gate_ok:
                raise PipelineGateRejected(
                    "Gate rejected after editorial_conference"
                )

        if "produce" not in self.state.completed_steps:
            self.state.current_step = "produce"
            await self._save_state()
            packages = await self.produce(assignments)
            self.state.packages = [asdict(p) for p in packages]
            self.state.completed_steps.append("produce")
            await self._save_state()

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
        """Scan current news sources and return raw findings."""
        agent = self.agents.get("collector")
        if not agent:
            logger.error("No 'collector' agent configured")
            return []

        message = (
            f"Today's date is {self.state.date}. "
            "Scan current news sources and return a JSON array of findings. "
            "Each finding should have: title, summary, source_url, source_name, "
            "language, region."
        )

        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "source_url": {"type": "string"},
                    "source_name": {"type": "string"},
                    "language": {"type": "string"},
                    "region": {"type": "string"},
                },
            },
        }

        try:
            result = await agent.run(message, output_schema=schema)
            parsed = _extract_list(result)
            if parsed is not None:
                return parsed
            logger.warning("Collector returned non-list output")
            return []
        except Exception as e:
            logger.error("Collector failed: %s", e)
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

        message = (
            "Review these raw findings. Select the most newsworthy topics. "
            "For each selected topic provide: title, topic_slug, relevance_score, "
            "summary, source_ids."
        )

        # Truncate findings to avoid context overflow (Issue A)
        trimmed = [
            {"title": f.get("title", ""), "summary": f.get("summary", ""),
             "source_name": f.get("source_name", "")}
            for f in raw_findings[:40]
        ]

        try:
            result = await agent.run(
                message, context={"findings": trimmed}
            )
            topics = _extract_list(result) or []

            # Sort by relevance_score (descending) and limit
            topics.sort(
                key=lambda t: t.get("relevance_score", 0), reverse=True
            )
            return topics[: self.max_topics]
        except Exception as e:
            logger.error("Curator failed: %s", e)
            return []

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
        self, assignments: list[TopicAssignment]
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
                pkg = await self._produce_single(assignment)
                packages.append(pkg)
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
        self, assignment: TopicAssignment
    ) -> TopicPackage:
        """Produce a single TopicPackage from an assignment."""
        assignment_data = asdict(assignment)
        perspectives: list[dict] = []
        article: dict = {}
        bias_analysis: dict = {}
        sources: list[dict] = []

        # 1. Perspektiv-Agent (optional)
        if perspektiv := self.agents.get("perspektiv"):
            result = await perspektiv.run(
                "Research the spectrum of perspectives on this topic.",
                context=assignment_data,
            )
            perspectives = _extract_list(result) or []

        # 2. Writer (required)
        writer = self.agents.get("writer")
        if not writer:
            raise PipelineStepError(
                f"No 'writer' agent for topic '{assignment.id}'"
            )

        writer_context = {**assignment_data, "perspectives": perspectives}
        result = await writer.run(
            "Write a multi-perspective article on this topic.",
            context=writer_context,
        )
        article = _extract_dict(result) or {
            "headline": assignment.title,
            "body": result.content,
        }

        # 3. Bias Detector (optional)
        if bias_detector := self.agents.get("bias_detector"):
            result = await bias_detector.run(
                "Analyze this article for bias across all five dimensions.",
                context={"article": article, "sources": sources},
            )
            bias_analysis = _extract_dict(result) or {}

        # 4. QA/Faktencheck (optional)
        if qa := self.agents.get("qa"):
            result = await qa.run(
                "Verify all factual claims in this article.",
                context={"article": article, "sources": sources},
            )
            sources = _extract_list(result) or []

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
            sources=sources,
            perspectives=perspectives,
            article=article,
            bias_analysis=bias_analysis,
            transparency={
                "selection_reason": assignment.selection_reason,
                "confidence": "medium",
                "pipeline_run": {
                    "run_id": self.state.run_id if self.state else "",
                    "date": self.state.date if self.state else "",
                },
            },
            status="review",
        )

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

        return packages

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
