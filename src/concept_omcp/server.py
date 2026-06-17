"""FastMCP server — a thin skin over a shared ConceptStore.

No business logic lives here: every tool is a wrapper that calls the store and
serializes ``ConceptMatch`` to JSON. Mirrors the omcp_server convention
(`@mcp_app.tool`) but without the frame-inspection decorator — a small Langfuse
span context manager does the same job, readably.

Replaces omcp_server's `Lookup_Drug`/`Lookup_Condition`: `search_concepts` with a
`domain_filter` subsumes both, and adds true semantic + relationship-aware search.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .logging import get_logger
from .settings import settings
from .store import ConceptStore

_logger = get_logger("concept_omcp.server")

mcp_app = FastMCP(
    "OMOP Concept Search",
    host=settings.host,
    port=settings.port,
    instructions=(
        "Semantic, relationship-aware search over the OMOP standardized vocabularies. "
        "Use search_concepts for clinical-term lookup (optionally restrict with domain_filter ∈ "
        "Condition|Drug|Procedure|Measurement|Observation); get_concept_by_id for a known concept_id; "
        "find_concepts_by_relationship to list concepts participating in given relationship types."
    ),
)

_store: Optional[ConceptStore] = None
_store_lock = threading.Lock()


def get_store() -> ConceptStore:
    """Return the process-wide store, loading artifacts once on first use.

    Double-checked locking: the lock is only contended on the very first call, so
    concurrent tool invocations don't each trigger a (slow, memory-heavy) load.
    """
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ConceptStore.load(settings)
    return _store


@contextmanager
def _span(name: str, **inputs: object):
    """Minimal Langfuse span; a no-op when langfuse (the `[observability]` extra)
    isn't installed/configured. The except guards ONLY span setup — exceptions in
    the wrapped body propagate normally (and are recorded by an active span)."""
    try:
        from langfuse import get_client

        client = get_client()
    except Exception:
        client = None

    if client is None:
        yield
        return
    with client.start_as_current_span(name=name, input=inputs):
        yield


def _dump(matches: list) -> str:
    return json.dumps([m.model_dump() for m in matches], indent=2)


@mcp_app.tool(
    name="search_concepts",
    description=(
        "Semantically search OMOP concepts for a clinical term and return the best matches with full "
        "metadata and relationship data. Use domain_filter (Condition|Drug|Procedure|Measurement|Observation) "
        "to restrict to a domain. Returns a JSON list of concept matches sorted by similarity."
    ),
)
def search_concepts(
    query_text: str,
    domain_filter: Optional[str] = None,
    top_k: int = 10,
    min_similarity: float = 0.5,
    include_relationships: bool = True,
) -> str:
    with _span("search_concepts", query_text=query_text, domain_filter=domain_filter):
        return _dump(
            get_store().search_concepts(
                query_text=query_text,
                domain_filter=domain_filter,
                top_k=top_k,
                min_similarity=min_similarity,
                include_relationships=include_relationships,
            )
        )


@mcp_app.tool(
    name="get_concept_by_id",
    description="Look up a single OMOP concept by its concept_id, including its parent and relationship types. "
    "Returns a JSON concept match, or null if not found.",
)
def get_concept_by_id(concept_id: int, include_relationships: bool = True) -> str:
    with _span("get_concept_by_id", concept_id=concept_id):
        match = get_store().get_concept_by_id(concept_id, include_relationships=include_relationships)
        return json.dumps(match.model_dump() if match else None, indent=2)


@mcp_app.tool(
    name="find_concepts_by_relationship",
    description="Find OMOP concepts that participate in any of the given relationship types "
    "(e.g. ['May treat', 'Has manifestation']), optionally restricted to a domain. Returns a JSON list.",
)
def find_concepts_by_relationship(
    relationship_types: list[str],
    domain_filter: Optional[str] = None,
    limit: int = 50,
) -> str:
    with _span("find_concepts_by_relationship", relationship_types=relationship_types):
        return _dump(
            get_store().find_concepts_by_relationship(
                relationship_types=relationship_types, domain_filter=domain_filter, limit=limit
            )
        )


def serve(transport: str | None = None) -> None:
    """Load artifacts once, then serve over the configured transport (stdio by default).

    In stdio mode nothing may be written to stdout except JSON-RPC, so logging is
    configured to stderr and the artifact load (which logs only to stderr) happens
    before the transport loop starts.
    """
    from .logging import setup_logging

    setup_logging(level=settings.log_level, log_file=settings.log_file, log_format=settings.log_format)
    resolved = transport or settings.transport
    _logger.info("Starting MCP server (transport=%s)", resolved)
    get_store()  # fail fast at startup if artifacts are missing/mismatched
    mcp_app.run(transport=resolved)
