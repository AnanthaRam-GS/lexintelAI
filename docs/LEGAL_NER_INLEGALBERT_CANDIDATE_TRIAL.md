# InLegalBERT Silver Candidate NER Trial

Candidate: `evolawyer/inlegalbert-sc-ner-silver`.

Decision: **LEARNED CANDIDATE REJECTED**.

## Candidate Identity

- Revision: `f7d54eb91551da4fb8a6329d1d871559c04e1832`
- Architecture: `['BertForTokenClassification']`
- Tokenizer: `BertTokenizer`
- Parameters: 108912411
- License metadata: `apache-2.0`
- Local cache identifier: `huggingface_hub/snapshots/snapshots/f7d54eb91551da4fb8a6329d1d871559c04e1832`

## Primary Metrics

| Metric | D0 Deterministic | L1 Learned | H1 Hybrid |
|---|---:|---:|---:|
| Prediction count | 76 | 18 | 76 |
| TP | 65 | 18 | 65 |
| FP | 11 | 0 | 11 |
| FN | 24 | 71 | 24 |
| Precision | 0.855263 | 1.0 | 0.855263 |
| Recall | 0.730337 | 0.202247 | 0.730337 |
| F1 | 0.787879 | 0.336449 | 0.787879 |
| Span-only F1 | 0.787879 | 0.336449 | 0.787879 |

## Merge Diagnostics

- deterministic_protected_count: 47
- learned_candidates_considered: 25
- learned_accepted: 17
- learned_suppressed_by_confidence: 7
- learned_suppressed_by_protected_overlap: 0
- learned_suppressed_by_duplicate: 17
- learned_boundary_replacements: 0
- same_span_conflicts: 0
- overlap_conflicts: 1
- other_suppressions: 0

## Latency

- model_load_time_ms: 2834.374
- mean_inference_ms: 13.398
- median_inference_ms: 12.935
- p95_inference_ms: 13.387
- max_inference_ms: 31.607
- total_inference_ms: 482.341
- mean_merge_ms: 0.004

## Label Mapping

| Raw label | Canonical label | Status |
|---|---|---|
| CASE_CITATION | CASE_CITATION | mapped |
| COURT | COURT | mapped |
| DATE | DATE | mapped |
| GPE | LOCATION | mapped |
| JUDGE | PERSON | mapped_actor |
| LAWYER | PERSON | mapped_actor |
| ORG | ORGANIZATION | mapped |
| OTHER_PERSON | PERSON | mapped |
| PETITIONER | PERSON | mapped_actor |
| PROVISION | SECTION | mapped |
| RESPONDENT | PERSON | mapped_actor |
| STATUTE | STATUTE | mapped |
| WITNESS | PERSON | mapped_actor |

## Target Gaps

- PERSON: D0 F1 0.0, L1 F1 0.0, H1 F1 0.0
- ORGANIZATION: D0 F1 0.0, L1 F1 0.0, H1 F1 0.0
- LOCATION: D0 F1 0.0, L1 F1 0.0, H1 F1 0.0
- CASE_NAME: D0 F1 0.0, L1 F1 0.0, H1 F1 0.0

## Shared Types

- COURT: D0 F1 0.636364, L1 F1 0.0, H1 F1 0.636364
- DATE: D0 F1 0.444444, L1 F1 0.0, H1 F1 0.444444
- CASE_CITATION: D0 F1 0.666667, L1 F1 1.0, H1 F1 0.666667
- OFFENCE: D0 F1 0.666667, L1 F1 0.0, H1 F1 0.666667

## Protected Regression Check

- Regression count: 0
- STATUTE: D0 TP/FP 16/0; H1 TP/FP 16/0
- SECTION: D0 TP/FP 8/0; H1 TP/FP 8/0
- LEGAL_ROLE: D0 TP/FP 9/0; H1 TP/FP 9/0
- POLICE_STATION: D0 TP/FP 2/0; H1 TP/FP 2/0
- FIR_NUMBER: D0 TP/FP 1/0; H1 TP/FP 1/0
- LEGAL_PROCEDURE: D0 TP/FP 11/0; H1 TP/FP 11/0

## Zero-Entity Guardrails

- ner-q026: L1 FP 0; H1 FP 0
- ner-q036: L1 FP 0; H1 FP 0

## New TP/FP Analysis

- learned_filled_fn: 0
- learned_filled_fn by type: `{'PERSON': 0, 'ORGANIZATION': 0, 'LOCATION': 0, 'COURT': 0, 'DATE': 0, 'CASE_CITATION': 0, 'other': 0}`
- learned_only_new_fp: 0
- hybrid_new_fp: 0

## Error Taxonomy

- L1: `{'MISSING_ENTITY_TYPE': 71, 'UNMAPPED_MODEL_LABEL': 0}`
- H1: `{'BOUNDARY_MISMATCH': 16, 'MISSING_ENTITY_TYPE': 16, 'SPURIOUS_ENTITY': 3, 'UNMAPPED_MODEL_LABEL': 0}`

## Important Examples

- ner-q005: gold 3; D0 1; L1 0; H1 1; raw labels COURT, ORG
- ner-q008: gold 3; D0 2; L1 2; H1 2; raw labels PROVISION, STATUTE
- ner-q010: gold 2; D0 2; L1 0; H1 2; raw labels none
- ner-q016: gold 2; D0 2; L1 0; H1 2; raw labels none
- ner-q021: gold 3; D0 1; L1 0; H1 1; raw labels none
- ner-q025: gold 2; D0 1; L1 0; H1 1; raw labels none
- ner-q032: gold 2; D0 1; L1 0; H1 1; raw labels none
- ner-q033: gold 3; D0 2; L1 0; H1 2; raw labels none

## Boundary Findings

- COURT: exact 7; boundary mismatches 4
- DATE: exact 2; boundary mismatches 2
- PERSON: exact 0; boundary mismatches 0
- ORGANIZATION: exact 0; boundary mismatches 0
- LOCATION: exact 0; boundary mismatches 0

## Limitations

- silver-labelled training data
- not human-gold training annotations
- Supreme Court judgment-oriented distribution
- potential ORG/GPE ambiguity
- potential entity-boundary drift
- potential positional bias
- only 36 gold examples
- one reviewer
- short synthetic/legal-style queries
- no fine-tuning
- no judgment-document evaluation
- no statistical superiority claim
