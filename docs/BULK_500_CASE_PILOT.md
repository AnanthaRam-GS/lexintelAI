# Stage A 500-Case Bulk Pilot

Run ID: `bulk_20260904_000000_stagea`

Current checkpoint: R3 reached 150 cumulative reviewable records. The run stopped at the requested R3 target and did not continue toward 300.

## Gate Summary

| Gate | Target | New Reviewable | Cumulative | Acquisition Calls | Calls/Reviewable | Stop Reason |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| A1 | 50 | 50 | 50 | 319 | 6.38 | target_reached |
| A2 checkpoint | 75 | 12 | 62 | 381 | 31.75 | stopped_budget |
| R2 | 100 | 38 | 100 | 304 | 8.0 | target_reached |
| R3 | 150 | 50 | 150 | 384 | 7.68 | target_reached |
| A3 | 300 | not run | 150 | not run | not run | stop_before_300 |

## API Accounting

| Endpoint | Incremental R3 | Cumulative Acquisition |
| --- | ---: | ---: |
| search | 17 | 66 |
| document | 157 | 577 |
| metadata | 155 | 575 |
| original_document | 55 | 170 |
| other | 0 | 0 |
| total | 384 | 1388 |

R3 calls/reviewable: 7.68. Cumulative acquisition calls/reviewable: 9.25. Recovery/maintenance requests remain separate: 62.

## Family Distribution

| Family | Before | New | Cumulative | Target | Gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| homicide | 29 | 0 | 29 | 60 | 31 |
| hurt_and_assault | 1 | 2 | 3 | 55 | 52 |
| theft_and_robbery | 21 | 0 | 21 | 50 | 29 |
| cheating_and_fraud | 12 | 0 | 12 | 50 | 38 |
| criminal_breach_of_trust | 4 | 1 | 5 | 35 | 30 |
| kidnapping | 4 | 3 | 7 | 35 | 28 |
| sexual_offences | 8 | 11 | 19 | 55 | 36 |
| dowry_and_domestic_cruelty | 7 | 9 | 16 | 45 | 29 |
| conspiracy_common_intention | 4 | 3 | 7 | 45 | 38 |
| narcotics_related | 7 | 6 | 13 | 45 | 32 |
| other | 3 | 15 | 18 | 25 | 7 |

## Partition Yield

| Partition | Requests | New Reviewable | Calls/Reviewable | Status |
| --- | ---: | ---: | ---: | --- |
| bulk_recent_ipc_hurt_assault | 42 | 2 | 21.0 | pending |
| bulk_recent_ipc_criminal_breach_trust | 43 | 1 | 43.0 | pending |
| bulk_recent_ipc_kidnapping | 37 | 3 | 12.33 | pending |
| bulk_recent_ipc_sexual_offences | 53 | 11 | 4.82 | pending |
| bulk_recent_ipc_dowry_domestic_cruelty | 51 | 9 | 5.67 | pending |
| bulk_recent_ipc_conspiracy_common_intention | 33 | 3 | 11.0 | pending |
| bulk_recent_ipc_narcotics | 48 | 6 | 8.0 | pending |
| bulk_current_transition_bns_bnss | 31 | 10 | 3.1 | pending |
| bulk_landmark_historical_criminal | 46 | 5 | 9.2 | pending |

Hurt/assault behavior: improved from R2-only 33.0 calls/reviewable to cumulative partition 25.0; R3-only 42 requests for 2 reviewable = 21.0 calls/reviewable; did not pause

## Coverage

Temporal incremental: `{"current_transition": 10, "landmark_historical": 5, "recent_ipc": 35}`

Temporal cumulative: `{"current_transition": 13, "landmark_historical": 5, "recent_ipc": 132}`

Legal regime incremental: `{"bns_bnss": 10, "ipc_crpc": 40}`

Legal regime cumulative: `{"bns_bnss": 10, "ipc_crpc": 133, "mixed_or_transition": 3, "unknown": 4}`

Court incremental: `{"district_or_sessions": 1, "high_court": 36, "supreme_court": 9, "unknown": 4}`

Court cumulative: `{"district_or_sessions": 7, "high_court": 114, "supreme_court": 24, "unknown": 5}`

Year incremental: `{"1960": 1, "1978": 1, "1979": 1, "1980": 1, "2016": 1, "2018": 8, "2019": 2, "2020": 10, "2021": 7, "2023": 5, "2024": 3, "2025": 2, "2026": 8}`

Year cumulative: `{"1960": 1, "1978": 1, "1979": 1, "1980": 1, "2016": 1, "2018": 19, "2019": 21, "2020": 20, "2021": 14, "2022": 8, "2023": 20, "2024": 27, "2025": 5, "2026": 8, "unknown": 3}`

## Deduplication

Source-ID skips: not_reconstructable_from provider skip logs.
SHA aliases among active reviewable records: 0.
Duplicate rejects in R3: 5.
Active duplicate records: 0.

## Storage

| Metric | R3 Reviewable Raw Files |
| --- | ---: |
| count | 50 |
| total_bytes | 15442929 |
| mean_bytes | 308858.58 |
| median_bytes | 294567.0 |
| minimum_bytes | 44 |
| maximum_bytes | 1074859 |

Raw files are ignored; tracked binaries added: 0.

## Text Availability

| Metric | R3 |
| --- | ---: |
| pdf_documents | 44 |
| pdf_usable | 44 |
| pdf_sparse | 0 |
| pdf_empty | 0 |
| pdf_failed | 0 |
| pdf_native_coverage_percent | 100.0 |
| html_or_text_documents | 6 |
| overall_usable_text_documents | 50 |
| overall_text_availability_percent | 100.0 |

## Live Resume Integrity

- historical_counters_preserved: True
- batch_numbering_continued: True
- completed_candidate_replay_observed: False
- retry_queue_preserved: True
- partition_metrics_preserved: True
- active_duplicates_remain_zero: True

## Human QA Sample

- path: `docs/BULK_PILOT_R3_REVIEW.md`
- sample size: 12
- selection basis: hurt/assault, low-count families, current-transition/landmark, unusual regime/court, needs-review records
- human status: pending

## Quality Guards

- global_budget_triggered: False
- partition_budget_triggered: False
- low_yield_triggered: False
- provider_failure_triggered: False
- duplicate_guard_triggered: True
- quality_noise_triggered: False
- stopped_before_300: True

## Recommendation

READY FOR REVIEW. Stop before any further live acquisition toward 300 until the R3 QA sample has been inspected.
