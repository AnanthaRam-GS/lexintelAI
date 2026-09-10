# Retrieval Evaluation Results

## Benchmark Snapshot

- queries: 30
- human judgments: 695
- corpus: 70 trusted judgments / 1356 chunks

## Systems

- BM25: legalai-bm25-index-v1, k1=1.5, b=0.75
- Dense: BAAI/bge-m3, legalai-chroma-index-v1
- Hybrid: RRF, K=60
- Hybrid+Rerank: hybrid RRF plus BAAI/bge-reranker-v2-m3, max_length=512

## Relevance Policies

Broad relevance treats grades 1 and 2 as relevant. Strict relevance treats only grade 2 as relevant. Graded nDCG@5 uses gain / log2(rank + 1), with gains 2, 1, and 0.

## Judged Coverage

| System | @5 | @20 |
|---|---:|---:|
| BM25 | 1.000 | 0.727 |
| Dense | 1.000 | 0.725 |
| Hybrid | 1.000 | 0.750 |
| Hybrid+Rerank | 1.000 | 0.750 |

## Overall Metrics

| System | P@5 Broad | Pooled R@5 Broad | Pooled R@20 Broad | MRR@5 Broad | nDCG@5 | Doc Hit@5 | P@5 Strict | Pooled R@5 Strict | MRR@5 Strict | nDCG@5 Strict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.833 | 0.277 | 0.673 | 0.917 | 0.728 | 0.933 | 0.533 | 0.371 | 0.780 | 0.621 |
| Dense | 0.860 | 0.284 | 0.686 | 0.942 | 0.786 | 1.000 | 0.593 | 0.392 | 0.815 | 0.679 |
| Hybrid | 0.873 | 0.286 | 0.705 | 0.961 | 0.787 | 1.000 | 0.593 | 0.401 | 0.824 | 0.678 |
| Hybrid+Rerank | 0.873 | 0.290 | 0.723 | 0.961 | 0.819 | 1.000 | 0.633 | 0.446 | 0.896 | 0.753 |

## Query-Type Breakdown

### hard_ambiguous

queries: 3

| System | P@5 Broad | Pooled R@5 Broad | Pooled R@20 Broad | MRR@5 Broad | nDCG@5 | Doc Hit@5 | P@5 Strict | Pooled R@5 Strict | MRR@5 Strict | nDCG@5 Strict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.933 | 0.271 | N/A | 1.000 | 0.762 | N/A | N/A | N/A | N/A | N/A |
| Dense | 0.867 | 0.250 | N/A | 1.000 | 0.762 | N/A | N/A | N/A | N/A | N/A |
| Hybrid | 0.933 | 0.269 | N/A | 1.000 | 0.779 | N/A | N/A | N/A | N/A | N/A |
| Hybrid+Rerank | 0.867 | 0.250 | N/A | 1.000 | 0.770 | N/A | N/A | N/A | N/A | N/A |

### plain_language

queries: 8

| System | P@5 Broad | Pooled R@5 Broad | Pooled R@20 Broad | MRR@5 Broad | nDCG@5 | Doc Hit@5 | P@5 Strict | Pooled R@5 Strict | MRR@5 Strict | nDCG@5 Strict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.800 | 0.291 | N/A | 0.812 | 0.666 | N/A | N/A | N/A | N/A | N/A |
| Dense | 0.900 | 0.308 | N/A | 0.938 | 0.813 | N/A | N/A | N/A | N/A | N/A |
| Hybrid | 0.875 | 0.299 | N/A | 0.938 | 0.759 | N/A | N/A | N/A | N/A | N/A |
| Hybrid+Rerank | 0.850 | 0.290 | N/A | 0.854 | 0.734 | N/A | N/A | N/A | N/A | N/A |

### procedural_relief

queries: 6

| System | P@5 Broad | Pooled R@5 Broad | Pooled R@20 Broad | MRR@5 Broad | nDCG@5 | Doc Hit@5 | P@5 Strict | Pooled R@5 Strict | MRR@5 Strict | nDCG@5 Strict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.733 | 0.208 | N/A | 0.833 | 0.675 | N/A | N/A | N/A | N/A | N/A |
| Dense | 0.867 | 0.265 | N/A | 1.000 | 0.808 | N/A | N/A | N/A | N/A | N/A |
| Hybrid | 0.767 | 0.223 | N/A | 0.889 | 0.698 | N/A | N/A | N/A | N/A | N/A |
| Hybrid+Rerank | 0.833 | 0.251 | N/A | 1.000 | 0.873 | N/A | N/A | N/A | N/A | N/A |

