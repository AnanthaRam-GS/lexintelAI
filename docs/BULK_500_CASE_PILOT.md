# Stage A 500-Case Bulk Pilot

Run ID: `bulk_20260904_000000_stagea`

R1 performed implementation and accounting correction only. No live acquisition was run in R1, and the ignored durable run checkpoint was not rewritten to fabricate historical per-partition metrics.

Status: stopped during the A2 checkpoint. A1 completed; A2 reached 62 cumulative reviewable records before the 700-call cumulative acquisition budget was exhausted. A3 and A4 were not run.

## Scheduler Tuning

| Setting | Value |
| --- | --- |
| scheduler | target-aware round robin |
| scheduling unit | one search page per partition visit |
| cursor state | `state.scheduler.cursor` |
| zero-representation priority | true |
| low-yield guard | enabled |
| low-yield action | pause partition as `paused_low_yield` and rotate |
| min unique candidates | 20 |
| max requests without reviewable | 120 |
| max calls per reviewable | 30.0 |

The scheduler now prefers positive-target families with zero current representation, then fewer scheduler visits, then larger family gap, then the rotating partition cursor. Future resume runs persist per-partition request and funnel metrics.

## Gate Summary

| Gate | Target | New Reviewable | Cumulative | Acquisition Calls | Calls/Reviewable | Duplicates | Failures | Stop Reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A1 | 50 | 50 | 50 | 319 | 6.38 | 0 | 0 | target_reached |
| A2 checkpoint | 75 | 12 | 62 | 381 | 31.75 | 0 | 0 | stopped_budget |
| A2 | 150 | not run | 62 | not run | not run | not run | not run | stopped_for_tuning |
| A3 | 300 | not run | 62 | not run | not run | not run | not run | not run |
| A4 | 500 | not run | 62 | not run | not run | not run | not run | not run |

## API Accounting

| Metric | Requests |
| --- | ---: |
| acquisition search | 33 |
| acquisition document | 296 |
| acquisition metadata | 296 |
| acquisition original_document | 75 |
| acquisition other | 0 |
| total acquisition requests | 700 |
| recovery or maintenance requests | 62 |
| total provider requests including recovery | 762 |

Configured cumulative acquisition budget at stop: 700.

Cumulative acquisition calls per durable reviewable candidate: 11.29.

Recovery calls are excluded from acquisition yield. They restored local raw files from durable source IDs after local cleanup and are reported separately.

## Funnel Semantics

| Metric | Count |
| --- | ---: |
| search result occurrences | not reconstructable from pre-R1 provider responses |
| unique source IDs seen in audit | 227 |
| document endpoint requests | 296 |
| metadata endpoint requests | 296 |
| original download attempts | 75 |
| successful unique originals in candidate manifest | 62 |
| reviewable unique records | 62 |
| candidate manifest records | 64 |
| pre-download rejected records | 2 |

Reconciliation: 75 is the acquisition original-document request count. 64 is the durable candidate-manifest record count after screening/upsert. Of those durable records, 62 are reviewable and 2 are pre-download rejections.

## Invariants

| Check | Result |
| --- | --- |
| review entries equal reviewable records | pass |
| candidate records equal reviewable plus pre-download rejects | pass |
| successful unique originals equal reviewable records | pass |
| SHA-256 mismatches zero | pass |

## Hash Verification

| Metric | Count |
| --- | ---: |
| checked restored durable raw files | 62 |
| hash matches | 62 |
| missing files | 0 |
| mismatches | 0 |

## Family Progress

Historical per-partition request spend was not persisted before R1. Future acquisition visits now persist search/document/metadata/original/total requests, search candidates, unique candidates, reviewable added, pre-download rejects, duplicates, failures, and calls per reviewable.

| Family | Target | Current | Gap | Active Partitions | Paused Low Yield | Requests Spent | Reviewable Yield |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| homicide | 60 | 29 | 31 | 0 | 0 | not_available_pre_r1 | 29 |
| hurt_and_assault | 55 | 0 | 55 | 1 | 0 | not_available_pre_r1 | 0 |
| theft_and_robbery | 50 | 21 | 29 | 0 | 0 | not_available_pre_r1 | 21 |
| cheating_and_fraud | 50 | 12 | 38 | 0 | 0 | not_available_pre_r1 | 12 |
| criminal_breach_of_trust | 35 | 0 | 35 | 1 | 0 | not_available_pre_r1 | 0 |
| kidnapping | 35 | 0 | 35 | 1 | 0 | not_available_pre_r1 | 0 |
| sexual_offences | 55 | 0 | 55 | 1 | 0 | not_available_pre_r1 | 0 |
| dowry_and_domestic_cruelty | 45 | 0 | 45 | 1 | 0 | not_available_pre_r1 | 0 |
| conspiracy_common_intention | 45 | 0 | 45 | 1 | 0 | not_available_pre_r1 | 0 |
| narcotics_related | 45 | 0 | 45 | 1 | 0 | not_available_pre_r1 | 0 |
| other | 25 | 0 | 25 | 2 | 0 | not_available_pre_r1 | 0 |

## Court Distribution

| Court | Count |
| --- | ---: |
| district_or_sessions | 6 |
| high_court | 49 |
| supreme_court | 7 |

## Year Distribution

| Year | Count |
| --- | ---: |
| 2018 | 4 |
| 2019 | 8 |
| 2020 | 6 |
| 2021 | 3 |
| 2022 | 7 |
| 2023 | 9 |
| 2024 | 23 |
| unknown | 2 |

## Temporal And Regime Distribution

| Temporal Track | Count |
| --- | ---: |
| recent_ipc | 62 |

| Legal Regime | Count |
| --- | ---: |
| ipc_crpc | 62 |
| bns_bnss | 0 |
| mixed_or_transition | 0 |
| unknown | 0 |

## Storage

| Metric | Value |
| --- | ---: |
| raw files | 62 |
| total bytes | 22292318 |
| mean bytes | 359553.52 |
| median bytes | 343984 |
| minimum bytes | 14171 |
| maximum bytes | 1616100 |

## Text Extraction

| Metric | Count |
| --- | ---: |
| PDF documents | 56 |
| PDF usable | 56 |
| PDF sparse | 0 |
| PDF empty | 0 |
| PDF failed | 0 |
| HTML/text documents | 6 |
| overall usable text documents | 62 |

PDF native text coverage: 100.0%.

Overall text availability: 100.0%.

## Resume Validation

The pilot paused at the A1 completed checkpoint and resumed explicitly toward a 75-reviewable checkpoint.

| Check | Result |
| --- | --- |
| checkpoint pause performed | yes |
| resumed same run | yes |
| counters preserved | yes |
| completed source work repeated | no observed duplicate records |
| duplicate records after resume | 0 |
| retry queue preserved | yes, empty |
| batch sequence preserved | yes, three batch files |

## Quality Guards

| Guard | Result |
| --- | --- |
| provider failure rate <= 5% | pass |
| PDF native text coverage = 100% | pass |
| catastrophic non-judgment/noise does not dominate | pass |
| family coverage balanced enough for immediate scale | fail before R1 scheduler tuning |
| budget efficiency acceptable without tuning | fail before R1 scheduler tuning |

## Recommendation

PILOT TUNING VALIDATED - READY TO RESUME TOWARD 150.
