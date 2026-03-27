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
