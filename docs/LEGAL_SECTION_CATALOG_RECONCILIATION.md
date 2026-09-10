# Legal Section Catalog Reconciliation

## Purpose

This reconciliation expands the bounded Phase 0 legal-section catalog only enough to cover the approved human section-review judgments. It does not materialize gold labels and does not change section prediction, retrieval, NER, or ranking behavior.

## Correction

The approved human-review arithmetic is:

- examples: 36
- primary labels: 36
- relevant labels: 24
- uncertain labels: 1
- positive labels: 60
- total annotated including uncertain: 61
- zero-positive examples: `sec-q026`, `sec-q027`, `sec-q035`

## Catalog Delta

The previous catalog contained 44 entries. This reconciliation adds exactly 18 unique provisions, for a reconciled catalog size of 62.

| Statute | Section | Canonical name |
| --- | --- | --- |
| IPC | 394 | Voluntarily causing hurt in committing robbery |
| IPC | 408 | Criminal breach of trust by clerk or servant |
| IPC | 361 | Kidnapping from lawful guardianship |
| POCSO Act | 7 | Sexual assault |
| NDPS Act | 37 | Offences to be cognizable and non-bailable |
| NDPS Act | 36A(4) | Special Court procedure for investigation period |
| IPC | 380 | Theft in dwelling house |
| IPC | 378 | Theft |
| BNS | 117 | Voluntarily causing grievous hurt |
| BNS | 116 | Grievous hurt |
| IPC | 375 | Rape |
| SC/ST Act | 18 | Section 438 of the Code not to apply |
| BNS | 358 | Repeal and savings |
| BNSS | 531 | Repeal and savings |
| CrPC | 154(3) | Information to Superintendent of Police |
| BNSS | 173(4) | Information to Superintendent of Police |
| CrPC | 437 | Bail in non-bailable offence |
| BNSS | 187(3) | Investigation not completed within twenty-four hours |

## Verification Sources

The additions were verified against official Government of India statutory sources, including India Code pages for the IPC, CrPC, NDPS Act, POCSO Act, and SC/ST Act, and the Ministry of Home Affairs official new-criminal-laws materials for BNS and BNSS provisions.

## Non-Changes

`data/structured/manifests/legal_section_eval.json` remains a pending human-review manifest with 36 examples, 0 reviewed examples, and empty `gold_sections`.

`backend/app/services/legal_section_prediction.py` remains unchanged. The reconciliation is catalog coverage only; it does not alter deterministic scoring, ranking, regime logic, query-analysis integration, retrieval, or NER behavior.

## Deterministic Coverage Validator

Run:

```bash
python3 backend/scripts/validate_section_catalog_coverage.py
```

Expected result:

- catalog entries: 62
- approved unique provisions checked: 18
- missing: 0
- duplicates: 0
- normalization conflicts: 0
- unauthorized additions: 0

## Status

CATALOG COVERAGE RECONCILED — RERUN 0.7A-H2 WITH CORRECTED TOTALS
