"""SSE formatting and per-run event buffer with bounded history + live fan-out."""
from __future__ import annotations

import asyncio
from collections import deque
from typing import AsyncIterator

from jurist.schemas import TraceEvent


def format_sse(event: TraceEvent) -> str:
    """Serialize a TraceEvent as a single SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


class EventBuffer:
    """Bounded per-run event buffer with replay + live streaming.

    - Holds up to `max_history` events so a late subscriber can replay.
    - After the last history event, streams live puts until a terminal event
      (`run_finished` or `run_failed`) is observed, then closes.
    - Exactly one subscriber per buffer is supported.
    """

    _TERMINAL = {"run_finished", "run_failed"}

    def __init__(self, max_history: int = 100) -> None:
        self._history: deque[TraceEvent] = deque(maxlen=max_history)
        self._total_put = 0
        self._new_event = asyncio.Event()
        self._closed = False

    async def put(self, event: TraceEvent) -> None:
        if self._closed:
            return
        self._history.append(event)
        self._total_put += 1
        self._new_event.set()
        if event.type in self._TERMINAL:
            self._closed = True

    async def subscribe(self) -> AsyncIterator[TraceEvent]:
        seen_total = 0
        while True:
            history = list(self._history)
            first_in_history_total = self._total_put - len(history)
            # Start from whichever is later: what we've seen, or the oldest still held.
            start_total = max(seen_total, first_in_history_total)
            start_idx = start_total - first_in_history_total
            for ev in history[start_idx:]:
                yield ev
                start_total += 1
                seen_total = start_total
                if ev.type in self._TERMINAL:
                    return
            if self._closed:
                return
            self._new_event.clear()
            await self._new_event.wait()
