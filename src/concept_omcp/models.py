"""Data contract for concept search results.

`ConceptMatch` is copied VERBATIM from the atlas-agent package
(`atlas_agent/models/concept_set.py`) so that concept-omcp's JSON output is
byte-identical to the tool it replaces. We intentionally do NOT import from
atlas_agent — that would re-couple this lean package to its dependencies. This
is a published contract, not logic, so duplication is correct.

Note: `ancestor_concepts` and `descendant_count` are persisted in SQLite for
future use (hierarchy exploration) but are deliberately NOT part of this
contract, to keep parity with the existing consumers exact.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RelatedConcept(BaseModel):
    """A concept discovered through relationship traversal."""

    concept_id: int
    concept_name: str
    domain_id: str
    relationship_type: str = Field(description="Type of relationship (e.g., 'May treat', 'Has manifestation', 'Is a')")
    relationship_direction: Literal["outgoing", "incoming"] = Field(
        description="Direction of relationship from source concept"
    )
    relevance_score: float = Field(ge=0.0, le=1.0, description="How relevant this related concept is (0-1)")
    rationale: str = Field(description="Why this relationship matters for the concept set")


class ConceptMatch(BaseModel):
    """A matched OMOP concept."""

    concept_id: int
    concept_name: str
    domain_id: str
    vocabulary_id: str
    standard_concept: str
    concept_class_id: str
    concept_code: str
    valid_start_date: str
    valid_end_date: str
    invalid_reason: Optional[str] = None
    similarity_score: Optional[float] = Field(default=1.0, ge=0.0, le=1.0, description="Semantic similarity score")
    matched_entity: Optional[str] = Field(default="", description="Which clinical entity this concept matches")

    # Relationship data (denormalized from the OMOP relationship/ancestor tables)
    parent_concept_id: Optional[str] = Field(
        default=None, description="Direct parent concept via 'Is a' or 'Subsumes' relationship"
    )
    relationship_types: List[str] = Field(
        default_factory=list, description="All relationship types this concept participates in"
    )

    # Related concepts discovered during reasoning (populated downstream, not by search)
    related_concepts: Optional[List[RelatedConcept]] = Field(
        default=None, description="Concepts discovered through relationship traversal"
    )
