# LegalAI Balanced Development Judgment Corpus

Phase 0 Step 0.4E acquired the initial controlled, balanced development judgment corpus.
Phase 0 Step 0.4F supplemented only underfilled offence-family gaps.
Phase 0 Step 0.4H records explicit human review decisions approved outside automation.

## Status

* Target reviewable candidates: 30
* Acquired reviewable candidates: 30
* Human accepted: 28
* Human rejected: 2
* Human pending: 0
* Step 0.4E reviewable candidates: 19
* Step 0.4F targeted additions: 11
* Corpus status: REVIEWED DEVELOPMENT CORPUS READY
* Reason: all acquired candidates have explicit human decisions; accepted distribution reflects approved reclassifications and rejections.

## Configured Quotas

| Offence Family | Target | Actual |
| --- | ---: | ---: |
| homicide | 4 | 5 |
| hurt_and_assault | 3 | 4 |
| theft_and_robbery | 3 | 3 |
| cheating_and_fraud | 3 | 3 |
| criminal_breach_of_trust | 2 | 2 |
| kidnapping | 2 | 2 |
| sexual_offences | 3 | 3 |
| dowry_and_domestic_cruelty | 3 | 3 |
| conspiracy_common_intention | 3 | 3 |
| narcotics_related | 2 | 2 |
| other | 2 | 0 |

## Composition

| Metric | Count |
| --- | ---: |
| total reviewable | 30 |
| human accepted | 28 |
| human rejected | 2 |
| accept_candidate | 20 |
| needs_review | 10 |
| pending human review | 0 |
| automated rejects | 72 |
| duplicates | 2 |
| failed retrievals | 1 |

## Accepted Corpus Distribution

| Offence Family | Accepted Count |
| --- | ---: |
| homicide | 5 |
| hurt_and_assault | 4 |
| theft_and_robbery | 2 |
| cheating_and_fraud | 3 |
| criminal_breach_of_trust | 2 |
| kidnapping | 2 |
| sexual_offences | 3 |
| dowry_and_domestic_cruelty | 3 |
| conspiracy_common_intention | 2 |
| narcotics_related | 2 |
| other | 0 |

## Human Review Changes

* 199957261: other -> homicide
* 22498132: other -> hurt_and_assault
* 7542474: rejected because the criminal theft proceeding is collateral to service/disciplinary litigation.
* 154726248: rejected as a semantic duplicate of retained source ID 154171944.

## Post-Review Quota Differences

| Offence Family | Target | Accepted | Difference |
| --- | ---: | ---: | ---: |
| homicide | 4 | 5 | 1 |
| hurt_and_assault | 3 | 4 | 1 |
| theft_and_robbery | 3 | 2 | -1 |
| cheating_and_fraud | 3 | 3 | 0 |
| criminal_breach_of_trust | 2 | 2 | 0 |
| kidnapping | 2 | 2 | 0 |
| sexual_offences | 3 | 3 | 0 |
| dowry_and_domestic_cruelty | 3 | 3 | 0 |
| conspiracy_common_intention | 3 | 2 | -1 |
| narcotics_related | 2 | 2 | 0 |
| other | 2 | 0 | -2 |

## Court Distribution

| Value | Count |
| --- | ---: |
| district_or_sessions | 2 |
| high_court | 20 |
| supreme_court | 8 |

## Year Distribution

| Value | Count |
| --- | ---: |
| 2018 | 1 |
| 2019 | 6 |
| 2020 | 3 |
| 2021 | 3 |
| 2022 | 6 |
| 2023 | 7 |
| 2024 | 4 |

## Temporal Track Distribution

| Value | Count |
| --- | ---: |
| recent_ipc | 30 |

## Legal Regime Distribution

| Value | Count |
| --- | ---: |
| ipc_crpc | 29 |
| unknown | 1 |

## Accepted Legal Regime Distribution

| Value | Count |
| --- | ---: |
| ipc_crpc | 27 |
| unknown | 1 |

## Reviewable Case Inventory

