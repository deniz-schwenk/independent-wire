"""Independent Wire — Multi-provider web search tool."""

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from openai import AsyncOpenAI

from src.tools.registry import Tool

logger = logging.getLogger(__name__)

# Repo root — for the merge-mode provenance channel map, which is written next
# to the per-topic run artifacts under ``output/{date}/_state/{run_id}/`` (the
# production ``output_dir`` is ``ROOT/output``; see scripts/run.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Default provider, overridable via env var.
# Interim flip (2026-07-06, TASK-SEARCH-PROVIDER-FLIP): default is `ollama`
# (flat-rate subscription, $0 marginal) instead of `perplexity` (Sonar) — a
# cost-driven bridge ahead of the registry endgame; basis in
# scratch/registry-shadow/BACKTEST-3ARM-REPORT.md (QUALIFIED GO).
# ONE-LINE REVERT: set `IW_SEARCH_PROVIDER=perplexity` in the environment (the
# perplexity/Sonar code path is retained deliberately as the revert target).
DEFAULT_PROVIDER = os.environ.get("IW_SEARCH_PROVIDER", "ollama")


def effective_search_provider(provider: str | None = None) -> str:
    """The provider that will ACTUALLY serve a query, accounting for the one
    silent-substitution path: ``ollama`` with no ``OLLAMA_API_KEY`` falls back
    to DuckDuckGo (see :func:`_search_ollama`). Every other provider surfaces
    its own missing-key error rather than swapping provider, so the configured
    name is the served name. Used for loud ``provider_used`` logging on the
    search stage — the fallback must never be silent (TASK-SEARCH-PROVIDER-FLIP
    condition 2)."""
    p = (provider or DEFAULT_PROVIDER).strip().lower()
    if p == "ollama" and not os.environ.get("OLLAMA_API_KEY"):
        return "duckduckgo"
    return p


def _format_results(query: str, items: list[dict[str, Any]], n: int) -> str:
    """Format search results into consistent plaintext output."""
    if not items:
        return f"No results for: {query}"
    lines = [f"Results for: {query}\n"]
    for i, item in enumerate(items[:n], 1):
        title = item.get("title", "").strip()
        url = item.get("url", "")
        snippet = item.get("content", "").strip()
        lines.append(f"{i}. {title}\n   {url}")
        if snippet:
            lines.append(f"   {snippet}")
    return "\n".join(lines)


async def _search_perplexity(query: str, n: int) -> str:
    """Search via Perplexity sonar-pro on OpenRouter. No extra API key needed."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return "Error: OPENROUTER_API_KEY not set"

    client = AsyncOpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    try:
        response = await client.chat.completions.create(
            model="perplexity/sonar-pro",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a web search assistant. Search for the query and return "
                        "structured results. For each result include: title, URL, and a "
                        "brief summary. Return results as a JSON array with objects having "
                        "'title', 'url', and 'content' keys. Be factual and concise."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Search for: {query}\n\nReturn up to {n} results.",
                },
            ],
            temperature=0.1,
            max_tokens=4096,
        )
        return response.choices[0].message.content or "No results found"
    except Exception as e:
        return f"Error: Perplexity search failed: {e}"


async def _search_brave(query: str, n: int) -> str:
    """Search via Brave Search API. Needs BRAVE_API_KEY."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        logger.warning("BRAVE_API_KEY not set, falling back to DuckDuckGo")
        return await _search_duckduckgo(query, n)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": n},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": api_key,
                },
                timeout=10.0,
            )
            r.raise_for_status()
        items = [
            {
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "content": x.get("description", ""),
            }
            for x in r.json().get("web", {}).get("results", [])
        ]
        return _format_results(query, items, n)
    except Exception as e:
        return f"Error: Brave search failed: {e}"


