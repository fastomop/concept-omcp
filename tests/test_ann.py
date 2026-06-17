"""Integration: real turbovec round-trip through the AnnIndex wrapper.

Marked `integration` because it needs the turbovec native dependency installed.
Run with:  pytest tests/test_ann.py -m integration
"""

import numpy as np
import pytest

from concept_omcp.ann import TurbovecIndex, build_index

pytestmark = pytest.mark.integration


def test_build_load_search_roundtrip(tmp_path):
    rng = np.random.default_rng(0)
    vectors = rng.standard_normal((6, 8)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    path = tmp_path / "index.turbovec"
    build_index(vectors, path, bit_width=4)

    index = TurbovecIndex.load(path)
    ids, scores = index.search(vectors[2], k=3)

    assert ids.shape == (3,) and scores.shape == (3,)
    assert int(ids[0]) == 2  # an exact vector ranks itself first
    assert scores[0] > 0.9
