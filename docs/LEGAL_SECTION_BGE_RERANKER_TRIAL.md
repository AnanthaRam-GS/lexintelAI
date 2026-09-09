# Legal Section BGE Cross-Encoder Reranker Trial

## Status

The zero-shot `BAAI/bge-reranker-v2-m3` legal-section cross-encoder reranking trial is complete.

Candidate decision:

BGE CROSS-ENCODER ACCEPTED FOR HYBRID SECTION RANKING

Leading signal decision:

CROSS-ENCODER IS LEADING SECTION RANKING SIGNAL

## Candidate

- model: `BAAI/bge-reranker-v2-m3`
- local revision: `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`
- architecture: `XLMRobertaForSequenceClassification`
- tokenizer: `XLMRobertaTokenizer`
- task type: cross-encoder pairwise reranker
- configured max length: 512
- model max length: 8192
- device: CPU
- parameter count: not recorded
- local-only loading: true

No model download or alternate model substitution was performed.

## Trial Design

D0 is the frozen deterministic baseline. T1-S1 and T1-H1 are loaded from the frozen BGE-M3 trial artifacts without recomputation.

X1 ranks the exact bounded D0 candidate list by raw cross-encoder score descending, with original D0 rank as deterministic tie-breaker.

HX1 uses exactly one predeclared strategy: start from X1 and apply frozen safety guardrails for explicit sections, regime behavior, zero-positive behavior, and top-k bounds. No numeric fusion, thresholding, weight search, candidate expansion, gold edits, or catalog edits were performed.

Each pair is `(original_query_text, section_semantic_text)`, where section text is the frozen 0.7C catalog-fields-only representation. Representation hash: `35d1cabaa5a165ea8ec96275ea08ffb0b85aa97d9c47bc39d37bed24d1c2f83c`.

## Overall Comparison

| Metric | D0 | T1-S1 | T1-H1 | X1 | HX1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| P@1 | 0.500000 | 0.777778 | 0.500000 | 0.805556 | 0.805556 |
| P@3 | 0.388889 | 0.416667 | 0.416667 | 0.425926 | 0.425926 |
| P@5 | 0.272222 | 0.272222 | 0.272222 | 0.272222 | 0.272222 |
| R@1 | 0.358586 | 0.560606 | 0.353535 | 0.580808 | 0.580808 |
| R@3 | 0.767677 | 0.803030 | 0.803030 | 0.813131 | 0.813131 |
| R@5 | 0.853535 | 0.853535 | 0.853535 | 0.853535 | 0.853535 |
| MRR | 0.662037 | 0.814815 | 0.662037 | 0.833333 | 0.833333 |
| nDCG@5 | 0.722516 | 0.821095 | 0.726846 | 0.831325 | 0.831325 |
| Hit@1 | 0.500000 | 0.777778 | 0.500000 | 0.805556 | 0.805556 |
| Hit@3 | 0.805556 | 0.861111 | 0.861111 | 0.861111 | 0.861111 |
| Hit@5 | 0.861111 | 0.861111 | 0.861111 | 0.861111 | 0.861111 |
| Primary recall@5 | 0.944444 | 0.944444 | 0.944444 | 0.944444 | 0.944444 |
| Relevant recall@5 | 0.625000 | 0.625000 | 0.625000 | 0.625000 | 0.625000 |
| Explicit recall@5 | 0.875000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| Zero-positive FP rate | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0.000000 |

HX1 improves over D0 by `+0.305556` P@1, `+0.171296` MRR, and `+0.108809` nDCG@5. HX1 also improves over T1-S1 by `+0.027778` P@1, `+0.018518` MRR, and `+0.010230` nDCG@5.

## Rank Movement

| Movement | X1 vs D0 | HX1 vs D0 | HX1 vs T1-S1 |
| --- | ---: | ---: | ---: |
| Primary moved up | 14 | 14 | 4 |
| Primary unchanged | 16 | 16 | 27 |
| Primary moved down | 4 | 4 | 3 |
| Primary missing | 2 | 2 | 2 |
| Relevant moved up | 8 | 8 | 4 |
| Relevant unchanged | 4 | 4 | 7 |
| Relevant moved down | 3 | 3 | 4 |
| Relevant missing | 9 | 9 | 9 |

