import pytest

from jurist.agents.statute_retriever_tools import ToolExecutor
from jurist.kg.networkx_kg import NetworkXKG
from jurist.llm.client import (
    Coerced,
    Done,
    LoopEvent,
    ToolResultEvent,
    ToolUseStart,
    _history_to_anthropic_messages,
    run_tool_loop,
)
from jurist.schemas import ArticleNode, KGSnapshot
from tests.fixtures.mock_llm import MockAnthropicClient, ScriptedToolUse, ScriptedTurn


def _kg() -> NetworkXKG:
    nodes = [
        ArticleNode(
            article_id="A",
            bwb_id="BWBX",
            label="Art A",
            title="T",
            body_text="body.",
            outgoing_refs=[],
        ),
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    return NetworkXKG.from_snapshot(snap)


@pytest.mark.asyncio
async def test_run_tool_loop_happy_path_terminates_on_done():
    kg = _kg()
    script = [
        ScriptedTurn(
            text_deltas=["Ik lees artikel A."],
            tool_uses=[ScriptedToolUse(name="get_article", args={"article_id": "A"})],
        ),
        ScriptedTurn(
            text_deltas=["Klaar."],
            tool_uses=[ScriptedToolUse(
                name="done",
                args={"selected": [{"article_id": "A", "reason": "relevant"}]},
            )],
        ),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    events: list[LoopEvent] = []
    async for ev in run_tool_loop(
        mock=mock,
        executor=executor,
        system="<sys>",
        tools=[],
        user_message="test",
        max_iters=15,
        wall_clock_cap_s=90.0,
    ):
        events.append(ev)

    # Event order: delta, tool_use_start, tool_result, delta, done
    types = [type(e).__name__ for e in events]
    assert "TextDelta" in types
    assert "ToolUseStart" in types
    assert "ToolResultEvent" in types
    assert types[-1] == "Done"
    final_done = events[-1]
    assert isinstance(final_done, Done)
    assert final_done.selected == [{"article_id": "A", "reason": "relevant"}]


def test_history_translator_preserves_user_strings():
    out = _history_to_anthropic_messages([{"role": "user", "content": "hi"}])
    assert out == [{"role": "user", "content": "hi"}]


def test_history_translator_renders_tool_use_and_result():
    hist = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": {
            "text": "thinking",
            "tool_uses": [{"name": "get_article", "args": {"article_id": "A"}}],
        }},
        {"role": "user", "content": {
            "tool_result": {"body_text": "..."},
            "is_error": False,
        }},
    ]
    out = _history_to_anthropic_messages(hist)
    assert out[0] == {"role": "user", "content": "q"}
    asst = out[1]
    assert asst["role"] == "assistant"
    assert any(b.get("type") == "text" for b in asst["content"])
    assert any(b.get("type") == "tool_use" for b in asst["content"])
    tr = out[2]
    assert tr["role"] == "user"
    assert tr["content"][0]["type"] == "tool_result"


def test_history_translator_binds_parallel_tool_results_to_distinct_ids():
    hist = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": {
            "text": "",
            "tool_uses": [
                {"name": "get_article", "args": {"article_id": "A"}},
                {"name": "get_article", "args": {"article_id": "B"}},
            ],
        }},
        {"role": "user", "content": {
            "tool_result": {"body_text": "A body"},
            "is_error": False,
            "_tu_idx": 0,
        }},
        {"role": "user", "content": {
            "tool_result": {"body_text": "B body"},
            "is_error": False,
            "_tu_idx": 1,
        }},
    ]
    out = _history_to_anthropic_messages(hist)
    # Find the assistant's tool_use ids
    asst_blocks = out[1]["content"]
    tu_ids = [b["id"] for b in asst_blocks if b.get("type") == "tool_use"]
    assert len(tu_ids) == 2
    assert tu_ids[0] != tu_ids[1]
    # Tool results 0 and 1 should reference different ids
    tr0 = out[2]["content"][0]
    tr1 = out[3]["content"][0]
    assert tr0["tool_use_id"] == tu_ids[0]
    assert tr1["tool_use_id"] == tu_ids[1]


@pytest.mark.asyncio
async def test_done_one_retry_then_accept():
    kg = _kg()
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "NOPE", "reason": "x"}]},
        )]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Done)
    assert final.selected == [{"article_id": "A", "reason": "ok"}]


@pytest.mark.asyncio
async def test_done_two_errors_coerces():
    kg = _kg()
    bad = {"selected": [{"article_id": "NOPE", "reason": "x"}]}
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(name="done", args=bad)]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(name="done", args=bad)]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "done_error"


