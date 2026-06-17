"""Append OMOP concepts of a domain to the existing turbovec artifacts — NO re-embed.

Selects a domain's (standard) concepts from an OMOP vocab dir that are NOT already in
the store, embeds their names + English synonyms with MedEmbed, and APPENDS them to
``index.turbovec`` (slots >= current length) and ``concepts.db`` (terms + concepts),
keeping ``row_id == turbovec slot``. The existing 4.5M vectors are reused untouched.

Atomic + safe: builds into ``*.new`` files, verifies a known lookup, then swaps in
(keeping ``*.bak``). Reusable for Visit, then Device / source codes later.

    .venv/bin/python -m concept_omcp.build.append_vocab --vocab ~/Documents/omop_vocab_current --domain Visit
    # preview only:
    .venv/bin/python -m concept_omcp.build.append_vocab --vocab <dir> --domain Visit --dry-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import numpy as np

from ..ann import TurbovecIndex, append_index
from ..embedder import Embedder
from ..settings import settings
from . import schema

_ENGLISH = "4180186"  # CONCEPT_SYNONYM.language_concept_id for English


def _existing(db_path: Path) -> Tuple[Set[int], int]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        ids = {r[0] for r in con.execute("SELECT concept_id FROM concepts")}
        max_row = con.execute("SELECT MAX(row_id) FROM terms").fetchone()[0]
    finally:
        con.close()
    return ids, int(max_row)


def _read_concepts(concept_csv: Path, domain: str, standard_only: bool, skip: Set[int]) -> List[dict]:
    out: List[dict] = []
    with open(concept_csv, encoding="utf-8") as f:
        next(f)  # header
        for line in f:
            p = line.rstrip("\r\n").split("\t")
            if len(p) < 10 or p[2] != domain:
                continue
            if standard_only and p[5] != "S":
                continue
            try:
                cid = int(p[0])
            except ValueError:
                continue
            if cid in skip:
                continue
            out.append(
                {
                    "concept_id": cid,
                    "concept_name": p[1],
                    "domain_id": p[2],
                    "vocabulary_id": p[3],
                    "concept_class_id": p[4],
                    "standard_concept": p[5],
                    "concept_code": p[6],
                    "valid_start_date": p[7],
                    "valid_end_date": p[8],
                    "invalid_reason": p[9] or None,
                }
            )
    return out


def _read_synonyms(syn_csv: Path, want: Set[int], max_syn: int) -> Dict[int, List[str]]:
    syns: Dict[int, List[str]] = {}
    with open(syn_csv, encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\r\n").split("\t")
            if len(p) < 3 or p[2] != _ENGLISH:
                continue
            try:
                cid = int(p[0])
            except ValueError:
                continue
            if cid not in want:
                continue
            bucket = syns.setdefault(cid, [])
            if len(bucket) < max_syn and p[1].strip():
                bucket.append(p[1])
    return syns


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vocab", required=True, help="OMOP vocab dir (CONCEPT.csv + CONCEPT_SYNONYM.csv)")
    ap.add_argument("--domain", default="Visit")
    ap.add_argument("--standard-only", action="store_true", default=True)
    ap.add_argument("--include-nonstandard", dest="standard_only", action="store_false")
    ap.add_argument("--max-synonyms", type=int, default=5)
    ap.add_argument("--verify-term", default="inpatient visit")
    ap.add_argument("--verify-concept-id", type=int, default=9201)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    voc = Path(args.vocab)
    concept_csv, syn_csv = voc / "CONCEPT.csv", voc / "CONCEPT_SYNONYM.csv"
    index_path, db_path, meta_path = settings.index_path, settings.db_path, settings.meta_path

    existing_ids, max_row = _existing(db_path)
    print(f"existing store: {len(existing_ids):,} concepts, max row_id {max_row:,}")
    print(f"scanning CONCEPT.csv for domain={args.domain!r} standard_only={args.standard_only}…")
    new_concepts = _read_concepts(concept_csv, args.domain, args.standard_only, existing_ids)
    print(f"  {len(new_concepts)} new {args.domain} concepts to add")
    if not new_concepts:
        print("nothing to add.")
        return

    want = {c["concept_id"] for c in new_concepts}
    syns = _read_synonyms(syn_csv, want, args.max_synonyms)

    # Flat-per-term rows: primary name + ≤max_synonyms English synonyms; row_id continues the index.
    terms: List[Tuple[int, int, str, int]] = []
    texts: List[str] = []
    rid = max_row + 1
    for c in new_concepts:
        terms.append((rid, c["concept_id"], c["concept_name"], 1))
        texts.append(c["concept_name"])
        rid += 1
        name_l = c["concept_name"].strip().lower()
        for s in syns.get(c["concept_id"], []):
            if s.strip().lower() == name_l:
                continue
            terms.append((rid, c["concept_id"], s, 0))
            texts.append(s)
            rid += 1
    print(f"  {len(terms)} terms ({len(new_concepts)} primary + {len(terms) - len(new_concepts)} synonyms)")
    if args.dry_run:
        for c in new_concepts[:15]:
            print(f"    {c['concept_id']:>10}  {c['concept_name']}  ({c['vocabulary_id']})")
        print("dry-run — artifacts not modified.")
        return

    print("embedding new terms with MedEmbed…")
    emb = Embedder(settings.embedding_model, settings.embedding_dim)
    vecs = emb.encode(texts).astype(np.float32)
    assert vecs.shape == (len(texts), settings.embedding_dim), vecs.shape

    idx_new = Path(str(index_path) + ".new")
    print(f"appending {len(vecs)} vectors to a fresh copy -> {idx_new.name}…")
    append_index(index_path, vecs, out_path=idx_new)  # original untouched

    db_new = Path(str(db_path) + ".new")
    shutil.copy2(db_path, db_new)
    con = sqlite3.connect(db_new)
    try:
        con.executemany("INSERT INTO terms VALUES (?,?,?,?)", terms)
        cols = list(schema.CONCEPTS_COLUMNS)
        rows = [
            (
                c["concept_id"],
                c["concept_name"],
                c["domain_id"],
                c["vocabulary_id"],
                c["standard_concept"],
                c["concept_class_id"],
                c["concept_code"],
                c["valid_start_date"],
                c["valid_end_date"],
                c["invalid_reason"],
                None,
                "[]",
                "[]",
                0,
            )
            for c in new_concepts
        ]
        con.executemany(f"INSERT INTO concepts VALUES ({','.join('?' * len(cols))})", rows)
        n_terms = con.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
        n_concepts = con.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        con.execute("INSERT OR REPLACE INTO meta VALUES ('n_terms', ?)", (str(n_terms),))
        con.execute("INSERT OR REPLACE INTO meta VALUES ('n_concepts', ?)", (str(n_concepts),))
        con.commit()
    finally:
        con.close()

    # Verify on the .new artifacts before swapping anything in.
    print("verifying…")
    idx = TurbovecIndex.load(idx_new)
    rids, _scores = idx.search(emb.encode_one(args.verify_term), 10)
    con = sqlite3.connect(f"file:{db_new}?mode=ro", uri=True)
    rid_in = ",".join(str(int(r)) for r in rids)
    row_to_cid = {r[0]: r[1] for r in con.execute(f"SELECT row_id, concept_id FROM terms WHERE row_id IN ({rid_in})")}
    con.close()
    cids = [row_to_cid.get(int(r)) for r in rids]
    print(f"  search({args.verify_term!r}) -> concept_ids {cids}")
    if args.verify_concept_id not in cids:
        print(
            f"VERIFY FAILED: expected {args.verify_concept_id} in top-10. "
            f"Left .new files in place (NOT swapped) — inspect before retrying.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"  ✓ {args.verify_concept_id} retrieved")

    # Atomic swap, keep .bak.
    for live, new in ((index_path, idx_new), (db_path, db_new)):
        bak = Path(str(live) + ".bak")
        if bak.exists():
            bak.unlink()
        live.rename(bak)
        new.rename(live)
    meta = json.loads(meta_path.read_text())
    meta.update(n_terms=str(n_terms), n_concepts=str(n_concepts))
    meta_path.write_text(json.dumps(meta, indent=2))
    print(
        f"✓ appended {len(new_concepts)} {args.domain} concepts ({len(terms)} terms). "
        f"now n_terms={n_terms:,} n_concepts={n_concepts:,}. Backups kept as *.bak"
    )


if __name__ == "__main__":
    main()
