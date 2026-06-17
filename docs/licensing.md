# Provenance & licensing

!!! danger "Do not redistribute built artifacts"
    A built `index.turbovec` / `concepts.db` embeds the literal source descriptions of the
    OMOP vocabularies it was built from. Those descriptions are licence-encumbered. **Do
    not publish or redistribute built artifacts**, and do not commit them to a repository.

## Two separate licences

| Layer | Licence |
| --- | --- |
| concept-omcp **code** (this repository) | Apache-2.0 — see [LICENSE](https://github.com/fastomop/concept-omcp/blob/main/LICENSE) |
| OMOP **vocabulary data** (what you load) | the source vocabularies' own licences — **your responsibility** |

The Apache-2.0 licence grants you broad rights over the *code*. It says nothing about the
vocabulary content, which you obtain separately from [Athena](https://athena.ohdsi.org) and
use under the terms you accept there.

## Bring-Your-Own-Vocab

Because the vocabulary content cannot be redistributed, concept-omcp ships **no vocabulary
data**. You:

1. Download an OMOP bundle from Athena, accepting the source licences at download time.
2. Build the artifacts locally with `concept-omcp build --omop`.
3. Keep the artifacts to yourself — they inherit the source vocabularies' restrictions.

## Per-vocabulary posture

This is an informal summary, **not legal advice**. Confirm the current terms with each
vocabulary's steward and your institution's licensing office before any redistribution.

| Vocabulary | Posture |
| --- | --- |
| **SNOMED CT** | SNOMED International Affiliate Licence. Distributing SNOMED-containing content requires being an Affiliate, sub-licensing downstream users, and (in non-member territories) fees. The single biggest blocker to redistribution. |
| **LOINC** | Regenstrief LOINC licence: free to use with attribution; **no derivative standards**; redistribution conditions apply. |
| **ICD-O-3** | WHO classification; WHO terms govern reuse and redistribution. |
| **RxNorm**, **RxNorm Extension** | Largely permissive (NLM); some included sources carry their own terms. |
| **OPCS4** | UK NHS/Crown terms apply. |
| **NAACCR**, **UK Biobank**, others | Each carries its own terms as bundled by Athena. |
| **OMOP-created / standard housekeeping concepts** | The most permissive layer. |
| **CPT-4** | The usual AMA blocker — **absent** from the corpus this tool targets. |

OHDSI's vocabulary team explicitly asks that vocabularies **not** be extracted and
redistributed. A public Hugging Face / GitHub download of built artifacts cannot satisfy
these terms, which is why concept-omcp is code-only.

## What this means in practice

- ✅ Run concept-omcp internally against vocabularies you are licensed to use.
- ✅ Share the *code* (it is Apache-2.0).
- ❌ Publish, mirror, or hand someone the built `index.turbovec` / `concepts.db`.
- ❓ A prebuilt, licence-permissive *subset* (RxNorm / LOINC / OMOP-created) for zero-build
  startup is a possible future addition — see the project's deferred work — but only after
  confirming the conservative reading above with the relevant stewards.
