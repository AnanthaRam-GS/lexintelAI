# Bulk Corpus Quality Audit

Run ID: `bulk_20260904_000000_stagea`

Status: pending human audit.

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
- court/date metadata accuracy: correct / determinate audited records
- text usability rate: usable / reviewed records
- duplicate/noise rate: no duplicate or noise / reviewed records
- RAG suitability rate: accept / reviewed records
- human correction rate and uncertainty rate

Initial metrics are pending/not_available until explicit human decisions are applied.

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