async def _search_grok_web(query: str, n: int) -> str:
    """Search via xAI Grok web_search. Needs XAI_API_KEY.

    Uses the xAI Responses API with server-side web_search tool.
    Grok searches the web autonomously and returns results with citations.
    """
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        logger.warning("XAI_API_KEY not set, falling back to DuckDuckGo")
        return await _search_duckduckgo(query, n)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.x.ai/v1/responses",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": "grok-3-fast",
                    "input": [
                        {
                            "role": "user",
                            "content": (
                                f"Search the web for: {query}\n\n"
                                f"Return the top {n} results with title, URL, and brief summary for each."
                            ),
                        }
                    ],
                    "tools": [{"type": "web_search"}],
                },
                timeout=30.0,
            )
            r.raise_for_status()

        data = r.json()
        output = data.get("output", [])
        text_parts = []
        for item in output:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))

        return "\n".join(text_parts) if text_parts else "No results found"
    except Exception as e:
        return f"Error: Grok web search failed: {e}"


async def _search_grok_x(query: str, n: int) -> str:
    """Search X/Twitter via xAI Grok x_search. Needs XAI_API_KEY.

    Searches posts, users, and threads on X. Useful for finding
    social media perspectives and narratives on a topic.
    """
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return "Error: XAI_API_KEY not set (required for X/Twitter search)"

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.x.ai/v1/responses",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json={
                    "model": "grok-3-fast",
                    "input": [
                        {
                            "role": "user",
                            "content": (
                                f"Search X/Twitter for: {query}\n\n"
                                f"Return the top {n} relevant posts with author, content, and any key context."
                            ),
                        }
                    ],
                    "tools": [{"type": "x_search"}],
                },
                timeout=30.0,
            )
            r.raise_for_status()

        data = r.json()
        output = data.get("output", [])
        text_parts = []
        for item in output:
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        text_parts.append(content.get("text", ""))

        return "\n".join(text_parts) if text_parts else "No results found"
    except Exception as e:
        return f"Error: Grok X search failed: {e}"


async def _search_ollama(query: str, n: int) -> str:
    """Search via Ollama Web Search API. Needs OLLAMA_API_KEY."""
    api_key = os.environ.get("OLLAMA_API_KEY")
    if not api_key:
        logger.warning(
            "web_search: OLLAMA_API_KEY missing — falling back to DuckDuckGo "
            "(provider_used=duckduckgo). Set OLLAMA_API_KEY, or "
            "IW_SEARCH_PROVIDER=perplexity to revert to Sonar."
        )
        return await _search_duckduckgo(query, n)

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://ollama.com/api/web_search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query},
                timeout=15.0,
            )
            r.raise_for_status()

        items = r.json().get("results", [])
        return _format_results(query, items, n)
    except Exception as e:
        return f"Error: Ollama search failed: {e}"


async def _search_duckduckgo(query: str, n: int) -> str:
    """Search via DuckDuckGo. No API key needed. Fallback provider."""
    try:
        import asyncio

        from ddgs import DDGS

        ddgs = DDGS(timeout=10)
        raw = await asyncio.to_thread(ddgs.text, query, max_results=n)
        if not raw:
            return f"No results for: {query}"
        items = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "content": r.get("body", ""),
            }
            for r in raw
        ]
        return _format_results(query, items, n)
    except ImportError:
        return (
            "Error: DuckDuckGo search requires 'duckduckgo-search' package "
            "(pip install duckduckgo-search)"
        )
    except Exception as e:
        return f"Error: DuckDuckGo search failed: {e}"


async def _search_registry(query: str, n: int) -> str:
    """Deterministic, LLM-free retrieval over the catalog's on_demand feeds.

    Implemented in :mod:`src.tools.registry_search` (Phase A2). $0/query;
    returns the same plain-text block shape as the Sonar path. Not active in
    production until IW_SEARCH_PROVIDER is flipped (a later phase)."""
    from src.tools.registry_search import _search_registry as _impl

    return await _impl(query, n)


