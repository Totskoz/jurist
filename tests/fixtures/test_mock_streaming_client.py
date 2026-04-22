"""Smoke tests proving MockStreamingClient behaves like AsyncAnthropic.messages.stream()."""
from __future__ import annotations

import pytest

from tests.fixtures.mock_llm import MockStreamingClient, StreamScript


@pytest.mark.asyncio
async def test_basic_stream_yields_text_deltas_and_final_tool_use():
    script = StreamScript(
        text_deltas=["Hallo ", "wereld"],
        tool_input={"key": "value"},
    )
    client = MockStreamingClient([script])

    text = []
    async with client.messages.stream(model="x") as stream:
        async for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                text.append(event.delta.text)
        final = await stream.get_final_message()

    assert "".join(text) == "Hallo wereld"
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "x"
    # final.content is a list with one tool_use block carrying our canned input.
    tool_blocks = [b for b in final.content if b.type == "tool_use"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0].input == {"key": "value"}


@pytest.mark.asyncio
async def test_stream_raises_queued_exception():
    class _CustomError(RuntimeError):
        pass

    script = StreamScript(text_deltas=[], tool_input=_CustomError("sim failure"))
    client = MockStreamingClient([script])

    with pytest.raises(_CustomError, match="sim failure"):
        async with client.messages.stream(model="x") as stream:
            async for _ in stream:
                pass
            await stream.get_final_message()


@pytest.mark.asyncio
async def test_stream_raises_on_empty_queue():
    client = MockStreamingClient([])
    with pytest.raises(RuntimeError, match="exhausted"):
        async with client.messages.stream(model="x") as stream:
            async for _ in stream:
                pass
