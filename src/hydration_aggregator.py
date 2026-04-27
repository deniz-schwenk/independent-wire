"""Independent Wire — Hydration Aggregator, dossier shaping, and merge logic.

Four public functions that compose the Hydration path between T1
(``src.hydration``) and the Researcher Assembler output. Each has a stable
contract; downstream code (T3 pipeline wiring) calls them in sequence:

    aggregator_output = await run_aggregator(
        assignment, hydration_results,
        phase1_agent=..., phase2_agent=...,
    )
    pre_dossier = build_prepared_dossier(hydration_results, aggregator_output)
    coverage = build_coverage_summary(pre_dossier)
    merged = merge_dossiers(pre_dossier, web_search_dossier)

Only records with ``status == "success"`` from ``src.hydration`` participate
in the Aggregator call and the prepared-dossier shape. Partial/bot-blocked/
error records are filtered at the input boundary.

**Two-phase chunked execution.** ``run_aggregator`` splits the work:

    Phase 1 — per-chunk article analysis. Chunks of 5–10 articles run in
    parallel (asyncio.gather). Each chunk call returns only
    ``article_analyses[]``. Each chunk has up to 2 intelligent retries that
    re-request only the missing article indices. Fresh chunk failures
    (structural, or still missing after 2 retries) raise
    ``AggregatorValidationError``.

    Phase 2 — single cross-corpus reducer over the merged analyses.
    Produces ``preliminary_divergences[]`` + ``coverage_gaps[]``. No retry.

Phase 1 and Phase 2 are passed in as proper, separately-registered
``Agent`` instances so each phase carries its own model / temperature
/ provider configuration. When neither agent is supplied, defaults
that match the production registration are constructed inline.

**Canonical actor shape across the Hydration pipeline.** Actor objects carry
exactly five fields, in this order:

    {"name", "role", "type", "position", "verbatim_quote"}

``verbatim_quote`` is a string containing the actor's direct speech in the
article's original language when one was present in the hydrated full text,
or ``None`` when the actor was only paraphrased. Web-search-derived actors
always carry ``verbatim_quote: None`` — snippets do not produce trustworthy
verbatim quotes. ``merge_dossiers`` normalises the web-search side to this
shape before merging so downstream consumers can assume five fields
uniformly.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter
from typing import Any

from src.agent import Agent

logger = logging.getLogger(__name__)


AGGREGATOR_MODEL = "google/gemini-3-flash-preview"
AGGREGATOR_TEMPERATURE = 0.3

# Per-phase prompt paths under the two-file layout. Each phase
# resolves to its own (SYSTEM, INSTRUCTIONS) pair, used by callers
# that construct phase agents inline (e.g. eval scripts).
PHASE_PROMPT_PATHS: dict[str, tuple[str, str]] = {
    "phase1": (
        "agents/hydration_aggregator/PHASE1-SYSTEM.md",
        "agents/hydration_aggregator/PHASE1-INSTRUCTIONS.md",
    ),
    "phase2": (
        "agents/hydration_aggregator/PHASE2-SYSTEM.md",
        "agents/hydration_aggregator/PHASE2-INSTRUCTIONS.md",
    ),
}

PHASE2_MODEL = "anthropic/claude-opus-4.6"
PHASE2_TEMPERATURE = 0.1

# Rule-6 enum from PHASE1.md.
ACTOR_TYPE_ENUM: frozenset[str] = frozenset({
    "government",
    "legislature",
    "judiciary",
    "military",
    "industry",
    "civil_society",
    "academia",
    "media",
    "international_org",
    "affected_community",
})

_PHASE1_USER_MESSAGE = (
    "Analyze the articles in the provided context per the STEPS and RULES in "
    "your system prompt. Return a single JSON object with one field: "
    "article_analyses."
)
_PHASE2_USER_MESSAGE = (
    "Synthesize cross-article observations from the provided article_analyses "
    "and article_metadata. Return a single JSON object with "
    "preliminary_divergences and coverage_gaps."
)

_PHASE1_MAX_RETRIES = 2


class AggregatorValidationError(ValueError):
    """Raised when the Aggregator's response violates Rule 1 or Rule 6."""