### statute_explicit

queries: 10

| System | P@5 Broad | Pooled R@5 Broad | Pooled R@20 Broad | MRR@5 Broad | nDCG@5 | Doc Hit@5 | P@5 Strict | Pooled R@5 Strict | MRR@5 Strict | nDCG@5 Strict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.920 | 0.306 | N/A | 1.000 | 0.806 | N/A | N/A | N/A | N/A | N/A |
| Dense | 0.860 | 0.287 | N/A | 0.950 | 0.808 | N/A | N/A | N/A | N/A | N/A |
| Hybrid | 0.960 | 0.320 | N/A | 1.000 | 0.883 | N/A | N/A | N/A | N/A | N/A |
| Hybrid+Rerank | 0.960 | 0.329 | N/A | 1.000 | 0.890 | N/A | N/A | N/A | N/A | N/A |

### transition_regime

queries: 3

| System | P@5 Broad | Pooled R@5 Broad | Pooled R@20 Broad | MRR@5 Broad | nDCG@5 | Doc Hit@5 | P@5 Strict | Pooled R@5 Strict | MRR@5 Strict | nDCG@5 Strict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.733 | 0.280 | N/A | 1.000 | 0.706 | N/A | N/A | N/A | N/A | N/A |
| Dense | 0.733 | 0.280 | N/A | 0.750 | 0.619 | N/A | N/A | N/A | N/A | N/A |
| Hybrid | 0.733 | 0.280 | N/A | 1.000 | 0.730 | N/A | N/A | N/A | N/A | N/A |
| Hybrid+Rerank | 0.733 | 0.280 | N/A | 1.000 | 0.756 | N/A | N/A | N/A | N/A | N/A |

## Regime Diagnostics

### bns_bnss

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 1.000 | 0.846 |
| Dense | 0.900 | 0.855 |
| Hybrid | 0.900 | 0.817 |
| Hybrid+Rerank | 1.000 | 0.921 |

### ipc_crpc

queries: 25

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.872 | 0.749 |
| Dense | 0.872 | 0.794 |
| Hybrid | 0.904 | 0.796 |
| Hybrid+Rerank | 0.896 | 0.825 |

### mixed_or_transition

queries: 3

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.400 | 0.475 |
| Dense | 0.733 | 0.671 |
| Hybrid | 0.600 | 0.694 |
| Hybrid+Rerank | 0.600 | 0.704 |

## Family Diagnostics

### cheating_and_fraud

queries: 3

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.933 | 0.871 |
| Dense | 0.933 | 0.843 |
| Hybrid | 0.933 | 0.900 |
| Hybrid+Rerank | 0.933 | 0.893 |

### conspiracy_common_intention

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.900 | 0.777 |
| Dense | 1.000 | 0.963 |
| Hybrid | 1.000 | 0.925 |
| Hybrid+Rerank | 0.900 | 0.881 |

### criminal_breach_of_trust

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 1.000 | 0.789 |
| Dense | 0.900 | 0.772 |
| Hybrid | 1.000 | 0.761 |
| Hybrid+Rerank | 0.900 | 0.760 |

### dowry_and_domestic_cruelty

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 1.000 | 1.000 |
| Dense | 1.000 | 1.000 |
| Hybrid | 1.000 | 1.000 |
| Hybrid+Rerank | 1.000 | 1.000 |

### homicide

queries: 3

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 1.000 | 0.872 |
| Dense | 0.867 | 0.797 |
| Hybrid | 0.933 | 0.880 |
| Hybrid+Rerank | 0.867 | 0.837 |

### hurt_and_assault

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.700 | 0.554 |
| Dense | 0.700 | 0.689 |
| Hybrid | 0.800 | 0.673 |
| Hybrid+Rerank | 1.000 | 0.931 |

### kidnapping

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.700 | 0.518 |
| Dense | 1.000 | 0.888 |
| Hybrid | 0.900 | 0.702 |
| Hybrid+Rerank | 0.800 | 0.702 |

### narcotics_related

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.900 | 0.708 |
| Dense | 1.000 | 0.910 |
| Hybrid | 1.000 | 0.879 |
| Hybrid+Rerank | 1.000 | 0.931 |

### other

queries: 7

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.657 | 0.655 |
| Dense | 0.800 | 0.729 |
| Hybrid | 0.686 | 0.663 |
| Hybrid+Rerank | 0.771 | 0.811 |

