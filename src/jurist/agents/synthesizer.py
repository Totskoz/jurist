"""M4 real synthesizer: streaming Sonnet + forced tool + closed-set grounding.

M5 adds:
- Early-branch refusal when BOTH retrievers flag low_confidence (AQ8 §6.2).
- Normal-path self-judged refusal via `kind="insufficient_context"`.
- `huurtype_hypothese` passthrough into the user message (AQ1 input).
- Tool schema uses `allow_refusal=True` so the synth may elect refusal.
"""
from __future__ import annotations

import asyncio
import logging
from collections import namedtuple
from collections.abc import AsyncIterator
from typing import Any

from jurist.agents.synthesizer_refusal import should_refuse
from jurist.agents.synthesizer_tools import (
    _format_regen_advisory,
    _validate_attempt,
    build_synthesis_corpus_block,
    build_synthesis_instructions_block,
    build_synthesis_tool_schema,
)
from jurist.config import RunContext, settings
from jurist.llm.prompts import render_synthesizer_system
from jurist.schemas import (
    StructuredAnswer,
    SynthesizerIn,
    SynthesizerOut,
    TraceEvent,
)

logger = logging.getLogger(__name__)

_ARTIKEL_URL = "https://wetten.overheid.nl/{bwb_id}"
_UITSPRAAK_URL = "https://uitspraken.rechtspraak.nl/details?id={ecli}"
_TOKEN_SLEEP_S = 0.02

# Lightweight views so `should_refuse` (which takes StatuteRetrieverOut /
# CaseRetrieverOut) can be driven from SynthesizerIn's flattened flags.
# We don't want to reconstruct the full retriever output objects here.
_StatuteView = namedtuple("_StatuteView", ["low_confidence"])
_CaseView = namedtuple("_CaseView", ["low_confidence"])


class CitationGroundingFailedError(Exception):
    """Citation verification failed on both attempt 1 and the regen. Orchestrator
    wraps this into run_failed { reason: 'citation_grounding', detail: str(exc) }."""


def _tokenize(text: str) -> list[str]:
    """Word-level chunks with trailing spaces; preserves reassembly."""
    words = text.split(" ")
    return [w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]


def _assemble_display_text(answer: StructuredAnswer) -> str:
    return " ".join([
        answer.korte_conclusie,
        *[c.quote + " " + c.explanation for c in answer.relevante_wetsartikelen],
        *[c.quote + " " + c.explanation for c in answer.vergelijkbare_uitspraken],
        answer.aanbeveling,
    ])


def _assemble_refusal_display_text(answer: StructuredAnswer) -> str:
    """Refusal answers have empty citation lists; assemble from conclusie,
    reason, and aanbeveling."""
    parts = [answer.korte_conclusie]
    if answer.insufficient_context_reason:
        parts.append(answer.insufficient_context_reason)
    parts.append(answer.aanbeveling)
    return " ".join(parts)


def _extract_tool_use(final_message: Any, tool_name: str) -> Any | None:
    """Pull the first tool_use block matching `tool_name` from a final message."""
    for block in getattr(final_message, "content", []):
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == tool_name
        ):
            return block
    return None


async def _stream_once(
    client: Any,
    system: str,
    corpus: str,
    instructions: str,
    schema: dict[str, Any],
) -> AsyncIterator[tuple[str, Any]]:
    """Drive one streaming Sonnet call. Yields:
      ("thinking", str) for each pre-tool text delta,
      ("tool", dict) exactly once with the extracted tool_use.input,
        or ("tool", None) if no tool_use block was present.

    The user message is split across two text content blocks: the slow-changing
    corpus (question + article bodies + case chunks) is marked
    `cache_control: ephemeral` so the regen attempt hits cache, while the
    short instructions/advisory block is left uncached."""
    async with client.messages.stream(
        model=settings.model_synthesizer,
        system=[{
            "type": "text", "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[schema],
        tool_choice={"type": "tool", "name": "emit_answer"},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text", "text": corpus,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": instructions},
            ],
        }],
        max_tokens=settings.synthesizer_max_tokens,
    ) as stream:
        async for event in stream:
            if (
                getattr(event, "type", None) == "content_block_delta"
                and getattr(getattr(event, "delta", None), "type", None) == "text_delta"
            ):
                yield ("thinking", event.delta.text)
        final = await stream.get_final_message()

    tool_use = _extract_tool_use(final, "emit_answer")
    yield ("tool", tool_use.input if tool_use is not None else None)


