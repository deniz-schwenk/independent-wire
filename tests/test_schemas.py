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
    CONSOLIDATOR_SCHEMA,
    HYDRATION_PHASE1_SCHEMA,
    HYDRATION_PHASE2_SCHEMA,
    RESEARCHER_ASSEMBLE_SCHEMA,
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


# -- CONSOLIDATOR_SCHEMA ------------------------------------------------------

def test_consolidator_schema_accepts_two_string_arrays():
    output = {
        "voices_missing": [
            "Iraqi government and media voices",
            "International humanitarian organizations",
        ],
        "topics_missing": ["Humanitarian dimension of US oil blockade"],
    }
    _validate(output, CONSOLIDATOR_SCHEMA)


def test_consolidator_schema_accepts_empty_arrays():
    """Either list may be empty per the prompt's OUTPUT FORMAT field notes."""
    _validate(
        {"voices_missing": [], "topics_missing": []},
        CONSOLIDATOR_SCHEMA,
    )


def test_consolidator_schema_rejects_missing_key():
    with pytest.raises(SchemaError):
        _validate({"voices_missing": []}, CONSOLIDATOR_SCHEMA)


def test_consolidator_schema_rejects_extra_key():
    with pytest.raises(SchemaError):
        _validate(
            {"voices_missing": [], "topics_missing": [], "extra": []},
            CONSOLIDATOR_SCHEMA,
        )


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


# -- RESEARCHER_ASSEMBLE_SCHEMA ---------------------------------------------
#
# TASK-ASSEMBLE-SCHEMA-FIX. ``coverage_gaps`` was in ``required`` while
# agents/researcher/ASSEMBLE-INSTRUCTIONS.md asks for "a single JSON object
# with two top-level fields" and never names it, and
# ResearcherAssembleStage drops the key on arrival. Production only held
# together because provider-side strict decoding force-filled it. These
# tests pin both shapes as valid so the contract no longer depends on who
# decodes it.
#
# The payload below is a real captured researcher_assemble output
# (scratch/eval/t2b/partB/runs/dsn-med/researcher_assemble/
# 2026-08-19-t0.r0.json), trimmed to one source and one divergence.


def _assemble_payload(**extra):
    payload = {
        "sources": [
            {
                "url": (
                    "https://apnews.com/article/syria-israel-turkey-airstrikes-"
                    "idlib-3a0e758c87ded0f26ed71b4a92db6816"
                ),
                "title": (
                    "Israel targets air base in northwest Syria to block "
                    "Turkish troops"
                ),
                "outlet": "AP News",
                "language": "en",
                "country": "United States",
                "summary": (
                    "Baseline factual account of the strike and Israel's "
                    "stated purpose, quoting Syrian Foreign Minister Asaad "
                    "al-Shibani's condemnation."
                ),
                "actors_quoted": [
                    {
                        "name": "Asaad al-Shibani",
                        "role": "Syrian Foreign Minister",
                        "type": "government",
                        "position": (
                            "Condemns the Israeli strike as unjustified "
                            "provocation and a violation of Syrian "
                            "sovereignty."
                        ),
                        "verbatim_quote": (
                            "an unjustified provocation, a violation of "
                            "Syria's sovereignty"
                        ),
                    },
                ],
            },
        ],
        "preliminary_divergences": [
            "Western and Arabic media emphasise the unusual US rebuke of "
            "Israel, while Israeli and Russian-language outlets focus on "
            "Syria's accusations and the security status quo argument.",
        ],
    }
    payload.update(extra)
    return payload


def test_assemble_schema_validates_output_without_coverage_gaps():
    """The shape the prompt actually asks for — two top-level fields."""
    _validate(_assemble_payload(), RESEARCHER_ASSEMBLE_SCHEMA)


def test_assemble_schema_still_validates_strict_decoded_output():
    """Every assemble output on disk was strict-decoded and carries the
    key (almost always empty). Keeping the property means those stay
    valid — the change is a relaxation, not a re-shaping."""
    _validate(
        _assemble_payload(coverage_gaps=[]), RESEARCHER_ASSEMBLE_SCHEMA
    )
    _validate(
        _assemble_payload(coverage_gaps=["No civil-society voices"]),
        RESEARCHER_ASSEMBLE_SCHEMA,
    )


def test_assemble_schema_coverage_gaps_is_not_required():
    """Guard against a future re-tightening: the key's absence is the
    contract, not an oversight."""
    assert "coverage_gaps" not in RESEARCHER_ASSEMBLE_SCHEMA["required"]
    assert "coverage_gaps" in RESEARCHER_ASSEMBLE_SCHEMA["properties"]


def test_assemble_schema_still_requires_the_two_real_fields():
    for missing in ("sources", "preliminary_divergences"):
        payload = _assemble_payload()
        del payload[missing]
        with pytest.raises(SchemaError):
            _validate(payload, RESEARCHER_ASSEMBLE_SCHEMA)


def test_assemble_schema_still_rejects_unknown_top_level_key():
    """additionalProperties stays false — relaxing one key is not an
    invitation for undeclared ones."""
    with pytest.raises(SchemaError):
        _validate(
            _assemble_payload(coverage_summary=["x"]),
            RESEARCHER_ASSEMBLE_SCHEMA,
        )
