"""Pure synchronous helpers for the M4 synthesizer.

Sync; no asyncio, no Anthropic. Schema/prompt builders + quote-verification +
internal exception types live here for unit-testability without mocks.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from jurist.schemas import CitedArticle, CitedCase, StructuredAnswer


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


@dataclass(frozen=True)
class FailedCitation:
    kind: Literal["wetsartikel", "uitspraak"]
    id: str
    quote: str
    reason: Literal["not_in_source", "too_short", "too_long", "unknown_id"]


def _normalize(s: str) -> str:
    """NFC-normalize + collapse whitespace runs to single spaces + strip."""
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def verify_citations(
    answer: StructuredAnswer,
    cited_articles: list[CitedArticle],
    cited_cases: list[CitedCase],
    *,
    min_quote_chars: int = 40,
    max_quote_chars: int = 500,
) -> list[FailedCitation]:
    """Return per-citation failures; empty list on success.

    Three checks per citation (in order, cheapest first):
      1. ID in candidate set → `unknown_id` if not.
      2. Length bounds → `too_short` / `too_long`.
      3. Normalized substring match → `not_in_source` if quote isn't in the
         body/chunk after NFC + whitespace collapse.
    """
    failures: list[FailedCitation] = []
    by_article = {a.article_id: a for a in cited_articles}
    by_case = {c.ecli: c for c in cited_cases}

    for wa in answer.relevante_wetsartikelen:
        article = by_article.get(wa.article_id)
        if article is None:
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "unknown_id"))
            continue
        if len(wa.quote) < min_quote_chars:
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "too_short"))
            continue
        if len(wa.quote) > max_quote_chars:
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "too_long"))
            continue
        if _normalize(wa.quote) not in _normalize(article.body_text):
            failures.append(FailedCitation(
                "wetsartikel", wa.article_id, wa.quote, "not_in_source"))

    for uc in answer.vergelijkbare_uitspraken:
        case = by_case.get(uc.ecli)
        if case is None:
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "unknown_id"))
            continue
        if len(uc.quote) < min_quote_chars:
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "too_short"))
            continue
        if len(uc.quote) > max_quote_chars:
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "too_long"))
            continue
        if _normalize(uc.quote) not in _normalize(case.chunk_text):
            failures.append(FailedCitation(
                "uitspraak", uc.ecli, uc.quote, "not_in_source"))

    return failures


def _format_regen_advisory(failures: list[FailedCitation]) -> str:
    """Render a Dutch advisory listing every failing citation. Appended to the
    user message on the regen attempt."""
    lines = [
        "Je vorige antwoord bevatte ongeldige citaten. De volgende `quote`-"
        "velden pasten niet bij de meegeleverde brontekst:",
    ]
    for f in failures:
        short = (f.quote[:80] + "…") if len(f.quote) > 80 else f.quote
        lines.append(f"- [{f.kind} {f.id}] ({f.reason}): {short!r}")
    lines.append("")
    lines.append(
        "Kies uitsluitend verbatim passages uit de meegeleverde brontekst. "
        "Lengte per quote tussen 40 en 500 tekens. Roep `emit_answer` opnieuw aan."
    )
    return "\n".join(lines)


def _validate_attempt(
    tool_input: dict[str, Any] | None,
    cited_articles: list[CitedArticle],
    cited_cases: list[CitedCase],
) -> tuple[list[FailedCitation], bool]:
    """Schema-check + post-hoc verify. Returns (failures, schema_ok).

    - tool_input is None (no tool_use block) → ([], False).
    - Pydantic StructuredAnswer.model_validate fails → ([], False).
    - Otherwise → (verify_citations(...), True).
    """
    if tool_input is None:
        return [], False
    try:
        answer = StructuredAnswer.model_validate(tool_input)
    except ValidationError:
        return [], False
    return verify_citations(answer, cited_articles, cited_cases), True


__all__ = [
    "FailedCitation",
    "_format_regen_advisory",
    "_normalize",
    "_validate_attempt",
    "build_synthesis_tool_schema",
    "build_synthesis_user_message",
    "verify_citations",
]
