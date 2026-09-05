# Stage A 500-Case Bulk Pilot

Run ID: `bulk_20260904_000000_stagea`

Current checkpoint: R5 stopped at 249 cumulative reviewable records after provider 4xx search failures and max-page exhaustion on safe non-other family partitions. It did not continue toward 500.

## Gate Summary

| Gate | Target | New Reviewable | Cumulative | Acquisition Calls | Calls/Reviewable | Stop Reason |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| A1 | 50 | 50 | 50 | 319 | 6.38 | target_reached |
| A2 checkpoint | 75 | 12 | 62 | 381 | 31.75 | stopped_budget |
| R2 | 100 | 38 | 100 | 304 | 8.0 | target_reached |
| R3 | 150 | 50 | 150 | 384 | 7.68 | target_reached |
| R4 | 225 | 75 | 225 | 443 | 5.91 | target_reached |
| R5 | 300 | 24 | 249 | 168 | 7.0 | provider_4xx_stop |

## API Accounting

| Endpoint | Incremental R5 | Cumulative Acquisition |
| --- | ---: | ---: |
| search | 26 | 112 |
| document | 58 | 806 |
| metadata | 59 | 805 |
| original_document | 25 | 276 |
| other | 0 | 0 |
| total | 168 | 1999 |

R5 calls/reviewable: 7.0. Cumulative acquisition calls/reviewable: 8.03. Recovery/maintenance calls remain separate: 62.

## Family Distribution

| Family | Before | R5 New | Cumulative | Target | Gap |
| --- | ---: | ---: | ---: | ---: | ---: |
| homicide | 29 | 0 | 29 | 60 | 31 |
| hurt_and_assault | 12 | 0 | 12 | 55 | 43 |
| theft_and_robbery | 21 | 0 | 21 | 50 | 29 |
| cheating_and_fraud | 12 | 0 | 12 | 50 | 38 |
| criminal_breach_of_trust | 8 | 5 | 13 | 35 | 22 |
| kidnapping | 17 | 0 | 17 | 35 | 18 |
| sexual_offences | 27 | 8 | 35 | 55 | 20 |
| dowry_and_domestic_cruelty | 22 | 6 | 28 | 45 | 17 |
| conspiracy_common_intention | 14 | 5 | 19 | 45 | 26 |
| narcotics_related | 23 | 0 | 23 | 45 | 22 |
| other | 40 | 0 | 40 | 25 | 0 |

Family-gap visit cap behaved correctly in R5: `other` remained 40/25 and received 0 new records.

## Partition Yield

| Partition | Requests | New Reviewable | Calls/Reviewable | Status |
| --- | ---: | ---: | ---: | --- |
| bulk_recent_ipc_hurt_assault | 2 | 0 | None | completed |
| bulk_recent_ipc_criminal_breach_trust | 49 | 5 | 9.8 | completed |
| bulk_recent_ipc_kidnapping | 4 | 0 | None | completed |
| bulk_recent_ipc_sexual_offences | 43 | 8 | 5.38 | completed |
| bulk_recent_ipc_dowry_domestic_cruelty | 37 | 6 | 6.17 | completed |
| bulk_recent_ipc_conspiracy_common_intention | 29 | 5 | 5.8 | completed |
| bulk_recent_ipc_narcotics | 4 | 0 | None | completed |

Hurt/assault: R5-only 2 provider-failed search requests and 0 new reviewable records; cumulative partition remains 12 reviewable over 156 requests = 13.0; the pre-fix runner advanced pages on no-progress 4xx responses, now fixed for future resumes
Criminal breach of trust: continued improving: R5-only 49 requests for 5 reviewable = 9.8 calls/reviewable; cumulative partition 13 reviewable over 182 requests = 14.0; completed max pages without low-yield pause

## Acquisition Funnel

| Metric | R5 Incremental | Cumulative |
| --- | ---: | ---: |
| unique source IDs seen | 25 | 272 |
| document API candidates | 58 | 806 |
| metadata API candidates | 59 | 805 |
| original download attempts | 25 | 276 |
| successful unique originals | 25 | 263 |
| reviewable unique records | 24 | 249 |

Search-result occurrences are not reconstructable from historical provider responses.

## Coverage

Temporal R5: `{"recent_ipc": 24}`

Temporal cumulative: `{"current_transition": 30, "landmark_historical": 10, "recent_ipc": 209}`

Legal regime R5: `{"ipc_crpc": 24}`

Legal regime cumulative: `{"bns_bnss": 13, "ipc_crpc": 214, "mixed_or_transition": 17, "unknown": 5}`

Court R5: `{"district_or_sessions": 5, "high_court": 18, "supreme_court": 1}`

Court cumulative: `{"district_or_sessions": 15, "high_court": 196, "supreme_court": 32, "unknown": 6}`

Year R5: `{"2018": 2, "2019": 3, "2020": 3, "2021": 5, "2022": 4, "2023": 6, "2024": 1}`

Year cumulative: `{"1960": 1, "1975": 2, "1977": 1, "1978": 1, "1979": 1, "1980": 1, "2016": 2, "2017": 1, "2018": 30, "2019": 35, "2020": 29, "2021": 20, "2022": 18, "2023": 43, "2024": 34, "2025": 14, "2026": 13, "unknown": 3}`

## Transition Regime QA

- new bns_bnss: 0
- new mixed_or_transition: 0
- QA sample transition coverage: none, because `other` family gap was zero
- suspicious regime behavior: none observed in R5

## Deduplication

Source-ID skips: not tracked as explicit skip counter.
SHA aliases among active reviewable records: 0.
Duplicate rejects in R5: 1.
Active duplicates: 0.

## Storage

| Metric | R5 Reviewable Raw Files |
| --- | ---: |
| count | 24 |
| total_bytes | 8120954 |
| mean_bytes | 338373.08 |
| median_bytes | 219866.0 |
| minimum_bytes | 23708 |
| maximum_bytes | 2195886 |

Raw files are ignored; tracked binaries added: 0.

## Text Availability

| Metric | R5 |
| --- | ---: |
| pdf_documents | 20 |
| pdf_usable | 20 |
| pdf_sparse | 0 |
| pdf_empty | 0 |
| pdf_failed | 0 |
| pdf_native_coverage_percent | 100.0 |
| html_or_text_documents | 4 |
| document_endpoint_fallback_count | 0 |
| overall_usable_text_documents | 24 |
| overall_text_availability_percent | 100.0 |

## Live Resume Integrity

- historical_counters_preserved: True
- batch_numbering_continued: True
- partition_metrics_preserved: True
- scheduler_state_preserved: True
- retry_queue_preserved: True
- completed_work_replay: 0
- active_duplicates: 0

## Human QA Sample

- path: `docs/BULK_PILOT_R5_REVIEW.md`
- sample size: 15
- selection basis: hurt/assault, criminal breach, low-count families, district/session, unusual regime, provider fallback, needs-review
- statuses: pending

## Quality Guards

- global_budget_triggered: False
- partition_budget_triggered: False
- low_yield_triggered: False
- provider_failure_triggered: True
- duplicate_guard_triggered: True
- quality_noise_triggered: False
- family_gap_cap_triggered: True

## Recommendation

PILOT R5 NEEDS TUNING BEFORE 500. Provider 4xx handling is now fixed for future resumes, and additional query strategy work is needed before scaling beyond this checkpoint.
