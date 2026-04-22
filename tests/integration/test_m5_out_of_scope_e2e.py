"""M5 — out-of-scope question returns structured refusal via run_finished."""
from __future__ import annotations

import os

import pytest

_RUN_E2E = os.getenv("RUN_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN_E2E,
    reason="integration test — set RUN_E2E=1 to run (costs Anthropic tokens + ~60-90s)",
)


@pytest.mark.asyncio
async def test_out_of_scope_burenrecht_refusal():
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

    question = "Ik heb een conflict met mijn buurman over geluidsoverlast, wat zijn mijn opties?"
    buf = EventBuffer(max_history=10_000)
    await run_question(question, run_id="run_m5_out_of_scope_e2e", buffer=buf, ctx=ctx)

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    # Terminal must be run_finished, not run_failed
    assert events[-1].type == "run_finished", (
        f"expected run_finished; got {events[-1].type}: {events[-1].data}"
    )

    answer = events[-1].data["final_answer"]
    assert answer["kind"] == "insufficient_context"
    assert answer["relevante_wetsartikelen"] == []
    assert answer["vergelijkbare_uitspraken"] == []

    reason = answer["insufficient_context_reason"]
    assert "huurrecht" in reason.lower()

    # The aanbeveling should suggest burenrecht
    assert "burenrecht" in answer["aanbeveling"].lower()
