# Retrieval Development Baseline Results

## Development-Set Snapshot

- queries: 20
- human judgments: 474
- development version: `legalai-retrieval-dev-v1`

## Systems

- BM25: legalai-bm25-index-v1, k1=1.5, b=0.75
- Dense: BAAI/bge-m3, legalai-chroma-index-v1
- Hybrid: RRF K=60
- Hybrid+Rerank: Hybrid RRF plus BAAI/bge-reranker-v2-m3, max_length=512

## Relevance Policies

Broad relevance is grade 1 or 2. Strict relevance is grade 2 only. Graded nDCG uses the frozen benchmark convention: gain / log2(rank + 1).

## Judged Coverage

| System | @5 | @20 |
|---|---:|---:|
| BM25 | 1.000 | 0.740 |
| Dense | 1.000 | 0.735 |
| Hybrid | 1.000 | 0.750 |
| Hybrid+Rerank | 1.000 | 0.750 |

## Overall Metric Table

| Metric | BM25 | Dense | Hybrid | Hybrid+Rerank |
|---|---:|---:|---:|---:|
| broad_precision_at_5 | 0.760 | 0.780 | 0.810 | 0.870 |
| broad_pooled_recall_at_5 | 0.296 | 0.301 | 0.318 | 0.343 |
| broad_pooled_recall_at_20 | 0.666 | 0.692 | 0.744 | 0.775 |
| broad_mrr_at_5 | 0.975 | 0.850 | 0.967 | 0.925 |
| graded_ndcg_at_5 | 0.601 | 0.663 | 0.675 | 0.723 |
| document_hit_at_5 | 1.000 | 0.950 | 1.000 | 0.950 |
| strict_precision_at_5 | 0.250 | 0.370 | 0.330 | 0.390 |
| strict_pooled_recall_at_5 | 0.267 | 0.385 | 0.323 | 0.391 |
| strict_pooled_recall_at_20 | N/A | N/A | N/A | N/A |
| strict_mrr_at_5 | 0.550 | 0.662 | 0.633 | 0.696 |
| strict_binary_ndcg_at_5 | 0.335 | 0.488 | 0.439 | 0.509 |

## Query-Type Breakdown

### composite_ambiguous

queries: 5

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.640 | 0.197 | 1.000 | 0.555 |
| Dense | 0.880 | 0.277 | 1.000 | 0.849 |
| Hybrid | 0.920 | 0.290 | 1.000 | 0.780 |
| Hybrid+Rerank | 0.920 | 0.290 | 1.000 | 0.810 |

### hard_negative

queries: 2

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 1.000 | 0.335 | 1.000 | 0.665 |
| Dense | 0.800 | 0.263 | 0.750 | 0.550 |
| Hybrid | 1.000 | 0.335 | 1.000 | 0.750 |
| Hybrid+Rerank | 1.000 | 0.335 | 1.000 | 0.844 |

### legal_regime_transition

queries: 6

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.833 | 0.390 | 1.000 | 0.611 |
| Dense | 0.833 | 0.374 | 0.917 | 0.674 |
| Hybrid | 0.833 | 0.374 | 1.000 | 0.649 |
| Hybrid+Rerank | 0.867 | 0.406 | 1.000 | 0.663 |

### metadata_sensitive

queries: 3

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.667 | 0.294 | 0.833 | 0.578 |
| Dense | 0.533 | 0.169 | 0.500 | 0.392 |
| Hybrid | 0.400 | 0.185 | 0.778 | 0.342 |
| Hybrid+Rerank | 0.600 | 0.193 | 0.500 | 0.383 |

### plain_language_expansion

queries: 4

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.750 | 0.262 | 1.000 | 0.629 |
| Dense | 0.750 | 0.337 | 0.875 | 0.673 |
| Hybrid | 0.850 | 0.362 | 1.000 | 0.795 |
| Hybrid+Rerank | 0.950 | 0.432 | 1.000 | 0.900 |

## Tuning-Focus Breakdown

Focus groups overlap and are not mutually exclusive.

### composite_reasoning

queries: 5

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.640 | N/A | 1.000 | 0.555 |
| Dense | 0.880 | N/A | 1.000 | 0.849 |
| Hybrid | 0.920 | N/A | 1.000 | 0.780 |
| Hybrid+Rerank | 0.920 | N/A | 1.000 | 0.810 |

### hard_negative

queries: 6

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.700 | N/A | 1.000 | 0.619 |
| Dense | 0.800 | N/A | 0.917 | 0.711 |
| Hybrid | 0.867 | N/A | 1.000 | 0.739 |
| Hybrid+Rerank | 0.967 | N/A | 1.000 | 0.868 |

### legal_regime

queries: 6

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.833 | N/A | 1.000 | 0.611 |
| Dense | 0.833 | N/A | 0.917 | 0.674 |
| Hybrid | 0.833 | N/A | 1.000 | 0.649 |
| Hybrid+Rerank | 0.867 | N/A | 1.000 | 0.663 |

### metadata_reranking

queries: 8

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.725 | N/A | 0.938 | 0.538 |
| Dense | 0.675 | N/A | 0.688 | 0.528 |
| Hybrid | 0.700 | N/A | 0.917 | 0.521 |
| Hybrid+Rerank | 0.800 | N/A | 0.812 | 0.583 |

### query_expansion

queries: 7

| System | Broad P@5 | Broad R@5 | Broad MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|
| BM25 | 0.829 | N/A | 1.000 | 0.652 |
| Dense | 0.857 | N/A | 0.929 | 0.710 |
| Hybrid | 0.914 | N/A | 1.000 | 0.787 |
| Hybrid+Rerank | 0.943 | N/A | 1.000 | 0.837 |

## Reranker Delta

- Broad P@5 improved/worsened/unchanged: 6/2/12
- Broad P@5 mean delta: 0.06
- Graded nDCG@5 mean delta: 0.048365

## Candidate Complementarity

- broad BM25 relevant top20: 186
- broad Dense relevant top20: 188
- broad intersection: 99
- broad BM25-only: 87
- broad Dense-only: 89
- broad union: 275

## Difficult-Query Observations

- dev-q001: top20 judged coverage is censored; broad qrels=15, strict qrels=5.
- dev-q002: top20 judged coverage is censored; broad qrels=10, strict qrels=2.
- dev-q003: top20 judged coverage is censored; broad qrels=9, strict qrels=4.
- dev-q004: top20 judged coverage is censored; broad qrels=7, strict qrels=4.
- dev-q006: no strict grade-2 qrels in development pool; broad qrels=10, strict qrels=0.
- dev-q007: no strict grade-2 qrels in development pool; broad qrels=20, strict qrels=0.
- dev-q010: top20 judged coverage is censored; broad qrels=12, strict qrels=8.
- dev-q012: top20 judged coverage is censored; broad qrels=5, strict qrels=3.
- dev-q016: top20 judged coverage is censored; broad qrels=18, strict qrels=7.
- dev-q019: top20 judged coverage is censored; broad qrels=16, strict qrels=8.

## Development-Set Caveat

THIS DEVELOPMENT SET IS FOR TUNING. Future variants may be selected using this dev-set performance. Dev-set gains are not unbiased final performance estimates; the original 30-query frozen benchmark remains the baseline reference set for later post-tuning evaluation.

## Limitations

- only 20 dev queries
- same 70-judgment / 1356-chunk trusted corpus
- pooled qrels are non-exhaustive
- top20 may be censored
- one human reviewer
- dev set intentionally emphasizes known weak areas
- this set is for tuning, not unbiased final reporting
- retrieval only, not answer generation
