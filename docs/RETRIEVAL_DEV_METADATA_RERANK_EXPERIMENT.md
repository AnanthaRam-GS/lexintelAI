# Retrieval Development Metadata Rerank Experiment

Development-set results are tuning evidence only.

## Metadata Intent Parser

- intents: court level/name, date period, case posture, offence family, legal regime
- trusted fields: court, decision_date, case_title, bounded chunk preview, effective_offence_family, effective_legal_regime
- unknown metadata is neutral
- adjustment is bounded to +/-0.20 and applied only to near-tie candidates

## Variants

| Variant | Description |
|---|---|
| M0 | Baseline Hybrid+Rerank ordering. |
| M1 | Court/date/posture near-tie tiebreak only. |
| M2 | Court/date/posture/family conservative bounded prior. |
| M3 | M2 plus high-confidence regime compatibility. |

## Overall Dev Results

| Variant | P@5 | R@5 | MRR@5 | nDCG@5 | Strict P@5 |
|---|---:|---:|---:|---:|---:|
| M0 | 0.870 | 0.343 | 0.925 | 0.723 | 0.390 |
| M1 | 0.870 | 0.343 | 0.925 | 0.723 | 0.390 |
| M2 | 0.870 | 0.343 | 0.925 | 0.723 | 0.390 |
| M3 | 0.870 | 0.343 | 0.925 | 0.723 | 0.390 |

## Metadata-Sensitive Results

| Variant | P@5 | R@5 | MRR@5 | nDCG@5 | Strict P@5 |
|---|---:|---:|---:|---:|---:|
| M0 | 0.600 | 0.193 | 0.500 | 0.383 | 0.200 |
| M1 | 0.600 | 0.193 | 0.500 | 0.383 | 0.200 |
| M2 | 0.600 | 0.193 | 0.500 | 0.383 | 0.200 |
| M3 | 0.600 | 0.193 | 0.500 | 0.383 | 0.200 |

## Metadata-Reranking Focus Results

| Variant | P@5 | R@5 | MRR@5 | nDCG@5 | Strict P@5 |
|---|---:|---:|---:|---:|---:|
| M0 | 0.800 | 0.279 | 0.812 | 0.583 | 0.225 |
| M1 | 0.800 | 0.279 | 0.812 | 0.583 | 0.225 |
| M2 | 0.800 | 0.279 | 0.812 | 0.583 | 0.225 |
| M3 | 0.800 | 0.279 | 0.812 | 0.583 | 0.225 |

## Ordering Changes

- M0: order changed=0, membership changed=0, P@5 improved/worsened/unchanged=0/0/20, nDCG improved/worsened/unchanged=0/0/20
- M1: order changed=0, membership changed=0, P@5 improved/worsened/unchanged=0/0/20, nDCG improved/worsened/unchanged=0/0/20
- M2: order changed=0, membership changed=0, P@5 improved/worsened/unchanged=0/0/20, nDCG improved/worsened/unchanged=0/0/20
- M3: order changed=0, membership changed=0, P@5 improved/worsened/unchanged=0/0/20, nDCG improved/worsened/unchanged=0/0/20

## Non-Target Regression

- M0: improved=0, unchanged=0, worsened=0, mean P@5 delta=0.0, mean nDCG delta=0.0, major regressions=0
- M1: improved=0, unchanged=12, worsened=0, mean P@5 delta=0.0, mean nDCG delta=0.0, major regressions=0
- M2: improved=0, unchanged=12, worsened=0, mean P@5 delta=0.0, mean nDCG delta=0.0, major regressions=0
- M3: improved=0, unchanged=12, worsened=0, mean P@5 delta=0.0, mean nDCG delta=0.0, major regressions=0

## Important Query Findings

- dev-q001: court=None, date=before 2024-07-01, posture=bail_petition, family=None, regime=mixed_or_transition
- dev-q003: court=None, date=None None, posture=bail_petition, family=None, regime=None
- dev-q005: court=None, date=after 2024-07-01, posture=arrest_procedure, family=None, regime=mixed_or_transition
- dev-q016: court=supreme_court, date=None None, posture=criminal_appeal, family=homicide, regime=None
- dev-q017: court=high_court, date=None None, posture=quashing_petition, family=cheating_and_fraud, regime=None
- dev-q018: court=district_court, date=None None, posture=criminal_appeal, family=sexual_offences, regime=None

## Bootstrap

- broad_precision_at_5: mean delta=0.0, p05=0.0, p95=0.0
- graded_ndcg_at_5: mean delta=0.0, p05=0.0, p95=0.0
- broad_mrr_at_5: mean delta=0.0, p05=0.0, p95=0.0

## Selection Decision

INCONCLUSIVE — RETAIN BASELINE

No metadata variant cleared the conservative dev-set selection criteria.

## Feature Usage

- court_level_match:match: 69
- court_level_match:mismatch: 66
- court_level_match:neutral: 765
- court_match:match: 69
- court_match:mismatch: 66
- court_match:neutral: 765
- date_compatible:match: 45
- date_compatible:mismatch: 45
- date_compatible:neutral: 810
- family_match:match: 240
- family_match:mismatch: 390
- family_match:neutral: 270
- posture_match:match: 153
- posture_match:mismatch: 207
- posture_match:neutral: 540
- regime_match:match: 168
- regime_match:mismatch: 57
- regime_match:neutral: 675

## Limitations

- 20-query dev set only
- post-rerank trace experiment over frozen dev pool
- metadata can be sparse or title-derived
- no production/default behavior is changed
