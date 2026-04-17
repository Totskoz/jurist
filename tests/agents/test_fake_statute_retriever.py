import pytest

from jurist.agents.statute_retriever import run
from jurist.fakes import FAKE_VISIT_PATH
from jurist.schemas import StatuteRetrieverIn, StatuteRetrieverOut


def _input() -> StatuteRetrieverIn:
    return StatuteRetrieverIn(
        sub_questions=["Wat is het max %?"],
        concepts=["huurverhoging"],
        intent="legality_check",
    )


@pytest.mark.asyncio
async def test_statute_retriever_emits_node_visited_for_each_step_of_path():
    visited = []
    async for ev in run(_input()):
        if ev.type == "node_visited":
            visited.append(ev.data["article_id"])
    assert visited == FAKE_VISIT_PATH


@pytest.mark.asyncio
async def test_statute_retriever_emits_edges_between_consecutive_visits():
    edges = []
    async for ev in run(_input()):
        if ev.type == "edge_traversed":
            edges.append((ev.data["from_id"], ev.data["to_id"]))
    # At least len(path)-1 edges between successive visits.
    assert len(edges) >= len(FAKE_VISIT_PATH) - 1


@pytest.mark.asyncio
async def test_statute_retriever_tool_call_events_wrap_visits():
    tool_starts = tool_completes = 0
    async for ev in run(_input()):
        if ev.type == "tool_call_started":
            tool_starts += 1
        if ev.type == "tool_call_completed":
            tool_completes += 1
    assert tool_starts > 0
    assert tool_starts == tool_completes


@pytest.mark.asyncio
async def test_statute_retriever_final_payload_validates():
    final = None
    async for ev in run(_input()):
        if ev.type == "agent_finished":
            final = ev
    assert final is not None
    out = StatuteRetrieverOut.model_validate(final.data)
    assert len(out.cited_articles) >= 2
    ids = [a.article_id for a in out.cited_articles]
    assert all(aid in FAKE_VISIT_PATH for aid in ids)
