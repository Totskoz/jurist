"""Real-Anthropic integration test for the M2 statute retriever.

Gated on RUN_E2E=1 to avoid burning tokens in normal test runs.
"""
from __future__ import annotations

import os

import pytest
from anthropic import AsyncAnthropic

from jurist.agents import statute_retriever
from jurist.agents.decomposer import run as decomposer_run
from jurist.config import RunContext, settings
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import (
    DecomposerIn,
    DecomposerOut,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
)

LOCKED_QUESTION = "Mijn verhuurder wil de huur met 15% verhogen per volgend jaar, mag dat?"
A248_SUFFIX = "Artikel248"  # art. 7:248 BW


@pytest.mark.skipif(
    os.environ.get("RUN_E2E") != "1",
    reason="gated on RUN_E2E=1 (real Anthropic call)",
)
@pytest.mark.asyncio
async def test_m2_retriever_finds_7_248_on_locked_question():
    # Load real KG (M1 output).
    kg = NetworkXKG.load_from_json(settings.kg_path)
    assert len(kg.all_nodes()) >= 200, "Expected the full M1 KG"

    # Real Anthropic client.
    client = AsyncAnthropic()  # picks ANTHROPIC_API_KEY from env

    # Drive the fake decomposer to get realistic canned input.
    dec_events = []
    async for ev in decomposer_run(DecomposerIn(question=LOCKED_QUESTION)):
        dec_events.append(ev)
    dec_out = DecomposerOut.model_validate(dec_events[-1].data)

    ctx = RunContext(kg=kg, llm=client)
    stat_in = StatuteRetrieverIn(
        sub_questions=dec_out.sub_questions,
        concepts=dec_out.concepts,
        intent=dec_out.intent,
    )

    events = []
    async for ev in statute_retriever.run(stat_in, ctx=ctx):
        events.append(ev)

    # Final output shape.
    out = StatuteRetrieverOut.model_validate(events[-1].data)
    assert len(out.cited_articles) >= 1, "retriever returned empty cited_articles"

    # Acceptance: 7:248 is cited.
    cited_ids = [c.article_id for c in out.cited_articles]
    assert any(A248_SUFFIX in aid for aid in cited_ids), (
        f"expected art. 7:248 BW in cited_articles; got {cited_ids}"
    )

    # Not coerced.
    coerced_events = [
        e for e in events
        if e.type == "tool_call_started"
        and e.data.get("tool") == "done"
        and e.data.get("args", {}).get("coerced") is True
    ]
    assert not coerced_events, "retriever terminated via coercion, not a clean done"

    # Visit path length >= 3 nodes.
    node_visits = [e for e in events if e.type == "node_visited"]
    unique_visits = {e.data["article_id"] for e in node_visits}
    assert len(unique_visits) >= 3, \
        f"expected visit path >= 3 nodes; got {len(unique_visits)}"

    # Zero is_error tool results.
    err_tcc = [e for e in events if e.type == "tool_call_completed"
               and e.data.get("is_error") is True]
    assert not err_tcc, f"unexpected tool errors: {[e.data for e in err_tcc]}"
