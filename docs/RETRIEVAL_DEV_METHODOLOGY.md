# Retrieval Development Set Methodology

This development set is separate from the frozen 30-query benchmark and is intended only for targeted tuning experiments.

## Purpose

The set emphasizes legal-regime filtering/boosting, query expansion, and metadata-aware reranking, based on the frozen error analysis.

## Query Design

The set contains 20 corpus-supported queries: 6 legal-regime/transition, 5 composite/ambiguous, 4 query-expansion-sensitive plain-language, 3 metadata-sensitive, and 2 hard-negative queries.

## Candidate Pooling

Pooling uses the frozen BM25, BGE-M3 dense, Hybrid RRF, and Hybrid+BGE-reranker stack with unchanged parameters. Candidate pools are deterministic, blinded, and separate from machine traces.

## Review Workload

Total candidate judgments: 474. Mean candidates/query: 23.7.

No retrieval tuning, query expansion implementation, metadata reranking implementation, RRF change, BM25 change, or answer generation is performed in this step.
