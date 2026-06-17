"""CLI subcommand dispatch + exit codes — hermetic (heavy work is mocked).

``main`` is the published console-script entry point. These cover its dispatch
to ``serve`` / ``build`` and the ``int`` exit code without spawning the server or
running a real embedding build. Argument-parsing helpers and the required-arg
errors live in ``test_logging_cli.py``.
"""

import pytest

from concept_omcp import cli


def test_serve_dispatch_default_transport(monkeypatch):
    seen = {}
    monkeypatch.setattr("concept_omcp.server.serve", lambda transport=None: seen.update(transport=transport))
    assert cli.main(["serve"]) == 0
    assert seen == {"transport": None}


def test_serve_dispatch_explicit_transport(monkeypatch):
    seen = {}
    monkeypatch.setattr("concept_omcp.server.serve", lambda transport=None: seen.update(transport=transport))
    assert cli.main(["serve", "--transport", "streamable-http"]) == 0
    assert seen["transport"] == "streamable-http"


def test_serve_rejects_unknown_transport():
    with pytest.raises(SystemExit):
        cli.main(["serve", "--transport", "carrier-pigeon"])


def test_build_omop_dispatch(monkeypatch, tmp_path):
    """--omop runs from_omop -> build, threading the parsed filters/device through."""
    seen = {}

    def fake_from_omop(omop_dir, out, *, domains, vocabularies, device, batch_size):
        seen["omop"] = dict(
            omop_dir=omop_dir, out=out, domains=domains, vocabularies=vocabularies, device=device, batch_size=batch_size
        )
        return tmp_path / "parquet"

    monkeypatch.setattr("concept_omcp.build.from_omop.build_parquet_from_omop", fake_from_omop)
    monkeypatch.setattr(
        "concept_omcp.build.build_artifacts.build",
        lambda parquet_dir=None, artifact_dir=None: seen.update(build=(parquet_dir, artifact_dir)),
    )

    rc = cli.main(
        [
            "build",
            "--omop",
            "/data/athena",
            "--domains",
            "Condition, Drug",
            "--vocabularies",
            "SNOMED",
            "--device",
            "cpu",
            "--batch-size",
            "64",
            "--out",
            str(tmp_path),
            "--artifact-dir",
            str(tmp_path / "art"),
        ]
    )

    assert rc == 0
    assert seen["omop"]["omop_dir"] == "/data/athena"
    assert seen["omop"]["domains"] == ["Condition", "Drug"]
    assert seen["omop"]["vocabularies"] == ["SNOMED"]
    assert seen["omop"]["device"] == "cpu"
    assert seen["omop"]["batch_size"] == 64
    # build() consumes the Parquet dir produced by the --omop step.
    assert seen["build"] == (str(tmp_path / "parquet"), str(tmp_path / "art"))


def test_build_parquet_dispatch_skips_embedding(monkeypatch):
    """--parquet feeds build() directly and must NOT invoke the CSV/embed front."""
    seen = {}
    monkeypatch.setattr(
        "concept_omcp.build.from_omop.build_parquet_from_omop",
        lambda *a, **k: pytest.fail("from_omop must not run on the --parquet path"),
    )
    monkeypatch.setattr(
        "concept_omcp.build.build_artifacts.build",
        lambda parquet_dir=None, artifact_dir=None: seen.update(parquet=parquet_dir, art=artifact_dir),
    )
    assert cli.main(["build", "--parquet", "/tmp/pq"]) == 0
    assert seen == {"parquet": "/tmp/pq", "art": None}


def test_build_omop_and_parquet_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.main(["build", "--omop", "/a", "--parquet", "/b"])


def test_extract_milvus_subcommand_is_removed():
    # The legacy Milvus extraction path was removed; argparse must reject the old command.
    with pytest.raises(SystemExit):
        cli.main(["extract-milvus"])
