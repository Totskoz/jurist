"""Lifespan gate tests for M3b — LanceDB presence + Embedder wiring."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI


def _fake_settings(tmp_path: Path) -> SimpleNamespace:
    """Duck-type Settings for what the lifespan actually reads."""
    return SimpleNamespace(
        kg_path=tmp_path / "kg" / "huurrecht.json",
        lance_path=tmp_path / "lancedb" / "cases.lance",
        embed_model="BAAI/bge-m3",
        anthropic_api_key="test-key",
        model_retriever="claude-sonnet-4-6",
        model_rerank="claude-haiku-4-5-20251001",
    )


@pytest.mark.asyncio
async def test_lifespan_raises_when_lance_path_missing(tmp_path, monkeypatch) -> None:
    from jurist.api import app as app_module

    # Seed a valid KG file so the KG gate passes — the LanceDB gate is what we test.
    (tmp_path / "kg").mkdir()
    (tmp_path / "kg" / "huurrecht.json").write_text(
        '{"generated_at":"t","source_versions":{},"nodes":[],"edges":[]}',
        encoding="utf-8",
    )
    # lance_path intentionally absent.

    monkeypatch.setattr(app_module, "settings", _fake_settings(tmp_path))
    fastapi_app = FastAPI()

    with pytest.raises(RuntimeError, match="LanceDB.*missing"):
        async with app_module.lifespan(fastapi_app):
            pass


@pytest.mark.asyncio
async def test_lifespan_raises_when_lance_index_empty(tmp_path, monkeypatch) -> None:
    from jurist.api import app as app_module
    from jurist.vectorstore import CaseStore

    (tmp_path / "kg").mkdir()
    (tmp_path / "kg" / "huurrecht.json").write_text(
        '{"generated_at":"t","source_versions":{},"nodes":[],"edges":[]}',
        encoding="utf-8",
    )
    # Create an empty lance table
    (tmp_path / "lancedb").mkdir()
    store = CaseStore(tmp_path / "lancedb" / "cases.lance")
    store.open_or_create()
    # Do NOT add any rows

    monkeypatch.setattr(app_module, "settings", _fake_settings(tmp_path))
    fastapi_app = FastAPI()

    with pytest.raises(RuntimeError, match="LanceDB.*empty"):
        async with app_module.lifespan(fastapi_app):
            pass
