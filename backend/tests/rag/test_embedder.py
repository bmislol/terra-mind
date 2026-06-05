"""Unit tests for app/rag/embedder.py.

The SentenceTransformer model is mocked — no model download in CI.
"""

from unittest.mock import MagicMock, patch

import numpy as np

from app.rag.embedder import Embedder


def _make_embedder(batch_size: int = 64) -> tuple[Embedder, MagicMock]:
    """Return an Embedder with a mocked SentenceTransformer."""
    mock_model = MagicMock()

    def _fake_encode(
        texts: list[str],
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray[tuple[int, int], np.dtype[np.float32]]:
        n = len(texts)
        vecs = np.random.randn(n, 384).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / norms  # type: ignore[no-any-return]

    mock_model.encode.side_effect = _fake_encode

    with patch("app.rag.embedder.SentenceTransformer", return_value=mock_model):
        emb = Embedder(batch_size=batch_size)

    return emb, mock_model


def test_embed_returns_correct_shape() -> None:
    emb, _ = _make_embedder()
    texts = ["hello world", "terraria is fun", "sword crafting"]
    result = emb.encode(texts)
    assert result.shape == (3, 384)
    assert result.dtype == np.float32


def test_embed_batching() -> None:
    emb, mock_model = _make_embedder(batch_size=64)
    texts = [f"text {i}" for i in range(200)]
    emb.encode(texts)
    # 200 texts at batch_size=64 → ceil(200/64) = 4 encode calls
    assert mock_model.encode.call_count == 4


def test_embed_normalised() -> None:
    emb, _ = _make_embedder()
    texts = ["normalize me", "and me too"]
    result = emb.encode(texts)
    norms = np.linalg.norm(result, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_embed_empty_returns_zero_array() -> None:
    emb, _ = _make_embedder()
    result = emb.encode([])
    assert result.shape == (0, 384)
