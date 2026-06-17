"""De-risk the vocab-extension plan: prove turbovec append works on the REAL index.

Loads the production 2.34 GB index, appends a handful of (new) Visit-term vectors
to a TEMP copy, reloads it, and verifies:
  (a) each appended vector self-returns at a new slot >= current length, and
  (b) top-10 results for existing probe queries are byte-identical to the
      un-appended index (append must not perturb existing slots / recall).

It never mutates the production artifact (writes the appended index to a tmpdir).
Decides: append (cheap, ~minutes) vs. full reindex for adding Visit/Device/source codes.

    .venv/bin/python eval/append_test.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import turbovec

from concept_omcp.embedder import Embedder
from concept_omcp.settings import settings


def _index_len(idx) -> int:
    for attr in ("__len__", "size", "ntotal", "count", "num_vectors"):
        try:
            v = getattr(idx, attr)
            return int(v() if callable(v) else v)
        except Exception:
            continue
    return -1  # unknown


def _top(idx, vec: np.ndarray, k: int) -> list[int]:
    q = np.ascontiguousarray(vec, dtype=np.float32).reshape(1, -1)
    _scores, ids = idx.search(q, k)
    return [int(x) for x in ids[0]]


def main() -> None:
    emb = Embedder(settings.embedding_model, settings.embedding_dim)

    # Probe queries that exercise existing slots (known good hits from smoke).
    probes = [
        "type 2 diabetes mellitus",
        "metformin",
        "aspirin",
        "chronic obstructive pulmonary disease",
        "appendectomy",
    ]
    qv = emb.encode(probes).astype(np.float32)  # (n,1024) L2-normalized

    # New Visit terms that are NOT in the store today — appending should make them findable.
    new_terms = [
        "Inpatient Visit",
        "Emergency Room Visit",
        "Emergency Room and Inpatient Visit",
        "Outpatient Visit",
        "Inpatient Hospitalization",
    ]
    new_vecs = emb.encode(new_terms).astype(np.float32)

    idx_path = str(settings.index_path)
    print(f"index: {idx_path}")

    # 1) Original index (untouched) — baseline top-10 + length.
    orig = turbovec.TurboQuantIndex.load(idx_path)
    orig.prepare()
    n0 = _index_len(orig)
    print(f"index length: {n0}  (expected next append slot: {n0 if n0 > 0 else '4,536,621'})")
    base = {t: _top(orig, v, 10) for t, v in zip(probes, qv)}

    # 2) Fresh load -> append new vectors -> write to a TEMP copy (never touch production).
    work = turbovec.TurboQuantIndex.load(idx_path)
    work.add(np.ascontiguousarray(new_vecs, dtype=np.float32))
    tmp = Path(tempfile.mkdtemp(prefix="tv_append_")) / "index_appended.turbovec"
    work.write(str(tmp))
    appended = turbovec.TurboQuantIndex.load(str(tmp))
    appended.prepare()
    n1 = _index_len(appended)
    print(f"appended length: {n1}  (added {len(new_terms)})")

    # 3) Verify appended vectors self-return at the new slots.
    print("\n-- appended vectors self-return --")
    ok_self = 0
    for i, (t, v) in enumerate(zip(new_terms, new_vecs)):
        ids = _top(appended, v, 1)
        expected = (n0 + i) if n0 > 0 else None
        good = ids[0] >= (n0 if n0 > 0 else 4_536_621)
        ok_self += good
        print(f"  {t!r:42} -> slot {ids[0]}  expected~{expected}  {'OK' if good else 'FAIL'}")

    # 4) Verify existing recall is unperturbed (orig top-10 == appended top-10).
    print("\n-- existing-query top-10 unchanged --")
    ok_recall = 0
    for t, v in zip(probes, qv):
        a = _top(appended, v, 10)
        same = a == base[t]
        ok_recall += same
        print(f"  {t!r:42} -> {'identical' if same else 'CHANGED'}  {a[:3]}")

    print(f"\n=== self-return {ok_self}/{len(new_terms)} | recall-unchanged {ok_recall}/{len(probes)} ===")
    verdict = "APPEND VIABLE" if (ok_self == len(new_terms) and ok_recall == len(probes)) else "REINDEX FALLBACK NEEDED"
    print(f"=== verdict: {verdict} ===")
    print(f"(temp appended index at {tmp} — safe to delete)")


if __name__ == "__main__":
    main()
