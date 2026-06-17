# concept-omcp

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![OMOP](https://img.shields.io/badge/OMOP-vocabularies-5C4EE5)
![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)
![Tests](https://github.com/fastomop/concept-omcp/actions/workflows/tests.yml/badge.svg)

Semantic, relationship-aware search over the **OMOP standardized vocabularies**, exposed
over the **Model Context Protocol (MCP)**. A clinical term is embedded with
[MedEmbed](https://huggingface.co/abhinand/MedEmbed-large-v0.1) and matched against a
prebuilt [turbovec](https://github.com/RyanCodrai/turbovec) index (4-bit quantized);
concept metadata and relationships are served from SQLite. ~4.5M term vectors occupy
roughly 2 GB rather than the ~17 GB of an unquantized float32 store, and the server opens
the prebuilt artifacts at startup in seconds — it never re-embeds or re-indexes at query
time.

📖 **Documentation: <https://fastomop.github.io/concept-omcp/>**

## Provenance & licensing — read first

concept-omcp ships **code only; it contains no vocabulary data.** The OMOP vocabularies
(SNOMED CT, LOINC, RxNorm, ICD-O-3, OPCS4, …) are licence-encumbered: SNOMED International
requires distributors to be Affiliates and to sub-licence downstream users, LOINC forbids
derivative standards, and OHDSI asks that vocabularies not be extracted and redistributed.
A built index embeds the literal source descriptions of these vocabularies and therefore
**must not be redistributed.**

The model is **Bring-Your-Own-Vocab (BYOV)**: you download an OMOP bundle from
[Athena](https://athena.ohdsi.org), accept the source licences at download time, and run a
one-time local build. The Apache-2.0 licence in this repository covers the *code* only. See
[NOTICE](NOTICE) and the [licensing guide](docs/licensing.md) for the per-vocabulary posture.

## Install

> New to uv? [Install it first](https://docs.astral.sh/uv/getting-started/installation/) — one command, no admin rights.

From inside a [uv project](https://docs.astral.sh/uv/concepts/projects/) (`uv init` first if you don't have one):

```bash
uv add "concept-omcp[build]"     # runtime + the one-time offline build pipeline
```

## Initialise (one-time)

```bash
# 1. Download an OMOP vocabulary bundle from https://athena.ohdsi.org and unpack it
#    (a directory of CONCEPT.csv, CONCEPT_SYNONYM.csv, CONCEPT_RELATIONSHIP.csv,
#    CONCEPT_ANCESTOR.csv), accepting the source licences.
# 2. Build the artifacts into the platform user-cache dir:
uv run concept-omcp build --omop ./athena_vocab
```

The build embeds every term and writes `index.turbovec` + `concepts.db` to the user-cache
directory (override with `CONCEPT_OMCP_ARTIFACT_DIR`). The device is auto-detected
(`cuda` → `mps` → `cpu`); embedding the full ~4.5M-term corpus takes **minutes–1h on a GPU,
a few hours on Apple MPS, and many hours–days on CPU**. To keep a CPU build tractable, scope
it:

```bash
uv run concept-omcp build --omop ./athena_vocab --domains Condition,Drug --vocabularies SNOMED,RxNorm
```

Builds are **resumable** — an interrupted run continues from per-chunk checkpoints rather
than restarting.

## Serve

```bash
uv run concept-omcp serve          # stdio JSON-RPC (default transport)
```

Attach it to an MCP host. Claude Desktop launches the server with an arbitrary working
directory and a minimal environment, so its config must (a) pin the project directory with
`--directory` and (b) pass `CONCEPT_OMCP_ARTIFACT_DIR` so `serve` finds the artifacts you
built (the default user-cache dir is otherwise empty):

```json
{
  "mcpServers": {
    "concept-omcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/your/project", "run", "--no-sync", "concept-omcp", "serve"],
      "env": { "CONCEPT_OMCP_ARTIFACT_DIR": "/path/to/your/artifacts" }
    }
  }
}
```

> **macOS:** launch via `uv` as shown — do **not** point `command` at the in-folder
> `.venv/bin/concept-omcp`. 

If artifacts are missing, `serve` fails fast with a message pointing at `concept-omcp build --omop`.

## Use in-process (skip MCP)

`ConceptStore` is the runtime core and knows nothing about MCP — import it directly:

```python
from concept_omcp import ConceptStore, settings

with ConceptStore.load(settings) as store:
    for m in store.search_concepts("type 2 diabetes mellitus", domain_filter="Condition", top_k=5):
        print(m.concept_id, m.concept_name, m.similarity_score)
```

See [examples/in_process_search.py](examples/in_process_search.py) for a runnable
end-to-end example.

## Tools exposed

| Tool | Purpose |
| --- | --- |
| `search_concepts` | semantic search (`domain_filter` ∈ Condition\|Drug\|Procedure\|Measurement\|Observation) |
| `get_concept_by_id` | direct concept lookup + parent/relationships |
| `find_concepts_by_relationship` | find concepts participating in given relationship types |

## Architecture

```
Initialise (once):  Athena OMOP CSVs ──parse + embed──▶ terms.parquet + concepts.parquet
                                                                │
                                                                ▼  build
                                       artifact_dir/index.turbovec + concepts.db
Runtime:  MedEmbed query-encoder + turbovec index + SQLite  ─▶  MCP tools (stdio by default)
```

- `store.py` — `ConceptStore`, the MCP-agnostic runtime core (turbovec + SQLite).
- `server.py` — a thin FastMCP skin over the store (stdio default; Streamable HTTP / SSE available).
- `build/` — the offline pipeline (`from_omop.py` → `build_artifacts.py`), quarantined from the served runtime.

See [docs/architecture.md](docs/architecture.md) for details.

## Documentation

| Topic | Page |
| --- | --- |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Initialisation (Athena → build) | [docs/initialisation.md](docs/initialisation.md) |
| MCP server & transports | [docs/mcp.md](docs/mcp.md) |
| In-process library use | [docs/library.md](docs/library.md) |
| Build provenance | [docs/build_provenance.md](docs/build_provenance.md) |
| Provenance & licensing | [docs/licensing.md](docs/licensing.md) |
| Logging | [docs/logging.md](docs/logging.md) |

For contributing, see [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md);
release notes live in [CHANGELOG.md](CHANGELOG.md).

## Stability

Pre-1.0 (`0.x.y`). The Python API (`ConceptStore`, `ConceptMatch`, `settings`) and the
three MCP tool signatures are stable; the exact ranking, scores, and metadata derivation
may change between minor versions as the build is calibrated. Pin to a minor version
(`concept-omcp>=0.1,<0.2`) and review the changelog before upgrading.

## License

[Apache 2.0](LICENSE) — for the **code**. Vocabulary data is governed by its own source
licences (see [NOTICE](NOTICE) / [docs/licensing.md](docs/licensing.md)).
