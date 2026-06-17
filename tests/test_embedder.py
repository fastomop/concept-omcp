"""Embedder normalization invariant (the load-bearing fix)."""

import numpy as np
import pytest

from concept_omcp.embedder import _as_unit_f32


def test_as_unit_f32_normalizes_rows():
    vecs = np.array([[3.0, 4.0], [0.0, 2.0]], dtype=np.float64)
    out = _as_unit_f32(vecs)
    assert out.dtype == np.float32
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), [1.0, 1.0], atol=1e-6)


def test_as_unit_f32_handles_1d_and_zero():
    out = _as_unit_f32(np.array([0.0, 0.0, 0.0], dtype=np.float32))
    assert out.shape == (1, 3)
    assert np.all(np.isfinite(out))  # zero vector must not produce NaNs


@pytest.mark.integration
def test_real_model_encode_is_unit_norm():
    from concept_omcp.embedder import Embedder

    emb = Embedder("abhinand/MedEmbed-large-v0.1", expected_dim=1024)
    v = emb.encode_one("type 2 diabetes mellitus")
    assert v.shape == (1024,)
    np.testing.assert_allclose(np.linalg.norm(v), 1.0, atol=1e-3)