# ---------- Function 1 — Aggregator call ----------

async def run_aggregator(
    assignment: dict[str, Any],
    hydration_results: list[dict[str, Any]],
    *,
    phase1_agent: Agent | None = None,
    phase2_agent: Agent | None = None,
) -> dict[str, Any]:
    """Call the Hydration Aggregator (two-phase chunked) on the successful fetch records.

    Args:
        assignment: The Editor's topic assignment dict. The ``title`` and
            ``selection_reason`` fields are forwarded to the LLM; other keys
            are ignored.
        hydration_results: The full T1 output for one topic. Entries with
            ``status != "success"`` are filtered out before calling the LLM
            — the Aggregator prompts are tuned on full-text inputs and
            partial stubs would degrade quality.
        phase1_agent: Pre-registered Phase 1 agent. When ``None`` a default
            (Gemini 3 Flash @ 0.3) is constructed inline.
        phase2_agent: Pre-registered Phase 2 agent. When ``None`` a default
            (Opus 4.6 @ 0.1) is constructed inline.

    Returns:
        A dict with exactly three keys: ``article_analyses`` (list of
        per-article dicts with ``article_index``, ``summary``, and
        ``actors_quoted``), ``preliminary_divergences`` (list of strings),
        ``coverage_gaps`` (list of strings). Matches the previous single-call
        schema so downstream code is unchanged.

    Raises:
        AggregatorValidationError: A Phase 1 chunk could not be completed
            after retries, Phase 2 returned unparseable JSON, or actor type
            enum was violated.
    """
    successful = [r for r in hydration_results if r.get("status") == "success"]
    if not successful:
        logger.info(
            "run_aggregator: zero successful records for assignment %r, "
            "skipping LLM call",
            assignment.get("title"),
        )
        return {
            "article_analyses": [],
            "preliminary_divergences": [],
            "coverage_gaps": [],
        }

    if phase1_agent is None:
        phase1_agent = _build_default_phase_agent("phase1")
    if phase2_agent is None:
        phase2_agent = _build_default_phase_agent("phase2")

    articles = [_prepare_article(r) for r in successful]
    chunks = _distribute_chunks(articles)

    for i, chunk in enumerate(chunks):
        logger.info(
            "Phase 1 chunk %d/%d: %d articles",
            i + 1, len(chunks), len(chunk),
        )

    phase1_results = await asyncio.gather(*[
        _run_phase1_chunk(
            assignment, chunk, chunk_idx=i + 1, agent=phase1_agent,
        )
        for i, chunk in enumerate(chunks)
    ])
    all_analyses = _merge_phase1_results(phase1_results, chunks)

    metadata = _build_article_metadata(successful)
    phase2 = await _run_phase2_reducer(
        assignment, all_analyses, metadata, agent=phase2_agent,
    )

    return {
        "article_analyses": all_analyses,
        "preliminary_divergences": phase2["preliminary_divergences"],
        "coverage_gaps": phase2["coverage_gaps"],
    }


# ---------- Phase 1 internals ----------

def _prepare_article(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": record.get("url"),
        "title": record.get("title"),
        "outlet": record.get("outlet"),
        "language": record.get("language"),
        "country": record.get("country"),
        "extracted_text": record.get("extracted_text"),
        "estimated_date": None,
    }


