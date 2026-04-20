import pytest

from jurist.agents.statute_retriever_tools import ToolExecutor
from jurist.kg.networkx_kg import NetworkXKG
from jurist.llm.client import (
    Done,
    LoopEvent,
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
