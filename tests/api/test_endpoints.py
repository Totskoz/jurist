import json

import pytest
from httpx import ASGITransport, AsyncClient

from jurist.api.app import app
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleNode, KGSnapshot
from tests.fixtures.mock_llm import (
    MockAnthropicClient,
    MockAnthropicForRerank,
    MockStreamingClient,
    ScriptedToolUse,
    ScriptedTurn,
    StreamScript,
)


def _minimal_kg():
    nodes = [
        ArticleNode(
            article_id="A", bwb_id="BWBX", label="Art A", title="T",
            body_text="body", outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    return NetworkXKG.from_snapshot(snap)


_VALID_SYNTH_INPUT = {
    "kind": "insufficient_context",   # empty lists valid only for refusals (M5)
    "korte_conclusie": "Stub synth conclusie voor endpoints test " * 2,
    "relevante_wetsartikelen": [],
    "vergelijkbare_uitspraken": [],
    "aanbeveling": "Stub synth aanbeveling voor endpoints test " * 2,
    "insufficient_context_reason": "Test stub — geen echte corpus beschikbaar.",
}


class _EndpointsMock:
    """Endpoints-test dual mock: statute_retriever tool-loop + decomposer
    messages.create + synthesizer messages.stream."""

    def __init__(self) -> None:
        self._stream = MockAnthropicClient([
            ScriptedTurn(tool_uses=[ScriptedToolUse(
                name="done",
                args={"selected": [{"article_id": "A", "reason": "ok"}]},
            )]),
        ])
        self._msg = MockAnthropicForRerank([
            {
                "sub_questions": ["q1"],
                "concepts": ["c1"],
                "intent": "legality_check",
            },
        ])
        self._synth_stream = MockStreamingClient([
            StreamScript(text_deltas=["stub."], tool_input=_VALID_SYNTH_INPUT),
        ])

    def next_turn(self, history):
        return self._stream.next_turn(history)

    @property
    def messages(self):
        outer = self

        class _Router:
            async def create(self, **kwargs):
                return await outer._msg.messages.create(**kwargs)

            def stream(self, **kwargs):
                return outer._synth_stream.messages.stream(**kwargs)

        return _Router()


def _mock_llm():
    return _EndpointsMock()


@pytest.fixture(autouse=True)
def _patch_app_state(tmp_path):
    """Populate app.state so the /api/ask endpoint can build a RunContext
    without the lifespan running."""
    import numpy as np

    from jurist.schemas import CaseChunkRow
    from jurist.vectorstore import CaseStore

    app.state.kg = _minimal_kg()
    app.state.anthropic = _mock_llm()

    # Minimal case_store + embedder — the case_retriever is stubbed for these
    # tests by tests/api/conftest.py, so nothing queries them.
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=np.zeros(1024, dtype=np.float32).tolist(), url="u",
    )])
    app.state.case_store = store

    class _NoOpEmbedder:
        def encode(self, texts, *, batch_size=32):
            return np.zeros((len(texts), 1024), dtype=np.float32)

    app.state.embedder = _NoOpEmbedder()

    yield
    # Cleanup after each test to avoid cross-test contamination.
    del app.state.kg
    del app.state.anthropic
    del app.state.case_store
    del app.state.embedder


@pytest.mark.asyncio
async def test_post_ask_returns_question_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"question": "q?"})
        assert resp.status_code == 200
        body = resp.json()
        assert "question_id" in body
        assert body["question_id"].startswith("run_")


@pytest.mark.asyncio
async def test_stream_yields_run_started_through_run_finished():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"question": "q?"})
        qid = resp.json()["question_id"]

        events: list[dict] = []
        async with client.stream("GET", f"/api/stream?question_id={qid}") as s:
            assert s.status_code == 200
            async for line in s.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[len("data: "):])
                events.append(payload)
                if payload["type"] in {"run_finished", "run_failed"}:
                    break

    types = [e["type"] for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert "answer_delta" in types


@pytest.mark.asyncio
async def test_stream_returns_404_for_unknown_question_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/stream?question_id=run_does_not_exist")
        assert resp.status_code == 404