### sexual_offences

queries: 3

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.867 | 0.587 |
| Dense | 0.733 | 0.578 |
| Hybrid | 1.000 | 0.793 |
| Hybrid+Rerank | 0.933 | 0.666 |

### theft_and_robbery

queries: 2

| System | P@5 Broad | nDCG@5 |
|---|---:|---:|
| BM25 | 0.800 | 0.788 |
| Dense | 0.700 | 0.686 |
| Hybrid | 0.700 | 0.692 |
| Hybrid+Rerank | 0.700 | 0.656 |

## Reranker Delta Analysis

- Broad Precision@5 improved queries: 3
- Broad Precision@5 worsened queries: 5
- Broad Precision@5 unchanged queries: 22
- Broad Precision@5 mean rerank delta: 0.0
- Metric deltas are descriptive paired differences, not significance claims.

## Per-Query Comparison

| Query | Type | BM25 P/R20/nDCG | Dense P/R20/nDCG | Hybrid P/R20/nDCG | Rerank P/R20/nDCG | Flags |
|---|---|---:|---:|---:|---:|---|
| eval-q001 | statute_explicit | 1.00/0.60/0.86 | 1.00/0.60/1.00 | 1.00/0.60/0.92 | 1.00/0.60/0.83 | low_judged_coverage_at_20 |
| eval-q002 | statute_explicit | 1.00/0.83/1.00 | 1.00/0.78/1.00 | 1.00/0.78/1.00 | 1.00/0.83/1.00 | low_judged_coverage_at_20 |
| eval-q003 | statute_explicit | 1.00/0.81/0.76 | 1.00/0.88/0.82 | 1.00/0.88/0.76 | 1.00/0.88/0.82 | low_judged_coverage_at_20 |
| eval-q004 | statute_explicit | 1.00/0.80/1.00 | 1.00/0.70/0.93 | 1.00/0.80/1.00 | 1.00/0.80/1.00 | low_judged_coverage_at_20 |
| eval-q005 | statute_explicit | 1.00/0.72/0.85 | 0.20/0.44/0.17 | 1.00/0.56/0.92 | 1.00/0.61/0.81 | document_hit_but_poor_chunk_score, low_judged_coverage_at_20 |
| eval-q006 | statute_explicit | 0.80/0.93/0.79 | 1.00/0.86/1.00 | 1.00/0.79/1.00 | 0.80/0.93/0.87 | low_judged_coverage_at_20 |
| eval-q007 | statute_explicit | 0.80/0.62/0.68 | 1.00/0.88/0.92 | 1.00/0.81/0.89 | 0.80/0.81/0.79 | low_judged_coverage_at_20 |
| eval-q008 | statute_explicit | 1.00/0.76/0.89 | 1.00/0.65/0.93 | 1.00/0.76/0.93 | 1.00/0.71/0.89 | low_judged_coverage_at_20 |
| eval-q009 | statute_explicit | 0.60/0.78/0.46 | 0.40/0.67/0.38 | 0.60/0.89/0.57 | 1.00/0.78/1.00 | low_judged_coverage_at_20 |
| eval-q010 | statute_explicit | 1.00/0.67/0.76 | 1.00/0.80/0.93 | 1.00/0.80/0.85 | 1.00/0.67/0.89 | low_judged_coverage_at_20 |
| eval-q011 | plain_language | 0.80/0.73/0.59 | 1.00/0.67/0.82 | 1.00/0.67/0.92 | 1.00/0.80/0.86 | low_judged_coverage_at_20 |
| eval-q012 | plain_language | 1.00/0.79/1.00 | 1.00/0.79/1.00 | 1.00/0.79/1.00 | 1.00/0.79/1.00 | low_judged_coverage_at_20 |
| eval-q013 | plain_language | 0.80/0.61/0.79 | 1.00/0.67/1.00 | 0.80/0.67/0.83 | 0.80/0.78/0.79 | low_judged_coverage_at_20 |
| eval-q014 | plain_language | 0.80/0.55/0.65 | 1.00/0.75/1.00 | 1.00/0.65/0.78 | 1.00/0.65/0.86 | low_judged_coverage_at_20 |
| eval-q015 | plain_language | 0.60/0.29/0.35 | 1.00/0.93/0.86 | 0.80/0.71/0.51 | 0.80/0.79/0.62 | low_judged_coverage_at_20 |
| eval-q016 | plain_language | 0.60/1.00/0.58 | 0.40/0.40/0.44 | 0.40/0.80/0.38 | 0.40/0.80/0.31 | low_judged_coverage_at_20 |
| eval-q017 | plain_language | 0.80/0.43/0.44 | 1.00/0.64/0.79 | 1.00/0.86/0.72 | 0.80/0.71/0.43 | low_judged_coverage_at_20 |
| eval-q018 | plain_language | 1.00/0.72/0.93 | 0.80/0.56/0.60 | 1.00/0.61/0.93 | 1.00/0.61/1.00 | low_judged_coverage_at_20 |
| eval-q019 | procedural_relief | 1.00/0.93/1.00 | 0.80/0.79/0.87 | 0.80/0.93/0.87 | 1.00/0.93/1.00 | low_judged_coverage_at_20 |
| eval-q020 | procedural_relief | 1.00/0.57/0.75 | 1.00/0.62/0.93 | 1.00/0.67/0.82 | 1.00/0.62/0.92 | low_judged_coverage_at_20 |
| eval-q021 | procedural_relief | 0.40/0.36/0.71 | 0.60/0.64/0.45 | 0.20/0.43/0.11 | 0.60/0.64/0.81 | document_hit_but_poor_chunk_score, low_judged_coverage_at_20 |
| eval-q022 | procedural_relief | 1.00/0.76/0.83 | 1.00/0.53/1.00 | 1.00/0.71/0.84 | 1.00/0.76/1.00 | low_judged_coverage_at_20 |
| eval-q023 | procedural_relief | 1.00/0.48/0.75 | 0.80/0.57/0.60 | 1.00/0.61/0.89 | 0.80/0.61/0.83 | low_judged_coverage_at_20 |
| eval-q024 | procedural_relief | 0.00/0.31/0.00 | 1.00/0.77/1.00 | 0.60/0.62/0.65 | 0.60/0.69/0.68 | low_judged_coverage_at_20, no_strict_qrels, zero_relevant_top5 |
| eval-q025 | transition_regime | 1.00/0.67/0.69 | 1.00/0.83/0.84 | 1.00/0.78/0.76 | 1.00/0.83/0.84 | low_judged_coverage_at_20 |
| eval-q026 | transition_regime | 1.00/0.88/1.00 | 1.00/0.62/0.83 | 1.00/0.75/1.00 | 1.00/0.81/1.00 | low_judged_coverage_at_20 |
| eval-q027 | transition_regime | 0.20/0.75/0.43 | 0.20/0.50/0.18 | 0.20/0.25/0.43 | 0.20/0.25/0.43 | document_hit_but_poor_chunk_score, low_judged_coverage_at_20 |
| eval-q028 | hard_ambiguous | 1.00/0.62/1.00 | 0.80/0.50/0.79 | 0.80/0.62/0.83 | 0.80/0.56/0.85 | low_judged_coverage_at_20, no_strict_qrels |
| eval-q029 | hard_ambiguous | 0.80/0.50/0.47 | 1.00/0.78/0.78 | 1.00/0.61/0.74 | 1.00/0.72/0.76 | low_judged_coverage_at_20 |
| eval-q030 | hard_ambiguous | 1.00/0.72/0.82 | 0.80/0.78/0.72 | 1.00/0.78/0.76 | 0.80/0.72/0.70 | low_judged_coverage_at_20 |

## Difficult Query Analysis

- eval-q001 tests Section 302 murder retrieval and shows high sensitivity to chunk-level ranking.
- eval-q009 tests Section 323 hurt retrieval and has sparse direct relevance.
- eval-q024 has no grade-2 qrels, so strict recall/nDCG are not applicable for that query.
- eval-q026 and eval-q027 represent IPC/BNS/BNSS transition cases with small judged pools.
- eval-q028 has no grade-2 qrels and should be read as a composite-query coverage diagnostic.

## Statistical Uncertainty

A deterministic paired bootstrap with 10,000 resamples is included in retrieval_eval_bootstrap.json. Confidence intervals are descriptive and should not be overread as proof of significance.

## Limitations

- trusted corpus contains only 70 judgments / 1356 chunks
- evaluation pool is pooled, not exhaustive
- Recall is pooled recall
- top20 may contain unjudged candidates
- human labels are from one reviewer
- n=30 queries is relatively small
- transition-law subsets are especially small
- benchmark was built from the existing corpus
- this is retrieval evaluation, not answer-generation evaluation
