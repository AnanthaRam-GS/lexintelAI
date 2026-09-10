# Legal Grounded Answer Evaluation Plan

## Research Question

Does grounded RAG provide better legally useful and better-supported Indian
criminal-law answers than the same LLM without retrieval?

This evaluation does not ask whether Gemini is universally accurate.

## Evaluation Conditions

`LLM_ONLY` receives the original query and the same mode-specific answer contract only.
It receives no `LegalRetrievalResult`, no retrieved case text, no corpus metadata, and
no E-style evidence IDs.

`GROUNDED_RAG` receives `LegalQueryUnderstanding`, frozen top-5 LegalAI retrieval
evidence, and the existing grounded prompt and citation contract.

Both conditions must use the same provider, model, temperature, answer schema, and
query text. The model is read from `GEMINI_MODEL` through `Settings`.

## Frozen Components

The query set, rubric, score scales, composite formula, display pairing, and component
hashes are frozen before generation. Future answer generation must not change retrieval,
query understanding, prompts, citation validation, NER, section ranking, or schemas.

## Query Set

The frozen manifest contains 30 independently authored evaluation queries:

- 15 public-mode queries
- 15 professional-mode queries
- 10 basic, 10 moderate, and 10 hard queries

The four Gemini smoke cases are not reused as scored benchmark items.

## Coverage

The set covers substantive offences, procedure, explicit-section queries, public
plain-language queries, professional analytical queries, BNS/BNSS, IPC/CrPC,
mixed-transition issues, special statutes, insufficient-fact cases, and negative or
low-criminal-content cases.

Coverage includes murder, hurt, theft/robbery, cheating, criminal breach of trust,
kidnapping, sexual offences, dowry/cruelty, conspiracy, NDPS, bail, anticipatory bail,
default bail, quashing, FIR registration/refusal, and transition law.

## Blinding

Human review should show outputs as Answer A and Answer B where practical. The reviewer
packet does not reveal which display side is `LLM_ONLY` or `GROUNDED_RAG`. The concealed
condition mapping is stored separately in `legal_answer_eval_pair_map.json`.

## Randomization

Pairing version: `legalai-answer-pairing-v1`.

Seed: `90210`.

The current pairing uses a deterministic balanced assignment over the frozen example
order. Once outputs are generated and inserted for review, display order must not be
changed.

## Human Rubric

Positive dimensions use:

- 0 = unacceptable or absent
- 1 = weak
- 2 = adequate
- 3 = strong
- 4 = excellent

Dimensions:

- Legal Relevance
- Legal Correctness
- Grounding / Support
- Citation Quality
- Completeness
- Uncertainty Handling
- Regime Handling
- Actionability

Hallucination severity is reported separately:

- 0 = none
- 1 = minor unsupported wording
- 2 = moderate unsupported claim
- 3 = major fabricated or unsafe authority/fact

Overall preference is A, B, or Tie.

## Automated Grounding Diagnostics

For grounded outputs, the existing structural validator may report citation validity
rate, claims-with-citation rate, structural grounding status, and evidence utilization.
These diagnostics supplement human review and do not prove semantic legal correctness.

## Scoring

Primary outcomes:

- mean legal correctness
- mean grounding/support
- mean citation quality
- mean overall quality composite
- pairwise preference win rate

Secondary outcomes:

- relevance
- completeness
- uncertainty handling
- regime handling
- actionability
- hallucination severity

## Composite

`quality_composite` is the simple unweighted mean of the eight positive dimensions.
Hallucination severity is not folded into the composite because it uses the opposite
direction.

## Hallucination Tracking

Reviewers score what the answer says, not what the system intended. They should not
infer missing citations, correct the answer during scoring, or reward verbosity.

## Public vs Professional

Public answers should be judged for clarity, plain language, practical next steps, and
appropriate uncertainty.

Professional answers should be judged for issue spotting, authority use, counterpoints,
procedural framing, and research utility.

## Limitations

The evaluation is descriptive. With 30 paired queries, results should not be presented
as decisive statistical proof. Optional paired nonparametric analysis may be reported
cautiously later, but the primary analysis is descriptive.

## Review Workflow

1. Generate both frozen conditions for all 30 queries in a later task.
2. Insert outputs into the review packet as Answer A and Answer B using the frozen pair
   map.
3. Human reviewer scores each displayed answer and chooses A, B, or Tie.
4. Store completed reviews in `legal_answer_eval_reviews.json`.
5. Run `backend/scripts/evaluate_grounded_legal_answers.py` to aggregate results.

## Future Generation Step

The dry-run-only generation interface is `backend/scripts/run_grounded_answer_eval_generation.py`.
Live generation belongs to the next phase and must not alter the query set or rubric.

## Final Decision Framework

Later final outcomes are limited to:

- GROUNDED RAG CLEARLY PREFERRED
- GROUNDED RAG MODESTLY PREFERRED
- NO CLEAR ADVANTAGE
- LLM-ONLY PREFERRED
- EVALUATION INCONCLUSIVE
