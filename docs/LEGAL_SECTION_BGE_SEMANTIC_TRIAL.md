# Legal Section BGE-M3 Semantic Trial

## Status

The zero-shot `BAAI/bge-m3` legal-section semantic ranking trial is complete.

Candidate decision:

INCONCLUSIVE — TRY CROSS-ENCODER RERANKER

## Candidate

- model: `BAAI/bge-m3`
- local revision: `5617a9f61b028005a4858fdac845db406aefb181`
- architecture: `XLMRobertaModel`
- embedding dimension: 1024
- device: CPU
- normalization: provider L2-normalized dense vectors
- similarity: cosine similarity via dot product on normalized vectors
- parameter count: not recorded

No model download or alternate model substitution was performed.

## Trial Design

D0 is the frozen deterministic baseline from 0.7B.

S1 ranks the same bounded deterministic candidates using BGE-M3 semantic similarity only.

H1 uses one predeclared fusion strategy: Reciprocal Rank Fusion over deterministic rank and semantic rank with `K=60`, plus existing explicit-section protection.

Candidate generation is unchanged: each query uses only the frozen deterministic predictor output. Query representation is Q0 original query only. Section representation is the 0.7C catalog-fields-only semantic text.

## Overall Comparison

| Metric | D0 | S1 | H1 | H1 Delta vs D0 |
| --- | ---: | ---: | ---: | ---: |
| P@1 | 0.500000 | 0.777778 | 0.500000 | 0.000000 |
| P@3 | 0.388889 | 0.416667 | 0.416667 | 0.027778 |
| P@5 | 0.272222 | 0.272222 | 0.272222 | 0.000000 |
| R@1 | 0.358586 | 0.560606 | 0.353535 | -0.005051 |
| R@3 | 0.767677 | 0.803030 | 0.803030 | 0.035353 |
| R@5 | 0.853535 | 0.853535 | 0.853535 | 0.000000 |
| MRR | 0.662037 | 0.814815 | 0.662037 | 0.000000 |
| nDCG@5 | 0.722516 | 0.821095 | 0.726846 | 0.004330 |
| Hit@1 | 0.500000 | 0.777778 | 0.500000 | 0.000000 |
| Hit@3 | 0.805556 | 0.861111 | 0.861111 | 0.055555 |
| Hit@5 | 0.861111 | 0.861111 | 0.861111 | 0.000000 |
| Primary recall@5 | 0.944444 | 0.944444 | 0.944444 | 0.000000 |
| Relevant recall@5 | 0.625000 | 0.625000 | 0.625000 | 0.000000 |
| Explicit recall@5 | 0.875000 | 1.000000 | 1.000000 | 0.125000 |
| Zero-positive FP rate | 0.000000 | 0.000000 | 0.000000 | 0.000000 |

S1 demonstrates meaningful semantic ordering signal, but H1 with the predeclared RRF fusion does not improve P@1 or MRR.

## Primary Rank Movement

| Ranker | Moved up | Unchanged | Moved down | Missing | Average rank change |
| --- | ---: | ---: | ---: | ---: | ---: |
| S1 | 14 | 14 | 6 | 2 | -0.411765 |
| H1 | 7 | 24 | 3 | 2 | -0.147059 |

Negative average rank change means movement upward.

## Subset Results

| Subset | Ranker | P@1 | P@5 | R@5 | MRR | nDCG@5 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Plain-language | D0 | 0.482759 | 0.289655 | 0.850575 | 0.683908 | 0.692512 |
| Plain-language | S1 | 0.827586 | 0.289655 | 0.850575 | 0.873563 | 0.804687 |
| Plain-language | H1 | 0.482759 | 0.289655 | 0.850575 | 0.683908 | 0.697439 |
| Procedural | D0 | 0.571429 | 0.271429 | 0.797619 | 0.696429 | 0.693125 |
| Procedural | S1 | 0.785714 | 0.271429 | 0.797619 | 0.809524 | 0.750914 |
| Procedural | H1 | 0.500000 | 0.271429 | 0.797619 | 0.654762 | 0.670112 |
| Substantive | D0 | 0.583333 | 0.333333 | 0.881944 | 0.763889 | 0.757510 |
| Substantive | S1 | 0.916667 | 0.333333 | 0.881944 | 0.958333 | 0.856347 |
| Substantive | H1 | 0.625000 | 0.333333 | 0.881944 | 0.791667 | 0.771383 |
| Mixed/transition | D0 | 0.250000 | 0.200000 | 0.500000 | 0.375000 | 0.423357 |
| Mixed/transition | S1 | 0.500000 | 0.200000 | 0.500000 | 0.500000 | 0.500000 |
| Mixed/transition | H1 | 0.250000 | 0.200000 | 0.500000 | 0.375000 | 0.423357 |

S1 improves ordering in multiple subsets, including mixed/transition, but H1 mostly preserves D0 ordering.

## Important Example Findings

`sec-q024` is unchanged across D0, S1, and H1 with both transition murder provisions retained.

`sec-q025` remains empty across D0, S1, and H1 because deterministic candidate generation emitted no candidates. Semantic reranking cannot recover absent candidates in this trial.

`sec-q028` remains a failure for FIR-registration gold because D0 produced hurt candidates rather than CrPC `154(3)` or BNSS `173(4)`.

`sec-q033` shows semantic value: S1 promotes CrPC `438` and BNSS `482` ahead of POCSO candidates, while H1 keeps POCSO `4` first due to RRF inertia.

## Overprediction Findings

H1 keeps the same bounded candidate set as D0, so overprediction count remains 27. Semantic reranking can move extras below relevant candidates, but the predeclared H1 fusion was too conservative to materially change top-rank behavior.

## Score Diagnostics

| Group | Count | Mean | Median | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| All candidates | 112 | 0.509008 | 0.510940 | 0.298621 | 0.722544 |
| Gold-positive candidates | 49 | 0.556923 | 0.559520 | 0.366741 | 0.722544 |
| Non-gold candidates | 63 | 0.471741 | 0.466204 | 0.298621 | 0.665303 |

Gold-positive candidates have a higher mean semantic similarity than non-gold candidates, supporting further semantic-reranking investigation. No threshold was selected.

## Latency

- model load: 2982.862 ms
- section embedding preparation: 1764.271 ms
- query embedding mean: 81.947 ms
- query embedding median: 80.907 ms
- query embedding p95: 89.171 ms
- query embedding max: 89.886 ms
- S1 total mean: 81.951 ms
- H1 total mean: 81.953 ms

This is CPU-only timing and not a heavyweight benchmark.

## Error Analysis

H1 error taxonomy is unchanged from the D0-style candidate-generation limitation:

- OVERPREDICTION: 27
- MISSING_GOLD_SECTION: 8
- SUPPLEMENTARY_SECTION_MISSED: 7
- WRONG_SECTION: 4
- PRIMARY_SECTION_RANKED_LOW: 2
- AMBIGUOUS_QUERY: 2
- CATALOG_CANDIDATE_NOT_TRIGGERED: 1

Because candidate generation is unchanged, semantic reranking cannot recover gold sections absent from deterministic candidates.

## Recommendation

Do not accept BGE-M3 RRF H1 as the hybrid ranker yet. Run one controlled T2 trial with `BAAI/bge-reranker-v2-m3`, because S1 shows real semantic ordering signal but the current H1 fusion does not turn that signal into main-metric gains.
