# Hybrid Legal NER Design

## Deterministic Baseline Evidence

The frozen deterministic baseline over 36 human-reviewed examples produced:

- gold entities: 89
- predictions: 76
- TP: 65
- FP: 11
- FN: 24
- precision: 0.855263
- recall: 0.730337
- F1: 0.787879

Strong deterministic types:

- `STATUTE`: 1.0 F1
- `SECTION`: 1.0 F1
- `LEGAL_PROCEDURE`: 0.956522 F1
- `LEGAL_ROLE`: 1.0 F1
- `POLICE_STATION`: 1.0 F1
- `FIR_NUMBER`: 1.0 F1

Weak or absent deterministic types:

- `PERSON`: 0.0 F1
- `ORGANIZATION`: 0.0 F1
- `LOCATION`: 0.0 F1
- `CASE_NAME`: 0.0 F1
- `DATE`: 0.444444 F1
- `COURT`: 0.636364 F1
- `OFFENCE`: 0.666667 F1

## Why Hybrid Is Justified

The deterministic system is reliable for explicit legal structure but cannot
cover ordinary named entities such as people, organizations, locations, or case
names. A learned model should enrich these gaps while protected deterministic
legal spans remain authoritative.

## Protected Entity Types

Protected deterministic types:

- `STATUTE`
- `SECTION`
- `LEGAL_ROLE`
- `POLICE_STATION`
- `FIR_NUMBER`
- `LEGAL_PROCEDURE`

Learned predictions must not override exact or overlapping deterministic
predictions for these types except under a future documented exception.

## Learned-Preferred Entity Types

Learned enrichment is preferred for:

- `PERSON`
- `ORGANIZATION`
- `LOCATION`
- `CASE_NAME`

Shared types requiring conflict policy:

- `COURT`
- `DATE`
- `OFFENCE`
- `CASE_CITATION`

## Merge Rules

`backend.app.services.hybrid_legal_ner.merge_hybrid_entities` merges
deterministic and learned canonical entities.

Rules:

- preserve original offsets
- remove exact duplicate span/type predictions
- preserve provenance
- suppress learned predictions below `LEGAL_NER_MIN_CONFIDENCE`
- protected deterministic entities win overlapping conflicts
- same-span different-type conflicts use centralized type priority
- shared-type boundary replacement is allowed only for same-type overlaps and
  no protected conflict
- output ordering is stable by start offset, longest span, and type

## Overlap Policy

For `Section 302 IPC`, deterministic `SECTION` and `STATUTE` spans are
protected. A learned overlapping generic span such as `302 IPC` must be
suppressed.

For court/date/offence/citation spans, learned boundary improvement may be
accepted only when it overlaps a single existing entity of the same type and
does not touch a protected deterministic entity.

## Confidence Policy

Default learned threshold:

`LEGAL_NER_MIN_CONFIDENCE=0.7`

Thresholds must not be tuned on the 36-example gold set in this design step.
Future candidate trials should evaluate fixed candidate thresholds and report
precision, recall, F1, latency, and protected conflict suppressions.

## Candidate Model Feasibility

| Candidate | Status | Token Classification | Local | Notes |
|---|---|---|---|---|
| `dslim/bert-base-NER` | NOT_LOCAL | yes | no | General English CoNLL-style PER/ORG/LOC/MISC candidate; useful for named-entity gaps, not legal structural spans. |
| `shreyas2809/IN_Lexi_X_BERT` | NOT_LOCAL | yes | no | Indian legal NER model card reports token classification labels including court, date, org, parties, provision, statute; gated/contact-share access noted in public card. |
| `evolawyer/inlegalbert-sc-ner-silver` | NOT_LOCAL | yes | no | Indian Supreme Court NER checkpoint with Apache-2.0 card; trained on silver labels, useful candidate but not locally cached. |
| `opennyaiorg/en_legal_ner_trf` | NOT_LOCAL | yes, spaCy pipeline | no | Indian court judgment NER spaCy transformer; project environment lacks spaCy. |
| `legal-text-classification/IndianLegalBERT` | INCOMPATIBLE | no, sequence classification | no | Not a token-classification NER checkpoint. |
| local `BAAI/bge-m3` | INCOMPATIBLE | no | yes | Embedding model, not NER. |
| local `BAAI/bge-reranker-v2-m3` | INCOMPATIBLE | no | yes | Reranker, not NER. |
| local `sentence-transformers/all-MiniLM-L6-v2` | INCOMPATIBLE | no | yes | Sentence embedding model, not NER. |

Local environment:

- `torch`: installed
- `transformers`: installed
- `spacy`: not installed
- CUDA: unavailable
- MPS: unavailable
- feasible device for future trial: CPU

## InLegalBERT Status

No local usable InLegalBERT token-classification checkpoint was found. The
existing `INLEGALBERT_MODEL_PATH=./models/inlegalbert-finetuned` remains an
architectural placeholder unless a real token-classification checkpoint is
provided later.

Status: no local usable InLegalBERT NER artifact.

## Case-Name Strategy

Generic NER models usually do not expose `CASE_NAME`. Preferred next design:

1. add a conservative deterministic `v.` / `vs.` case-title recognizer
2. allow learned person/org spans to assist boundary checks
3. consider a future custom label only if deterministic case-title rules fail

## Court Considerations

Current court errors are mostly boundary errors where deterministic extraction
includes leading words such as `the` or `Can the`. Improve deterministic court
normalization before relying on learned `ORG`/`LOC` labels for courts.

## Date Considerations

Current date errors are boundary-policy issues, especially transition phrases
such as `after 1 July 2024` versus `1 July 2024`. Improve deterministic date
span policy separately before depending on learned NER for dates.

## Offence Considerations

General NER models usually do not output `OFFENCE`. Treat offence extraction as
a separate legal semantic problem: deterministic legal lexicon, classifier, or
future legal sequence labeler.

## Evaluation Harness

`backend/scripts/evaluate_hybrid_legal_ner.py` validates learned prediction
manifests and compares:

- deterministic baseline
- learned-only predictions above threshold
- hybrid merged predictions

It reports exact span+type metrics, per-type metrics, span-only metrics,
learned added TP/FP, learned filled FN, protected deterministic counts,
protected-overlap suppressions, and merge timing.

Prediction template:

`data/structured/manifests/legal_ner_learned_predictions_template.json`

## Acceptance Criteria

A learned model should be promoted only if:

- recall improves materially
- overall F1 improves
- deterministic precision is not badly degraded
- protected legal entity performance remains stable
- latency is acceptable on the target device

## Latency Considerations

Future candidate trials should capture:

- `load_time_ms`
- `inference_ms`
- `merge_ms`
- `entity_count`

This design step performs no heavy benchmarking.

## Limitations

- no model was downloaded
- no learned inference was run
- no fine-tuning was performed
- candidate feasibility is based on local inspection and public model cards
- 36-example gold set is small
- no judgment-document NER benchmark exists yet

## Next Step

Run a deliberately authorized learned NER candidate trial using the prediction
manifest format, then evaluate hybrid value before selecting or fine-tuning any
checkpoint.
