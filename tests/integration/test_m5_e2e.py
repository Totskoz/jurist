"""M5 — end-to-end against real Anthropic + real KG + real LanceDB.

Gated by RUN_E2E=1. Asserts AQ1 branching and no procedure-stacking on the
locked question.
"""
from __future__ import annotations

import os
import re

import pytest

LOCKED_Q = "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"

_RUN_E2E = os.getenv("RUN_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN_E2E,
    reason="integration test — set RUN_E2E=1 to run (costs Anthropic tokens + ~60-90s)",
)


@pytest.mark.asyncio
async def test_m5_locked_question_has_branching_and_no_stacking():
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")

    from anthropic import AsyncAnthropic

    from jurist.api.orchestrator import run_question
    from jurist.api.sse import EventBuffer
    from jurist.config import RunContext, settings
    from jurist.embedding import Embedder
    from jurist.kg.networkx_kg import NetworkXKG
    from jurist.vectorstore import CaseStore

    if not settings.kg_path.exists():
        pytest.skip(f"KG missing at {settings.kg_path}; run jurist.ingest first")
    if not settings.lance_path.exists():
        pytest.skip(
            f"LanceDB missing at {settings.lance_path}; run jurist.ingest.caselaw first"
        )

    kg = NetworkXKG.load_from_json(settings.kg_path)
    case_store = CaseStore(settings.lance_path)
    case_store.open_or_create()
    if case_store.row_count() == 0:
        pytest.skip("LanceDB is empty")

    embedder = Embedder(model_name=settings.embed_model)
    llm = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    ctx = RunContext(kg=kg, llm=llm, case_store=case_store, embedder=embedder)

    buf = EventBuffer(max_history=10_000)
    await run_question(LOCKED_Q, run_id="run_m5_e2e", buffer=buf, ctx=ctx)

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    # Terminal event must be run_finished, not run_failed.
    assert events[-1].type == "run_finished", (
        f"expected run_finished; got {events[-1].type}: {events[-1].data}"
    )

    final = events[-1].data["final_answer"]
    assert final["kind"] == "answer"

    # Decomposer must classify huurtype as onbekend for the locked question.
    decomp = next(
        e.data for e in events
        if e.type == "agent_finished" and e.agent == "decomposer"
    )
    assert decomp["huurtype_hypothese"] == "onbekend"

    # AQ1: aanbeveling must present >=2 conditional "Als " branches.
    aanbeveling = final["aanbeveling"]
    als_count = len(re.findall(r"\bAls ", aanbeveling))
    assert als_count >= 2, (
        f"expected >=2 'Als' branches, got {als_count}: {aanbeveling!r}"
    )

    # No procedure stacking: 7:248 lid 4 and 7:253 must not both appear.
    assert not (
        "7:248 lid 4" in aanbeveling and "7:253" in aanbeveling
    ), f"procedure stacking detected: {aanbeveling!r}"
