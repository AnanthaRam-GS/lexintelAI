# Stage A 500-Case Bulk Pilot

Run ID: `bulk_20260904_000000_stagea`

Current checkpoint: R4 reached 225 cumulative reviewable records. The run stopped at the requested R4 target and did not continue toward 300.

## Gate Summary

| Gate | Target | New Reviewable | Cumulative | Acquisition Calls | Calls/Reviewable | Stop Reason |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| A1 | 50 | 50 | 50 | 319 | 6.38 | target_reached |
| A2 checkpoint | 75 | 12 | 62 | 381 | 31.75 | stopped_budget |
| R2 | 100 | 38 | 100 | 304 | 8.0 | target_reached |
| R3 | 150 | 50 | 150 | 384 | 7.68 | target_reached |
| R4 | 225 | 75 | 225 | 443 | 5.91 | target_reached |
| A3 | 300 | not run | 225 | not run | not run | stop_before_300 |

## API Accounting

| Endpoint | Incremental R4 | Cumulative Acquisition |
| --- | ---: | ---: |
| search | 20 | 86 |
| document | 171 | 748 |
| metadata | 171 | 746 |
| original_document | 81 | 251 |
| other | 0 | 0 |
| total | 443 | 1831 |

R4 calls/reviewable: 5.91. Cumulative acquisition calls/reviewable: 8.14. Recovery/maintenance requests remain separate: 62.

## Family Distribution

| Family | Before | R4 New | Cumulative | Target | Gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| homicide | 29 | 0 | 29 | 60 | 31 |
| hurt_and_assault | 3 | 9 | 12 | 55 | 43 |
| theft_and_robbery | 21 | 0 | 21 | 50 | 29 |
| cheating_and_fraud | 12 | 0 | 12 | 50 | 38 |
| criminal_breach_of_trust | 5 | 3 | 8 | 35 | 27 |
| kidnapping | 7 | 10 | 17 | 35 | 18 |
| sexual_offences | 19 | 8 | 27 | 55 | 28 |
| dowry_and_domestic_cruelty | 16 | 6 | 22 | 45 | 23 |
| conspiracy_common_intention | 7 | 7 | 14 | 45 | 31 |
| narcotics_related | 13 | 10 | 23 | 45 | 22 |
| other | 18 | 22 | 40 | 25 | 0 |

## Partition Yield

| Partition | Requests | Search | Document | Metadata | Original | New Reviewable | Rejects | Duplicates | Failures | Calls/Reviewable | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| bulk_recent_ipc_hurt_assault | 79 | 10 | 33 | 33 | 9 | 9 | 1 | 0 | 0 | 8.78 | pending |
| bulk_recent_ipc_criminal_breach_trust | 43 | 3 | 19 | 19 | 3 | 3 | 0 | 0 | 0 | 14.33 | pending |
| bulk_recent_ipc_kidnapping | 41 | 11 | 14 | 14 | 11 | 10 | 0 | 1 | 0 | 4.1 | pending |
| bulk_recent_ipc_sexual_offences | 42 | 8 | 16 | 16 | 8 | 8 | 0 | 0 | 0 | 5.25 | pending |
| bulk_recent_ipc_dowry_domestic_cruelty | 48 | 7 | 20 | 20 | 6 | 6 | 1 | 0 | 0 | 8.0 | pending |
| bulk_recent_ipc_conspiracy_common_intention | 37 | 7 | 14 | 14 | 7 | 7 | 0 | 0 | 0 | 5.29 | pending |
| bulk_recent_ipc_narcotics | 52 | 11 | 20 | 20 | 10 | 10 | 1 | 0 | 0 | 5.2 | pending |
| bulk_current_transition_bns_bnss | 62 | 20 | 20 | 20 | 20 | 17 | 0 | 3 | 0 | 3.65 | pending |
| bulk_landmark_historical_criminal | 39 | 9 | 15 | 15 | 7 | 5 | 2 | 2 | 0 | 7.8 | pending |

Hurt/assault: improved again: R4-only 79 requests for 9 reviewable = 8.78 calls/reviewable; cumulative partition 12 reviewable over 197 requests = 16.42; did not pause
Criminal breach of trust: improved: R4-only 43 requests for 3 reviewable = 14.33 calls/reviewable; cumulative partition 8 reviewable over 133 requests = 16.62; did not pause

