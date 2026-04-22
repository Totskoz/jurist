"""End-to-end test for the full M4 chain on the locked question.

Requires:
- RUN_E2E=1 environment variable.
- ANTHROPIC_API_KEY set.
- data/kg/huurrecht.json present (M1 ingest).
- data/lancedb/cases.lance present and non-empty (M3a ingest).
"""
from __future__ import annotations

import os

import pytest

from jurist.agents.synthesizer_tools import _normalize

LOCKED_Q = "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"

_RUN_E2E = os.getenv("RUN_E2E") == "1"

pytestmark = pytest.mark.skipif(
    not _RUN_E2E,
    reason="integration test — set RUN_E2E=1 to run (costs Anthropic tokens + ~60-90s)",
)


@pytest.mark.asyncio
async def test_m4_full_chain_on_locked_question():
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

    buf = EventBuffer()
    await run_question(LOCKED_Q, run_id="run_m4_e2e", buffer=buf, ctx=ctx)

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    # Terminal event is run_finished, not run_failed.
    assert events[-1].type == "run_finished", (
        f"expected run_finished; got {events[-1].type}: {events[-1].data}"
    )

    final = events[-1].data["final_answer"]
    assert len(final["relevante_wetsartikelen"]) >= 1
    assert len(final["vergelijkbare_uitspraken"]) >= 1
    assert len(final["korte_conclusie"]) >= 40
    assert len(final["aanbeveling"]) >= 40

    # Gather citation_resolved events (one per wetsartikel + uitspraak).
    resolved = [ev for ev in events if ev.type == "citation_resolved"]
    assert len(resolved) == (
        len(final["relevante_wetsartikelen"]) + len(final["vergelijkbare_uitspraken"])
    )

    # Grounding: every quote is normalized-substring of the corresponding source.
    # Build lookup from the synth input via the case_retriever's cited_cases event.
    case_finished = next(
        ev for ev in events
        if ev.type == "agent_finished" and ev.agent == "case_retriever"
    )
    stat_finished = next(
        ev for ev in events
        if ev.type == "agent_finished" and ev.agent == "statute_retriever"
    )
    by_article = {a["article_id"]: a for a in stat_finished.data["cited_articles"]}
    by_case = {c["ecli"]: c for c in case_finished.data["cited_cases"]}

    for wa in final["relevante_wetsartikelen"]:
        art = by_article[wa["article_id"]]
        assert _normalize(wa["quote"]) in _normalize(art["body_text"]), (
            f"quote not in article body: {wa['quote'][:80]!r}"
        )
    for uc in final["vergelijkbare_uitspraken"]:
        case = by_case[uc["ecli"]]
        assert _normalize(uc["quote"]) in _normalize(case["chunk_text"]), (
            f"quote not in case chunk: {uc['quote'][:80]!r}"
        )