def _build_refusal_schema() -> dict[str, Any]:
    """Refusal-only tool schema: `kind` pinned to the 1-element enum
    `insufficient_context`, citation arrays pinned to empty. Used by the
    early-branch refusal flow (AQ8 §6.2)."""
    return {
        "name": "emit_answer",
        "description": (
            "Geef een beleefde weigering als de huurrecht-corpus de vraag "
            "niet ondersteunt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["insufficient_context"]},
                "korte_conclusie": {
                    "type": "string", "minLength": 40, "maxLength": 2000,
                },
                "relevante_wetsartikelen": {
                    "type": "array", "items": {}, "maxItems": 0,
                },
                "vergelijkbare_uitspraken": {
                    "type": "array", "items": {}, "maxItems": 0,
                },
                "aanbeveling": {
                    "type": "string", "minLength": 40, "maxLength": 2000,
                },
                "insufficient_context_reason": {
                    "type": "string", "minLength": 40, "maxLength": 1000,
                },
            },
            "required": [
                "kind",
                "korte_conclusie",
                "aanbeveling",
                "insufficient_context_reason",
            ],
        },
    }


def _build_refusal_user_message(question: str) -> str:
    return (
        f"Vraag: {question}\n\n"
        "De huurrecht-retrievers gaven te weinig relevante bronnen om deze "
        "vraag te onderbouwen. Roep `emit_answer` aan met "
        "`kind=\"insufficient_context\"` en benoem in "
        "`insufficient_context_reason` wat is gezocht, wat ontbreekt, "
        "en naar welk specialisme (uit {arbeidsrecht, verzekeringsrecht, "
        "burenrecht, consumentenrecht, familierecht, algemeen}) je zou "
        "verwijzen."
    )


def _fallback_refusal_answer() -> StructuredAnswer:
    """Manufactured refusal so the pipeline terminates via run_finished,
    not run_failed, even when the refusal-path LLM call itself produces
    no tool_use block."""
    return StructuredAnswer(
        kind="insufficient_context",
        korte_conclusie=(
            "Deze vraag valt buiten het bereik van dit systeem. "
            "Het huurrecht-corpus bevat geen bronnen die de vraag onderbouwen."
        ),
        relevante_wetsartikelen=[],
        vergelijkbare_uitspraken=[],
        aanbeveling=(
            "Raadpleeg een specialist in een relevanter rechtsgebied "
            "(bijv. arbeidsrecht, verzekeringsrecht of burenrecht)."
        ),
        insufficient_context_reason=(
            "De synthesizer kon geen hulpmiddel-aanroep genereren; "
            "automatische fallback-weigering."
        ),
    )


async def _stream_refusal_answer(
    ctx: RunContext,
    input: SynthesizerIn,
) -> StructuredAnswer:
    """Single Sonnet streaming call with a refusal-only schema.

    Tool schema has `kind` fixed to 'insufficient_context' via a 1-element
    enum. Citation arrays are pinned to empty (maxItems: 0). On tool-use
    absence or pydantic-invalid output, returns a manufactured fallback
    refusal so the pipeline still terminates via run_finished."""
    refusal_schema = _build_refusal_schema()
    user_msg = _build_refusal_user_message(input.question)

    async with ctx.llm.messages.stream(
        model=settings.model_synthesizer,
        system=[{"type": "text", "text": render_synthesizer_system()}],
        tools=[refusal_schema],
        tool_choice={"type": "tool", "name": "emit_answer"},
        messages=[{"role": "user", "content": user_msg}],
        max_tokens=1024,
    ) as stream:
        async for _event in stream:
            # No pre-tool text expected; refusal is short.
            pass
        final = await stream.get_final_message()

    tool_use = _extract_tool_use(final, "emit_answer")
    if tool_use is None:
        logger.warning(
            "synthesizer refusal path: no tool_use block, using fallback",
        )
        return _fallback_refusal_answer()
    try:
        return StructuredAnswer.model_validate(tool_use.input)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError etc.
        logger.warning(
            "synthesizer refusal path: invalid tool_use input (%s), using fallback",
            exc,
        )
        return _fallback_refusal_answer()


async def _emit_refusal_events(
    answer: StructuredAnswer,
) -> AsyncIterator[TraceEvent]:
    """Shared refusal emission: no citation_resolved (empty lists), then
    synthetic answer_delta replay of conclusie + reason + aanbeveling,
    terminated by agent_finished."""
    full_text = _assemble_refusal_display_text(answer)
    for tok in _tokenize(full_text):
        await asyncio.sleep(_TOKEN_SLEEP_S)
        yield TraceEvent(type="answer_delta", data={"text": tok})
    yield TraceEvent(
        type="agent_finished",
        data=SynthesizerOut(answer=answer).model_dump(),
    )


