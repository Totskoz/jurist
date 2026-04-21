"""bge-m3 embedding wrapper. Shared by ingester (M3a) and case retriever (M3b).

First use triggers a HuggingFace model download (~2.3 GB) to the default
`~/.cache/huggingface/hub/`. Subsequent instantiations hit the cache.
"""
from __future__ import annotations

import logging

import numpy as np
from sentence_transformers import SentenceTransformer

log = logging.getLogger(__name__)

EMBED_DIM = 1024


class Embedder:
    def __init__(self, *, model_name: str = "BAAI/bge-m3") -> None:
        log.info("Embedder: loading %s (may download on first use)", model_name)
        self._model = SentenceTransformer(model_name)
        self.model_name = model_name

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int = 32,
    ) -> np.ndarray:
        """Return (N, 1024) float32 L2-normalized embeddings.

        Empty input → (0, 1024) array.
        """
        if not texts:
            return np.zeros((0, EMBED_DIM), dtype=np.float32)
        return self._model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
