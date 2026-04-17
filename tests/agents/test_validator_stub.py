import pytest

from jurist.agents.validator_stub import run
from jurist.fakes import FAKE_ANSWER, FAKE_CASES
from jurist.schemas import ValidatorIn, ValidatorOut


@pytest.mark.asyncio
async def test_validator_stub_always_valid():
    inp = ValidatorIn(
        question="q",
        answer=FAKE_ANSWER,
        cited_articles=[],
        cited_cases=list(FAKE_CASES),
    )
    events = []
    async for ev in run(inp):
        events.append(ev)
    assert events[0].type == "agent_started"
    assert events[-1].type == "agent_finished"
    out = ValidatorOut.model_validate(events[-1].data)
    assert out.valid is True
    assert out.issues == []
