# General BERT Candidate NER Trial

Candidate: `dslim/bert-base-NER`.

Decision: **GENERAL NER CANDIDATE REJECTED**.

T1 vs T2 decision: **NEITHER CANDIDATE JUSTIFIED**.

## Candidate Identity

- Revision: `d1a3e8f13f8c3566299d95fcfc9a8d2382a9affc`
- Architecture: `['BertForTokenClassification']`
- Tokenizer: `BertTokenizer`
- Parameters: 107726601
- License metadata: `mit`
- Local cache identifier: `huggingface_hub/models--dslim--bert-base-NER/snapshots/d1a3e8f13f8c3566299d95fcfc9a8d2382a9affc`

## Primary Metrics

| Metric | D0 Deterministic | L2 General BERT | H2 General Hybrid |
|---|---:|---:|---:|
| Prediction count | 76 | 42 | 95 |
| TP | 65 | 5 | 70 |
| FP | 11 | 37 | 25 |
| FN | 24 | 84 | 19 |
| Precision | 0.855263 | 0.119048 | 0.736842 |
| Recall | 0.730337 | 0.05618 | 0.786517 |
| F1 | 0.787879 | 0.076336 | 0.76087 |
| Span-only F1 | 0.787879 | 0.351145 | 0.76087 |

## Merge Diagnostics

- deterministic_protected_count: 47
- learned_candidates_considered: 43
- learned_accepted: 32
- learned_suppressed_by_confidence: 1
- learned_suppressed_by_protected_overlap: 6
- learned_suppressed_by_duplicate: 0
- learned_boundary_replacements: 0
- same_span_conflicts: 13
- overlap_conflicts: 10
- other_suppressions: 0

## Latency

- model_load_time_ms: 2696.671
- mean_inference_ms: 12.877
- median_inference_ms: 12.323
- p95_inference_ms: 12.878
- max_inference_ms: 31.793
- total_inference_ms: 463.586
- mean_merge_ms: 0.006

## Label Mapping

| Raw label | Canonical label | Status |
|---|---|---|
| LOC | LOCATION | mapped |
| MISC | None | unmapped |
| ORG | ORGANIZATION | mapped |
| PER | PERSON | mapped |

## Target Gaps

- PERSON: D0 F1 0.0, L2 F1 0.0, H2 F1 0.0
- ORGANIZATION: D0 F1 0.0, L2 F1 0.064516, H2 F1 0.2
- LOCATION: D0 F1 0.0, L2 F1 0.727273, H2 F1 0.888889
- CASE_NAME: D0 F1 0.0, L2 F1 0.0, H2 F1 0.0

## Shared Types

- COURT: D0 F1 0.636364, L2 F1 0.0, H2 F1 0.636364
- DATE: D0 F1 0.444444, L2 F1 0.0, H2 F1 0.444444
- CASE_CITATION: D0 F1 0.666667, L2 F1 0.0, H2 F1 0.666667
- OFFENCE: D0 F1 0.666667, L2 F1 0.0, H2 F1 0.666667

## Protected Regression Check

- Regression count: 0
- STATUTE: D0 TP/FP 16/0; H2 TP/FP 16/0
- SECTION: D0 TP/FP 8/0; H2 TP/FP 8/0
- LEGAL_ROLE: D0 TP/FP 9/0; H2 TP/FP 9/0
- POLICE_STATION: D0 TP/FP 2/0; H2 TP/FP 2/0
- FIR_NUMBER: D0 TP/FP 1/0; H2 TP/FP 1/0
- LEGAL_PROCEDURE: D0 TP/FP 11/0; H2 TP/FP 11/0

## Zero-Entity Guardrails

- ner-q026: L2 FP 0; H2 FP 0
- ner-q036: L2 FP 0; H2 FP 0

## New TP/FP Analysis

- learned_filled_fn: 5
- learned_filled_fn by type: `{'PERSON': 0, 'ORGANIZATION': 1, 'LOCATION': 4, 'COURT': 0, 'DATE': 0, 'CASE_CITATION': 0, 'other': 0}`
- learned_only_new_fp: 37
- hybrid_new_fp: 14

## Error Taxonomy

- L2: `{'BOUNDARY_MISMATCH': 31, 'MISSING_ENTITY_TYPE': 56, 'UNMAPPED_MODEL_LABEL': 12, 'WRONG_ENTITY_TYPE': 34}`
- H2: `{'BOUNDARY_MISMATCH': 37, 'MISSING_ENTITY_TYPE': 4, 'SPURIOUS_ENTITY': 3, 'UNMAPPED_MODEL_LABEL': 0}`

## Important Examples

- ner-q005: gold 3; D0 1; L2 5; H2 5; raw labels LOC, ORG, PER
- ner-q010: gold 2; D0 2; L2 1; H2 3; raw labels LOC
- ner-q016: gold 2; D0 2; L2 1; H2 3; raw labels ORG
- ner-q017: gold 3; D0 2; L2 1; H2 3; raw labels LOC
- ner-q021: gold 3; D0 1; L2 4; H2 5; raw labels PER
- ner-q022: gold 2; D0 1; L2 1; H2 2; raw labels LOC
- ner-q025: gold 2; D0 1; L2 2; H2 3; raw labels ORG
- ner-q032: gold 2; D0 1; L2 1; H2 2; raw labels LOC
- ner-q033: gold 3; D0 2; L2 1; H2 3; raw labels ORG

## Boundary Findings

- COURT: exact 7; boundary mismatches 4
- DATE: exact 2; boundary mismatches 2
- PERSON: exact 0; boundary mismatches 12
- ORGANIZATION: exact 2; boundary mismatches 8
- LOCATION: exact 8; boundary mismatches 0

## Limitations

- 36 examples only
- 89 gold entities
- one reviewer
- synthetic/legal-style queries
- generic NER training distribution
- no fine-tuning
- no judgment-document NER evaluation
- CASE_NAME not naturally represented by candidate taxonomy
- no significance claims
- potential entity-boundary drift
