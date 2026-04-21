"""Tests for CaseStore LanceDB CRUD."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from jurist.schemas import CaseChunkRow


def _make_row(ecli: str, chunk_idx: int, *, vector: list[float] | None = None) -> CaseChunkRow:
    if vector is None:
        vector = [0.1] * 1024
    return CaseChunkRow(
        ecli=ecli,
        chunk_idx=chunk_idx,
        court="Rechtbank Test",
        date="2025-06-15",
        zaaknummer="C/13/1",
        subject_uri="http://psi.rechtspraak.nl/rechtsgebied#civielRecht_verbintenissenrecht",
        modified="2025-06-20T14:22:10Z",
        text=f"Body for {ecli} chunk {chunk_idx}",
        embedding=vector,
        url=f"https://uitspraken.rechtspraak.nl/details?id={ecli}",
    )


def test_open_or_create_on_fresh_path(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    assert store.all_eclis() == set()


def test_add_rows_then_contains_ecli(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([_make_row("ECLI:NL:A:1", 0), _make_row("ECLI:NL:A:1", 1)])
    assert store.contains_ecli("ECLI:NL:A:1") is True
    assert store.contains_ecli("ECLI:NL:A:2") is False
    assert store.all_eclis() == {"ECLI:NL:A:1"}


def test_add_rows_dedupes_on_ecli_and_chunk_idx(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([_make_row("ECLI:NL:A:1", 0)])
    store.add_rows([_make_row("ECLI:NL:A:1", 0), _make_row("ECLI:NL:A:1", 1)])
    # (A:1, 0) is a duplicate; add_rows skips it.
    assert store.row_count() == 2


def test_query_top_k_by_cosine(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    v_near = [1.0, 0.0] + [0.0] * 1022
    v_far = [0.0, 1.0] + [0.0] * 1022
    store.add_rows([
        _make_row("ECLI:NL:NEAR:1", 0, vector=v_near),
        _make_row("ECLI:NL:FAR:1", 0, vector=v_far),
    ])
    results = store.query(np.array([1.0, 0.0] + [0.0] * 1022, dtype=np.float32), top_k=1)
    assert len(results) == 1
    row, _sim = results[0]
    assert row.ecli == "ECLI:NL:NEAR:1"


def test_drop_removes_table(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore
    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()
    store.add_rows([_make_row("ECLI:NL:A:1", 0)])
    store.drop()
    store.open_or_create()
    assert store.all_eclis() == set()


def test_query_returns_row_similarity_tuples(tmp_path: Path) -> None:
    from jurist.vectorstore import CaseStore

    store = CaseStore(tmp_path / "cases.lance")
    store.open_or_create()

    # Two distinct vectors; query with one exactly and verify ordering + score.
    v1 = (np.eye(1024)[0]).astype(np.float32).tolist()
    v2 = (np.eye(1024)[1]).astype(np.float32).tolist()
    rows = [
        CaseChunkRow(
            ecli="ECLI:NL:X:2025:1", chunk_idx=0, court="Rb", date="2025-01-01",
            zaaknummer="z1", subject_uri="u", modified="2025-01-01",
            text="t1", embedding=v1, url="u1",
        ),
        CaseChunkRow(
            ecli="ECLI:NL:X:2025:2", chunk_idx=0, court="Rb", date="2025-01-01",
            zaaknummer="z2", subject_uri="u", modified="2025-01-01",
            text="t2", embedding=v2, url="u2",
        ),
    ]
    store.add_rows(rows)

    results = store.query(np.asarray(v1, dtype=np.float32), top_k=2)
    assert len(results) == 2
    # Each entry is a (CaseChunkRow, float) tuple
    (first_row, first_sim), (second_row, second_sim) = results
    assert first_row.ecli == "ECLI:NL:X:2025:1"
    assert second_row.ecli == "ECLI:NL:X:2025:2"
    # Perfect match similarity ≈ 1.0; orthogonal ≈ 0.0
    assert first_sim > second_sim
    assert 0.99 <= first_sim <= 1.0 + 1e-6
    assert -1e-6 <= second_sim <= 0.01
