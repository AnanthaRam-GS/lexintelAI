# Deterministic Legal NER Baseline

## Evaluation Set

36 human-reviewed examples with 89 gold entities from `legal_ner_gold_template.json`.

## Evaluated System

Deterministic query-analysis / legal-NER bridge only. Learned NER remains disabled.

## Matching Policy

Primary correctness requires exact character start, exact character end, and canonical entity type.

## Overall Metrics

- TP: 65
- FP: 11
- FN: 24
- Precision: 0.855263
- Recall: 0.730337
- F1: 0.787879

## Per-Type Metrics

| Type | Gold | Pred | TP | FP | FN | P | R | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| PERSON | 3 | 0 | 0 | 0 | 3 | 0.0 | 0.0 | 0.0 |
| ORGANIZATION | 4 | 0 | 0 | 0 | 4 | 0.0 | 0.0 | 0.0 |
| COURT | 11 | 11 | 7 | 4 | 4 | 0.636364 | 0.636364 | 0.636364 |
| LOCATION | 4 | 0 | 0 | 0 | 4 | 0.0 | 0.0 | 0.0 |
| DATE | 4 | 5 | 2 | 3 | 2 | 0.4 | 0.5 | 0.444444 |
| STATUTE | 16 | 16 | 16 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| SECTION | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| CASE_CITATION | 2 | 1 | 1 | 0 | 1 | 1.0 | 0.5 | 0.666667 |
| CASE_NAME | 1 | 0 | 0 | 0 | 1 | 0.0 | 0.0 | 0.0 |
| LEGAL_PROCEDURE | 12 | 11 | 11 | 0 | 1 | 1.0 | 0.916667 | 0.956522 |
| OFFENCE | 12 | 12 | 8 | 4 | 4 | 0.666667 | 0.666667 | 0.666667 |
| LEGAL_ROLE | 9 | 9 | 9 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| POLICE_STATION | 2 | 2 | 2 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| FIR_NUMBER | 1 | 1 | 1 | 0 | 0 | 1.0 | 1.0 | 1.0 |

## Span-Only Diagnostic

| TP | FP | FN | Precision | Recall | F1 |
|---:|---:|---:|---:|---:|---:|
| 65 | 11 | 24 | 0.855263 | 0.730337 | 0.787879 |

## Zero-Entity Precision Guardrails

- `ner-q026`: 0 false positives
- `ner-q036`: 0 false positives

## Error Analysis

Total FP/FN error records: 35.

- BOUNDARY_MISMATCH: 16
- MISSING_ENTITY_TYPE: 16
- SPURIOUS_ENTITY: 3

## Strengths

- STATUTE: measured F1 1.0 on 16 gold spans
- SECTION: measured F1 1.0 on 8 gold spans
- LEGAL_PROCEDURE: measured F1 0.956522 on 12 gold spans
- LEGAL_ROLE: measured F1 1.0 on 9 gold spans
- POLICE_STATION: measured F1 1.0 on 2 gold spans
- FIR_NUMBER: measured F1 1.0 on 1 gold spans

## Gaps

- PERSON: weak/no deterministic coverage with F1 0.0 on 3 gold spans
- ORGANIZATION: weak/no deterministic coverage with F1 0.0 on 4 gold spans
- COURT: partial coverage with F1 0.636364 on 11 gold spans
- LOCATION: weak/no deterministic coverage with F1 0.0 on 4 gold spans
- DATE: partial coverage with F1 0.444444 on 4 gold spans
- CASE_CITATION: partial coverage with F1 0.666667 on 2 gold spans
- CASE_NAME: weak/no deterministic coverage with F1 0.0 on 1 gold spans
- OFFENCE: partial coverage with F1 0.666667 on 12 gold spans

## Important Example Findings

- `ner-q001`: all gold entities matched exactly; no false positives
- `ner-q006`: all gold entities matched exactly; no false positives
- `ner-q008`: 1 false negative(s): State of Maharashtra v. Arjun Singh
- `ner-q012`: all gold entities matched exactly; no false positives
- `ner-q016`: 1 false positive(s): false promise; 1 false negative(s): Alpha Traders
- `ner-q021`: 2 false negative(s): Suresh, Meena
- `ner-q026`: all gold entities matched exactly; no false positives
- `ner-q030`: 1 false negative(s): common intention
- `ner-q033`: 1 false negative(s): Zenith Logistics
- `ner-q036`: all gold entities matched exactly; no false positives

## Limitations

- only 36 examples
- independently authored short legal queries
- one human reviewer
- synthetic/legal-style distribution
- no judgment-document NER evaluation yet
- no learned model comparison yet

## Recommendation

HYBRID RULES + LEARNED MODEL JUSTIFIED
