# Legal Section Baseline Evaluation

## Status

The frozen deterministic legal-section predictor was evaluated against the 36-example human gold set without tuning, catalog edits, gold edits, retrieval, NER inference, model downloads, or LLM calls.

Decision:

DETERMINISTIC BASELINE USEFUL BUT LEARNED MULTI-LABEL MODEL JUSTIFIED

## Frozen Inputs

- examples: 36
- positive primary/relevant judgments: 60
- uncertain judgments: 1
- zero-positive examples: `sec-q026`, `sec-q027`, `sec-q035`
- catalog entries: 62
- predictor SHA-256: `6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c`
- catalog SHA-256: `2d2c8fbf4a241d2adc6f67ce827f990976d3309cb59b7add15f6bc26d439dbef`

## Metric Definitions

Precision@k is the fraction of the top-k ranks that match primary or relevant gold provisions. Recall@k is the fraction of primary or relevant gold provisions recovered in the top-k ranks, averaged only over queries with positive gold. Hit@k is 1 when any positive gold appears in the top-k ranks and 0 otherwise.

MRR uses the first rank containing a primary or relevant gold provision. nDCG@5 uses graded gain `primary=2`, `relevant=1`, `uncertain=0`. The single uncertain gold provision is excluded from binary positive relevance.

## Overall Metrics

| Metric | Value |
| --- | ---: |
| Precision@1 | 0.500000 |
| Precision@3 | 0.388889 |
| Precision@5 | 0.272222 |
| Recall@1 | 0.358586 |
| Recall@3 | 0.767677 |
| Recall@5 | 0.853535 |
| MRR | 0.662037 |
| nDCG@5 | 0.722516 |
| Hit@1 | 0.500000 |
| Hit@3 | 0.805556 |
| Hit@5 | 0.861111 |

## Primary vs Relevant Recovery

| Measure | Value |
| --- | ---: |
| Primary gold | 36 |
| Primary recovered@1 | 15 |
| Primary recovered@3 | 28 |
| Primary recovered@5 | 34 |
| Primary Recall@5 | 0.944444 |
| Relevant gold | 24 |
| Relevant recovered@5 | 15 |
| Relevant Recall@5 | 0.625000 |

The deterministic predictor is strong at recovering central provisions by rank 5, but supplementary provision recovery remains weaker.

## Explicit-Section Performance

| Metric | Value |
| --- | ---: |
| Explicit Section Recall@1 | 0.500000 |
| Explicit Section Recall@3 | 0.875000 |
| Explicit Section Recall@5 | 0.875000 |

The main explicit-section guardrail works often but is not perfect at rank 5 for all multi-explicit examples.

## Subset Results

| Subset | Queries | P@5 | R@5 | MRR | nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Plain-language | 29 | 0.289655 | 0.850575 | 0.683908 | 0.692512 |
| Procedural | 14 | 0.271429 | 0.797619 | 0.696429 | 0.693125 |
| Substantive | 24 | 0.333333 | 0.881944 | 0.763889 | 0.757510 |
| IPC/CrPC | 20 | 0.330000 | 0.866667 | 0.675000 | 0.695931 |
| BNS/BNSS | 12 | 0.216667 | 0.777778 | 0.652778 | 0.681436 |
| Special-law | 6 | 0.333333 | 0.805556 | 0.916667 | 0.747253 |
| Mixed/transition | 4 | 0.200000 | 0.500000 | 0.375000 | 0.423357 |

Mixed and transition examples are the clearest weak spot.

## Per-Statute Results

| Statute | Gold Positive | Retrieved@1 | Retrieved@3 | Retrieved@5 | Recall@5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| IPC | 25 | 5 | 19 | 22 | 0.880000 |
| CrPC | 10 | 2 | 6 | 8 | 0.800000 |
| BNS | 8 | 3 | 6 | 7 | 0.875000 |
| BNSS | 6 | 3 | 4 | 4 | 0.666667 |
| NDPS Act | 5 | 3 | 4 | 5 | 1.000000 |
| POCSO Act | 4 | 1 | 2 | 2 | 0.500000 |
| SC/ST Act | 2 | 1 | 1 | 1 | 0.500000 |

Small-support statutes should be interpreted cautiously.

## Zero-Positive Guardrails

| Example | Prediction Count | False Positive |
| --- | ---: | --- |
| `sec-q026` | 0 | no |
| `sec-q027` | 0 | no |
| `sec-q035` | 0 | no |

Zero-positive false-positive rate: 0.000000. Zero-positive clean rate: 1.000000.

## Important Error Findings

The strongest behavior is central-section recovery: 34 of 36 primary provisions are recovered by rank 5. The baseline is also clean on all three no-positive examples.

The most important weakness is multi-label completeness. Supplementary recovery is 15 of 24 by rank 5, and mixed/transition recall@5 is only 0.500000. Special-law support is uneven: NDPS is fully recovered at rank 5, while POCSO and SC/ST support are both 0.500000 on small samples.

The predictor emits many extra top-k candidates because it ranks all triggered catalog entries within the current bounded top-k discipline. This is useful for recall, but it reduces Precision@5 to 0.272222.

## Error Taxonomy

| Category | Count |
| --- | ---: |
| AMBIGUOUS_QUERY | 2 |
| CATALOG_CANDIDATE_NOT_TRIGGERED | 1 |
| MISSING_GOLD_SECTION | 8 |
| OVERPREDICTION | 27 |
| PRIMARY_SECTION_RANKED_LOW | 2 |
| SUPPLEMENTARY_SECTION_MISSED | 7 |
| WRONG_SECTION | 4 |

## Score And Confidence Diagnostics

- high-confidence predictions: 92
- medium-confidence predictions: 20
- score minimum: 0.700000
- score maximum: 0.990000

No threshold, score, rank, lexicon, alias, or regime rule was changed after observing these diagnostics.
