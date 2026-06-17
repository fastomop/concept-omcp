"""Integration: end-to-end build -> artifacts -> ConceptStore over real turbovec + SQLite.

Synthesizes a tiny Parquet pair (dim 1024 to satisfy the schema), runs the real
build_artifacts pipeline, then drives ConceptStore against the built index + db
with a fake embedder. Validates the whole offline+runtime path minus the model
and the CSV-parsing/embedding front of the build.

Run with:  pytest tests/test_build_pipeline.py -m integration
"""

import json
import sqlite3

import numpy as np
import pytest

pytestmark = pytest.mark.integration

DIM = 1024


def _unit(n: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, DIM)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _write_parquet(dir_, vectors):
    import pyarrow as pa
    import pyarrow.parquet as pq

    # row_id, concept_id, term_text, is_primary, embedding
    terms = pa.table(
        {
            "row_id": pa.array(range(len(vectors)), pa.int64()),
            "concept_id": pa.array([100, 100, 200, 300, 300, 400], pa.int64()),
            "term_text": pa.array(["Type 2 diabetes mellitus", "T2DM", "Metformin", "Aspirin", "ASA", "Lisinopril"]),
            "is_primary": pa.array([True, False, True, True, False, True]),
            "embedding": pa.array([v.tolist() for v in vectors], pa.list_(pa.float32(), DIM)),
        }
    )
    pq.write_table(terms, dir_ / "terms.parquet")

    def concept(cid, name, domain, rels):
        return (
            cid,
            name,
            domain,
            "SNOMED",
            "S",
            "Clinical Finding",
            str(cid),
            "1970-01-01",
            "2099-12-31",
            None,
            None,
            json.dumps(rels),
            "[]",
            0,
        )

    cols = [
        "concept_id",
        "concept_name",
        "domain_id",
        "vocabulary_id",
        "standard_concept",
        "concept_class_id",
        "concept_code",
        "valid_start_date",
        "valid_end_date",
        "invalid_reason",
        "parent_concept_id",
        "relationship_types",
        "ancestor_concepts",
        "descendant_count",
    ]
    rows = [
        concept(100, "Type 2 diabetes mellitus", "Condition", ["Is a", "May treat"]),
        concept(200, "Metformin", "Drug", ["May treat"]),
        concept(300, "Aspirin", "Drug", []),
        concept(400, "Lisinopril", "Drug", ["May treat"]),
    ]
    table = pa.table({c: [r[i] for r in rows] for i, c in enumerate(cols)})
    pq.write_table(table, dir_ / "concepts.parquet")


def test_build_then_search(tmp_path):
    from concept_omcp.ann import TurbovecIndex
    from concept_omcp.build import build_artifacts
    from concept_omcp.store import ConceptStore

    vectors = _unit(6, seed=1)
    parquet_dir = tmp_path / "pq"
    parquet_dir.mkdir()
    _write_parquet(parquet_dir, vectors)

    artifact_dir = tmp_path / "artifacts"
    build_artifacts.build(parquet_dir=str(parquet_dir), artifact_dir=str(artifact_dir))

    assert (artifact_dir / "index.turbovec").exists()
    assert (artifact_dir / "concepts.db").exists()
    meta = json.loads((artifact_dir / "meta.json").read_text())
    assert meta["n_terms"] == "6" and meta["n_concepts"] == "4"
    assert meta["embedding_dim"] == str(DIM)

    class FakeEmbedder:
        def __init__(self, vec):
            self._vec = vec

        def encode_one(self, text):
            return self._vec

    conn = sqlite3.connect(f"file:{artifact_dir / 'concepts.db'}?mode=ro", uri=True)
    ann = TurbovecIndex.load(artifact_dir / "index.turbovec")

    # Query == the Metformin vector (row 2) -> concept 200 should top the results.
    store = ConceptStore(FakeEmbedder(vectors[2]), ann, conn, overfetch_min=6)
    out = store.search_concepts("metformin", top_k=3, min_similarity=0.3, use_hybrid_search=False)
    assert out[0].concept_id == 200
    assert out[0].relationship_types == ["May treat"]

    # SQLite-backed paths
    assert store.get_concept_by_id(300).concept_name == "Aspirin"
    assert {m.concept_id for m in store.find_concepts_by_relationship(["May treat"])} == {100, 200, 400}
    # Hybrid exact-text fallback resolves a synonym row to its concept.
    hit = store.search_concepts("ASA", top_k=3, use_hybrid_search=True)
    assert 300 in {m.concept_id for m in hit}
