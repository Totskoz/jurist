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
    history: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    # Visit-recency log of article_ids touched by get_article / follow_cross_ref.
    visited: list[str] = []
    done_errors = 0  # counts consecutive done failures
    last_call: tuple[str, str] | None = None
    dup_count = 0

    async def _next_turn(hist: list[dict[str, Any]]) -> ModelTurn:
        if mock is not None:
            return mock.next_turn(hist)
        return await _anthropic_next_turn(
            client=client, model=model, temperature=temperature,
            max_tokens=max_tokens, system=system, tools=tools,
            messages=_history_to_anthropic_messages(hist),
        )

    def _coerce_selection(reason: str) -> list[dict[str, Any]]:
        # Deduplicate preserving last-occurrence (recency-ordered).
        seen: set[str] = set()
        recency: list[str] = []
        for aid in reversed(visited):
            if aid in seen:
                continue
            seen.add(aid)
            recency.append(aid)
        recency = recency[:8]
        return [{"article_id": aid, "reason": f"auto-selected (coerced: {reason})"}
                for aid in recency]

    for _ in range(max_iters):
        if (time.monotonic() - started) > wall_clock_cap_s:
            yield Coerced(reason="wall_clock", selected=_coerce_selection("wall_clock"))
            return
        turn = await _next_turn(history)
        for delta in turn.text_deltas:
            yield TextDelta(text=delta)
        if not turn.tool_uses:
            if not turn.text_deltas:
                yield Coerced(reason="stall", selected=_coerce_selection("stall"))
                return
            history.append({"role": "assistant", "content": "".join(turn.text_deltas)})
            continue
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
            _args_key = sorted(tu.args.items()) if isinstance(tu.args, dict) else tu.args
            call_sig = (tu.name, repr(_args_key))
            if last_call == call_sig:
                dup_count += 1
            else:
                dup_count = 0
            last_call = call_sig

            if dup_count >= 2:
                yield Coerced(reason="dup_loop",
                              selected=_coerce_selection("dup_loop"))
                return
            if dup_count == 1 and tu.name != "done":
                advisory = ToolResult(
                    result_summary=(
                        "You already called this tool with identical "
                        "arguments. Try get_article, follow_cross_ref, "
                        "list_neighbors, or done with a different plan."
                    ),
                    is_error=True,
                )
                yield ToolResultEvent(name=tu.name, args=tu.args, result=advisory)
                history.append({
                    "role": "user",
                    "content": {"tool_result": {"advice": advisory.result_summary},
                                "is_error": True},
                })
                continue

            yield ToolUseStart(name=tu.name, args=tu.args)
            if tu.name == "done":
                result = await executor.execute("done", tu.args)
                yield ToolResultEvent(name="done", args=tu.args, result=result)
                if not result.is_error:
                    yield Done(selected=list(tu.args.get("selected", [])))
                    return
                done_errors += 1
                if done_errors >= 2:
                    yield Coerced(reason="done_error",
                                  selected=_coerce_selection("done_error"))
                    return
                # Inject the error tool_result for the model to correct next turn.
                history.append({
                    "role": "user",
                    "content": {"tool_result": result.extra or {"error": result.result_summary},
                                "is_error": True},
                })
                continue
            result = await executor.execute(tu.name, tu.args)
            yield ToolResultEvent(name=tu.name, args=tu.args, result=result)
            if result.kg_effect and "node_visited" in result.kg_effect:
                visited.append(result.kg_effect["node_visited"])
            history.append({
                "role": "user",
                "content": {
                    "tool_result": result.extra or {"error": result.result_summary},
                    "is_error": result.is_error,
                },
            })
    # Loop exhausted without done.
    yield Coerced(reason="max_iter", selected=_coerce_selection("max_iter"))


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
