"""Centralised logging for concept-omcp.

Structured logging with configurable level, format, and destination. The one
non-negotiable invariant: **every handler writes to ``sys.stderr``**. The MCP
server's default transport is stdio, where stdout carries JSON-RPC frames and a
single stray byte breaks the protocol — so logs (build progress, ETA, the
artifact load) must never touch stdout.

Environment variables (prefix ``CONCEPT_OMCP_``, matching ``settings.py``):
    CONCEPT_OMCP_LOG_LEVEL:  DEBUG | INFO | WARNING | ERROR | CRITICAL
    CONCEPT_OMCP_LOG_FILE:   path to a log file (optional; adds a file handler)
    CONCEPT_OMCP_LOG_FORMAT: 'simple' | 'detailed' | 'json'
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_LOG_FORMAT = "detailed"

FORMATS = {
    "simple": "%(levelname)s: %(message)s",
    "detailed": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "json": None,  # handled by JSONFormatter
}

# Custom record attributes the JSON formatter promotes to top-level fields.
_EXTRA_FIELDS = ("duration_ms", "n_terms", "n_concepts", "row_id", "phase")


class JSONFormatter(logging.Formatter):
    """Render log records as one JSON object per line (for log aggregators)."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_data)


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
    log_format: Optional[str] = None,
    logger_name: str = "concept_omcp",
) -> logging.Logger:
    """Configure and return the package logger.

    Arguments fall back to the ``CONCEPT_OMCP_LOG_*`` environment variables, then
    to the module defaults. Idempotent: existing handlers are cleared first so
    repeated calls (e.g. CLI then library) don't duplicate output.
    """
    level = level or os.getenv("CONCEPT_OMCP_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    log_file = log_file or os.getenv("CONCEPT_OMCP_LOG_FILE")
    log_format = log_format or os.getenv("CONCEPT_OMCP_LOG_FORMAT", DEFAULT_LOG_FORMAT)

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logger = logging.getLogger(logger_name)
    logger.setLevel(numeric_level)
    logger.handlers.clear()

    if log_format == "json":
        formatter: logging.Formatter = JSONFormatter()
    else:
        format_string = FORMATS.get(log_format) or FORMATS["detailed"]
        formatter = logging.Formatter(format_string, datefmt="%Y-%m-%d %H:%M:%S")

    # stderr ONLY — stdout is reserved for stdio JSON-RPC.
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "concept_omcp") -> logging.Logger:
    """Return a logger, attaching a ``NullHandler`` until ``setup_logging`` runs.

    Library consumers that never call ``setup_logging`` get silence (the Python
    logging best practice), not unconfigured root-logger output on stdout.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger


__all__ = ["setup_logging", "get_logger", "JSONFormatter"]