def _distribute_chunks(articles: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split articles into chunks of 5–10 items (1 chunk of N when N<5).

    Formula: ``num_chunks = max(1, ceil(N / 10))``. Remainder (``extras``)
    placed on the trailing chunks so chunks grow monotonically: e.g. N=11
    → [5, 6]; N=25 → [8, 8, 9].
    """
    n = len(articles)
    if n == 0:
        return []
    num_chunks = max(1, math.ceil(n / 10))
    base_size = n // num_chunks
    extras = n % num_chunks
    chunks: list[list[dict[str, Any]]] = []
    start = 0
    for i in range(num_chunks):
        size = base_size + (1 if i >= num_chunks - extras else 0)
        chunks.append(articles[start:start + size])
        start += size
    return chunks


async def _run_phase1_chunk(
    assignment: dict[str, Any],
    chunk_articles: list[dict[str, Any]],
    *,
    chunk_idx: int,
    agent: Agent,
) -> list[dict[str, Any]]:
    """Run one Phase-1 call with up to two intelligent-retry follow-ups.

    Retries re-request only the missing article indices (re-indexed from 0
    in the retry call). Returns per-chunk analyses sorted by chunk-local
    article_index (0..len(chunk_articles)-1).
    """
    analyses: list[dict[str, Any]] = []
    remaining_articles = list(chunk_articles)
    remaining_original_positions = list(range(len(chunk_articles)))

    for attempt in range(_PHASE1_MAX_RETRIES + 1):
        output = await _call_phase1(assignment, remaining_articles, agent=agent)
        returned, missing_local = _validate_phase1_output(
            output, expected_count=len(remaining_articles),
        )

        for a in returned:
            local_idx = a["article_index"]
            chunk_local_idx = remaining_original_positions[local_idx]
            a["article_index"] = chunk_local_idx
            analyses.append(a)

        if not missing_local:
            break

        if attempt < _PHASE1_MAX_RETRIES:
            missing_global = sorted(
                remaining_original_positions[i] for i in missing_local
            )
            logger.warning(
                "Phase 1 chunk %d retry %d: missing chunk-local indices %s",
                chunk_idx, attempt + 1, missing_global,
            )
            missing_sorted = sorted(missing_local)
            remaining_articles = [remaining_articles[i] for i in missing_sorted]
            remaining_original_positions = [
                remaining_original_positions[i] for i in missing_sorted
            ]

    if len(analyses) != len(chunk_articles):
        got = sorted(a["article_index"] for a in analyses)
        missing = sorted(set(range(len(chunk_articles))) - set(got))
        raise AggregatorValidationError(
            f"Rule 1 violation: chunk {chunk_idx} of {len(chunk_articles)} "
            f"articles got only {len(analyses)} analyses after "
            f"{_PHASE1_MAX_RETRIES} retries; still missing {missing}"
        )

    analyses.sort(key=lambda a: a["article_index"])
    return analyses


async def _call_phase1(
    assignment: dict[str, Any],
    articles: list[dict[str, Any]],
    *,
    agent: Agent,
) -> dict[str, Any]:
    payload = {
        "assignment": {
            "title": assignment.get("title"),
            "selection_reason": assignment.get("selection_reason"),
        },
        "articles": articles,
    }
    result = await agent.run(
        _PHASE1_USER_MESSAGE,
        context=payload,
        output_schema={"type": "object"},
    )
    structured = result.structured
    if not isinstance(structured, dict):
        raise AggregatorValidationError(
            f"Phase 1 chunk returned no parseable JSON object for assignment "
            f"{assignment.get('title')!r}"
        )
    return structured


def _validate_phase1_output(
    output: dict[str, Any],
    *,
    expected_count: int,
) -> tuple[list[dict[str, Any]], set[int]]:
    """Extract valid analyses and report missing chunk-local indices.

    Returns ``(analyses, missing_indices)``. Rule 6 (actor type enum) still
    raises — it is a structural content error that retry cannot fix.
    """
    analyses_raw = output.get("article_analyses")
    if not isinstance(analyses_raw, list):
        raise AggregatorValidationError(
            "article_analyses missing or not a list"
        )
    valid: list[dict[str, Any]] = []
    seen: set[int] = set()
    for entry in analyses_raw:
        if not isinstance(entry, dict):
            continue
        idx = entry.get("article_index")
        if not isinstance(idx, int) or not (0 <= idx < expected_count):
            continue
        if idx in seen:
            continue
        for actor in entry.get("actors_quoted") or []:
            if not isinstance(actor, dict):
                continue
            actor_type = actor.get("type")
            if actor_type not in ACTOR_TYPE_ENUM:
                raise AggregatorValidationError(
                    f"Rule 6 violation: invalid actor type {actor_type!r} "
                    f"(article_index={idx}, actor={actor.get('name')!r})"
                )
        seen.add(idx)
        valid.append(entry)
    missing = set(range(expected_count)) - seen
    return valid, missing


def _merge_phase1_results(
    phase1_results: list[list[dict[str, Any]]],
    chunks: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten chunk outputs to a single globally-indexed analyses array.

    Each chunk's per-article ``article_index`` is in [0..chunk_size-1]; the
    merged output rewrites to [0..N-1] across the full input corpus,
    preserving chunk order as provided by ``_distribute_chunks``.
    """
    merged: list[dict[str, Any]] = []
    global_offset = 0
    for chunk_analyses, chunk_articles in zip(phase1_results, chunks):
        for a in chunk_analyses:
            rewritten = dict(a)
            rewritten["article_index"] = a["article_index"] + global_offset
            merged.append(rewritten)
        global_offset += len(chunk_articles)
    merged.sort(key=lambda a: a["article_index"])
    return merged


# ---------- Phase 2 internals ----------

def _build_article_metadata(
    successful: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "article_index": i,
            "language": r.get("language"),
            "country": r.get("country"),
            "outlet": r.get("outlet"),
        }
        for i, r in enumerate(successful)
    ]


