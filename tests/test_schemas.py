"""Tests for OpenRouter structured-output schemas in src.schemas.

Covers the three Phase-5 schemas wired up in TASK-HYDRATED-ACTIVATION:
- HYDRATION_PHASE1_SCHEMA
- HYDRATION_PHASE2_SCHEMA
- PERSPECTIVE_SYNC_SCHEMA (sanity check; was correct pre-task)

The project does not depend on the ``jsonschema`` package (no new
dependencies are added by this task), so a minimal recursive validator
covers the JSON Schema features actually used here: ``type`` (single or
union), ``properties``, ``required``, ``items``, ``additionalProperties:
false``. That subset is sufficient for the schemas under test and matches
the strict-mode rules OpenRouter enforces server-side.
"""

from __future__ import annotations

import pytest

from src.schemas import (
    HYDRATION_PHASE1_SCHEMA,
    HYDRATION_PHASE2_SCHEMA,
    PERSPECTIVE_SYNC_SCHEMA,
)


class SchemaError(AssertionError):
    pass


def _check_type(instance, expected) -> bool:
    """Return True if ``instance`` matches one or more JSON Schema types.

    Mirrors the JSON Schema ``type`` keyword: a string for a single type
    or a list of strings for a union.
    """
    if isinstance(expected, list):
        return any(_check_type(instance, t) for t in expected)
    if expected == "object":
        return isinstance(instance, dict)
    if expected == "array":
        return isinstance(instance, list)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "integer":
        return isinstance(instance, bool) is False and isinstance(instance, int)
    if expected == "number":
        return isinstance(instance, bool) is False and isinstance(instance, (int, float))
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "null":
        return instance is None
    raise SchemaError(f"Unsupported type in schema: {expected!r}")


def _validate(instance, schema, path: str = "$") -> None:
    """Tiny JSON-Schema validator covering the keywords used in src.schemas."""
    if "type" in schema and not _check_type(instance, schema["type"]):
        raise SchemaError(f"{path}: expected type {schema['type']!r}, got {type(instance).__name__}")

    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in instance:
                raise SchemaError(f"{path}: missing required key {key!r}")
        if schema.get("additionalProperties") is False:
            extras = set(instance.keys()) - set(properties.keys())
            if extras:
                raise SchemaError(f"{path}: additional properties not allowed: {sorted(extras)!r}")
        for key, value in instance.items():
            if key in properties:
                _validate(value, properties[key], f"{path}.{key}")

    if isinstance(instance, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(instance):
                _validate(item, item_schema, f"{path}[{i}]")


# -- HYDRATION_PHASE1_SCHEMA -------------------------------------------------

def test_hydration_phase1_schema_validates_minimal_output():
    minimal = {
        "article_analyses": [
            {"article_index": 0, "summary": "x", "actors_quoted": []},
        ],
    }
    _validate(minimal, HYDRATION_PHASE1_SCHEMA)


def test_hydration_phase1_schema_rejects_missing_field():
    bad = {
        "article_analyses": [
            {
                "article_index": 0,
                "summary": "x",
                "actors_quoted": [
                    {
                        "name": "A",
                        "role": "spokesperson",
                        "type": "government",
                        "position": "p",
                        # verbatim_quote omitted on purpose
                    },
                ],
            },
        ],
    }
    with pytest.raises(SchemaError):
        _validate(bad, HYDRATION_PHASE1_SCHEMA)


def test_hydration_phase1_schema_accepts_null_verbatim_quote():
    output = {
        "article_analyses": [
            {
                "article_index": 0,
                "summary": "x",
                "actors_quoted": [
                    {
                        "name": "A",
                        "role": "spokesperson",
                        "type": "government",
                        "position": "p",
                        "verbatim_quote": None,
                    },
                ],
            },
        ],
    }
    _validate(output, HYDRATION_PHASE1_SCHEMA)


# -- HYDRATION_PHASE2_SCHEMA -------------------------------------------------

def test_hydration_phase2_schema_validates_empty_arrays():
    _validate({"preliminary_divergences": [], "coverage_gaps": []}, HYDRATION_PHASE2_SCHEMA)


def test_hydration_phase2_schema_rejects_missing_key():
    with pytest.raises(SchemaError):
        _validate({"preliminary_divergences": []}, HYDRATION_PHASE2_SCHEMA)


# -- PERSPECTIVE_SYNC_SCHEMA --------------------------------------------------

def test_perspective_sync_schema_already_correct():
    output = {
        "position_cluster_updates": [
            {
                "id": "pc-001",
                "position_label": "x",
                "position_summary": None,
            },
        ],
    }
    _validate(output, PERSPECTIVE_SYNC_SCHEMA)
