"""Seed queries for the retrieval-accuracy smoke harness.

Each entry: (query, expected_domain). expected_domain is None where the source
probe had no hard label. Drives eval/smoke.py against a built index.
"""

# From test_retrieval.py — 20 queries with expected domains.
LABELED_QUERIES: list[tuple[str, str]] = [
    ("type 2 diabetes mellitus", "Condition"),
    ("hypertension", "Condition"),
    ("atrial fibrillation", "Condition"),
    ("myocardial infarction", "Condition"),
    ("chronic kidney disease", "Condition"),
    ("COPD", "Condition"),
    ("SLE", "Condition"),
    ("ARDS", "Condition"),
    ("metformin", "Drug"),
    ("lisinopril", "Drug"),
    ("aspirin", "Drug"),
    ("atorvastatin", "Drug"),
    ("hemoglobin A1c", "Measurement"),
    ("troponin", "Measurement"),
    ("serum creatinine", "Measurement"),
    ("coronary angiography", "Procedure"),
    ("mechanical ventilation", "Procedure"),
    ("dialysis", "Procedure"),
    ("shortness of breath", "Observation"),
    ("smoking", "Observation"),
]

# From test_procedures.py — 20 real procedure descriptions (expected Procedure).
PROCEDURE_QUERIES: list[tuple[str, str]] = [
    ("67-Gallium scintigraphy (per session)", "Procedure"),
    ("Radionuclide therapy with Lu177-DOTA-Tate (per session)", "Procedure"),
    ("Sonography of superficial masses (per session)", "Procedure"),
    ("Preoperative anesthesiological examination (per session)", "Procedure"),
    ("Gynecological check-up (per session)", "Procedure"),
    ("Collection of material for in-vitro diagnostics (other)", "Procedure"),
    ("Histological assessment of specimens from cytological material (cell block) (per outpatient visit)", "Procedure"),
    ("Semiquantitative immunohistochemistry (per outpatient visit)", "Procedure"),
    ("Biopsy", "Procedure"),
    ("Treated with gamma knife", "Procedure"),
    ("Surgical exploration with or without biopsy", "Procedure"),
    ("Treated with radioactive iodine", "Procedure"),
    ("Unspecified caesaerean section", "Procedure"),
    ("Local ablative treatment with or without biopsy", "Procedure"),
    ("Surgical removal of tumor and parts of or the entire organ(s)", "Procedure"),
    ("Surgical removal of only tumor", "Procedure"),
    ("Surgical removal of lymph nodes", "Procedure"),
    ("Transvesical resection", "Procedure"),
    ("Larger specialised surgical procedures", "Procedure"),
    ("Mastectomy with removal of lymph nodes", "Procedure"),
]

SEED_QUERIES: list[tuple[str, str]] = LABELED_QUERIES + PROCEDURE_QUERIES
