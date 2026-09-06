# Bulk Corpus Quality Audit

Run ID: `bulk_20260904_000000_stagea`

Status: completed human audit for the 50-record stratified sample.

Corpus size: 249
Sample target: 50
Actual sample size: 50
Sampling strategy/version: `bulk-quality-audit-stratified-v1`
Random seed: `legalai-phase0-step0.4l`

## RAG Suitability Definition

A case is suitable for the future global criminal-law RAG corpus when it is a genuinely relevant criminal/legal judgment, has usable text, preserves provenance, is not a semantic or byte duplicate, has enough legal substance for retrieval, and has metadata that is usable or correctable. HTML/text fallback records may be suitable when the stored judgment text is trustworthy.

## Human Audit Fields

criminal_relevance, document_type, offence_family_review, legal_regime_review, court_metadata_review, date_metadata_review, text_quality, duplicate_or_noise, rag_suitability, corrected values, reviewer, reviewed_at, notes.

## Metric Definitions

- criminal relevance precision: human relevant / determinate audited records
- document-type precision: judgment / determinate audited records
- offence-family accuracy: confirmed / determinate audited records
- legal-regime accuracy: confirmed / determinate audited records
- court metadata accuracy: correct / determinate audited records
- exact decision-date accuracy/completeness: automated exact decision date correct / determinate audited records
- year accuracy: automated year matches human corrected exact-date year / records with both values
- text usability rate: usable / reviewed records
- duplicate/noise problem rate: duplicate, irrelevant_noise, provider_wrapper_only, or other problem / reviewed records
- clean record rate: no duplicate or noise / reviewed records
- RAG suitability rate: accept / reviewed records
- any, offence-family, legal-regime, court, date, and label correction rates
- uncertainty rate

The remaining 199 bulk records are unaudited/pending. These metrics describe only the reviewed stratified sample unless explicitly labeled as sample-based estimates.

## Human Decision Totals

- reviewed: 50 / 50
- pending sample records: 0
- RAG accept: 42
- RAG reject: 7
- RAG needs_review: 1

## Measured Metrics

| Metric | Numerator | Denominator | Percentage |
| --- | ---: | ---: | ---: |
| criminal relevance precision | 43 | 50 | 86.0 |
| document type precision | 47 | 50 | 94.0 |
| offence-family accuracy | 33 | 42 | 78.57 |
| legal-regime accuracy | 48 | 50 | 96.0 |
| court metadata accuracy | 47 | 47 | 100.0 |
| exact decision-date accuracy/completeness | 0 | 50 | 0.0 |
| year accuracy | 49 | 50 | 98.0 |
| text usability | 50 | 50 | 100.0 |
| duplicate/noise problem rate | 7 | 50 | 14.0 |
| clean record rate | 43 | 50 | 86.0 |
| RAG suitability rate | 42 | 50 | 84.0 |
| any human correction rate | 50 | 50 | 100.0 |
| offence-family correction rate | 9 | 50 | 18.0 |
| legal-regime correction rate | 2 | 50 | 4.0 |
| court metadata correction rate | 0 | 50 | 0.0 |
| date correction rate | 50 | 50 | 100.0 |
| label correction rate | 11 | 50 | 22.0 |
| uncertainty rate | 11 | 450 | 2.44 |

## Correction Matrices

### Offence Family

| Automated | Human | Count |
| --- | --- | ---: |
| cheating_and_fraud | cheating_and_fraud | 1 |
| cheating_and_fraud | other | 1 |
| conspiracy_common_intention | cheating_and_fraud | 1 |
| conspiracy_common_intention | conspiracy_common_intention | 2 |
| conspiracy_common_intention | homicide | 1 |
| criminal_breach_of_trust | cheating_and_fraud | 1 |
| criminal_breach_of_trust | criminal_breach_of_trust | 2 |
| dowry_and_domestic_cruelty | dowry_and_domestic_cruelty | 5 |
| homicide | homicide | 5 |
| homicide | hurt_and_assault | 1 |
| hurt_and_assault | hurt_and_assault | 2 |
| kidnapping | kidnapping | 1 |
| kidnapping | sexual_offences | 1 |
| narcotics_related | narcotics_related | 5 |
| other | cheating_and_fraud | 1 |
| other | homicide | 1 |
| other | other | 6 |
| other | sexual_offences | 1 |
| sexual_offences | sexual_offences | 2 |
| theft_and_robbery | theft_and_robbery | 2 |

