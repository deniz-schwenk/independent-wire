"""JSON schemas for OpenRouter structured outputs (response_format).

Each constant is a JSON Schema object that defines the exact shape of one
agent's output. The schemas track each agent's INSTRUCTIONS.md OUTPUT
FORMAT section field-for-field — that prompt section is the source of
truth.

Strict mode (``response_format.json_schema.strict: true``) implies:

- Every property listed under ``properties`` must also appear in ``required``.
- ``additionalProperties: false`` on every object.
- Optional fields (where the prompt allows omission) are modelled as
  ``{"type": ["string", "null"]}`` and required, with the model emitting
  ``null`` when the field doesn't apply. The pipeline's merge / consume
  logic already treats null as absent.
- Top-level array schemas are not supported by Anthropic's strict mode.
  For agents whose prompts emit a list (Editor, Researcher PLAN), the
  schema wraps the list in an object with one ``items`` field. The
  pipeline unwraps before consuming.
"""

from __future__ import annotations

# ---------------------------------------------------------------- Curator
CURATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "relevance_score": {"type": "integer"},
                    "summary": {"type": "string"},
                },
                "required": ["title", "relevance_score", "summary"],
                "additionalProperties": False,
            },
        },
        "cluster_assignments": {
            "type": "array",
            "items": {"type": ["integer", "null"]},
        },
    },
    "required": ["topics", "cluster_assignments"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Editor
# Editor prompt emits a top-level array. Wrapped here to satisfy strict
# mode's "no top-level array" rule. Pipeline unwraps before consuming.
EDITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "priority": {"type": "integer"},
                    "selection_reason": {"type": "string"},
                    "follow_up_to": {"type": ["string", "null"]},
                    "follow_up_reason": {"type": ["string", "null"]},
                },
                "required": [
                    "title", "priority", "selection_reason",
                    "follow_up_to", "follow_up_reason",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["assignments"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Researcher PLAN
# Prompt emits a top-level array; wrapped to satisfy strict mode.
RESEARCHER_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "language": {"type": "string"},
                },
                "required": ["query", "language"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["queries"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Researcher ASSEMBLE
RESEARCHER_ASSEMBLE_SCHEMA = {
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "outlet": {"type": "string"},
                    "language": {"type": "string"},
                    "country": {"type": "string"},
                    "summary": {"type": "string"},
                    "actors_quoted": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "role": {"type": "string"},
                                "type": {"type": "string"},
                                "position": {"type": "string"},
                                "verbatim_quote": {"type": ["string", "null"]},
                            },
                            "required": [
                                "name", "role", "type", "position",
                                "verbatim_quote",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "url", "title", "outlet", "language", "country",
                    "summary", "actors_quoted",
                ],
                "additionalProperties": False,
            },
        },
        "preliminary_divergences": {
            "type": "array",
            "items": {"type": "string"},
        },
        "coverage_gaps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["sources", "preliminary_divergences", "coverage_gaps"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Perspective (V2)
PERSPECTIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "position_clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position_label": {"type": "string"},
                    "position_summary": {"type": "string"},
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["position_label", "position_summary", "source_ids"],
                "additionalProperties": False,
            },
        },
        "missing_positions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["type", "description"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["position_clusters", "missing_positions"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Writer
WRITER_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "subheadline": {"type": "string"},
        "body": {"type": "string"},
        "summary": {"type": "string"},
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "src_id": {"type": "string"},
                },
                "required": ["src_id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headline", "subheadline", "body", "summary", "sources"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- QA+Fix
# Article carries headline/subheadline/body/summary/sources (sources is
# passed through unchanged from the input). divergences[] carries five
# fields per the prompt (type, description, source_ids[], resolution,
# resolution_note).
QA_ANALYZE_SCHEMA = {
    "type": "object",
    "properties": {
        "problems_found": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "article_excerpt": {"type": "string"},
                    "problem": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["article_excerpt", "problem", "explanation"],
                "additionalProperties": False,
            },
        },
        "qa_corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "proposed_correction": {"type": "string"},
                    "correction_needed": {"type": "boolean"},
                },
                "required": ["proposed_correction", "correction_needed"],
                "additionalProperties": False,
            },
        },
        # Note: ``article.sources`` is intentionally NOT in the schema. The
        # QA prompt asks for sources to be passed through, and Python's QA
        # consumer (``_produce_single``) explicitly ignores the field
        # ("we deliberately do NOT replace article['sources']"). Strict
        # mode + ``additionalProperties: false`` forbids the model from
        # emitting sources at all, which saves tokens with no functional
        # effect.
        "article": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "subheadline": {"type": "string"},
                "body": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": [
                "headline", "subheadline", "body", "summary",
            ],
            "additionalProperties": False,
        },
        "divergences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "source_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "resolution": {"type": "string"},
                    "resolution_note": {"type": "string"},
                },
                "required": [
                    "type", "description", "source_ids",
                    "resolution", "resolution_note",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "problems_found", "qa_corrections", "divergences",
    ],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Perspective-Sync
# Strict mode forces all properties present. The prompt says "omit when
# unchanged"; with the schema, the model must emit ``null`` for unchanged
# fields. ``merge_perspective_deltas`` already treats ``null`` as
# "no change" (V2 forbids null overrides), so the semantics are preserved.
PERSPECTIVE_SYNC_SCHEMA = {
    "type": "object",
    "properties": {
        "position_cluster_updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "position_label": {"type": ["string", "null"]},
                    "position_summary": {"type": ["string", "null"]},
                },
                "required": ["id", "position_label", "position_summary"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["position_cluster_updates"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Bias Detector
BIAS_DETECTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "language_bias": {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "excerpt": {"type": "string"},
                            "issue": {"type": "string"},
                            "explanation": {"type": "string"},
                        },
                        "required": ["excerpt", "issue", "explanation"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["findings"],
            "additionalProperties": False,
        },
        "reader_note": {"type": "string"},
    },
    "required": ["language_bias", "reader_note"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Hydration Aggregator Phase 1
# Per-chunk article analysis. Each entry corresponds to one input article
# and carries its index, a one-paragraph summary, and the actor-quoted list.
# The actors_quoted shape mirrors RESEARCHER_ASSEMBLE_SCHEMA.sources[].actors_quoted[]
# so Perspective reads both shapes interchangeably. verbatim_quote is
# nullable per the prompt's "When the article only paraphrases, the field
# is null" rule.
HYDRATION_PHASE1_SCHEMA = {
    "type": "object",
    "properties": {
        "article_analyses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "article_index": {"type": "integer"},
                    "summary": {"type": "string"},
                    "actors_quoted": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "role": {"type": "string"},
                                "type": {"type": "string"},
                                "position": {"type": "string"},
                                "verbatim_quote": {"type": ["string", "null"]},
                            },
                            "required": [
                                "name", "role", "type", "position",
                                "verbatim_quote",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["article_index", "summary", "actors_quoted"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["article_analyses"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------- Hydration Aggregator Phase 2
# Cross-corpus reducer. Both arrays may legitimately be empty when no
# divergence / gap is observed; strict mode requires the keys present
# but does not enforce non-empty content.
HYDRATION_PHASE2_SCHEMA = {
    "type": "object",
    "properties": {
        "preliminary_divergences": {
            "type": "array",
            "items": {"type": "string"},
        },
        "coverage_gaps": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["preliminary_divergences", "coverage_gaps"],
    "additionalProperties": False,
}