async def _run_phase2_reducer(
    assignment: dict[str, Any],
    all_analyses: list[dict[str, Any]],
    article_metadata: list[dict[str, Any]],
    *,
    agent: Agent,
) -> dict[str, Any]:
    if not all_analyses:
        return {"preliminary_divergences": [], "coverage_gaps": []}
    payload = {
        "assignment": {
            "title": assignment.get("title"),
            "selection_reason": assignment.get("selection_reason"),
        },
        "article_analyses": all_analyses,
        "article_metadata": article_metadata,
    }
    logger.info("Phase 2 reducer: %d analyses input", len(all_analyses))
    result = await agent.run(
        _PHASE2_USER_MESSAGE,
        context=payload,
        output_schema={"type": "object"},
    )
    structured = result.structured
    if not isinstance(structured, dict):
        raise AggregatorValidationError(
            f"Phase 2 reducer returned no parseable JSON object for assignment "
            f"{assignment.get('title')!r}"
        )
    return {
        "preliminary_divergences": list(
            structured.get("preliminary_divergences") or []
        ),
        "coverage_gaps": list(structured.get("coverage_gaps") or []),
    }


# ---------- Default agent constructors ----------

def _build_default_phase_agent(phase: str) -> Agent:
    """Construct a default per-phase Agent when the caller omits one.

    Phase 1 defaults to Gemini 3 Flash @ 0.3 (per Session-12 eval); Phase 2
    defaults to Opus 4.6 @ 0.1 (variant B, 114/120). Use a registered Agent
    instance from the agents dict in production — these defaults exist for
    test scripts and other callers that don't carry a Pipeline context.
    """
    try:
        system_path, instructions_path = PHASE_PROMPT_PATHS[phase]
    except KeyError as exc:
        raise ValueError(
            f"_build_default_phase_agent: unknown phase {phase!r}; "
            f"expected one of {sorted(PHASE_PROMPT_PATHS)}"
        ) from exc

    if phase == "phase1":
        return Agent(
            name="hydration_aggregator_phase1",
            model=AGGREGATOR_MODEL,
            system_prompt_path=system_path,
            instructions_path=instructions_path,
            temperature=AGGREGATOR_TEMPERATURE,
            max_tokens=32000,
            provider="openrouter",
            reasoning="none",
        )
    return Agent(
        name="hydration_aggregator_phase2",
        model=PHASE2_MODEL,
        system_prompt_path=system_path,
        instructions_path=instructions_path,
        temperature=PHASE2_TEMPERATURE,
        max_tokens=32000,
        provider="openrouter",
        reasoning="none",
    )


# ---------- Function 2 — Build prepared dossier ----------

