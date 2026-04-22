"""Pure synchronous helpers for the M4 synthesizer.

Sync; no asyncio, no Anthropic. Schema/prompt builders + quote-verification +
internal exception types live here for unit-testability without mocks.
"""
from __future__ import annotations

from typing import Any


def build_synthesis_tool_schema(
    candidate_article_ids: list[str],
    candidate_bwb_ids: list[str],
    candidate_eclis: list[str],
) -> dict[str, Any]:
    """Anthropic tool JSON-schema for the M4 synthesizer `emit_answer` call.

    Per-request `enum` on `article_id`, `bwb_id`, and `ecli` applies the
    closed-set constraint at schema-validation time — the JSON-Schema form
    of Pydantic's `Literal[...]` pattern (parent spec §15 decision #9 + M4
    spec §9 decision #20). Length bounds 40–500 for `quote` back up the
    post-hoc verification.
    """
    return {
        "name": "emit_answer",
        "description": (
            "Genereer het gestructureerde Nederlandse antwoord met "
            "gegrondveste citaten."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "korte_conclusie": {
                    "type": "string", "minLength": 40, "maxLength": 2000,
                },
                "relevante_wetsartikelen": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "article_id":    {"type": "string",
                                              "enum": list(candidate_article_ids)},
                            "bwb_id":        {"type": "string",
                                              "enum": list(candidate_bwb_ids)},
                            "article_label": {"type": "string", "minLength": 5},
                            "quote":         {"type": "string",
                                              "minLength": 40, "maxLength": 500},
                            "explanation":   {"type": "string",
                                              "minLength": 40, "maxLength": 2000},
                        },
                        "required": ["article_id", "bwb_id", "article_label",
                                     "quote", "explanation"],
                    },
                },
                "vergelijkbare_uitspraken": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "ecli":        {"type": "string",
                                            "enum": list(candidate_eclis)},
                            "quote":       {"type": "string",
                                            "minLength": 40, "maxLength": 500},
                            "explanation": {"type": "string",
                                            "minLength": 40, "maxLength": 2000},
                        },
                        "required": ["ecli", "quote", "explanation"],
                    },
                },
                "aanbeveling": {
                    "type": "string", "minLength": 40, "maxLength": 2000,
                },
            },
            "required": ["korte_conclusie", "relevante_wetsartikelen",
                         "vergelijkbare_uitspraken", "aanbeveling"],
        },
    }


__all__ = ["build_synthesis_tool_schema"]
