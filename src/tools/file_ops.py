"""Independent Wire — File operation tools."""

import logging
from pathlib import Path

from src.tools.registry import Tool

logger = logging.getLogger(__name__)


def read_file_handler(path: str) -> str:
    """Read contents of a file."""
    logger.info("read_file: path=%r", path)
    try:
        content = Path(path).read_text(encoding="utf-8")
        logger.info("read_file: read %d chars from %s", len(content), path)
        return content
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: Could not read {path}: {e}"


def write_file_handler(path: str, content: str) -> str:
    """Write content to a file. Creates directories if needed."""
    logger.info("write_file: path=%r, %d chars", path, len(content))
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        logger.info("write_file: wrote %d chars to %s", len(content), path)
        return f"Successfully wrote {len(content)} characters to {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: Could not write {path}: {e}"


read_file_tool = Tool(
    name="read_file",
    description="Read contents of a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read"},
        },
        "required": ["path"],
    },
    handler=read_file_handler,
)

write_file_tool = Tool(
    name="write_file",
    description="Write content to a file. Creates directories if needed.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to write to"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    },
    handler=write_file_handler,
)