# ─────────────────────────────────────────────────────────────────────────────
# `merge` provider — registry + web arm, deterministic Python-side dedup/merge
#
# Transition state (gate review 2026-07-13, D1): runs BOTH the curated registry
# arm (:func:`_search_registry`, $0, dated-by-construction) and the current web
# arm (:func:`_search_ollama`, with its own DuckDuckGo fallback) concurrently,
# then merges + dedups in Python. No LLM is involved in the merge — dedup,
# ordering and channel provenance are all deterministic (Principle 1,
# deterministic-before-LLM). Replacement of the web arm by the registry is the
# end goal; see BACKLOG-WEBSEARCH-SUNSET.md for the sunset criterion.
#
# URL-normalization rule (dedup key — documented here, exercised in
# tests/test_web_search_merge.py):
#   1. scheme dropped entirely  → http and https forms of one URL collide;
#   2. host lowercased, a leading ``www.`` stripped;
#   3. fragment (``#...``) dropped;
#   4. known tracking params dropped (``utm_*``, ``fbclid``, ``gclid``,
#      ``mc_cid``/``mc_eid``, ``igshid``, ``ref``/``ref_src``, ``cmpid``,
#      ``icid``, ``ncid``, ``spm``, ``yclid``, ``_hsenc``/``_hsmi``), remaining
#      params sorted for a stable key;
#   5. a trailing ``/`` on a non-root path stripped.
# The DISPLAYED url is always the un-normalized original of the winning arm.
#
# Ordering rule (deterministic): registry results first (curated / auditable /
# 100 %-dated channel), then web results, each arm in the order its provider
# returned; a web result whose normalized key matches any registry result is
# dropped (REGISTRY WINS on duplicate — it is dated by construction). Given
# fixed arm outputs the merged block is byte-identical across runs.
# ─────────────────────────────────────────────────────────────────────────────

# Query params that carry no resource identity — dropped before building the
# dedup key so tracking-decorated duplicates collapse.
_TRACKING_PARAMS: frozenset[str] = frozenset(
    {
        "fbclid", "gclid", "dclid", "yclid", "msclkid",
        "mc_cid", "mc_eid", "igshid", "ref", "ref_src", "referrer",
        "cmpid", "icid", "ncid", "spm", "vero_id", "vero_conv",
        "_hsenc", "_hsmi", "mkt_tok", "wt_mc", "ito", "cmp", "at_medium",
    }
)

# Entry / URL / snippet line shapes emitted by ``_format_results`` — parsing its
# own output back into items is the inverse of ``_format_results`` (kept in sync
# with topic_stages._ENTRY_PATTERN, which parses the identical block shape).
_MERGE_ENTRY_RE = re.compile(r"^\d+\.\s+(.+)$")
_MERGE_URL_RE = re.compile(r"^\s{3}(https?://\S+)\s*$")


