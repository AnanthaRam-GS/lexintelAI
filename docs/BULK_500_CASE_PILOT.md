# Stage A 500-Case Bulk Pilot

Run ID: `bulk_20260904_000000_stagea`

Current checkpoint: R2 reached 100 cumulative reviewable records. The run stopped at the requested R2 target and did not continue toward 150.

## Scheduler Tuning

| Setting | Value |
| --- | --- |
| scheduler | target-aware round robin |
| scheduling unit | one search page per partition visit |
| cursor state | `state.scheduler.cursor` |
| low-yield guard | enabled |
| low-yield action | pause partition as `paused_low_yield` and rotate |
| max requests without reviewable | 120 |
| max calls per reviewable | 30.0 |

## Gate Summary

| Gate | Target | New Reviewable | Cumulative | Acquisition Calls | Calls/Reviewable | Stop Reason |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| A1 | 50 | 50 | 50 | 319 | 6.38 | target_reached |
| A2 checkpoint | 75 | 12 | 62 | 381 | 31.75 | stopped_budget |
| R2 | 100 | 38 | 100 | 304 | 8.0 | target_reached |
| A2 | 150 | not run | 100 | not run | not run | stop_before_150 |

## API Accounting

| Endpoint | Incremental R2 | Cumulative Acquisition |
| --- | ---: | ---: |
| search | 16 | 49 |
| document | 124 | 420 |
| metadata | 124 | 420 |
| original_document | 40 | 115 |
| other | 0 | 0 |
| total | 304 | 1004 |

R2 calls per reviewable: 8.0.
Cumulative acquisition calls per reviewable: 10.04.
Recovery/maintenance requests remain separate: 62.

## Funnel Semantics

| Metric | R2 Incremental | Cumulative |
| --- | ---: | ---: |
| search result occurrences | not_reconstructable_from provider responses; partition metrics search_candidates=41 | not_reconstructable_from provider responses; audit rows=350 |
| unique source IDs seen | 41 | 350 |
| document API candidates | 124 | 420 |
| metadata API candidates | 124 | 420 |
| original download attempts | 40 | 115 |
| successful unique originals | 40 | 102 |
| reviewable unique records | 38 | 100 |

Search-result occurrences remain non-reconstructable from pre-R2 provider responses; persisted partition metrics now retain candidate counters for future visits.

## Family Distribution

| Family | Before | New | Cumulative | Target | Gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| cheating_and_fraud | 12 | 0 | 12 | 50 | 38 |
| conspiracy_common_intention | 0 | 4 | 4 | 45 | 41 |
| criminal_breach_of_trust | 0 | 4 | 4 | 35 | 31 |
| dowry_and_domestic_cruelty | 0 | 7 | 7 | 45 | 38 |
| homicide | 29 | 0 | 29 | 60 | 31 |
| hurt_and_assault | 0 | 1 | 1 | 55 | 54 |
| kidnapping | 0 | 4 | 4 | 35 | 31 |
| narcotics_related | 0 | 7 | 7 | 45 | 38 |
| other | 0 | 3 | 3 | 25 | 22 |
| sexual_offences | 0 | 8 | 8 | 55 | 47 |
| theft_and_robbery | 21 | 0 | 21 | 50 | 29 |

## Partition Yield

| Partition | Requests | Search Candidates | Unique Sources | Original Attempts | New Reviewable | Duplicates | Rejects | Failures | Calls/Reviewable | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| bulk_recent_ipc_hurt_assault | 33 | 3 | 3 | 3 | 1 | 2 | 0 | 0 | 33.0 | pending |
| bulk_recent_ipc_criminal_breach_trust | 47 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 11.75 | pending |
| bulk_recent_ipc_kidnapping | 34 | 4 | 4 | 4 | 4 | 0 | 0 | 0 | 8.5 | pending |
| bulk_recent_ipc_sexual_offences | 51 | 8 | 8 | 8 | 8 | 0 | 0 | 0 | 6.38 | pending |
| bulk_recent_ipc_dowry_domestic_cruelty | 43 | 7 | 7 | 7 | 7 | 0 | 0 | 0 | 6.14 | pending |
| bulk_recent_ipc_conspiracy_common_intention | 36 | 5 | 5 | 4 | 4 | 0 | 1 | 0 | 9.0 | pending |
| bulk_recent_ipc_narcotics | 49 | 7 | 7 | 7 | 7 | 0 | 0 | 0 | 7.0 | pending |
| bulk_current_transition_bns_bnss | 11 | 3 | 3 | 3 | 3 | 0 | 0 | 0 | 3.67 | pending |

## Coverage

Temporal incremental: `{"current_transition": 3, "recent_ipc": 35}`

Temporal cumulative: `{"current_transition": 3, "recent_ipc": 97}`

Legal regime incremental: `{"ipc_crpc": 31, "mixed_or_transition": 3, "unknown": 4}`

Legal regime cumulative: `{"ipc_crpc": 93, "mixed_or_transition": 3, "unknown": 4}`

Court incremental: `{"high_court": 29, "supreme_court": 8, "unknown": 1}`

Court cumulative: `{"district_or_sessions": 6, "high_court": 78, "supreme_court": 15, "unknown": 1}`

Year incremental: `{"2018": 7, "2019": 11, "2020": 4, "2021": 4, "2022": 1, "2023": 6, "2024": 1, "2025": 3, "unknown": 1}`

Year cumulative: `{"2018": 11, "2019": 19, "2020": 10, "2021": 7, "2022": 8, "2023": 15, "2024": 24, "2025": 3, "unknown": 3}`

## Deduplication

Source-ID skips: not_reconstructable_from pre-R2 duplicate-skip logs.
SHA aliases among active reviewable records: 0.
Duplicate downloads avoided: 0.
R2 duplicate records rejected: 2.
Duplicate active records: 0.

## Storage

| Metric | R2 Reviewable Raw Files |
| --- | ---: |
| count | 38 |
| maximum_bytes | 1949497 |
| mean_bytes | 388323.16 |
| median_bytes | 241646.0 |
| minimum_bytes | 26300 |
| total_bytes | 14756280 |

Raw files are ignored; tracked binaries added: 0.

## Text Availability

| Metric | R2 |
| --- | ---: |
| html_or_text_documents | 4 |
| overall_text_availability_percent | 10.53 |
| overall_usable_text_documents | 4 |
| pdf_documents | 34 |
| pdf_empty | 0 |
| pdf_failed | 34 |
| pdf_native_coverage_percent | 0.0 |
| pdf_sparse | 0 |
| pdf_usable | 0 |

## Live Resume Integrity

- batch_numbering_continued: True
- completed_work_repeated: False
- duplicate_active_records: 0
- family_partition_metrics_preserved: True
- historical_counters_preserved: True
- retry_queue_preserved: True

## Human QA Sample

- path: `docs/BULK_PILOT_R2_REVIEW.md`
- sample size: 10
- selection method: current-transition first, then newly activated families, then unusual court/status records
- human statuses: pending

## Quality Guards

- global_budget_reached: False
- low_yield_triggered: False
- multiple_partitions_paused_low_yield: False
- provider_issue_triggered: False
- stopped_before_150: True
- target_reached: True

## Recommendation

READY FOR REVIEW. Stop before any further live acquisition toward 150 until the R2 QA sample has been inspected.
