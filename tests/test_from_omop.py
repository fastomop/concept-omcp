"""Tests for the Bring-Your-Own-Vocab build path (build/from_omop.py).

Two tiers:
  * Hermetic parsing tests exercise ``_load_omop`` directly — no model, no pyarrow,
    no turbovec. They cover the genuinely-new derivation logic (domain/standard
    filtering, synonym dedup + English-only, relationship_types, parent/ancestor/
    descendant_count) against the committed Athena CSV fixture.
  * Integration tests run the full ``build_parquet_from_omop`` (+ downstream
    ``build_artifacts.build`` and ``ConceptStore``) with a deterministic fake
    embedder; they need pyarrow + turbovec and are marked ``integration``.
"""

import json
import zlib
from pathlib import Path

import numpy as np
import pytest

from concept_omcp.build import from_omop

FIX = Path(__file__).parent / "fixtures" / "athena"
DIM = 1024

# Expected kept concepts, in CONCEPT.csv file order (Visit dropped by domain,
# the non-standard "Legacy diabetes term" dropped by standard_concept != 'S').
KEPT_ORDER = [201826, 1503297, 1112807, 4048225, 3004410, 443238]


def _unit_vectors(texts, dim=DIM):
    """Deterministic unit vectors keyed by text (stable across processes/runs)."""
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        rng = np.random.default_rng(zlib.crc32(t.encode("utf-8")))
        v = rng.standard_normal(dim).astype(np.float32)
        out[i] = v / np.linalg.norm(v)
    return out


# ------------------------------------------------------------------ hermetic


def test_load_omop_filters_and_terms():
    concepts, terms = from_omop._load_omop(FIX, set(from_omop._DEFAULT_DOMAINS), None)

    # Visit (domain) + non-standard concept excluded; 6 concepts kept, in file order.
    assert [c[0] for c in concepts] == KEPT_ORDER

    # 9 terms: 6 primary + 3 synonyms; dense row_ids; dup-of-name + non-English dropped.
    assert [(r, cid, txt, prim) for (r, cid, txt, prim) in terms] == [
        (0, 201826, "Type 2 diabetes mellitus", 1),
        (1, 201826, "T2DM", 0),
        (2, 1503297, "Metformin", 1),
        (3, 1503297, "Glucophage", 0),
        (4, 1112807, "Aspirin", 1),
        (5, 4048225, "Appendectomy", 1),
        (6, 3004410, "Hemoglobin A1c", 1),
        (7, 3004410, "HbA1c", 0),
        (8, 443238, "Diabetes mellitus", 1),
    ]


def test_load_omop_relationships_and_hierarchy():
    concepts, _ = from_omop._load_omop(FIX, set(from_omop._DEFAULT_DOMAINS), None)
    cols = list(__import__("concept_omcp.build.schema", fromlist=["CONCEPTS_COLUMNS"]).CONCEPTS_COLUMNS)
    by_id = {row[0]: dict(zip(cols, row)) for row in concepts}

    t2dm = by_id[201826]
    # sorted distinct outgoing relationship_ids; "Subsumes"/"May treat" belong to other concepts.
    assert json.loads(t2dm["relationship_types"]) == ["Has finding", "Is a"]
    assert t2dm["parent_concept_id"] == "443238"  # CONCEPT_ANCESTOR min_levels == 1
    assert json.loads(t2dm["ancestor_concepts"]) == [443238]
    assert t2dm["descendant_count"] == 0

    # Deprecated relationship (invalid_reason='D') excluded; only the valid "May treat" remains.
    assert json.loads(by_id[1112807]["relationship_types"]) == ["May treat"]
    assert json.loads(by_id[1503297]["relationship_types"]) == ["May treat"]

    diabetes = by_id[443238]
    assert json.loads(diabetes["relationship_types"]) == ["Subsumes"]
    assert diabetes["descendant_count"] == 2  # 201826 (lvl1) + 4048225 (lvl2)
    assert diabetes["parent_concept_id"] is None


