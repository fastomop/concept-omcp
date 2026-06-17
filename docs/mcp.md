# MCP server

`concept-omcp serve` runs a [FastMCP](https://modelcontextprotocol.io/) server exposing three
tools over the configured transport. The default is **stdio**: the MCP host spawns
`concept-omcp serve` as a subprocess and speaks JSON-RPC over stdin/stdout — no port, no host,
no network surface.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_concepts` | `query_text`, `domain_filter?`, `top_k=10`, `min_similarity=0.5`, `include_relationships=True` | JSON list of matches, sorted by similarity |
| `get_concept_by_id` | `concept_id`, `include_relationships=True` | JSON match, or `null` |
| `find_concepts_by_relationship` | `relationship_types`, `domain_filter?`, `limit=50` | JSON list of matches |

`domain_filter` is one of `Condition`, `Drug`, `Procedure`, `Measurement`, `Observation`.
Each match is a `ConceptMatch` (see [In-process library](library.md)).

## Claude Desktop

Claude Desktop launches the server with an arbitrary working directory and a minimal
environment, so the config pins the project directory with `--directory` and passes
`CONCEPT_OMCP_ARTIFACT_DIR` so `serve` finds the artifacts you built:

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

> **macOS:** launch via `uv` (above) rather than pointing `command` at the in-folder
> `.venv/bin/concept-omcp` — under Full Disk Access controls a venv binary inside a protected
> folder (e.g. `~/Documents`) can't read its own `pyvenv.cfg`. (`… run --no-sync python -m
> concept_omcp.cli serve` is equivalent.)

The server fails fast at startup if the artifacts are missing, with a message pointing at
`concept-omcp build --omop`.

## Transports

```bash
uv run concept-omcp serve                            # stdio (default)
uv run concept-omcp serve --transport streamable-http  # network: CONCEPT_OMCP_HOST:PORT
uv run concept-omcp serve --transport sse
```

The networked transports (Streamable HTTP / SSE) are **unauthenticated at the application
layer** — authorization is OPTIONAL in MCP. When exposing concept-omcp over a network, gate
it at your reverse proxy. The [container deployment](https://github.com/fastomop/concept-omcp/tree/main/deploy)
serves over Streamable HTTP with the artifact directory mounted read-only.

## stdout purity

Under stdio, stdout carries JSON-RPC frames; a single stray byte breaks the handshake. All
concept-omcp logging is written to **stderr** (see [Logging](logging.md)), and
`eval/mcp_smoke.py` asserts clean stdout across the full handshake + tool calls.
