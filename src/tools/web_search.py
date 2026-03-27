"""Independent Wire — Web search tool via Perplexity on OpenRouter."""

import logging
import os

from openai import AsyncOpenAI, APIStatusError

from src.tools.registry import Tool

logger = logging.getLogger(__name__)


async def web_search_handler(query: str, num_results: int = 5) -> str:
    """Search the web using Perplexity via OpenRouter.

    Makes an LLM call to perplexity/sonar-pro which searches the web
    and returns results with citations.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "Error: OPENROUTER_API_KEY not set"

    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    logger.info("web_search: query=%r, num_results=%d", query, num_results)

    try:
        response = await client.chat.completions.create(
            model="perplexity/sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a web search assistant. Search for the query and return "
                        "structured results. For each result include: title, URL, and a "
                        "brief summary. Return results as a JSON array. Include the source "
                        "URLs. Be factual and concise."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Search for: {query}\n\nReturn up to {num_results} results.",
                },
            ],
            temperature=0.1,
            max_tokens=4096,
        )
    except APIStatusError as e:
        msg = f"Error: web_search API call failed ({e.status_code}): {e.message}"
        logger.error(msg)
        return msg
    except Exception as e:
        msg = f"Error: web_search failed: {e}"
        logger.error(msg)
        return msg

    result = response.choices[0].message.content or "No results found"
    logger.info("web_search: got %d chars response", len(result))
    return result


web_search_tool = Tool(
    name="web_search",
    description="Search the web for current information. Returns results with titles, URLs, and summaries.",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    handler=web_search_handler,
)
