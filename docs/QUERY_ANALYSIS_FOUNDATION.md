# Query Analysis Foundation

Phase 0 Step 0.6A adds a deterministic, offline query-understanding layer for
raw Indian criminal-law questions. It produces a structured representation that
can be reused by retrieval, RAG prompting, professional brief generation, and
future model-based NER or section prediction.

This foundation does not call an LLM, load embedding models, predict legal
entities, infer missing sections, tune retrieval, or change the frozen retrieval
configuration.

## Public API

Use `backend.app.services.query_analysis.analyze_legal_query(query: str)`.

The function returns `LegalQueryAnalysis` with version
`legalai-query-analysis-v1`. The original query is preserved exactly and the
normalized query is conservative: Unicode normalization, whitespace collapse,
safe section notation normalization, and punctuation spacing cleanup.

## Schema Contract

The schema lives in `backend/app/schemas/query_analysis.py`.

The main fields are:

- `original_query`: exact raw input.
- `normalized_query`: deterministic normalized text.
- `explicit_statutes`: explicit statute mentions only.
- `explicit_sections`: explicit section references, with conservative statute
  association when the statute appears next to the section block.
- `explicit_legal_terms`: extracted procedural posture and deterministic
  offence-family hints.
- `dates` and `date_ranges`: explicit dates or transition date phrases.
- `court_mentions`: explicit court references.
- `procedural_posture`: controlled procedural-posture signals.
- `offence_family_hints`: deterministic taxonomy hints.
- `legal_regime` and `legal_regime_evidence`: delegated to the existing
  `legal_regime` resolver.
- `entities`: intentionally empty in 0.6A.
- `predicted_sections`: intentionally empty in 0.6A.
- `warnings`: conservative ambiguity and conflict markers.

Each extracted signal stores `value`, `normalized`, `source`, optional `span`,
and `confidence`. Current sources are `explicit` and
`deterministic_inference`; `model` is reserved for later phases.

## Deterministic Extractors

Supported explicit statutes include IPC, CrPC, BNS, BNSS, NDPS Act, POCSO Act,
SC/ST Act, and Evidence Act.

Section extraction supports common section notation such as `Section 302`,
`Sec. 302`, `S.302`, multi-section lists, and subsection forms such as
`351(3)`. The analyzer does not associate a section with a statute unless a
nearby explicit statute mention is present.

Date extraction covers the transition date forms used by the project, including
`01.07.2024`, `1 July 2024`, `July 1, 2024`, year mentions, and phrases such as
`before July 2024`, `after July 2024`, `post July 2024`, and
`after commencement of new criminal laws`.

Court extraction covers Supreme Court, High Court, named High Courts, trial
court, Sessions Court, District Court, and Special Court.

Procedural posture uses a closed deterministic vocabulary:
`anticipatory_bail`, `regular_bail`, `default_bail`, `fir_quashing`,
`quashing_petition`, `criminal_appeal`, `revision`, `trial`, `investigation`,
`cognizance`, `charge_sheet`, and `final_report`.

Offence-family hints use the existing project taxonomy:
`homicide`, `hurt_and_assault`, `theft`, `cheating`,
`criminal_breach_of_trust`, `kidnapping`, `sexual_offences`, `dowry`,
`conspiracy`, `narcotics`, and `other`. Multiple hints are allowed; none is
forced when the query is underspecified.

## Warnings

The analyzer emits conservative warnings:

- `section_without_explicit_statute`
- `conflicting_old_new_statutes`
- `ambiguous_date_context`
- `multiple_offence_families`

Warnings are diagnostic only. They do not trigger retrieval tuning or section
prediction.

## Retrieval Boundary

The analyzer reuses `backend.app.services.legal_regime.resolve_legal_regime`.
It does not replace that resolver and does not enable legal-regime ranking,
query expansion, or metadata-aware reranking. Tests assert that the frozen
retrieval decision remains `RETAIN_UNTUNED_HYBRID_RERANK` and that experimental
retrieval features remain disabled.

## Inspection CLI

For manual inspection:

```bash
.venv/bin/python backend/scripts/inspect_query_analysis.py --query "Can I get anticipatory bail under Section 438 CrPC for a 2023 IPC case?"
```

The CLI prints the `LegalQueryAnalysis` object as JSON and performs no network,
model, vector-index, or retrieval-evaluation work.
