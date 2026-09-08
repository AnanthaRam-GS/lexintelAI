# Retrieval Development Regime-Aware Experiment

This experiment uses only the dev set and does not evaluate the frozen 30-query benchmark.

## Motivation

D1 identified legal-regime resolution as a targeted tuning candidate for IPC/BNS and CrPC/BNSS transition failures.

## Resolver Rules

Explicit statute names take precedence. Mixed old/new references resolve to mixed_or_transition. The 1 July 2024 transition date is evidence but judgment year alone is not used. Bare section numbers are not mapped across statutes.

## Variants

| Variant | Adjustment | Description |
|---|---|---|
| R0 | `{}` | Baseline Hybrid+Rerank ordering. |
| R1 | `{'exact_regime_match': 0.15, 'transition_compatible': 0.08, 'unknown_metadata': 0.0, 'regime_mismatch': -0.05}` | Very conservative score prior. |
| R2 | `{'exact_regime_match': 0.3, 'transition_compatible': 0.15, 'unknown_metadata': 0.0, 'regime_mismatch': -0.1}` | Moderate score prior. |
| R3 | `{'exact_regime_match': 0.2, 'transition_compatible': 0.1, 'unknown_metadata': 0.0, 'regime_mismatch': -0.05}` | Rank tie/near-tie preference via adjusted rank. |

## Dev Metrics

| Variant | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 |
|---|---:|---:|---:|---:|---:|---:|
| R0 | 0.870 | 0.343 | 0.775 | 0.925 | 0.723 | 0.950 |
| R1 | 0.870 | 0.343 | 0.775 | 0.925 | 0.723 | 0.950 |
| R2 | 0.870 | 0.343 | 0.775 | 0.925 | 0.723 | 0.950 |
| R3 | 0.870 | 0.343 | 0.775 | 0.925 | 0.723 | 0.950 |

## Strict Sensitivity

| Variant | Strict P@5 | Strict R@5 | Strict MRR@5 | Strict nDCG@5 |
|---|---:|---:|---:|---:|
| R0 | 0.390 | 0.391 | 0.696 | 0.509 |
| R1 | 0.390 | 0.391 | 0.696 | 0.509 |
| R2 | 0.390 | 0.391 | 0.696 | 0.509 |
| R3 | 0.390 | 0.391 | 0.696 | 0.509 |

## Legal-Regime Subset

| Variant | P@5 | R@5 | R@20 | MRR@5 | nDCG@5 | Doc Hit@5 |
|---|---:|---:|---:|---:|---:|---:|
| R0 | 0.867 | 0.406 | 0.861 | 1.000 | 0.663 | 1.000 |
| R1 | 0.867 | 0.406 | 0.861 | 1.000 | 0.663 | 1.000 |
| R2 | 0.867 | 0.406 | 0.861 | 1.000 | 0.663 | 1.000 |
| R3 | 0.867 | 0.406 | 0.861 | 1.000 | 0.663 | 1.000 |

## Resolver QA Counts

- mixed_or_transition/high: 3
- mixed_or_transition/medium: 2
- unknown/low: 15

## Legal-Regime Query Findings

- dev-q001: R0 P@5=0.800, nDCG@5=0.577; R3 P@5=0.800, nDCG@5=0.577
- dev-q002: R0 P@5=1.000, nDCG@5=0.782; R3 P@5=1.000, nDCG@5=0.782
- dev-q003: R0 P@5=0.800, nDCG@5=0.457; R3 P@5=0.800, nDCG@5=0.457
- dev-q004: R0 P@5=0.600, nDCG@5=0.660; R3 P@5=0.600, nDCG@5=0.660
- dev-q005: R0 P@5=1.000, nDCG@5=0.500; R3 P@5=1.000, nDCG@5=0.500
- dev-q006: R0 P@5=1.000, nDCG@5=1.000; R3 P@5=1.000, nDCG@5=1.000

## Non-Regime Regressions

- R1: improved=0, unchanged=14, worsened=0, mean P@5 delta=0.0, mean nDCG delta=0.0, major regressions=0
- R2: improved=0, unchanged=14, worsened=0, mean P@5 delta=0.0, mean nDCG delta=0.0, major regressions=0
- R3: improved=0, unchanged=14, worsened=0, mean P@5 delta=0.0, mean nDCG delta=0.0, major regressions=0

## Selection Decision

INCONCLUSIVE — RETAIN BASELINE

No variant cleared the conservative selection criteria.

## Limitations

- development-set evidence only
- six legal-regime-focused queries
- pooled qrels are non-exhaustive
- no frozen benchmark evaluation was performed
- variant is not promoted to production/default here
