"""Independent Wire — Web page fetching tool."""

import logging

import httpx

from src.tools.registry import Tool

logger = logging.getLogger(__name__)


async def web_fetch_handler(url: str, max_chars: int = 10000) -> str:
    """Fetch a web page and return its text content."""
    logger.info("web_fetch: url=%r, max_chars=%d", url, max_chars)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(
                url, headers={"User-Agent": "IndependentWire/0.1"}
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        msg = f"Error: web_fetch timed out fetching {url}"
        logger.error(msg)
        return msg
    except httpx.HTTPStatusError as e:
        msg = f"Error: web_fetch got HTTP {e.response.status_code} for {url}"
        logger.error(msg)
        return msg
    except Exception as e:
        msg = f"Error: web_fetch failed for {url}: {e}"
        logger.error(msg)
        return msg

    text = response.text
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[Truncated at {max_chars} characters]"

    logger.info("web_fetch: got %d chars from %s", len(text), url)
    return text


web_fetch_tool = Tool(
    name="web_fetch",
    description="Fetch the content of a web page. Returns the page text.",
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum characters to return (default: 10000)",
                "default": 10000,
            },
        },
        "required": ["url"],
    },
    handler=web_fetch_handler,
)
