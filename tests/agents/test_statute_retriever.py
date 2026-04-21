import tempfile
from pathlib import Path

import numpy as np
import pytest

from jurist.agents import statute_retriever
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import (
    ArticleEdge,
    ArticleNode,
    CaseChunkRow,
    KGSnapshot,
    StatuteRetrieverIn,
    StatuteRetrieverOut,
)
from jurist.vectorstore import CaseStore
from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedToolUse, ScriptedTurn


class _NoOpEmbedder:
    def encode(self, texts, *, batch_size=32):
        return np.zeros((len(texts), 1024), dtype=np.float32)


def _minimal_case_store() -> CaseStore:
    tmp = Path(tempfile.mkdtemp()) / "cases.lance"
    store = CaseStore(tmp)
    store.open_or_create()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=np.zeros(1024, dtype=np.float32).tolist(), url="u",
    )])
    return store


@pytest.fixture
def small_kg():
    nodes = [
        ArticleNode(
            article_id="A", bwb_id="BWBX", label="Art A", title="T",
            body_text="a body", outgoing_refs=["B"],
        ),
        ArticleNode(
            article_id="B", bwb_id="BWBX", label="Art B", title="T",
            body_text="b body", outgoing_refs=[],
        ),
    ]
    edges = [ArticleEdge(from_id="A", to_id="B", kind="explicit")]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=edges)
    return NetworkXKG.from_snapshot(snap)


@pytest.mark.asyncio
async def test_agent_emits_event_sequence(small_kg, monkeypatch):
    script = [
        ScriptedTurn(
            text_deltas=["Ik lees artikel A."],
            tool_uses=[ScriptedToolUse(name="get_article", args={"article_id": "A"})],
        ),
        ScriptedTurn(
            text_deltas=["Volg naar B."],
            tool_uses=[ScriptedToolUse(
                name="follow_cross_ref", args={"from_id": "A", "to_id": "B"}
            )],
        ),
        ScriptedTurn(
            tool_uses=[ScriptedToolUse(name="done", args={"selected": [
                {"article_id": "A", "reason": "core"},
                {"article_id": "B", "reason": "procedure"},
            ]})],
        ),
    ]
    mock = MockAnthropicClient(script)
    ctx = RunContext(
        kg=small_kg, llm=mock,
        case_store=_minimal_case_store(), embedder=_NoOpEmbedder(),
    )

    events = []
    async for ev in statute_retriever.run(
        StatuteRetrieverIn(
            sub_questions=["q?"], concepts=["huurverhoging"],
            intent="legality_check",
        ),
        ctx=ctx,
    ):
        events.append(ev)

    types = [e.type for e in events]
    # First and last
    assert types[0] == "agent_started"
    assert types[-1] == "agent_finished"
    # Thinking, tool calls, node visits, edge traversal, done
    assert "agent_thinking" in types
    assert types.count("tool_call_started") >= 3
    assert types.count("tool_call_completed") >= 3
    assert "node_visited" in types
    assert "edge_traversed" in types
    # Output shape
    out = StatuteRetrieverOut.model_validate(events[-1].data)
    assert [c.article_id for c in out.cited_articles] == ["A", "B"]
    assert out.cited_articles[0].reason == "core"


@pytest.mark.asyncio
async def test_agent_node_visited_on_get_article_but_not_on_list_neighbors(small_kg):
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="list_neighbors", args={"article_id": "A"},
        )]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    ctx = RunContext(
        kg=small_kg, llm=mock,
        case_store=_minimal_case_store(), embedder=_NoOpEmbedder(),
    )
    events = []
    async for ev in statute_retriever.run(
        StatuteRetrieverIn(sub_questions=[], concepts=[], intent="other"),
        ctx=ctx,
    ):
        events.append(ev)
    # list_neighbors does NOT trigger node_visited
    assert not any(e.type == "node_visited" for e in events)
    # Hit ids / neighbor ids surface in tool_call_completed.data
    tcc = next(e for e in events if e.type == "tool_call_completed")
    assert "neighbor_ids" in tcc.data
