"""Tests for OpenRouter structured-output schemas in src.schemas.

Covers the Phase-5 schemas wired up in TASK-HYDRATED-ACTIVATION:
- HYDRATION_PHASE1_SCHEMA
- HYDRATION_PHASE2_SCHEMA
- PERSPECTIVE_SYNC_SCHEMA (sanity check; was correct pre-task)

Plus the LLM-cluster-assignment schema from TASK-CLUSTER-LLM-
ASSIGNMENT:
- CLUSTER_ASSIGNMENT_SCHEMA

The project does not depend on the ``jsonschema`` package (no new
dependencies are added by this task), so a minimal recursive validator
covers the JSON Schema features actually used here: ``type`` (single or
union), ``properties``, ``required``, ``items``, ``additionalProperties:
false``, plus ``minimum`` and ``minItems`` (added for
CLUSTER_ASSIGNMENT_SCHEMA's non-empty-non-negative ``topic_indices``
contract). That subset is sufficient for the schemas under test and
matches the strict-mode rules OpenRouter enforces server-side.
"""

from __future__ import annotations

import pytest

from src.schemas import (
    BIAS_DETECTOR_SCHEMA,
    CLUSTER_ASSIGNMENT_SCHEMA,
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

    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if instance < schema["minimum"]:
            raise SchemaError(
                f"{path}: value {instance!r} below minimum {schema['minimum']!r}"
            )

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
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise SchemaError(
                f"{path}: array length {len(instance)} below minItems {schema['minItems']}"
            )
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
                        "evidence_type": "stated",
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


# -- CLUSTER_ASSIGNMENT_SCHEMA -----------------------------------------------
# TASK-CLUSTER-LLM-ASSIGNMENT: assignment of micro-clusters to topics.


def test_cluster_assignment_schema_happy_path():
    payload = {
        "assignments": [
            {"cluster_id": "mc-003", "topic_indices": [0]},
            {"cluster_id": "mc-007", "topic_indices": [0, 4]},
            {"cluster_id": "mc-012", "topic_indices": [2]},
        ]
    }
    _validate(payload, CLUSTER_ASSIGNMENT_SCHEMA)


def test_cluster_assignment_schema_accepts_empty_assignments():
    """Zero clusters got assigned → valid shape; the orphan list
    downstream subsumes all input clusters."""
    _validate({"assignments": []}, CLUSTER_ASSIGNMENT_SCHEMA)


def test_cluster_assignment_schema_rejects_extra_top_level_field():
    payload = {
        "assignments": [{"cluster_id": "mc-001", "topic_indices": [0]}],
        "spurious": "rejected",
    }
    with pytest.raises(SchemaError):
        _validate(payload, CLUSTER_ASSIGNMENT_SCHEMA)


def test_cluster_assignment_schema_rejects_extra_per_entry_field():
    payload = {
        "assignments": [
            {
                "cluster_id": "mc-001",
                "topic_indices": [0],
                "extra": "rejected",
            }
        ]
    }
    with pytest.raises(SchemaError):
        _validate(payload, CLUSTER_ASSIGNMENT_SCHEMA)


def test_cluster_assignment_schema_rejects_empty_topic_indices():
    """A cluster row must have at least one topic — orphan-ness is
    expressed by omitting the cluster entirely, not by an empty
    topic_indices array."""
    payload = {"assignments": [{"cluster_id": "mc-001", "topic_indices": []}]}
    with pytest.raises(SchemaError):
        _validate(payload, CLUSTER_ASSIGNMENT_SCHEMA)


def test_cluster_assignment_schema_rejects_negative_topic_index():
    payload = {
        "assignments": [{"cluster_id": "mc-001", "topic_indices": [-1]}]
    }
    with pytest.raises(SchemaError):
        _validate(payload, CLUSTER_ASSIGNMENT_SCHEMA)


def test_cluster_assignment_schema_rejects_missing_cluster_id():
    payload = {"assignments": [{"topic_indices": [0]}]}
    with pytest.raises(SchemaError):
        _validate(payload, CLUSTER_ASSIGNMENT_SCHEMA)


def test_cluster_assignment_schema_rejects_missing_assignments_key():
    with pytest.raises(SchemaError):
        _validate({}, CLUSTER_ASSIGNMENT_SCHEMA)


# ---------------------------------------------------------------------------
# BIAS_DETECTOR_SCHEMA — finding_valid self-retraction marker
# ---------------------------------------------------------------------------


def _bias_payload(findings: list[dict], reader_note: str = "x") -> dict:
    return {
        "language_bias": {"findings": findings},
        "reader_note": reader_note,
    }


def test_bias_schema_rejects_finding_missing_finding_valid():
    """A finding without `finding_valid` must fail validation the same
    way as any other missing mandatory field."""
    payload = _bias_payload([
        {"excerpt": "Trump", "issue": "loaded_term", "explanation": "x"},
    ])
    with pytest.raises(SchemaError) as exc:
        _validate(payload, BIAS_DETECTOR_SCHEMA)
    assert "finding_valid" in str(exc.value)


def test_bias_schema_accepts_finding_valid_true():
    payload = _bias_payload([
        {
            "excerpt": "Trump",
            "issue": "loaded_term",
            "explanation": "x",
            "finding_valid": True,
        },
    ])
    _validate(payload, BIAS_DETECTOR_SCHEMA)  # does not raise


def test_bias_schema_accepts_finding_valid_false():
    """Self-retracted findings are valid output shape; the audit trail
    needs them to survive schema validation."""
    payload = _bias_payload([
        {
            "excerpt": "Trump",
            "issue": "loaded_term",
            "explanation": "x",
            "finding_valid": False,
        },
    ])
    _validate(payload, BIAS_DETECTOR_SCHEMA)  # does not raise


def test_bias_schema_rejects_non_boolean_finding_valid():
    """`finding_valid: "false"` (string) is a shape error — strict-mode
    must enforce the boolean type."""
    payload = _bias_payload([
        {
            "excerpt": "Trump",
            "issue": "loaded_term",
            "explanation": "x",
            "finding_valid": "false",
        },
    ])
    with pytest.raises(SchemaError):
        _validate(payload, BIAS_DETECTOR_SCHEMA)
