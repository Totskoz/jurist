"""M3b case retriever — happy path + M5 low_confidence."""
from __future__ import annotations

import numpy as np
import pytest

from jurist.agents import case_retriever
from jurist.config import RunContext, Settings
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
    # kept stays around for back-compat.
    assert reranked[0].data["kept"] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]
    picks = reranked[0].data["picks"]
    assert [p["ecli"] for p in picks] == [
        "ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3",
    ]
    # Reasons flow from the Haiku mock's tool input (≥20 Dutch chars each).
    assert picks[0]["reason"] == "Feitelijk zeer vergelijkbaar met de vraag."
    assert picks[1]["reason"].startswith("Relevant voor juridische context")
    assert picks[2]["reason"].startswith("Toepassing van Boek 7")

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
    # M4: chunk_text propagates from candidate → CitedCase
    assert all(c.chunk_text for c in out.cited_cases)
    assert all(len(c.chunk_text) >= len(c.snippet) for c in out.cited_cases)


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


# ---------------------------------------------------------------------------
# M5 low_confidence tests
# ---------------------------------------------------------------------------

def _make_chunk_row(ecli: str, text: str) -> CaseChunkRow:
    """Minimal CaseChunkRow for _FakeCaseStore — embedding field unused."""
    return CaseChunkRow(
        ecli=ecli, chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text=text, embedding=[0.0] * 1024,
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


class _FakeCaseStore:
    """Bypasses LanceDB. Returns predetermined (CaseChunkRow, similarity) pairs."""

    def __init__(self, rows_with_sims: list[tuple[CaseChunkRow, float]]) -> None:
        self._rows = rows_with_sims

    def query(self, vector: np.ndarray, *, top_k: int = 20) -> list[tuple[CaseChunkRow, float]]:  # noqa: ARG002
        return self._rows[:top_k]


def _weak_store() -> _FakeCaseStore:
    """3 candidates with similarities [0.42, 0.38, 0.40] — all below 0.55."""
    return _FakeCaseStore([
        (_make_chunk_row("ECLI:NL:W:1", "weak alpha text"), 0.42),
        (_make_chunk_row("ECLI:NL:W:2", "weak beta text"), 0.40),
        (_make_chunk_row("ECLI:NL:W:3", "weak gamma text"), 0.38),
    ])


def _mixed_store() -> _FakeCaseStore:
    """3 candidates with similarities [0.71, 0.52, 0.48] — top one above 0.55."""
    return _FakeCaseStore([
        (_make_chunk_row("ECLI:NL:M:1", "strong alpha text"), 0.71),
        (_make_chunk_row("ECLI:NL:M:2", "medium beta text"), 0.52),
        (_make_chunk_row("ECLI:NL:M:3", "medium gamma text"), 0.48),
    ])


def _rerank_picks(eclis: list[str]) -> dict:
    assert len(eclis) == 3
    return {"picks": [
        {"ecli": eclis[0], "reason": "Meest relevante uitspraak voor deze zaak."},
        {"ecli": eclis[1], "reason": "Relevant voor juridische context huurrecht."},
        {"ecli": eclis[2], "reason": "Toepassing van vergelijkbare huurprocedure."},
    ]}


@pytest.mark.asyncio
async def test_case_retriever_low_confidence_true_when_all_below_floor() -> None:
    """All three reranked picks have similarity < 0.55 → low_confidence=True."""
    store = _weak_store()
    embedder = _FakeEmbedder()
    eclis = ["ECLI:NL:W:1", "ECLI:NL:W:2", "ECLI:NL:W:3"]
    mock = MockAnthropicForRerank(tool_inputs=[_rerank_picks(eclis)])
    ctx = RunContext(kg=_kg_stub(), llm=mock, case_store=store, embedder=embedder)
    inp = CaseRetrieverIn(
        question="off-topic vraag", sub_questions=["?"], statute_context=[],
    )

    out_events = []
    async for ev in case_retriever.run(inp, ctx=ctx):
        out_events.append(ev)

    out = CaseRetrieverOut.model_validate(out_events[-1].data)
    assert len(out.cited_cases) == 3
    assert all(c.similarity < 0.55 for c in out.cited_cases)
    assert out.low_confidence is True


@pytest.mark.asyncio
async def test_case_retriever_low_confidence_false_when_any_above_floor() -> None:
    """At least one picked case ≥ 0.55 → low_confidence=False."""
    store = _mixed_store()
    embedder = _FakeEmbedder()
    eclis = ["ECLI:NL:M:1", "ECLI:NL:M:2", "ECLI:NL:M:3"]
    mock = MockAnthropicForRerank(tool_inputs=[_rerank_picks(eclis)])
    ctx = RunContext(kg=_kg_stub(), llm=mock, case_store=store, embedder=embedder)
    inp = CaseRetrieverIn(
        question="relevante huurvraag", sub_questions=["?"], statute_context=[],
    )

    out_events = []
    async for ev in case_retriever.run(inp, ctx=ctx):
        out_events.append(ev)

    out = CaseRetrieverOut.model_validate(out_events[-1].data)
    assert out.low_confidence is False


@pytest.mark.asyncio
async def test_case_retriever_low_confidence_respects_floor_threshold(monkeypatch) -> None:
    """Lowering the floor to 0.80 makes even similarity=0.71 count as low → True."""
    # Patch the settings object in the case_retriever module directly.
    # This avoids importlib.reload complications with module-level bindings.
    high_floor_settings = Settings(case_similarity_floor=0.80)
    monkeypatch.setattr("jurist.agents.case_retriever.settings", high_floor_settings)

    store = _mixed_store()  # similarities [0.71, 0.52, 0.48] — all < 0.80
    embedder = _FakeEmbedder()
    eclis = ["ECLI:NL:M:1", "ECLI:NL:M:2", "ECLI:NL:M:3"]
    mock = MockAnthropicForRerank(tool_inputs=[_rerank_picks(eclis)])
    ctx = RunContext(kg=_kg_stub(), llm=mock, case_store=store, embedder=embedder)
    inp = CaseRetrieverIn(
        question="relevante huurvraag", sub_questions=["?"], statute_context=[],
    )

    out_events = []
    async for ev in case_retriever.run(inp, ctx=ctx):
        out_events.append(ev)

    out = CaseRetrieverOut.model_validate(out_events[-1].data)
    assert out.low_confidence is True
