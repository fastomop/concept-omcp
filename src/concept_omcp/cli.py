"""Command-line entry point: ``concept-omcp <command>``.

Subcommands import their (sometimes heavy) modules lazily, so e.g. running the
server never imports the build dependencies. ``main`` returns an int exit code;
the console-script wrapper and ``python -m concept_omcp.cli`` both pass it to
``sys.exit``.
"""

from __future__ import annotations

import argparse
import sys


def _split_csv(value: str) -> list[str] | None:
    return [v.strip() for v in value.split(",") if v.strip()] or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="concept-omcp", description="Semantic, relationship-aware OMOP concept search over MCP (turbovec-backed)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the MCP server (loads prebuilt artifacts).")
    p_serve.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=None,
        help="Override the transport (default: settings/CONCEPT_OMCP_TRANSPORT, i.e. stdio).",
    )

    p_build = sub.add_parser("build", help="Build artifacts (turbovec index + sqlite) from OMOP CSVs or Parquet.")
    source = p_build.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--omop",
        metavar="DIR",
        help="Athena OMOP vocabulary dir (CONCEPT.csv, CONCEPT_SYNONYM.csv, ...). Full build: CSV -> embed -> index.",
    )
    source.add_argument(
        "--parquet",
        metavar="DIR",
        help="Prebuilt terms.parquet + concepts.parquet (maintainer path; skips parsing + embedding).",
    )
    p_build.add_argument(
        "--domains",
        type=_split_csv,
        default=None,
        help="Comma-separated domain filter (default: Condition,Drug,Procedure,Observation,Measurement). --omop only.",
    )
    p_build.add_argument(
        "--vocabularies",
        type=_split_csv,
        default=None,
        help="Comma-separated vocabulary_id filter, e.g. SNOMED,RxNorm (default: all). --omop only.",
    )
    p_build.add_argument("--device", default=None, help="Embedding device: cuda|mps|cpu (default: auto-detect).")
    p_build.add_argument(
        "--batch-size", type=int, default=256, help="Embedding batch size (default: 256). --omop only."
    )
    p_build.add_argument("--out", default="build_tmp", help="Temp dir for the intermediate Parquet pair.")
    p_build.add_argument(
        "--artifact-dir", default=None, help="Where to write artifacts (default: settings.artifact_dir / user cache)."
    )

    args = parser.parse_args(argv)

    from .logging import setup_logging
    from .settings import settings

    setup_logging(level=settings.log_level, log_file=settings.log_file, log_format=settings.log_format)

    if args.command == "serve":
        from .server import serve

        serve(transport=args.transport)
        return 0

    if args.command == "build":
        from .build.build_artifacts import build

        if args.omop:
            from .build.from_omop import build_parquet_from_omop

            parquet_dir = build_parquet_from_omop(
                args.omop,
                args.out,
                domains=args.domains,
                vocabularies=args.vocabularies,
                device=args.device,
                batch_size=args.batch_size,
            )
            build(parquet_dir=str(parquet_dir), artifact_dir=args.artifact_dir)
        else:
            build(parquet_dir=args.parquet, artifact_dir=args.artifact_dir)
        return 0

    return 0  # unreachable: subparser is required


if __name__ == "__main__":
    sys.exit(main())
