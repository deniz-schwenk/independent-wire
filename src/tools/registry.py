"""Independent Wire — Tool system."""

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    """A callable function that agents can invoke during LLM interaction."""

    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[..., Any]

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return result as string."""
        if inspect.iscoroutinefunction(self.handler):
            result = await self.handler(**kwargs)
        else:
            result = await asyncio.to_thread(self.handler, **kwargs)
        return str(result)

    def to_openai_format(self) -> dict:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Manages available tools. Each agent gets a filtered subset."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_for_agent(self, allowed: list[str]) -> list[Tool]:
        return [self._tools[n] for n in allowed if n in self._tools]

    def to_openai_format(self, allowed: list[str]) -> list[dict]:
        return [t.to_openai_format() for t in self.get_for_agent(allowed)]
