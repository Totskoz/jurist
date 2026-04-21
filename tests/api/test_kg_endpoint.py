import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from jurist.config import Settings
from jurist.schemas import CaseChunkRow
from jurist.vectorstore import CaseStore

_SAMPLE_SNAPSHOT = {
    "generated_at": "2026-04-20T10:00:00Z",
    "source_versions": {"BWBR0005290": "2024-01-01"},
    "nodes": [
        {
            "article_id": "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248",  # noqa: E501
            "bwb_id": "BWBR0005290",
            "label": "Boek 7, Artikel 248",
            "title": "Huurverhoging",
            "body_text": "De verhuurder kan ...",
            "outgoing_refs": [
                "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel249"  # noqa: E501
            ],
        },
        {
            "article_id": "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel249",  # noqa: E501
            "bwb_id": "BWBR0005290",
            "label": "Boek 7, Artikel 249",
            "title": "Voorstel",
            "body_text": "Een voorstel ...",
            "outgoing_refs": [],
        },
    ],
    "edges": [
        {
            "from_id": "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel248",  # noqa: E501
            "to_id": "BWBR0005290/Boek7/Titeldeel4/Afdeling5/ParagraafOnderafdeling2/Sub-paragraaf1/Artikel249",  # noqa: E501
            "kind": "explicit",
            "context": None,
        }
    ],
}


def _isolate_kg(tmp_path: Path, monkeypatch) -> Settings:
    new_settings = Settings(data_dir=tmp_path)
    monkeypatch.setattr("jurist.config.settings", new_settings)
    monkeypatch.setattr("jurist.api.app.settings", new_settings)
    return new_settings


def _write_kg(tmp_path: Path) -> Path:
    p = tmp_path / "kg" / "huurrecht.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_SAMPLE_SNAPSHOT), encoding="utf-8")
    return p


def _seed_lance(tmp_path: Path) -> None:
    """Create a non-empty LanceDB so the M3b lifespan gate passes."""
    store = CaseStore(tmp_path / "lancedb" / "cases.lance")
    store.open_or_create()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=np.zeros(1024, dtype=np.float32).tolist(), url="u",
    )])


class _NoOpEmbedder:
    """Stub that satisfies the Embedder interface without loading bge-m3."""
    def __init__(self, model_name: str) -> None:
        pass

    def encode(self, texts, *, batch_size=32):
        return np.zeros((len(texts), 1024), dtype=np.float32)


def test_api_kg_returns_loaded_nodes_and_edges(tmp_path: Path, monkeypatch):
    _isolate_kg(tmp_path, monkeypatch)
    _write_kg(tmp_path)
    _seed_lance(tmp_path)

    from jurist.api import app as app_module

    # Prevent bge-m3 cold-load (2.3 GB) during unit test.
    monkeypatch.setattr(app_module, "Embedder", _NoOpEmbedder)

    with TestClient(app_module.app) as client:
        resp = client.get("/api/kg")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["nodes"]) == 2
        assert len(body["edges"]) == 1
        assert body["nodes"][0]["article_id"].startswith("BWBR0005290/")


def test_api_startup_hard_fails_on_missing_kg(tmp_path: Path, monkeypatch):
    _isolate_kg(tmp_path, monkeypatch)
    # No KG file written — lifespan should raise RuntimeError

    from jurist.api.app import app

    with pytest.raises(RuntimeError, match="KG not found"):
        with TestClient(app):
            pass


def test_api_startup_hard_fails_on_corrupt_kg(tmp_path: Path, monkeypatch):
    """Malformed JSON at kg_path → RuntimeError with re-run hint."""
    _isolate_kg(tmp_path, monkeypatch)
    kg_path = tmp_path / "kg" / "huurrecht.json"
    kg_path.parent.mkdir(parents=True, exist_ok=True)
    kg_path.write_text("{ not valid json at all", encoding="utf-8")

    from jurist.api.app import app

    with pytest.raises(RuntimeError, match="failed to load"):
        with TestClient(app):
            pass


def test_api_startup_hard_fails_on_schema_invalid_kg(tmp_path: Path, monkeypatch):
    """JSON that parses but fails KGSnapshot validation → RuntimeError with re-run hint."""
    _isolate_kg(tmp_path, monkeypatch)
    kg_path = tmp_path / "kg" / "huurrecht.json"
    kg_path.parent.mkdir(parents=True, exist_ok=True)
    # Missing required fields (generated_at, source_versions)
    kg_path.write_text('{"nodes": [], "edges": []}', encoding="utf-8")

    from jurist.api.app import app

    with pytest.raises(RuntimeError, match="failed to load"):
        with TestClient(app):
            pass
