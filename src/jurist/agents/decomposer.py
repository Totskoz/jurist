"""M0 fake decomposer — yields hardcoded thinking + a fixed decomposition."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from jurist.schemas import DecomposerIn, DecomposerOut, TraceEvent


async def run(input: DecomposerIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    deltas = [
        "De vraag gaat over huurverhoging — ",
        "specifiek een eenzijdig voorstel van 15%. ",
        "Subvragen: is de woning gereguleerd of geliberaliseerd, ",
        "en wat is het maximale jaarlijkse huurverhogingspercentage?",
    ]
    for d in deltas:
        await asyncio.sleep(0.25)
        yield TraceEvent(type="agent_thinking", data={"text": d})

    out = DecomposerOut(
        sub_questions=[
            "Is de woning gereguleerd of geliberaliseerd?",
            "Wat is het maximale jaarlijkse huurverhogingspercentage?",
            "Wat kan de huurder doen bij bezwaar?",
        ],
        concepts=["huurverhoging", "geliberaliseerd", "puntenstelsel", "Huurcommissie"],
        intent="legality_check",
    )
    yield TraceEvent(type="agent_finished", data=out.model_dump())
