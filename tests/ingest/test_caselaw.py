"""Tests for the caselaw ingest orchestrator (with mocked fetch + embedder)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

# The real `fetch_content` is replaced by a stub that writes fixture files
# into the disk cache.


def _install_fake_fetch(monkeypatch, fixtures_dir: Path, cache_dir: Path) -> None:
    from jurist.ingest import caselaw_fetch

    def fake_list(**_kwargs):
        # Yield three ECLIs; caselaw.py downloads content for each.
        yield ("ECLI:NL:RBAMS:2025:1001", "2025-06-15T10:00:00Z")
        yield ("ECLI:NL:RBAMS:2025:1002", "2025-06-16T10:00:00Z")
        yield ("ECLI:NL:RBTEST:2025:9999", "2025-06-20T14:22:10Z")

    def fake_fetch(ecli: str, *, cache_dir: Path) -> Path:
        # Map fake ECLIs to committed fixtures.
        mapping = {
            "ECLI:NL:RBTEST:2025:9999": fixtures_dir / "sparse_case.xml",
        }
        real_fixtures = [p for p in fixtures_dir.glob("ECLI_*.xml")]
        # Route the two RBAMS ECLIs to the first two real fixtures (if available).
        for i, real_ecli in enumerate([
            "ECLI:NL:RBAMS:2025:1001", "ECLI:NL:RBAMS:2025:1002",
        ]):
            if i < len(real_fixtures):
                mapping[real_ecli] = real_fixtures[i]
        source = mapping[ecli]
        target = cache_dir / f"{ecli.replace(':', '_')}.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        return target

    monkeypatch.setattr(caselaw_fetch, "list_eclis", fake_list)
    monkeypatch.setattr(caselaw_fetch, "fetch_content", fake_fetch)


class _FakeEmbedder:
    def __init__(self, *_args, **_kwargs) -> None:
        self.model_name = "fake"

    def encode(self, texts: list[str], *, batch_size: int = 32) -> np.ndarray:  # noqa: ARG002
        arr = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, t in enumerate(texts):
            arr[i, 0] = float(len(t))
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "caselaw"


def test_run_ingest_end_to_end(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw

    monkeypatch.setattr(caselaw, "Embedder", _FakeEmbedder)
    _install_fake_fetch(monkeypatch, FIXTURE_DIR, tmp_path / "cases")

    result = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )

    # The sparse fixture contains "huurder" → passes fence; RBAMS real fixtures
    # may or may not, depending on what was committed. Assert on structure.
    assert result.listed == 3
    assert result.fetched >= 1
    assert result.filter_passed >= 1
    assert result.embedded == result.chunks_written
    assert result.unique_eclis == result.filter_passed


def test_run_ingest_idempotent(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw

    monkeypatch.setattr(caselaw, "Embedder", _FakeEmbedder)
    _install_fake_fetch(monkeypatch, FIXTURE_DIR, tmp_path / "cases")

    r1 = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )
    r2 = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )
    assert r2.chunks_written == 0
    assert r2.unique_eclis_added == 0
    assert r2.listed == r1.listed  # pagination re-queried; gate filters all


def test_run_ingest_refresh_wipes(tmp_path: Path, monkeypatch) -> None:
    from jurist.ingest import caselaw

    monkeypatch.setattr(caselaw, "Embedder", _FakeEmbedder)
    _install_fake_fetch(monkeypatch, FIXTURE_DIR, tmp_path / "cases")

    caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=False,
        verbose=False,
    )
    r2 = caselaw.run_ingest(
        profile="huurrecht",
        since="2024-01-01",
        cases_dir=tmp_path / "cases",
        lance_path=tmp_path / "cases.lance",
        refresh=True,
        verbose=False,
    )
    # After --refresh, we ingested fresh again.
    assert r2.chunks_written >= 1
