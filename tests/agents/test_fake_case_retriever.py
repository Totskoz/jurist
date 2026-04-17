import pytest

from jurist.agents.case_retriever import run
from jurist.fakes import FAKE_CASES
from jurist.schemas import CaseRetrieverIn, CaseRetrieverOut


def _input() -> CaseRetrieverIn:
    return CaseRetrieverIn(sub_questions=["huur 15% verhogen"], statute_context=[])


@pytest.mark.asyncio
async def test_case_retriever_emits_search_started_and_cases():
    types = []
    async for ev in run(_input()):
        types.append(ev.type)
    assert "search_started" in types
    assert types.count("case_found") == len(FAKE_CASES)


@pytest.mark.asyncio
async def test_case_retriever_reranked_event_lists_kept_eclis():
    kept = None
    async for ev in run(_input()):
        if ev.type == "reranked":
            kept = ev.data["kept"]
    assert kept is not None
    assert set(kept).issubset({c.ecli for c in FAKE_CASES})


@pytest.mark.asyncio
async def test_case_retriever_final_payload_validates():
    final = None
    async for ev in run(_input()):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = CaseRetrieverOut.model_validate(final.data)
    assert len(out.cited_cases) == len(FAKE_CASES)
