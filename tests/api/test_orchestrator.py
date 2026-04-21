import tempfile
from pathlib import Path

import numpy as np
import pytest

from jurist.api.orchestrator import run_question
from jurist.api.sse import EventBuffer
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleNode, CaseChunkRow, KGSnapshot
from jurist.vectorstore import CaseStore
from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedToolUse, ScriptedTurn


class _NoOpEmbedder:
    def encode(self, texts, *, batch_size=32):
        return np.zeros((len(texts), 1024), dtype=np.float32)


def _orch_ctx() -> RunContext:
    nodes = [
        ArticleNode(
            article_id="A", bwb_id="BWBX", label="Art A", title="T",
            body_text="b", outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    kg = NetworkXKG.from_snapshot(snap)
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    # One-row CaseStore — satisfies RunContext construction; the autouse
    # conftest stub replaces case_retriever.run so the store is never queried.
    tmp = Path(tempfile.mkdtemp()) / "cases.lance"
    store = CaseStore(tmp)
    store.open_or_create()
    v = np.zeros(1024, dtype=np.float32).tolist()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=v, url="u",
    )])

    return RunContext(
        kg=kg,
        llm=MockAnthropicClient(script),
        case_store=store,
        embedder=_NoOpEmbedder(),
    )


@pytest.mark.asyncio
async def test_orchestrator_emits_run_started_and_run_finished():
    buf = EventBuffer()
    await run_question("Mag de huur 15% omhoog?", run_id="run_test",
                       buffer=buf, ctx=_orch_ctx())
    events = []
    async for ev in buf.subscribe():
        events.append(ev)
    types = [e.type for e in events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"


@pytest.mark.asyncio
async def test_orchestrator_stamps_run_id_and_agent_on_every_event():
    buf = EventBuffer()
    await run_question("q", run_id="run_test", buffer=buf, ctx=_orch_ctx())
    async for ev in buf.subscribe():
        assert ev.run_id == "run_test"
        assert ev.ts != ""
        if ev.type not in {"run_started", "run_finished", "run_failed"}:
            assert ev.agent != ""


@pytest.mark.asyncio
async def test_orchestrator_runs_agents_in_expected_order():
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
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
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
    final = None
    async for ev in buf.subscribe():
        if ev.type == "run_finished":
            final = ev
    assert final is not None
    ans = final.data["final_answer"]
    assert "korte_conclusie" in ans
    assert "aanbeveling" in ans


class _BoomLLM:
    """Raises on first turn — simulates Anthropic 429/5xx."""

    def next_turn(self, history):
        raise RuntimeError("anthropic 503")


@pytest.mark.asyncio
async def test_orchestrator_emits_run_failed_on_llm_error():
    """Per spec §5: uncaught exception in statute_retriever → run_failed."""
    nodes = [ArticleNode(
        article_id="A", bwb_id="BWBX", label="A", title="T",
        body_text="b", outgoing_refs=[],
    )]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    kg = NetworkXKG.from_snapshot(snap)

    tmp = Path(tempfile.mkdtemp()) / "cases.lance"
    store = CaseStore(tmp)
    store.open_or_create()
    v = np.zeros(1024, dtype=np.float32).tolist()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=v, url="u",
    )])

    ctx = RunContext(
        kg=kg, llm=_BoomLLM(), case_store=store, embedder=_NoOpEmbedder(),
    )
    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=ctx)
    events = [ev async for ev in buf.subscribe()]
    final = events[-1]
    assert final.type == "run_failed"
    assert final.data["reason"] == "llm_error"
    assert "anthropic 503" in final.data["detail"]
    assert not any(e.type == "run_finished" for e in events)


@pytest.mark.asyncio
async def test_orchestrator_emits_run_failed_on_rerank_failed(monkeypatch):
    """RerankFailedError from case_retriever → run_failed{case_rerank}."""
    from jurist.agents import case_retriever
    from jurist.agents.case_retriever import RerankFailedError
    from jurist.schemas import TraceEvent

    async def _failing_case_retriever(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RerankFailedError("mock: invalid after retry")

    # Overrides the autouse conftest stub
    monkeypatch.setattr(case_retriever, "run", _failing_case_retriever)

    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
    events = [ev async for ev in buf.subscribe()]
    final = events[-1]
    assert final.type == "run_failed"
    assert final.data["reason"] == "case_rerank"
    assert "invalid after retry" in final.data["detail"]
    assert not any(e.type == "run_finished" for e in events)


@pytest.mark.asyncio
async def test_orchestrator_emits_run_failed_on_generic_case_exception(monkeypatch):
    """Generic Exception from case_retriever → run_failed{llm_error}."""
    from jurist.agents import case_retriever
    from jurist.schemas import TraceEvent

    async def _exploding_case_retriever(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RuntimeError("anthropic 429 rate limited")

    monkeypatch.setattr(case_retriever, "run", _exploding_case_retriever)

    buf = EventBuffer()
    await run_question("q", run_id="r", buffer=buf, ctx=_orch_ctx())
    events = [ev async for ev in buf.subscribe()]
    final = events[-1]
    assert final.type == "run_failed"
    assert final.data["reason"] == "llm_error"
    assert "429" in final.data["detail"]
    assert not any(e.type == "run_finished" for e in events)
