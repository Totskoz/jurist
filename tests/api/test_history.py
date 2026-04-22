"""Tests for /api/history — atomic-write, size caps, version gate."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jurist.api.history import router
from jurist.config import Settings


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Minimal app with only the history router mounted — no KG/Lance lifespan."""
    new_settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("jurist.api.history.settings", new_settings)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _entry(i: int) -> dict:
    return {
        "id": f"run_{i:04d}",
        "question": f"q{i}",
        "timestamp": 1_700_000_000_000 + i,
        "status": "finished",
        "snapshot": {
            "kgState": [], "edgeState": [], "traceLog": [],
            "thinkingByAgent": {}, "answerText": "", "finalAnswer": None,
            "cases": [], "resolutions": [], "citedSet": [],
        },
    }


def test_get_on_missing_file_returns_empty(client: TestClient):
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "entries": []}


def test_put_then_get_roundtrips(client: TestClient):
    body = {"version": 1, "entries": [_entry(1), _entry(2)]}
    put = client.put("/api/history", json=body)
    assert put.status_code == 200
    assert put.json() == {"ok": True}

    got = client.get("/api/history")
    assert got.status_code == 200
    assert got.json() == body


def test_put_rejects_too_many_entries(client: TestClient):
    body = {"version": 1, "entries": [_entry(i) for i in range(16)]}
    resp = client.put("/api/history", json=body)
    assert resp.status_code == 400
    assert "15" in resp.text


def test_put_rejects_wrong_version(client: TestClient):
    resp = client.put("/api/history", json={"version": 2, "entries": []})
    # Pydantic's Literal[1] → 422 at validation layer; that's fine.
    assert resp.status_code in (400, 422)


def test_get_on_wrong_version_returns_empty_default(
    client: TestClient, tmp_path: Path
):
    (tmp_path / "history.json").write_text(
        json.dumps({"version": 99, "entries": []}), encoding="utf-8"
    )
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "entries": []}


def test_get_on_corrupt_file_returns_empty_default(
    client: TestClient, tmp_path: Path
):
    (tmp_path / "history.json").write_text("{ not json", encoding="utf-8")
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "entries": []}


def test_put_atomic_write_does_not_leave_partial(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Seed a valid file.
    body = {"version": 1, "entries": [_entry(1)]}
    client.put("/api/history", json=body)

    # Patch json.dump inside the history module to raise mid-write.
    import jurist.api.history as history_mod

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(history_mod.json, "dump", boom)

    # Attempt another write — should fail.
    resp = client.put("/api/history", json={"version": 1, "entries": [_entry(2)]})
    assert resp.status_code == 500

    # Original file must still be the seeded one.
    got = json.loads((tmp_path / "history.json").read_text(encoding="utf-8"))
    assert got == body
    # No stray .tmp file.
    assert not (tmp_path / "history.json.tmp").exists()


def test_put_rejects_payload_over_5mb(client: TestClient):
    # One giant question text → pushes entry well over limit; 5 entries is enough.
    big = "x" * (2 * 1024 * 1024)  # 2 MB string
    entries = []
    for i in range(3):
        e = _entry(i)
        e["question"] = big
        entries.append(e)
    resp = client.put("/api/history", json={"version": 1, "entries": entries})
    assert resp.status_code == 413


def test_history_mounted_on_full_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The full app (with KG + Lance lifespan) also exposes /api/history."""
    import numpy as np

    from jurist.schemas import CaseChunkRow
    from jurist.vectorstore import CaseStore

    # Isolate KG + lance + history under tmp_path.
    new_settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("jurist.config.settings", new_settings)
    monkeypatch.setattr("jurist.api.app.settings", new_settings)
    monkeypatch.setattr("jurist.api.history.settings", new_settings)

    # Seed KG.
    kg_path = tmp_path / "kg" / "huurrecht.json"
    kg_path.parent.mkdir(parents=True, exist_ok=True)
    kg_path.write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "source_versions": {"BWB": "x"},
        "nodes": [], "edges": [],
    }), encoding="utf-8")

    # Seed a non-empty LanceDB.
    store = CaseStore(tmp_path / "lancedb" / "cases.lance")
    store.open_or_create()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=np.zeros(1024, dtype=np.float32).tolist(), url="u",
    )])

    from jurist.api import app as app_module

    class _NoOpEmbedder:
        def __init__(self, model_name): pass
        def encode(self, texts, *, batch_size=32):
            return np.zeros((len(texts), 1024), dtype=np.float32)

    monkeypatch.setattr(app_module, "Embedder", _NoOpEmbedder)

    with TestClient(app_module.app) as client:
        r = client.get("/api/history")
        assert r.status_code == 200
        assert r.json() == {"version": 1, "entries": []}
