# Stage A 500-Case Bulk Pilot

Run ID: `bulk_20260904_000000_stagea`

Status: stopped early during A2 checkpoint. A1 completed; A2 reached 62 cumulative reviewable before the 700-call cumulative budget was exhausted. A3 and A4 were not run.

## Gate Summary

| Gate | Target | New Reviewable | Cumulative | API Calls | Calls/Reviewable | Duplicates | Failures | Stop Reason |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| A1 | 50 | 50 | 50 | 319 | 6.38 | 0 | 0 | target_reached |
| A2 checkpoint | 75 | 12 | 62 | 381 | 31.75 | 0 | 0 | stopped_budget |
| A2 | 150 | not run | 62 | not run | not run | not run | not run | stopped_for_tuning |
| A3 | 300 | not run | 62 | not run | not run | not run | not run | not run |
| A4 | 500 | not run | 62 | not run | not run | not run | not run | not run |

## API Usage

| Endpoint | Requests |
| --- | ---: |
| search | 33 |
| document | 296 |
| metadata | 296 |
| original_document | 75 |
| other | 0 |
| total | 700 |

Configured cumulative budget at stop: 700.

Cumulative calls per durable reviewable candidate: 11.29.

The 62 raw-file recovery calls after local cleanup are excluded from acquisition yield metrics and recorded as a deviation.

## Acquisition Funnel

| Metric | Count |
| --- | ---: |
| search candidates | 64 |
| unique candidates | 64 |
| pre-download rejected | 2 |
| original documents downloaded during acquisition | 75 |
| durable reviewable candidates | 62 |
| source-ID duplicates | 0 |
| SHA duplicates | 0 |
| provider failures | 0 |
| retry events | 0 |

## Family Distribution

| Family | Target | Actual | Gap |
| --- | ---: | ---: | ---: |
| homicide | 60 | 29 | 31 |
| hurt_and_assault | 55 | 0 | 55 |
| theft_and_robbery | 50 | 21 | 29 |
| cheating_and_fraud | 50 | 12 | 38 |
| criminal_breach_of_trust | 35 | 0 | 35 |
| kidnapping | 35 | 0 | 35 |
| sexual_offences | 55 | 0 | 55 |
| dowry_and_domestic_cruelty | 45 | 0 | 45 |
| conspiracy_common_intention | 45 | 0 | 45 |
| narcotics_related | 45 | 0 | 45 |
| other | 25 | 0 | 25 |

## Court Distribution

| Court | Count |
| --- | ---: |
| high_court | 49 |
| supreme_court | 7 |
| district_or_sessions | 6 |

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

## Native Text Extraction

| Status | Count |
| --- | ---: |
| usable | 56 |
| sparse | 0 |
| empty | 0 |
| failed | 0 |
| non-PDF text/HTML | 6 |

Native extraction coverage: 90.32%.

## Live Resume Validation

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
| native text usability >= 90% | pass |
| catastrophic non-judgment/noise does not dominate | pass |
| family coverage balanced enough for further scale | fail |
| budget efficiency acceptable for immediate A3/A4 | fail |

## Stop Decision

Do not continue to A3/A4 without tuning. The early partitions produced usable data, but the A2 checkpoint consumed the 700-call cumulative budget at only 62 durable reviewable candidates and had coverage limited to three offence families.

All bulk reviewable records remain pending human review.
