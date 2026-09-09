# Legal NER Foundation

Phase 0 Step 0.6B defines the LegalAI canonical NER schema, deterministic
baseline, future model adapter contract, evaluation manifest, and human review
workflow. NER is an enrichment layer and remains optional.

## Canonical Taxonomy

Schema version: `legalai-ner-schema-v1`

Canonical entity types:

- `PERSON`
- `ORGANIZATION`
- `COURT`
- `LOCATION`
- `DATE`
- `STATUTE`
- `SECTION`
- `CASE_CITATION`
- `CASE_NAME`
- `LEGAL_PROCEDURE`
- `OFFENCE`
- `LEGAL_ROLE`
- `POLICE_STATION`
- `FIR_NUMBER`

The taxonomy is deliberately small. `POLICE_STATION` and `FIR_NUMBER` are
included because they are common criminal-procedure query entities and can be
detected conservatively.

## Label Mapping

Model or extractor labels are centralized in
`backend.app.services.legal_ner.LABEL_MAPPING`.

Examples:

- `PER`, `PERSON`, `B-PER`, `I-PER` map to `PERSON`.
- `ORG`, `ORGANISATION`, `ORGANIZATION` map to `ORGANIZATION`.
- `LAW`, `ACT`, `STATUTE` map to `STATUTE`.
- `PROCEDURE` maps to `LEGAL_PROCEDURE`.
- `FIR` maps to `FIR_NUMBER`.

Mappings are deterministic and versioned by the canonical schema version.

## Deterministic Baseline

`extract_deterministic_entities(text)` reuses the Phase 0.6A query-analysis
foundation. It bridges existing trusted signals into canonical NER entities:

- statutes to `STATUTE`
- explicit sections to `SECTION`
- dates to `DATE`
- court mentions to `COURT`
- procedural posture to `LEGAL_PROCEDURE`
- offence-family hints to `OFFENCE`

It also includes narrow deterministic patterns for:

- case citations
- FIR numbers
- police-station references
- legal roles

The baseline does not invent entities and does not call a model.

## Merge Rules

Entity merge behavior is deterministic:

- exact duplicate span and type collapse
- provenance is preserved
- overlapping entities are resolved by protected deterministic statute/section
  signals first, then longer span, then confidence, then canonical type
- output is ordered by `start_char`, longest span, then entity type

Deterministic statute and section entities are not silently overwritten by a
lower-confidence learned label.

## Offset Policy

All character offsets refer to the original query text. Entity `text` is the
exact original span. Normalization is stored separately in `normalized_text`.

Synthetic token-classification alignment utilities support BIO/BIOES-like
labels, ignore special tokens, merge subword token spans by character offsets,
and preserve original whitespace and punctuation between token spans.

## Model Adapter

`LegalNERModel` defines the future learned-model adapter:

```python
extract(text: str) -> list[CanonicalEntity]
```

`DisabledLegalNERModel` is the safe default and always returns an empty list.
Configuration defaults keep learned NER off:

- `LEGAL_NER_ENABLED=false`
- `LEGAL_NER_MODEL=`
- `LEGAL_NER_DEVICE=cpu`

## Local Model Feasibility

Local inspection found BGE-M3 and BGE reranker cache entries only:

- `BAAI/bge-m3`
- `BAAI/bge-reranker-v2-m3`

These are not NER models. `requirements.txt` does not list `transformers`, and
no local InLegalBERT token-classification checkpoint was verified. The existing
`INLEGALBERT_MODEL_PATH=./models/inlegalbert-finetuned` is treated as an
architectural placeholder unless a real token-classification checkpoint is
provided later.

Current status: `C. no local usable InLegalBERT artifact`.

Selected status for now: disabled/null adapter.

## Evaluation Dataset

Machine manifest:

`data/structured/manifests/legal_ner_eval.json`

The manifest contains 36 independently authored examples, all with:

- `gold_entities = []`
- `review_status = pending`

This means formal deterministic-baseline F1 is not reported yet.

Human review packet:

`docs/LEGAL_NER_REVIEW.md`

## Metrics

`exact_entity_metrics(predicted, gold)` reports:

- entity-level exact span+type precision
- entity-level exact span+type recall
- entity-level exact span+type F1
- per-type precision, recall, F1, and counts

Overlapping spans are not counted as exact matches unless start, end, and type
match exactly.

## Limitations

This phase does not fine-tune InLegalBERT, download checkpoints, run learned
NER inference, generate fake gold annotations, change retrieval, or implement
section prediction.

Next step: complete human gold annotation for the pending NER evaluation set.