def build_prepared_dossier(
    hydration_results: list[dict[str, Any]],
    aggregator_output: dict[str, Any],
) -> dict[str, Any]:
    """Merge T1 fetch records and Aggregator output into a Researcher-shaped dossier.

    Args:
        hydration_results: The same T1 records passed to ``run_aggregator``.
            Only ``status == "success"`` entries are used.
        aggregator_output: The return value of ``run_aggregator``.

    Returns:
        A dict shaped like the Researcher Assembler's output, extended with
        verbatim quotes:
        ``{sources: [...], preliminary_divergences: [...], coverage_gaps: [...]}``.
        Each source entry carries:
        ``{id, url, title, outlet, language, country, summary, estimated_date,
        actors_quoted}``.

        ``id`` values are assigned sequentially starting at ``rsrc-001``.
        ``estimated_date`` is always ``None`` at this stage (date extraction
        is not part of T2). ``title`` is pass-through from the T1 record and
        will typically be ``None`` because T1 does not extract titles.

        Each actor object inside ``actors_quoted`` carries exactly five
        fields in this order: ``name``, ``role``, ``type``, ``position``,
        ``verbatim_quote``. The ``verbatim_quote`` value is passed through
        unchanged from the Aggregator — a string when the article contained
        direct speech from that actor, or ``None`` when only paraphrased.
    """
    successful = [r for r in hydration_results if r.get("status") == "success"]
    analyses_by_index: dict[int, dict[str, Any]] = {
        entry["article_index"]: entry
        for entry in aggregator_output.get("article_analyses") or []
        if isinstance(entry, dict) and isinstance(entry.get("article_index"), int)
    }

    sources: list[dict[str, Any]] = []

    for i, record in enumerate(successful):
        analysis = analyses_by_index.get(i, {})
        actors_out: list[dict[str, Any]] = []
        for actor in analysis.get("actors_quoted") or []:
            if not isinstance(actor, dict):
                continue
            quote = actor.get("verbatim_quote")
            if not isinstance(quote, str) or not quote:
                quote = None
            actors_out.append({
                "name": actor.get("name", ""),
                "role": actor.get("role", ""),
                "type": actor.get("type", ""),
                "position": actor.get("position", ""),
                "verbatim_quote": quote,
            })
        sources.append({
            "id": f"rsrc-{i + 1:03d}",
            "url": record.get("url"),
            "title": record.get("title"),
            "outlet": record.get("outlet"),
            "language": record.get("language"),
            "country": record.get("country"),
            "summary": analysis.get("summary", ""),
            "estimated_date": None,
            "actors_quoted": actors_out,
        })

    return {
        "sources": sources,
        "preliminary_divergences": list(
            aggregator_output.get("preliminary_divergences") or []
        ),
        "coverage_gaps": list(aggregator_output.get("coverage_gaps") or []),
    }


# ---------- Function 3 — Build coverage summary ----------

def build_coverage_summary(prepared_dossier: dict[str, Any]) -> dict[str, Any]:
    """Compute the compact coverage summary for the Hydrated Researcher Planner.

    Args:
        prepared_dossier: The return value of ``build_prepared_dossier``.

    Returns:
        A dict with exactly five keys:
        ``total_sources`` (int),
        ``languages_covered`` (mapping iso_code → count),
        ``countries_covered`` (mapping country name → count),
        ``stakeholder_types_present`` (mapping actor type → count),
        ``coverage_gaps`` (list of strings, pass-through).

        All three count-dicts are ordered by descending count, then
        alphabetically for ties. Output is deterministic for a given input.
    """
    sources = prepared_dossier.get("sources") or []

    languages: Counter[str] = Counter()
    countries: Counter[str] = Counter()
    stakeholder_types: Counter[str] = Counter()

    for source in sources:
        language = source.get("language")
        if language:
            languages[language] += 1
        country = source.get("country")
        if country:
            countries[country] += 1
        for actor in source.get("actors_quoted") or []:
            if not isinstance(actor, dict):
                continue
            actor_type = actor.get("type")
            if actor_type:
                stakeholder_types[actor_type] += 1

    return {
        "total_sources": len(sources),
        "languages_covered": _sorted_counter(languages),
        "countries_covered": _sorted_counter(countries),
        "stakeholder_types_present": _sorted_counter(stakeholder_types),
        "coverage_gaps": list(prepared_dossier.get("coverage_gaps") or []),
    }


