"""Thin tool-use loop driver. Yields LoopEvents; callers translate to UI
events or TraceEvents as they see fit.

For M2, two implementations of the 'next turn' source exist:
  - scripted (MockAnthropicClient) for tests
  - real Anthropic streaming (added in Task 13)

This module hides that distinction behind a duck-typed `mock` parameter in
run_tool_loop. Task 13 wires a real-client path that lives in the same file.
"""
from __future__ import annotations

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any  # noqa: UP035 — Any lives in typing, not collections.abc

from jurist.agents.statute_retriever_tools import ToolExecutor, ToolResult

# ---------------- LoopEvent ADT ----------------

@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUseStart:
    name: str
    args: dict[str, Any]


@dataclass
class ToolResultEvent:
    name: str
    args: dict[str, Any]
    result: ToolResult


@dataclass
class Done:
    selected: list[dict[str, Any]]


@dataclass
class Coerced:
    reason: str  # "max_iter" | "wall_clock" | "dup_loop"
    selected: list[dict[str, Any]] = field(default_factory=list)


LoopEvent = TextDelta | ToolUseStart | ToolResultEvent | Done | Coerced


# ---------------- Driver ----------------

async def run_tool_loop(
    *,
    mock: Any | None = None,   # MockAnthropicClient for tests
    executor: ToolExecutor,
    system: str,
    tools: list[dict[str, Any]],
    user_message: str,
    max_iters: int,
    wall_clock_cap_s: float,
) -> AsyncIterator[LoopEvent]:
    """Drive a tool-use loop. `mock` is used when supplied; otherwise Task 13
    wires a real Anthropic call path here."""
    started = time.monotonic()
    history: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]
    for _ in range(max_iters):
        if (time.monotonic() - started) > wall_clock_cap_s:
            yield Coerced(reason="wall_clock", selected=[])
            return
        turn = mock.next_turn(history)
        for delta in turn.text_deltas:
            yield TextDelta(text=delta)
        if not turn.tool_uses:
            # No tool calls, no text — model stalled. Coerce.
            if not turn.text_deltas:
                yield Coerced(reason="stall", selected=[])
                return
            # Text without tools and no done: keep looping; the model might
            # reply again next turn. Append an assistant-text record.
            history.append({
                "role": "assistant",
                "content": "".join(turn.text_deltas),
            })
            continue
        # Record the assistant turn (text + tool_uses) in history.
        history.append({
            "role": "assistant",
            "content": {
                "text": "".join(turn.text_deltas),
                "tool_uses": [
                    {"name": tu.name, "args": tu.args} for tu in turn.tool_uses
                ],
            },
        })
        for tu in turn.tool_uses:
            yield ToolUseStart(name=tu.name, args=tu.args)
            if tu.name == "done":
                result = await executor.execute("done", tu.args)
                yield ToolResultEvent(name="done", args=tu.args, result=result)
                if not result.is_error:
                    yield Done(selected=list(tu.args.get("selected", [])))
                    return
                # Error on done — caller (Task 14) will implement the
                # one-retry-then-coerce policy; for now, coerce immediately
                # with empty selection so the happy-path test stays simple.
                yield Coerced(reason="done_error", selected=[])
                return
            result = await executor.execute(tu.name, tu.args)
            yield ToolResultEvent(name=tu.name, args=tu.args, result=result)
            history.append({
                "role": "user",
                "content": {"tool_result": result.extra, "is_error": result.is_error},
            })
    # Loop exhausted without done.
    yield Coerced(reason="max_iter", selected=[])
