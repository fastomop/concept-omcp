"""Build the runtime artifacts from canonical Parquet.

``terms.parquet`` + ``concepts.parquet`` -> ``index.turbovec`` + ``concepts.db``
(+ a ``meta`` table / ``meta.json``). Everything is written into a temp dir and
atomically moved into ``artifact_dir`` so the server never sees a half-built set.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ..ann import build_index_streaming
from ..logging import get_logger
from ..settings import settings
from . import schema

_logger = get_logger("concept_omcp.build.build_artifacts")

_TERMS_BATCH = 50_000
_INSERT_BATCH = 10_000


def build(parquet_dir: str = "build_tmp", artifact_dir: str | None = None, bit_width: int = 4) -> None:
    """Produce the turbovec index + SQLite metadata DB from the Parquet pair."""
    import pyarrow.parquet as pq

    parquet = Path(parquet_dir)
    terms_path = parquet / "terms.parquet"
    concepts_path = parquet / "concepts.parquet"
    if not terms_path.exists() or not concepts_path.exists():
        raise FileNotFoundError(f"Expected {terms_path} and {concepts_path}. Run extraction/ingest first.")

    schema.validate_parquet(terms_path, concepts_path)

    out_dir = Path(artifact_dir) if artifact_dir else settings.artifact_dir
    tmp_dir = out_dir / ".build_tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)

    tmp_index = tmp_dir / "index.turbovec"
    tmp_db = tmp_dir / "concepts.db"
    tmp_meta = tmp_dir / "meta.json"

    terms_file = pq.ParquetFile(terms_path)
    n_terms = _build_turbovec(terms_file, tmp_index, bit_width)
    n_concepts = _build_sqlite(terms_file, pq.ParquetFile(concepts_path), tmp_db)

    meta = {
        "embedding_model": settings.embedding_model,
        "embedding_dim": str(settings.embedding_dim),
        "normalized": "true",
        "n_terms": str(n_terms),
        "n_concepts": str(n_concepts),
        "bit_width": str(bit_width),
        "turbovec_version": _pkg_version("turbovec"),
        "build_ts": str(int(time.time())),
    }
    _write_meta(tmp_db, tmp_meta, meta)

    # Atomic-ish publish: replace each artifact in place.
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("index.turbovec", "concepts.db", "meta.json"):
        (tmp_dir / name).replace(out_dir / name)
    shutil.rmtree(tmp_dir)
    _logger.info("Built %s terms / %s concepts -> %s", f"{n_terms:,}", f"{n_concepts:,}", out_dir)


def _build_turbovec(terms_file, index_path: Path, bit_width: int) -> int:
    """Stream embeddings in row_id order into a turbovec index. Returns n_terms."""
    import numpy as np

    counter = {"n": 0, "next_row": 0}

    def batches():
        for batch in terms_file.iter_batches(batch_size=_TERMS_BATCH, columns=["row_id", "embedding"]):
            row_ids = batch.column("row_id").to_numpy()
            # row_id must be dense and in order — the turbovec slot index IS the row_id.
            if row_ids[0] != counter["next_row"] or not _is_consecutive(row_ids):
                raise ValueError(f"terms.parquet row_id not dense/ordered near {counter['next_row']}")
            counter["next_row"] = int(row_ids[-1]) + 1
            emb = batch.column("embedding")
            flat = emb.values.to_numpy(zero_copy_only=False).astype(np.float32, copy=False)
            mat = flat.reshape(len(emb), settings.embedding_dim)
            counter["n"] += len(emb)
            if counter["n"] % 500_000 < _TERMS_BATCH:
                _logger.info("  ...fed %s vectors to the index", f"{counter['n']:,}")
            yield mat

    _logger.info("Building turbovec index (streaming embeddings)...")
    build_index_streaming(batches(), settings.embedding_dim, index_path, bit_width=bit_width)
    _logger.info("  index finalized (%s vectors)", f"{counter['n']:,}")
    return counter["n"]


def _build_sqlite(terms_file, concepts_file, db_path: Path) -> int:
    """Load terms + concepts tables into a fresh SQLite. Returns n_concepts."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema.SQLITE_DDL)

        _logger.info("Writing SQLite metadata (terms + concepts)...")
        term_cols = ["row_id", "concept_id", "term_text", "is_primary"]  # skip the heavy embedding column
        n_inserted = 0
        for batch in terms_file.iter_batches(batch_size=_INSERT_BATCH, columns=term_cols):
            rows = zip(
                batch.column("row_id").to_pylist(),
                batch.column("concept_id").to_pylist(),
                batch.column("term_text").to_pylist(),
                (1 if p else 0 for p in batch.column("is_primary").to_pylist()),
            )
            conn.executemany("INSERT INTO terms VALUES (?,?,?,?)", rows)
            n_inserted += batch.num_rows
            if n_inserted % 500_000 < _INSERT_BATCH:
                _logger.info("  ...wrote %s term rows", f"{n_inserted:,}")

        cols = list(schema.CONCEPTS_COLUMNS)
        placeholders = ",".join("?" * len(cols))
        n_concepts = 0
        for batch in concepts_file.iter_batches(batch_size=_INSERT_BATCH, columns=cols):
            table = batch.to_pydict()
            rows = list(zip(*(table[c] for c in cols)))
            n_concepts += len(rows)
            conn.executemany(f"INSERT INTO concepts VALUES ({placeholders})", rows)

        conn.commit()
        return n_concepts
    finally:
        conn.close()


def _write_meta(db_path: Path, meta_path: Path, meta: dict[str, str]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
        conn.commit()
    finally:
        conn.close()
    meta_path.write_text(json.dumps(meta, indent=2))


def _is_consecutive(arr) -> bool:
    import numpy as np

    return bool(np.all(np.diff(arr) == 1)) if len(arr) > 1 else True


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"
