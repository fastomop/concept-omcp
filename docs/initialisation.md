# Initialisation

concept-omcp ships no vocabulary data. Before the server can answer queries you build the
artifacts once from an OMOP vocabulary you obtain yourself.

## 1. Download from Athena

Create an account at [athena.ohdsi.org](https://athena.ohdsi.org), select the vocabularies
you need, and download the bundle. **You accept the source licences at download time** and
are responsible for complying with them (see [Provenance & licensing](licensing.md)).

Unpack it to a directory containing the tab-delimited CSVs:

```
athena_vocab/
  CONCEPT.csv
  CONCEPT_SYNONYM.csv
  CONCEPT_RELATIONSHIP.csv
  CONCEPT_ANCESTOR.csv
```

## 2. Build

```bash
uv add "concept-omcp[build]"
uv run concept-omcp build --omop ./athena_vocab
```

This parses the CSVs, keeps standard concepts (`standard_concept = 'S'`) in the clinical
domains, flattens each concept to its primary name plus up to five English synonyms,
derives relationships and hierarchy, embeds every term, and writes `index.turbovec` +
`concepts.db` to the user-cache directory.

### Device and timing

The embedding device is auto-detected (`cuda` → `mps` → `cpu`); pin it with `--device`.
Honest expectations for the full ~4.5M-term corpus:

| Device | Rough time |
| --- | --- |
| CUDA GPU | minutes – 1 h |
| Apple MPS | a few hours |
| CPU | many hours – days |

### Scoping a CPU build

To keep a CPU build tractable, restrict the domains and/or vocabularies:

```bash
uv run concept-omcp build --omop ./athena_vocab \
    --domains Condition,Drug \
    --vocabularies SNOMED,RxNorm \
    --device cpu --batch-size 128
```

### Resuming

Builds are **resumable**. Embeddings are checkpointed per chunk under `<out>/.emb_ckpt/`;
an interrupted build re-run with the same inputs skips completed chunks. Changing
`--domains` / `--vocabularies` (which changes the term set) invalidates stale checkpoints
automatically.

!!! note "Transient disk"
    A full build needs roughly twice the final embedding size in transient disk
    (checkpoints + `terms.parquet`); the build logs an estimate up front. The checkpoint
    directory is removed on success.

## 3. Locate / relocate artifacts

By default artifacts live in the platform user-cache dir. Point the server elsewhere with:

```bash
export CONCEPT_OMCP_ARTIFACT_DIR=/data/concept-omcp/artifacts
uv run concept-omcp build --omop ./athena_vocab   # writes there
uv run concept-omcp serve                          # reads there
```

## 4. Verify (optional)

`eval/check_index.py` validates the built index without the embedding model — it confirms
sample vectors self-return at the top of their own search and that `row_id` alignment holds:

```bash
python eval/check_index.py --parquet build_tmp
```
