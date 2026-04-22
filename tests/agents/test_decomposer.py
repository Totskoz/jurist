"""Unit tests for the M4 decomposer agent."""
from __future__ import annotations

from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_decomposer_regens_on_missing_tool_use():
    """First response has no tool_use block → regen → second response valid."""
    import jurist.agents.decomposer as dec_mod

    # Bypass MockMessagesClient (which wraps everything as select_cases).
    # Build a direct client with two canned responses.
    class _TwoShotClient:
        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            async def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                self._outer._n += 1
                if self._outer._n == 1:
                    # No tool_use block — only a text block.
                    return SimpleNamespace(content=[
                        SimpleNamespace(type="text", text="oh no"),
                    ])
                # Valid tool_use on retry.
                return SimpleNamespace(content=[
                    SimpleNamespace(
                        type="tool_use",
                        name="emit_decomposition",
                        input={
                            "sub_questions": ["q1"],
                            "concepts": ["c1"],
                            "intent": "procedure",
                        },
                    ),
                ])

        def __init__(self):
            self.calls: list[dict] = []
            self._n = 0
            self.messages = _TwoShotClient._Messages(self)

    mock = _TwoShotClient()
    ctx = RunContext(kg=None, llm=mock, case_store=None, embedder=None)  # type: ignore[arg-type]

    events = []
    async for ev in dec_mod.run(DecomposerIn(question="q"), ctx=ctx):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(mock.calls) == 2
    # Advisory appears in the retry's user message.
    retry_user = mock.calls[1]["messages"][0]["content"]
    assert "ongeldig" in retry_user
    assert "emit_decomposition" in retry_user


@pytest.mark.asyncio
async def test_decomposer_hard_fails_after_two_invalids():
    """Two consecutive missing-tool responses → DecomposerFailedError."""
    import jurist.agents.decomposer as dec_mod

    class _AlwaysBadClient:
        class _Messages:
            def __init__(self, outer):
                self._outer = outer
                self._outer.calls = []

            async def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                return SimpleNamespace(content=[
                    SimpleNamespace(type="text", text="no tool use here"),
                ])

        def __init__(self):
            self.messages = _AlwaysBadClient._Messages(self)

    mock = _AlwaysBadClient()
    ctx = RunContext(kg=None, llm=mock, case_store=None, embedder=None)  # type: ignore[arg-type]

    with pytest.raises(DecomposerFailedError):
        async for _ in dec_mod.run(DecomposerIn(question="q"), ctx=ctx):
            pass
    assert len(mock.calls) == 2


@pytest.mark.asyncio
async def test_decomposer_regens_on_bad_intent():
    """tool_use.input has intent='foo' (not in enum). Pydantic validation fails
    → regen → second response has valid intent."""
    import jurist.agents.decomposer as dec_mod

    class _Client:
        def __init__(self):
            self.calls: list[dict] = []
            self._n = 0
            self.messages = _Client._Messages(self)

        class _Messages:
            def __init__(self, outer):
                self._outer = outer

            async def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                self._outer._n += 1
                if self._outer._n == 1:
                    bad_input = {
                        "sub_questions": ["q1"],
                        "concepts": ["c1"],
                        "intent": "foo",         # not in enum
                    }
                    return SimpleNamespace(content=[
                        SimpleNamespace(
                            type="tool_use", name="emit_decomposition",
                            input=bad_input,
                        ),
                    ])
                return SimpleNamespace(content=[
                    SimpleNamespace(
                        type="tool_use", name="emit_decomposition",
                        input={
                            "sub_questions": ["q1"],
                            "concepts": ["c1"],
                            "intent": "calculation",
                        },
                    ),
                ])

    mock = _Client()
    ctx = RunContext(kg=None, llm=mock, case_store=None, embedder=None)  # type: ignore[arg-type]
    events = []
    async for ev in dec_mod.run(DecomposerIn(question="q"), ctx=ctx):
        events.append(ev)

    assert events[-1].type == "agent_finished"
    assert len(mock.calls) == 2
