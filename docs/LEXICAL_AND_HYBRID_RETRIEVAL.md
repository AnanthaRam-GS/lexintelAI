# Lexical And Hybrid Retrieval

This phase adds deterministic BM25 lexical retrieval and Reciprocal Rank Fusion over the existing real BGE-M3 Chroma dense index.

## Scope

- documents: 70
- chunks: 1356
- trusted 0.5A chunks only

## BM25

- implementation: internal local BM25
- index version: `legalai-bm25-index-v1`
- tokenizer version: `legalai-legal-tokenizer-v1`
- k1: 1.5
- b: 0.75
- no generic English stopword list is applied
- statute normalization preserves legal tokens and adds safe alternates such as `304-B`/`304B` and `498-A`/`498A`

## Dense Reuse

Dense retrieval reuses the existing BGE-M3 embedding provider and Chroma vector-store abstraction. It does not create a second dense index path.

## Hybrid

Hybrid retrieval uses Reciprocal Rank Fusion with RRF_K=60. Each retriever contributes up to candidate_k=20; duplicates are fused by `chunk_id`.

## Score Semantics

Dense scores are Chroma cosine similarities derived from `1 - distance`. BM25 scores are lexical relevance scores. Hybrid scores are RRF scores. These scores are diagnostic and not directly interchangeable.

## Filters

The retrieval service accepts optional `effective_legal_regime`, `effective_offence_family`, and `court` filters. Filters are infrastructure only and are not query-derived.

## CLI

```bash
python3 backend/scripts/build_lexical_index.py --dry-run
python3 backend/scripts/build_lexical_index.py --rebuild
HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --query "murder section 302 IPC" --mode hybrid --top-k 5 --candidate-k 20
HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --qa
```

No reranker, LLM/RAG generation, Gemini, Ollama, InLegalBERT, query NLP/NER, or formal retrieval benchmark is implemented in this phase.
