# Legal NER Selection Decision

## Phase 0 Goal

Phase 0 evaluated whether the LegalAI NER layer should remain deterministic or promote a pretrained learned NER candidate through the frozen hybrid merge policy.

## Canonical Schema

The selected schema remains `legalai-ner-schema-v1`.

## Gold Evaluation Set

The frozen human-reviewed set contains 36 examples and 89 gold entities. It remains unchanged.

## Deterministic Baseline

D0 uses the deterministic LegalAI NER bridge. Its frozen exact metrics are precision `0.855263`, recall `0.730337`, and F1 `0.787879`.

Strong deterministic types are `STATUTE`, `SECTION`, `LEGAL_ROLE`, `POLICE_STATION`, `FIR_NUMBER`, and `LEGAL_PROCEDURE`. Weaker types are `OFFENCE`, `COURT`, `CASE_CITATION`, and `DATE`. Missing coverage remains `PERSON`, `ORGANIZATION`, `LOCATION`, and `CASE_NAME`.

## Candidate T1 - InLegalBERT Silver

Candidate `evolawyer/inlegalbert-sc-ner-silver` at revision `f7d54eb91551da4fb8a6329d1d871559c04e1832` was evaluated at threshold `0.70`.

L1 exact F1 was `0.336449`. H1 exact F1 was `0.787879`, equal to D0. The candidate did not provide sufficient evidence for Phase 0 promotion.

## Candidate T2 - General BERT NER

Candidate `dslim/bert-base-NER` at revision `d1a3e8f13f8c3566299d95fcfc9a8d2382a9affc` was evaluated at threshold `0.70`.

L2 exact F1 was `0.076336`. H2 exact F1 was `0.760870`, below D0. H2 recovered 5 deterministic false negatives, including 4 `LOCATION` and 1 `ORGANIZATION`, but precision dropped by `0.118421`.

## Comparative Results

| System | Precision | Recall | F1 | Decision |
|---|---:|---:|---:|---|
| D0 deterministic | 0.855263 | 0.730337 | 0.787879 | selected |
| L1 InLegalBERT silver | 1.000000 | 0.202247 | 0.336449 | rejected |
| H1 InLegalBERT hybrid | 0.855263 | 0.730337 | 0.787879 | rejected |
| L2 general BERT | 0.119048 | 0.056180 | 0.076336 | rejected |
| H2 general BERT hybrid | 0.736842 | 0.786517 | 0.760870 | rejected |

## Type-Level Findings

T1 was precise but too conservative and produced no hybrid gain. T2 improved `LOCATION` and one `ORGANIZATION` result, but it introduced too many `PERSON` and `ORGANIZATION` false positives for the Phase 0 precision guardrail.

`CASE_NAME` was not improved by either candidate and is not naturally represented by the tested pretrained taxonomies.

## Why Neither Learned Candidate Was Promoted

Neither learned candidate improved hybrid F1 over D0. T1 had no measurable hybrid gain. T2 improved recall but reduced precision and exact F1.

## Why Further Model Shopping Was Stopped

The gold set is small: 36 examples and 89 entities. Two reasonable pretrained candidates were already tested: one legal-domain token classifier and one general-purpose NER token classifier. Additional checkpoint trials would risk evaluation-set overfitting, threshold/checkpoint hunting, and added architecture complexity without evidence.

Therefore, there will be no further pretrained NER candidate search in Phase 0.

## Selected Phase 0 NER Pipeline

Phase 0 retains `LEGAL_NER_MODE=deterministic`.

Selected extractor: `deterministic_legal_ner`.

Default learned model: none.

Hybrid mode: disabled.

## Experimental Infrastructure Retained

The hybrid merge service, candidate evaluation harnesses, label mapping infrastructure, prediction manifest schema, raw prediction artifacts, and per-example analysis artifacts remain useful for future experiments.

## Future Fine-Tuning Path

Future learned NER work may become justified once a larger human-labelled NER corpus exists, judgment-document spans are annotated, `PERSON`/`ORGANIZATION`/`LOCATION`/`CASE_NAME` support increases, and a train/dev/test split is available.

Potential future paths include task-specific legal token classification or a hybrid deterministic plus fine-tuned model. No training architecture is selected now.

## Limitations

The decision is based on 36 examples, 89 gold entities, one reviewer, short synthetic/legal-style queries, no fine-tuning, and no judgment-document NER evaluation. It is a Phase 0 engineering selection, not a statistical superiority claim.

## Final Decision

RETAIN DETERMINISTIC NER FOR PHASE 0
