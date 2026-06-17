# concept-omcp

**concept-omcp** is semantic, relationship-aware search over the OMOP standardized
vocabularies, exposed over the [Model Context Protocol](https://modelcontextprotocol.io/).
A clinical term is embedded with [MedEmbed](https://huggingface.co/abhinand/MedEmbed-large-v0.1)
and matched against a prebuilt [turbovec](https://github.com/RyanCodrai/turbovec) index;
concept metadata and relationships come from SQLite. The server opens prebuilt artifacts at
startup in seconds — it never re-embeds or re-indexes at query time.

!!! warning "Bring-Your-Own-Vocab — the package ships no vocabulary data"
    The OMOP vocabularies (SNOMED CT, LOINC, RxNorm, …) are licence-encumbered and must not
    be redistributed. You download a bundle from [Athena](https://athena.ohdsi.org),
    accept the source licences, and build the artifacts locally. The Apache-2.0 licence
    covers the *code* only. See [Provenance & licensing](licensing.md).

## What's in these docs

<div class="grid cards" markdown>

-   :material-sitemap: **[Architecture](architecture.md)**

    The runtime core, the ANN Protocol seam, and the offline build pipeline.

-   :material-database-import: **[Initialisation](initialisation.md)**

    Download from Athena and run the one-time `build --omop`.

-   :material-link-variant: **[MCP server](mcp.md)**

    The three tools, the stdio default, and the Streamable HTTP / SSE transports.

-   :material-language-python: **[In-process library](library.md)**

    Use `ConceptStore` directly and skip MCP entirely.

-   :material-cog: **[Build provenance](build_provenance.md)**

    What the build records in `meta.json`, and how to verify an index.

-   :material-scale-balance: **[Provenance & licensing](licensing.md)**

    The per-vocabulary posture and your responsibilities.

-   :material-text-box-outline: **[Logging](logging.md)**

    Level, format, destination — and why everything goes to stderr.

</div>

## Quick start

```bash
uv add "concept-omcp[build]"
uv run concept-omcp build --omop ./athena_vocab   # one-time
uv run concept-omcp serve                         # stdio MCP server
```