def _sorted_counter(counter: Counter[str]) -> dict[str, int]:
    # Descending count, ascending key for ties. dict in Python 3.7+ preserves
    # insertion order, so the returned dict iterates in the documented order.
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return {key: count for key, count in items}


# ---------- Function 4 — Merge dossiers ----------

def merge_dossiers(
    pre_dossier: dict[str, Any],
    web_dossier: dict[str, Any],
) -> dict[str, Any]:
    """Combine a Pre-Dossier and a Web-Search Dossier into one unified dossier.

    Args:
        pre_dossier: Output of ``build_prepared_dossier`` (or any dict in
            the Researcher Assembler shape).
        web_dossier: Researcher Assembler output covering gaps the hydration
            path did not reach (same shape).

    Returns:
        A dossier in the same shape. The merge policy is:

        - Web-search source actors are first normalised to the five-field
          canonical actor shape (``name``, ``role``, ``type``, ``position``,
          ``verbatim_quote``) with ``verbatim_quote`` forced to ``None``.
          Snippets cannot produce trustworthy verbatim quotes; this
          guarantees every actor in the merged output has uniformly five
          fields. The caller's ``web_dossier`` dict is not mutated.
        - Sources: pre-dossier entries first, then web-search entries whose
          ``url`` is not already in the pre-dossier. IDs are reassigned
          sequentially across the concatenated list starting at ``rsrc-001``.
          Original IDs from both inputs are overwritten.
        - ``preliminary_divergences`` / ``coverage_gaps``: concatenated, then
          deduplicated by case-insensitive whitespace-trimmed string match
          (first occurrence wins). No semantic matching.

        If both input source lists are empty, returns an empty dossier.
    """
    pre_sources = list(pre_dossier.get("sources") or [])
    web_sources = [
        _normalise_web_source_actors(source)
        for source in (web_dossier.get("sources") or [])
    ]

    blocklist: set[str] = {
        source["url"]
        for source in pre_sources
        if isinstance(source, dict) and source.get("url")
    }
    filtered_web = [
        source
        for source in web_sources
        if isinstance(source, dict) and source.get("url") not in blocklist
    ]

    combined: list[dict[str, Any]] = []
    for i, source in enumerate(pre_sources + filtered_web):
        new_source = dict(source)
        new_source["id"] = f"rsrc-{i + 1:03d}"
        combined.append(new_source)

    merged_divergences = _dedup_strings(
        list(pre_dossier.get("preliminary_divergences") or [])
        + list(web_dossier.get("preliminary_divergences") or [])
    )
    merged_gaps = _dedup_strings(
        list(pre_dossier.get("coverage_gaps") or [])
        + list(web_dossier.get("coverage_gaps") or [])
    )

    dropped = len(web_sources) - len(filtered_web)
    if dropped:
        logger.debug(
            "merge_dossiers: filtered %d web-search source(s) whose URL "
            "already appears in the pre-dossier",
            dropped,
        )

    return {
        "sources": combined,
        "preliminary_divergences": merged_divergences,
        "coverage_gaps": merged_gaps,
    }


def _normalise_web_source_actors(source: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of ``source`` with actors coerced to the five-field shape.

    Web-search-derived actors always carry ``verbatim_quote: None`` because
    snippet-based extraction cannot produce trustworthy direct quotes. The
    caller's dict is not mutated.
    """
    if not isinstance(source, dict):
        return source
    normalised = dict(source)
    actors = source.get("actors_quoted") or []
    rebuilt: list[dict[str, Any]] = []
    for actor in actors:
        if not isinstance(actor, dict):
            continue
        rebuilt.append({
            "name": actor.get("name", ""),
            "role": actor.get("role", ""),
            "type": actor.get("type", ""),
            "position": actor.get("position", ""),
            "verbatim_quote": None,
        })
    normalised["actors_quoted"] = rebuilt
    return normalised


def _dedup_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
