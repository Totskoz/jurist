"""Chains the four fake agents + validator stub; stamps events; emits to a buffer."""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from jurist.agents import (
    case_retriever,
    decomposer,
    statute_retriever,
    synthesizer,
    validator_stub,
)
from jurist.api.sse import EventBuffer
from jurist.config import RunContext
from jurist.schemas import (
    CaseRetrieverIn,
    CaseRetrieverOut,
    DecomposerIn,
    DecomposerOut,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
    SynthesizerIn,
    SynthesizerOut,
    TraceEvent,
    ValidatorIn,
    ValidatorOut,
)

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _pump(
    agent_name: str,
    stream: AsyncIterator[TraceEvent],
    run_id: str,
    buffer: EventBuffer,
) -> TraceEvent:
    """Forward every event from `stream` into `buffer`, stamped. Return the final event."""
    final: TraceEvent | None = None
    async for ev in stream:
        ev.agent = agent_name
        ev.run_id = run_id
        ev.ts = _now_iso()
        await buffer.put(ev)
        if ev.type == "agent_finished":
            final = ev
    if final is None:
        raise RuntimeError(f"Agent {agent_name} ended without agent_finished")
    return final


async def run_question(
    question: str,
    run_id: str,
    buffer: EventBuffer,
    ctx: RunContext | None = None,
) -> None:
    """End-to-end run. In M2+ requires a RunContext for the statute retriever."""
    run_started_at = time.monotonic()
    logger.info("run_started id=%s q=%r", run_id, question[:80])
    await buffer.put(
        TraceEvent(
            type="run_started",
            run_id=run_id,
            ts=_now_iso(),
            data={"question": question},
        )
    )

    # 1. Decomposer — fake
    dec_final = await _pump(
        "decomposer",
        decomposer.run(DecomposerIn(question=question)),
        run_id,
        buffer,
    )
    decomposer_out = DecomposerOut.model_validate(dec_final.data)

    # 2. Statute retriever — real in M2
    if ctx is None:
        raise RuntimeError(
            "run_question requires a RunContext in M2+. "
            "The API lifespan must provide one."
        )
    stat_in = StatuteRetrieverIn(
        sub_questions=decomposer_out.sub_questions,
        concepts=decomposer_out.concepts,
        intent=decomposer_out.intent,
    )
    try:
        stat_final = await _pump(
            "statute_retriever",
            statute_retriever.run(stat_in, ctx=ctx),
            run_id,
            buffer,
        )
    except Exception as exc:  # noqa: BLE001 — surface all LLM/network errors
        logger.exception(
            "run_failed id=%s reason=llm_error detail=%s: %s",
            run_id, type(exc).__name__, exc,
        )
        await buffer.put(
            TraceEvent(
                type="run_failed",
                run_id=run_id,
                ts=_now_iso(),
                data={"reason": "llm_error", "detail": f"{type(exc).__name__}: {exc}"},
            )
        )
        return
    stat_out = StatuteRetrieverOut.model_validate(stat_final.data)

    # 3. Case retriever
    case_in = CaseRetrieverIn(
        sub_questions=decomposer_out.sub_questions,
        statute_context=stat_out.cited_articles,
    )
    case_final = await _pump(
        "case_retriever",
        case_retriever.run(case_in),
        run_id,
        buffer,
    )
    case_out = CaseRetrieverOut.model_validate(case_final.data)

    # 4. Synthesizer
    synth_in = SynthesizerIn(
        question=question,
        cited_articles=stat_out.cited_articles,
        cited_cases=case_out.cited_cases,
    )
    synth_final = await _pump(
        "synthesizer",
        synthesizer.run(synth_in),
        run_id,
        buffer,
    )
    synth_out = SynthesizerOut.model_validate(synth_final.data)

    # 5. Validator stub
    val_in = ValidatorIn(
        question=question,
        answer=synth_out.answer,
        cited_articles=stat_out.cited_articles,
        cited_cases=case_out.cited_cases,
    )
    val_final = await _pump(
        "validator",
        validator_stub.run(val_in),
        run_id,
        buffer,
    )
    _ = ValidatorOut.model_validate(val_final.data)

    await buffer.put(
        TraceEvent(
            type="run_finished",
            run_id=run_id,
            ts=_now_iso(),
            data={"final_answer": synth_out.answer.model_dump()},
        )
    )
    logger.info(
        "run_finished id=%s elapsed_s=%.2f cited_articles=%d cited_cases=%d",
        run_id,
        time.monotonic() - run_started_at,
        len(stat_out.cited_articles),
        len(case_out.cited_cases),
    )


__all__ = ["run_question"]
