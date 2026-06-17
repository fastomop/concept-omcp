"""FastMCP tool wrappers — hermetic, via a fake store injected into the module.

The three ``@mcp_app.tool`` functions stay plain callables, so we drive them
directly with a fake ConceptStore and assert they serialize ``ConceptMatch`` to
JSON. No artifacts, no model. langfuse (the ``[observability]`` extra) is absent
in the dev env, so ``_span`` is exercised on its no-op path.
"""

import json

import pytest

from concept_omcp import server
from concept_omcp.models import ConceptMatch


def _match(concept_id: int, name: str, domain: str = "Condition") -> ConceptMatch:
    return ConceptMatch(
        concept_id=concept_id,
        concept_name=name,
        domain_id=domain,
        vocabulary_id="SNOMED",
        standard_concept="S",
        concept_class_id="Clinical Finding",
        concept_code=str(concept_id),
        valid_start_date="1970-01-01",
        valid_end_date="2099-12-31",
        similarity_score=0.9,
    )


class FakeStore:
    """Records calls and returns canned ConceptMatch lists — no ANN, no SQLite."""

    def __init__(self) -> None:
        self.calls: list = []

    def search_concepts(self, **kw):
        self.calls.append(("search", kw))
        return [_match(100, "Type 2 diabetes mellitus"), _match(200, "Metformin", "Drug")]

    def get_concept_by_id(self, concept_id, include_relationships=True):
        self.calls.append(("get", concept_id))
        return _match(200, "Metformin", "Drug") if concept_id == 200 else None

    def find_concepts_by_relationship(self, **kw):
        self.calls.append(("rel", kw))
        return [_match(100, "Type 2 diabetes mellitus")]


@pytest.fixture
def fake_store(monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(server, "_store", store)  # reverted to None after the test
    return store


def test_get_store_returns_cached_without_loading(fake_store):
    # _store is preset, so get_store() must return it without a (heavy) load.
    assert server.get_store() is fake_store


def test_search_concepts_serializes_and_threads_args(fake_store):
    out = json.loads(server.search_concepts("diabetes", domain_filter="Condition", top_k=3))
    assert [m["concept_id"] for m in out] == [100, 200]
    assert out[0]["concept_name"] == "Type 2 diabetes mellitus"
    kind, kw = fake_store.calls[0]
    assert kind == "search"
    assert kw["query_text"] == "diabetes"
    assert kw["domain_filter"] == "Condition"
    assert kw["top_k"] == 3


def test_get_concept_by_id_found(fake_store):
    out = json.loads(server.get_concept_by_id(200))
    assert out["concept_id"] == 200
    assert out["concept_name"] == "Metformin"


def test_get_concept_by_id_missing_returns_null(fake_store):
    assert json.loads(server.get_concept_by_id(999)) is None


def test_find_concepts_by_relationship_serializes(fake_store):
    out = json.loads(server.find_concepts_by_relationship(["May treat"], domain_filter="Condition", limit=10))
    assert [m["concept_id"] for m in out] == [100]
    kind, kw = fake_store.calls[0]
    assert kind == "rel"
    assert kw["relationship_types"] == ["May treat"]
    assert kw["limit"] == 10


def test_span_is_noop_without_langfuse():
    # No langfuse installed -> client is None -> span yields without wrapping.
    with server._span("probe", arg=1):
        pass
