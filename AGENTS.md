# AGENTS.md

Shared guidance for AI coding agents on **concept-omcp**. Format follows the [agents.md](https://agents.md/) standard so every agent (Claude Code, Codex, Cursor, …) reads the same file. See [Cross-tool layout](#cross-tool-layout) for tool-specific entry points.

For the contribution policy (DCO, AI-assisted-PR disclosure), see [CONTRIBUTING.md](CONTRIBUTING.md).

## What this is

A semantic, relationship-aware search service over the [OMOP standardized vocabularies](https://www.ohdsi.org/data-standardization/), exposed over the **Model Context Protocol**. Queries are embedded with [MedEmbed](https://huggingface.co/abhinand/MedEmbed-large-v0.1) and matched against a prebuilt [turbovec](https://github.com/RyanCodrai/turbovec) index (4-bit quantized) with concept metadata + relationships in SQLite. The default transport is **stdio** (the harness spawns `concept-omcp serve` as a subprocess); FastMCP's Streamable HTTP / SSE transports cover the networked case.

**Bring-Your-Own-Vocab (BYOV).** The package ships *code only* — no vocabulary data. Vocabulary text (SNOMED CT, LOINC, …) is licence-encumbered and must not be redistributed (see [NOTICE](NOTICE) / [docs/licensing.md](docs/licensing.md)). The user downloads an OMOP bundle from [Athena](https://athena.ohdsi.org), accepts the source licences, and runs a one-time local build.

## Setup

`requires-python = ">=3.10"`. The project uses **uv** end-to-end ([install](https://docs.astral.sh/uv/getting-started/installation/)):

```sh
uv sync --frozen --extra dev                 # hermetic unit suite + lint
uv sync --frozen --extra dev --extra build   # + the OMOP build pipeline (pyarrow/pandas) and integration tests
uv sync --frozen --extra docs                # docs site (zensical)
```

## Commands

| Task | Command |
| --- | --- |
| Tests (hermetic) | `uv run --frozen --no-sync pytest` |
| Tests (full, incl. integration) | `uv run --frozen --no-sync pytest -o addopts=""` |
| Tests (CI-equivalent: full minus model download) | `uv run --frozen --no-sync pytest -o addopts="" -m "not realmodel"` |
| Tests + coverage (CI) | `uv run --frozen --no-sync pytest -o addopts="" -m "not realmodel" --cov` |
| Lint | `uvx ruff check src tests eval examples` |
| Format | `uvx ruff format src tests eval examples` |
| Pre-commit | `uvx prek run --all-files` |
| Build sdist + wheel | `uv build` |
| Build artifacts (BYOV) | `uv run concept-omcp build --omop <athena_dir>` |
| Serve (stdio) | `uv run concept-omcp serve` |
| Serve docs | `uv run --frozen --no-sync zensical serve` |
| Build container | `docker compose -f deploy/docker-compose.yml build` |

`-o addopts=""` clears the default `-m 'not integration'` filter so the build-pipeline tests run (they use a fake embedder — no model download — but need `pyarrow`/`turbovec`, i.e. the `build` extra). The one test that downloads the real MedEmbed model is marked `realmodel`: CI excludes it with `-m "not realmodel"` (it would be network-dependent and Hugging-Face-rate-limited), and it auto-skips locally when the model is neither cached nor reachable. Run it deliberately with `-o addopts="" -m realmodel`.

## Layout

```
src/concept_omcp/
  server.py           FastMCP server — thin skin over ConceptStore; 3 tools
  store.py            ConceptStore — runtime core (turbovec + SQLite); MCP-agnostic
  embedder.py         shared query/index encoder (device auto-detect cuda→mps→cpu)
  ann.py              AnnIndex Protocol + TurbovecIndex; build/append helpers
  models.py           ConceptMatch / RelatedConcept (the stable output contract)
  settings.py         pydantic-settings (env prefix CONCEPT_OMCP_); artifact dir, transport, logging
  logging.py          structured logging — STDERR ONLY (stdout is JSON-RPC under stdio)
  cli.py              `concept-omcp serve | build`
  build/              offline pipeline ([build] extra) — never imported by the served runtime
    from_omop.py      BYOV: Athena CSV -> embed (resumable) -> Parquet
    build_artifacts.py  Parquet -> turbovec index + concepts.db (atomic publish)
    schema.py         canonical TERMS_COLUMNS / CONCEPTS_COLUMNS + SQLite DDL
    append_vocab.py   append a domain to existing artifacts (no re-embed)
tests/                pytest; fixtures/athena/ holds a tiny Athena CSV vocab
eval/                 manual smoke scripts (mcp_smoke, smoke, check_index, ...)
examples/             reference consumer code (in_process_search.py)
docs/                 zensical source (zensical.toml at repo root)
deploy/               Dockerfile + docker-compose (Streamable HTTP serve)
.github/workflows/    tests.yml, publish.yml, docs.yml, ghcr-build-push.yml
```

## Code style

- **ruff** (`[tool.ruff]`). Line length 120, target 3.10+, `select = ["E","F","W","I"]` (isort on). No project-wide ignores — keep new code clean rather than relaxing rules.
- Fully type-hinted; `py.typed` is shipped.
- **stdout purity:** under the stdio transport, stdout carries JSON-RPC. Never `print()` on a runtime/build path — use `concept_omcp.logging` (handlers are stderr-only). `cli.main()` returns an `int` exit code.
- The `Embedder` is shared by build and runtime so the index and query encoders can never diverge — don't bypass it.

## Build & release

- `[build-system].build-backend = "uv_build"`. `uv build` produces sdist + wheel.
- Version is single-sourced in `pyproject.toml [project].version`; `__init__.__version__` reads it via `importlib.metadata`.
- Tag-driven publish: `.github/workflows/publish.yml` fires on `v*`, aborts unless the tag matches `[project].version`, smoke-tests the wheel AND sdist, then publishes to PyPI via Trusted Publishing (OIDC).

## The BYOV build path

`concept-omcp build --omop <athena_dir>` (in `build/from_omop.py`) parses the tab-delimited Athena CSVs (`CONCEPT`, `CONCEPT_SYNONYM`, `CONCEPT_RELATIONSHIP`, `CONCEPT_ANCESTOR`), flattens to one *term* per primary name + ≤5 English synonyms, derives `relationship_types` / `parent_concept_id` / `descendant_count`, embeds (resumable, checkpointed per chunk under `.emb_ckpt/`), and emits the canonical Parquet pair — which `build_artifacts.build()` turns into the runtime artifacts. Both Parquet files MUST match `build/schema.py`. Subset a slow CPU build with `--domains` / `--vocabularies`.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semver from 1.0.0. **Update `## [Unreleased]` for every user-visible change** — CLI/API surface, build behaviour, dependencies, the `ConceptMatch` contract, removals, fixes — under the right `### Added/Changed/Fixed/Removed/Deprecated/Security` heading.

## After making changes

1. **Sweep for stale references.** When you rename or remove a public symbol, CLI flag, setting (`CONCEPT_OMCP_*`), dependency, or file, grep the whole tree and update every hit: `src/`, `tests/`, `eval/`, `examples/`, `docs/`, `README.md`, `## [Unreleased]` in `CHANGELOG.md`, `AGENTS.md` (+ the `CLAUDE.md` symlink), `.github/workflows/`, `deploy/`.
2. **Run pre-commit**: `uvx prek run --all-files` (trailing whitespace, EOL, YAML/TOML, large-file guard, `ruff check --fix`, `ruff format`).
3. **Verify end-to-end.** `pytest` (hermetic) is necessary but not sufficient for build/runtime changes: run the full suite (`pytest -o addopts=""`) and, for transport changes, `python eval/mcp_smoke.py` — it spawns the stdio server and asserts **clean stdout** (a stray print breaks the handshake).

## Conventions

- **`uv sync` / `uv add` only — never `uv pip install`.** CI and Docker use `uv sync --frozen`.
- End-user docs are uv-native (`uv add concept-omcp`, `uv run concept-omcp …`). No `pip install`.
- `[project.optional-dependencies]` extras: `build`, `observability`, `dev`, `docs`. New optional groups go alongside.
- **Never commit vocabulary artifacts.** `/artifacts/` and `*.parquet` are gitignored; the licence model forbids redistribution.
- The container ships code + model only and serves over Streamable HTTP with artifacts mounted at runtime — never bake artifacts into the image.

## Cross-tool layout

`AGENTS.md` is the canonical project-wide agent file ([agents.md](https://agents.md/) spec). Tool-specific entry points alias into it via tracked symlinks:

- `CLAUDE.md` → `AGENTS.md` (Claude Code)
- `.claude/<file>` → `.agents/<file>` for shared assets

Personal preferences (your permission allowlist, ad-hoc env vars) belong in `.claude/settings.local.json` (gitignored). Shared team settings go in `.claude/settings.json`.
