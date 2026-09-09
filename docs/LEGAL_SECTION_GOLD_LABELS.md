# Legal Section Gold Labels

## Status

The Phase 0 legal-section evaluation set has been reviewed by Ananthu and frozen as human gold labels.

## Counts

- examples: 36
- reviewed: 36
- pending: 0
- primary judgments: 36
- relevant judgments: 24
- uncertain judgments: 1
- positive primary/relevant judgments: 60
- total annotated judgments including uncertain: 61
- zero-positive examples: 3

Zero-positive examples:

- `sec-q026`
- `sec-q027`
- `sec-q035`

## Label Semantics

`primary` marks the central provision directly answering the query.

`relevant` marks a useful supplementary provision that should be considered but is not the principal answer.

`uncertain` marks a provision that may be applicable, but where the query lacks enough bounded information to promote it to primary or relevant.

No-positive examples are reviewed examples with empty `gold_sections`. They are retained to evaluate whether the system avoids inventing criminal-law sections for non-section queries.

## Review Design

The set is multi-label. A single query may contain multiple primary provisions, a primary plus supplementary relevant provisions, or no positive provisions.

Explicit section references remain authoritative human evidence. Mixed and transition examples are preserved without collapsing old-code and new-code provisions into one regime.

Catalog coverage was reconciled before materialization, so every non-empty gold provision exists in the 62-entry legal-section catalog with subsection notation preserved.

## Guardrails

No predictor scores, ranks, confidence tiers, retrieval outputs, NER outputs, LLM outputs, or model-generated labels are stored in the human gold annotations.

The reconciled catalog and deterministic predictor are intentionally unchanged by this materialization step.
