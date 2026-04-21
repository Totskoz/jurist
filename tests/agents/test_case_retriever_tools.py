"""Pure-helper tests for case_retriever_tools — no asyncio, no Anthropic."""
from __future__ import annotations

import numpy as np
import pytest

from jurist.agents.case_retriever_tools import (
    CaseCandidate,
    build_rerank_tool_schema,
    build_rerank_user_message,
    retrieve_candidates,
)
from jurist.schemas import CaseChunkRow, CitedArticle
from jurist.vectorstore import CaseStore


class _FakeEmbedder:
    """Returns a fixed (1, 1024) vector. Ignores input texts."""

    def __init__(self, vector: np.ndarray) -> None:
        self._vector = vector.reshape(1, -1).astype(np.float32)

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:
        return np.repeat(self._vector, len(texts) or 1, axis=0)


def _row(ecli: str, chunk_idx: int, text: str, embedding: list[float]) -> CaseChunkRow:
    return CaseChunkRow(
        ecli=ecli, chunk_idx=chunk_idx,
        court="Rb", date="2025-01-01", zaaknummer="z",
        subject_uri="u", modified="2025-01-01",
        text=text, embedding=embedding,
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


@pytest.fixture
def populated_store(tmp_path):
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    # 12 chunks across 4 ECLIs: A has 5, B has 4, C has 2, D has 1.
    # Vectors are crafted so that A's chunk 0 has the highest similarity
    # to the query basis e[0], followed by A's chunk 1, then B's chunks…
    def vec(dim: int, scale: float = 1.0) -> list[float]:
        v = np.zeros(1024, dtype=np.float32)
        v[dim] = scale
        return v.tolist()

    rows = [
        _row("ECLI:A", 0, "A best",  vec(0, 1.00)),
        _row("ECLI:A", 1, "A next",  vec(0, 0.95)),
        _row("ECLI:A", 2, "A mid",   vec(0, 0.90)),
        _row("ECLI:A", 3, "A late",  vec(0, 0.85)),
        _row("ECLI:A", 4, "A worst", vec(0, 0.80)),
        _row("ECLI:B", 0, "B best",  vec(0, 0.75)),
        _row("ECLI:B", 1, "B next",  vec(0, 0.70)),
        _row("ECLI:B", 2, "B mid",   vec(0, 0.65)),
        _row("ECLI:B", 3, "B late",  vec(0, 0.60)),
        _row("ECLI:C", 0, "C best",  vec(0, 0.55)),
        _row("ECLI:C", 1, "C next",  vec(0, 0.50)),
        _row("ECLI:D", 0, "D only " * 100, vec(0, 0.45)),
    ]
    store.add_rows(rows)
    return store


def test_retrieve_candidates_preserves_descending_similarity(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32)
    query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=10, snippet_chars=50,
    )
    assert [c.ecli for c in cands] == ["ECLI:A", "ECLI:B", "ECLI:C", "ECLI:D"]
    sims = [c.similarity for c in cands]
    assert sims == sorted(sims, reverse=True)


def test_retrieve_candidates_keeps_best_chunk_per_ecli(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32)
    query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=10, snippet_chars=200,
    )
    by_ecli = {c.ecli: c for c in cands}
    # A's best chunk (idx 0, scale 1.00) wins over chunks 1-4
    assert by_ecli["ECLI:A"].snippet.startswith("A best")
    # B's best (idx 0, 0.75)
    assert by_ecli["ECLI:B"].snippet.startswith("B best")


def test_retrieve_candidates_caps_at_eclis_limit(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32)
    query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=2, snippet_chars=50,
    )
    assert len(cands) == 2
    assert [c.ecli for c in cands] == ["ECLI:A", "ECLI:B"]


def test_retrieve_candidates_truncates_snippet_with_ellipsis(populated_store) -> None:
    query_vec = np.zeros(1024, dtype=np.float32)
    query_vec[0] = 1.0
    embedder = _FakeEmbedder(query_vec)
    cands = retrieve_candidates(
        populated_store, embedder, "any query",
        chunks_top_k=12, eclis_limit=10, snippet_chars=30,
    )
    d = next(c for c in cands if c.ecli == "ECLI:D")
    # D's text is "D only D only ..." — text[:30] ends with a trailing space
    # that rstrip() removes, yielding 29 content chars + 1 ellipsis = 30 total.
    assert d.snippet.endswith("…")
    assert len(d.snippet) == 30
    assert not d.snippet.startswith(" ") and " …" not in d.snippet  # rstrip fired


