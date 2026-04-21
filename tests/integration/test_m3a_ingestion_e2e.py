"""M3a end-to-end: live rechtspraak.nl + real bge-m3.

Gated on RUN_E2E=1 to avoid token/time cost on default test runs.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_E2E"),
    reason="RUN_E2E=1 required (hits network + downloads ~2.3 GB on first run)",
)


def test_small_live_ingest_end_to_end(tmp_path: Path) -> None:
    from jurist.ingest import caselaw

    result = caselaw.run_ingest(
        profile="huurrecht",
        since="2025-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        max_list=10,
        refresh=False,
        verbose=False,
    )

    # Pipeline produced output
    assert result.listed >= 1
    assert result.fetched >= 1

    # At least one survived the keyword fence (2025 verbintenissenrecht corpus
    # has plenty of huur mentions — but we don't hard-assert >0 here to allow
    # for edge days when max-list=10 samples all miss; instead, if zero
    # survived, check that chunks+embedded are also zero (consistent state).
    if result.filter_passed == 0:
        assert result.chunks_written == 0
    else:
        assert result.chunks_written >= 1
        assert result.embedded == result.chunks_written


def test_idempotent_rerun(tmp_path: Path) -> None:
    from jurist.ingest import caselaw

    r1 = caselaw.run_ingest(
        profile="huurrecht",
        since="2025-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        max_list=5,
        refresh=False,
        verbose=False,
    )
    r2 = caselaw.run_ingest(
        profile="huurrecht",
        since="2025-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        max_list=5,
        refresh=False,
        verbose=False,
    )
    # r2 should add no new rows (all ECLIs in cache + index).
    assert r2.unique_eclis_added == 0
    assert r2.chunks_written == 0
    assert r2.unique_eclis == r1.unique_eclis


def test_bge_m3_determinism() -> None:
    """Parent spec §11 M3 requirement: same input → same embedding."""
    from jurist.embedding import Embedder

    emb = Embedder()  # default BAAI/bge-m3
    v1 = emb.encode(["huurverhoging per jaar"])
    v2 = emb.encode(["huurverhoging per jaar"])
    assert np.array_equal(v1, v2), "bge-m3 embeddings must be bit-equal across runs"
    # Sanity: 1024-d unit-norm
    assert v1.shape == (1, 1024)
    assert abs(np.linalg.norm(v1) - 1.0) < 1e-5
