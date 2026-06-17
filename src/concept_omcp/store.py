"""ConceptStore — the runtime core. turbovec (ANN) + SQLite (metadata).

Knows nothing about MCP; usable in-process by any consumer that wants semantic
concept search without the JSON-RPC layer. Returns ``ConceptMatch`` objects.

Search flow: over-fetch candidates from the ANN index, dedup by concept_id
keeping the max score, apply ``min_similarity`` and a Python-side domain filter
(never an ANN pre-filter), materialize metadata from SQLite, then a hybrid
exact-text fallback.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from .ann import AnnIndex, TurbovecIndex
from .embedder import Embedder
from .logging import get_logger
from .models import ConceptMatch
from .settings import Settings

_logger = get_logger("concept_omcp.store")

# Columns selected from the `concepts` table, in ConceptMatch-friendly order.
_CONCEPT_COLS = (
    "concept_id, concept_name, domain_id, vocabulary_id, standard_concept, "
    "concept_class_id, concept_code, valid_start_date, valid_end_date, "
    "invalid_reason, parent_concept_id, relationship_types"
)


class ConceptStore:
    """Semantic + relationship-aware concept lookup over prebuilt artifacts."""

    def __init__(self, embedder: Embedder, ann: AnnIndex, conn: sqlite3.Connection, overfetch_min: int = 100) -> None:
        self._embedder = embedder
        self._ann = ann
        self._conn = conn
        self._conn.row_factory = sqlite3.Row
        self._overfetch_min = overfetch_min

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, settings: Settings) -> "ConceptStore":
        """Open all artifacts (model, turbovec index, SQLite). Fast: no recompute."""
        for path in (settings.index_path, settings.db_path):
            if not Path(path).exists():
                raise FileNotFoundError(
                    f"Missing artifact: {path}. Build it first with "
                    "`concept-omcp build --omop <athena_vocab_dir>` "
                    "(download the OMOP vocabulary from https://athena.ohdsi.org). "
                    "Set CONCEPT_OMCP_ARTIFACT_DIR if your artifacts live elsewhere."
                )

        conn = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row  # _assert_meta reads rows by name; __init__ sets this too (idempotent)
        cls._assert_meta(conn, settings)

        embedder = Embedder(settings.embedding_model, settings.embedding_dim)
        ann = TurbovecIndex.load(settings.index_path)
        _logger.info("Loaded artifacts from %s", settings.artifact_dir)
        return cls(embedder, ann, conn, overfetch_min=settings.overfetch_min)

    # --------------------------------------------------------------- lifecycle
    def close(self) -> None:
        """Close the SQLite connection. Idempotent; safe for repeated calls."""
        try:
            self._conn.close()
        except Exception:  # already closed / never opened
            pass

    def __enter__(self) -> "ConceptStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @staticmethod
    def _assert_meta(conn: sqlite3.Connection, settings: Settings) -> None:
        meta = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM meta")}
        model = meta.get("embedding_model")
        if model and model != settings.embedding_model:
            raise ValueError(f"Artifact built with model {model!r} but settings use {settings.embedding_model!r}.")
        dim = meta.get("embedding_dim")
        if dim and int(dim) != settings.embedding_dim:
            raise ValueError(f"Artifact dim {dim} != settings dim {settings.embedding_dim}.")

    # ---------------------------------------------------------------- search
    def search_concepts(
        self,
        query_text: str,
        domain_filter: Optional[str] = None,
        top_k: int = 10,
        min_similarity: float = 0.5,
        include_relationships: bool = True,
        use_hybrid_search: bool = True,
    ) -> list[ConceptMatch]:
        """Semantic search -> deduplicated ConceptMatch list, sorted by score desc."""
        query = self._embedder.encode_one(query_text)
        overfetch = max(top_k * 3, self._overfetch_min)
        row_ids, scores = self._ann.search(query, overfetch)

        # row_id -> best score (candidates already desc; first seen wins per concept).
        row_to_concept = self._rows_to_concepts([int(r) for r in row_ids])
        best: dict[int, float] = {}
        order: list[int] = []
        for row_id, score in zip((int(r) for r in row_ids), (float(s) for s in scores)):
            concept_id = row_to_concept.get(row_id)
            if concept_id is None or score < min_similarity:
                continue
            if concept_id not in best:
                best[concept_id] = score
                order.append(concept_id)
            elif score > best[concept_id]:
                best[concept_id] = score

        matches = self._materialize(order, best, query_text, domain_filter, include_relationships)

        # Hybrid fallback: exact concept-name match when semantic search is thin.
        if use_hybrid_search and len(matches) < top_k:
            seen = {m.concept_id for m in matches}
            for m in self._exact_text_search(query_text, domain_filter, top_k, include_relationships):
                if m.concept_id not in seen:
                    matches.append(m)
                    seen.add(m.concept_id)

        matches.sort(key=lambda m: m.similarity_score or 0.0, reverse=True)
        return matches[:top_k]

    def get_concept_by_id(self, concept_id: int, include_relationships: bool = True) -> Optional[ConceptMatch]:
        """Direct lookup by OMOP concept_id (perfect-match score 1.0)."""
        row = self._conn.execute(f"SELECT {_CONCEPT_COLS} FROM concepts WHERE concept_id = ?", (concept_id,)).fetchone()
        if row is None:
            return None
        return self._to_match(row, 1.0, row["concept_name"], include_relationships)

    def find_concepts_by_relationship(
        self,
        relationship_types: list[str],
        domain_filter: Optional[str] = None,
        limit: int = 50,
    ) -> list[ConceptMatch]:
        """Find concepts participating in any of the given relationship types."""
        sql = f"SELECT {_CONCEPT_COLS} FROM concepts"
        params: list[object] = []
        if domain_filter:
            sql += " WHERE domain_id = ?"
            params.append(domain_filter)
        sql += " LIMIT ?"
        params.append(limit * 3)  # over-fetch; filter the JSON array in Python

        wanted = set(relationship_types)
        out: list[ConceptMatch] = []
        for row in self._conn.execute(sql, params):
            if wanted & set(_parse_json_list(row["relationship_types"])):
                out.append(self._to_match(row, 1.0, "relationship query", include_relationships=True))
                if len(out) >= limit:
                    break
        return out

    # --------------------------------------------------------------- helpers
    def _exact_text_search(
        self,
        query_text: str,
        domain_filter: Optional[str],
        limit: int,
        include_relationships: bool,
    ) -> list[ConceptMatch]:
        """Case-insensitive exact concept-name match (one indexed query)."""
        sql = (
            f"SELECT {_CONCEPT_COLS} FROM concepts "
            "WHERE concept_id IN (SELECT concept_id FROM terms WHERE term_text = ? COLLATE NOCASE)"
        )
        params: list[object] = [query_text]
        if domain_filter:
            sql += " AND domain_id = ?"
            params.append(domain_filter)
        sql += " LIMIT ?"
        params.append(limit)
        return [self._to_match(row, 0.95, query_text, include_relationships) for row in self._conn.execute(sql, params)]

    def _rows_to_concepts(self, row_ids: list[int]) -> dict[int, int]:
        if not row_ids:
            return {}
        placeholders = ",".join("?" * len(row_ids))
        cur = self._conn.execute(f"SELECT row_id, concept_id FROM terms WHERE row_id IN ({placeholders})", row_ids)
        return {row["row_id"]: row["concept_id"] for row in cur}

    def _materialize(
        self,
        order: list[int],
        scores: dict[int, float],
        query_text: str,
        domain_filter: Optional[str],
        include_relationships: bool,
    ) -> list[ConceptMatch]:
        if not order:
            return []
        placeholders = ",".join("?" * len(order))
        rows = {
            row["concept_id"]: row
            for row in self._conn.execute(
                f"SELECT {_CONCEPT_COLS} FROM concepts WHERE concept_id IN ({placeholders})", order
            )
        }
        out: list[ConceptMatch] = []
        for concept_id in order:  # preserve score-desc order
            row = rows.get(concept_id)
            if row is None:
                continue
            if domain_filter and row["domain_id"] != domain_filter:
                continue
            out.append(self._to_match(row, scores[concept_id], query_text, include_relationships))
        return out

    @staticmethod
    def _to_match(row: sqlite3.Row, score: float, matched_entity: str, include_relationships: bool) -> ConceptMatch:
        return ConceptMatch(
            concept_id=int(row["concept_id"]),
            concept_name=row["concept_name"],
            domain_id=row["domain_id"],
            vocabulary_id=row["vocabulary_id"] or "",
            standard_concept=row["standard_concept"] or "",
            concept_class_id=row["concept_class_id"] or "",
            concept_code=row["concept_code"] or "",
            valid_start_date=row["valid_start_date"] or "",
            valid_end_date=row["valid_end_date"] or "",
            invalid_reason=row["invalid_reason"],
            similarity_score=min(1.0, max(0.0, score)),
            matched_entity=matched_entity,
            parent_concept_id=row["parent_concept_id"] if include_relationships else None,
            relationship_types=_parse_json_list(row["relationship_types"]) if include_relationships else [],
        )


def _parse_json_list(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return value if isinstance(value, list) else []