| Source ID | Case Name | Court | Year | Offence Family | Track | Criminal Score | Regime | Automated Decision | Human Review |
| --- | --- | --- | ---: | --- | --- | ---: | --- | --- | --- |
| 14496522 | Dr. Lakshman vs The State Of Karnataka on 17 October, 2019 | supreme_court | 2019 | cheating_and_fraud | recent_ipc | 0.68 | ipc_crpc | needs_review | accepted |
| 8095700 | Amit Kumar Alias Sushil vs State Of H.P on 4 February, 2021 | high_court | 2021 | cheating_and_fraud | recent_ipc | 1.0 | ipc_crpc | needs_review | accepted |
| 31369863 | K.V. Brahmaji Rao vs Union Of India & Ors on 4 September, 2023 | high_court | 2023 | cheating_and_fraud | recent_ipc | 0.86 | ipc_crpc | needs_review | accepted |
| 111592349 | Jinofer Kawasji Bhujwala vs The State Of Gujarat on 19 June, 2020 | supreme_court | 2020 | criminal_breach_of_trust | recent_ipc | 0.63 | ipc_crpc | needs_review | accepted |
| 44731735 | Sahadev Prasad Agarwal & Anr vs The State Of West Bengal & Anr on 30 July, 2021 | high_court | 2021 | criminal_breach_of_trust | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 173395727 | Santosh Paswan Son Of Ramdin Paswan vs The State Of Jharkhand on 12 February, 2024 | high_court | 2024 | kidnapping | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 83401027 | Charan Singh @ Charanjit Singh vs The State Of Uttarakhand Home ... on 20 April, 2023 | supreme_court | 2023 | dowry_and_domestic_cruelty | recent_ipc | 0.89 | ipc_crpc | accept_candidate | accepted |
| 70774666 | Smt. Alka vs State Of U.P. And Another on 13 May, 2022 | high_court | 2022 | dowry_and_domestic_cruelty | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 26223875 | Devender Singh vs The State Of Uttarakhand on 21 April, 2022 | supreme_court | 2022 | dowry_and_domestic_cruelty | recent_ipc | 0.89 | ipc_crpc | accept_candidate | accepted |
| 31029978 | Veerendra vs State Of Madhya Pradesh on 13 May, 2022 | supreme_court | 2022 | sexual_offences | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 179828917 | Manoj Pratap Singh vs The State Of Rajasthan on 24 June, 2022 | supreme_court | 2022 | sexual_offences | recent_ipc | 1.0 | ipc_crpc | needs_review | accepted |
| 194128214 | Indresh Kumar vs The State Of Uttar Pradesh on 12 July, 2022 | supreme_court | 2022 | sexual_offences | recent_ipc | 0.82 | ipc_crpc | accept_candidate | accepted |
| 154171944 | Saifurrehman Ansari S/O Abdul Rehman ... vs State Of Rajasthan on 29 March, 2023 | high_court | 2023 | conspiracy_common_intention | recent_ipc | 1.0 | ipc_crpc | needs_review | accepted |
| 154726248 | State Of vs Shahbaz Hussain @ Shahbaz Ahmed @ Shanu ... on 29 March, 2023 | high_court | 2023 | conspiracy_common_intention | recent_ipc | 1.0 | ipc_crpc | needs_review | rejected |
| 178355286 | Special Judge (Pc Act) Cbi-13 vs Padmanabhan Nair (Supra) To on 22 April, 2019 | district_or_sessions | 2019 | conspiracy_common_intention | recent_ipc | 1.0 | ipc_crpc | needs_review | accepted |
| 6939849 | Deepak Nandwanshi vs The State Of Madhya Pradesh on 3 December, 2019 | high_court | 2019 | hurt_and_assault | recent_ipc | 0.8 | ipc_crpc | accept_candidate | accepted |
| 180296861 | The State Of Karnataka By vs B Rajeeva (A-1) on 2 April, 2024 | high_court | 2024 | hurt_and_assault | recent_ipc | 0.87 | ipc_crpc | accept_candidate | accepted |
| 199957261 | Manik vs The State Of Maharashtra on 25 September, 2024 | supreme_court | 2024 | homicide | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 22498132 | The State - Through Police Sub Inspector vs James Vinod on 9 January, 2023 | high_court | 2023 | hurt_and_assault | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 7542474 | Steel Authority Of India Ltd. Through ... vs Prakash Poddar on 30 August, 2018 | high_court | 2018 | theft_and_robbery | recent_ipc | 0.75 | ipc_crpc | accept_candidate | rejected |
| 108783291 | Banti @ Jitendra Sharma vs The State Of Madhya Pradesh on 5 May, 2020 | high_court | 2020 | theft_and_robbery | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 136492342 | Neelam @ Neeraj vs The State Of Madhya Pradesh on 8 February, 2019 | high_court | 2019 | theft_and_robbery | recent_ipc | 0.66 | ipc_crpc | needs_review | accepted |
| 90446963 | Babu vs State Rep. By on 29 September, 2021 | high_court | 2021 | narcotics_related | recent_ipc | 0.75 | ipc_crpc | accept_candidate | accepted |
| 116547627 | State vs . Brahma Nand, on 16 March, 2020 | district_or_sessions | 2020 | narcotics_related | recent_ipc | 0.47 | unknown | needs_review | accepted |
| 127989801 | Surendra Koli vs C.B.I. on 16 October, 2023 | high_court | 2023 | homicide | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 189001274 | Page No.# 1/77 vs The State Of Assam on 5 August, 2023 | high_court | 2023 | homicide | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 156271048 | Md. Fakar Uddin Barbhuiya And Anr vs The State Of Assam on 18 January, 2019 | high_court | 2019 | homicide | recent_ipc | 1.0 | ipc_crpc | accept_candidate | accepted |
| 15834217 | Mukesh Khandelwal @ Devendra Kumar S/O ... vs State Of Rajasthan Through Pp on 29 January, 2019 | high_court | 2019 | homicide | recent_ipc | 0.91 | ipc_crpc | accept_candidate | accepted |
| 77330685 | Crl.A./213/2020 on 12 June, 2024 | high_court | 2024 | kidnapping | recent_ipc | 0.79 | ipc_crpc | accept_candidate | accepted |
| 123721856 | Suresh Ram vs The State Of Bihar on 13 July, 2022 | high_court | 2022 | hurt_and_assault | recent_ipc | 0.89 | ipc_crpc | accept_candidate | accepted |
