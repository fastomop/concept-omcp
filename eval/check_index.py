"""Index-integrity check — validate the built artifacts WITHOUT the embedding model.

Pulls a spread-out sample of raw vectors straight from terms.parquet, queries the
turbovec index with each, and asserts the index returns that very row among the
top-k at near-1.0 self-similarity. This proves two things the build could get
wrong, using no model and no internet:

  * index integrity      — the vector is present and searchable;
  * row_id alignment      — turbovec slot index == row_id == the SQLite terms row
                            (i.e. build added vectors in row_id order).

Run right after `concept-omcp build`, pointing at the parquet dir that build used,
so a corrupt build is caught before the artifacts are relied on:

    python eval/check_index.py --parquet build_tmp
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from concept_omcp.ann import TurbovecIndex
from concept_omcp.settings import settings

_K = 5  # the query's own row should land within the top-K of its own vector


def _load_probe_rows(terms_path: Path, probe_rows: list[int]) -> dict[int, tuple[np.ndarray, int]]:
    """row_id -> (raw embedding, concept_id) for each requested row, scanning batches."""
    pf = pq.ParquetFile(terms_path)
    wanted = set(probe_rows)
    targets: dict[int, tuple[np.ndarray, int]] = {}
    for batch in pf.iter_batches(batch_size=50_000, columns=["row_id", "concept_id", "embedding"]):
        rids = batch.column("row_id").to_numpy()
        lo, hi = int(rids[0]), int(rids[-1])
        here = [r for r in wanted if lo <= r <= hi]
        if not here:
            continue
        flat = batch.column("embedding").values.to_numpy(zero_copy_only=False).astype(np.float32)
        mat = flat.reshape(len(rids), settings.embedding_dim)
        cids = batch.column("concept_id").to_numpy()
        for r in here:
            off = r - lo
            targets[r] = (mat[off].copy(), int(cids[off]))
        if len(targets) == len(wanted):
            break
    return targets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default="build_tmp", help="dir holding terms.parquet")
    ap.add_argument("--samples", type=int, default=8)
    args = ap.parse_args()

    terms_path = Path(args.parquet) / "terms.parquet"
    print(f"index:   {settings.index_path}")
    print(f"sqlite:  {settings.db_path}")
    print(f"parquet: {terms_path}\n")

    n = pq.ParquetFile(terms_path).metadata.num_rows
    probe_rows = sorted({int(i) for i in np.linspace(0, n - 1, args.samples)})
    print(f"{n:,} terms; probing rows {probe_rows}\n")

    targets = _load_probe_rows(terms_path, probe_rows)
    ann = TurbovecIndex.load(settings.index_path)
    conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    ok = 0
    for row_id in probe_rows:
        vec, parquet_cid = targets[row_id]
        ids, scores = ann.search(vec, _K)
        ids = [int(x) for x in ids]
        top_score = float(scores[0])
        db = conn.execute("SELECT concept_id FROM terms WHERE row_id=?", (row_id,)).fetchone()
        db_cid = db["concept_id"] if db else None

        self_in_topk = row_id in ids
        aligned = db_cid == parquet_cid
        status = "OK" if (self_in_topk and aligned and top_score > 0.95) else "FAIL"
        ok += status == "OK"
        print(
            f"[{status}] row {row_id}: top5={ids} top_score={top_score:.3f} "
            f"self_in_top5={self_in_topk} cid(parquet/sqlite)={parquet_cid}/{db_cid}"
        )

    print(f"\n=== {ok}/{len(probe_rows)} probes OK ===")
    print(
        "OK = the index returns the query's own row within its top-5 at score>0.95 AND the SQLite "
        "row_id->concept_id matches the parquet. Proves index integrity + row alignment without the model.\n"
        "(A non-self top hit at high score is fine if it's a true duplicate vector; a FAIL means misalignment.)"
    )


if __name__ == "__main__":
    main()
