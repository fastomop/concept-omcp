"""Query/term embedding — the single place text becomes a unit vector.

Both the offline build and the runtime query path use THIS class, so they can
never diverge on model or normalization. The normalization is load-bearing:
turbovec scores by inner product, so a non-unit query would produce wrong
scores. We always L2-normalize, on both the index and the query side.
"""

from __future__ import annotations

import threading

import numpy as np


class Embedder:
    """Lazy-loaded SentenceTransformer wrapper that returns L2-normalized float32.

    The SAME class encodes both the offline index (build) and the runtime query,
    so the two can never diverge on model, device-induced rounding, or
    normalization. ``device`` is auto-detected (``cuda`` → ``mps`` → ``cpu``)
    unless pinned explicitly.
    """

    def __init__(self, model_name: str, expected_dim: int, device: str | None = None) -> None:
        self.model_name = model_name
        self.expected_dim = expected_dim
        self._device = device
        self._model = None
        # SentenceTransformer.encode is not guaranteed thread-safe; serialize it.
        self._lock = threading.Lock()

    def _select_device(self) -> str:
        if self._device:
            return self._device
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
            mps = getattr(torch.backends, "mps", None)
            if mps is not None and mps.is_available():
                return "mps"
        except Exception:  # torch missing or probe failed — CPU is always valid
            pass
        return "cpu"

    @property
    def device(self) -> str:
        """The resolved torch device (loads nothing; just runs detection once)."""
        if self._device is None:
            self._device = self._select_device()
        return self._device

    def _ensure_model(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy; import lazily

            self._model = SentenceTransformer(self.model_name, device=self.device)
            # `get_sentence_embedding_dimension` was renamed to `get_embedding_dimension`;
            # prefer the new name, fall back for older sentence-transformers.
            get_dim = getattr(self._model, "get_embedding_dimension", None)
            dim = get_dim() if get_dim else self._model.get_sentence_embedding_dimension()
            if dim != self.expected_dim:
                raise ValueError(
                    f"Model {self.model_name!r} has dim {dim}, expected {self.expected_dim}. "
                    "Artifacts and query encoder must match."
                )

    def encode_one(self, text: str) -> np.ndarray:
        """Embed a single string -> (dim,) float32, L2-normalized."""
        return self.encode([text])[0]

    def encode(self, texts: list[str], batch_size: int = 256) -> np.ndarray:
        """Embed a batch -> (n, dim) float32, each row L2-normalized."""
        self._ensure_model()
        with self._lock:
            vecs = self._model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        return _as_unit_f32(np.asarray(vecs))


def _as_unit_f32(vecs: np.ndarray) -> np.ndarray:
    """Defensive: cast to float32 and re-normalize (idempotent on unit vectors)."""
    vecs = np.ascontiguousarray(vecs, dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs[None, :]
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return vecs / norms