def _normalize_url_key(url: str) -> str:
    """Return the canonical dedup key for ``url`` (see the module rule above).

    Deterministic and side-effect-free. Not the displayed URL — only the
    equality key used to detect cross-arm duplicates."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = (parts.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_PARAMS)
    ]
    kept.sort()
    query = urlencode(kept)
    # scheme dropped (empty) so http/https collide; fragment dropped.
    return urlunsplit(("", host, path, query, ""))


def _parse_result_block(text: str) -> list[dict[str, Any]]:
    """Inverse of :func:`_format_results`: a plain-text results block → items.

    Handles the 2-line (no snippet) and 3-line (with snippet) entry shapes and
    yields ``{"title", "url", "content"}`` dicts. ``No results``/``Error``
    blocks contain no numbered entries and parse to ``[]`` — so a failed arm
    contributes nothing without special-casing."""
    items: list[dict[str, Any]] = []
    if not text:
        return items
    lines = text.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        m = _MERGE_ENTRY_RE.match(lines[i])
        if not m:
            i += 1
            continue
        url_m = _MERGE_URL_RE.match(lines[i + 1]) if i + 1 < n else None
        if not url_m:
            i += 1
            continue
        title = m.group(1).strip()
        url = url_m.group(1).strip()
        snippet = ""
        j = i + 2
        # A snippet line is 3-space-indented, not itself a URL and not a new
        # numbered entry (guards against a URL-less entry running together).
        if (
            j < n
            and lines[j].startswith("   ")
            and not _MERGE_URL_RE.match(lines[j])
            and not _MERGE_ENTRY_RE.match(lines[j].strip())
        ):
            snippet = lines[j].strip()
            j += 1
        items.append({"title": title, "url": url, "content": snippet})
        i = j
    return items


def _merge_results(
    registry_items: list[dict[str, Any]], web_items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Deterministically merge the two arms (registry-first, registry-wins).

    Returns ``(merged_items, provenance)`` where provenance is a list of
    ``(displayed_url, channel)`` in merged order (``channel`` ∈
    {``registry``, ``web_search``})."""
    merged: list[dict[str, Any]] = []
    provenance: list[tuple[str, str]] = []
    seen: set[str] = set()
    for channel, items in (("registry", registry_items), ("web_search", web_items)):
        for it in items:
            url = (it.get("url") or "").strip()
            if not url:
                continue
            key = _normalize_url_key(url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(it)
            provenance.append((url, channel))
    return merged, provenance


# ── merge provenance channel map (deterministic groundwork for D3) ────────────
# Process-level url→channel accumulator. The merge provider is called once per
# query and has no topic context; the researcher_search stage (which does)
# resets it before a topic's query loop and drains it after, then writes the
# per-topic artifact. Registry never downgrades to web_search.
_MERGE_PROVENANCE: dict[str, str] = {}

# Loud, machine-readable stats from the most recent merge call (parallels
# registry_search._LAST_STATS — the tool boundary can only return a string).
_LAST_MERGE_STATS: dict[str, Any] = {}


def reset_merge_provenance() -> None:
    """Clear the process-level url→channel accumulator (per-topic isolation)."""
    _MERGE_PROVENANCE.clear()


def drain_merge_provenance() -> dict[str, str]:
    """Return a copy of the accumulated url→channel map and clear it."""
    snapshot = dict(_MERGE_PROVENANCE)
    _MERGE_PROVENANCE.clear()
    return snapshot


def _record_provenance(provenance: list[tuple[str, str]]) -> None:
    for url, channel in provenance:
        if _MERGE_PROVENANCE.get(url) == "registry":
            continue  # registry never downgrades to web_search
        _MERGE_PROVENANCE[url] = channel


def write_provenance_channel_map(
    run_date: str,
    run_id: str,
    topic_key: str,
    provenance: dict[str, str],
    output_root: Path | None = None,
) -> Path | None:
    """Write the per-topic ``url→channel`` artifact next to the run's per-topic
    Bus snapshots (``output/{run_date}/_state/{run_id}/``).

    Deterministic (Python stamps it — no agent emits it; D3 groundwork). Returns
    the written path, or ``None`` when there is nothing to write or the run
    identifiers are absent (best-effort — a missing run_date/run_id skips the
    write rather than raising)."""
    if not provenance or not run_date or not run_id:
        return None
    root = Path(output_root) if output_root is not None else (_REPO_ROOT / "output")
    state_dir = root / run_date / "_state" / run_id
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"provenance_channel_map.{topic_key}.json"
    channel_map = dict(sorted(provenance.items()))
    payload = {
        "provider": "merge",
        "topic_key": topic_key,
        "channel_map": channel_map,
        "counts": {
            "registry": sum(1 for c in channel_map.values() if c == "registry"),
            "web_search": sum(1 for c in channel_map.values() if c == "web_search"),
            "total": len(channel_map),
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


async def _search_merge(query: str, n: int) -> str:
    """The `merge` provider: registry arm + web (Ollama) arm, deterministic
    Python merge. Signature matches every other provider (``query``, ``n``);
    returns the standard plain-text block so researcher stages cannot tell a
    merged result from a single-provider one. Transition state (D1)."""
    registry_raw, web_raw = await asyncio.gather(
        _search_registry(query, n),
        _search_ollama(query, n),
        return_exceptions=True,
    )
    if isinstance(registry_raw, BaseException):
        logger.warning("web_search[merge]: registry arm failed: %s", registry_raw)
        registry_raw = ""
    if isinstance(web_raw, BaseException):
        logger.warning("web_search[merge]: web arm failed: %s", web_raw)
        web_raw = ""

    registry_items = _parse_result_block(registry_raw)
    web_items = _parse_result_block(web_raw)
    merged, provenance = _merge_results(registry_items, web_items)
    _record_provenance(provenance)

    # Format the full merged set (no truncation — surfacing both arms' unique
    # contributions is the point of merge); the block shape is identical.
    output = _format_results(query, merged, len(merged))

    dedup_dropped = (len(registry_items) + len(web_items)) - len(merged)
    _LAST_MERGE_STATS.clear()
    _LAST_MERGE_STATS.update(
        {
            "search_provider_used": "merge",
            "query": query,
            "registry_results": len(registry_items),
            "web_results": len(web_items),
            "merged_results": len(merged),
            "dedup_dropped": dedup_dropped,
            "cost_usd": 0.0,
        }
    )
    logger.info(
        "web_search[merge]: search_provider_used=merge registry_results=%d "
        "web_results=%d merged_results=%d dedup_dropped=%d cost_usd=0.0 query=%r",
        len(registry_items),
        len(web_items),
        len(merged),
        dedup_dropped,
        query,
    )
    return output


# Provider dispatch map
PROVIDERS: dict[str, Any] = {
    "perplexity": _search_perplexity,
    "brave": _search_brave,
    "grok": _search_grok_web,
    "grok_x": _search_grok_x,
    "ollama": _search_ollama,
    "duckduckgo": _search_duckduckgo,
    "registry": _search_registry,
    "merge": _search_merge,
}


async def web_search_handler(
    query: str,
    num_results: int = 5,
    provider: str | None = None,
) -> str:
    """Search the web using the configured or specified provider.

    Providers:
    - ollama: Ollama Web Search API, uses OLLAMA_API_KEY (default since 2026-07-06)
    - perplexity: Via OpenRouter, uses OPENROUTER_API_KEY (revert target)
    - brave: Brave Search API, uses BRAVE_API_KEY
    - grok: xAI Grok web search, uses XAI_API_KEY
    - grok_x: xAI Grok X/Twitter search, uses XAI_API_KEY
    - duckduckgo: Free, no API key needed (ollama's missing-key fallback)
    - registry: Deterministic $0 retrieval over the on_demand catalog (A2)
    - merge: registry + web (Ollama) arms, deterministic Python dedup (D1)
    """
    p = (provider or DEFAULT_PROVIDER).strip().lower()
    n = min(max(num_results, 1), 10)

    search_fn = PROVIDERS.get(p)
    if not search_fn:
        return f"Error: Unknown search provider '{p}'. Available: {', '.join(PROVIDERS.keys())}"

    logger.info("web_search: provider=%s, query=%r, num_results=%d", p, query, n)
    result = await search_fn(query, n)
    logger.info("web_search: got %d chars response", len(result))
    return result


# --- Tool definitions for ToolRegistry ---

web_search_tool = Tool(
    name="web_search",
    description=(
        "Search the web for current information. Returns results with titles, URLs, and summaries. "
        "Supports multiple providers: ollama (default), perplexity, brave, grok, duckduckgo."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
            "num_results": {
                "type": "integer",
                "description": "Number of results to return (default: 5, max: 10)",
                "default": 5,
            },
            "provider": {
                "type": "string",
                "description": (
                    "Search provider: perplexity, brave, grok, grok_x, ollama, "
                    "duckduckgo, registry, merge "
                    "(default: from IW_SEARCH_PROVIDER env or ollama)"
                ),
                "enum": [
                    "perplexity", "brave", "grok", "grok_x", "ollama",
                    "duckduckgo", "registry", "merge",
                ],
            },
        },
        "required": ["query"],
    },
    handler=web_search_handler,
)

# Separate tool for X/Twitter search (agents that need social media analysis)
x_search_tool = Tool(
    name="x_search",
    description=(
        "Search X (Twitter) for posts, users, and threads on a topic. "
        "Useful for finding social media perspectives and narratives. "
        "Requires XAI_API_KEY."
    ),
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
    handler=lambda query, num_results=5: _search_grok_x(query, num_results),
)