Negative average rank movement indicates upward movement: HX1 primary average rank change vs D0 is `-0.470588`; HX1 relevant average rank change vs D0 is `-0.466667`.

## Subset Results

| Subset | D0 P@1 | T1-S1 P@1 | HX1 P@1 | D0 nDCG@5 | T1-S1 nDCG@5 | HX1 nDCG@5 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Plain-language | 0.482759 | 0.827586 | 0.862069 | 0.692512 | 0.804687 | 0.818044 |
| Procedural | 0.571429 | 0.785714 | 0.785714 | 0.693125 | 0.750914 | 0.778361 |
| Substantive | 0.583333 | 0.916667 | 0.916667 | 0.757510 | 0.856347 | 0.854576 |
| IPC/CrPC | 0.450000 | 0.850000 | 0.850000 | 0.695931 | 0.829879 | 0.834613 |
| BNS/BNSS | 0.500000 | 0.750000 | 0.833333 | 0.681436 | 0.764581 | 0.782614 |
| Special-law | 0.833333 | 0.833333 | 1.000000 | 0.747253 | 0.733169 | 0.800936 |
| Mixed/transition | 0.250000 | 0.500000 | 0.500000 | 0.423357 | 0.500000 | 0.500000 |

Mixed/transition improves over D0 and matches T1-S1. Special-law support is small, but HX1 ranks all six special-law examples correctly at rank 1.

## Important Findings

Explicit sections remain present within the bounded final output for `sec-q001`, `sec-q002`, `sec-q023`, and `sec-q024`. `sec-q023` preserves both IPC `406` and IPC `420`; `sec-q024` preserves both BNS `103` and IPC `302`.

Zero-positive examples `sec-q026`, `sec-q027`, and `sec-q035` remain empty for D0, T1-S1, X1, and HX1.

`sec-q025` remains empty because D0 emitted no candidates. `sec-q028` remains candidate-generation-limited because the bounded candidate set omits the FIR-registration gold sections. Cross-encoder reranking cannot recover absent candidates in this trial.

## Score Diagnostics

| Group | Count | Mean | Median | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| All candidate pairs | 112 | -3.194366 | -3.239246 | -8.974416 | 3.222795 |
| Gold-positive pairs | 49 | -1.525413 | -1.276014 | -6.811406 | 3.222795 |
| Non-gold pairs | 63 | -4.492442 | -4.335362 | -8.974416 | 1.859184 |

Within-query positive-vs-negative discrimination: 83 of 96 pairs, fraction `0.864583`. This is diagnostic only; no threshold was selected.

## Latency

- model load: 3791.923 ms
- candidate pairs scored: 112
- pair scoring mean: 279.032 ms
- pair scoring median: 256.087 ms
- pair scoring p95: 382.890 ms
- pair scoring max: 1821.312 ms
- HX1 total mean: 279.035 ms
- T1 S1 total mean: 81.951 ms

The CPU cross-encoder is slower than T1 embedding similarity, as expected, but remains operational for the bounded section-candidate set.

## Error Analysis

HX1 error taxonomy remains constrained by the D0 candidate universe:

- OVERPREDICTION: 27
- MISSING_GOLD_SECTION: 8
- SUPPLEMENTARY_SECTION_MISSED: 7
- WRONG_SECTION: 4
- PRIMARY_SECTION_RANKED_LOW: 2
- AMBIGUOUS_QUERY: 2
- CATALOG_CANDIDATE_NOT_TRIGGERED: 1

Ranking-fixable diagnostics: 2 primary-ranked-low cases and 2 extra-above-gold cases remain. Candidate-generation-limited diagnostics: 8 missing-gold-section and 1 catalog-candidate-not-triggered cases remain.

## Recommendation

Accept `BAAI/bge-reranker-v2-m3` as the leading zero-shot learned section-ranking signal for the bounded candidate reranking architecture. Do not fine-tune yet; 36 held-out examples are too small for supervised training. The next work should decide whether to promote this zero-shot ranker or separately improve deterministic candidate generation for cases where the gold section is absent from D0.
