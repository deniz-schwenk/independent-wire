"""Independent Wire — Tool system."""

from src.tools.registry import Tool, ToolRegistry
from src.tools.web_search import web_search_tool, x_search_tool
from src.tools.web_fetch import web_fetch_tool
from src.tools.file_ops import read_file_tool, write_file_tool


def create_default_registry() -> ToolRegistry:
    """Create a ToolRegistry with all built-in tools registered."""
    registry = ToolRegistry()
    registry.register(web_search_tool)
    registry.register(x_search_tool)
    registry.register(web_fetch_tool)
    registry.register(read_file_tool)
    registry.register(write_file_tool)
    return registry


__all__ = [
    "Tool",
    "ToolRegistry",
    "web_search_tool",
    "x_search_tool",
    "web_fetch_tool",
    "read_file_tool",
    "write_file_tool",
    "create_default_registry",
]
