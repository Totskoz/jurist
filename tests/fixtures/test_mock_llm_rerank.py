"""Self-tests for the rerank mocks."""
from __future__ import annotations

import pytest

from tests.fixtures.mock_llm import MockAnthropicForRerank


@pytest.mark.asyncio
async def test_mock_returns_canned_tool_input() -> None:
    mock = MockAnthropicForRerank(tool_inputs=[
        {"picks": [
            {"ecli": "E1", "reason": "r" * 20},
            {"ecli": "E2", "reason": "r" * 20},
            {"ecli": "E3", "reason": "r" * 20},
        ]},
    ])
    resp = await mock.messages.create(
        model="m", system=[], tools=[], tool_choice={},
        messages=[], max_tokens=100,
    )
    blocks = [b for b in resp.content if b.type == "tool_use"]
    assert len(blocks) == 1
    assert blocks[0].name == "select_cases"
    assert len(blocks[0].input["picks"]) == 3
    assert blocks[0].input["picks"][0]["ecli"] == "E1"


@pytest.mark.asyncio
async def test_mock_raises_queued_exceptions() -> None:
    mock = MockAnthropicForRerank(tool_inputs=[
        RuntimeError("anthropic 503"),
    ])
    with pytest.raises(RuntimeError, match="anthropic 503"):
        await mock.messages.create(model="m", messages=[])


@pytest.mark.asyncio
async def test_mock_exhausted_queue_raises() -> None:
    mock = MockAnthropicForRerank(tool_inputs=[])
    with pytest.raises(RuntimeError, match="queue exhausted"):
        await mock.messages.create(model="m", messages=[])


@pytest.mark.asyncio
async def test_mock_rejects_exception_class_not_instance() -> None:
    """Catches the common typo `RuntimeError` vs `RuntimeError('x')`."""
    mock = MockAnthropicForRerank(tool_inputs=[RuntimeError])  # class, not instance
    with pytest.raises(TypeError, match="class, not an instance"):
        await mock.messages.create(model="m", messages=[])
