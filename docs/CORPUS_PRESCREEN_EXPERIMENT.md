# Corpus Prescreen Experiment

## Purpose

Phase 0 Step 0.4D uses Indian Kanoon Document API text as the primary
deterministic quality-analysis input before downloading original court copies.
The Original Document endpoint remains for source preservation, provenance,
checksum validation, later ingestion, and human/source verification.

No OCR, PDF parser, LLM, embeddings, InLegalBERT, Gemini, Ollama, PostgreSQL,
or ChromaDB component was used.

## Step 0.4C Baseline

Measured Step 0.4C live experiment:

- search candidates considered: 10
- original-document downloads: 5
- pre-download rejections: 5, all from local temporal-track checks
- accept_candidate: 1
- needs_review: 3
- reject: 6
- API calls: 30
- human-review queue completeness: incomplete, because only accept_candidate
  records entered the V2 review queue
- unresolved limitation: PDF content was not parsed, so many candidates stayed
  conservative `needs_review`

## Step 0.4D Document Prescreen

Measured Step 0.4D live experiment:

- search candidates considered: 15
- Document API records analyzed: 8
- metadata calls: 15
- candidates rejected before original download: 8
- candidates rejected after Document API before original download: 3
- original-document downloads: 5
- accept_candidate: 1
- needs_review: 4
- reject: 10
- API calls: 40
- documents with usable Document API text: 8
- sparse/unavailable Document API text: 7, all from out-of-track candidates
  rejected before Document API text analysis
- human-review queue completeness: complete for final `accept_candidate` and
  `needs_review` records

## API Usage

| Endpoint | Requests |
|---|---:|
| Search | 5 |
| Document | 15 |
| Metadata | 15 |
| Original Document | 5 |
| Other | 0 |
| Total | 40 |

The Step 0.4D run consumed 40% of the 100-request budget. It avoided 8 original
document downloads, including 3 candidates rejected after Document API
prescreening.

## Legal Regime Detection

| Regime | Count |
|---|---:|
| ipc_crpc | 8 |
| bns_bnss | 0 |
| mixed_or_transition | 0 |
| unknown | 7 |

The experiment again shows that recent decision dates do not imply BNS/BNSS
usage. All downloaded/reviewable candidates with explicit statute evidence
resolved to `ipc_crpc`.

## Case Inventory

| Source ID | Case Name | Family | Track | Text Available | Criminal Score | Regime | Pre-Download Decision | Final Decision | Human Review |
|---|---|---|---|---|---:|---|---|---|---|
| 70332624 | Directorate Of Enforcement vs Mukesh Jain | cheating_and_fraud | current_transition | yes | 1.00 | ipc_crpc | needs_more_evidence | needs_review | pending |
| 28369644 | Criminal Courts - Rules and Orders | theft_and_robbery | recent_ipc | yes | 1.00 | ipc_crpc | reject_before_download | reject | audit only |
| 163270670 | Criminal Courts - Rules and Orders | theft_and_robbery | recent_ipc | yes | 1.00 | ipc_crpc | reject_before_download | reject | audit only |
| 14485072 | Vijay Madanlal Choudhary vs Union Of India | theft_and_robbery | recent_ipc | yes | 1.00 | ipc_crpc | reject_before_download | reject | audit only |
| 1234898 | Raj Kumar @ Raju vs State Of Uttaranchal | theft_and_robbery | recent_ipc | no |  | unknown |  | reject | audit only |
| 55558 | Rampal Pithwa Rahidas vs State Of Maharashtra | theft_and_robbery | recent_ipc | no |  | unknown |  | reject | audit only |
| 38986681 | Sunil Tyagi vs Govt Of Nct Of Delhi & Anr | theft_and_robbery | recent_ipc | yes | 1.00 | ipc_crpc | needs_more_evidence | needs_review | pending |
| 99504196 | Anosh Ekka vs The Directorate Of Enforcement | criminal_breach_of_trust | recent_ipc | yes | 0.84 | ipc_crpc | needs_more_evidence | needs_review | pending |
| 27865803 | Anand Kushwaha vs The State Of Madhya Pradesh | kidnapping | recent_ipc | yes | 1.00 | ipc_crpc | needs_more_evidence | needs_review | pending |
| 83401027 | Charan Singh @ Charanjit Singh vs The State Of Uttarakhand Home ... | dowry_and_domestic_cruelty | current_transition | no |  | unknown |  | reject | audit only |
| 17701479 | Savita vs State Of Delhi | dowry_and_domestic_cruelty | current_transition | no |  | unknown |  | reject | audit only |
| 876962 | Siri Bhagwan vs State Of Haryana | dowry_and_domestic_cruelty | current_transition | no |  | unknown |  | reject | audit only |
| 166101582 | Rakesh & Anr. vs State Of Delhi | dowry_and_domestic_cruelty | current_transition | no |  | unknown |  | reject | audit only |
| 123779490 | Hompal Singh & Ors. vs State Of Delhi | dowry_and_domestic_cruelty | current_transition | no |  | unknown |  | reject | audit only |
| 37639548 | State Of Kerala vs Abdul Majeed | dowry_and_domestic_cruelty | current_transition | yes | 0.87 | ipc_crpc | needs_more_evidence | accept_candidate | pending |

## Assessment

Step 0.4D improved queue completeness and prevented several rules/orders
collections from reaching the Original Document endpoint. It also made legal
regime detection more evidence-based by analyzing Document API text.

The strategy is not ready for full-scale unattended acquisition. It still needs
human review because some judgment-like records remain `needs_review`, and the
provider search/date filters still return out-of-track records that require
local rejection.
