import pytest

from jurist.agents.synthesizer import run
from jurist.fakes import FAKE_ANSWER, FAKE_CASES
from jurist.schemas import SynthesizerIn, SynthesizerOut


def _input() -> SynthesizerIn:
    return SynthesizerIn(
        question="Mag de huur 15% omhoog?",
        cited_articles=[],
        cited_cases=list(FAKE_CASES),
    )


@pytest.mark.asyncio
async def test_synthesizer_streams_answer_deltas_before_finishing():
    types = []
    async for ev in run(_input()):
        types.append(ev.type)
    delta_count = types.count("answer_delta")
    assert delta_count >= 5
    assert types[-1] == "agent_finished"
    last_delta_idx = max(i for i, t in enumerate(types) if t == "answer_delta")
    assert last_delta_idx < types.index("agent_finished")


@pytest.mark.asyncio
async def test_synthesizer_emits_citation_resolved_events():
    resolved = []
    async for ev in run(_input()):
        if ev.type == "citation_resolved":
            resolved.append(ev.data)
    # One per wetsartikel + one per uitspraak in FAKE_ANSWER.
    expected = len(FAKE_ANSWER.relevante_wetsartikelen) + len(FAKE_ANSWER.vergelijkbare_uitspraken)
    assert len(resolved) == expected
    kinds = {r["kind"] for r in resolved}
    assert kinds == {"artikel", "uitspraak"}


@pytest.mark.asyncio
async def test_synthesizer_final_payload_equals_fake_answer():
    final = None
    async for ev in run(_input()):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = SynthesizerOut.model_validate(final.data)
    assert out.answer == FAKE_ANSWER
