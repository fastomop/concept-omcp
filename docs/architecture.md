# Architecture

concept-omcp separates a small, MCP-agnostic **runtime core** from a quarantined **offline
build pipeline**. The served process never imports the build dependencies.

```
Initialise (once):  Athena OMOP CSVs ──parse + embed──▶ terms.parquet + concepts.parquet
                                                                │
                                                                ▼  build
                                       artifact_dir/index.turbovec + concepts.db (+ meta.json)
Runtime:  MedEmbed query-encoder + turbovec index + SQLite  ─▶  MCP tools (stdio by default)
```

## Runtime core

- **`store.py` — `ConceptStore`.** The runtime core. It over-fetches candidates from the
  ANN index, dedups by `concept_id` keeping the max score, applies `min_similarity` and a
  Python-side domain filter (never an ANN pre-filter), materializes metadata from SQLite,
  and falls back to an exact case-insensitive name match when semantic recall is thin. It
  knows nothing about MCP and is usable [in-process](library.md).
- **`embedder.py` — `Embedder`.** The single place text becomes a unit vector. The *same*
  class encodes both the offline index and the runtime query, so they can never diverge on
  model or normalization. Device is auto-detected (`cuda` → `mps` → `cpu`).
- **`ann.py` — `AnnIndex` Protocol + `TurbovecIndex`.** turbovec sits behind a tiny
  Protocol so the candidate-generation layer is swappable; the store depends only on the
  Protocol. Vectors are added in `row_id` order, so a returned slot index *is* the `row_id`.
- **`models.py` — `ConceptMatch`.** The stable output contract returned by every tool.
- **`server.py`.** A thin FastMCP skin exposing `search_concepts`, `get_concept_by_id`, and
  `find_concepts_by_relationship`. The store is loaded once, lazily, under a lock.

## Offline build pipeline (`build/`)

- **`from_omop.py`** — the Bring-Your-Own-Vocab path: Athena CSVs → embed → Parquet pair.
  See [Initialisation](initialisation.md).
- **`build_artifacts.py`** — Parquet → streaming 4-bit turbovec index + `concepts.db`,
  written to a temp dir and atomically moved into place so the server never sees a
  half-built set.
- **`schema.py`** — the canonical `TERMS_COLUMNS` / `CONCEPTS_COLUMNS` and SQLite DDL,
  defined once; both ingest paths must emit Parquet matching it.
- **`append_vocab.py`** — append a domain's concepts to existing artifacts without
  re-embedding the corpus.

## Artifacts

A build produces three files in `artifact_dir` (the platform user-cache dir by default;
override with `CONCEPT_OMCP_ARTIFACT_DIR`):

| File | Contents |
| --- | --- |
| `index.turbovec` | the 4-bit quantized ANN index; slot index == `row_id` |
| `concepts.db` | SQLite: `terms` (row_id → concept_id, text) + `concepts` (metadata, relationships) + `meta` |
| `meta.json` | build provenance — model, dim, counts, bit width, turbovec version, timestamp |

`ConceptStore.load()` checks the embedding model/dim in `meta` against the active settings
and fails fast on a mismatch, so a query encoder can never silently diverge from the index.
