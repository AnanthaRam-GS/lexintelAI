# Bulk Pilot A1 Human QA Sample

Run ID: `bulk_20260904_000000_stagea`

Sampling version: `bulk-pilot-a1-v1`

Selection method: deterministic stratified sample from reviewable pilot records, balanced across available offence families, court levels, and automated decisions. The A1/A2 partial corpus contains only `ipc_crpc` and `recent_ipc` records, so regime and temporal stratification are limited by observed data.

All sampled records remain `human_review_status = pending`.

| Source ID | Case Name | Family | Court | Regime | Automated Decision | Human Status |
| --- | --- | --- | --- | --- | --- | --- |
| 122682909 | Sh. E.V. Jothi vs Cbi on 3 May, 2018 | cheating_and_fraud | district_or_sessions | ipc_crpc | accept_candidate | pending |
| 186615496 | On The Basis Of Information/Complaint ... vs . on 7 December, 2019 | cheating_and_fraud | district_or_sessions | ipc_crpc | needs_review | pending |
| 73295342 | Cbi vs Narain Diwakar (Anchal Cghs) on 12 September, 2023 | cheating_and_fraud | district_or_sessions | ipc_crpc | needs_review | pending |
| 121299318 | Aman Kumar Mehta And 4 Others vs State Of U.P. And Another on 26 August, 2020 | cheating_and_fraud | high_court | ipc_crpc | accept_candidate | pending |
| 102778545 | Mrinal Sharma vs The State Of Madhya Pradesh on 14 July, 2022 | homicide | high_court | ipc_crpc | accept_candidate | pending |
| 114356088 | Mahadev S/O. Gahininath Bahir And ... vs The State Of Maharashtra And Anr on 17 April, 2024 | homicide | high_court | ipc_crpc | accept_candidate | pending |
| 123692674 | Manvir Singh And Others vs State Of U.P. on 7 February, 2024 | homicide | high_court | ipc_crpc | accept_candidate | pending |
| 128411538 | Pounthai vs The State Represented By on 15 February, 2023 | homicide | high_court | ipc_crpc | accept_candidate | pending |
| 176964646 | Raju vs The State on 1 February, 2020 | theft_and_robbery | district_or_sessions | ipc_crpc | accept_candidate | pending |
| 177113492 | Sarvan vs The State on 26 August, 2020 | theft_and_robbery | district_or_sessions | ipc_crpc | accept_candidate | pending |
| 75836528 | Rupesh Kumar vs State on 23 September, 2023 | theft_and_robbery | district_or_sessions | ipc_crpc | accept_candidate | pending |
| 132722557 | Ahammed Kabeer vs The State Of Kerala on 11 June, 2019 | theft_and_robbery | high_court | ipc_crpc | accept_candidate | pending |

## Review Focus

* Confirm these are criminal judgments or criminal-proceeding orders.
* Confirm offence-family assignment is plausible.
* Confirm `ipc_crpc` regime evidence is correct.
* Pay special attention to `needs_review` records and district/session court records.
* Do not mark accepted/rejected here; human review decisions must be applied through a later explicit review step.
