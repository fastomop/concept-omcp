"""BYOV build: raw Athena OMOP CSVs -> embed -> canonical Parquet.

This is the user-facing (Bring-Your-Own-Vocab) ingest path. The user downloads an
OMOP vocabulary bundle from Athena (accepting the source licences) and points this
at the unpacked directory; it produces the canonical ``terms.parquet`` +
``concepts.parquet`` pair that the downstream ``build_artifacts.build()`` step
turns into the runtime artifacts.

Pipeline:
  1. Parse the tab-delimited CSVs (CONCEPT, CONCEPT_SYNONYM, CONCEPT_RELATIONSHIP,
     CONCEPT_ANCESTOR), keeping standard concepts in the requested domains.
  2. Flatten to one *term* per (primary concept_name + up to 5 English synonyms),
     assigning dense ``row_id``s in deterministic file order.
  3. Derive per-concept metadata: ``relationship_types`` (from CONCEPT_RELATIONSHIP),
     ``parent_concept_id`` + ``ancestor_concepts`` + ``descendant_count`` (from
     CONCEPT_ANCESTOR).
  4. Embed the term texts with the shared ``Embedder``, checkpointed per chunk so an
     interrupted build resumes instead of restarting.
  5. Emit ``terms.parquet`` (with embeddings) + ``concepts.parquet``, validated
     against ``build/schema.py``.

CSV column conventions are the OMOP CDM v5.x vocabulary export layout, matching the
parsing already proven in ``build/append_vocab.py``.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Iterable, Optional

from ..embedder import Embedder
from ..logging import get_logger
from ..settings import settings
from . import schema

_logger = get_logger("concept_omcp.build.from_omop")

_ENGLISH = "4180186"  # CONCEPT_SYNONYM.language_concept_id for English
_DEFAULT_DOMAINS = ("Condition", "Drug", "Procedure", "Observation", "Measurement")
_MAX_SYNONYMS = 5
_MAX_ANCESTORS = 10  # ancestor_concepts is persisted but not surfaced; cap to keep rows small
_CHUNK_ROWS = 50_000  # embedding checkpoint granularity (one .npy per chunk)


def build_parquet_from_omop(
    vocab_dir: str,
    out_dir: str = "build_tmp",
    *,
    domains: Optional[Iterable[str]] = None,
    vocabularies: Optional[Iterable[str]] = None,
    device: Optional[str] = None,
    batch_size: int = 256,
    chunk_rows: int = _CHUNK_ROWS,
) -> Path:
    """Process Athena CSVs, embed terms, write the canonical Parquet pair.

    Returns the output directory. Resumable: re-running after an interruption
    reuses any embedding checkpoints under ``<out_dir>/.emb_ckpt`` whose manifest
    still matches (same model / domains / vocabularies / term count).
    """
    voc = Path(vocab_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    terms_path = out / "terms.parquet"
    concepts_path = out / "concepts.parquet"

    domain_set = set(domains) if domains else set(_DEFAULT_DOMAINS)
    vocab_set = set(vocabularies) if vocabularies else None
    _logger.info(
        "Scanning OMOP vocab %s — domains=%s vocabularies=%s",
        voc,
        sorted(domain_set),
        sorted(vocab_set) if vocab_set else "ALL",
    )

    concepts_rows, terms = _load_omop(voc, domain_set, vocab_set)
    if not terms:
        raise ValueError(
            f"No concepts matched in {voc} (domains={sorted(domain_set)}, "
            f"vocabularies={sorted(vocab_set) if vocab_set else 'ALL'}). "
            "Check the directory holds Athena CONCEPT.csv etc. and the filters are not too narrow."
        )
    _logger.info("Loaded %d concepts / %d terms", len(concepts_rows), len(terms))

    _write_concepts_parquet(concepts_rows, concepts_path)

    embedder = Embedder(settings.embedding_model, settings.embedding_dim, device=device)
    _logger.info("Embedding %d terms on device=%s (model=%s)", len(terms), embedder.device, settings.embedding_model)
    est_gb = len(terms) * settings.embedding_dim * 4 / 1e9
    _logger.info("Embeddings will need ~%.1f GB on disk (checkpoints + terms.parquet, transient)", 2 * est_gb)

    manifest_key = {
        "n_terms": len(terms),
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
        "domains": sorted(domain_set),
        "vocabularies": sorted(vocab_set) if vocab_set else None,
    }
    _embed_terms_to_parquet(
        terms,
        terms_path,
        embedder=embedder,
        batch_size=batch_size,
        chunk_rows=chunk_rows,
        ckpt_dir=out / ".emb_ckpt",
        manifest_key=manifest_key,
    )

    _logger.info("Validating Parquet against canonical schema...")
    schema.validate_parquet(terms_path, concepts_path)
    _logger.info("OK -> %s, %s", terms_path, concepts_path)
    return out


# --------------------------------------------------------------------------- load


def _load_omop(voc: Path, domains: set[str], vocabularies: Optional[set[str]]):
    """Return (concepts_rows, terms).

    concepts_rows: list of tuples in ``schema.CONCEPTS_COLUMNS`` order.
    terms: list of (row_id, concept_id, term_text, is_primary) in dense row_id order.
    """
    concept_csv = voc / "CONCEPT.csv"
    if not concept_csv.exists():
        raise FileNotFoundError(f"Missing {concept_csv}. Point --omop at an unpacked Athena vocabulary directory.")

    kept, order = _read_concepts(concept_csv, domains, vocabularies)
    _logger.info("  kept %d standard concepts in-domain", len(kept))

    syns = _read_optional(voc / "CONCEPT_SYNONYM.csv", lambda p: _read_synonyms(p, set(kept), _MAX_SYNONYMS), {})
    rels = _read_optional(voc / "CONCEPT_RELATIONSHIP.csv", lambda p: _read_relationship_types(p, set(kept)), {})
    parents, ancestors, descendant_count = _read_optional(
        voc / "CONCEPT_ANCESTOR.csv",
        lambda p: _read_ancestry(p, set(kept), _MAX_ANCESTORS),
        ({}, {}, {}),
    )

    terms: list[tuple[int, int, str, int]] = []
    row_id = 0
    for cid in order:
        name = kept[cid]["concept_name"]
        terms.append((row_id, cid, name, 1))
        row_id += 1
        seen = {name.strip().lower()}
        for s in syns.get(cid, ()):  # already capped + English-only
            key = s.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            terms.append((row_id, cid, s, 0))
            row_id += 1

    concepts_rows: list[tuple] = []
    for cid in order:
        c = kept[cid]
        parent = parents.get(cid)
        concepts_rows.append(
            (
                cid,
                c["concept_name"],
                c["domain_id"],
                c["vocabulary_id"],
                c["standard_concept"],
                c["concept_class_id"],
                c["concept_code"],
                c["valid_start_date"],
                c["valid_end_date"],
                c["invalid_reason"],
                str(parent) if parent is not None else None,
                json.dumps(sorted(rels.get(cid, ()))),
                json.dumps(ancestors.get(cid, [])),
                int(descendant_count.get(cid, 0)),
            )
        )
    return concepts_rows, terms


def _read_optional(path: Path, fn, default):
    if not path.exists():
        _logger.warning("  %s not found — skipping (downstream fields left empty)", path.name)
        return default
    return fn(path)


def _read_concepts(concept_csv: Path, domains: set[str], vocabularies: Optional[set[str]]):
    """Return (kept: dict[cid -> fields], order: list[cid]) in file order."""
    kept: dict[int, dict] = {}
    order: list[int] = []
    with open(concept_csv, encoding="utf-8") as f:
        next(f, None)  # header
        for line in f:
            p = line.rstrip("\r\n").split("\t")
            if len(p) < 10 or p[2] not in domains or p[5] != "S":
                continue
            if vocabularies is not None and p[3] not in vocabularies:
                continue
            try:
                cid = int(p[0])
            except ValueError:
                continue
            if cid in kept:
                continue
            kept[cid] = {
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
            order.append(cid)
    return kept, order


def _read_synonyms(syn_csv: Path, want: set[int], max_syn: int) -> dict[int, list[str]]:
    syns: dict[int, list[str]] = {}
    with open(syn_csv, encoding="utf-8") as f:
        next(f, None)
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


def _read_relationship_types(rel_csv: Path, want: set[int]) -> dict[int, set[str]]:
    """For each kept concept, the distinct *valid* relationship_ids it participates
    in as the source (concept_id_1). Mirrors ConceptMatch.relationship_types."""
    rels: dict[int, set[str]] = {}
    with open(rel_csv, encoding="utf-8") as f:
        next(f, None)
        for line in f:
            p = line.rstrip("\r\n").split("\t")
            if len(p) < 6 or p[5]:  # invalid_reason non-empty -> deprecated relationship
                continue
            try:
                c1 = int(p[0])
            except ValueError:
                continue
            if c1 in want and p[2]:
                rels.setdefault(c1, set()).add(p[2])
    return rels


def _read_ancestry(anc_csv: Path, want: set[int], max_ancestors: int):
    """Return (parents, ancestors, descendant_count) from CONCEPT_ANCESTOR.

    parents[cid]          -> chosen direct parent (smallest ancestor id at min_levels==1)
    ancestors[cid]        -> ancestor ids at 1<=min_levels<=2, sorted, capped
    descendant_count[cid] -> distinct descendants at min_levels>=1 (rows are unique per pair)
    """
    parents: dict[int, int] = {}
    raw_ancestors: dict[int, list[tuple[int, int]]] = {}
    descendant_count: dict[int, int] = {}
    with open(anc_csv, encoding="utf-8") as f:
        next(f, None)
        for line in f:
            p = line.rstrip("\r\n").split("\t")
            if len(p) < 3:
                continue
            try:
                anc, desc, minlev = int(p[0]), int(p[1]), int(p[2])
            except ValueError:
                continue
            if minlev >= 1 and anc in want:
                descendant_count[anc] = descendant_count.get(anc, 0) + 1
            if desc in want and 1 <= minlev <= 2:
                raw_ancestors.setdefault(desc, []).append((minlev, anc))
                if minlev == 1 and (desc not in parents or anc < parents[desc]):
                    parents[desc] = anc
    ancestors = {desc: [a for _, a in sorted(lst)[:max_ancestors]] for desc, lst in raw_ancestors.items()}
    return parents, ancestors, descendant_count


# ------------------------------------------------------------------------- write


def _write_concepts_parquet(concepts_rows: list[tuple], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    cols = list(schema.CONCEPTS_COLUMNS)
    columns = list(zip(*concepts_rows)) if concepts_rows else [[] for _ in cols]
    table = pa.table({name: list(col) for name, col in zip(cols, columns)})
    pq.write_table(table, path)
    _logger.info("  wrote %s (%d concepts)", path.name, len(concepts_rows))


def _embed_terms_to_parquet(
    terms: list[tuple[int, int, str, int]],
    out_path: Path,
    *,
    embedder: Embedder,
    batch_size: int,
    chunk_rows: int,
    ckpt_dir: Path,
    manifest_key: dict,
) -> None:
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

    dim = settings.embedding_dim
    n = len(terms)
    texts = [t[2] for t in terms]
    starts = list(range(0, n, chunk_rows))

    ckpt_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = ckpt_dir / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest_key:
        stale = list(ckpt_dir.glob("emb_*.npy"))
        _logger.warning("checkpoint manifest mismatch — discarding %d stale checkpoint(s)", len(stale))
        for f in stale:
            f.unlink()
    manifest_path.write_text(json.dumps(manifest_key))

    # --- Phase 1: embed each chunk to a checkpoint (resume skips completed ones) ---
    embedded_terms = 0
    embed_time = 0.0
    for start in starts:
        end = min(start + chunk_rows, n)
        ck = ckpt_dir / f"emb_{start:09d}.npy"
        if ck.exists():
            arr = np.load(ck, mmap_mode="r")
            if arr.shape == (end - start, dim):
                continue
            _logger.warning("  bad checkpoint %s (shape %s) — recomputing", ck.name, tuple(arr.shape))
        t0 = time.perf_counter()
        vecs = embedder.encode(texts[start:end], batch_size=batch_size).astype(np.float32, copy=False)
        np.save(ck, vecs)
        dt = time.perf_counter() - t0
        embedded_terms += end - start
        embed_time += dt
        rate = embedded_terms / embed_time if embed_time else 0.0
        eta = (n - end) / rate if rate else 0.0
        _logger.info(
            "  embedded %d/%d terms (%.0f terms/s, ETA %s)",
            end,
            n,
            rate,
            _fmt_eta(eta),
            extra={"n_terms": end, "duration_ms": dt * 1000.0},
        )

    # --- Phase 2: stream checkpoints + metadata into terms.parquet (atomic rename) ---
    arrow_schema = pa.schema(
        [
            ("row_id", pa.int64()),
            ("concept_id", pa.int64()),
            ("term_text", pa.string()),
            ("is_primary", pa.bool_()),
            ("embedding", pa.list_(pa.float32(), dim)),
        ]
    )
    tmp = Path(str(out_path) + ".tmp")
    _logger.info("Assembling %s from %d checkpoint(s)...", out_path.name, len(starts))
    writer = pq.ParquetWriter(tmp, arrow_schema)
    try:
        for start in starts:
            end = min(start + chunk_rows, n)
            vecs = np.ascontiguousarray(np.load(ckpt_dir / f"emb_{start:09d}.npy"), dtype=np.float32)
            chunk = terms[start:end]
            emb_col = pa.FixedSizeListArray.from_arrays(pa.array(vecs.reshape(-1), pa.float32()), dim)
            batch = pa.record_batch(
                [
                    pa.array([t[0] for t in chunk], pa.int64()),
                    pa.array([t[1] for t in chunk], pa.int64()),
                    pa.array([t[2] for t in chunk], pa.string()),
                    pa.array([bool(t[3]) for t in chunk], pa.bool_()),
                    emb_col,
                ],
                schema=arrow_schema,
            )
            writer.write_batch(batch)
    finally:
        writer.close()
    tmp.replace(out_path)
    shutil.rmtree(ckpt_dir, ignore_errors=True)  # success — drop the checkpoints


def _fmt_eta(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"
