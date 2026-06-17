# Logging

concept-omcp uses a small structured-logging module (`concept_omcp.logging`). The defining
constraint: **every handler writes to `sys.stderr`.** Under the stdio MCP transport, stdout
carries JSON-RPC frames, so the build progress, ETA, and artifact-load messages must never
touch stdout.

## Configuration

Set via environment (prefix `CONCEPT_OMCP_`) or `.env`:

| Variable | Default | Values |
| --- | --- | --- |
| `CONCEPT_OMCP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `CONCEPT_OMCP_LOG_FORMAT` | `detailed` | `simple`, `detailed`, `json` |
| `CONCEPT_OMCP_LOG_FILE` | _(none)_ | path; adds a file handler alongside stderr |

The CLI calls `setup_logging()` for every command, and `serve()` calls it again before the
transport loop — `setup_logging` is idempotent (it clears existing handlers, so repeated
calls never duplicate output).

## Formats

- `simple` — `LEVEL: message`
- `detailed` — `timestamp - logger - LEVEL - message`
- `json` — one JSON object per line, suitable for log aggregators. Extra fields the build
  attaches (`duration_ms`, `n_terms`, `n_concepts`, `row_id`, `phase`) are promoted to
  top-level keys.

```bash
CONCEPT_OMCP_LOG_FORMAT=json CONCEPT_OMCP_LOG_LEVEL=DEBUG uv run concept-omcp build --omop ./athena_vocab
```

## Library use

If you import `ConceptStore` without calling `setup_logging()`, the package logger has a
`NullHandler` and stays silent — the standard library convention. Call
`concept_omcp.logging.setup_logging()` yourself to see output, or configure the root logger
in your application.
