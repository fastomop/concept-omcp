"""concept-omcp: semantic, relationship-aware OMOP concept search over MCP.

Public API for in-process consumers (e.g. the Agno hot batch path), which can
import the store directly and skip MCP entirely::

    from concept_omcp import ConceptStore, settings
    store = ConceptStore.load(settings)
    matches = store.search_concepts("type 2 diabetes mellitus", domain_filter="Condition")
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from .models import ConceptMatch, RelatedConcept
from .settings import Settings, settings
from .store import ConceptStore

try:
    __version__ = _version("concept-omcp")  # single source of truth: pyproject [project].version
except PackageNotFoundError:  # running from source without an install
    __version__ = "0.1.0"

__all__ = ["ConceptMatch", "RelatedConcept", "ConceptStore", "Settings", "settings", "__version__"]
