import pytest

from jurist.agents.decomposer import run
from jurist.schemas import DecomposerIn, DecomposerOut


@pytest.mark.asyncio
async def test_decomposer_emits_started_thinking_finished_in_order():
    events = []
    async for ev in run(DecomposerIn(question="Mag de huur 15% omhoog?")):
        events.append(ev)
    types = [e.type for e in events]
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    assert "agent_thinking" in types


@pytest.mark.asyncio
async def test_decomposer_finished_payload_validates_as_decomposer_out():
    final = None
    async for ev in run(DecomposerIn(question="Mag de huur 15% omhoog?")):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = DecomposerOut.model_validate(final.data)
    assert out.intent in {"legality_check", "calculation", "procedure", "other"}
    assert len(out.sub_questions) >= 1
    assert len(out.concepts) >= 1


@pytest.mark.asyncio
async def test_decomposer_thinking_events_carry_text():
    thinking = []
    async for ev in run(DecomposerIn(question="q")):
        if ev.type == "agent_thinking":
            thinking.append(ev)
    assert len(thinking) >= 2
    assert all("text" in ev.data for ev in thinking)
