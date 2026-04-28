"""Independent Wire — Pipeline orchestration.

A Pipeline calls Agents in a defined sequence, passes data between steps,
persists state to disk, and continues on individual topic failures.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from src.agent import Agent
from src.models import PipelineState, TopicAssignment, TopicPackage

logger = logging.getLogger(__name__)


def _slugify(title: str) -> str:
    """Deterministic ASCII-fold slug for topic_slug generation.

    Lowercase, NFKD-fold to drop accents, replace any non-``\\w`` run with
    ``-``, collapse repeats, strip edges, then truncate to 60 chars at the
    nearest hyphen-delimited word boundary. Returns ``""`` when the title
    is empty or yields no slug-safe characters.
    """
    if not title:
        return ""
    normalized = unicodedata.normalize("NFKD", title)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    s = ascii_only.lower()
    s = re.sub(r"[^\w]+", "-", s, flags=re.ASCII)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-_")
    if len(s) > 60:
        s = s[:60]
        last_hyphen = s.rfind("-")
        if last_hyphen >= 30:
            s = s[:last_hyphen]
        s = s.strip("-_")
    return s


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output.

    Handles variations: ```json, ```, ```JSON, triple backticks with language tags,
    and multiple code fence blocks (takes the first one).
    """
    text = text.strip()
    # Full wrap: ```json ... ``` or ``` ... ```
    match = re.match(r"^```(?:\w+)?\s*\n(.*?)\n\s*```\s*$", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Partial: starts with fence but no closing (truncated output)
    match = re.match(r"^```(?:\w+)?\s*\n(.*)", text, re.DOTALL)
    if match:
        inner = match.group(1).strip()
        # Remove trailing ``` if present somewhere inside
        inner = re.sub(r"\n\s*```\s*$", "", inner)
        return inner
    return text


def _extract_date_from_url(url: str) -> str | None:
    """Extract publication date from common news URL patterns.

    Most news outlets embed dates in URLs:
    - /2026/04/14/  (path segments)
    - /2026-04-14/  (ISO in path)
    - /20260414/    (compact)
    - /article/2026/04/  (year/month only)

    Returns ISO date string (YYYY-MM-DD) or None if no date found.
    """
    # Pattern 1: /YYYY/MM/DD/ or /YYYY-MM-DD/
    m = re.search(r'/(\d{4})[/-](\d{2})[/-](\d{2})(?:/|[^0-9])', url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # Pattern 2: /YYYYMMDD/ (compact, e.g. some Asian outlets)
    m = re.search(r'/(\d{4})(\d{2})(\d{2})(?:/|[^0-9]|$)', url)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2020 <= y <= 2030 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    # Pattern 3: /YYYY/MM/ (year and month only, no day)
    m = re.search(r'/(\d{4})[/-](\d{2})(?:/|[^0-9])', url)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 2020 <= y <= 2030 and 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-01"

    return None


def _sanitize_null_strings(obj: dict | list | str | None) -> dict | list | str | None:
    """Recursively replace LLM-generated string 'null'/'None'/'N/A'/'' with actual None.

    LLMs sometimes write "null" as a string instead of the JSON null value.
    This is valid JSON but causes visible 'null' labels in rendered output.
    Only applies to string values — does not affect keys, numbers, or booleans.
    """
    if isinstance(obj, dict):
        return {k: _sanitize_null_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_null_strings(item) for item in obj]
    if isinstance(obj, str) and obj.strip().lower() in ("null", "none", "n/a", ""):
        return None
    return obj


def _extract_list(result: object) -> list[dict] | None:
    """Extract a list from an AgentResult (structured or content)."""
    if result.structured and isinstance(result.structured, list):
        return result.structured
    try:
        cleaned = _strip_code_fences(result.content)
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        # Some LLMs wrap lists in an object: {"findings": [...]}
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    return v
    except (json.JSONDecodeError, ValueError):
        pass
    # Last resort: find JSON array in prose
    try:
        cleaned = _strip_code_fences(result.content)
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 4: use json_repair for LLM-typical malformed JSON
    try:
        from json_repair import repair_json
        repaired = repair_json(result.content, return_objects=True)
        if isinstance(repaired, list):
            logger.info("_extract_list: recovered JSON via json_repair")
            return repaired
    except Exception:
        pass

    return None


def _extract_dict(result: object) -> dict | None:
    """Extract a dict from an AgentResult (structured or content).

    Tries multiple fallback strategies for common LLM output issues:
    1. Structured output (already parsed)
    2. Strip code fences and parse
    3. Find first { to last } and parse that substring
    4. Use Agent._parse_json() for trailing comma removal and truncation repair
    """
    if result.structured and isinstance(result.structured, dict):
        return result.structured

    content = (result.content or "").strip()
    if not content:
        return None

    # Attempt 1: strip code fences and parse directly
    try:
        cleaned = _strip_code_fences(content)
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Attempt 2: find first { to last } in the raw content
    first_brace = content.find("{")
    if first_brace >= 0:
        last_brace = content.rfind("}")
        if last_brace > first_brace:
            try:
                parsed = json.loads(content[first_brace:last_brace + 1])
                if isinstance(parsed, dict):
                    logger.info("_extract_dict: recovered JSON via brace extraction")
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass

    # Attempt 3: use Agent._parse_json() which handles trailing commas and truncation
    try:
        from src.agent import Agent
        parsed = Agent._parse_json(content)
        if isinstance(parsed, dict):
            logger.info("_extract_dict: recovered JSON via Agent._parse_json")
            return parsed
    except Exception:
        pass

    # Attempt 4: use json_repair for LLM-typical malformed JSON
    try:
        from json_repair import repair_json
        repaired = repair_json(content, return_objects=True)
        if isinstance(repaired, dict):
            logger.info("_extract_dict: recovered JSON via json_repair")
            return repaired
    except Exception:
        pass

    return None


def _deduplicate_search_results(search_results: list[dict]) -> list[dict]:
    """Deduplicate search results by URL, merging query sources.

    Parses URLs from the raw plaintext search results (format: "N. title\\n   url\\n   snippet").
    If the same URL appears in results from multiple queries, keeps the entry with the
    longest snippet and records all queries that found it.
    """
    # Parse individual results from each search result block
    url_pattern = re.compile(r"^\s{3}(https?://\S+)", re.MULTILINE)
    # Pattern to extract numbered entries: "N. title\n   url\n   snippet"
    entry_pattern = re.compile(
        r"^\d+\.\s+(.+)\n\s{3}(https?://\S+)\n\s{3}(.+?)(?=\n\d+\.\s|\nResults for:|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    # Map URL → best entry info
    url_map: dict[str, dict] = {}  # url → {title, snippet, found_by}

    for sr in search_results:
        raw = sr.get("results", "")
        query_str = sr.get("query", "")

        for match in entry_pattern.finditer(raw):
            title = match.group(1).strip()
            url = match.group(2).strip()
            snippet = match.group(3).strip()

            if url in url_map:
                url_map[url]["found_by"].append(query_str)
                # Keep the longer snippet
                if len(snippet) > len(url_map[url]["snippet"]):
                    url_map[url]["snippet"] = snippet
                    url_map[url]["title"] = title
            else:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "found_by": [query_str],
                }

    # Rebuild search results with deduplicated entries
    deduped: list[dict] = []
    seen_urls: set[str] = set()

    for sr in search_results:
        raw = sr.get("results", "")
        query_str = sr.get("query", "")

        # Rebuild the results text, skipping URLs already emitted
        new_lines = []
        entry_num = 1
        for match in entry_pattern.finditer(raw):
            url = match.group(2).strip()
            if url in seen_urls:
                continue
            seen_urls.add(url)
            info = url_map.get(url, {})
            title = info.get("title", match.group(1).strip())
            snippet = info.get("snippet", match.group(3).strip())
            found_by = info.get("found_by", [query_str])
            found_by_note = ""
            if len(found_by) > 1:
                other_queries = [q for q in found_by if q != query_str]
                found_by_note = f"\n   [Also found by: {'; '.join(other_queries)}]"
            new_lines.append(f"{entry_num}. {title}\n   {url}\n   {snippet}{found_by_note}")
            entry_num += 1

        if new_lines:
            header = f"Results for: {query_str}"
            new_entry = dict(sr)
            new_entry["results"] = header + "\n\n" + "\n\n".join(new_lines)
            deduped.append(new_entry)
        elif not entry_pattern.search(raw):
            # No parseable entries (e.g., "No results" or error) — keep as-is
            deduped.append(sr)

    duplicates_removed = sum(len(v["found_by"]) - 1 for v in url_map.values() if len(v["found_by"]) > 1)
    if duplicates_removed:
        logger.info("Deduplication: removed %d duplicate URLs across queries", duplicates_removed)

    return deduped


# ISO language code → English name. Used for the Python-rendered
# meta-transparency sentence that replaces the Writer's [[COVERAGE_STATEMENT]]
# placeholder. Unknown codes fall back to "[code]".
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "sv": "Swedish",
    "no": "Norwegian", "da": "Danish", "fi": "Finnish", "el": "Greek",
    "tr": "Turkish", "ru": "Russian", "uk": "Ukrainian", "pl": "Polish",
    "cs": "Czech", "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian",
    "sr": "Serbian", "hr": "Croatian", "ar": "Arabic", "fa": "Persian",
    "he": "Hebrew", "ur": "Urdu", "hi": "Hindi", "bn": "Bengali",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "vi": "Vietnamese",
    "th": "Thai", "id": "Indonesian", "ms": "Malay", "sw": "Swahili",
}

# Canonical country-name lookup. RSS feeds and agent outputs mix short and
# long forms ("USA" vs "United States"). All downstream deduplication and
# missing-country detection runs on the normalised key so "US" and
# "United States" aggregate into one bucket.
COUNTRY_ALIASES: dict[str, str] = {
    "us": "United States", "usa": "United States",
    "u.s.": "United States", "u.s.a.": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom", "u.k.": "United Kingdom",
    "great britain": "United Kingdom", "britain": "United Kingdom",
    "uae": "United Arab Emirates", "u.a.e.": "United Arab Emirates",
    "prc": "China", "people's republic of china": "China",
    "roc": "Taiwan", "rok": "South Korea",
    "dprk": "North Korea",
    "russia": "Russia", "russian federation": "Russia",
    "drc": "Democratic Republic of the Congo",
    "dr congo": "Democratic Republic of the Congo",
    "czechia": "Czech Republic",
}


def _normalise_country(name: str | None) -> str:
    """Normalise a country name to its canonical long form.

    Returns an empty string for None / empty input. Unknown names are
    returned stripped but otherwise unchanged so custom labels from feed
    metadata survive. Tries multiple lookup keys to absorb common
    punctuation variants ("U.S.", "US", "US.", "u.s").
    """
    if not name or not isinstance(name, str):
        return ""
    stripped = name.strip()
    if not stripped:
        return ""
    # Reject multi-country markers — guessing is worse than missing.
    if re.search(r"[/,&]|\band\b|\bund\b", stripped, re.IGNORECASE):
        return ""
    lower = stripped.lower()
    for candidate in (lower, lower.rstrip("."), lower.replace(".", "")):
        if candidate in COUNTRY_ALIASES:
            return COUNTRY_ALIASES[candidate]
    return stripped


_LANGUAGE_NAME_TO_CODE: dict[str, str] = {
    name.lower(): code for code, name in LANGUAGE_NAMES.items()
}


def _normalise_language(value: str | None) -> str:
    """Return the ISO 639-1 lowercase code for a language value.

    Accepts either an ISO code ("en") or an English language name
    ("English"). Unknown inputs are returned stripped and lowercased
    so downstream string comparisons remain stable; they are not
    blanked, because custom language tags (e.g. "zh-Hant") are
    legitimate even when not in the canonical table.
    """
    if not value or not isinstance(value, str):
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    if v in LANGUAGE_NAMES:
        return v
    return _LANGUAGE_NAME_TO_CODE.get(v, v)


def _language_name(code: str | None) -> str:
    """ISO code → English name; unknown codes echo as '[code]'."""
    if not code or not isinstance(code, str):
        return "[unknown]"
    key = code.strip().lower()
    if not key:
        return "[unknown]"
    return LANGUAGE_NAMES.get(key, f"[{key}]")


def _render_coverage_statement(sources: list[dict]) -> str:
    """Generate the meta-transparency sentence from the final source array.

    Shape: "This report draws on {N} sources in {M} languages:
    {language_list}." Language list is English names in frequency order
    (most sources first), comma-separated with "and" before the last.
    """
    n = len(sources)
    counts: dict[str, int] = {}
    for source in sources:
        code = (source.get("language") or "").strip().lower()
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
    # Frequency order (desc), alphabetical for ties.
    ordered_codes = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    names = [_language_name(code) for code, _ in ordered_codes]
    m = len(names)
    if m == 0:
        lang_phrase = "an unspecified language"
        return f"This report draws on {n} sources in {lang_phrase}."
    if m == 1:
        lang_list = names[0]
    elif m == 2:
        lang_list = f"{names[0]} and {names[1]}"
    else:
        lang_list = ", ".join(names[:-1]) + f", and {names[-1]}"
    return f"This report draws on {n} sources in {m} languages: {lang_list}."


def _substitute_coverage_statement(article: dict) -> None:
    """Replace the Writer's ``[[COVERAGE_STATEMENT]]`` placeholder with a
    Python-rendered sentence based on the final source array. Mutates
    ``article['body']`` in place. Idempotent when the placeholder is absent.
    """
    body = article.get("body")
    if not isinstance(body, str) or "[[COVERAGE_STATEMENT]]" not in body:
        return
    statement = _render_coverage_statement(article.get("sources", []))
    article["body"] = body.replace("[[COVERAGE_STATEMENT]]", statement)


_WRITER_SOURCE_METADATA_FIELDS = (
    "url", "title", "outlet", "language", "country", "estimated_date",
)

# Internal-only keys carried on merged source objects through the
# renumber/QA chain. ``rsrc_id`` survives renumbering so Fix-3 can
# rewrite ``rsrc-NNN`` → ``src-NNN`` in Perspektiv source_ids;
# ``web_id`` is dropped at renumber time. Both are stripped before TP
# serialization — never appear in the final Topic Package JSON.
_INTERNAL_RSRC_ID_KEY = "rsrc_id"
_INTERNAL_WEB_ID_KEY = "web_id"


def _merge_writer_sources(
    writer_refs: list, research_dossier: dict,
) -> list[dict]:
    """Build full source objects from Writer references + research dossier.

    The Writer emits two source-entry shapes:

    * Dossier reference: ``{"rsrc_id": "rsrc-NNN"}`` — exactly one field.
      Resolved against ``research_dossier.sources[]`` by id; the merged
      object carries the dossier metadata plus the internal ``rsrc_id``
      stash so Fix-3 (perspective source_ids rewrite) can map back.
    * Web-search source: ``{"web_id": "web-N", "url", "outlet",
      "title", "language", "country"}`` — exactly six fields. Passed
      through with the ``web_id`` stash for renumber-time citation
      rewriting.

    The ``id`` field is **not** set by this function — renumbering owns
    the final ``src-NNN`` assignment.

    Unknown ``rsrc_id`` references and entries missing both stash keys
    log WARNING and are skipped.
    """
    dossier_by_id: dict[str, dict] = {}
    for src in research_dossier.get("sources", []) or []:
        if not isinstance(src, dict):
            continue
        sid = src.get("id")
        if isinstance(sid, str) and sid:
            dossier_by_id[sid] = src

    merged: list[dict] = []
    for ref in writer_refs or []:
        if not isinstance(ref, dict):
            continue
        rsrc_id = ref.get("rsrc_id")
        web_id = ref.get("web_id")

        if rsrc_id:
            dossier_src = dossier_by_id.get(rsrc_id)
            if not dossier_src:
                logger.warning(
                    "Writer references unknown rsrc_id=%s; skipping",
                    rsrc_id,
                )
                continue
            merged_src: dict = {}
            for field in _WRITER_SOURCE_METADATA_FIELDS:
                if field in dossier_src:
                    merged_src[field] = dossier_src[field]
            merged_src[_INTERNAL_RSRC_ID_KEY] = rsrc_id
            merged.append(merged_src)
            continue

        if web_id:
            web_src: dict = {}
            for field in _WRITER_SOURCE_METADATA_FIELDS:
                if field in ref:
                    web_src[field] = ref[field]
            web_src[_INTERNAL_WEB_ID_KEY] = web_id
            merged.append(web_src)
            continue

        logger.warning(
            "Writer source entry has neither rsrc_id nor web_id; skipping: %r",
            ref,
        )
    return merged


_RSRC_CITATION_RE = re.compile(r"\[rsrc-(\d+)\]")
_WEB_CITATION_RE = re.compile(r"\[web-(\d+)\]")
# Kept for post-finalisation tooling (e.g. ``scripts/test_pipeline_hygiene.py``)
# that walks finalized Topic Packages where citations are already in
# ``src-NNN`` form.
_SRC_CITATION_RE = re.compile(r"\[src-(\d+)\]")

_ARTICLE_TEXT_FIELDS = ("headline", "subheadline", "body", "summary")


def _collect_cited_src_ids(article: dict) -> set[str]:
    """Return every ``src-NNN`` token cited across the article text fields.

    Use this on **finalized** Topic Packages where renumbering has
    already produced ``src-NNN`` citations. For Writer-stage outputs
    (``[rsrc-NNN]`` / ``[web-N]`` tokens), use
    :func:`_collect_cited_writer_refs` instead.
    """
    cited: set[str] = set()
    for field in _ARTICLE_TEXT_FIELDS:
        text = article.get(field) or ""
        if not isinstance(text, str):
            continue
        for match in _SRC_CITATION_RE.finditer(text):
            cited.add(f"src-{match.group(1).zfill(3)}")
    return cited


def _collect_cited_writer_refs(article: dict) -> set[str]:
    """Return every ``rsrc-NNN`` and ``web-N`` token cited in article text.

    Tokens are returned in their stash-canonical form: ``rsrc-NNN``
    zero-padded to three digits (matching the dossier's ``rsrc-001``
    convention); ``web-N`` left un-padded (matching the Writer's
    ``web-1``/``web-2`` style).
    """
    cited: set[str] = set()
    for field in _ARTICLE_TEXT_FIELDS:
        text = article.get(field) or ""
        if not isinstance(text, str):
            continue
        for match in _RSRC_CITATION_RE.finditer(text):
            cited.add(f"rsrc-{match.group(1).zfill(3)}")
        for match in _WEB_CITATION_RE.finditer(text):
            cited.add(f"web-{int(match.group(1))}")
    return cited


def _renumber_and_prune_sources(
    article: dict, sources: list[dict], slug: str = "",
) -> tuple[dict, list[dict], dict[str, str]]:
    """Drop unreferenced sources and renumber survivors to ``src-NNN``.

    Consumes the merged sources from :func:`_merge_writer_sources`
    (each carrying an internal ``rsrc_id`` xor ``web_id`` stash) and
    the article body's ``[rsrc-NNN]`` / ``[web-N]`` citations.

    Sources whose stash token does not appear in the body are dropped
    (INFO log per drop). Survivors are renumbered to ``src-001``,
    ``src-002``, … in their **current array order** (Writer's editorial
    decision, not body-citation order). All four text fields
    (``headline``, ``subheadline``, ``body``, ``summary``) get both
    ``[rsrc-N]`` and ``[web-N]`` tokens rewritten to their final
    ``[src-NNN]`` form atomically.

    Returns ``(new_article, new_sources, rename_map)`` where
    ``rename_map`` is keyed by the original stash token (``rsrc-001``
    or ``web-1``) and valued by the final ``src-NNN`` id.

    Each survivor receives ``id = "src-NNN"``. The ``rsrc_id`` stash is
    **kept** on dossier survivors (Fix-3 needs it); the ``web_id``
    stash is dropped here since no downstream code references it.

    If every source would be dropped, the inputs are returned unchanged
    with an empty rename map and a WARNING — emptying the array masks
    upstream breakage worse than orphan citations.
    """
    import copy

    if not isinstance(sources, list) or not sources:
        return article, sources, {}

    cited_tokens = _collect_cited_writer_refs(article)

    surviving_stashes: list[str] = []
    surviving_sources: list[dict] = []
    dropped_count = 0
    for src in sources:
        if not isinstance(src, dict):
            continue
        if rsrc := src.get(_INTERNAL_RSRC_ID_KEY):
            stash = rsrc
        elif web := src.get(_INTERNAL_WEB_ID_KEY):
            stash = web
        else:
            dropped_count += 1
            logger.info(
                "Fix-1[%s]: dropping source with no stash token (%s)",
                slug, src.get("outlet", "?"),
            )
            continue
        if stash in cited_tokens:
            surviving_stashes.append(stash)
            surviving_sources.append(src)
        else:
            dropped_count += 1
            logger.info(
                "Fix-1[%s]: dropping unreferenced source %s (%s)",
                slug, stash, src.get("outlet", "?"),
            )

    if not surviving_sources:
        logger.warning(
            "Fix-1[%s]: every source is unreferenced — keeping pre-fix "
            "state rather than emptying the array",
            slug,
        )
        return article, sources, {}

    rename_map: dict[str, str] = {}
    new_sources: list[dict] = []
    for new_index, src in enumerate(surviving_sources, start=1):
        new_id = f"src-{new_index:03d}"
        rename_map[surviving_stashes[new_index - 1]] = new_id
        new_src = copy.deepcopy(src)
        new_src["id"] = new_id
        new_src.pop(_INTERNAL_WEB_ID_KEY, None)
        new_sources.append(new_src)

    new_article = copy.deepcopy(article)
    if rename_map:
        def _rewrite_rsrc(match: re.Match) -> str:
            stash = f"rsrc-{match.group(1).zfill(3)}"
            return f"[{rename_map.get(stash, stash)}]"

        def _rewrite_web(match: re.Match) -> str:
            stash = f"web-{int(match.group(1))}"
            return f"[{rename_map.get(stash, stash)}]"

        for field in _ARTICLE_TEXT_FIELDS:
            value = new_article.get(field)
            if isinstance(value, str) and value:
                value = _RSRC_CITATION_RE.sub(_rewrite_rsrc, value)
                value = _WEB_CITATION_RE.sub(_rewrite_web, value)
                new_article[field] = value

    if dropped_count or rename_map:
        logger.info(
            "Fix-1[%s]: dropped %d unreferenced source(s); "
            "renumbered %d survivor(s)",
            slug, dropped_count, len(new_sources),
        )
    return new_article, new_sources, rename_map


def _convert_rsrc_to_src_in_perspectives(
    perspective_analysis: dict,
    final_sources: list[dict],
    slug: str = "",
) -> dict:
    """Rewrite ``rsrc-NNN`` references in the enriched Perspektiv V2 output
    to the matching final ``src-NNN``.

    Walks ``position_clusters[*].source_ids`` and each
    ``position_clusters[*].actors[*].source_ids`` (and
    ``position_clusters[*].source_ids_aggregate`` if present). Uses the
    internal ``rsrc_id`` stashed on each merged source by
    :func:`_merge_writer_sources`. Unmapped entries (a cluster or actor
    references a source that did not survive to the final array) are
    dropped. A cluster whose ``source_ids`` become empty after rewriting
    is dropped from the output entirely — once the backing sources are
    gone, the position has no evidence in the final TP. Actors whose
    own ``source_ids`` are empty after rewriting are kept (the cluster's
    position still stands).
    """
    import copy

    if not perspective_analysis or not isinstance(perspective_analysis, dict):
        return perspective_analysis

    rsrc_to_src: dict[str, str] = {}
    for src in final_sources or []:
        if not isinstance(src, dict):
            continue
        rsrc = src.get(_INTERNAL_RSRC_ID_KEY)
        final_id = src.get("id")
        if isinstance(rsrc, str) and isinstance(final_id, str) and rsrc and final_id:
            rsrc_to_src[rsrc] = final_id

    if not rsrc_to_src:
        return perspective_analysis

    synced = copy.deepcopy(perspective_analysis)

    def _rewrite(ids: list) -> list[str]:
        out: list[str] = []
        for sid in ids or []:
            if not isinstance(sid, str):
                continue
            if sid in rsrc_to_src:
                out.append(rsrc_to_src[sid])
            elif sid.startswith("rsrc-"):
                continue  # orphaned — drop
            else:
                out.append(sid)  # already src-NNN or custom — pass through
        return out

    surviving: list[dict] = []
    for cluster in synced.get("position_clusters", []) or []:
        if not isinstance(cluster, dict):
            continue
        cluster["source_ids"] = _rewrite(cluster.get("source_ids") or [])
        if "source_ids_aggregate" in cluster:
            cluster["source_ids_aggregate"] = _rewrite(
                cluster.get("source_ids_aggregate") or []
            )
        for actor in cluster.get("actors", []) or []:
            if isinstance(actor, dict):
                actor["source_ids"] = _rewrite(actor.get("source_ids") or [])
        if not cluster["source_ids"]:
            logger.info(
                "Perspektiv[%s]: cluster %s dropped — no surviving sources",
                slug, cluster.get("id", "?"),
            )
            continue
        surviving.append(cluster)

    synced["position_clusters"] = surviving
    return synced


def _enrich_position_clusters(
    perspective_analysis: dict,
    research_dossier: dict,
) -> dict:
    """Attach deterministic fields to the agent's raw cluster output.

    The Perspektiv V2 agent emits only
    ``{position_clusters: [{id, position_label, position_summary, source_ids}],
    missing_positions: [...]}``. This pass computes the remaining fields
    from ``source_ids`` against the research dossier:

    - ``actors`` — one entry per ``actors_quoted[]`` entry on each cited
      source, carrying its own single-item ``source_ids`` and a ``quote``
      mirrored from ``verbatim_quote``.
    - ``regions`` — sorted, deduplicated, normalized country values from
      the cited sources.
    - ``languages`` — sorted, deduplicated, normalized language values
      from the cited sources.
    - ``representation`` — computed as ``len(source_ids) /
      len(dossier.sources)``: ≥0.40 → ``dominant``; ≥0.15 → ``substantial``;
      else ``marginal``. Empty dossier → ``marginal`` with a WARNING log.

    The input is not mutated — callers get a deep-copied result.
    """
    import copy

    if not perspective_analysis or not isinstance(perspective_analysis, dict):
        return perspective_analysis

    dossier_sources = research_dossier.get("sources", []) if research_dossier else []
    total_sources = len(dossier_sources)
    by_id: dict[str, dict] = {}
    for src in dossier_sources:
        if isinstance(src, dict):
            sid = src.get("id")
            if isinstance(sid, str) and sid:
                by_id[sid] = src

    if total_sources == 0:
        logger.warning(
            "Perspektiv enrichment: research dossier has no sources; "
            "all clusters default to representation='marginal'"
        )

    enriched = copy.deepcopy(perspective_analysis)
    for cluster_idx, cluster in enumerate(
        enriched.get("position_clusters", []) or [], start=1,
    ):
        if not isinstance(cluster, dict):
            continue
        cluster["id"] = f"pc-{cluster_idx:03d}"
        source_ids = [
            s for s in (cluster.get("source_ids") or []) if isinstance(s, str)
        ]

        actors: list[dict] = []
        regions_seen: set[str] = set()
        languages_seen: set[str] = set()
        for sid in source_ids:
            src = by_id.get(sid)
            if not src:
                continue
            country = _normalise_country(src.get("country"))
            language = _normalise_language(src.get("language"))
            if country:
                regions_seen.add(country)
            if language:
                languages_seen.add(language)
            for entry in src.get("actors_quoted", []) or []:
                if not isinstance(entry, dict):
                    continue
                actors.append({
                    "name": entry.get("name", ""),
                    "role": entry.get("role", ""),
                    "type": entry.get("type", ""),
                    "region": country,
                    "source_ids": [sid],
                    "quote": entry.get("verbatim_quote"),
                })

        if total_sources == 0:
            representation = "marginal"
        else:
            ratio = len(source_ids) / total_sources
            if ratio >= 0.40:
                representation = "dominant"
            elif ratio >= 0.15:
                representation = "substantial"
            else:
                representation = "marginal"

        cluster["actors"] = actors
        cluster["regions"] = sorted(regions_seen)
        cluster["languages"] = sorted(languages_seen)
        cluster["representation"] = representation

    return enriched


def _strip_internal_fields_from_sources(sources: list[dict]) -> list[dict]:
    """Drop internal stash keys from each source object before TP assembly.

    Strips both ``rsrc_id`` (kept through QA+Fix to map Perspektiv
    source_ids) and ``web_id`` (defensive — should already be dropped
    at renumber time, but if anything leaks it's caught here). Returns
    a new list with new dicts — never mutates the input.
    """
    internal_keys = {_INTERNAL_RSRC_ID_KEY, _INTERNAL_WEB_ID_KEY}
    cleaned: list[dict] = []
    for src in sources or []:
        if not isinstance(src, dict):
            continue
        clean = {k: v for k, v in src.items() if k not in internal_keys}
        cleaned.append(clean)
    return cleaned


def _build_bias_card(
    article: dict,
    perspective_analysis: dict,
    qa_analysis: dict,
    research_dossier: dict,
) -> dict:
    """Build the deterministic portion of the Bias Transparency Card.

    Pure data aggregation from existing pipeline outputs — no LLM calls.
    Country names are normalised via :func:`_normalise_country` so short
    forms (USA, UK) aggregate with their long forms.
    """
    writer_sources = article.get("sources", [])
    researcher_sources = research_dossier.get("sources", [])
    clusters = perspective_analysis.get("position_clusters", []) or []
    missing_positions = perspective_analysis.get("missing_positions", []) or []

    # Source balance — count by language and normalised country
    by_language: dict[str, int] = {}
    by_country: dict[str, int] = {}
    for s in writer_sources:
        lang = s.get("language") or "unknown"
        by_language[lang] = by_language.get(lang, 0) + 1
        country = _normalise_country(s.get("country")) or "unknown"
        by_country[country] = by_country.get(country, 0) + 1

    # Geographic coverage — compare on normalised country sets; drop any
    # empty / None values defensively.
    writer_countries = {
        _normalise_country(s.get("country")) for s in writer_sources
    }
    writer_countries.discard("")
    researcher_countries = {
        _normalise_country(s.get("country")) for s in researcher_sources
    }
    researcher_countries.discard("")
    missing_countries = sorted(
        c for c in (researcher_countries - writer_countries) if c
    )

    distinct_actors: set[tuple] = set()
    representation_distribution: dict[str, int] = {
        "dominant": 0, "substantial": 0, "marginal": 0,
    }
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        rep = cluster.get("representation", "marginal")
        if rep in representation_distribution:
            representation_distribution[rep] += 1
        for actor in cluster.get("actors", []) or []:
            if not isinstance(actor, dict):
                continue
            key = (actor.get("name", ""), actor.get("role", ""))
            if any(key):
                distinct_actors.add(key)

    return {
        "source_balance": {
            "total": len(writer_sources),
            "by_language": by_language,
            "by_country": by_country,
        },
        "geographic_coverage": {
            "represented": sorted(writer_countries),
            "missing_from_dossier": missing_countries,
        },
        "perspectives": {
            "cluster_count": len(clusters),
            "distinct_actor_count": len(distinct_actors),
            "representation_distribution": representation_distribution,
            "missing_positions": missing_positions,
        },
        "factual_divergences": qa_analysis.get("divergences", []),
        "coverage_gaps": research_dossier.get("coverage_gaps", []),
    }


class PipelineError(Exception):
    """Base exception for pipeline errors."""


class PipelineGateRejected(PipelineError):
    """Raised when a gate handler rejects the pipeline."""


class PipelineStepError(PipelineError):
    """Raised when a critical pipeline step fails (collect, curate, etc.)."""


class Pipeline:
    """Orchestrates agents in a defined sequence with data flow and gating."""

    STEPS = ["collect", "curate", "editorial_conference", "produce", "verify"]

    def __init__(
        self,
        name: str,
        agents: dict[str, Agent],
        output_dir: str = "./output",
        state_dir: str = "./state",
        max_topics: int = 10,
        max_produce: int = 3,
        mode: str = "full",
        gate_handler: Callable | None = None,
    ) -> None:
        self.name = name
        self.agents = agents
        self.output_dir = output_dir
        self.state_dir = state_dir
        self.max_topics = max_topics
        self.max_produce = max_produce
        self.mode = mode
        self.gate_handler = gate_handler
        self.state: PipelineState | None = None
        self._agent_stats: list[dict] = []

    def _track_agent(self, result: object, agent_name: str, topic_slug: str | None = None) -> None:
        """Record agent metrics for the run stats."""
        self._agent_stats.append({
            "agent": agent_name,
            "topic": topic_slug,
            "tokens_used": result.tokens_used,
            "duration_seconds": result.duration_seconds,
            "cost_usd": result.cost_usd,
            "model": result.model,
        })

    # Map CLI step names to internal pipeline step names
    _STEP_TO_INTERNAL = {
        "collector": "collect",
        "curator": "curate",
        "editor": "editorial_conference",
        "researcher": "produce",
        "perspektiv": "produce",
        "writer": "produce",
        "qa_analyze": "produce",
    }

    STEP_ORDER = ["collector", "curator", "editor", "researcher", "perspektiv", "writer", "qa_analyze", "bias_detector"]

    async def run(self, date: str | None = None, to_step: str | None = None) -> list[TopicPackage]:
        """Execute the full pipeline. Returns completed TopicPackages.

        If to_step is given, stop after that step (inclusive).
        """
        date = date or datetime.now().strftime("%Y-%m-%d")

        # Check for incomplete state
        existing = self._load_incomplete_state(date)
        if existing:
            logger.info("Resuming incomplete run: %s", existing.run_id)
            self.state = existing
        else:
            run_id = f"run-{date}-{uuid4().hex[:6]}"
            self.state = PipelineState(
                run_id=run_id,
                date=date,
                current_step="collect",
                started_at=datetime.now().isoformat(),
            )

        # Determine stop point
        to_idx = self.STEP_ORDER.index(to_step) if to_step else len(self.STEP_ORDER) - 1

        # Execute steps in order, skipping already completed ones
        raw_findings: list[dict] = self.state.raw_findings
        curated_topics: list[dict] = self.state.curated_topics
        assignments: list[TopicAssignment] = [
            TopicAssignment(**a) for a in self.state.assignments
        ]
        packages: list[TopicPackage] = [
            TopicPackage(**p) for p in self.state.packages
        ]

        if "collect" not in self.state.completed_steps:
            self.state.current_step = "collect"
            await self._save_state()
            raw_findings = await self.collect()
            self.state.raw_findings = raw_findings
            self.state.completed_steps.append("collect")
            await self._save_state()
            self._write_debug_output("01-collector-raw.json", raw_findings)

        if to_idx <= self.STEP_ORDER.index("collector"):
            logger.info("Stopping after step 'collector' as requested.")
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "curate" not in self.state.completed_steps:
            self.state.current_step = "curate"
            await self._save_state()
            curated_topics = await self.curate(raw_findings)
            self.state.curated_topics = curated_topics
            self.state.completed_steps.append("curate")
            await self._save_state()
            self._write_debug_output("02-curator-topics.json", curated_topics)

        if to_idx <= self.STEP_ORDER.index("curator"):
            logger.info("Stopping after step 'curator' as requested.")
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "editorial_conference" not in self.state.completed_steps:
            self.state.current_step = "editorial_conference"
            await self._save_state()
            assignments = await self.editorial_conference(curated_topics)
            self.state.assignments = [asdict(a) for a in assignments]
            self.state.completed_steps.append("editorial_conference")
            await self._save_state()
            self._write_debug_output(
                "03-editor-assignments.json",
                [asdict(a) for a in assignments],
            )

            # Filter out rejected topics (priority 0) — Editor includes them
            # for transparency but they must not enter production.
            rejected = [a for a in assignments if a.priority <= 0]
            assignments = [a for a in assignments if a.priority > 0]
            if rejected:
                rejected_titles = [a.title for a in rejected]
                logger.info(
                    "Filtered %d rejected topic(s): %s",
                    len(rejected), rejected_titles,
                )
            if not assignments:
                logger.warning("Editor rejected all topics — no production this run")
                self.state.current_step = "done"
                await self._save_state()
                return packages

            # Sort by priority (desc), tiebreaker: source count (desc), then position
            assignments.sort(
                key=lambda a: (
                    -a.priority,
                    -len(a.raw_data.get("source_ids", [])),
                )
            )

            # Slice to production budget
            if len(assignments) > self.max_produce:
                logger.info(
                    "Production budget: %d accepted topics, producing top %d",
                    len(assignments), self.max_produce,
                )
                assignments = assignments[: self.max_produce]

            # Gate check after editorial conference (full mode only)
            gate_ok = await self.gate("editorial_conference", assignments)
            if not gate_ok:
                raise PipelineGateRejected(
                    "Gate rejected after editorial_conference"
                )

        if to_idx <= self.STEP_ORDER.index("editor"):
            logger.info("Stopping after step 'editor' as requested.")
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "produce" not in self.state.completed_steps:
            self.state.current_step = "produce"
            await self._save_state()
            packages = await self.produce(assignments, to_step=to_step)
            self.state.packages = [asdict(p) for p in packages]
            self.state.completed_steps.append("produce")
            await self._save_state()

        # If --to stops before qa_analyze, skip verify and write_output
        if to_step and self.STEP_ORDER.index(to_step) < self.STEP_ORDER.index("qa_analyze"):
            if to_step in ("researcher", "perspektiv", "writer"):
                logger.info("Stopping after step '%s' as requested.", to_step)
            self.state.current_step = "done"
            await self._save_state()
            return packages

        if "verify" not in self.state.completed_steps:
            self.state.current_step = "verify"
            await self._save_state()
            packages = await self.verify(packages)
            self.state.completed_steps.append("verify")
            await self._save_state()

        # Mark as done
        self.state.current_step = "done"
        await self._save_state()

        # Write output
        await self._write_output(packages)

        return packages

    async def collect(self) -> list[dict]:
        """Two-phase collection: plan queries, execute in Python, assemble findings."""
        from src.tools import web_search_tool

        planner = self.agents.get("collector_plan")
        assembler = self.agents.get("collector_assemble")

        if not planner and not assembler and "collector" not in self.agents:
            logger.info("No collector configured, skipping collection step")
            return []

        if not planner or not assembler:
            logger.error("No 'collector_plan' or 'collector_assemble' agent configured")
            return []

        # Phase 1: Plan search queries
        plan_result = await planner.run(
            f"Plan search queries for today's global news scan. Today is {self.state.date}.",
            output_schema={"type": "array", "items": {"type": "object"}},
        )
        self._track_agent(plan_result, "collector_plan")

        queries = plan_result.structured
        if not queries or not isinstance(queries, list):
            queries = _extract_list(plan_result) or []
        if not queries:
            logger.warning("Collector planner returned no queries")
            return []

        logger.info("Collector plan: %d queries", len(queries))
        self._write_debug_output("01-collector-plan.json", queries)

        # Phase 2: Execute searches in Python (no LLM)
        search_results = []
        for q in queries:
            query_str = q.get("query", "")
            if not query_str:
                continue
            try:
                result_text = await web_search_tool.execute(query=query_str)
                search_results.append({"query": q, "results": result_text})
            except Exception as e:
                logger.warning("Collector search failed for '%s': %s", query_str, e)
                search_results.append({"query": q, "results": f"Error: {e}"})

        logger.info("Collector search: %d/%d queries returned results",
                     len([r for r in search_results if not r["results"].startswith("Error")]),
                     len(search_results))

        # Deduplicate by URL
        search_results = _deduplicate_search_results(search_results)

        self._write_debug_output("01-collector-search.json", search_results)

        # Phase 3: Assemble findings (one LLM call, no tools)
        try:
            assemble_result = await assembler.run(
                "Compile these search results into a JSON array of news findings.",
                context={"search_results": search_results},
            )
            self._track_agent(assemble_result, "collector_assemble")
            parsed = _extract_list(assemble_result)
            if parsed is not None:
                return parsed
            logger.warning("Collector assembler returned non-list output")
            return []
        except Exception as e:
            logger.error("Collector assembly failed: %s", e)
            return []

    def _load_feed_findings(self) -> list[dict]:
        """Load feed findings from raw/{date}/feeds.json if available."""
        if not self.state:
            return []
        feeds_path = Path("raw") / self.state.date / "feeds.json"
        if not feeds_path.exists():
            return []
        try:
            data = json.loads(feeds_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                logger.info("Loaded %d feed findings from %s", len(data), feeds_path)
                return data
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Could not load feed findings: %s", e)
        return []

    def _prepare_curator_input(self, raw_findings: list[dict]) -> list[dict]:
        """Compress all findings for the Curator. Pure Python, no LLM.

        Keeps ALL findings (no filtering, no dedup beyond URL).
        Strips fields the Curator doesn't need (url, region, language, feed_source).
        Only includes summary if it exists AND differs from the title.
        """
        # URL dedup (safety net — already done in fetch_feeds.py)
        seen_urls: set[str] = set()
        unique: list[dict] = []
        for f in raw_findings:
            url = f.get("source_url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            unique.append(f)

        url_dupes = len(raw_findings) - len(unique)
        if url_dupes:
            logger.info("Curator prep: removed %d URL duplicates", url_dupes)

        # Compress: only title + summary (if useful) + source_name + index
        compressed: list[dict] = []
        for i, f in enumerate(unique):
            title = f.get("title", "").strip()
            if not title:
                continue

            entry: dict = {
                "id": f"finding-{i}",
                "title": title,
                "source_name": f.get("source_name", ""),
            }

            # Include summary only if it exists and adds information beyond the title
            summary = f.get("summary", "").strip()
            if summary and summary.lower() != title.lower() and not title.lower().startswith(summary.lower()[:50]):
                entry["summary"] = summary

            compressed.append(entry)

        logger.info(
            "Curator prep: %d raw → %d unique → %d with titles (compressed)",
            len(raw_findings), len(unique), len(compressed),
        )

        return compressed

    @staticmethod
    def _recover_truncated_cluster_assignments(
        content: str, n_findings: int
    ) -> list | None:
        """Recover ``cluster_assignments`` from a raw Curator response.

        Triggered when ``_extract_dict`` returns a dict carrying ``topics``
        but no ``cluster_assignments``. With the S13 envelope
        ``{topics, cluster_assignments}`` the array sits at the end of the
        JSON. Gemini Flash occasionally truncates mid-array (sometimes
        emitting a long all-``null`` tail). The bracket-balance repair in
        ``Agent._parse_json`` then closes the dict at the last topic's
        ``}``, dropping the partial array entirely.

        This recovery scans the raw content for ``"cluster_assignments": [``
        and parses entries (integers or ``null``) up to ``n_findings`` or the
        first non-entry token. Returns the list or ``None`` if the key is
        absent.
        """
        if not content:
            return None
        m = re.search(r'"cluster_assignments"\s*:\s*\[', content)
        if not m:
            return None
        pos = m.end()
        n = len(content)
        entries: list = []
        while pos < n and len(entries) < n_findings:
            while pos < n and content[pos] in " \n\t\r":
                pos += 1
            if pos >= n:
                break
            ch = content[pos]
            if ch == "]":
                break
            if ch == ",":
                pos += 1
                continue
            if content.startswith("null", pos):
                entries.append(None)
                pos += 4
                continue
            m2 = re.match(r"-?\d+", content[pos:])
            if m2:
                entries.append(int(m2.group()))
                pos += m2.end()
                continue
            break
        return entries

    def _rebuild_curator_source_ids(
        self, agent_result: object, raw_findings: list[dict]
    ) -> list[dict]:
        """Extract Curator topics and rebuild ``source_ids`` deterministically.

        The S13 Curator emits ``{"topics": [...], "cluster_assignments":
        [int|null, ...]}`` where ``cluster_assignments`` is a flat array
        with exactly one entry per finding in input order. Each integer is
        a 0-based topic index; ``null`` means the finding belongs to no
        topic.

        Falls back to the legacy shape (a top-level JSON array of topics
        each carrying ``source_ids: ["finding-N", ...]``) when the new
        envelope is absent — older prompts on disk still produce that
        shape and the pipeline must keep working through any future
        migration.

        Length mismatch (``len(cluster_assignments) != len(raw_findings)``)
        logs a WARNING and processes whatever overlap exists. Out-of-range
        ``topic_index`` values are skipped with a WARNING. Topics with
        zero matching cluster_assignments get an empty ``source_ids`` list
        and an INFO log.
        """
        parsed = _extract_dict(agent_result)

        # Truncation recovery: if the parsed dict carries ``topics`` but no
        # ``cluster_assignments`` (Gemini Flash sometimes truncates mid-array,
        # and the bracket-balance repair then drops the array entirely), pull
        # the cluster_assignments back out of the raw response by regex.
        if (
            isinstance(parsed, dict)
            and isinstance(parsed.get("topics"), list)
            and parsed.get("cluster_assignments") is None
        ):
            recovered = self._recover_truncated_cluster_assignments(
                getattr(agent_result, "content", "") or "", len(raw_findings)
            )
            if recovered is not None:
                logger.warning(
                    "Curator cluster_assignments dropped by JSON repair; "
                    "recovered %d entries via regex (expected %d)",
                    len(recovered), len(raw_findings),
                )
                parsed["cluster_assignments"] = recovered

        new_shape = (
            isinstance(parsed, dict)
            and isinstance(parsed.get("topics"), list)
            and isinstance(parsed.get("cluster_assignments"), list)
        )
        if not new_shape:
            # Legacy: top-level list of topics with source_ids already attached.
            return _extract_list(agent_result) or []

        topics_in: list = parsed.get("topics") or []
        topics: list[dict] = [t for t in topics_in if isinstance(t, dict)]
        for t in topics:
            t["source_ids"] = []

        n_findings = len(raw_findings)
        n_topics = len(topics)
        assignments: list = parsed.get("cluster_assignments") or []
        n_assignments = len(assignments)

        if n_assignments != n_findings:
            logger.warning(
                "Curator cluster_assignments length=%d does not match findings "
                "length=%d; processing the overlap only",
                n_assignments, n_findings,
            )

        overlap = min(n_assignments, n_findings)
        for finding_index in range(overlap):
            topic_index = assignments[finding_index]
            if topic_index is None:
                continue
            if not isinstance(topic_index, int):
                logger.warning(
                    "Curator cluster_assignments[%d]=%r is not an int|null; skipping",
                    finding_index, topic_index,
                )
                continue
            if not (0 <= topic_index < n_topics):
                logger.warning(
                    "Curator cluster_assignments[%d]=%d is out of range "
                    "(have %d topics); skipping",
                    finding_index, topic_index, n_topics,
                )
                continue
            topics[topic_index]["source_ids"].append(f"finding-{finding_index}")

        for ti, t in enumerate(topics):
            if not t["source_ids"]:
                logger.info(
                    "Curator topic %d ('%s') has no cluster_assignments — "
                    "empty source_ids; unlikely to survive Editor",
                    ti, t.get("title", "?"),
                )
        return topics

    def _enrich_curator_output(
        self, topics: list[dict], raw_findings: list[dict]
    ) -> list[dict]:
        """Add geographic_coverage, missing_perspectives, languages deterministically.

        The Curator only clusters and scores. This function computes metadata
        from the original finding fields (region, language, source_name) that
        the Curator never sees. Pure Python, 0 LLM tokens.
        """
        # Load source metadata for tier/editorial_independence
        sources_path = Path("config") / "sources.json"
        source_meta: dict[str, dict] = {}
        if sources_path.exists():
            try:
                data = json.loads(sources_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Could not load sources.json: %s", e)
                data = {"feeds": []}
            source_meta = {s["name"]: s for s in data.get("feeds", [])}

        # Build index: finding-N → original finding dict
        finding_index: dict[str, dict] = {}
        for i, f in enumerate(raw_findings):
            finding_index[f"finding-{i}"] = f

        # All regions and languages across ALL findings (for gap detection)
        all_regions: set[str] = set()
        all_languages: set[str] = set()
        for f in raw_findings:
            r = f.get("region", "")
            if r:
                all_regions.add(r)
            lang = f.get("language", "")
            if lang:
                all_languages.add(lang)

        for topic in topics:
            source_ids = topic.get("source_ids", [])

            # Collect metadata from clustered findings
            topic_regions: set[str] = set()
            topic_languages: set[str] = set()
            topic_sources: list[dict] = []

            for sid in source_ids:
                finding = finding_index.get(sid)
                if not finding:
                    continue
                r = finding.get("region", "")
                if r:
                    topic_regions.add(r)
                lang = finding.get("language", "")
                if lang:
                    topic_languages.add(lang)

                sname = finding.get("source_name", "")
                meta = source_meta.get(sname, {})
                topic_sources.append({
                    "name": sname,
                    "tier": meta.get("tier"),
                    "editorial_independence": meta.get("editorial_independence"),
                })

            # Deterministic enrichment
            topic["geographic_coverage"] = sorted(topic_regions)
            topic["languages"] = sorted(topic_languages)
            topic["source_count"] = len(source_ids)

            # Missing regions: all regions in the full feed set minus this topic's regions
            missing_regions = sorted(all_regions - topic_regions)
            topic["missing_regions"] = missing_regions

            # Missing languages
            missing_langs = sorted(all_languages - topic_languages)
            topic["missing_languages"] = missing_langs

            # Source diversity
            topic["source_diversity"] = topic_sources

            # Build missing_perspectives string (human-readable)
            parts: list[str] = []
            if missing_regions:
                parts.append(f"No sources from: {', '.join(missing_regions)}")
            if missing_langs:
                parts.append(f"No coverage in: {', '.join(missing_langs)}")

            # Keep LLM-generated missing_perspectives if present, append deterministic data
            existing = topic.get("missing_perspectives", "")
            deterministic = ". ".join(parts) if parts else ""
            if existing and deterministic:
                topic["missing_perspectives"] = f"{existing} [Deterministic: {deterministic}]"
            elif deterministic:
                topic["missing_perspectives"] = deterministic

        return topics

    async def curate(self, raw_findings: list[dict]) -> list[dict]:
        """Select the most newsworthy topics from raw findings."""
        agent = self.agents.get("curator")
        if not agent:
            logger.error("No 'curator' agent configured")
            return []

        # Merge feed findings with collector findings
        feed_findings = self._load_feed_findings()
        if feed_findings:
            logger.info(
                "Merged %d feed findings with %d collector findings",
                len(feed_findings), len(raw_findings),
            )
            raw_findings = raw_findings + feed_findings

        # Prepare compressed input (all findings, no filtering)
        prepared = self._prepare_curator_input(raw_findings)
        self._write_debug_output("01b-curator-prepared.json", {
            "raw_count": len(raw_findings),
            "prepared_count": len(prepared),
            "sources_represented": len(set(f.get("source_name", "") for f in prepared)),
            "token_estimate": sum(len(json.dumps(f)) for f in prepared) // 4,
        })

        message = (
            "Review these findings. Cluster related findings into topics. "
            "Score each topic's newsworthiness on a 1-10 scale."
        )

        try:
            result = await agent.run(
                message, context={"findings": prepared}
            )
            self._track_agent(result, "curator")

            # Rebuild source_ids from cluster_assignments (S13 shape) or
            # pass through topics-with-source_ids (legacy shape).
            topics = self._rebuild_curator_source_ids(result, raw_findings)

            # Deterministic enrichment (geographic_coverage, missing_perspectives, etc.)
            topics = self._enrich_curator_output(topics, raw_findings)

            # Sort by relevance_score (descending) and limit
            topics.sort(
                key=lambda t: t.get("relevance_score", 0), reverse=True
            )

            # Write unsliced output for transparency before max_topics cap
            self._write_debug_output("02-curator-topics-unsliced.json", topics)
            logger.info(
                "Curator produced %d topics, slicing to top %d",
                len(topics), self.max_topics,
            )

            return topics[: self.max_topics]
        except Exception as e:
            logger.error("Curator failed: %s", e)
            return []

    def _scan_previous_coverage(self, days: int = 7) -> list[dict]:
        """Scan output directory for Topic Packages from the last N days.

        Returns list of dicts with: tp_id, date, headline, slug, summary.
        Sorted by date descending (most recent first).
        """
        if not self.state:
            return []

        current_date = datetime.strptime(self.state.date, "%Y-%m-%d")
        out = Path(self.output_dir)
        if not out.exists():
            return []

        results: list[dict] = []
        for d in out.iterdir():
            if not d.is_dir() or len(d.name) != 10:
                continue
            # Skip current date's directory
            if d.name == self.state.date:
                continue
            try:
                dir_date = datetime.strptime(d.name, "%Y-%m-%d")
            except ValueError:
                continue
            if (current_date - dir_date).days > days or dir_date > current_date:
                continue

            for tp_path in d.glob("tp-*.json"):
                try:
                    data = json.loads(tp_path.read_text(encoding="utf-8"))
                    meta = data.get("metadata", {})
                    article = data.get("article", {})
                    headline = article.get("headline", "")
                    if not headline:
                        continue
                    results.append({
                        "tp_id": data.get("id", ""),
                        "date": meta.get("date", d.name),
                        "headline": headline,
                        "slug": meta.get("topic_slug", ""),
                        "summary": article.get("summary", ""),
                    })
                except (json.JSONDecodeError, KeyError):
                    continue

        results.sort(key=lambda x: x["date"], reverse=True)
        date_dirs = len({r["date"] for r in results})
        logger.info(
            "Loaded %d previous TPs from %d days for coverage continuity",
            len(results), date_dirs,
        )
        return results

    def _get_previous_headline(self, tp_id: str) -> str:
        """Look up headline from a previous TP by ID."""
        parts = tp_id.split("-")
        if len(parts) >= 5:
            date_str = f"{parts[1]}-{parts[2]}-{parts[3]}"
            tp_path = Path(self.output_dir) / date_str / f"{tp_id}.json"
            if tp_path.exists():
                try:
                    data = json.loads(tp_path.read_text(encoding="utf-8"))
                    return data.get("article", {}).get("headline", "")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("Could not read previous TP %s: %s", tp_id, e)
        return ""

    _CURATOR_RAW_DATA_FIELDS = (
        "source_ids", "summary", "geographic_coverage", "languages",
        "missing_perspectives", "source_count", "missing_regions",
        "missing_languages", "source_diversity", "relevance_score",
    )

    @classmethod
    def _attach_raw_data_from_curated(
        cls, raw_assignments: list[dict], curated_topics: list[dict],
    ) -> None:
        """Re-attach Curator's enrichment to Editor's assignments in place.

        Editor's strict-mode schema cannot emit ``raw_data``. Match each
        Editor entry to a curated topic by exact title first, then by slug
        as a fallback when the Editor refined the title. ``raw_data`` is
        assembled from a fixed set of curator-enrichment fields so the
        downstream tiebreaker (``source_ids``) and Researcher PLAN prompt
        (``summary``, ``geographic_coverage``, ``languages``,
        ``missing_perspectives``, ``source_count``) see populated context.
        """
        def _extract(t: dict) -> dict:
            return {k: t[k] for k in cls._CURATOR_RAW_DATA_FIELDS if k in t}

        title_lookup: dict[str, dict] = {}
        slug_buckets: dict[str, list[dict]] = {}
        for t in curated_topics:
            if not isinstance(t, dict):
                continue
            title = t.get("title") or ""
            raw_data = _extract(t)
            if title and title not in title_lookup:
                title_lookup[title] = raw_data
            slug = _slugify(title)
            if slug:
                slug_buckets.setdefault(slug, []).append(raw_data)

        for a in raw_assignments:
            if not isinstance(a, dict):
                continue
            if a.get("raw_data"):
                continue
            title = a.get("title") or ""
            if title in title_lookup:
                a["raw_data"] = title_lookup[title]
                continue
            slug = _slugify(title)
            if slug and slug in slug_buckets:
                bucket = slug_buckets[slug]
                if len(bucket) == 1:
                    a["raw_data"] = bucket[0]
                    logger.info(
                        "editor refined title; matched by slug: '%s' (slug=%s)",
                        title, slug,
                    )
                    continue
                logger.warning(
                    "editor topic '%s' has %d slug-level matches; raw_data left empty",
                    title, len(bucket),
                )
                a["raw_data"] = {}
                continue
            logger.warning(
                "editor topic '%s' did not match any curated topic; "
                "raw_data unavailable for tiebreaker and researcher_plan",
                title,
            )
            a["raw_data"] = {}

    async def editorial_conference(
        self, curated_topics: list[dict]
    ) -> list[TopicAssignment]:
        """Prioritize topics and create assignments.

        Editor emits one entry per topic with ``title``, ``priority``,
        ``selection_reason``, and optional ``follow_up_to`` /
        ``follow_up_reason``. Python owns the deterministic fields
        (``id``, ``topic_slug``):

        1. Parse the raw output, preserving original input order.
        2. Filter rejected topics (priority ≤ 0). Rejected topics never
           receive an ``id`` — they appear at the tail of the returned
           list with ``id=""`` so the debug snapshot still records them.
        3. Sort survivors by priority desc, source_count desc, position asc.
        4. Assign ``id = f"tp-{date}-{seq:03d}"`` (1-based seq) and
           ``topic_slug`` (deterministic ASCII-fold of ``title``).
        5. Construct ``TopicAssignment`` instances.
        """
        agent = self.agents.get("editor")
        if not agent:
            logger.error("No 'editor' agent configured")
            return []

        previous_coverage = self._scan_previous_coverage()

        message = (
            "Prioritize these topics for today's report. For each, assign a "
            "priority (1-10) and a selection_reason. Today's date is "
            f"{self.state.date}."
        )

        try:
            result = await agent.run(
                message, context={
                    "topics": curated_topics,
                    "previous_coverage": previous_coverage,
                }
            )
            self._track_agent(result, "editor")

            # Strict schema wraps the assignments list as ``{"assignments": [...]}``.
            # Unwrap before consuming. Fall back to raw extraction if a provider
            # didn't apply the schema.
            structured = result.structured
            if isinstance(structured, dict):
                raw_assignments = structured.get("assignments")
            else:
                raw_assignments = structured
            if not raw_assignments or not isinstance(raw_assignments, list):
                raw_assignments = _extract_list(result) or []

            self._attach_raw_data_from_curated(raw_assignments, curated_topics)

            survivors: list[dict] = []
            rejected: list[dict] = []
            for position, a in enumerate(raw_assignments):
                if not isinstance(a, dict):
                    continue
                priority_raw = a.get("priority", 5)
                try:
                    priority = int(priority_raw)
                except (TypeError, ValueError):
                    priority = 5
                source_count = len(a.get("raw_data", {}).get("source_ids", []))
                entry = {
                    "raw": a,
                    "priority": priority,
                    "source_count": source_count,
                    "position": position,
                }
                if priority <= 0:
                    rejected.append(entry)
                else:
                    survivors.append(entry)

            survivors.sort(
                key=lambda e: (-e["priority"], -e["source_count"], e["position"])
            )

            date = self.state.date if self.state else ""
            assignments: list[TopicAssignment] = []
            for seq, entry in enumerate(survivors, start=1):
                a = entry["raw"]
                title = a.get("title", "") or ""
                slug = _slugify(title) or "topic"
                assignments.append(
                    TopicAssignment(
                        id=f"tp-{date}-{seq:03d}",
                        title=title,
                        priority=entry["priority"],
                        topic_slug=slug,
                        selection_reason=a.get("selection_reason", ""),
                        raw_data=a.get("raw_data", {}),
                        follow_up_to=a.get("follow_up_to"),
                        follow_up_reason=a.get("follow_up_reason"),
                    )
                )

            for entry in rejected:
                a = entry["raw"]
                assignments.append(
                    TopicAssignment(
                        id="",
                        title=a.get("title", "") or "",
                        priority=entry["priority"],
                        topic_slug="",
                        selection_reason=a.get("selection_reason", ""),
                        raw_data=a.get("raw_data", {}),
                        follow_up_to=a.get("follow_up_to"),
                        follow_up_reason=a.get("follow_up_reason"),
                    )
                )
            return assignments
        except Exception as e:
            logger.error("Editor failed: %s", e)
            return []

    async def gate(self, step_name: str, data: object) -> bool:
        """Gate check — only in full mode, calls gate_handler if provided."""
        if self.mode != "full":
            return True
        if not self.gate_handler:
            return True
        return await self.gate_handler(step_name, data)

    async def produce(
        self, assignments: list[TopicAssignment], to_step: str | None = None,
    ) -> list[TopicPackage]:
        """Produce TopicPackages for all assignments sequentially."""
        import asyncio

        packages: list[TopicPackage] = []
        for i, assignment in enumerate(assignments):
            # Delay between topics to avoid upstream rate limits (429s)
            if i > 0:
                logger.info("Waiting 30s before next topic to avoid rate limits...")
                await asyncio.sleep(30)
            try:
                pkg = await self._produce_single(assignment, to_step=to_step)
                packages.append(pkg)
            except Exception as e:
                logger.exception(
                    "Failed to produce topic '%s': %s", assignment.id, e
                )
                pkg = TopicPackage(
                    id=assignment.id,
                    metadata={
                        "title": assignment.title,
                        "date": self.state.date if self.state else "",
                        "status": "failed",
                        "topic_slug": assignment.topic_slug,
                    },
                    status="failed",
                    error=str(e),
                )
                packages.append(pkg)
        return packages

    async def _produce_single(
        self,
        assignment: TopicAssignment,
        preloaded_dossier: dict | None = None,
        preloaded_article: dict | None = None,
        skip_perspektiv: bool = False,
        to_step: str | None = None,
        preloaded_perspectives: dict | None = None,
    ) -> TopicPackage:
        """Produce a single TopicPackage from an assignment.

        Optional preloaded data skips the corresponding step:
        - preloaded_dossier: skip researcher
        - preloaded_article: skip writer (and researcher and perspektiv)
        - skip_perspektiv: skip perspektiv even when dossier is available
        - preloaded_perspectives: use this perspektiv data when step is skipped
        - to_step: stop after this step (inclusive)
        """
        import asyncio

        assignment_data = asdict(assignment)
        article: dict = {}
        bias_analysis: dict = {}

        slug = assignment.topic_slug or assignment.id

        # 2. Research Agent — two-phase: plan → search → assemble
        research_dossier: dict = {}
        if preloaded_dossier is not None:
            research_dossier = preloaded_dossier
            logger.info("Using preloaded researcher dossier for '%s'", assignment.title)
        else:
            research_dossier = await self._research_two_phase(assignment_data, slug)

        if to_step == "researcher":
            return TopicPackage(
                id=assignment.id,
                metadata={
                    "title": assignment.title,
                    "date": self.state.date if self.state else "",
                    "status": "partial",
                    "topic_slug": assignment.topic_slug,
                    "stopped_at": "researcher",
                },
                status="partial",
            )

        # 10s delay between researcher and perspektiv/writer to avoid rate limits
        if research_dossier and preloaded_dossier is None:
            logger.info("Waiting 10s after researcher...")
            await asyncio.sleep(10)

        # 2b. Perspective Agent (stakeholder mapping, no tools)
        perspective_analysis: dict = preloaded_perspectives or {}
        if preloaded_perspectives:
            logger.info("Using preloaded perspektiv data for '%s'", assignment.title)
        elif not skip_perspektiv and preloaded_article is None and research_dossier:
            if perspektiv := self.agents.get("perspektiv"):
                perspektiv_context = {
                    "title": assignment.title,
                    "selection_reason": assignment.selection_reason,
                    "sources": research_dossier.get("sources", []),
                    "preliminary_divergences": research_dossier.get("preliminary_divergences", []),
                    "coverage_gaps": research_dossier.get("coverage_gaps", []),
                }
                result = await perspektiv.run(
                    "",
                    context=perspektiv_context,
                )
                perspective_analysis = _extract_dict(result) or {}
                if perspective_analysis:
                    perspective_analysis = _sanitize_null_strings(perspective_analysis)
                self._track_agent(result, "perspektiv", slug)
                if not perspective_analysis and result.content:
                    self._log_raw_on_parse_failure(result, "Perspektiv", slug, "04b-perspektiv")
                perspective_analysis = _enrich_position_clusters(
                    perspective_analysis, research_dossier,
                )
                self._write_debug_output(f"04b-perspektiv-{slug}.json", perspective_analysis)

                # 5s delay before writer
                await asyncio.sleep(5)

        if to_step == "perspektiv":
            return TopicPackage(
                id=assignment.id,
                metadata={
                    "title": assignment.title,
                    "date": self.state.date if self.state else "",
                    "status": "partial",
                    "topic_slug": assignment.topic_slug,
                    "stopped_at": "perspektiv",
                },
                perspectives=perspective_analysis.get("position_clusters", []),
                status="partial",
            )

        # 3. Writer (required, unless preloaded)
        if preloaded_article is not None:
            article = preloaded_article
            logger.info("Using preloaded writer output for '%s'", assignment.title)
        else:
            writer = self.agents.get("writer")
            if not writer:
                raise PipelineStepError(
                    f"No 'writer' agent for topic '{assignment.id}'"
                )

            writer_context = {
                "title": assignment.title,
                "selection_reason": assignment.selection_reason,
                "perspective_analysis": perspective_analysis,
                "sources": research_dossier.get("sources", []),
                "coverage_gaps": research_dossier.get("coverage_gaps", []),
            }

            # Load follow-up addendum if this topic is a follow-up
            writer_addendum = None
            if assignment.follow_up_to:
                followup_path = Path("agents/writer/FOLLOWUP.md")
                if followup_path.exists():
                    writer_addendum = followup_path.read_text(encoding="utf-8")
                    logger.info(
                        "Loaded follow-up addendum for '%s' (follows %s)",
                        assignment.title, assignment.follow_up_to,
                    )
                else:
                    # FOLLOWUP.md not yet delivered by Prompt Engineer
                    logger.warning(
                        "Follow-up topic '%s' but FOLLOWUP.md not found",
                        assignment.title,
                    )

                writer_context["follow_up"] = {
                    "previous_headline": self._get_previous_headline(assignment.follow_up_to),
                    "reason": assignment.follow_up_reason or "",
                }

            result = await writer.run(
                "Write a multi-perspective article on this topic.",
                context=writer_context,
                instructions_addendum=writer_addendum,
            )
            self._track_agent(result, "writer", slug)
            article = _extract_dict(result)
            if not article:
                self._log_raw_on_parse_failure(result, "Writer", slug, "05-writer")
                article = {
                    "headline": assignment.title,
                    "body": result.content,
                }
            # Debug snapshot of the raw Writer output (minimal source refs,
            # pre-merge). Downstream code reads this file via
            # ``writer_data.get("article", writer_data)`` which falls back to
            # the article dict when the file isn't a full TopicPackage.
            self._write_debug_output(f"05-writer-{slug}.json", article)

        # Compute word_count in Python (never trust LLM counting)
        body_text = article.get("body", "")
        article["word_count"] = len(body_text.split())

        # Resolve Writer source refs ({id, rsrc_id}) against the research
        # dossier. After this step ``article["sources"]`` carries full
        # metadata (url, outlet, language, country, estimated_date, ...)
        # that downstream stages (QA+Fix, bias card, render) rely on.
        article["sources"] = _merge_writer_sources(
            article.get("sources", []) or [], research_dossier,
        )

        if to_step == "writer":
            return TopicPackage(
                id=assignment.id,
                metadata={
                    "title": assignment.title,
                    "date": self.state.date if self.state else "",
                    "status": "partial",
                    "topic_slug": assignment.topic_slug,
                    "stopped_at": "writer",
                },
                sources=article.get("sources", []),
                perspectives=perspective_analysis.get("position_clusters", []),
                article=article,
                status="partial",
            )

        # Fix 1 — Source-ID renumbering (now BEFORE QA+Fix). Drops any
        # sources never cited in the article and renames the survivors to
        # a gapless src-001, src-002, … sequence. Rewrites [rsrc-NNN] /
        # [web-N] citations atomically across headline/subheadline/body/
        # summary so QA+Fix sees one consistent ID scheme everywhere.
        new_article, new_sources, _rename_map = _renumber_and_prune_sources(
            article, article.get("sources", []) or [], slug=slug,
        )
        article = new_article
        article["sources"] = new_sources
        article["word_count"] = len(article.get("body", "").split())

        # Debug snapshot of the QA input — verifiable at smoke time.
        self._write_debug_output(f"06-qa-input-{slug}.json", article)

        # 4. QA+Fix (single call: find errors + apply corrections + return corrected article)
        qa_analysis: dict = {}
        article_original = article.get("body", "")
        if qa_analyze := self.agents.get("qa_analyze"):
            qa_context = {
                "article": article,
                "sources": research_dossier.get("sources", []),
                "preliminary_divergences": research_dossier.get("preliminary_divergences", []),
                "position_clusters": perspective_analysis.get("position_clusters", []),
                "missing_positions": perspective_analysis.get("missing_positions", []),
            }
            result = await qa_analyze.run(
                "Check this article against the source material. Find errors and divergences. "
                "Apply corrections directly in the article. Return the corrected article.",
                context=qa_context,
            )
            qa_analysis = _extract_dict(result) or {}
            self._track_agent(result, "qa_analyze", slug)
            if not qa_analysis and result.content:
                self._log_raw_on_parse_failure(result, "QA+Fix", slug, "06-qa-analyze")
            self._write_debug_output(f"06-qa-analyze-{slug}.json", qa_analysis)

            # Take corrected article from QA+Fix. Note: we deliberately do
            # NOT replace article["sources"] from qa_article["sources"] —
            # the pre-QA renumbered sources carry the internal ``rsrc_id``
            # stash that Fix-3 needs. QA+Fix's prompt promises sources are
            # passed through unchanged, so dropping its sources field is
            # safe.
            qa_article = qa_analysis.get("article")
            if qa_article and isinstance(qa_article, dict) and qa_article.get("body"):
                article["body"] = qa_article["body"]
                if qa_article.get("headline"):
                    article["headline"] = qa_article["headline"]
                if qa_article.get("subheadline"):
                    article["subheadline"] = qa_article["subheadline"]
                if qa_article.get("summary"):
                    article["summary"] = qa_article["summary"]

                proposed_corrections = qa_analysis.get("proposed_corrections", [])
                logger.info(
                    "QA+Fix for '%s': %d problems found, %d proposed corrections",
                    assignment.title,
                    len(qa_analysis.get("problems_found", [])),
                    len(proposed_corrections),
                )
            else:
                logger.warning(
                    "QA+Fix for '%s' returned no usable article — keeping original",
                    assignment.title,
                )

        # Compute word_count in Python (never trust LLM counting)
        article["word_count"] = len(article.get("body", "").split())

        # Replace the Writer's [[COVERAGE_STATEMENT]] placeholder with a
        # Python-rendered sentence. Runs after QA+Fix; the final source
        # array is authoritative at this point.
        if article.get("body") and "[[COVERAGE_STATEMENT]]" in article["body"]:
            _substitute_coverage_statement(article)
            article["word_count"] = len(article.get("body", "").split())
            logger.info(
                "Coverage statement: rendered for '%s' (%d sources)",
                assignment.title, len(article.get("sources", [])),
            )
        elif article.get("body"):
            logger.warning(
                "Coverage statement: [[COVERAGE_STATEMENT]] missing in article "
                "body for '%s' (Writer omitted it, or QA+Fix dropped it)",
                assignment.title,
            )

        # Fix 3 — Perspektiv source_ids use rsrc-NNN; rewrite to the
        # final src-NNN via the internal rsrc_id stash on each surviving
        # source. Renumbering ran before QA+Fix; the rsrc_id stash
        # survived because we did not replace article["sources"] from
        # QA+Fix's article output.
        perspective_analysis = _convert_rsrc_to_src_in_perspectives(
            perspective_analysis, article.get("sources", []), slug=slug,
        )

        # 7. Bias Transparency Card (hybrid: Python aggregation + LLM language analysis)
        bias_card = _build_bias_card(article, perspective_analysis, qa_analysis, research_dossier)

        if bias_language := self.agents.get("bias_language"):
            result = await bias_language.run(
                "Analyze this article text for linguistic bias patterns. "
                "Then write a reader note that synthesizes the bias card data "
                "with your language findings.",
                context={"article_body": article.get("body", ""), "bias_card": bias_card},
            )
            self._track_agent(result, "bias_language", slug)
            llm_result = _extract_dict(result) or {}
            if not llm_result and result.content:
                self._log_raw_on_parse_failure(result, "Bias Language", slug, "08-bias-language")
            bias_card["language_bias"] = llm_result.get("language_bias", {})
            bias_card["reader_note"] = llm_result.get("reader_note", "")

        self._write_debug_output(f"08-bias-card-{slug}.json", bias_card)
        bias_analysis = bias_card

        # Build follow_up object for TP (Python assembly, not agent output)
        follow_up_data = None
        if assignment.follow_up_to:
            prev_headline = self._get_previous_headline(assignment.follow_up_to)
            parts = assignment.follow_up_to.split("-")
            prev_date = f"{parts[1]}-{parts[2]}-{parts[3]}" if len(parts) >= 5 else ""
            follow_up_data = {
                "previous_tp_id": assignment.follow_up_to,
                "previous_headline": prev_headline,
                "previous_date": prev_date,
                "previous_slug": "",
                "reason": assignment.follow_up_reason or "",
            }
            tp_path = Path(self.output_dir) / prev_date / f"{assignment.follow_up_to}.json"
            if tp_path.exists():
                try:
                    prev_data = json.loads(tp_path.read_text(encoding="utf-8"))
                    follow_up_data["previous_slug"] = prev_data.get("metadata", {}).get("topic_slug", "")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("Could not read follow-up TP %s: %s", assignment.follow_up_to, e)

        # Restore actors_quoted from the research dossier onto the final
        # sources. The Writer doesn't need actors_quoted in its source-ref
        # contract (it reads them from the dossier context directly), and
        # QA+Fix's sources[] replacement drops them. The final TP is the
        # only place they need to be present.
        dossier_actors = {
            s["url"]: s.get("actors_quoted", [])
            for s in research_dossier.get("sources", []) or []
            if s.get("url")
        }
        for src in article.get("sources", []):
            url = src.get("url")
            if url and url in dossier_actors:
                src["actors_quoted"] = dossier_actors[url]
            src["country"] = _normalise_country(src.get("country"))
            src["language"] = _normalise_language(src.get("language"))

        # Restore estimated_date from research dossier onto Writer's sources.
        # The Writer re-indexes rsrc-NNN → src-NNN but drops estimated_date.
        # Python copies it back via URL lookup — no prompt change needed.
        dossier_dates = {
            s["url"]: s.get("estimated_date")
            for s in research_dossier.get("sources", [])
            if s.get("estimated_date")
        }
        for src in article.get("sources", []):
            url = src.get("url", "")
            if url in dossier_dates:
                src["estimated_date"] = dossier_dates[url]
            elif url:
                # Writer-added source (via web_search) — try URL extraction
                est = _extract_date_from_url(url)
                if est:
                    src["estimated_date"] = est

        # Strip internal rsrc_id before TP assembly so it never leaks
        # into the published Topic Package JSON.
        article["sources"] = _strip_internal_fields_from_sources(
            article.get("sources", [])
        )

        # Assemble TopicPackage. ``perspectives`` carries the enriched
        # ``position_clusters`` from Perspektiv V2. ``gaps`` carries the
        # Phase 2 reducer's ``coverage_gaps`` from the Hydrated path
        # (empty list on Production, which has no Phase 2). Perspektiv's
        # ``missing_positions`` lives under
        # ``bias_analysis.perspectives.missing_positions`` — different
        # semantic, different field.
        return TopicPackage(
            id=assignment.id,
            metadata={
                "title": assignment.title,
                "date": self.state.date if self.state else "",
                "status": "review",
                "topic_slug": assignment.topic_slug,
                "priority": assignment.priority,
                "follow_up": follow_up_data,
            },
            sources=article.get("sources", []),
            perspectives=perspective_analysis.get("position_clusters", []),
            divergences=qa_analysis.get("divergences", []),
            gaps=research_dossier.get("coverage_gaps", []) or [],
            article=article,
            bias_analysis=bias_analysis,
            transparency={
                "selection_reason": assignment.selection_reason,
                "pipeline_run": {
                    "run_id": self.state.run_id if self.state else "",
                    "date": self.state.date if self.state else "",
                },
                "article_original": article_original if qa_analysis.get("proposed_corrections") else None,
                "qa_problems_found": qa_analysis.get("problems_found", []),
                "qa_proposed_corrections": qa_analysis.get("proposed_corrections", []),
            },
            status="review",
        )

    async def _research_two_phase(self, assignment_data: dict, slug: str) -> dict:
        """Two-phase research: plan queries, execute in Python, assemble dossier."""
        from src.tools import web_search_tool

        planner = self.agents.get("researcher_plan")
        assembler = self.agents.get("researcher_assemble")
        if not planner or not assembler:
            logger.error("No 'researcher_plan' or 'researcher_assemble' agent configured")
            return {}

        # Phase 1: Plan multilingual queries
        plan_context = {
            "title": assignment_data.get("title", ""),
            "selection_reason": assignment_data.get("selection_reason", ""),
            "raw_data": assignment_data.get("raw_data", {}),
        }
        plan_result = await planner.run(
            f"Plan multilingual research queries for this topic. Today is {self.state.date}.",
            context=plan_context,
        )
        self._track_agent(plan_result, "researcher_plan", slug)

        # Strict schema wraps the queries list as ``{"queries": [...]}``.
        # Unwrap before consuming. Fall back to raw extraction if a
        # provider didn't apply the schema.
        queries_obj = plan_result.structured
        if isinstance(queries_obj, dict):
            queries = queries_obj.get("queries")
        else:
            queries = queries_obj
        if not queries or not isinstance(queries, list):
            queries = _extract_list(plan_result) or []
        if not queries:
            logger.warning("Researcher planner for '%s' returned no queries", slug)
            return {}

        languages = {q.get("language", "en") for q in queries}
        logger.info("Researcher plan: %d queries across %d languages for '%s'",
                     len(queries), len(languages), slug)
        self._write_debug_output(f"04-researcher-plan-{slug}.json", queries)

        # Phase 2: Execute searches in Python (no LLM)
        search_results = []
        for q in queries:
            query_str = q.get("query", "")
            if not query_str:
                continue
            try:
                result_text = await web_search_tool.execute(query=query_str)
                search_results.append({
                    "query": query_str,
                    "language": q.get("language", "en"),
                    "results": result_text,
                })
            except Exception as e:
                logger.warning("Research search failed for '%s': %s", query_str, e)
                search_results.append({
                    "query": query_str,
                    "language": q.get("language", "en"),
                    "results": f"Error: {e}",
                })

        successful = len([r for r in search_results if not r["results"].startswith("Error")])
        logger.info("Researcher search: %d/%d queries returned results for '%s'",
                     successful, len(search_results), slug)

        # Deduplicate by URL
        search_results = _deduplicate_search_results(search_results)

        # Enrich search results with estimated publication dates from URLs
        for sr in search_results:
            raw = sr.get("results", "")
            url_pattern = re.compile(r"^\s{3}(https?://\S+)", re.MULTILINE)
            urls_with_dates = []
            for url_match in url_pattern.finditer(raw):
                url = url_match.group(1)
                est_date = _extract_date_from_url(url)
                if est_date:
                    urls_with_dates.append({"url": url, "estimated_date": est_date})
            if urls_with_dates:
                sr["url_dates"] = urls_with_dates

        self._write_debug_output(f"04-researcher-search-{slug}.json", search_results)

        # Phase 3: Assemble dossier (one LLM call, no tools)
        assemble_result = await assembler.run(
            "Build a research dossier from these search results. "
            "Extract sources, actors, divergences, and coverage gaps.",
            context={
                "assignment": {
                    "title": assignment_data.get("title", ""),
                    "selection_reason": assignment_data.get("selection_reason", ""),
                },
                "date": self.state.date,
                "search_results": search_results,
            },
        )
        self._track_agent(assemble_result, "researcher_assemble", slug)

        dossier = _extract_dict(assemble_result) or {}

        # Assembler emits sources without `id` or `estimated_date`; Python
        # owns both. Array order is the assembler's editorial decision —
        # do not reorder.
        sources = dossier.get("sources") or []
        for idx, source in enumerate(sources):
            if not isinstance(source, dict):
                continue
            source["id"] = f"rsrc-{idx + 1:03d}"
            if not source.get("estimated_date"):
                url = source.get("url", "") or ""
                est = _extract_date_from_url(url)
                if est:
                    source["estimated_date"] = est

        # Check for old sources and log warnings
        if dossier and self.state:
            run_date = datetime.strptime(self.state.date, "%Y-%m-%d")
            for source in dossier.get("sources", []):
                est_date_str = source.get("estimated_date")
                if not est_date_str:
                    continue
                try:
                    est_date = datetime.strptime(est_date_str, "%Y-%m-%d")
                except ValueError:
                    continue
                age_days = (run_date - est_date).days
                if age_days > 30:
                    logger.warning(
                        "Old source in '%s': %s (%s, %d days old)",
                        slug, source.get("outlet", ""), est_date_str, age_days,
                    )

        # Write debug output (raw content if parsing failed)
        if dossier:
            self._write_debug_output(f"04-researcher-{slug}.json", dossier)
        else:
            self._log_raw_on_parse_failure(assemble_result, "Researcher Assemble", slug, "04-researcher")

        return dossier

    async def verify(
        self, packages: list[TopicPackage]
    ) -> list[TopicPackage]:
        """Verify integrity: count completed vs failed packages."""
        total = len(packages)
        completed = len([p for p in packages if p.status != "failed"])
        failed = len([p for p in packages if p.status == "failed"])

        if completed + failed != total:
            logger.error(
                "Verify: count mismatch! completed(%d) + failed(%d) != total(%d)",
                completed,
                failed,
                total,
            )

        logger.info(
            "Verify: %d/%d topics completed, %d failed",
            completed,
            total,
            failed,
        )

        # Check source language diversity per topic
        for pkg in packages:
            if pkg.status == "failed":
                continue
            sources = pkg.article.get("sources", []) if isinstance(pkg.article, dict) else []
            langs = {s.get("language", "") for s in sources if s.get("language")}
            if len(langs) == 1:
                lang = next(iter(langs))
                logger.warning(
                    "Verify: topic '%s' has sources in only one language (%s). "
                    "Consider adding non-English sources.",
                    pkg.id,
                    lang,
                )

        return packages

    # ------------------------------------------------------------------
    # Partial run support
    # ------------------------------------------------------------------

    def _load_debug_output(self, date: str, filename: str) -> dict | list | None:
        """Load a debug output file from a previous run."""
        path = Path(self.output_dir) / date / filename
        if not path.exists():
            logger.error("Debug file not found: %s", path)
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Could not parse debug file %s: %s", path, e)
            return None

    def _find_latest_output_date(self) -> str | None:
        """Find the most recent date directory in output/."""
        out = Path(self.output_dir)
        if not out.exists():
            return None
        dates = sorted(
            [d.name for d in out.iterdir() if d.is_dir() and d.name[:4].isdigit()]
        )
        return dates[-1] if dates else None

    async def run_partial(
        self,
        from_step: str,
        topic_filter: int | None = None,
        reuse_date: str | None = None,
        to_step: str | None = None,
    ) -> list[TopicPackage]:
        """Run pipeline from a specific step, loading earlier data from debug output.

        If to_step is given, stop after that step (inclusive).
        """
        import asyncio

        # Resolve which date to load debug data from
        reuse = reuse_date or self._find_latest_output_date()
        if not reuse:
            raise PipelineError("No previous output found to reuse")

        date = datetime.now().strftime("%Y-%m-%d")
        run_id = f"run-{date}-{uuid4().hex[:6]}"
        self.state = PipelineState(
            run_id=run_id,
            date=date,
            current_step=from_step,
            started_at=datetime.now().isoformat(),
        )

        logger.info(
            "Partial run: starting from '%s'%s, reusing data from %s",
            from_step,
            f" to '{to_step}'" if to_step else "",
            reuse,
        )

        # Determine which steps to skip/run based on from_step and to_step
        step_order = self.STEP_ORDER
        from_idx = step_order.index(from_step)
        to_idx = step_order.index(to_step) if to_step else len(step_order) - 1

        # --- Load assignments and apply post-load filters (needed for researcher onward) ---
        assignments: list[TopicAssignment] = []
        if from_idx >= step_order.index("researcher"):
            raw_assignments = self._load_debug_output(reuse, "03-editor-assignments.json")
            if not raw_assignments or not isinstance(raw_assignments, list):
                raise PipelineError(
                    f"Could not load 03-editor-assignments.json from {reuse}"
                )
            for a in raw_assignments:
                assignments.append(
                    TopicAssignment(
                        id=a.get("id", a.get("topic_id", "")),
                        title=a.get("title", ""),
                        priority=a.get("priority", 5),
                        topic_slug=a.get("topic_slug", ""),
                        selection_reason=a.get("selection_reason", ""),
                        raw_data=a.get("raw_data", {}),
                        follow_up_to=a.get("follow_up_to"),
                        follow_up_reason=a.get("follow_up_reason"),
                    )
                )
            logger.info("Loaded %d assignments from %s", len(assignments), reuse)

            # Apply topic filter (1-based index)
            if topic_filter is not None:
                if topic_filter < 1 or topic_filter > len(assignments):
                    raise PipelineError(
                        f"--topic {topic_filter} out of range (have {len(assignments)} topics)"
                    )
                assignments = [assignments[topic_filter - 1]]
                logger.info("Filtered to topic %d: %s", topic_filter, assignments[0].title)

            # Filter out rejected topics (priority 0)
            pre_filter_count = len(assignments)
            assignments = [a for a in assignments if a.priority > 0]
            filtered_count = pre_filter_count - len(assignments)
            if filtered_count:
                logger.info("Filtered %d rejected topic(s) (priority 0)", filtered_count)
            if not assignments:
                logger.warning("All selected assignments have priority 0 — nothing to produce")
                self.state.current_step = "done"
                await self._save_state()
                return packages

            # Sort + slice to production budget (same logic as run())
            assignments.sort(
                key=lambda a: (
                    -a.priority,
                    -len(a.raw_data.get("source_ids", [])),
                )
            )
            if len(assignments) > self.max_produce:
                logger.info(
                    "Production budget: %d accepted topics, producing top %d",
                    len(assignments), self.max_produce,
                )
                assignments = assignments[: self.max_produce]

        # --- Load per-topic data for later steps ---
        dossiers: dict[str, dict] = {}
        writer_outputs: dict[str, dict] = {}

        # Load researcher dossiers (needed for --from perspektiv onward)
        if from_idx >= step_order.index("perspektiv"):
            for assignment in assignments:
                slug = assignment.topic_slug or assignment.id
                filename = f"04-researcher-{slug}.json"
                dossier = self._load_debug_output(reuse, filename)
                if dossier and isinstance(dossier, dict):
                    dossiers[slug] = dossier
                    logger.info("Loaded researcher dossier: %s", filename)
                else:
                    logger.warning("No researcher dossier found: %s", filename)

        # Load perspektiv outputs (needed when perspektiv is skipped: --from writer/qa_analyze onward)
        perspektiv_outputs: dict[str, dict] = {}
        if from_idx >= step_order.index("writer"):
            for assignment in assignments:
                slug = assignment.topic_slug or assignment.id
                filename = f"04b-perspektiv-{slug}.json"
                perspektiv_data = self._load_debug_output(reuse, filename)
                if perspektiv_data and isinstance(perspektiv_data, dict):
                    perspektiv_outputs[slug] = perspektiv_data
                    logger.info("Loaded perspektiv output: %s", filename)
                else:
                    logger.warning("No perspektiv output found: %s", filename)

        # Load writer outputs (needed for --from qa_analyze onward)
        if from_idx >= step_order.index("qa_analyze"):
            for assignment in assignments:
                slug = assignment.topic_slug or assignment.id
                filename = f"05-writer-{slug}.json"
                writer_data = self._load_debug_output(reuse, filename)
                if writer_data and isinstance(writer_data, dict):
                    # Writer debug output is a full TopicPackage — extract the article
                    writer_outputs[slug] = writer_data.get("article", writer_data)
                    logger.info("Loaded writer output: %s", filename)
                else:
                    logger.warning("No writer output found: %s", filename)

        # --- Execute remaining steps ---
        packages: list[TopicPackage] = []

        if from_step in ("collector", "curator", "editor"):
            # Load raw findings for curator/editor starts
            raw_findings: list[dict] = []
            if from_idx >= step_order.index("curator"):
                raw_findings = self._load_debug_output(reuse, "01-collector-raw.json") or []
                logger.info("Loaded %d raw findings from %s", len(raw_findings), reuse)

            curated_topics: list[dict] = []
            if from_idx >= step_order.index("editor"):
                curated_topics = self._load_debug_output(reuse, "02-curator-topics.json") or []
                logger.info("Loaded %d curated topics from %s", len(curated_topics), reuse)

            # Run the steps that weren't skipped
            if from_step == "collector":
                raw_findings = await self.collect()
                self._write_debug_output("01-collector-raw.json", raw_findings)
                if to_step == "collector":
                    logger.info("Stopping after step 'collector' as requested.")
                    self.state.current_step = "done"
                    await self._save_state()
                    return packages

            if from_idx <= step_order.index("curator"):
                curated_topics = await self.curate(raw_findings)
                self._write_debug_output("02-curator-topics.json", curated_topics)
                if to_idx <= step_order.index("curator"):
                    logger.info("Stopping after step 'curator' as requested.")
                    self.state.current_step = "done"
                    await self._save_state()
                    return packages

            if from_idx <= step_order.index("editor"):
                assignments = await self.editorial_conference(curated_topics)
                self._write_debug_output(
                    "03-editor-assignments.json",
                    [asdict(a) for a in assignments],
                )
                if topic_filter is not None:
                    assignments = [assignments[topic_filter - 1]]
                if to_idx <= step_order.index("editor"):
                    logger.info("Stopping after step 'editor' as requested.")
                    self.state.current_step = "done"
                    await self._save_state()
                    return packages

            # Fall through to produce
            packages = await self.produce(assignments, to_step=to_step)

        elif from_step == "researcher":
            packages = await self.produce(assignments, to_step=to_step)

        elif from_step in ("perspektiv", "writer", "qa_analyze"):
            # Run from perspektiv/writer/qa_analyze with preloaded data
            for i, assignment in enumerate(assignments):
                if i > 0:
                    logger.info("Waiting 30s before next topic to avoid rate limits...")
                    await asyncio.sleep(30)
                slug = assignment.topic_slug or assignment.id
                try:
                    pkg = await self._produce_single(
                        assignment,
                        preloaded_dossier=dossiers.get(slug),
                        preloaded_article=writer_outputs.get(slug) if from_idx >= step_order.index("qa_analyze") else None,
                        skip_perspektiv=from_step in ("writer", "qa_analyze"),
                        to_step=to_step,
                        preloaded_perspectives=perspektiv_outputs.get(slug),
                    )
                    packages.append(pkg)
                except Exception as e:
                    logger.exception("Failed to produce topic '%s': %s", assignment.id, e)
                    packages.append(TopicPackage(
                        id=assignment.id,
                        metadata={
                            "title": assignment.title,
                            "date": self.state.date,
                            "status": "failed",
                            "topic_slug": assignment.topic_slug,
                        },
                        status="failed",
                        error=str(e),
                    ))

        elif from_step == "bias_detector":
            # Run only the bias card step with all data loaded from debug output
            for i, assignment in enumerate(assignments):
                slug = assignment.topic_slug or assignment.id

                # Load article — prefer corrected version, fall back to writer output
                correction_file = f"07-writer-correction-{slug}.json"
                writer_file = f"05-writer-{slug}.json"
                article_data = self._load_debug_output(reuse, correction_file)
                if not article_data or not isinstance(article_data, dict):
                    article_data = self._load_debug_output(reuse, writer_file)
                if not article_data or not isinstance(article_data, dict):
                    logger.error("No article found for '%s'", slug)
                    continue
                # Writer debug output may be a full TopicPackage — extract the article
                article = article_data.get("article", article_data)

                # Load supporting data
                perspective_analysis = self._load_debug_output(reuse, f"04b-perspektiv-{slug}.json") or {}
                qa_analysis = self._load_debug_output(reuse, f"06-qa-analyze-{slug}.json") or {}
                research_dossier = self._load_debug_output(reuse, f"04-researcher-{slug}.json") or {}

                # Build bias card (Python, 0 tokens)
                bias_card = _build_bias_card(article, perspective_analysis, qa_analysis, research_dossier)

                # LLM language analysis
                if bias_language := self.agents.get("bias_language"):
                    result = await bias_language.run(
                        "Analyze this article text for linguistic bias patterns. "
                        "Then write a reader note that synthesizes the bias card data "
                        "with your language findings.",
                        context={"article_body": article.get("body", ""), "bias_card": bias_card},
                    )
                    self._track_agent(result, "bias_language", slug)
                    llm_result = _extract_dict(result) or {}
                    bias_card["language_bias"] = llm_result.get("language_bias", {})
                    bias_card["reader_note"] = llm_result.get("reader_note", "")

                self._write_debug_output(f"08-bias-card-{slug}.json", bias_card)

                packages.append(TopicPackage(
                    id=assignment.id,
                    metadata={
                        "title": assignment.title,
                        "date": self.state.date,
                        "status": "review",
                        "topic_slug": slug,
                    },
                    sources=article.get("sources", []),
                    article=article,
                    bias_analysis=bias_card,
                    status="review",
                ))

        # Skip verify and write_output if we stopped before writer
        writer_idx = step_order.index("writer")
        if to_idx < writer_idx:
            logger.info("Stopping after step '%s' as requested.", to_step)
            self.state.current_step = "done"
            await self._save_state()
            return packages

        # Verify and write output
        packages = await self.verify(packages)
        await self._write_output(packages)

        if to_step:
            logger.info("Stopping after step '%s' as requested.", to_step)

        self.state.current_step = "done"
        await self._save_state()

        return packages

    def _write_debug_output(self, filename: str, data: object) -> None:
        """Write intermediate step output as JSON for debugging."""
        out = Path(self.output_dir) / self.state.date
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info("Debug output: %s", filename)

    def _log_raw_on_parse_failure(
        self, result: object, agent_name: str, slug: str, debug_prefix: str,
    ) -> None:
        """Write raw LLM content to a debug file when _extract_dict fails."""
        content = getattr(result, "content", "") or ""
        if not content:
            return
        filename = f"{debug_prefix}-{slug}-RAW.txt"
        out = Path(self.output_dir) / self.state.date
        out.mkdir(parents=True, exist_ok=True)
        path = out / filename
        path.write_text(content, encoding="utf-8")
        logger.warning(
            "%s for '%s': JSON extraction failed (%d chars). Raw output saved to %s",
            agent_name, slug, len(content), filename,
        )

    async def _save_state(self) -> None:
        """Save current pipeline state to disk."""
        path = Path(self.state_dir) / f"{self.state.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self.state)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _load_incomplete_state(self, date: str) -> PipelineState | None:
        """Check for incomplete runs from the same date."""
        state_path = Path(self.state_dir)
        if not state_path.exists():
            return None
        for f in state_path.glob(f"run-{date}-*.json"):
            try:
                data = json.loads(f.read_text())
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Could not parse state file %s: %s", f, e)
                continue
            state = PipelineState(**data)
            if state.current_step != "done":
                return state
        return None

    async def _write_output(self, packages: list[TopicPackage]) -> None:
        """Write completed TopicPackages as JSON to output_dir."""
        out = Path(self.output_dir) / self.state.date
        out.mkdir(parents=True, exist_ok=True)
        for pkg in packages:
            if pkg.status == "failed":
                continue
            path = out / f"{pkg.id}.json"
            path.write_text(
                json.dumps(pkg.to_dict(), indent=2, ensure_ascii=False)
            )
        # Also write a run summary
        summary_path = out / f"{self.state.run_id}-summary.json"
        summary = {
            "run_id": self.state.run_id,
            "date": self.state.date,
            "total_topics": len(packages),
            "completed": len([p for p in packages if p.status != "failed"]),
            "failed": len([p for p in packages if p.status == "failed"]),
            "packages": [p.id for p in packages],
        }
        summary_path.write_text(json.dumps(summary, indent=2))

        # Write agent stats (token usage, durations)
        if self._agent_stats:
            stats_path = out / f"{self.state.run_id}-stats.json"
            stats = {
                "run_id": self.state.run_id,
                "date": self.state.date,
                "agents": self._agent_stats,
                "total_tokens": sum(s["tokens_used"] for s in self._agent_stats),
                "total_duration_seconds": sum(s["duration_seconds"] for s in self._agent_stats),
                "total_cost_usd": sum(s.get("cost_usd") or 0.0 for s in self._agent_stats),
            }
            stats_path.write_text(json.dumps(stats, indent=2))
