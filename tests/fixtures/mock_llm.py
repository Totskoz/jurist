"""Scripted mock for Anthropic tool-use turns.

Re-exports ModelTurn/ModelToolUse as ScriptedTurn/ScriptedToolUse for
readability in tests. A script is a list of ScriptedTurn. Each turn
models one assistant reply. When the script is exhausted, the mock
returns an empty turn so the loop under test coerces on its own."""
from __future__ import annotations

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


__all__ = ["MockAnthropicClient", "ScriptedToolUse", "ScriptedTurn"]
