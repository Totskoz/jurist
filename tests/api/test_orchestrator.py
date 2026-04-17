import pytest

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer


@pytest.mark.asyncio
async def test_orchestrator_emits_run_started_and_run_finished():
    buf = EventBuffer()
    await run_question("Mag de huur 15% omhoog?", run_id="run_test", buffer=buf)

    # Consume the whole buffer history.
    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    types = [e.type for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"


@pytest.mark.asyncio
async def test_orchestrator_stamps_run_id_and_agent_on_every_event():
    buf = EventBuffer()
    await run_question("q", run_id="run_test", buffer=buf)
    async for ev in buf.subscribe():
        assert ev.run_id == "run_test"
        assert ev.ts != ""
        if ev.type not in {"run_started", "run_finished", "run_failed"}:
            assert ev.agent != ""


@pytest.mark.asyncio
async def test_orchestrator_runs_agents_in_expected_order():
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf)
    agent_order = []
    async for ev in buf.subscribe():
        if ev.type == "agent_started":
            agent_order.append(ev.agent)
    assert agent_order == [
        "decomposer",
        "statute_retriever",
        "case_retriever",
        "synthesizer",
        "validator",
    ]


@pytest.mark.asyncio
async def test_orchestrator_run_finished_carries_final_answer():
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf)
    final = None
    async for ev in buf.subscribe():
        if ev.type == "run_finished":
            final = ev
    assert final is not None
    ans = final.data["final_answer"]
    assert "korte_conclusie" in ans
    assert "aanbeveling" in ans
