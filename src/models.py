"""Independent Wire — Data models."""

from dataclasses import dataclass, field


@dataclass
class AgentResult:
    """What an agent returns."""

    content: str
    structured: dict | None = None
    tool_calls: list[dict] = field(default_factory=list)
    tokens_used: int = 0
    cost_usd: float = 0.0
    model: str = ""
    duration_seconds: float = 0.0


@dataclass
class TopicAssignment:
    """A topic assigned by Chefredaktion to be processed."""

    id: str  # e.g. "tp-2026-03-30-001"
    title: str
    priority: int  # 1-10
    topic_slug: str
    selection_reason: str
    raw_data: dict = field(default_factory=dict)  # data from Kurator


@dataclass
class TopicPackage:
    """The atomic output unit — a complete topic with all layers."""

    id: str
    metadata: dict
    sources: list[dict] = field(default_factory=list)
    perspectives: list[dict] = field(default_factory=list)
    divergences: list[dict] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    article: dict = field(default_factory=dict)
    bias_analysis: dict = field(default_factory=dict)
    visualizations: list[dict] = field(default_factory=list)
    transparency: dict = field(default_factory=dict)
    status: str = "draft"  # draft/review/published/rejected/failed
    error: str | None = None  # error message if status=="failed"

    def to_dict(self) -> dict:
        """Serialize to dict matching topic-package-v1.json schema."""
        return {
            "id": self.id,
            "version": "1.0",
            "metadata": self.metadata,
            "sources": self.sources,
            "perspectives": self.perspectives,
            "divergences": self.divergences,
            "gaps": self.gaps,
            "article": self.article,
            "bias_analysis": self.bias_analysis,
            "visualizations": self.visualizations,
            "transparency": self.transparency,
        }


@dataclass
class PipelineState:
    """Checkpoint state for pipeline resumption."""

    run_id: str
    date: str
    current_step: str  # which step we're at
    completed_steps: list[str] = field(default_factory=list)
    raw_findings: list[dict] = field(default_factory=list)
    curated_topics: list[dict] = field(default_factory=list)
    assignments: list[dict] = field(default_factory=list)
    packages: list[dict] = field(default_factory=list)  # serialized TopicPackages
    started_at: str = ""  # ISO timestamp
    error: str | None = None