def test_retrieve_candidates_returns_empty_for_empty_store(tmp_path) -> None:
    store = CaseStore(tmp_path / "empty.lance")
    store.open_or_create()
    embedder = _FakeEmbedder(np.zeros(1024, dtype=np.float32))
    cands = retrieve_candidates(
        store, embedder, "q", chunks_top_k=10, eclis_limit=5, snippet_chars=50,
    )
    assert cands == []


def test_case_candidate_is_frozen() -> None:
    import dataclasses
    c = CaseCandidate(
        ecli="E", court="Rb", date="2025-01-01",
        snippet="s", similarity=0.5, url="u",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.ecli = "F"  # type: ignore[misc]


def test_rerank_tool_schema_populates_enum() -> None:
    eclis = ["ECLI:NL:A:1", "ECLI:NL:B:2", "ECLI:NL:C:3"]
    schema = build_rerank_tool_schema(eclis)
    assert schema["name"] == "select_cases"
    props = schema["input_schema"]["properties"]["picks"]
    assert props["minItems"] == 3
    assert props["maxItems"] == 3
    assert props["uniqueItems"] is True
    item_props = props["items"]["properties"]
    assert item_props["ecli"]["enum"] == eclis
    assert item_props["ecli"]["type"] == "string"
    assert item_props["reason"]["minLength"] == 20
    assert set(props["items"]["required"]) == {"ecli", "reason"}


def test_rerank_tool_schema_top_level_required_is_picks() -> None:
    schema = build_rerank_tool_schema(["E1", "E2", "E3", "E4"])
    assert schema["input_schema"]["required"] == ["picks"]
    assert schema["input_schema"]["type"] == "object"


def test_build_rerank_user_message_contains_all_inputs() -> None:
    candidates = [
        CaseCandidate(
            ecli="ECLI:NL:RBAMS:2022:5678",
            court="Rechtbank Amsterdam",
            date="2022-03-14",
            snippet="Huurverhoging van 15% …",
            similarity=0.81,
            url="https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:RBAMS:2022:5678",
        ),
        CaseCandidate(
            ecli="ECLI:NL:HR:2020:1234",
            court="Hoge Raad",
            date="2020-09-11",
            snippet="De verhuurder mag …",
            similarity=0.70,
            url="u",
        ),
    ]
    statute_context = [
        CitedArticle(
            bwb_id="BWBR0005290",
            article_id="BWBR0005290/Boek7/Artikel248",
            article_label="Boek 7, Artikel 248",
            body_text="body",
            reason="Regelt jaarlijkse huurverhoging.",
        ),
    ]
    msg = build_rerank_user_message(
        question="Mag de huur 15% omhoog?",
        sub_questions=["Is 15% rechtmatig?", "Geldt dit ook bij vrije sector?"],
        statute_context=statute_context,
        candidates=candidates,
    )
    # Question rendered
    assert "Mag de huur 15% omhoog?" in msg
    # Sub-questions rendered as bullets
    assert "- Is 15% rechtmatig?" in msg
    assert "- Geldt dit ook bij vrije sector?" in msg
    # Statute label + reason rendered
    assert "Boek 7, Artikel 248" in msg
    assert "Regelt jaarlijkse huurverhoging." in msg
    # Candidates rendered with index + ECLI + court + date + similarity
    assert "[1]" in msg
    assert "ECLI:NL:RBAMS:2022:5678" in msg
    assert "Rechtbank Amsterdam" in msg
    assert "2022-03-14" in msg
    # Similarity numeric (not the CaseCandidate repr)
    assert "0.81" in msg
    # Snippet rendered
    assert "Huurverhoging van 15%" in msg
    # Instruction to call select_cases
    assert "select_cases" in msg


def test_build_rerank_user_message_handles_empty_statute_context() -> None:
    cand = CaseCandidate(
        ecli="E", court="Rb", date="2025-01-01",
        snippet="s", similarity=0.5, url="u",
    )
    msg = build_rerank_user_message(
        question="Q",
        sub_questions=["SQ"],
        statute_context=[],
        candidates=[cand],
    )
    # Does not crash; still contains the question + candidate
    assert "Q" in msg
    assert "ECLI:E" in msg or "E" in msg
    # Statute header must be omitted entirely — no headerless section
    assert "Relevante wetsartikelen" not in msg
