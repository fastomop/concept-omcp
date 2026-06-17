"""Approximate-nearest-neighbour layer.

turbovec sits behind a tiny ``AnnIndex`` Protocol so the candidate-generation
layer is swappable (FAISS / hnswlib) if turbovec ever stalls. The store depends
only on the Protocol, never on turbovec directly.

NOTE: turbovec's concrete Python symbols are bound lazily inside `TurbovecIndex`
and confirmed against the installed package in Phase 2 (build). Keeping every
turbovec call in this one file means an API change touches nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class AnnIndex(Protocol):
    """Minimal contract the ConceptStore needs from a vector index."""

    def search(self, query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        """Return (row_ids, scores) for the top-k nearest neighbours of `query`.

        row_ids are int64 indices into the term table / artifact ordering.
        scores are inner-product (cosine, since vectors are unit-norm) float32.
        """
        ...


class TurbovecIndex:
    """Concrete `AnnIndex` backed by a prebuilt, persisted ``TurboQuantIndex``.

    We use the positional (``TurboQuantIndex``) variant: the index returns slot
    indices in insertion order, so building in ``row_id`` order makes returned
    ids == row_ids directly (no id-map indirection).
    """

    def __init__(self, handle: object) -> None:
        self._index = handle

    @classmethod
    def load(cls, path: Path) -> "TurbovecIndex":
        import turbovec  # lazy: native dep, only needed when serving/building

        index = turbovec.TurboQuantIndex.load(str(path))
        index.prepare()  # warm rotation/centroid/SIMD caches so first search isn't slow
        return cls(index)

    def search(self, query: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
        # turbovec expects a 2-D (nq, dim) batch and returns (scores, ids) shaped (nq, k).
        q = np.ascontiguousarray(query, dtype=np.float32).reshape(1, -1)
        scores, ids = self._index.search(q, k)
        return np.asarray(ids[0], dtype=np.int64), np.asarray(scores[0], dtype=np.float32)


def build_index_streaming(batches: Iterable[np.ndarray], dim: int, path: Path, *, bit_width: int = 4) -> None:
    """Build a ``TurboQuantIndex`` by adding (n_i, dim) float32 batches in order.

    Streaming keeps peak memory at one batch + the quantized index, so a 4M-row
    corpus never needs the full ~17 GB float32 matrix resident. Used offline only.
    """
    import turbovec

    index = turbovec.TurboQuantIndex(dim=dim, bit_width=bit_width)
    for batch in batches:
        index.add(np.ascontiguousarray(batch, dtype=np.float32))
    index.write(str(path))


def build_index(vectors: np.ndarray, path: Path, *, bit_width: int = 4) -> None:
    """Build a ``TurboQuantIndex`` over `vectors` (row i == row_id i) and persist to `path`."""
    build_index_streaming([vectors], vectors.shape[1], path, bit_width=bit_width)


def append_index(existing_path: Path, new_vectors: np.ndarray, out_path: Path | None = None) -> None:
    """Append (n, dim) float32 vectors to a built index at slots >= its current length.

    Loads the existing ``TurboQuantIndex``, adds the new vectors IN ORDER (slot == row_id
    continues from the current length), and writes to ``out_path`` (default: in place).
    The 4-bit codebook tolerates appends without re-fitting — verified on the full 4.5M
    index (appended vectors self-return at their new slots; existing recall unchanged),
    so new vocab (Visit/Device/source codes) can be added without re-embedding the corpus.
    """
    import turbovec

    index = turbovec.TurboQuantIndex.load(str(existing_path))
    index.add(np.ascontiguousarray(new_vectors, dtype=np.float32))
    index.write(str(out_path or existing_path))
