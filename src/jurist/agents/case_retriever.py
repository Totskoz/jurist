"""M3b real case retriever: bge-m3 + LanceDB + Haiku rerank."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from jurist.agents.case_retriever_tools import (
    CaseCandidate,
    InvalidRerankOutput,
    RerankPick,
    build_rerank_tool_schema,
    build_rerank_user_message,
    retrieve_candidates,
)
from jurist.config import RunContext, settings
from jurist.llm.prompts import render_case_rerank_system
from jurist.schemas import (
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedArticle,
    CitedCase,
    TraceEvent,
)

logger = logging.getLogger(__name__)

_RERANK_MAX_TOKENS = 1500


class RerankFailedError(Exception):
    """Rerank produced invalid output twice. Orchestrator wraps this into
    run_failed { reason: 'case_rerank', detail: str(exc) }."""


async def run(
    input: CaseRetrieverIn,
    *,
    ctx: RunContext,
) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    yield TraceEvent(type="search_started")

    query = "\n".join(input.sub_questions)
    candidates = retrieve_candidates(
        store=ctx.case_store,
        embedder=ctx.embedder,
        query=query,
        chunks_top_k=settings.caselaw_candidate_chunks,
        eclis_limit=settings.caselaw_candidate_eclis,
        snippet_chars=settings.caselaw_rerank_snippet_chars,
    )
    if len(candidates) < 3:
        raise RerankFailedError(
            f"retrieval produced {len(candidates)} candidates (<3); "
            "LanceDB index may be underpopulated or query wildly off-topic"
        )

    for cand in candidates:
        yield TraceEvent(
            type="case_found",
            data={"ecli": cand.ecli, "similarity": cand.similarity},
        )

    picks = await _rerank_with_retry(
        client=ctx.llm,
        candidates=candidates,
        question=input.question,
        sub_questions=input.sub_questions,
        statute_context=input.statute_context,
    )

    yield TraceEvent(
        type="reranked",
        data={"kept": [p.ecli for p in picks]},
    )

    by_ecli = {c.ecli: c for c in candidates}
    cited = [
        CitedCase(
            ecli=p.ecli,
            court=by_ecli[p.ecli].court,
            date=by_ecli[p.ecli].date,
            snippet=by_ecli[p.ecli].snippet,
            similarity=by_ecli[p.ecli].similarity,
            reason=p.reason,
            chunk_text=by_ecli[p.ecli].chunk_text,
            url=by_ecli[p.ecli].url,
        )
        for p in picks
    ]
    floor = settings.case_similarity_floor
    low_confidence = (
        len(cited) >= 3
        and all(c.similarity < floor for c in cited)
    )
    yield TraceEvent(
        type="agent_finished",
        data=CaseRetrieverOut(cited_cases=cited, low_confidence=low_confidence).model_dump(),
    )


async def _rerank_with_retry(
    *,
    client: Any,
    candidates: list[CaseCandidate],
    question: str,
    sub_questions: list[str],
    statute_context: list[CitedArticle],
) -> list[RerankPick]:
    system = render_case_rerank_system()
    user = build_rerank_user_message(
        question=question,
        sub_questions=sub_questions,
        statute_context=statute_context,
        candidates=candidates,
    )
    candidate_eclis = [c.ecli for c in candidates]
    schema = build_rerank_tool_schema(candidate_eclis)

    try:
        return await _rerank_once(client, system, user, schema, candidate_eclis)
    except InvalidRerankOutput as first_err:
        logger.info("rerank attempt 1 invalid: %s — retrying once", first_err)
        user_retry = (
            user + "\n\n"
            f"Je vorige antwoord was ongeldig ({first_err}). "
            "Kies exact 3 verschillende ECLI's uit de lijst en geef voor "
            "elk een korte Nederlandse reden (minimaal 20 tekens)."
        )
        try:
            return await _rerank_once(client, system, user_retry, schema, candidate_eclis)
        except InvalidRerankOutput as second_err:
            raise RerankFailedError(
                f"case rerank invalid after retry: {second_err}"
            ) from second_err


async def _rerank_once(
    client: Any,
    system: str,
    user: str,
    schema: dict,
    candidate_eclis: list[str],
) -> list[RerankPick]:
    response = await client.messages.create(
        model=settings.model_rerank,
        system=[{
            "type": "text", "text": system,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[schema],
        tool_choice={"type": "tool", "name": "select_cases"},
        messages=[{"role": "user", "content": user}],
        max_tokens=_RERANK_MAX_TOKENS,
    )
    tool_use = _extract_tool_use(response, "select_cases")
    picks_raw = tool_use.input.get("picks")
    _validate_picks(picks_raw, candidate_eclis)
    return [RerankPick(ecli=p["ecli"], reason=p["reason"].strip()) for p in picks_raw]


def _extract_tool_use(response: Any, expected_name: str):
    for block in getattr(response, "content", []):
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == expected_name
        ):
            return block
    raise InvalidRerankOutput(
        f"no tool_use block named {expected_name!r} in response"
    )


def _validate_picks(picks: Any, candidate_eclis: list[str]) -> None:
    if not isinstance(picks, list) or len(picks) != 3:
        raise InvalidRerankOutput(
            f"picks must be a list of exactly 3 items, got {type(picks).__name__} "
            f"len={len(picks) if hasattr(picks, '__len__') else 'n/a'}"
        )
    enum_set = set(candidate_eclis)
    seen: set[str] = set()
    for i, p in enumerate(picks):
        if not isinstance(p, dict):
            raise InvalidRerankOutput(f"pick {i} not a dict")
        ecli = p.get("ecli")
        reason = p.get("reason", "")
        if ecli not in enum_set:
            raise InvalidRerankOutput(
                f"pick {i} ecli {ecli!r} not in candidate set"
            )
        if ecli in seen:
            raise InvalidRerankOutput(f"duplicate ecli {ecli!r}")
        seen.add(ecli)
        if not isinstance(reason, str) or len(reason.strip()) < 20:
            raise InvalidRerankOutput(
                f"pick {i} reason must be a string of ≥20 chars (post-strip)"
            )


__all__ = ["run", "RerankFailedError"]
