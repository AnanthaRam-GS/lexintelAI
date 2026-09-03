# Corpus Filter Experiment

## Purpose

Phase 0 Step 0.4C introduced a deterministic V2 acquisition strategy before
scaling the development judgment corpus. The experiment compares the V1
diagnostic corpus with a small filtered V2 run. No LLM, embedding model, OCR,
Gemini, Ollama, InLegalBERT, ChromaDB, or PostgreSQL component was used.

## V1 Initial Query Strategy

V1 produced 10 active validated judgments from 14 manifest records. It is kept
as an audit and regression sample.

Measured V1 characteristics:

- active valid count: 10
- offence-family skew: 8 homicide, 2 hurt_and_assault
- irrelevant results: 2
- duplicates: 1 excluded duplicate record
- failed acquisitions: 1
- API call observability: no exact counter; known lower bound was 44
- deterministic V2 retrospective: 10 needs_review, 4 reject

The V2 retrospective rejected the known bad/noise records for the image-like
HTML judgment payload, the failed Criminal Rules/Circular Orders JSON, the
duplicate Md. Anwar candidate, and the Law Commission volume/report candidate.
Most genuine-looking PDF judgments landed in `needs_review` because PDF text
extraction is intentionally not installed or inferred in this phase.

## V2 Filtered Recent Strategy

V2 used date-aware query configuration, judgment-oriented `doctypes`,
per-family quotas, deterministic document-type analysis, criminal relevance
scoring, statute/regime detection, metadata quality scoring, and exact API
request instrumentation.

The live experiment was capped at 5 downloaded documents and a 100-request
budget. It considered 10 candidates across five query families and downloaded
5 documents.

Measured V2 characteristics:

- candidates considered: 10
- accepted candidates: 1
- needs-review candidates: 3
- rejected candidates: 6
- offence-family distribution among downloaded records: 1 each for
  cheating_and_fraud, theft_and_robbery, criminal_breach_of_trust, kidnapping,
  and dowry_and_domestic_cruelty
- temporal-track distribution among considered candidates: 7 current_transition,
  3 recent_ipc
- detected legal regimes among downloaded records: 5 ipc_crpc
- exact API request count: 30
- candidates rejected before original-document download: 5

## API Usage

| Endpoint | Requests |
|---|---:|
| Search | 5 |
| Document | 10 |
| Metadata | 10 |
| Original Document | 5 |
| Other | 0 |
| Total | 30 |

The run consumed 30% of the 100-request budget. API calls per downloaded
candidate were 6.0. Five out-of-track candidates were rejected before original
document download.

## V2 Case Inventory

| Source ID | Case Name | Court | Year | Offence Family | Track | Criminal Score | Regime | Decision |
|---|---|---|---:|---|---|---:|---|---|
| 70332624 | Directorate Of Enforcement vs Mukesh Jain | Delhi District Court | 2024 | cheating_and_fraud | current_transition | 0.79 | ipc_crpc | needs_review |
| 28369644 | Criminal Courts - Rules and Orders | State of Madhya Pradesh - Act |  | theft_and_robbery | recent_ipc | 1.00 | ipc_crpc | reject |
| 99504196 | Anosh Ekka vs The Directorate Of Enforcement | Jharkhand High Court | 2023 | criminal_breach_of_trust | recent_ipc | 0.60 | ipc_crpc | needs_review |
| 27865803 | Anand Kushwaha vs The State Of Madhya Pradesh | Madhya Pradesh High Court | 2019 | kidnapping | recent_ipc | 0.76 | ipc_crpc | needs_review |
| 37639548 | State Of Kerala vs Abdul Majeed | Kerala High Court |  | dowry_and_domestic_cruelty | current_transition | 0.75 | ipc_crpc | accept_candidate |

## V1 vs V2

V2 improved offence-family diversity in the small experiment: five downloaded
records covered five distinct missing V1 families, while V1 active records
covered two families. V2 also measured exact API calls and rejected five
out-of-track candidates before original-document download.

V2 did not eliminate irrelevant results: one downloaded candidate was an
obvious rules/order collection and was rejected by deterministic scoring. V2
also showed that Indian Kanoon date filters cannot be trusted as the sole date
gate, so local temporal validation remains necessary.

The experiment supports keeping V2 for human review, but not scaling yet.
Quality remains conservative because PDF content is not parsed in this phase,
and most downloaded records require manual review.

## Human Review

V2 `accept_candidate` means only that the document passed automated
pre-screening. It is not human acceptance. Accepted-by-automation records are
added to `development_judgment_review_v2.json` with `human_review_status` set
to `pending`.

No automated human decisions occurred.
