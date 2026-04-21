"""Tests for Embedder with a mocked SentenceTransformer."""
from __future__ import annotations

import numpy as np


class _FakeST:
    """Stand-in for sentence_transformers.SentenceTransformer."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.calls: list[dict] = []

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        convert_to_numpy: bool,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        self.calls.append({"batch_size": batch_size, "n": len(texts)})
        # Deterministic 1024-d vectors based on text length hash.
        vecs = np.zeros((len(texts), 1024), dtype=np.float32)
        for i, t in enumerate(texts):
            vecs[i, 0] = float(len(t))
            vecs[i, 1] = float(hash(t) % 1000)
        if normalize_embeddings:
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vecs = vecs / norms
        return vecs


def test_embedder_returns_1024d_unit_norm(monkeypatch) -> None:
    import jurist.embedding as embedding_mod
    monkeypatch.setattr(embedding_mod, "SentenceTransformer", _FakeST)
    emb = embedding_mod.Embedder(model_name="fake-model")
    vectors = emb.encode(["hallo", "wereld"])
    assert vectors.shape == (2, 1024)
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_embedder_passes_batch_size(monkeypatch) -> None:
    import jurist.embedding as embedding_mod
    monkeypatch.setattr(embedding_mod, "SentenceTransformer", _FakeST)
    emb = embedding_mod.Embedder(model_name="fake-model")
    emb.encode(["a", "b", "c"], batch_size=2)
    assert emb._model.calls == [{"batch_size": 2, "n": 3}]


def test_embedder_empty_input_returns_empty_array(monkeypatch) -> None:
    import jurist.embedding as embedding_mod
    monkeypatch.setattr(embedding_mod, "SentenceTransformer", _FakeST)
    emb = embedding_mod.Embedder(model_name="fake-model")
    vectors = emb.encode([])
    assert vectors.shape == (0, 1024)
