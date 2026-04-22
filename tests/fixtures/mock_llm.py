"""Scripted mock for Anthropic tool-use turns.

Re-exports ModelTurn/ModelToolUse as ScriptedTurn/ScriptedToolUse for
readability in tests. A script is a list of ScriptedTurn. Each turn
models one assistant reply. When the script is exhausted, the mock
returns an empty turn so the loop under test coerces on its own."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from jurist.llm.turn import ModelToolUse as ScriptedToolUse
from jurist.llm.turn import ModelTurn as ScriptedTurn


class MockAnthropicClient:
    """Replays scripted turns. The loop driver calls `next_turn(history)`
    and receives a `ScriptedTurn`. `history` is the full message list
    the real Anthropic client would have received."""

    def __init__(self, script: list[ScriptedTurn]) -> None:
        self._script = list(script)
        self.history_snapshots: list[list[dict[str, Any]]] = []

    def next_turn(self, history: list[dict[str, Any]]) -> ScriptedTurn:
        self.history_snapshots.append([dict(m) for m in history])
        if not self._script:
            return ScriptedTurn()
        return self._script.pop(0)


class MockMessagesClient:
    """Mocks `AsyncAnthropic.messages.create` for forced-tool, non-streaming
    calls (M3b case rerank). Returns a canned tool_use response from a queue.

    A queued Exception is raised instead of returning — for simulating 5xx/network.
    An empty queue raises RuntimeError to surface test-setup mistakes."""

    def __init__(self, tool_inputs: list) -> None:
        # Each entry is either a `dict` (canned tool input) or an `Exception`.
        self._queue = list(tool_inputs)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self._queue:
            raise RuntimeError("MockMessagesClient: tool_inputs queue exhausted")
        item = self._queue.pop(0)
        if isinstance(item, type) and issubclass(item, BaseException):
            raise TypeError(
                f"MockMessagesClient: queue item {item!r} is an exception "
                "class, not an instance — did you forget the parentheses?"
            )
        if isinstance(item, Exception):
            raise item
        # Derive tool name from tool_choice kwarg so the mock works for any
        # forced-tool call (select_cases for M3b rerank, emit_decomposition
        # for M4 decomposer, etc.). Fall back to select_cases for back-compat
        # with tests that don't set tool_choice.
        tool_choice = kwargs.get("tool_choice") or {}
        tool_name = tool_choice.get("name", "select_cases")
        # Mirror the Anthropic SDK's `Message` object shape (enough for our agent).
        tool_use = SimpleNamespace(
            type="tool_use",
            name=tool_name,
            input=item,
        )
        return SimpleNamespace(content=[tool_use])


class MockAnthropicForRerank:
    """Mirrors `AsyncAnthropic`'s `.messages` attribute shape for one-shot
    `messages.create` tests."""

    def __init__(self, tool_inputs: list) -> None:
        self.messages = MockMessagesClient(tool_inputs)


__all__ = [  # alphabetical
    "MockAnthropicClient",
    "MockAnthropicForRerank",
    "MockMessagesClient",
    "ScriptedToolUse",
    "ScriptedTurn",
]
