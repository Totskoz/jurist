"""M3b case retriever — happy path."""
from __future__ import annotations

import numpy as np
import pytest

from jurist.agents import case_retriever
from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import (
    ArticleNode,
    CaseChunkRow,
    CaseRetrieverIn,
    CaseRetrieverOut,
    CitedArticle,
    KGSnapshot,
)
from jurist.vectorstore import CaseStore
from tests.fixtures.mock_llm import MockAnthropicForRerank


class _FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        self.calls.append(list(texts))
        v = np.zeros((len(texts), 1024), dtype=np.float32)
        v[:, 0] = 1.0
        return v


def _row(ecli: str, idx: int, text: str, scale: float) -> CaseChunkRow:
    emb = np.zeros(1024, dtype=np.float32)
    emb[0] = scale
    return CaseChunkRow(
        ecli=ecli, chunk_idx=idx, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text=text, embedding=emb.tolist(),
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


def _populate_store(tmp_path) -> CaseStore:
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    rows = [
        _row("ECLI:NL:A:1", 0, "text A best",  1.00),
        _row("ECLI:NL:A:1", 1, "text A next",  0.95),
        _row("ECLI:NL:B:2", 0, "text B best",  0.80),
        _row("ECLI:NL:C:3", 0, "text C best",  0.60),
        _row("ECLI:NL:D:4", 0, "text D best",  0.55),
    ]
    store.add_rows(rows)
    return store


def _valid_picks(eclis: list[str]) -> dict:
    assert len(eclis) >= 3
    return {"picks": [
        {"ecli": eclis[0], "reason": "Feitelijk zeer vergelijkbaar met de vraag."},
        {"ecli": eclis[1], "reason": "Relevant voor juridische context van huurverhoging."},
        {"ecli": eclis[2], "reason": "Toepassing van Boek 7, Artikel 248 in vergelijkbare zaak."},
    ]}


@pytest.mark.asyncio
async def test_happy_path_emits_expected_events(tmp_path) -> None:
    store = _populate_store(tmp_path)
    embedder = _FakeEmbedder()
    # First 3 ECLIs in cosine order: A, B, C
    mock = MockAnthropicForRerank(tool_inputs=[
        _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"]),
    ])
    ctx = RunContext(
        kg=_kg_stub(), llm=mock, case_store=store, embedder=embedder,
    )
    inp = CaseRetrieverIn(
        question="Mag de huur 15% omhoog?",
        sub_questions=["Is 15% rechtmatig?"],
        statute_context=[CitedArticle(
            bwb_id="BWBR0005290",
            article_id="BWBR0005290/Boek7/Artikel248",
            article_label="Boek 7, Artikel 248",
            body_text="body",
            reason="Regelt huurverhoging.",
        )],
    )

    events = [ev async for ev in case_retriever.run(inp, ctx=ctx)]
    types = [e.type for e in events]

    assert types[0] == "agent_started"
    assert types[1] == "search_started"
    case_found_events = [e for e in events if e.type == "case_found"]
    assert len(case_found_events) == 4  # A, B, C, D
    assert {e.data["ecli"] for e in case_found_events} == {
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3", "ECLI:NL:D:4",
    }

    reranked = [e for e in events if e.type == "reranked"]
    assert len(reranked) == 1
    assert reranked[0].data["kept"] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]

    assert types[-1] == "agent_finished"
    final_data = events[-1].data
    out = CaseRetrieverOut.model_validate(final_data)
    assert len(out.cited_cases) == 3
    assert [c.ecli for c in out.cited_cases] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]
    # Similarity flows from best chunk; A's best chunk scale is 1.0
    assert out.cited_cases[0].similarity > 0.99
    # Reason flows from Haiku mock
    assert "vergelijkbaar" in out.cited_cases[0].reason
    # URL flows through from the row
    assert out.cited_cases[0].url == (
        "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:A:1"
    )


@pytest.mark.asyncio
async def test_embedder_called_once_with_joined_sub_questions(tmp_path) -> None:
    store = _populate_store(tmp_path)
    embedder = _FakeEmbedder()
    mock = MockAnthropicForRerank(tool_inputs=[
        _valid_picks(["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"]),
    ])
    ctx = RunContext(kg=_kg_stub(), llm=mock, case_store=store, embedder=embedder)
    inp = CaseRetrieverIn(
        question="Q?", sub_questions=["SQ1", "SQ2"], statute_context=[],
    )
    _ = [ev async for ev in case_retriever.run(inp, ctx=ctx)]
    assert len(embedder.calls) == 1
    # Joined with newline
    assert embedder.calls[0] == ["SQ1\nSQ2"]
