# Changelog

All notable changes to concept-omcp are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project adheres to
semantic versioning from 1.0.0 onward (pre-1.0, minor versions may break).

## [Unreleased]

First public release preparation: a `pip`/`uv`-installable, **Bring-Your-Own-Vocab**
MCP server, aligned with the `fastomop` house architecture.

### Added

- **Milvus-free build path** (`concept-omcp build --omop <athena_dir>`). Parses the
  tab-delimited Athena OMOP CSVs (`CONCEPT`, `CONCEPT_SYNONYM`, `CONCEPT_RELATIONSHIP`,
  `CONCEPT_ANCESTOR`), flattens to terms (primary name + ≤5 English synonyms), derives
  `relationship_types` / `parent_concept_id` / `ancestor_concepts` / `descendant_count`,
  embeds, and produces the runtime artifacts — no Milvus required. `--domains` /
  `--vocabularies` scope (and shrink) a build.
- **Resumable, checkpointed embedding.** An interrupted build resumes from per-chunk
  checkpoints instead of restarting; throughput + ETA are logged.
- **Device auto-detect** in the embedder (`cuda` → `mps` → `cpu`), with an explicit
  `--device` override and a tunable embedding `--batch-size`.
- **Structured logging** (`concept_omcp.logging`): env-driven level/file/format
  (`CONCEPT_OMCP_LOG_*`), JSON formatter, **stderr-only** so the stdio MCP transport's
  stdout stays pure JSON-RPC.
- `ConceptStore` context-manager support (`close()` / `with`) for in-process library use.
- MCP server `instructions`, thread-safe lazy artifact load.
- Packaging for PyPI: Apache-2.0 `LICENSE` + `NOTICE`, trove classifiers, `[project.urls]`,
  `py.typed`, single-sourced version, `uv_build` backend.
- Documentation site (zensical) and the four CI workflows (tests, publish, docs, GHCR).
- Container deploy bundle (`deploy/Dockerfile` + `docker-compose.yml`) serving over
  Streamable HTTP with the artifact directory mounted at runtime.
- Test fixtures (`tests/fixtures/athena/`) and a build-pipeline smoke + resume test.

### Changed

- **Licence is Apache-2.0** (was MIT in early drafts) — matches the `fastomop` org and
  adds an explicit patent grant.
- **Python floor widened to `>=3.10`** (was `>=3.13`); CI tests across 3.10–3.14.
- Default `artifact_dir` is now the platform **user-cache dir** (`platformdirs`), not a
  repo-relative path — correct once pip-installed. Override with `CONCEPT_OMCP_ARTIFACT_DIR`.
- The missing-artifact error now points at `concept-omcp build --omop <athena_dir>`.
- `langfuse` moved from a core dependency to the optional `[observability]` extra; the
  tracing span degrades to a no-op when it is absent, and its `except` no longer masks
  errors raised inside the traced body.
- Build/runtime progress goes through the logger instead of `print()`.
- `cli.main()` returns an `int` exit code.

### Removed

- Author-internal deploy scripts and Milvus-baseline/scratch eval scripts.
- 3.7 GB of local artifact backups (`*.bak`).
- **The legacy Milvus extraction path entirely**: the `extract-milvus` CLI subcommand,
  `build/extract_milvus.py`, the `[milvus]` extra (`pymilvus`), and the `MILVUS_*`
  environment variables. The supported build path is `concept-omcp build --omop`.
- `examples/atlas_milvus_search.py` (the `MilvusSearchTool` drop-in facade tied to an
  internal `atlas_agent`); `examples/in_process_search.py` is the canonical example.
