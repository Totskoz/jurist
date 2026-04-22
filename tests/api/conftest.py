"""Shared fixtures for tests/api/. Keeps orchestrator tests focused on
orchestrator behavior (event stamping, pump ordering, run_finished) by
stubbing the real case_retriever — individual tests can override via
monkeypatch.setattr to exercise the real one or a specific failure."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stub_case_retriever(monkeypatch):
    from jurist.agents import case_retriever
    from jurist.schemas import CaseRetrieverOut, CitedCase, TraceEvent

    async def _fake(_input, *, ctx):
        yield TraceEvent(type="agent_started")
        yield TraceEvent(type="search_started")
        yield TraceEvent(
            type="case_found",
            data={"ecli": "ECLI:NL:STUB:1", "similarity": 0.9},
        )
        yield TraceEvent(
            type="reranked",
            data={"kept": ["ECLI:NL:STUB:1"]},
        )
        out = CaseRetrieverOut(cited_cases=[CitedCase(
            ecli="ECLI:NL:STUB:1", court="Rb Test", date="2025-01-01",
            snippet="canned snippet for orchestrator tests",
            similarity=0.9,
            reason="Canned reason from tests/api/conftest.py stub fixture.",
            chunk_text="canned chunk text for orchestrator tests",
            url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:STUB:1",
        )])
        yield TraceEvent(type="agent_finished", data=out.model_dump())

    monkeypatch.setattr(case_retriever, "run", _fake)
    yield