async def run(
    input: SynthesizerIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    # ---- M5 AQ8 — early-branch refusal when both retrievers flag low confidence ----
    if should_refuse(
        _StatuteView(low_confidence=input.statute_low_confidence),
        _CaseView(low_confidence=input.case_low_confidence),
    ):
        logger.info(
            "synthesizer early-branch refusal (stat_low=%s case_low=%s)",
            input.statute_low_confidence, input.case_low_confidence,
        )
        refusal_answer = await _stream_refusal_answer(ctx, input)
        async for ev in _emit_refusal_events(refusal_answer):
            yield ev
        return

    # ---- Normal path ----
    system = render_synthesizer_system()
    huurtype = (
        input.decomposer_out.huurtype_hypothese
        if input.decomposer_out is not None
        else "onbekend"
    )
    corpus = build_synthesis_corpus_block(
        input.question,
        input.cited_articles,
        input.cited_cases,
        huurtype_hypothese=huurtype,
    )
    instructions = build_synthesis_instructions_block()
    schema = build_synthesis_tool_schema(
        [a.article_id for a in input.cited_articles],
        list({a.bwb_id for a in input.cited_articles}),
        [c.ecli for c in input.cited_cases],
        allow_refusal=True,  # M5: synth may self-judge kind='insufficient_context'
    )

    # ---------- Attempt 1 ----------
    tool_input_1: dict[str, Any] | None = None
    async for kind, payload in _stream_once(
        ctx.llm, system, corpus, instructions, schema,
    ):
        if kind == "thinking":
            yield TraceEvent(type="agent_thinking", data={"text": payload})
        else:  # "tool"
            tool_input_1 = payload

    failures_1, schema_ok_1 = _validate_attempt(
        tool_input_1, input.cited_articles, input.cited_cases,
    )

    if failures_1 or not schema_ok_1:
        # Advisory: specific if we have failures; generic otherwise.
        if failures_1:
            advisory = _format_regen_advisory(failures_1)
        else:
            advisory = (
                "Je vorige antwoord miste een geldige `emit_answer`-aanroep of "
                "voldeed niet aan het schema. Roep het hulpmiddel correct aan "
                "met alle verplichte velden."
            )
        logger.warning(
            "synthesizer attempt 1 invalid (schema_ok=%s, failures=%d) — retrying once",
            schema_ok_1, len(failures_1),
        )
        # Corpus stays identical so cache hits; advisory appends to the
        # uncached instructions block.
        instructions_retry = instructions + "\n\n" + advisory

        # ---------- Attempt 2 ----------
        tool_input_2: dict[str, Any] | None = None
        async for kind, payload in _stream_once(
            ctx.llm, system, corpus, instructions_retry, schema,
        ):
            if kind == "thinking":
                yield TraceEvent(type="agent_thinking", data={"text": payload})
            else:
                tool_input_2 = payload

        failures_2, schema_ok_2 = _validate_attempt(
            tool_input_2, input.cited_articles, input.cited_cases,
        )
        if failures_2 or not schema_ok_2:
            raise CitationGroundingFailedError(
                f"citation grounding failed after retry: "
                f"schema_ok={schema_ok_2}, failures={failures_2}"
            )
        tool_input_final = tool_input_2
    else:
        tool_input_final = tool_input_1

    assert tool_input_final is not None
    answer = StructuredAnswer.model_validate(tool_input_final)

    # M5 — normal-path self-judged refusal: no citations to resolve, just
    # replay the refusal text and finish. Uses the same emission helper as
    # the early-branch flow so the UI sees a uniform shape.
    if answer.kind == "insufficient_context":
        logger.info(
            "synthesizer normal-path refusal: kind='insufficient_context'",
        )
        async for ev in _emit_refusal_events(answer):
            yield ev
        return

    for wa in answer.relevante_wetsartikelen:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "artikel",
                "id": wa.bwb_id,
                "resolved_url": _ARTIKEL_URL.format(bwb_id=wa.bwb_id),
                "label": wa.article_label,
                "quote": wa.quote,
                "explanation": wa.explanation,
            },
        )
    for uc in answer.vergelijkbare_uitspraken:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "uitspraak",
                "id": uc.ecli,
                "resolved_url": _UITSPRAAK_URL.format(ecli=uc.ecli),
                "quote": uc.quote,
                "explanation": uc.explanation,
            },
        )

    full_text = _assemble_display_text(answer)
    for tok in _tokenize(full_text):
        await asyncio.sleep(_TOKEN_SLEEP_S)
        yield TraceEvent(type="answer_delta", data={"text": tok})

    yield TraceEvent(
        type="agent_finished",
        data=SynthesizerOut(answer=answer).model_dump(),
    )


__all__ = [
    "CitationGroundingFailedError",
    "run",
]
