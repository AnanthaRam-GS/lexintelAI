# Legal Section Prediction Foundation

## Purpose

This foundation adds a safe, deterministic baseline for suggesting likely Indian criminal-law sections from a user query. Predictions are supplementary signals for query understanding, retrieval enrichment, and future structured case analysis.

## Supplementary Signal Principle

Predicted sections never override explicit user-provided statute or section references. Explicit sections remain separate in `explicit_sections`; `predicted_sections` only adds ranked candidates with provenance, confidence, evidence, and warnings.

Priority remains: original query, explicit statute or section text, deterministic query-analysis signals, canonical entities or offence-family hints, then predicted candidate sections.

## Schema

`PredictedLegalSection` contains `statute`, `section`, `normalized_section`, `score`, `rank`, `source`, `confidence`, `evidence`, `prediction_version`, optional `offence_family`, optional `legal_regime`, `relationship_to_explicit`, and `warnings`.

`source` is explicit and currently uses `deterministic_baseline`. Classifier and hybrid sources are reserved for later work.

## Catalog

The bounded catalog lives at `data/structured/manifests/legal_section_catalog.json`. It covers high-value Phase 0 sections across `IPC`, `CrPC`, `BNS`, `BNSS`, `NDPS Act`, `POCSO Act`, and `SC/ST Act`.

Coverage includes homicide, hurt and assault, theft, robbery, cheating, criminal breach of trust, kidnapping, sexual offences, dowry, conspiracy, narcotics, bail, default bail, quashing, and arrest safeguards.

The initial foundation catalog contained 44 entries. The post-human-review coverage reconciliation expands the catalog to 62 entries without changing predictor scoring, ranking, or gold-label materialization.

The catalog does not attempt a comprehensive Indian statute universe and does not auto-create speculative old/new code equivalence mappings.

## Regime Handling

The predictor reuses the existing legal-regime resolver. Queries resolved as `ipc_crpc` prefer IPC/CrPC plus special statutes. Queries resolved as `bns_bnss` prefer BNS/BNSS plus special statutes. `mixed_or_transition` allows old and new regimes side by side.

## Explicit-Section Priority

When explicit sections are present, predictions are marked as `supports_explicit`, `supplementary`, or `conflicts_with_explicit`. Conflicts are retained as warnings rather than silently replacing explicit user evidence.

## Deterministic Baseline

The baseline uses offence-family hints, procedural posture, deterministic legal lexicon matches, regime evidence, explicit statute evidence, and catalog aliases. It returns at most 5 ranked candidates.

No model inference, LLM calls, retrieval execution, or NER inference are part of this foundation.

## Multi-Label Design

Legal section prediction is multi-label. A query may raise multiple relevant sections, such as cheating plus criminal breach of trust, robbery plus hurt, or procedural relief plus a substantive offence.

## Top-K Policy

The default and maximum top-k is 5. This keeps predictions human-reviewable and avoids flooding downstream retrieval with weak candidates.

## Evaluation Set

`data/structured/manifests/legal_section_eval.json` contains 36 pending examples independent from the frozen retrieval benchmark. The set covers explicit section queries, plain-language offence queries, procedural queries, old-code, new-code, transition, mixed, multi-label, ambiguous, and negative/no-section cases.

## Human Review Workflow

`docs/LEGAL_SECTION_REVIEW.md` provides a blank review packet. Reviewers should label candidate gold sections with `primary`, `relevant`, `not_relevant`, or `uncertain`. Predictor output is not shown as gold.

## Metrics

Reusable metrics are prepared for future reviewed gold: Precision@1, Precision@3, Precision@5, Recall@5, MRR, and nDCG@5. Formal baseline effectiveness is not reported while gold labels are pending.

## Limitations

The catalog is bounded and conservative. The baseline is deterministic and lexical, so it can miss implicit legal theories or over-rank sections triggered by broad language. BNS/BNSS support is intentionally limited to high-value project concepts and should be expanded only through reviewed future work.

## Future Classifier Path

A future classifier may be considered after human section gold labels are materialized and a train/dev/test split exists. Any learned section predictor must preserve explicit-section priority and keep raw scores separate from confidence tiers.

## Status

READY FOR HUMAN SECTION GOLD ANNOTATION