def test_load_omop_domain_and_vocabulary_filters():
    # Restrict to one domain.
    concepts, terms = from_omop._load_omop(FIX, {"Drug"}, None)
    assert {c[0] for c in concepts} == {1503297, 1112807}

    # Restrict by vocabulary_id.
    concepts, _ = from_omop._load_omop(FIX, set(from_omop._DEFAULT_DOMAINS), {"LOINC"})
    assert {c[0] for c in concepts} == {3004410}


# ----------------------------------------------------------------- integration


@pytest.mark.integration
def test_build_parquet_then_artifacts_then_store(tmp_path, monkeypatch):
    import sqlite3

    from concept_omcp.ann import TurbovecIndex
    from concept_omcp.build import build_artifacts
    from concept_omcp.store import ConceptStore

    class FakeEmbedder:
        def __init__(self, model, dim, device=None):
            self.expected_dim = dim
            self.device = "cpu"

        def encode(self, texts, batch_size=256):
            return _unit_vectors(texts, self.expected_dim)

        def encode_one(self, text):
            return self.encode([text])[0]

    monkeypatch.setattr(from_omop, "Embedder", FakeEmbedder)

    pq_dir = tmp_path / "pq"
    from_omop.build_parquet_from_omop(str(FIX), str(pq_dir), chunk_rows=4)
    assert (pq_dir / "terms.parquet").exists() and (pq_dir / "concepts.parquet").exists()
    assert not (pq_dir / ".emb_ckpt").exists()  # checkpoints cleaned on success

    art = tmp_path / "artifacts"
    build_artifacts.build(parquet_dir=str(pq_dir), artifact_dir=str(art))
    meta = json.loads((art / "meta.json").read_text())
    assert meta["n_terms"] == "9" and meta["n_concepts"] == "6"

    # descendant_count persisted to SQLite (not surfaced in ConceptMatch).
    conn = sqlite3.connect(f"file:{art / 'concepts.db'}?mode=ro", uri=True)
    assert conn.execute("SELECT descendant_count FROM concepts WHERE concept_id=443238").fetchone()[0] == 2

    store = ConceptStore(FakeEmbedder("m", DIM), TurbovecIndex.load(art / "index.turbovec"), conn, overfetch_min=9)

    # Query == the Metformin primary vector -> concept 1503297 on top.
    metformin_vec = _unit_vectors(["Metformin"])[0]
    monkeypatch.setattr(store, "_embedder", type("E", (), {"encode_one": lambda self, t: metformin_vec})())
    hits = store.search_concepts("metformin", top_k=3, min_similarity=0.3, use_hybrid_search=False)
    assert hits[0].concept_id == 1503297

    one = store.get_concept_by_id(201826)
    assert one.parent_concept_id == "443238"
    assert one.relationship_types == ["Has finding", "Is a"]
    assert {m.concept_id for m in store.find_concepts_by_relationship(["May treat"])} == {1503297, 1112807}
    store.close()


@pytest.mark.integration
def test_embedding_is_resumable(tmp_path, monkeypatch):
    """An interrupted build reuses on-disk checkpoints instead of re-embedding."""
    state = {"texts": 0, "fail_after": None}

    class FlakyEmbedder:
        def __init__(self, model, dim, device=None):
            self.expected_dim = dim
            self.device = "cpu"

        def encode(self, texts, batch_size=256):
            state["texts"] += len(texts)
            if state["fail_after"] is not None and state["texts"] > state["fail_after"]:
                raise RuntimeError("simulated interruption")
            return _unit_vectors(texts, self.expected_dim)

    monkeypatch.setattr(from_omop, "Embedder", FlakyEmbedder)
    pq_dir = tmp_path / "pq"

    # Run 1: fail after the first chunk of 4 is checkpointed.
    state["fail_after"] = 4
    with pytest.raises(RuntimeError):
        from_omop.build_parquet_from_omop(str(FIX), str(pq_dir), chunk_rows=4)
    assert (pq_dir / ".emb_ckpt").exists()  # checkpoints survive the crash

    # Run 2: resume — only the un-checkpointed terms (5 of 9) are re-embedded.
    state["fail_after"] = None
    state["texts"] = 0
    from_omop.build_parquet_from_omop(str(FIX), str(pq_dir), chunk_rows=4)
    assert state["texts"] == 5
    assert (pq_dir / "terms.parquet").exists()
    assert not (pq_dir / ".emb_ckpt").exists()
