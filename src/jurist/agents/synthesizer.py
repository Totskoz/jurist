"""M0 fake synthesizer — streams the canned FAKE_ANSWER token-by-token."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from jurist.fakes import FAKE_ANSWER
from jurist.schemas import SynthesizerIn, SynthesizerOut, TraceEvent

_ARTIKEL_URL = "https://wetten.overheid.nl/{bwb_id}"
_UITSPRAAK_URL = "https://uitspraken.rechtspraak.nl/details?id={ecli}"


def _tokenize(text: str) -> list[str]:
    # Word-level chunks with trailing spaces so reassembly reproduces the text.
    words = text.split(" ")
    return [w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]


async def run(input: SynthesizerIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")

    full_text = " ".join(
        [
            FAKE_ANSWER.korte_conclusie,
            *[c.quote + " " + c.explanation for c in FAKE_ANSWER.relevante_wetsartikelen],
            *[c.quote + " " + c.explanation for c in FAKE_ANSWER.vergelijkbare_uitspraken],
            FAKE_ANSWER.aanbeveling,
        ]
    )
    for tok in _tokenize(full_text):
        await asyncio.sleep(0.02)
        yield TraceEvent(type="answer_delta", data={"text": tok})

    for cit in FAKE_ANSWER.relevante_wetsartikelen:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "artikel",
                "id": cit.bwb_id,
                "resolved_url": _ARTIKEL_URL.format(bwb_id=cit.bwb_id),
            },
        )
    for cit in FAKE_ANSWER.vergelijkbare_uitspraken:
        yield TraceEvent(
            type="citation_resolved",
            data={
                "kind": "uitspraak",
                "id": cit.ecli,
                "resolved_url": _UITSPRAAK_URL.format(ecli=cit.ecli),
            },
        )

    out = SynthesizerOut(answer=FAKE_ANSWER)
    yield TraceEvent(type="agent_finished", data=out.model_dump())
