"""M0 fake case retriever — yields the three hardcoded FAKE_CASES."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from jurist.fakes import FAKE_CASES
from jurist.schemas import CaseRetrieverIn, CaseRetrieverOut, TraceEvent


async def run(input: CaseRetrieverIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    yield TraceEvent(type="search_started")

    for case in FAKE_CASES:
        await asyncio.sleep(0.3)
        yield TraceEvent(
            type="case_found",
            data={"ecli": case.ecli, "similarity": case.similarity},
        )

    yield TraceEvent(
        type="reranked",
        data={"kept": [c.ecli for c in FAKE_CASES]},
    )

    out = CaseRetrieverOut(cited_cases=list(FAKE_CASES))
    yield TraceEvent(type="agent_finished", data=out.model_dump())
