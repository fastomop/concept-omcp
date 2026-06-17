"""Hermetic tests for the logging module and CLI argument helpers.

No model, no pyarrow, no turbovec — these cover the genuinely-new plumbing
(stderr-only structured logging, CLI parsing) without the heavy build deps.
"""

import json
import logging

import pytest

from concept_omcp import cli
from concept_omcp.logging import JSONFormatter, get_logger, setup_logging


def test_setup_logging_level_and_stderr():
    log = setup_logging(level="DEBUG", log_format="detailed", logger_name="concept_omcp.test_a")
    assert log.level == logging.DEBUG
    assert log.handlers, "expected at least one handler"
    # stdout MUST stay clean for stdio MCP — every stream handler writes to stderr.
    import sys

    for h in log.handlers:
        if isinstance(h, logging.StreamHandler):
            assert h.stream is sys.stderr


def test_setup_logging_idempotent():
    a = setup_logging(logger_name="concept_omcp.test_b")
    n = len(a.handlers)
    b = setup_logging(logger_name="concept_omcp.test_b")
    assert b is a and len(b.handlers) == n  # handlers cleared, not duplicated


def test_json_formatter_emits_extra_fields():
    rec = logging.LogRecord("concept_omcp", logging.INFO, "f.py", 1, "hi", None, None)
    rec.n_terms = 9
    rec.duration_ms = 12.5
    out = json.loads(JSONFormatter().format(rec))
    assert out["message"] == "hi" and out["level"] == "INFO"
    assert out["n_terms"] == 9 and out["duration_ms"] == 12.5


def test_get_logger_attaches_nullhandler():
    log = get_logger("concept_omcp.fresh_xyz")
    assert any(isinstance(h, logging.NullHandler) for h in log.handlers)


def test_cli_split_csv():
    assert cli._split_csv("Condition, Drug ,Measurement") == ["Condition", "Drug", "Measurement"]
    assert cli._split_csv("") is None
    assert cli._split_csv("  ") is None


def test_cli_requires_subcommand():
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_build_requires_a_source():
    # --omop / --parquet are a required mutually-exclusive group.
    with pytest.raises(SystemExit):
        cli.main(["build"])
