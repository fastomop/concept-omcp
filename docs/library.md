# In-process library

`ConceptStore` is the runtime core and is independent of MCP. Import it directly to embed
concept search in a Python process — no subprocess, no JSON-RPC.

```python
from concept_omcp import ConceptStore, settings

with ConceptStore.load(settings) as store:
    matches = store.search_concepts(
        "type 2 diabetes mellitus",
        domain_filter="Condition",
        top_k=5,
        min_similarity=0.5,
    )
    for m in matches:
        print(f"{m.similarity_score:.3f}  {m.concept_id}  {m.concept_name}  ({m.domain_id})")

    one = store.get_concept_by_id(201826)
    related = store.find_concepts_by_relationship(["May treat"], domain_filter="Drug", limit=20)
```

`ConceptStore.load(settings)` opens the model, the turbovec index, and SQLite once
(seconds). It is a context manager — `with` (or an explicit `store.close()`) closes the
SQLite connection. The store is safe to share across threads for reads.

## `ConceptMatch`

Every method returns `ConceptMatch` (or a list of them):

| Field | Notes |
| --- | --- |
| `concept_id`, `concept_name`, `domain_id` | core identity |
| `vocabulary_id`, `standard_concept`, `concept_class_id`, `concept_code` | OMOP metadata |
| `valid_start_date`, `valid_end_date`, `invalid_reason` | validity |
| `similarity_score` | semantic score in `[0, 1]` (1.0 for id/relationship lookups) |
| `matched_entity` | which entity the match was against |
| `parent_concept_id` | direct parent (when `include_relationships`) |
| `relationship_types` | relationship types the concept participates in |

`ConceptMatch` is the **stable contract** — it is copied verbatim from the atlas-agent
package so concept-omcp's output is byte-identical to the tool it replaces. See
[examples/in_process_search.py](https://github.com/fastomop/concept-omcp/blob/main/examples/in_process_search.py)
for a runnable end-to-end example.

## Settings

`settings` is a `pydantic-settings` object; override any field via `CONCEPT_OMCP_*`
environment variables or a `.env` file. Construct your own `Settings(...)` to load from a
different `artifact_dir` within one process.
