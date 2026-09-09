# Legal Query Understanding Orchestration

## Purpose

The query-understanding orchestration layer combines the frozen Phase 0 legal query-analysis components into one typed, deterministic, provenance-aware enrichment object before retrieval.

It does not retrieve documents, generate answers, train models, tune models, or change frozen evaluation artifacts.

## Frozen Component Inputs

- deterministic legal query analysis: `legalai-query-analysis-v1`
- deterministic legal NER schema: `legalai-ner-schema-v1`
- section candidate generator: `legalai-section-prediction-baseline-v1`
- section ranking selection: `legalai-section-selected-configuration-v1`
- retrieval selection: frozen separately and not executed here

## Priority Policy

Signal authority is frozen in this order:

1. original query
2. explicit user-provided statutes and sections
3. deterministic high-confidence legal signals
4. deterministic NER
5. procedure, offence-family, and regime signals
6. predicted or reranked sections as supplementary evidence only

Predicted sections must not override explicit user sections.

## Schema

`LegalQueryUnderstanding` contains the original query, normalized query, deterministic analysis, deterministic NER entities, explicit statutes, explicit sections, procedural posture, offence-family hints, legal-regime resolution, predicted sections, warnings, conflicts, provenance, versions, timings, fallback status, and a `LegalRetrievalEnrichment` view.

The result serializes to JSON without model objects, tokenizers, tensors, or arrays.

## Execution Flow

The service entry point is:

```python
understand_legal_query(query, section_ranking_mode=None, section_ranker=None)
```

The deterministic flow is:

1. preserve raw query exactly
2. run `analyze_legal_query(query)`
3. run deterministic legal NER
4. resolve legal regime through the frozen resolver
5. reuse deterministic section candidates from query analysis
6. rank deterministically by default
7. return a typed `LegalQueryUnderstanding`

## Explicit Section Authority

Explicit section mentions keep their original statute and section fields. Duplicate predicted sections are treated as supporting explicit evidence when the deterministic predictor marks them `supports_explicit`.

The orchestrator does not delete, replace, rewrite, or suppress explicit sections merely because a predicted or ranked section differs.

## NER Integration

NER uses the frozen deterministic configuration. Rejected learned NER models are not invoked, and hybrid NER remains disabled.

## Regime Integration

The orchestrator reuses `resolve_legal_regime`. Broad regimes remain `ipc_crpc`, `bns_bnss`, `mixed_or_transition`, and `unknown`.

Mixed or transition contexts preserve both old-code and new-code evidence. Unknown regime does not force certainty.

## Section Ranking Integration

Default section ranking is deterministic. The selected Phase 0 learned architecture is `BAAI/bge-reranker-v2-m3` cross-encoder protected hybrid, but it is not loaded by default and is not wired globally in this task.

Cross-encoder mode is available only through explicit mode selection and an injected/local ranker adapter. The ranker receives only the bounded deterministic candidates and must return top-k <= 5.

## Cross-Encoder Fallback

If `cross_encoder_protected_hybrid` is requested but no ranker is available, the orchestrator falls back to deterministic ranking and records `SECTION_RANKER_FALLBACK_DETERMINISTIC`.

Public or legal-query handling must not fail solely because the learned reranker is absent.

## Warnings and Conflicts

Warnings are structured with a code, message, and source. Current warning codes include `AMBIGUOUS_LEGAL_REGIME`, `SECTION_RANKER_FALLBACK_DETERMINISTIC`, `LOW_CONFIDENCE_OFFENCE_FAMILY`, `NO_SECTION_CANDIDATES`, and `TRANSITIONAL_LAW_CONTEXT`.

Conflicts are reserved for useful structured cases such as explicit old/new statute mixes or predicted sections that conflict with explicit user sections.

## Provenance

The result records provenance entries for the original query, explicit section extraction, deterministic NER, regime resolution, deterministic section prediction, and cross-encoder ranking when an injected ranker is used.

Deterministic inference is not labeled as user-provided.

## Timings

The timings object records query analysis, NER, regime resolution, section candidate handling, section ranking, and total orchestration time in milliseconds.

Unit tests only assert schema presence and non-negative timing values.

## Retrieval Enrichment View

`LegalRetrievalEnrichment` prepares structured fields that future retrieval orchestration may consume: original query, explicit sections, statutes, offence families, procedural posture, regime, and predicted sections.

It does not build a weighted retrieval query string and does not activate query expansion.

## Retrieval Boundary

The orchestration layer stops before BM25 retrieval, dense retrieval, retrieval RRF, retrieval reranking, prompt construction, and answer generation.

## Limitations

- deterministic extraction quality is inherited from the frozen components
- default runtime remains deterministic
- learned section ranking requires a separate injected/local adapter
- no document retrieval or answer generation is performed
- no new model trial, threshold tuning, or fine-tuning is performed

## Future RAG Integration

A later orchestration layer can consume `LegalQueryUnderstanding` and `LegalRetrievalEnrichment` to configure retrieval, citation planning, and answer behavior. That future layer must preserve the same priority policy: original query and explicit user sections remain authoritative.
