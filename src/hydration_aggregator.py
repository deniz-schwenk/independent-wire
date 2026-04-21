"""Independent Wire — Hydration Aggregator, dossier shaping, and merge logic.

Four public functions that compose the Hydration path between T1
(``src.hydration``) and the Researcher Assembler output. Each has a stable
contract; downstream code (T3 pipeline wiring) calls them in sequence:

    aggregator_output = await run_aggregator(assignment, hydration_results)
    pre_dossier = build_prepared_dossier(hydration_results, aggregator_output)
    coverage = build_coverage_summary(pre_dossier)
    merged = merge_dossiers(pre_dossier, web_search_dossier)

Only records with ``status == "success"`` from ``src.hydration`` participate
in the Aggregator call and the prepared-dossier shape. Partial/bot-blocked/
error records are filtered at the input boundary.

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

import logging
from collections import Counter
from typing import Any

from src.agent import Agent

logger = logging.getLogger(__name__)


AGGREGATOR_MODEL = "google/gemini-3-flash-preview"
AGGREGATOR_PROMPT_PATH = "agents/hydration_aggregator/AGENTS.md"
AGGREGATOR_TEMPERATURE = 0.3

# Rule-6 enum from agents/hydration_aggregator/AGENTS.md.
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

_AGGREGATOR_USER_MESSAGE = (
    "Analyze the hydrated articles in the provided context per the STEPS and "
    "RULES in your system prompt. Return a single JSON object with "
    "article_analyses, preliminary_divergences, and coverage_gaps."
)


class AggregatorValidationError(ValueError):
    """Raised when the Aggregator's response violates Rule 1 or Rule 6."""


# ---------- Function 1 — Aggregator call ----------

async def run_aggregator(
    assignment: dict[str, Any],
    hydration_results: list[dict[str, Any]],
    *,
    agent: Agent | None = None,
) -> dict[str, Any]:
    """Call the Hydration Aggregator LLM on the successful fetch records.

    Args:
        assignment: The Editor's topic assignment dict. The ``title`` and
            ``selection_reason`` fields are forwarded to the LLM; other keys
            are ignored.
        hydration_results: The full T1 output for one topic. Entries with
            ``status != "success"`` are filtered out before calling the LLM
            — the Aggregator prompt was tuned on full-text inputs and partial
            stubs would degrade quality.
        agent: Optional injected Agent instance, used for testing or to avoid
            re-instantiating on repeated calls. When ``None`` a fresh Agent
            is constructed with the default model and prompt path.

    Returns:
        A dict with exactly three keys: ``article_analyses`` (list of
        per-article dicts with ``article_index``, ``summary``, and
        ``actors_quoted``), ``preliminary_divergences`` (list of strings),
        ``coverage_gaps`` (list of strings). Matches the Aggregator prompt's
        output schema.

    Raises:
        AggregatorValidationError: The LLM response could not be parsed as
            JSON, omitted an input article's analysis (Rule 1), or included
            an actor with ``type`` outside the ten-value enum (Rule 6).
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

    articles = [
        {
            "url": r.get("url"),
            "title": r.get("title"),
            "outlet": r.get("outlet"),
            "language": r.get("language"),
            "country": r.get("country"),
            "extracted_text": r.get("extracted_text"),
            "estimated_date": None,
        }
        for r in successful
    ]
    payload = {
        "assignment": {
            "title": assignment.get("title"),
            "selection_reason": assignment.get("selection_reason"),
        },
        "articles": articles,
    }

    if agent is None:
        agent = Agent(
            name="hydration_aggregator",
            model=AGGREGATOR_MODEL,
            prompt_path=AGGREGATOR_PROMPT_PATH,
            temperature=AGGREGATOR_TEMPERATURE,
        )

    result = await agent.run(
        _AGGREGATOR_USER_MESSAGE,
        context=payload,
        output_schema={"type": "object"},
    )

    structured = result.structured
    if not isinstance(structured, dict):
        raise AggregatorValidationError(
            f"Aggregator returned no parseable JSON object for assignment "
            f"{assignment.get('title')!r}"
        )

    _validate_aggregator_output(structured, expected_count=len(articles))

    return {
        "article_analyses": structured["article_analyses"],
        "preliminary_divergences": list(
            structured.get("preliminary_divergences") or []
        ),
        "coverage_gaps": list(structured.get("coverage_gaps") or []),
    }


def _validate_aggregator_output(
    output: dict[str, Any],
    *,
    expected_count: int,
) -> None:
    analyses = output.get("article_analyses")
    if not isinstance(analyses, list):
        raise AggregatorValidationError(
            "article_analyses missing or not a list"
        )
    if len(analyses) != expected_count:
        raise AggregatorValidationError(
            f"Rule 1 violation: expected {expected_count} article_analyses, "
            f"got {len(analyses)}"
        )
    seen_indices: set[int] = set()
    for entry in analyses:
        if not isinstance(entry, dict):
            raise AggregatorValidationError(
                f"article_analyses entry is not an object: {entry!r}"
            )
        idx = entry.get("article_index")
        if not isinstance(idx, int):
            raise AggregatorValidationError(
                f"article_analyses entry missing integer article_index: {entry!r}"
            )
        seen_indices.add(idx)
        for actor in entry.get("actors_quoted") or []:
            if not isinstance(actor, dict):
                continue
            actor_type = actor.get("type")
            if actor_type not in ACTOR_TYPE_ENUM:
                raise AggregatorValidationError(
                    f"Rule 6 violation: invalid actor type {actor_type!r} "
                    f"(article_index={idx}, actor={actor.get('name')!r})"
                )
    if seen_indices != set(range(expected_count)):
        missing = sorted(set(range(expected_count)) - seen_indices)
        raise AggregatorValidationError(
            f"Rule 1 violation: article_index values do not cover "
            f"[0..{expected_count - 1}]; missing {missing}"
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