@pytest.mark.asyncio
async def test_max_iter_coerces_with_visited_recency_capped():
    # Build a KG with >8 nodes and a script that visits them all via
    # get_article, then never calls done.
    nodes = [
        ArticleNode(
            article_id=f"N{i}", bwb_id="BWBX", label=f"N{i}",
            title="t", body_text="b", outgoing_refs=[],
        )
        for i in range(10)
    ]
    snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
    big_kg = NetworkXKG.from_snapshot(snap)
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="get_article", args={"article_id": f"N{i}"}
        )])
        for i in range(10)
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(big_kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=10, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "max_iter"
    # Most recent 8 visits, in recency order: N9, N8, ..., N2
    assert len(final.selected) == 8
    assert final.selected[0]["article_id"] == "N9"
    assert final.selected[-1]["article_id"] == "N2"
    for entry in final.selected:
        assert "coerced: max_iter" in entry["reason"]


class _SlowMock:
    """Sleeps on every turn so the wall-clock cap fires quickly."""

    def __init__(self) -> None:
        self.calls = 0

    def next_turn(self, history):
        self.calls += 1
        # Block the event loop briefly by yielding a synchronous turn
        # that does nothing; the loop advances monotonic time via sleeps
        # only when we await, so we inject an await via a sentinel. The
        # wall-clock test instead uses a very short cap.
        return ScriptedTurn(
            text_deltas=["…"],
            tool_uses=[ScriptedToolUse(name="get_article", args={"article_id": "A"})],
        )


@pytest.mark.asyncio
async def test_wall_clock_coerces_on_tight_cap(monkeypatch):
    kg = _kg()
    mock = _SlowMock()
    executor = ToolExecutor(kg)

    # Force monotonic time to jump forward each call.
    import jurist.llm.client as client_mod

    _times = [0.0, 0.0, 0.0, 1000.0]
    _call_count = [0]

    def _fake_monotonic() -> float:
        val = _times[min(_call_count[0], len(_times) - 1)]
        _call_count[0] += 1
        return val

    monkeypatch.setattr(client_mod.time, "monotonic", _fake_monotonic)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=10.0,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "wall_clock"


@pytest.mark.asyncio
async def test_dup_two_consecutive_triggers_advisory():
    kg = _kg()
    call = ScriptedToolUse(name="get_article", args={"article_id": "A"})
    script = [
        ScriptedTurn(tool_uses=[call]),
        ScriptedTurn(tool_uses=[call]),  # duplicate — should advisory
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    events: list[LoopEvent] = []
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        events.append(ev)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    # First get_article succeeds; second is an advisory error; done succeeds.
    assert tool_results[0].result.is_error is False
    assert tool_results[1].result.is_error is True
    assert "already" in tool_results[1].result.result_summary.lower()
    assert isinstance(events[-1], Done)
    # Every ToolResultEvent must have a preceding ToolUseStart with matching (name, args).
    ttypes = [type(e).__name__ for e in events]
    for i, t in enumerate(ttypes):
        if t == "ToolResultEvent":
            prior_tus = [j for j, tt in enumerate(ttypes[:i]) if tt == "ToolUseStart"]
            assert prior_tus, f"ToolResultEvent at index {i} has no preceding ToolUseStart"
            # The immediately preceding ToolUseStart must match name and args.
            tu_ev = events[prior_tus[-1]]
            tr_ev = events[i]
            assert isinstance(tu_ev, ToolUseStart)
            assert isinstance(tr_ev, ToolResultEvent)
            assert tu_ev.name == tr_ev.name
            assert tu_ev.args == tr_ev.args


@pytest.mark.asyncio
async def test_dup_three_consecutive_coerces():
    kg = _kg()
    call = ScriptedToolUse(name="get_article", args={"article_id": "A"})
    script = [
        ScriptedTurn(tool_uses=[call]),
        ScriptedTurn(tool_uses=[call]),
        ScriptedTurn(tool_uses=[call]),
    ]
    mock = MockAnthropicClient(script)
    executor = ToolExecutor(kg)

    final = None
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        final = ev
    assert isinstance(final, Coerced)
    assert final.reason == "dup_loop"


class _BoomExecutor(ToolExecutor):
    async def execute(self, name, args):
        if name == "get_article":
            raise RuntimeError("boom")
        return await super().execute(name, args)


@pytest.mark.asyncio
async def test_executor_exception_becomes_is_error():
    kg = _kg()
    script = [
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="get_article", args={"article_id": "A"}
        )]),
        ScriptedTurn(tool_uses=[ScriptedToolUse(
            name="done",
            args={"selected": [{"article_id": "A", "reason": "ok"}]},
        )]),
    ]
    mock = MockAnthropicClient(script)
    executor = _BoomExecutor(kg)

    events: list[LoopEvent] = []
    async for ev in run_tool_loop(
        mock=mock, executor=executor, system="<sys>", tools=[],
        user_message="q", max_iters=15, wall_clock_cap_s=90,
    ):
        events.append(ev)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    # get_article raised → is_error
    assert tool_results[0].result.is_error is True
    assert "boom" in tool_results[0].result.result_summary.lower()
    # Loop continued to done
    assert isinstance(events[-1], Done)
