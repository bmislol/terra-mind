"""Local MiniLM embedding wrapper (D-004: all-MiniLM-L6-v2, 384-dim)."""

from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_DIM = 384
_DEFAULT_BATCH = 64


class Embedder:
    def __init__(
        self, model_name: str = _MODEL_NAME, batch_size: int = _DEFAULT_BATCH
    ) -> None:
        self._model: SentenceTransformer = SentenceTransformer(model_name)
        self._batch_size = batch_size
        self.model_name = model_name
        self.dim = _DIM

    def encode(
        self, texts: list[str]
    ) -> np.ndarray[tuple[int, int], np.dtype[np.float32]]:
        """Embed a list of strings. Returns float32 ndarray of shape (n, 384).

        Texts are processed in batches of self._batch_size.  MiniLM outputs
        are L2-normalised, so cosine similarity == inner product.
        """
        if not texts:
            return np.zeros((0, _DIM), dtype=np.float32)

        all_vecs: list[np.ndarray[tuple[int, int], np.dtype[np.float32]]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            vecs: np.ndarray[tuple[int, int], np.dtype[np.float32]] = (
                self._model.encode(
                    batch,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            )
            all_vecs.append(vecs)

        return np.vstack(all_vecs).astype(np.float32)
