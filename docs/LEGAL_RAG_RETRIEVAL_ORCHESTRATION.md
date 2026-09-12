# Legal RAG Retrieval Orchestration

Phase 0 Step 0.8B adds the first answer-generation-safe retrieval boundary for LegalAI.
It consumes a completed `LegalQueryUnderstanding` object and returns citation-ready
evidence from the frozen retrieval stack. It does not generate answers, call an LLM,
tune retrieval, expand the query, or alter legal NER/section prediction artifacts.

## Contract

Primary API:

```python
retrieve_legal_evidence(
    understanding: LegalQueryUnderstanding,
    *,
    retrieval_service: RetrievalService,
    top_k: int = 5,
    candidate_depth: int = 20,
) -> LegalRetrievalResult
```

The orchestration passes only `understanding.query` to retrieval. Deterministic query
understanding fields are preserved in `understanding_summary` for provenance and later
answer planning, but predicted sections, regimes, offence families, and procedural
posture are not used as retrieval filters, boosts, or query expansion terms.

## Frozen Stack

The wrapper encodes the selected Phase 0 retrieval decision:

- Decision: `RETAIN_UNTUNED_HYBRID_RERANK`
- BM25 index: `legalai-bm25-index-v1`
- Tokenizer: `legalai-legal-tokenizer-v1`
- BM25 parameters: `k1=1.5`, `b=0.75`
- Dense model: `BAAI/bge-m3`
- Dense embedding dimension: `1024`
- Dense collection: `legalai_trusted_judgments_v1`
- Fusion: Reciprocal Rank Fusion with `K=60`
- Candidate depth: `20`
- Reranker: `BAAI/bge-reranker-v2-m3`
- Reranker configuration: `max_length=512`, `batch_size=8`
- Final evidence count: top `5`

The following experimental paths remain disabled: legal-regime-aware ranking, query
expansion, metadata-aware reranking, learned NER loading, and answer generation.

## Result Shape

`LegalRetrievalResult` contains:

- the original query and query-understanding schema version;
- the frozen retrieval configuration;
- an understanding summary marked `retrieval_query_policy="original_query_only"`;
- ordered `LegalEvidenceChunk` records with stable citation IDs such as `E1`;
- citation metadata including document ID, judgment ID, court, case name, date,
  source URL, pages, and paragraph range when available;
- BM25, dense, RRF, and reranker scores/ranks where the retrieval stack supplies them;
- stage counts and timings;
- structured warnings and optional structured retrieval error details.

Citation metadata is copied from stored chunk metadata only. The orchestrator does not
invent missing citations.

## Failure Policy

The frozen stack has no hidden fallback. If a required dependency is unavailable, the
result contains no evidence, no fallback entry, and an `error` object with one of these
codes where detectable:

- `BM25_UNAVAILABLE`
- `DENSE_INDEX_UNAVAILABLE`
- `RERANKER_UNAVAILABLE`
- `RETRIEVAL_DEPENDENCY_UNAVAILABLE`

Other warning codes include:

- `NO_RETRIEVAL_RESULTS`
- `INCOMPLETE_EVIDENCE_PROVENANCE`

## Diagnostic CLI

Use the smoke-test CLI for local inspection:

```bash
.venv/bin/python backend/scripts/retrieve_legal_evidence.py "Section 302 IPC murder bail before Sessions Court"
```

By default, full chunk text is omitted from the JSON output. Add `--include-text` only
when inspecting stored normalized text. The CLI sets Hugging Face offline flags before
loading the frozen models, so it is suitable for cache-only validation and will not
start a new model download.

## Boundary For Step 0.8C

This layer stops at ranked, citation-ready evidence. Later answer-generation work must
treat this result as its grounding input and should fail closed when evidence is empty
or provenance warnings are material.
