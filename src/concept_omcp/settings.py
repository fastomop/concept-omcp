"""Runtime + build settings, in one place (explicit is better than implicit).

Everything is overridable via environment (prefix ``CONCEPT_OMCP_``) or a local
``.env`` file. No scattered ``os.getenv`` calls elsewhere in the package.
"""

from pathlib import Path

from platformdirs import user_cache_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_artifact_dir() -> Path:
    """Platform user-cache dir, e.g. ~/Library/Caches/concept-omcp (macOS),
    ~/.cache/concept-omcp (Linux). Correct once pip-installed, where the old
    repo-relative default would land inside site-packages.
    """
    return Path(user_cache_dir("concept-omcp"))


class Settings(BaseSettings):
    """Single source of truth for paths, model, ANN params, transport, logging."""

    model_config = SettingsConfigDict(
        env_prefix="CONCEPT_OMCP_",
        env_file=".env",
        extra="ignore",
    )

    # --- Artifacts (built once via `concept-omcp build --omop`; opened at startup) ---
    # Override with CONCEPT_OMCP_ARTIFACT_DIR. `build --omop` writes here; `serve` reads here.
    artifact_dir: Path = Field(default_factory=_default_artifact_dir)

    # --- Embedding (query encoder; must match what the artifacts were built with) ---
    embedding_model: str = "abhinand/MedEmbed-large-v0.1"
    embedding_dim: int = 1024

    # --- ANN search ---
    overfetch_min: int = Field(default=100, description="Candidate floor before dedup/domain-filter")

    # --- MCP server transport ---
    # stdio by default: the agent harness spawns `concept-omcp serve` as a subprocess
    # and speaks JSON-RPC over stdin/stdout — no port, no host, no firewall. host/port
    # apply only when transport is overridden to "streamable-http" / "sse".
    transport: str = "stdio"
    host: str = "0.0.0.0"
    port: int = 8100

    # --- Logging (consumed by concept_omcp.logging.setup_logging) ---
    log_level: str = "INFO"
    log_file: str | None = None
    log_format: str = "detailed"

    @property
    def index_path(self) -> Path:
        return self.artifact_dir / "index.turbovec"

    @property
    def db_path(self) -> Path:
        return self.artifact_dir / "concepts.db"

    @property
    def meta_path(self) -> Path:
        return self.artifact_dir / "meta.json"


settings = Settings()
