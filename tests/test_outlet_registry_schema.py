"""Schema conformance tests for ``config/outlet_registry.json``.

Audit 2026-08-20, finding D1: the 2026-08-12 bulk classification wrote 309
entries keyed on ``display_name`` where the registry and its only consumer
(``src/hydration.py`` — ``registry_entry.get("outlet")``) use ``outlet``. The
classification session ran its own validator and reported "Keine
Schema-Validierungsfehler" — true, and useless: it compared *values* against
the three vocabularies and never checked *field names*. For all 309 hostnames
``.get("outlet")`` returned ``None`` and the expression fell through to the
feed-supplied name, so registry-driven outlet naming was silently dead for
every outlet added that day.

This module is the guard whose absence let that ship. It asserts the shape of
the registry, not the truth of its values — fact-checking entries is the
re-verification workstream, not something a test can do.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from src.region_buckets import lookup_region
from src.stages._helpers import LANGUAGE_NAMES

REGISTRY_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "outlet_registry.json"
)

# Every entry must carry these. ``outlet`` is the name field — ``display_name``
# is the D1 break and must never reappear (see test_no_entry_uses_display_name).
REQUIRED_FIELDS = frozenset(
    {"outlet", "country", "language", "type", "tier", "bias_note"}
)

# ``editorial_independence`` is optional by one documented exception:
# khaligyoun.com had it removed on 2026-08-20 because the audit found no
# evidence for the ``state_influenced`` it had been assigned, and
# editorial_independence_vocabulary has no neutral/unknown value to demote it
# to. Consumers already handle absence (propagate_outlet_metadata setdefault
# -> None; the renderer's "Country only" branch). ``alt_languages`` is a
# genuinely optional enrichment carried by 17 entries.
OPTIONAL_FIELDS = frozenset({"editorial_independence", "alt_languages"})

# Outlet names that legitimately appear on more than one hostname: language
# editions, ccTLD pairs, and CDN/alias domains of one publisher. Each was
# checked by hand on 2026-08-21. A name NOT on this list appearing twice means
# two different outlets were given the same name — the failure mode that
# produced the epochtimes.com / theepochtimes.com pair (audit D4), where one
# remembered outlet was written onto two distinct hostnames.
DUPLICATE_NAME_ALLOWLIST = {
    "BBC": "bbc.co.uk, bbc.com, bbci.co.uk — one broadcaster, incl. its asset domain",
    "Euronews": "euronews.com + de./fr. language editions",
    "Xinhua": "news.cn, xinhuanet.com, english.news.cn — one state agency",
    "Al Jazeera": "aljazeera.com, aljazeera.net — same publisher, two TLDs",
    "Anadolu Agency": "aa.com.tr, anadoluagency.com — same agency, two TLDs",
    "Haaretz": "haaretz.co.il, haaretz.com — Hebrew and English editions",
    "PRC Ministry of Foreign Affairs": "fmprc.gov.cn, mfa.gov.cn — one ministry",
    "Press TV": "presstv.ir, presstv.co.uk — one broadcaster, two TLDs",
    "TASS": "tass.ru, tass.com — one agency, two TLDs",
    "Ukrinform": "ukrinform.ua, ukrinform.net — one agency, two TLDs",
    # Genuinely one brand (Chinese vs English edition) but the shared name is
    # undifferentiated, which is precisely how audit D4 spotted that the two
    # hostnames had been given byte-identical metadata. Distinguishing the
    # names is a value change and belongs to the re-verification workstream.
    "The Epoch Times": "epochtimes.com (zh), theepochtimes.com (en) — see audit D4",
}


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entries(registry: dict) -> dict[str, dict]:
    """Outlet entries only — top-level ``_``-prefixed keys are metadata."""
    return {
        host: entry
        for host, entry in registry.items()
        if not host.startswith("_") and isinstance(entry, dict)
    }


def test_registry_is_non_empty(entries: dict[str, dict]):
    assert len(entries) > 600, f"only {len(entries)} entries — registry truncated?"


# --- (a) field-set conformance ---------------------------------------------


def test_no_entry_uses_display_name(entries: dict[str, dict]):
    """Audit D1. This is the assertion that would have blocked e5bd305."""
    offenders = sorted(h for h, e in entries.items() if "display_name" in e)
    assert not offenders, (
        f"{len(offenders)} entries use 'display_name'; the registry field is "
        f"'outlet' (src/hydration.py reads registry_entry.get('outlet')). "
        f"First 10: {offenders[:10]}"
    )


def test_every_entry_has_all_required_fields(entries: dict[str, dict]):
    missing = {
        host: sorted(REQUIRED_FIELDS - set(entry))
        for host, entry in entries.items()
        if not REQUIRED_FIELDS <= set(entry)
    }
    assert not missing, f"entries missing required fields: {missing}"


def test_no_entry_has_unknown_fields(entries: dict[str, dict]):
    known = REQUIRED_FIELDS | OPTIONAL_FIELDS
    unknown = {
        host: sorted(set(entry) - known)
        for host, entry in entries.items()
        if set(entry) - known
    }
    assert not unknown, (
        f"entries carry fields outside the schema: {unknown}. Adding a field is "
        f"a decision — extend REQUIRED_FIELDS/OPTIONAL_FIELDS deliberately."
    )


# --- (b) value-vocabulary conformance --------------------------------------


@pytest.mark.parametrize(
    "field, vocabulary_key",
    [
        ("type", "type_vocabulary"),
        ("tier", "tier_vocabulary"),
        ("editorial_independence", "editorial_independence_vocabulary"),
    ],
)
def test_values_conform_to_vocabulary(
    registry: dict, entries: dict[str, dict], field: str, vocabulary_key: str
):
    vocabulary = registry["_schema"][vocabulary_key]
    offenders = [
        (host, entry[field])
        for host, entry in entries.items()
        if field in entry and entry[field] not in vocabulary
    ]
    assert not offenders, f"{field} values outside {vocabulary_key}: {offenders}"


# --- (c) every country resolves to a region bucket -------------------------


def test_every_country_has_a_region_bucket(entries: dict[str, dict]):
    """A country that does not bucket drops the outlet out of the Source Map
    and geographic_coverage silently — the 2026-08-19 Congo defect.
    """
    unbucketed = sorted(
        (host, entry["country"])
        for host, entry in entries.items()
        if entry.get("country") and lookup_region(entry["country"]) is None
    )
    assert not unbucketed, (
        f"countries with no region bucket: {unbucketed}. Use the spelling "
        f"config/region_buckets.json carries — lookup_region does no aliasing."
    )


# --- (d) language conformance ----------------------------------------------


def test_every_language_is_a_known_code(entries: dict[str, dict]):
    """``language`` must be a code src.stages._helpers.LANGUAGE_NAMES knows.

    Extend LANGUAGE_NAMES when a genuinely new language enters the registry;
    do not exclude the entry here.
    """
    unknown = sorted(
        (host, entry["language"])
        for host, entry in entries.items()
        if entry.get("language") and entry["language"] not in LANGUAGE_NAMES
    )
    assert not unknown, (
        f"language codes unknown to LANGUAGE_NAMES: {unknown}. Add the code to "
        f"src/stages/_helpers.py rather than excluding the entry."
    )


# --- (e) outlet-name uniqueness --------------------------------------------


def test_no_undocumented_duplicate_outlet_names(entries: dict[str, dict]):
    by_name: dict[str, list[str]] = defaultdict(list)
    for host, entry in entries.items():
        name = entry.get("outlet")
        if isinstance(name, str) and name.strip():
            by_name[name].append(host)

    duplicates = {
        name: sorted(hosts) for name, hosts in by_name.items() if len(hosts) > 1
    }
    undocumented = {
        name: hosts
        for name, hosts in duplicates.items()
        if name not in DUPLICATE_NAME_ALLOWLIST
    }
    assert not undocumented, (
        f"outlet names shared by hostnames that are not a documented "
        f"multi-hostname outlet: {undocumented}. Two different outlets sharing "
        f"a name means one was written onto the wrong hostname (audit D5). If "
        f"they are genuinely one outlet, add the name to "
        f"DUPLICATE_NAME_ALLOWLIST with its rationale."
    )


def test_duplicate_allowlist_has_no_stale_entries(entries: dict[str, dict]):
    """An allowlisted name that no longer collides is dead documentation."""
    counts: dict[str, int] = defaultdict(int)
    for entry in entries.values():
        name = entry.get("outlet")
        if isinstance(name, str):
            counts[name] += 1
    stale = sorted(n for n in DUPLICATE_NAME_ALLOWLIST if counts.get(n, 0) < 2)
    assert not stale, f"DUPLICATE_NAME_ALLOWLIST entries no longer collide: {stale}"


# --- consumer path (audit D1's actual failure point) -----------------------


def test_outlet_resolves_through_lookup_outlet(entries: dict[str, dict]):
    """Exercise the exact expression that D1 broke.

    ``src/hydration.py``::

        output["outlet"] = registry_entry.get("outlet") or output.get("outlet")

    Under D1 this returned ``None`` for all 309 new hostnames and fell through
    to the feed name. Resolve every hostname through the real ``lookup_outlet``
    and assert the left operand is truthy.
    """
    from src.outlet_registry import lookup_outlet

    unresolved = []
    for host in sorted(entries):
        hit = lookup_outlet(f"https://{host}/some/article")
        if hit is None or not hit.get("outlet"):
            unresolved.append(host)
    assert not unresolved, (
        f"{len(unresolved)} hostnames do not yield an 'outlet' through "
        f"lookup_outlet — hydration would fall back to the feed name. "
        f"First 10: {unresolved[:10]}"
    )