### Legal Regime

| Automated | Human | Count |
| --- | --- | ---: |
| bns_bnss | bns_bnss | 5 |
| ipc_crpc | ipc_crpc | 37 |
| mixed_or_transition | bns_bnss | 1 |
| mixed_or_transition | mixed_or_transition | 4 |
| unknown | ipc_crpc | 1 |
| unknown | unknown | 2 |

## Duplicate And Noise Findings

- CIC RTI/noise cluster rejected: 27724816, 100481688, 131426670
- Patna duplicate pair: retained 194768350, rejected duplicate 70072092
- Bombay duplicate pair: retained 186425747, rejected duplicate 105760653
- Other non-criminal/noise rejections: 125812430, 120980289

## Date Metadata Findings

- Explicit corrected dates were recorded separately from provider date metadata.
- 120980289 has a provider title/date mismatch; human corrected decision date is 2024-03-06.

## Metric Exclusions

- Offence-family accuracy denominator: 42 included; 7 RAG-rejected non-criminal/noise records and 1 uncertain non-rejected records excluded.
- Legal-regime accuracy denominator includes rejected records where regime remained determinately reviewable; uncertain regime reviews would be excluded.
- Uncertain values are excluded from correctness denominators and counted in the uncertainty-rate numerator.
- Rejected/non-criminal records are included for criminal relevance, document type, legal regime, exact-date, text, duplicate/noise, and RAG suitability metrics, but excluded from offence-family accuracy because offence family is not meaningful for non-criminal/noise records.

## Sample Distribution

### offence_family

| Value | Corpus Count | Sample Count |
| --- | ---: | ---: |
| cheating_and_fraud | 12 | 2 |
| conspiracy_common_intention | 19 | 4 |
| criminal_breach_of_trust | 13 | 3 |
| dowry_and_domestic_cruelty | 28 | 6 |
| homicide | 29 | 6 |
| hurt_and_assault | 12 | 2 |
| kidnapping | 17 | 3 |
| narcotics_related | 23 | 6 |
| other | 40 | 13 |
| sexual_offences | 35 | 2 |
| theft_and_robbery | 21 | 3 |

### legal_regime

| Value | Corpus Count | Sample Count |
| --- | ---: | ---: |
| bns_bnss | 13 | 5 |
| ipc_crpc | 214 | 37 |
| mixed_or_transition | 17 | 5 |
| unknown | 5 | 3 |

### temporal_track

| Value | Corpus Count | Sample Count |
| --- | ---: | ---: |
| current_transition | 30 | 10 |
| landmark_historical | 10 | 3 |
| recent_ipc | 209 | 37 |

### court

| Value | Corpus Count | Sample Count |
| --- | ---: | ---: |
| district_or_sessions | 15 | 7 |
| high_court | 196 | 34 |
| supreme_court | 32 | 6 |
| unknown | 6 | 3 |

## Human Review Commands

Apply one explicit decision:

```bash
python3 backend/scripts/review_bulk_quality_audit.py apply --source-id SAMPLE_SOURCE_ID --reviewer Ananthu --criminal-relevance correct --document-type judgment --offence-family-review confirmed --legal-regime-review confirmed --court-metadata-review correct --date-metadata-review correct --text-quality usable --duplicate-or-noise no --rag-suitability accept --notes "bounded human note"
```

Regenerate packet and metrics:

```bash
python3 backend/scripts/review_bulk_quality_audit.py generate
python3 backend/scripts/review_bulk_quality_audit.py summary
```
