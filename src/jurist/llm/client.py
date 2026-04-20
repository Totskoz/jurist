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
from jurist.llm.turn import ModelToolUse, ModelTurn

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
    mock: Any | None = None,          # MockAnthropicClient for tests
    client: Any | None = None,        # AsyncAnthropic when real
    model: str = "claude-sonnet-4-6",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    executor: ToolExecutor,
    system: str,
    tools: list[dict[str, Any]],
    user_message: str,
    max_iters: int,
    wall_clock_cap_s: float,
) -> AsyncIterator[LoopEvent]:
    """Drive a tool-use loop. `mock` is used when supplied; otherwise the real
    Anthropic streaming path is invoked via `client`."""
    started = time.monotonic()
    history: list[dict[str, Any]] = [
        {"role": "user", "content": user_message},
    ]

    async def _next_turn(history: list[dict[str, Any]]) -> ModelTurn:
        if mock is not None:
            return mock.next_turn(history)  # ScriptedTurn is a ModelTurn alias
        # Real Anthropic path: stream a single message, assemble into a ModelTurn.
        return await _anthropic_next_turn(
            client=client,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=_history_to_anthropic_messages(history),
        )

    for _ in range(max_iters):
        if (time.monotonic() - started) > wall_clock_cap_s:
            yield Coerced(reason="wall_clock", selected=[])
            return
        turn = await _next_turn(history)
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


# ---------------- Anthropic message translators ----------------

def _history_to_anthropic_messages(
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Translate our simple history into the Anthropic messages format.

    Our history uses a compact shape to keep the happy-path test readable;
    Anthropic expects a specific content-blocks structure."""
    out: list[dict[str, Any]] = []
    for msg in history:
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant" and "tool_uses" in content:
            blocks: list[dict[str, Any]] = []
            if content.get("text"):
                blocks.append({"type": "text", "text": content["text"]})
            for idx, tu in enumerate(content["tool_uses"]):
                blocks.append({
                    "type": "tool_use",
                    "id": f"tu_{len(out)}_{idx}",
                    "name": tu["name"],
                    "input": tu["args"],
                })
            out.append({"role": "assistant", "content": blocks})
            continue
        if role == "user" and "tool_result" in content:
            # Attach tool_result block referencing the preceding tool_use id.
            last_assistant = next(
                (m for m in reversed(out) if m["role"] == "assistant"), None
            )
            if last_assistant is None:
                continue
            tu_block = next(
                (b for b in last_assistant["content"] if b.get("type") == "tool_use"),
                None,
            )
            out.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tu_block["id"] if tu_block else "tu_missing",
                    "content": str(content["tool_result"]),
                    "is_error": bool(content.get("is_error")),
                }],
            })
            continue
        out.append({"role": role, "content": str(content)})
    return out


async def _anthropic_next_turn(
    *,
    client: Any,
    model: str,
    temperature: float,
    max_tokens: int,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> ModelTurn:
    """Stream one Anthropic turn and assemble a ModelTurn."""
    text_deltas: list[str] = []
    tool_uses: list[ModelToolUse] = []
    async with client.messages.stream(
        model=model,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        tools=tools,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    ) as stream:
        async for event in stream:
            if event.type == "content_block_delta":
                delta = event.delta
                if getattr(delta, "type", None) == "text_delta":
                    text_deltas.append(delta.text)
                # input_json_delta for tool_use is assembled by the SDK —
                # we read the finalized block in message_stop below.
            elif event.type == "message_stop":
                pass
        final = await stream.get_final_message()
    for block in final.content:
        if getattr(block, "type", None) == "tool_use":
            tool_uses.append(ModelToolUse(name=block.name, args=dict(block.input)))
    return ModelTurn(text_deltas=text_deltas, tool_uses=tool_uses)
