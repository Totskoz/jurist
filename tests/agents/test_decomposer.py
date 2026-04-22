"""Unit tests for the M4 decomposer agent."""
from __future__ import annotations

import pytest

from jurist.agents import decomposer
from jurist.agents.decomposer import (
    DecomposerFailedError,  # noqa: F401 — re-export smoke; used by Task 6 tests
)
from jurist.config import RunContext
from jurist.schemas import DecomposerIn, DecomposerOut
from tests.fixtures.mock_llm import MockAnthropicForRerank


def _ctx(tool_inputs):
    """RunContext with a mock .messages.create client. KG/case_store/embedder
    are None-typed; decomposer never touches them."""
    return RunContext(
        kg=None,           # type: ignore[arg-type]
        llm=MockAnthropicForRerank(tool_inputs),
        case_store=None,   # type: ignore[arg-type]
        embedder=None,     # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_decomposer_happy_path():
    ctx = _ctx([
        {
            "sub_questions": ["Is de woning gereguleerd?", "Wat is het maximum?"],
            "concepts": ["huurverhoging", "gereguleerd"],
            "intent": "legality_check",
        }
    ])
    events = []
    async for ev in decomposer.run(DecomposerIn(question="Mag 15%?"), ctx=ctx):
        events.append(ev)

    assert [ev.type for ev in events] == ["agent_started", "agent_finished"]
    out = DecomposerOut.model_validate(events[-1].data)
    assert out.intent == "legality_check"
    assert len(out.sub_questions) == 2
    assert "huurverhoging" in out.concepts
