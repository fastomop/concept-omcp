"""Canonical data schemas shared by both ingest paths and the build step.

Defined ONCE here so column names, dtypes, and the SQLite DDL exist in exactly
one place. Every ingest path (``from_omop``, ``append_vocab``) must emit Parquet
matching ``TERMS_COLUMNS`` / ``CONCEPTS_COLUMNS``, validated by ``validate_parquet``.
"""

from __future__ import annotations

from pathlib import Path

EMBEDDING_DIM = 1024

# One row per term-vector (flat-per-term: each concept_name + synonym is a row).
# row_id is dense 0..N-1 and IS the turbovec id and the artifact ordering.
TERMS_COLUMNS: dict[str, str] = {
    "row_id": "int64",
    "concept_id": "int64",
    "term_text": "string",
    "is_primary": "bool",
    "embedding": "list<float32>[1024]",
}

# One row per unique concept (metadata + denormalized relationships).
CONCEPTS_COLUMNS: dict[str, str] = {
    "concept_id": "int64",
    "concept_name": "string",
    "domain_id": "string",
    "vocabulary_id": "string",
    "standard_concept": "string",
    "concept_class_id": "string",
    "concept_code": "string",
    "valid_start_date": "string",
    "valid_end_date": "string",
    "invalid_reason": "string",
    "parent_concept_id": "string",
    "relationship_types": "string",  # JSON array
    "ancestor_concepts": "string",  # JSON array (persisted, not surfaced in ConceptMatch)
    "descendant_count": "int64",
}

# Built atomically into ARTIFACT_DIR/concepts.db. Server opens it read-only.
SQLITE_DDL = """
CREATE TABLE terms (
    row_id      INTEGER PRIMARY KEY,
    concept_id  INTEGER NOT NULL,
    term_text   TEXT NOT NULL,
    is_primary  INTEGER NOT NULL
);
CREATE INDEX idx_terms_concept ON terms(concept_id);
CREATE INDEX idx_terms_text_nocase ON terms(term_text COLLATE NOCASE);

CREATE TABLE concepts (
    concept_id         INTEGER PRIMARY KEY,
    concept_name       TEXT NOT NULL,
    domain_id          TEXT NOT NULL,
    vocabulary_id      TEXT,
    standard_concept   TEXT,
    concept_class_id   TEXT,
    concept_code       TEXT,
    valid_start_date   TEXT,
    valid_end_date     TEXT,
    invalid_reason     TEXT,
    parent_concept_id  TEXT,
    relationship_types TEXT,
    ancestor_concepts  TEXT,
    descendant_count   INTEGER
);
CREATE INDEX idx_concepts_domain ON concepts(domain_id);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def validate_parquet(terms_path: Path, concepts_path: Path, *, sample: int = 1000) -> None:
    """Assert both Parquet files match the canonical schema before the build trusts them.

    Checks column presence, embedding dim, and that a sample of embeddings is
    L2-normalized (``||v|| ~= 1``). Raises ``ValueError`` on mismatch.
    """
    import numpy as np
    import pyarrow.parquet as pq

    terms = pq.ParquetFile(terms_path)
    concepts = pq.ParquetFile(concepts_path)

    missing_terms = set(TERMS_COLUMNS) - set(terms.schema_arrow.names)
    if missing_terms:
        raise ValueError(f"terms.parquet missing columns: {sorted(missing_terms)}")
    missing_concepts = set(CONCEPTS_COLUMNS) - set(concepts.schema_arrow.names)
    if missing_concepts:
        raise ValueError(f"concepts.parquet missing columns: {sorted(missing_concepts)}")

    head = terms.read_row_group(0, columns=["embedding"]).to_pandas()["embedding"].head(sample)
    vecs = np.array([np.asarray(v, dtype=np.float32) for v in head])
    if vecs.shape[1] != EMBEDDING_DIM:
        raise ValueError(f"embedding dim {vecs.shape[1]} != expected {EMBEDDING_DIM}")
    norms = np.linalg.norm(vecs, axis=1)
    if not np.allclose(norms, 1.0, atol=1e-3):
        raise ValueError(f"embeddings not L2-normalized (norm range {norms.min():.4f}..{norms.max():.4f})")
