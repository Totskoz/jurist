"""M4 real synthesizer: streaming Sonnet + forced tool + closed-set grounding."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

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

    tool_use = None
    for block in getattr(final, "content", []):
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "emit_answer"
        ):
            tool_use = block
            break
    yield ("tool", tool_use.input if tool_use is not None else None)


async def run(
    input: SynthesizerIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    system = render_synthesizer_system()
    corpus = build_synthesis_corpus_block(
        input.question, input.cited_articles, input.cited_cases,
    )
    instructions = build_synthesis_instructions_block()
    schema = build_synthesis_tool_schema(
        [a.article_id for a in input.cited_articles],
        [a.bwb_id for a in input.cited_articles],
        [c.ecli for c in input.cited_cases],
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

    for wa in answer.relevante_wetsartikelen:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "artikel",
                "id": wa.bwb_id,
                "resolved_url": _ARTIKEL_URL.format(bwb_id=wa.bwb_id),
            },
        )
    for uc in answer.vergelijkbare_uitspraken:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "uitspraak",
                "id": uc.ecli,
                "resolved_url": _UITSPRAAK_URL.format(ecli=uc.ecli),
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
