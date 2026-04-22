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
from tests.fixtures.mock_llm import (
    MockAnthropicClient,
    MockAnthropicForRerank,
    MockStreamingClient,
    ScriptedToolUse,
    ScriptedTurn,
    StreamScript,
)


class _NoOpEmbedder:
    def encode(self, texts, *, batch_size=32):
        return np.zeros((len(texts), 1024), dtype=np.float32)


_VALID_SYNTH_INPUT = {
    "kind": "insufficient_context",   # empty lists valid only for refusals (M5)
    "korte_conclusie": "Stub synth conclusie voor orchestrator test " * 2,
    "relevante_wetsartikelen": [],    # empty — test stub uses a tiny KG fixture
    "vergelijkbare_uitspraken": [],
    "aanbeveling": "Stub synth aanbeveling voor orchestrator test " * 2,
    "insufficient_context_reason": "Test stub — geen echte corpus beschikbaar.",
}


class _DualMock:
    """Supports statute_retriever's .next_turn(history) (streaming tool-loop
    mock), decomposer's .messages.create (forced-tool mock), and the M4
    synthesizer's .messages.stream (streaming forced-tool mock).

    Shape-duck-types AsyncAnthropic enough for M2 + M4 agents."""

    def __init__(self, script: list[ScriptedTurn]) -> None:
        self._stream = MockAnthropicClient(script)
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
        # Decomposer uses .messages.create; synthesizer uses .messages.stream.
        # Route by call site.
        outer = self

        class _Router:
            async def create(self, **kwargs):
                return await outer._msg.messages.create(**kwargs)

            def stream(self, **kwargs):
                return outer._synth_stream.messages.stream(**kwargs)

        return _Router()


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
        llm=_DualMock(script),
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
    """Decomposer path succeeds (canned emit_decomposition); statute_retriever
    path raises on first turn to simulate Anthropic 429/5xx. The test asserts
    run_failed{llm_error} bubbles from the statute retriever pump."""

    def __init__(self) -> None:
        self._msg = MockAnthropicForRerank([
            {
                "sub_questions": ["q1"],
                "concepts": ["c1"],
                "intent": "legality_check",
            },
        ])

    def next_turn(self, history):
        raise RuntimeError("anthropic 503")

    @property
    def messages(self):
        return self._msg.messages


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


@pytest.mark.asyncio
async def test_orchestrator_decomposer_failed_surfaces_as_run_failed(monkeypatch):
    """When decomposer.run raises DecomposerFailedError, orchestrator emits
    run_failed{reason:"decomposition", detail}."""
    from jurist.agents import decomposer
    from jurist.agents.decomposer import DecomposerFailedError
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise DecomposerFailedError("two strikes")

    monkeypatch.setattr(decomposer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_t", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    types = [e.type for e in events]
    assert types[-1] == "run_failed"
    assert events[-1].data["reason"] == "decomposition"
    assert "two strikes" in events[-1].data["detail"]


@pytest.mark.asyncio
async def test_orchestrator_decomposer_generic_error_surfaces_as_llm_error(monkeypatch):
    from jurist.agents import decomposer
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RuntimeError("network down")

    monkeypatch.setattr(decomposer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_t2", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "llm_error"
    assert "RuntimeError" in events[-1].data["detail"]


@pytest.mark.asyncio
async def test_orchestrator_synthesizer_grounding_failure_surfaces(monkeypatch):
    """CitationGroundingFailedError → run_failed{reason:"citation_grounding"}."""
    from jurist.agents import synthesizer
    from jurist.agents.synthesizer import CitationGroundingFailedError
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise CitationGroundingFailedError("two strikes")

    monkeypatch.setattr(synthesizer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_sg", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "citation_grounding"
    assert "two strikes" in events[-1].data["detail"]


@pytest.mark.asyncio
async def test_orchestrator_synthesizer_generic_error_is_llm_error(monkeypatch):
    from jurist.agents import synthesizer
    from jurist.schemas import TraceEvent

    async def _boom(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise RuntimeError("network down")

    monkeypatch.setattr(synthesizer, "run", _boom)

    buf = EventBuffer()
    await run_question("q", run_id="run_sg2", buffer=buf, ctx=_orch_ctx())

    events = []
    async for ev in buf.subscribe():
        events.append(ev)

    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "llm_error"


def _make_rate_limit_error(msg: str):
    """Construct a real anthropic.RateLimitError without hitting the network.
    Subclass that bypasses __init__ (which needs an httpx Response) so
    isinstance(exc, RateLimitError) still holds inside the orchestrator."""
    import anthropic

    class _FakeRateLimit(anthropic.RateLimitError):
        def __init__(self, message: str) -> None:
            Exception.__init__(self, message)
            self.message = message
            self.status_code = 429

    return _FakeRateLimit(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent_attr,run_id",
    [
        ("decomposer",        "run_rl_dec"),
        ("case_retriever",    "run_rl_case"),
        ("synthesizer",       "run_rl_synth"),
    ],
)
async def test_orchestrator_rate_limit_error_surfaces_as_rate_limit(
    monkeypatch, agent_attr, run_id,
):
    """anthropic.RateLimitError from any wrapped agent → run_failed{rate_limit}."""
    from jurist.agents import (
        case_retriever as _case,
    )
    from jurist.agents import (
        decomposer as _dec,
    )
    from jurist.agents import (
        synthesizer as _synth,
    )
    from jurist.schemas import TraceEvent

    mod = {
        "decomposer": _dec,
        "case_retriever": _case,
        "synthesizer": _synth,
    }[agent_attr]

    async def _rl(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise _make_rate_limit_error("429 rate_limit_error")

    monkeypatch.setattr(mod, "run", _rl)

    buf = EventBuffer()
    await run_question("q", run_id=run_id, buffer=buf, ctx=_orch_ctx())

    events = [ev async for ev in buf.subscribe()]
    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "rate_limit"
    assert "429" in events[-1].data["detail"]
    assert not any(e.type == "run_finished" for e in events)


@pytest.mark.asyncio
async def test_orchestrator_statute_retriever_rate_limit_surfaces_as_rate_limit(
    monkeypatch,
):
    """Separate from the parametrized test because statute_retriever.run is
    import-shadowed via `from jurist.agents import statute_retriever` at the
    top of orchestrator.py — monkeypatching the module-level run function
    works the same way, just a distinct test for readability."""
    from jurist.agents import statute_retriever
    from jurist.schemas import TraceEvent

    async def _rl(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        raise _make_rate_limit_error("429 rate_limit_error")

    monkeypatch.setattr(statute_retriever, "run", _rl)

    buf = EventBuffer()
    await run_question("q", run_id="run_rl_stat", buffer=buf, ctx=_orch_ctx())

    events = [ev async for ev in buf.subscribe()]
    assert events[-1].type == "run_failed"
    assert events[-1].data["reason"] == "rate_limit"
