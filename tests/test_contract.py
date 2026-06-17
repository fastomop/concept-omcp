"""ConceptMatch must stay byte-identical to the atlas_agent contract it replaces."""

from concept_omcp.models import ConceptMatch

# The exact field set atlas_agent/models/concept_set.py exposes (order-independent).
EXPECTED_FIELDS = {
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
    "similarity_score",
    "matched_entity",
    "parent_concept_id",
    "relationship_types",
    "related_concepts",
}


def test_fields_match_contract():
    assert set(ConceptMatch.model_fields) == EXPECTED_FIELDS


def test_defaults_match_contract():
    m = ConceptMatch(
        concept_id=201826,
        concept_name="Type 2 diabetes mellitus",
        domain_id="Condition",
        vocabulary_id="SNOMED",
        standard_concept="S",
        concept_class_id="Clinical Finding",
        concept_code="44054006",
        valid_start_date="1970-01-01",
        valid_end_date="2099-12-31",
    )
    assert m.invalid_reason is None
    assert m.similarity_score == 1.0
    assert m.matched_entity == ""
    assert m.parent_concept_id is None
    assert m.relationship_types == []
    assert m.related_concepts is None


def test_similarity_score_clamped_by_validator():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ConceptMatch(
            concept_id=1,
            concept_name="x",
            domain_id="Condition",
            vocabulary_id="SNOMED",
            standard_concept="S",
            concept_class_id="c",
            concept_code="1",
            valid_start_date="1970-01-01",
            valid_end_date="2099-12-31",
            similarity_score=1.5,
        )
