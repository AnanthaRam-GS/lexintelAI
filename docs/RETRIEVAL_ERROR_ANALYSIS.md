# Retrieval Error Analysis

This diagnosis uses only frozen human qrels, frozen machine traces, and frozen benchmark metrics. No retrieval systems were rerun.

## Overall Diagnosis

Most baseline weakness is localized rather than systemic: hybrid retrieval is broadly strong, reranking improves graded ordering, and remaining failures cluster around sparse transition-law/regime resolution, ambiguous composite queries, and chunk/document granularity.

## Candidate Generation

- broad BM25 relevant top20: 312
- broad Dense relevant top20: 327
- broad intersection: 171
- broad union: 468
- broad BM25-only / Dense-only: 141 / 156

## Reranker Findings

- helpful: 14
- neutral: 5
- harmful: 11

## Difficult Queries

### eval-q001

- primary failure: `reranker_ordering`
- secondary: benchmark_pool_limitation
- tuning could plausibly help: True
- evidence: eval-q001: broad relevant 25, strict relevant 14; BM25/Dense top20 broad relevant 15/15; Hybrid/Rerank P@5 1.0/1.0; rerank nDCG delta -0.087806; right-document/wrong-chunk 0.

### eval-q009

- primary failure: `benchmark_pool_limitation`
- secondary: none
- tuning could plausibly help: False
- evidence: eval-q009: broad relevant 9, strict relevant 1; BM25/Dense top20 broad relevant 7/6; Hybrid/Rerank P@5 0.6/1.0; rerank nDCG delta 0.430612; right-document/wrong-chunk 0.

### eval-q016

- primary failure: `mixed`
- secondary: candidate_generation_dense, fusion_ordering, reranker_ordering, benchmark_pool_limitation
- tuning could plausibly help: True
- evidence: eval-q016: broad relevant 5, strict relevant 2; BM25/Dense top20 broad relevant 5/2; Hybrid/Rerank P@5 0.4/0.4; rerank nDCG delta -0.07232; right-document/wrong-chunk 0.

### eval-q024

- primary failure: `mixed`
- secondary: candidate_generation_lexical, fusion_ordering, legal_regime_resolution, benchmark_pool_limitation
- tuning could plausibly help: True
- evidence: eval-q024: broad relevant 13, strict relevant 0; BM25/Dense top20 broad relevant 4/10; Hybrid/Rerank P@5 0.6/0.6; rerank nDCG delta 0.029543; right-document/wrong-chunk 0.

### eval-q025

- primary failure: `legal_regime_resolution`
- secondary: candidate_generation_lexical, benchmark_pool_limitation
- tuning could plausibly help: True
- evidence: eval-q025: broad relevant 18, strict relevant 6; BM25/Dense top20 broad relevant 12/15; Hybrid/Rerank P@5 1.0/1.0; rerank nDCG delta 0.077358; right-document/wrong-chunk 0.

### eval-q026

- primary failure: `legal_regime_resolution`
- secondary: candidate_generation_dense, benchmark_pool_limitation
- tuning could plausibly help: True
- evidence: eval-q026: broad relevant 16, strict relevant 5; BM25/Dense top20 broad relevant 14/10; Hybrid/Rerank P@5 1.0/1.0; rerank nDCG delta 0.0; right-document/wrong-chunk 0.

### eval-q027

- primary failure: `legal_regime_resolution`
- secondary: benchmark_pool_limitation
- tuning could plausibly help: True
- evidence: eval-q027: broad relevant 4, strict relevant 3; BM25/Dense top20 broad relevant 3/2; Hybrid/Rerank P@5 0.2/0.2; rerank nDCG delta 0.0; right-document/wrong-chunk 0.

### eval-q028

- primary failure: `mixed`
- secondary: fusion_ordering, chunk_quality, query_ambiguity, benchmark_pool_limitation
- tuning could plausibly help: True
- evidence: eval-q028: broad relevant 16, strict relevant 0; BM25/Dense top20 broad relevant 10/8; Hybrid/Rerank P@5 0.8/0.8; rerank nDCG delta 0.023512; right-document/wrong-chunk 6.
