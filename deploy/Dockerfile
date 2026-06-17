# syntax=docker/dockerfile:1.7
#
# concept-omcp runtime image. Ships CODE + the embedding model cache only — NEVER
# vocabulary artifacts (those are licence-encumbered; mount them at runtime). Serves
# over the Streamable HTTP transport; stdio is for local subprocess use, not containers.

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Cached dependency layer: install runtime deps (no extras) WITHOUT the project, so
# editing src/ doesn't bust the (large — torch/sentence-transformers) dependency layer.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --frozen --no-install-project

COPY pyproject.toml README.md LICENSE uv.lock ./
COPY src ./src

# Project layer: install concept-omcp itself non-editably for a slim image.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable


FROM python:3.12-slim AS runtime

# Defaults: serve Streamable HTTP on :8100, read artifacts from the mounted /artifacts
# volume, cache the embedding model under the writable HF cache volume.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    CONCEPT_OMCP_TRANSPORT=streamable-http \
    CONCEPT_OMCP_HOST=0.0.0.0 \
    CONCEPT_OMCP_PORT=8100 \
    CONCEPT_OMCP_ARTIFACT_DIR=/artifacts \
    HF_HOME=/home/appuser/.cache/huggingface

RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --create-home --shell /usr/sbin/nologin appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

WORKDIR /app
USER appuser

EXPOSE 8100

# Liveness: the Streamable HTTP server is accepting TCP connections on its port.
# (The process fails fast at startup if the /artifacts volume is empty, so an
#  unhealthy/exited container signals a missing-artifacts misconfiguration.)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket,os,sys; \
s=socket.create_connection(('127.0.0.1', int(os.environ.get('CONCEPT_OMCP_PORT','8100'))), 3); s.close()" \
    || exit 1

CMD ["concept-omcp", "serve"]
