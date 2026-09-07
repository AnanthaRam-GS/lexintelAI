# Reranking Foundation

This phase adds a BGE reranking layer over existing dense, lexical, or hybrid retrieval candidates. It does not generate answers or perform formal retrieval evaluation.

## Reranker Choice

- model: `BAAI/bge-reranker-v2-m3`
- library: `FlagEmbedding`
- device: `cpu`
- batch size: 8
- max length: 512

## Candidate Flow

Default diagnostic flow retrieves hybrid candidates with candidate_k=20 and reranks to top_k=5. Dense-only and lexical-only reranking are also supported by the same service.

## Score Semantics

The BGE reranker returns model scores for query-passage pairs. They are recorded as `rerank_score`; higher values are treated as better. They are not probabilities or cosine similarities.

## Preservation

Reranking preserves original dense, lexical, and hybrid ranks/scores and all chunk provenance. Final `rank` is the post-rerank position.

## Truncation And Batching

FlagEmbedding pair tokenizer truncates deterministically to max_length, preserving the query and passage prefix per model tokenizer behavior.

Candidate pairs are scored in configurable batches to avoid one model invocation per candidate.

## CLI

```bash
HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --query "murder conviction section 302 IPC" --mode hybrid --candidate-k 20 --top-k 5 --rerank
HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --smoke-reranker
HF_HUB_OFFLINE=1 python3 backend/scripts/query_retrieval.py --rerank-qa
```

No Gemini, Ollama, answer generation, RAG orchestration, query NLP/NER enrichment, InLegalBERT, or formal metrics are implemented here.
