"""Use concept-omcp as an in-process library — no MCP, no subprocess.

`ConceptStore` is the runtime core and knows nothing about MCP. Import it directly to
embed semantic concept search in a Python program. Requires artifacts built once with
`concept-omcp build --omop <athena_dir>` (or set CONCEPT_OMCP_ARTIFACT_DIR to point at them).

    python examples/in_process_search.py "type 2 diabetes mellitus" Condition
"""

from __future__ import annotations

import sys

from concept_omcp import ConceptStore, settings


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else "type 2 diabetes mellitus"
    domain = sys.argv[2] if len(sys.argv) > 2 else None

    # Context-manager: closes the SQLite connection on exit.
    with ConceptStore.load(settings) as store:
        matches = store.search_concepts(query, domain_filter=domain, top_k=5, min_similarity=0.3)
        print(f"search_concepts({query!r}, domain_filter={domain!r}):")
        for m in matches:
            print(f"  [{m.similarity_score:.3f}] {m.concept_id:>9}  {m.concept_name}  ({m.domain_id})")

        if matches:
            top = matches[0]
            one = store.get_concept_by_id(top.concept_id)
            print(f"\nget_concept_by_id({top.concept_id}): {one.concept_name} parent={one.parent_concept_id}")
            print(f"  relationship_types: {one.relationship_types[:5]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
