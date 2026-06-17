# Build provenance

Every build records what produced the artifacts in a `meta` table (and a mirror
`meta.json`). `ConceptStore.load()` reads it and refuses to serve if the active embedding
model or dimension disagrees with the index — so a query encoder can never silently
diverge from what the index was built with.

## `meta` keys

| Key | Meaning |
| --- | --- |
| `embedding_model` | the SentenceTransformer model id used to embed every term |
| `embedding_dim` | vector dimension (must match `settings.embedding_dim`) |
| `normalized` | `true` — vectors are L2-normalized (turbovec scores by inner product) |
| `n_terms` | number of term vectors in the index |
| `n_concepts` | number of unique concepts |
| `bit_width` | turbovec quantization bit width (default 4) |
| `turbovec_version` | the turbovec package version at build time |
| `build_ts` | Unix timestamp of the build |

## Determinism

The term ordering is deterministic in the Athena CSV file order, and `row_id` is dense and
contiguous — the turbovec slot index *is* the `row_id`, which *is* the SQLite `terms` row.
The resumable embedding checkpoints rely on this: re-running a build with the same inputs
reproduces the same term set and ordering, so completed chunks are reused safely.

## Verifying an index without the model

`eval/check_index.py` samples raw vectors straight from `terms.parquet`, queries the
turbovec index with each, and asserts the query's own row is returned at the top with
near-1.0 self-similarity and that the SQLite `row_id → concept_id` mapping matches. This
proves index integrity and `row_id` alignment using no model and no network:

```bash
python eval/check_index.py --parquet build_tmp
```

## Reproducing or updating

Re-run `concept-omcp build --omop <athena_dir>` against a newer Athena release to rebuild.
To add a single domain to an existing index without re-embedding the whole corpus, see
`build/append_vocab.py`, which appends new vectors at slots beyond the current length and
inserts the corresponding `terms` / `concepts` rows, keeping `row_id == slot`.
