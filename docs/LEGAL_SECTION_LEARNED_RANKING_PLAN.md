# Legal Section Learned Ranking Plan

## Motivation

The 0.7B deterministic baseline is useful as a candidate generator but leaves ranking quality to improve.

Frozen 0.7B evidence:

- Precision@1: 0.500000
- Precision@3: 0.388889
- Precision@5: 0.272222
- Recall@5: 0.853535
- MRR: 0.662037
- nDCG@5: 0.722516
- Hit@5: 0.861111
- primary recovered@5: 34 / 36, recall 0.944444
- relevant recovered@5: 15 / 24, recall 0.625000
- zero-positive false-positive rate: 0.000000
- overprediction error count: 27

The deterministic layer should remain the default and should not be replaced. The learned component should first be tested as a candidate ranker or semantic scorer.

## Why Candidate Ranking Instead Of Free Generation

Legal section prediction must remain bounded to the reconciled catalog. A learned model may score candidate sections, but it must not generate arbitrary statute-section pairs. Every final section must resolve to a catalog entry.

## Frozen Baseline

D0 is the untouched deterministic predictor from 0.7B. Its artifacts are:

- `data/structured/manifests/legal_section_baseline_eval.json`
- `data/structured/manifests/legal_section_baseline_per_example.json`
- `data/structured/manifests/legal_section_baseline_predictions.json`
- `data/structured/manifests/legal_section_baseline_error_analysis.json`

These artifacts are not modified by the learned-ranking foundation.

## Frozen Gold

The 36-query legal-section gold set is held-out evaluation data:

- examples: 36
- primary/relevant positives: 60
- uncertain: 1
- zero-positive examples: `sec-q026`, `sec-q027`, `sec-q035`

The uncertain label is diagnostic only and is not positive training or evaluation evidence.

## Frozen Catalog

The legal-section catalog remains fixed:

- entries: 62
- SHA-256: `2d2c8fbf4a241d2adc6f67ce827f990976d3309cb59b7add15f6bc26d439dbef`

No sections, aliases, descriptions, or cross-code mappings are added in this task.

## Architecture

D0 is deterministic candidate generation and ranking.

S1 is a semantic-only candidate ranker over bounded candidates. It may use query-to-section-description embedding similarity or a query-section pair reranker in a future controlled trial.

H1 is a bounded hybrid ranker combining deterministic score, semantic score, explicit-section protection, and regime compatibility.

Application default remains deterministic. Semantic and hybrid modes are experiment-only until explicitly approved by later evaluation.

## Candidate Representation

Each catalog entry has a deterministic semantic text representation:

`<statute> Section <section>: <canonical_name>. <brief_description>. Family: <offence_family>. Regime: <regime>.`

Only catalog fields are used. No LLM-generated descriptions are permitted.

## Query Representation

Candidate future query representations are:

- Q0: original query only
- Q1: original query plus explicit statute/section evidence
- Q2: original query plus deterministic offence/procedure/regime metadata

The original query remains highest-authority text. No representation is selected as a winner in this foundation task.

## Explicit-Section Protection

Explicit user-provided sections must not be suppressed by learned semantic scores. If a user writes `Section 420 IPC`, that provision remains protected in the bounded candidate set and ranking layer.

## Regime Protection

The learned layer must reuse existing legal-regime analysis. It must not blindly promote IPC/CrPC for BNS/BNSS queries or vice versa. Mixed and transition queries may keep multiple regimes.

## Negative-Query Protection

The interface must allow `[]` when deterministic evidence indicates no bounded criminal-law section. A learned semantic model must not force at least one section. Guardrail examples remain `sec-q026`, `sec-q027`, and `sec-q035`.

## Candidate Model Families

Option A: reuse `BAAI/bge-m3` for query-to-section-description embedding similarity. This avoids another deployment model and aligns with the retrieval stack, but may have domain mismatch for compact statute descriptions.

Option B: reuse `BAAI/bge-reranker-v2-m3` for query-section pair scoring. This can improve pairwise ranking quality, but has higher per-candidate latency.

Option C: test another legal or general semantic model later. Do not select a model just because it says LegalBERT; model choice requires a separate controlled trial.

## Data Leakage Policy

The 36-query gold set must not be used to fine-tune, fit weights, optimize thresholds, select representation variants, or choose model families. It remains held-out evaluation unless an explicit data-split redesign is approved.

Supervised fine-tuning requires a separate training corpus with query text, section labels, statute, regime, provenance, and train/development/test splits.

## Metrics

Future S1/H1 trials must remain comparable with D0:

- Precision@1, Precision@3, Precision@5
- Recall@1, Recall@3, Recall@5
- MRR
- nDCG@5
- Hit@1, Hit@3, Hit@5
- primary recall@5
- relevant recall@5
- explicit-section recall
- zero-positive false-positive rate

The principal target is better ranking precision and ordering, not merely higher candidate recall.

## Subsets

Future comparisons must reuse the 0.7B subsets:

- plain-language
- procedural
- substantive
- IPC/CrPC
- BNS/BNSS
- special-law
- mixed/transition

Mixed/transition remains a priority diagnostic subset because D0 had 4 queries, P@5 0.200000, R@5 0.500000, and nDCG@5 0.423357.

## Acceptance Framework

A learned or hybrid candidate should be considered useful only if evidence shows:

- Precision@1 improves
- MRR improves
- nDCG@5 improves
- primary recall@5 does not materially regress
- explicit-section recall is preserved
- zero-positive guardrail remains strong
- mixed/transition behavior does not materially worsen

No post-hoc hard thresholds are set in this task.

## Future Fine-Tuning Requirements

Supervised multi-label section prediction is deferred until a separate labeled corpus exists. The future corpus must include provenance and splits, and must not quietly repurpose the current 36-query gold set as training data.
