"""Shared pytest configuration."""
import tempfile
from pathlib import Path

import numpy as np
import pytest

from jurist.config import RunContext
from jurist.kg.networkx_kg import NetworkXKG
from jurist.schemas import ArticleNode, CaseChunkRow, KGSnapshot
from jurist.vectorstore import CaseStore
from tests.fixtures.mock_llm import MockAnthropicClient


class _NoOpEmbedder:
    def encode(self, texts, *, batch_size=32):
        return np.zeros((len(texts), 1024), dtype=np.float32)


def _minimal_case_store() -> CaseStore:
    tmp = Path(tempfile.mkdtemp()) / "cases.lance"
    store = CaseStore(tmp)
    store.open_or_create()
    store.add_rows([CaseChunkRow(
        ecli="ECLI:NL:STUB:1", chunk_idx=0, court="Rb", date="2025-01-01",
        zaaknummer="z", subject_uri="u", modified="2025-01-01",
        text="t", embedding=np.zeros(1024, dtype=np.float32).tolist(), url="u",
    )])
    return store


@pytest.fixture
def minimal_ctx_factory():
    """Returns a callable that builds a RunContext with a tiny KG, the
    supplied script, and no-op case_store + embedder. Use
    `ctx = factory(script)` in tests."""

    def _make(script):
        nodes = [
            ArticleNode(
                article_id="A", bwb_id="BWBX", label="Art A", title="T",
                body_text="body", outgoing_refs=[],
            ),
        ]
        snap = KGSnapshot(generated_at="t", source_versions={}, nodes=nodes, edges=[])
        kg = NetworkXKG.from_snapshot(snap)
        mock = MockAnthropicClient(script)
        return RunContext(
            kg=kg, llm=mock,
            case_store=_minimal_case_store(), embedder=_NoOpEmbedder(),
        )

    return _make
