# Retrieval Tuning Decision

## Selected Configuration

RETAIN UNTUNED HYBRID + RERANKER CONFIGURATION.

The selected Phase 0 retrieval path remains:

- BM25 lexical retrieval, `legalai-bm25-index-v1`, tokenizer `legalai-legal-tokenizer-v1`, k1=1.5, b=0.75
- BGE-M3 dense retrieval, `BAAI/bge-m3`, 1024-dimensional normalized embeddings, `legalai-chroma-index-v1`
- Reciprocal Rank Fusion with K=60 and candidate depth 20
- BGE reranking with `BAAI/bge-reranker-v2-m3`, max_length=512, batch_size=8
- final `top_k=5`

## Evaluation Evidence

### Frozen Benchmark

These are existing frozen 30-query benchmark results. No benchmark rerun was performed for this decision.

| System | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 |
|---|---:|---:|---:|---:|---:|---:|
| BM25 | 0.833 | 0.277 | 0.673 | 0.917 | 0.728 | 0.933 |
| Dense | 0.860 | 0.284 | 0.686 | 0.942 | 0.786 | 1.000 |
| Hybrid | 0.873 | 0.286 | 0.705 | 0.961 | 0.787 | 1.000 |
| Hybrid+Rerank | 0.873 | 0.290 | 0.723 | 0.961 | 0.819 | 1.000 |

### Development Baseline

The 20-query development set contains 474 judgments: 103 grade-2, 174 grade-1, 197 grade-0, and 0 uncertain labels.

| System | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 |
|---|---:|---:|---:|---:|---:|---:|
| Hybrid+Rerank | 0.870 | 0.343 | 0.775 | 0.925 | 0.723 | 0.950 |

Strict development metrics for Hybrid+Rerank: P@5 0.390, R@5 0.391, MRR@5 0.696, binary nDCG@5 0.509.

## Experiment T1-A

Deterministic legal-regime-aware retrieval adjustment: INCONCLUSIVE — RETAIN BASELINE.

The resolver produced 15 unknown/low, 3 mixed_or_transition/high, and 2 mixed_or_transition/medium query resolutions. Regime features were too sparse for conservative ranking adjustment; R1/R2/R3 reproduced baseline with no ranking changes and no regressions.

The legal-regime resolver is retained as reusable deterministic infrastructure, but it is not active as a retrieval score modifier.

## Experiment T1-B

Controlled deterministic legal query expansion: INCONCLUSIVE — RETAIN BASELINE.

| Variant | P@5 | nDCG@5 | Outcome |
|---|---:|---:|---|
| Q0 | 0.870 | 0.723 | baseline |
| Q1 | 0.850 | 0.716 | rejected for overall regression |
| Q2 | 0.850 | 0.700 | rejected for overall regression |
| Q3 | 0.850 | 0.700 | rejected for overall regression |

Q1 improved some strict metrics and Q2/Q3 increased BM25 relevant top20 coverage, but expansion did not improve final broad top-5 quality. All variants reduced overall broad P@5 and graded nDCG, and non-target regressions occurred, including a notable dev-q002 regression.

The query-expansion module is retained as experimental/reusable code, but it is not active in the default retrieval path.

## Experiment T1-C

Metadata-aware post-rerank adjustment: INCONCLUSIVE — RETAIN BASELINE.

M0/M1/M2/M3 all produced broad P@5 0.870, graded nDCG@5 0.723, strict P@5 0.390, and strict binary nDCG@5 0.509. Top-5 order changes and top-5 membership changes were both 0.

Metadata features for court, date, posture, family, and regime did fire, but the conservative near-tie adjustment was insufficient to alter rankings. The metadata-intent parser is retained as reusable infrastructure, but it is not active in default retrieval.

## Ablation Summary

| Stage | Variant | Outcome | Reason |
|---|---|---|---|
| Baseline | Hybrid+Rerank | selected | Strong benchmark and dev-set baseline |
| T1-A | Regime adjustment R1/R2/R3 | inconclusive | No ordering movement |
| T1-B | Controlled expansion Q1/Q2/Q3 | inconclusive | Candidate coverage gains did not improve overall top-5 quality |
| T1-C | Metadata adjustment M1/M2/M3 | inconclusive | Feature signals did not alter top-5 order under conservative safeguards |

## Candidate Complementarity

Frozen benchmark broad relevant candidate generation: BM25 312, Dense 327, intersection 171, BM25-only 141, Dense-only 156, union 468 / 473.

Development-set broad relevant candidate generation baseline: BM25 186, Dense 188, intersection 99, BM25-only 87, Dense-only 89, union 275 / 277.

This complementarity supports retaining the hybrid retrieval foundation.

## Why Further Tuning Was Stopped

The baseline Hybrid+Rerank stack is already strong, and three independent development-set experiments did not provide sufficient evidence for promotion. T1-B showed that retrieving additional candidates does not necessarily improve final top-5 quality. T1-A and T1-C showed that conservative post-rerank adjustments did not produce useful ranking movement.

Increasing weights, widening thresholds, or running additional small parameter grids would risk tuning directly to only 20 development queries. Further Phase 0 retrieval tuning is not justified by current evidence.

## Selected Default Pipeline

The default pipeline uses the original query with BM25, BGE-M3 dense retrieval, RRF K=60, BGE reranking, candidate depth 20, and final top_k 5.

## Experimental Features Retained But Disabled

- `legal_regime.py`: keep as reusable deterministic service; not active as retrieval score modifier
- `legal_query_expansion.py`: keep as experimental/reusable service; not active in default retrieval
- `retrieval_metadata_intent.py`: keep as reusable parser; not active in default retrieval

## Frozen Benchmark Policy

No post-tuning frozen benchmark evaluation is required because no tuned variant was accepted. The selected retrieval system is exactly the same configuration already evaluated on the frozen benchmark.

If a materially different retrieval configuration is adopted later, the frozen benchmark may be used once under a separately documented evaluation plan.

## Limitations

- 20 development queries only
- pooled qrels are non-exhaustive
- tuning experiments are development evidence, not unbiased final performance
- one human-labelled dev pool
- no accepted tuning variant was promoted

## Final Decision

RETAIN UNTUNED HYBRID + RERANKER CONFIGURATION.

No Phase 0 tuning variant provided sufficient development-set evidence for promotion.
