"""ConceptStore logic via fakes — no embedding model, no turbovec required.

Exercises the load-bearing search behaviours: dedup-by-concept (keep max score),
min_similarity filter, post-search domain filter, and the hybrid exact-text
fallback.
"""

import json
import sqlite3

import numpy as np
import pytest

from concept_omcp.build.schema import SQLITE_DDL
from concept_omcp.store import ConceptStore


class FakeEmbedder:
    def encode_one(self, text: str) -> np.ndarray:
        return np.zeros(4, dtype=np.float32)  # value irrelevant; FakeAnn ignores it


class FakeAnn:
    """Returns a fixed candidate list (row_ids, scores) regardless of the query."""

    def __init__(self, row_ids, scores):
        self._row_ids = np.asarray(row_ids, dtype=np.int64)
        self._scores = np.asarray(scores, dtype=np.float32)

    def search(self, query, k):
        return self._row_ids[:k], self._scores[:k]


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SQLITE_DDL)
    terms = [
        (0, 100, "Type 2 diabetes mellitus", 1),
        (1, 100, "T2DM", 0),
        (2, 200, "Metformin", 1),
        (3, 300, "Aspirin", 1),
    ]
    conn.executemany("INSERT INTO terms VALUES (?,?,?,?)", terms)
    concepts = [
        (
            100,
            "Type 2 diabetes mellitus",
            "Condition",
            "SNOMED",
            "S",
            "Clinical Finding",
            "44054006",
            "1970-01-01",
            "2099-12-31",
            None,
            "73211009",
            json.dumps(["Is a", "May treat"]),
            "[]",
            0,
        ),
        (
            200,
            "Metformin",
            "Drug",
            "RxNorm",
            "S",
            "Ingredient",
            "6809",
            "1970-01-01",
            "2099-12-31",
            None,
            None,
            json.dumps(["May treat"]),
            "[]",
            0,
        ),
        (
            300,
            "Aspirin",
            "Drug",
            "RxNorm",
            "S",
            "Ingredient",
            "1191",
            "1970-01-01",
            "2099-12-31",
            None,
            None,
            json.dumps([]),
            "[]",
            0,
        ),
    ]
    conn.executemany("INSERT INTO concepts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", concepts)
    conn.commit()
    return conn


@pytest.fixture
def store() -> ConceptStore:
    ann = FakeAnn(row_ids=[0, 1, 2, 3], scores=[0.9, 0.85, 0.7, 0.4])
    return ConceptStore(FakeEmbedder(), ann, _make_db(), overfetch_min=4)


def test_dedup_and_min_similarity(store):
    # row1 (concept 100) is a dup of row0 -> dropped; row3 (0.4) below min 0.5 -> dropped.
    out = store.search_concepts("diabetes", top_k=5, min_similarity=0.5, use_hybrid_search=False)
    ids = [m.concept_id for m in out]
    assert ids == [100, 200]
    assert out[0].similarity_score == pytest.approx(0.9)
    assert out[0].relationship_types == ["Is a", "May treat"]


def test_post_search_domain_filter(store):
    out = store.search_concepts("diabetes", domain_filter="Drug", top_k=5, min_similarity=0.5, use_hybrid_search=False)
    assert [m.concept_id for m in out] == [200]


def test_hybrid_exact_text_fallback(store):
    # ANN returns nothing useful; exact term match on "Aspirin" should backfill at 0.95.
    empty_ann = FakeAnn(row_ids=[], scores=[])
    s = ConceptStore(FakeEmbedder(), empty_ann, _make_db(), overfetch_min=4)
    out = s.search_concepts("Aspirin", top_k=5, use_hybrid_search=True)
    assert 300 in [m.concept_id for m in out]
    assert out[0].similarity_score == pytest.approx(0.95)


def test_get_concept_by_id(store):
    m = store.get_concept_by_id(200)
    assert m is not None and m.concept_name == "Metformin"
    assert store.get_concept_by_id(999) is None


def test_find_by_relationship(store):
    out = store.find_concepts_by_relationship(["May treat"])
    assert {m.concept_id for m in out} == {100, 200}
