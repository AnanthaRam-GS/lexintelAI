# Legal Section Ranking Selection Decision

## Phase 0 Goal

Select and freeze the Phase 0 legal-section prediction/ranking configuration after the deterministic baseline, BGE-M3 embedding trial, and BGE cross-encoder trial.

Final decision:

SELECT BGE CROSS-ENCODER PROTECTED HYBRID FOR PHASE 0 SECTION RANKING

## Frozen Gold

The evaluation set contains 36 human-reviewed queries, 36 primary judgments, 24 relevant judgments, 1 uncertain judgment, and 3 zero-positive queries. Uncertain judgments are excluded from binary relevance metrics.

The gold set was used only for evaluation. No training, fine-tuning, threshold fitting, or weight fitting was performed on it.

## Deterministic Baseline

D0 used deterministic legal-section candidate generation and deterministic ranking.

Key frozen metrics: P@1 `0.500000`, MRR `0.662037`, nDCG@5 `0.722516`, primary recall@5 `0.944444`, explicit recall@5 `0.875000`, zero-positive FP rate `0.000000`.

## T1 BGE-M3 Trial

T1 evaluated `BAAI/bge-m3`. The semantic-only S1 result was strong: P@1 `0.777778`, MRR `0.814815`, nDCG@5 `0.821095`.

The RRF hybrid H1 did not preserve those ranking gains: P@1 `0.500000`, MRR `0.662037`, nDCG@5 `0.726846`.

T1 decision: `INCONCLUSIVE — TRY CROSS-ENCODER RERANKER`.

BGE-M3 should not be described as failed. It remains a viable fallback and experimental signal; it was not selected because the later cross-encoder produced stronger measured ranking metrics.

## T2 Cross-Encoder Trial

T2 evaluated `BAAI/bge-reranker-v2-m3` at revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.

Architecture: `XLMRobertaForSequenceClassification`. Tokenizer: `XLMRobertaTokenizer`. Evaluation device: CPU.

HX1 scored 112 bounded query-section candidate pairs and produced P@1 `0.805556`, MRR `0.833333`, nDCG@5 `0.831325`, primary recall@5 `0.944444`, explicit recall@5 `1.000000`, and zero-positive FP rate `0.000000`.

## Comparative Results

| System | P@1 | MRR | nDCG@5 | Primary R@5 | Explicit R@5 | Zero FP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| D0 | 0.500000 | 0.662037 | 0.722516 | 0.944444 | 0.875000 | 0.000000 |
| T1-S1 | 0.777778 | 0.814815 | 0.821095 | 0.944444 | 1.000000 | 0.000000 |
| T1-H1 | 0.500000 | 0.662037 | 0.726846 | 0.944444 | 1.000000 | 0.000000 |
| T2-HX1 | 0.805556 | 0.833333 | 0.831325 | 0.944444 | 1.000000 | 0.000000 |

## Selected Architecture

The selected conceptual pipeline is:

1. original query
2. deterministic legal query analysis
3. deterministic section candidate generation
4. bounded candidate set
5. cross-encoder query-section pair scoring
6. protected hybrid ranking
7. explicit-section protection
8. regime protection
9. zero-positive preservation
10. top-k <= 5

No arbitrary section generation or candidate expansion is permitted.

## Safety Guardrails

The selected ranker is wrapped by mandatory explicit-section protection, regime protection, zero-positive preservation, bounded catalog behavior, candidate expansion disabled, and final top-k <= 5.

## Fallback Behavior

The current default runtime remains `LEGAL_SECTION_RANKING_MODE=deterministic` unless a later integration task explicitly wires the selected learned mode.

If `BAAI/bge-reranker-v2-m3` is unavailable in learned reranking mode, fallback is deterministic D0 ranking. Runtime query handling must not fail solely because the learned reranker is absent. No arbitrary third-party model may be substituted automatically.

## Why Cross-Encoder Was Selected

The cross-encoder protected hybrid had the strongest P@1, MRR, and nDCG@5 among tested systems. It preserved primary recall@5, improved explicit recall@5 relative to D0, preserved zero-positive cleanliness, used no candidate expansion, and required no training or fine-tuning.

This is a Phase 0 selection based on this evaluation set only; it is not a universal superiority claim.

## Why No Further Model Search

Further pretrained section-ranker search is frozen as false. BGE-M3 already showed strong semantic ranking gains, and the BGE cross-encoder improved further while preserving safety guardrails. A third model is not justified in Phase 0.

## Data Leakage Policy

The 36-query human gold set remains evaluation-only. Future supervised training requires separate train/dev data and must not train on this held-out evaluation set.

## Candidate-Generation Limitation

Cross-encoder reranking cannot recover gold sections absent from deterministic candidate generation. Candidate generation remains a separate future improvement track and is not modified by this freeze.

## Future Training Path

Future training research is allowed, but fine-tuning now is frozen as false. The current gold set is too small and too evaluative for responsible supervised training.

## Limitations

- only 36 evaluation queries
- 60 positive primary/relevant judgments
- 1 uncertain judgment
- 3 zero-positive queries
- one human reviewer
- bounded 62-entry catalog
- candidate recall remains limited by D0 generation
- no statistical significance claim
- CPU latency measured on development hardware only
- no judgment-document section-classification evaluation
- no supervised training

## Final Decision

SELECT BGE CROSS-ENCODER PROTECTED HYBRID FOR PHASE 0 SECTION RANKING
