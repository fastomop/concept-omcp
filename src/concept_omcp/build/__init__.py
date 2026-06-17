"""Offline build pipeline (Athena CSV -> Parquet -> artifacts).

Imported only by build tooling, never by the served runtime. Pulls heavy,
build-only deps (pandas, pyarrow) — installed via the `[build]` extra.
"""