## Acquisition Funnel

| Metric | R4 Incremental | Cumulative |
| --- | ---: | ---: |
| search result occurrences | not_reconstructable_from provider responses; partition metrics search_candidates=86 | not_reconstructable_from provider responses; durable candidate records=247 |
| unique source IDs seen | 86 | 247 |
| document API candidates | 171 | 748 |
| metadata API candidates | 171 | 746 |
| original download attempts | 81 | 251 |
| successful unique originals | 81 | 238 |
| reviewable unique records | 75 | 225 |

## Coverage

Temporal incremental: `{"current_transition": 17, "landmark_historical": 5, "recent_ipc": 53}`

Temporal cumulative: `{"current_transition": 30, "landmark_historical": 10, "recent_ipc": 185}`

Legal regime incremental: `{"bns_bnss": 3, "ipc_crpc": 57, "mixed_or_transition": 14, "unknown": 1}`

Legal regime cumulative: `{"bns_bnss": 13, "ipc_crpc": 190, "mixed_or_transition": 17, "unknown": 5}`

Court incremental: `{"district_or_sessions": 3, "high_court": 64, "supreme_court": 7, "unknown": 1}`

Court cumulative: `{"district_or_sessions": 10, "high_court": 178, "supreme_court": 31, "unknown": 6}`

Year incremental: `{"1975": 2, "1977": 1, "2016": 1, "2017": 1, "2018": 9, "2019": 11, "2020": 6, "2021": 1, "2022": 6, "2023": 17, "2024": 6, "2025": 9, "2026": 5}`

Year cumulative: `{"1960": 1, "1975": 2, "1977": 1, "1978": 1, "1979": 1, "1980": 1, "2016": 2, "2017": 1, "2018": 28, "2019": 32, "2020": 26, "2021": 15, "2022": 14, "2023": 37, "2024": 33, "2025": 14, "2026": 13, "unknown": 3}`

## 44-Byte Artifact Investigation

- source_id: 1291057
- raw_type: application/json
- raw_size_bytes: 44
- content_classification: provider original-document JSON wrapper: Original document not available
- usable: True
- usable_basis: document endpoint text was available before original fetch (86681 chars); raw original payload itself is not usable judgment text
- provider_wrapper_or_error_artifact: True
- provenance_mime_correct: True
- action_taken: documented and retained as needs_review; no mutation or deletion

## Deduplication

Source-ID skips: not tracked as explicit skip counter; duplicate records persisted as rejects.
SHA aliases among active reviewable records: 0.
Duplicate rejects in R4: 6.
Active duplicate records: 0.

## Storage

| Metric | R4 Reviewable Raw Files |
| --- | ---: |
| count | 75 |
| total_bytes | 24749074 |
| mean_bytes | 329987.65 |
| median_bytes | 248206 |
| minimum_bytes | 15522 |
| maximum_bytes | 1949265 |

Raw files are ignored; tracked binaries added: 0.

## Text Availability

| Metric | R4 |
| --- | ---: |
| pdf_documents | 60 |
| pdf_usable | 60 |
| pdf_sparse | 0 |
| pdf_empty | 0 |
| pdf_failed | 0 |
| pdf_native_coverage_percent | 100.0 |
| html_or_text_documents | 15 |
| overall_usable_text_documents | 75 |
| overall_text_availability_percent | 100.0 |

## Live Resume Integrity

- historical_counters_preserved: True
- batch_numbering_continued_beyond_batch_0020: True
- scheduler_position_preserved: True
- completed_candidate_replay_observed: False
- retry_queue_preserved: True
- partition_metrics_preserved: True
- active_duplicates_remain_zero: True

## Human QA Sample

- path: `docs/BULK_PILOT_R4_REVIEW.md`
- sample size: 15
- selection basis: criminal breach, hurt/assault, current-transition, BNS/BNSS or unknown regime, district/session, low-yield outputs, landmark historical
- statuses: pending

## Quality Guards

- global_budget_triggered: False
- partition_budget_triggered: False
- low_yield_triggered: False
- provider_failure_triggered: False
- duplicate_guard_triggered: True
- quality_noise_triggered: False
- stopped_before_300: True

## Recommendation

READY FOR REVIEW. Stop before any further live acquisition toward 300 until the R4 QA sample and the 44-byte artifact note have been inspected.
