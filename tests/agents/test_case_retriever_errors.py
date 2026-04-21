"""M3b case retriever — error paths. All tests use mocks; no network."""
from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from jurist.agents import case_retriever
from jurist.agents.case_retriever import RerankFailedError
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import (
    ArticleNode,
    CaseChunkRow,
    CaseRetrieverIn,
    KGSnapshot,
)
from jurist.vectorstore import CaseStore
from tests.fixtures.mock_llm import MockAnthropicForRerank


class _FakeEmbedder:
    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        v = np.zeros((len(texts), 1024), dtype=np.float32)
        v[:, 0] = 1.0
        return v


def _row(ecli: str, idx: int, scale: float) -> CaseChunkRow:
    emb = np.zeros(1024, dtype=np.float32)
    emb[0] = scale
    return CaseChunkRow(
        ecli=ecli, chunk_idx=idx, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t" * 500, embedding=emb.tolist(),
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


def _kg_stub() -> NetworkXKG:
    snap = KGSnapshot(
        generated_at="t", source_versions={},
        nodes=[ArticleNode(
            article_id="A", bwb_id="BWBX", label="A", title="T",
            body_text="b", outgoing_refs=[],
        )],
        edges=[],
    )
    return NetworkXKG.from_snapshot(snap)


def _full_store(tmp_path) -> CaseStore:
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    rows = [
        _row("ECLI:NL:A:1", 0, 1.00),
        _row("ECLI:NL:B:2", 0, 0.80),
        _row("ECLI:NL:C:3", 0, 0.60),
        _row("ECLI:NL:D:4", 0, 0.55),
    ]
    store.add_rows(rows)
    return store


def _valid_picks(eclis: list[str]) -> dict:
    return {"picks": [
        {"ecli": eclis[0], "reason": "Relevant voor feitelijke gelijkenis."},
        {"ecli": eclis[1], "reason": "Past juridisch bij de vraag over huurverhoging."},
        {"ecli": eclis[2], "reason": "Illustreert de werking van Boek 7 Artikel 248."},
    ]}


def _ctx(tmp_path, mock: MockAnthropicForRerank, store=None) -> RunContext:
    return RunContext(
        kg=_kg_stub(), llm=mock,
        case_store=store if store is not None else _full_store(tmp_path),
        embedder=_FakeEmbedder(),
    )


def _input() -> CaseRetrieverIn:
    return CaseRetrieverIn(
        question="Q?", sub_questions=["SQ"], statute_context=[],
    )


@pytest.mark.asyncio
async def test_regen_succeeds_after_invalid_first_response(tmp_path, caplog) -> None:
    # First response: missing tool_use (empty content). Second: valid.

    class _FirstBadClient:
        """First call: response with no tool_use. Second: valid picks."""
        def __init__(self) -> None:
            self._second = MockAnthropicForRerank(
                tool_inputs=[_valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])],
            )
            self._calls = 0

        class _Msgs:
            def __init__(self, outer: _FirstBadClient) -> None:
                self._outer = outer

            async def create(self, **kwargs):
                self._outer._calls += 1
                if self._outer._calls == 1:
                    # Empty response: no tool_use blocks
                    return SimpleNamespace(content=[])
                return await self._outer._second.messages.create(**kwargs)

        @property
        def messages(self):
            return _FirstBadClient._Msgs(self)

    client = _FirstBadClient()
    ctx = _ctx(tmp_path, client)  # type: ignore[arg-type]

    caplog.set_level(logging.INFO, logger="jurist.agents.case_retriever")
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"
    # Exactly one regen happened — two LLM calls total
    assert client._calls == 2
    assert any("rerank attempt 1 invalid" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_invalid_twice_raises_rerank_failed(tmp_path) -> None:
    # Both responses: empty content (no tool_use)

    class _AlwaysEmpty:
        class _Msgs:
            async def create(self, **kwargs):
                return SimpleNamespace(content=[])

        @property
        def messages(self):
            return _AlwaysEmpty._Msgs()

    ctx = _ctx(tmp_path, _AlwaysEmpty())  # type: ignore[arg-type]
    with pytest.raises(RerankFailedError, match="invalid after retry"):
        _ = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]


@pytest.mark.asyncio
async def test_less_than_three_candidates_short_circuits(tmp_path) -> None:
    # Store with only 2 unique ECLIs
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([
        _row("ECLI:NL:A:1", 0, 1.0),
        _row("ECLI:NL:B:2", 0, 0.8),
    ])

    class _NoCallClient:
        class _Msgs:
            async def create(self, **kwargs):
                raise AssertionError("must not be called when candidates < 3")

        @property
        def messages(self):
            return _NoCallClient._Msgs()

    ctx = _ctx(tmp_path, _NoCallClient(), store=store)  # type: ignore[arg-type]
    with pytest.raises(RerankFailedError, match="candidates.*<3"):
        _ = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]


@pytest.mark.asyncio
async def test_duplicate_ecli_in_picks_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:A:1", "reason": "Feitelijk zeer vergelijkbaar."},
        {"ecli": "ECLI:NL:A:1", "reason": "Tweede keer A — ongeldig, dupliceert."},
        {"ecli": "ECLI:NL:B:2", "reason": "Relevant voor juridische context."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"


@pytest.mark.asyncio
async def test_ecli_not_in_candidate_set_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:Z:99", "reason": "Uit de lucht gegrepen ECLI-niet-in-set."},
        {"ecli": "ECLI:NL:A:1", "reason": "Echte ECLI uit de kandidaten."},
        {"ecli": "ECLI:NL:B:2", "reason": "Nog een echte ECLI uit de kandidaten."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"


@pytest.mark.asyncio
async def test_short_reason_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:A:1", "reason": "Ok"},   # too short
        {"ecli": "ECLI:NL:B:2", "reason": "Voldoet aan alle eisen hoop ik."},
        {"ecli": "ECLI:NL:C:3", "reason": "Ook voldoende, minstens twintig tekens."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"


@pytest.mark.asyncio
async def test_wrong_pick_count_triggers_regen(tmp_path) -> None:
    bad = {"picks": [
        {"ecli": "ECLI:NL:A:1", "reason": "Slechts een pick; te weinig."},
    ]}
    good = _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"])
    mock = MockAnthropicForRerank(tool_inputs=[bad, good])
    ctx = _ctx(tmp_path, mock)
    events = [ev async for ev in case_retriever.run(_input(), ctx=ctx)]
    assert events[-1].type == "agent_finished"
