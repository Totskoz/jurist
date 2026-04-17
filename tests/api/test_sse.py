import asyncio

import pytest

from jurist.api.sse import EventBuffer, format_sse
from jurist.schemas import TraceEvent


def test_format_sse_json_payload():
    ev = TraceEvent(type="agent_started", agent="decomposer", run_id="r1", ts="t")
    out = format_sse(ev)
    # SSE frames are "data: <json>\n\n".
    assert out.endswith("\n\n")
    assert out.startswith("data: ")
    body = out[len("data: "):-2]
    assert '"type":"agent_started"' in body


@pytest.mark.asyncio
async def test_buffer_replays_then_streams_live():
    buf = EventBuffer(max_history=10)
    await buf.put(TraceEvent(type="run_started"))
    await buf.put(TraceEvent(type="agent_started", agent="decomposer"))

    collected: list[TraceEvent] = []

    async def consumer():
        async for ev in buf.subscribe():
            collected.append(ev)
            if ev.type == "run_finished":
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    await buf.put(TraceEvent(type="agent_finished", agent="decomposer"))
    await buf.put(TraceEvent(type="run_finished"))
    await asyncio.wait_for(task, timeout=1.0)

    types = [e.type for e in collected]
    assert types == ["run_started", "agent_started", "agent_finished", "run_finished"]


@pytest.mark.asyncio
async def test_buffer_drops_oldest_when_history_full():
    buf = EventBuffer(max_history=3)
    for i in range(5):
        await buf.put(TraceEvent(type=f"e{i}"))

    collected: list[str] = []

    async def consumer():
        async for ev in buf.subscribe():
            collected.append(ev.type)
            if ev.type == "done":
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    await buf.put(TraceEvent(type="done"))
    await asyncio.wait_for(task, timeout=1.0)

    # Only last 3 history events + "done" are seen (e2, e3, e4, done).
    assert collected == ["e2", "e3", "e4", "done"]
