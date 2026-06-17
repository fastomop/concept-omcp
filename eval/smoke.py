"""Smoke test: drive the REAL artifacts (4.5M-term turbovec index + SQLite).

The unit/integration suites exercise only a handful of synthetic rows; this is the
first run of ConceptStore against the actual built artifacts. It loads the store
from settings (artifact_dir), fires a set of known clinical queries at a LOW
similarity floor so the raw top-5 and their scores are always visible, and prints
them for eyeballing. This is the gate to clear before the fastomop cutover.

Run on whichever box holds artifacts/ (needs the MedEmbed model available):
    .venv/bin/python eval/smoke.py
"""

from __future__ import annotations

import time

from concept_omcp.settings import settings
from concept_omcp.store import ConceptStore

# (query, expected OMOP domain) — common standard concepts certain to be in the vocab.
PROBES = [
    ("type 2 diabetes mellitus", "Condition"),
    ("metformin", "Drug"),
    ("chronic obstructive pulmonary disease", "Condition"),
    ("myocardial infarction", "Condition"),
    ("appendectomy", "Procedure"),
    ("CT scan of upper abdomen", "Procedure"),
    ("hemoglobin A1c", "Measurement"),
    ("aspirin", "Drug"),
]


def _line(m) -> str:
    return f"      [{(m.similarity_score or 0):.3f}] {m.concept_id:>8}  {m.concept_name}  ({m.domain_id})"


def main() -> None:
    print(f"Loading artifacts from {settings.artifact_dir} ...")
    t0 = time.time()
    store = ConceptStore.load(settings)
    print(f"Loaded in {time.time() - t0:.1f}s (model + turbovec index + sqlite)\n")

    passed = 0
    first_id = None
    for query, expected in PROBES:
        t = time.time()
        matches = store.search_concepts(query, top_k=5, min_similarity=0.0)
        dt = (time.time() - t) * 1000.0
        for m in matches:  # hard invariant: scores stay in [0, 1]
            assert 0.0 <= (m.similarity_score or 0.0) <= 1.0
        hit = any(m.domain_id == expected for m in matches)
        passed += hit
        print(f"[{'PASS' if hit else 'WARN'}] {query!r} -> expect {expected}  ({dt:.0f} ms)")
        for m in matches:
            print(_line(m))
        if first_id is None and matches:
            first_id = matches[0].concept_id
        print()

    print("get_concept_by_id round-trip:")
    one = store.get_concept_by_id(first_id) if first_id is not None else None
    assert one is None or one.concept_id == first_id
    print(f"      {first_id} -> {one.concept_name} ({one.domain_id})\n" if one else "      (no id to round-trip)\n")

    print("find_concepts_by_relationship(['May treat'], limit=5):")
    rel = store.find_concepts_by_relationship(["May treat"], limit=5)
    print(f"      {len(rel)} concepts:")
    for m in rel:
        print(f"        {m.concept_id:>8}  {m.concept_name}  ({m.domain_id})  rels={m.relationship_types[:3]}")
    print()

    print("hybrid exact-text fallback ('Metformin'):")
    exact = store.search_concepts("Metformin", top_k=3, min_similarity=0.0)
    print(_line(exact[0]) if exact else "      NONE")
    print()

    print(f"=== {passed}/{len(PROBES)} probes hit the expected domain in top-5 ===")
    print("Eyeball: is the right concept at/near the top, and what score does it get?")
    print("A correct match scoring just under fastomop's 0.5 floor signals threshold recalibration, not a bug.")


if __name__ == "__main__":
    main()
