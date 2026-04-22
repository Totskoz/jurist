"""Pure synchronous helpers for the M4 synthesizer.

Sync; no asyncio, no Anthropic. Schema/prompt builders + quote-verification +
internal exception types live here for unit-testability without mocks.
"""
from __future__ import annotations

from typing import Any

from jurist.schemas import CitedArticle, CitedCase


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


def build_synthesis_user_message(
    question: str,
    cited_articles: list[CitedArticle],
    cited_cases: list[CitedCase],
) -> str:
    """Render the Dutch user message for the synthesizer call. Includes full
    article bodies and case chunk_text — the quote-verification surface."""
    lines: list[str] = []
    lines.append(f"Vraag: {question}")
    lines.append("")
    lines.append("Relevante wetsartikelen (gebruik uitsluitend deze article_id's):")
    for i, art in enumerate(cited_articles, start=1):
        lines.append(f"[{i}] article_id: {art.article_id}")
        lines.append(f"    bwb_id: {art.bwb_id}")
        lines.append(f"    label: {art.article_label}")
        lines.append(f"    reden (van de KG-retriever): {art.reason}")
        lines.append("    tekst:")
        lines.append(f"    {art.body_text}")
        lines.append("")

    lines.append("Relevante uitspraken (gebruik uitsluitend deze ECLI's):")
    for i, case in enumerate(cited_cases, start=1):
        header = (
            f"[{i}] ecli: {case.ecli} | {case.court} | {case.date} | "
            f"similarity {case.similarity:.2f}"
        )
        lines.append(header)
        lines.append(f"    reden (van de rerank): {case.reason}")
        lines.append("    chunk:")
        lines.append(f"    {case.chunk_text}")
        lines.append("")

    lines.append("Instructies:")
    lines.append("1. Denk kort hardop in het Nederlands over welke bronnen je zult citeren.")
    lines.append(
        "2. Roep daarna `emit_answer` aan. Citeer uitsluitend uit de "
        "meegeleverde brontekst, verbatim (40–500 tekens per quote)."
    )
    lines.append(
        "3. Elk citaat moet letterlijk voorkomen in de bijbehorende brontekst."
    )
    return "\n".join(lines)


__all__ = ["build_synthesis_tool_schema", "build_synthesis_user_message"]
