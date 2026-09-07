# Retrieval Evaluation Methodology

Human labels are required because prior sanity queries are diagnostic only and cannot support formal retrieval metrics.

## Corpus

The benchmark uses only the trusted 70-judgment, 1356-chunk corpus.

## Query Design

The query set contains exactly 30 corpus-supported queries across statute-explicit, plain-language, procedural/relief, transition/regime, and hard ambiguous categories.

## Candidate Pooling

Pooling version `legalai-retrieval-pool-v1` uses BM25, dense BGE-M3, hybrid RRF, and hybrid plus BGE reranker. It retrieves depth 20 and caps blinded pools at 25 candidates per query while retaining each system top 5.

## Blinding

The human review packet omits retriever ranks and scores. Machine traces are stored separately.

## Relevance Grades

2 means directly/highly relevant. 1 means partially useful. 0 means not materially relevant. uncertain is separate and is not automatically relevant.

## Chunk And Document Relevance

Reviewers judge chunk relevance and separately mark whether the document is relevant, allowing right-judgment/wrong-chunk cases.

## Future Metrics

Step 0.5E-L2 may compute Precision@5, pooled Recall@5, pooled Recall@20, MRR, and nDCG@5 after labels exist. Recall is pooled recall unless exhaustive corpus relevance is established.

## Frozen Configuration

- dense: `BAAI/bge-m3`
- BM25: k1=1.5, b=0.75
- hybrid RRF K: 60
- reranker: `BAAI/bge-reranker-v2-m3`

No Gemini, Ollama, external LLM, InLegalBERT, retrieval tuning, answer generation, or formal metric reporting is performed in this task.
