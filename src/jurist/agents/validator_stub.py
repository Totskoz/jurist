"""M0 validator stub — always returns valid=True.

v2 will check: schema validity, citation resolution, presence of conclusion,
and explicit contradiction detection between statutes and cases.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from jurist.schemas import TraceEvent, ValidatorIn, ValidatorOut


async def run(input: ValidatorIn) -> AsyncIterator[TraceEvent]:
    yield TraceEvent(type="agent_started")
    out = ValidatorOut(valid=True, issues=[])
    yield TraceEvent(type="agent_finished", data=out.model_dump())
