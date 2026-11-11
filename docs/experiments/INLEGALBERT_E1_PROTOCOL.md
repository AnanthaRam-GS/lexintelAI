# InLegalBERT E1 (NER): label mapping, combination policy and recipe, frozen before training

Frozen on 2026-11-11, before any E1 training code was written or run. Nothing here was chosen by looking at the 36
gold examples: the mapping follows our annotation guidelines (`docs/LEGAL_NER_ANNOTATION_GUIDELINES.md`) and
InLegalNER's published schema (Kalamkar et al., NLLP 2022). The pass thresholds are those of
`docs/experiments/INLEGALBERT_PLAN.md` (section 6), unchanged.

## 1. Data

- **InLegalNER** at revision `2e32a46e6714424979db8677b39dbc0aa7e308e7` (MIT): train = 9,435 judgment sentences +
  1,560 preambles; validation = the official dev split, 949 judgment sentences + 125 preambles. The split is the
  authors' own, so it is fixed; the training order is shuffled with each run's seed.
- **Leakage exclusion** (`experiments/inlegalbert/leakage_check.py`): 108 train and 23 dev items removed (they share a
  13-word passage with our corpus). Remaining: 10,887 train, 1,051 dev.
- The official InLegalNER test split is not used.
- **Our 36 gold examples are the test set only.** They are not used for training, validation, early stopping,
  threshold tuning or any choice in this document, and each seed's selected checkpoint is scored on them once.

## 2. Label mapping (InLegalNER -> `legalai-ner-schema-v1`)

The model is trained on InLegalNER's 14 native types (BIO, 29 labels); predictions are mapped afterwards:

| InLegalNER | Canonical | Rationale |
|---|---|---|
| COURT | COURT | same concept ("named courts and court levels") |
| DATE | DATE | same concept |
| STATUTE | STATUTE | same concept; rule-owned in the combined system (below) |
| PROVISION | SECTION | sections, sub-sections and articles; rule-owned in the combined system |
| ORG | ORGANIZATION | companies, agencies, government bodies; their ORG also covers police stations, which our guidelines label POLICE_STATION (rule-owned, protected) |
| GPE | LOCATION | countries, states, cities, districts, villages = our "cities, states, districts and places" |
| PRECEDENT | CASE_NAME | party names (+ optional citation) of a cited case; our guidelines give CASE_NAME precedence for case titles |
| PETITIONER, RESPONDENT | ORGANIZATION if the span names a government or organisational party (see rule), else PERSON | our guidelines label government bodies and institutions as ORGANIZATION; InLegalNER's party roles include parties such as "State of …" |
| JUDGE, LAWYER, WITNESS, OTHER_PERSON | PERSON | named people; our LEGAL_ROLE is the role word, not the name |
| CASE_NUMBER | not mapped (dropped) | court case numbers have no type in our schema (CASE_CITATION is a formal citation; FIR_NUMBER is rule-owned) |

**Party rule.** A PETITIONER or RESPONDENT span maps to ORGANIZATION when it starts with "State", "Union of India",
"Government", "Commissioner", "Director", "Municipal" or "Central Bureau", or contains one of "Ltd", "Limited",
"Pvt", "Bank", "Corporation", "Company", "Department", "Board", "Authority", "Council", "Commission", "Society",
"Trust", "University", "Police" (case-insensitive, whole words); otherwise PERSON.

**Types the model cannot express** (no InLegalNER label): OFFENCE, LEGAL_PROCEDURE, LEGAL_ROLE, FIR_NUMBER, and
POLICE_STATION and CASE_CITATION as separate types. They are left to the existing deterministic rules.

## 3. Combination policy (the combined system)

The combined system is the product's existing hybrid merge, used unchanged:
`backend/app/services/hybrid_legal_ner.merge_hybrid_entities(deterministic, model, HybridMergeConfig(mode="hybrid",
min_confidence=0.70))`.
- Rule-owned (protected) types: STATUTE, SECTION, LEGAL_ROLE, POLICE_STATION, FIR_NUMBER, LEGAL_PROCEDURE. A model span
  that overlaps one is dropped, and model spans of these types are never inserted.
- Model-preferred types: PERSON, ORGANIZATION, LOCATION, CASE_NAME; shared types: COURT, DATE, OFFENCE,
  CASE_CITATION (a model span may replace a same-type rule span it overlaps; otherwise overlaps go to the
  higher-priority type per `TYPE_PRIORITY`).
- Threshold 0.70, as fixed in the plan. A model entity's **confidence** is the mean softmax probability of the
  predicted labels over the entity's tokens.
- The deterministic baseline (D0) is `legal_ner.extract_deterministic_entities`, as in Phase 0.

Systems scored: **(a) model alone** (all mapped model entities at confidence >= 0.70), **(b) deterministic baseline**,
**(c) combined**. The verdict is on (c).

## 4. Recipe

- Checkpoint `law-ai/InLegalBERT` at `b5ecfed8ed6cf9d25a3cb8225a8c52f161f7401a`, `AutoModelForTokenClassification`
  with 29 labels (O + B/I for the 14 native types).
- Tokens: the checkpoint's fast tokenizer with offset mapping; windows of **256** tokens with a stride (overlap) of
  **64** for long texts. Every sub-word token carries a label (B on an entity's first token, I on the rest); special
  tokens are ignored in the loss.
- Prediction: per token, the most probable label from the window in which the token is most central; an entity is a
  B-T token followed by I-T tokens (an I-T without a preceding T starts an entity); its span runs from the first
  token's start to the last token's end.
- AdamW, learning rate **3e-5**, weight decay 0.01, linear warm-up over 10% of steps then linear decay, gradient
  clipping 1.0, batch **16**, fp32 on MPS.
- Up to **5 epochs**; validation after each epoch by **entity-level exact F1** (character span + native type) on the
  dev split; **early stopping** with patience 2; the best-validation epoch is kept.
- **Seeds 11, 22, 33** (set in the step E1 brief; they replace the plan's example seeds and change no threshold).
- Checkpoints under the gitignored `models/inlegalbert_ner/seed-<n>/`; curves and timings committed under
  `experiments/inlegalbert/runs/`.
- Budget: stop and report if training exceeds 6 hours in total. The LegalAI backend is stopped during training.

## 5. Scoring (once per model)

- The existing scorer: `legal_ner.exact_entity_metrics` (exact span and type), per type over the 14 canonical types,
  and the gold contract check (36 examples, 89 entities).
- 95% confidence intervals: bootstrap over the 36 examples, 10,000 resamples, seed 20261111. The paired bootstrap of
  F1(combined) - F1(D0) uses the same resamples for both systems.
- **Median seed:** the three seeds are ranked by the combined system's exact F1 on the gold set; the verdict uses the
  median one. Per-seed results and the mean are also reported.
- Brief-relevant types (no loss allowed): STATUTE, SECTION, COURT, DATE, LEGAL_ROLE, LEGAL_PROCEDURE, POLICE_STATION,
  FIR_NUMBER.
- No-entity examples: the reviewed gold examples with no entities; any combined-system entity on them is a failure.
