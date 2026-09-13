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

## Generation Run (Phase 0 Step 0.9C-B)

Generation interface: `backend/scripts/run_grounded_answer_eval_generation.py`
(`--dry-run` plans with zero model calls; `--live` executes real Gemini
generation and is safely resumable).

Run ID: `legalai-answer-eval-generation-v1`

Provider: `gemini`. Configured model: `gemini-3.6-flash` (read from
`GEMINI_MODEL` via `Settings`, never hardcoded in generation logic).

Started: 2026-09-12T18:02:34Z. Last resume completed: 2026-09-13T14:13:16Z
(across five invocations total: one initial run in Step 0.9C-B, then two
Step 0.9C-B-R1 resumes of only the still-failing slots).

Planned outputs: 60 (30 examples x 2 conditions). Attempted: 60.
Cumulative successful: 41. Cumulative failed: 19.

- `LLM_ONLY`: 30 attempted, 21 generated/parsed successfully, 9 failed.
- `GROUNDED_RAG`: 30 attempted, 20 generated/parsed successfully, 10 failed,
  20/20 successful outputs had fully valid citations. Grounding status among
  successful outputs: 17 STRUCTURALLY_GROUNDED, 1 PARTIALLY_GROUNDED,
  2 UNGROUNDED.

All 19 remaining failures carry the identical diagnostic: `GEMINI_RATE_LIMIT`
(HTTP 429), exhausted after the frozen 3-attempt/0.25s+0.5s retry policy.
The model, provider, and retry backoff were not changed at any point, and
generation was never forced past the authorized retry bounds.

### Step 0.9C-B-R1 resume (2026-09-13)

A minimal, harmless one-shot health check ("Return the word OK.", no legal
content) confirmed `gemini-3.6-flash` was responding (HTTP 200) before any
benchmark call resumed. Two resume invocations followed, both against the
existing run ID:

1. **Resume 1**: attempted the 39 then-incomplete slots. 20 new successes,
   19 renewed failures (still `GEMINI_RATE_LIMIT`). Cumulative: 21 -> 41
   successful. All 21 previously-successful records were verified
   byte-identical (immutable) before and after.
2. **Resume 2**: attempted the 19 still-incomplete slots. 0 new successes;
   identical `GEMINI_RATE_LIMIT` failures on all 19. Cumulative unchanged at
   41 successful. All 41 successful records (including the 20 new from
   Resume 1) were verified byte-identical before and after this second
   resume.

Further resume attempts were deliberately not made in the same task run to
avoid repeatedly hammering the provider; the harness remains safely resumable
for a later attempt.

Provider attempts (current state of all 60 records): 98. Retries: 38. Schema
repairs: 0 (no repair path exists in the frozen architecture). Fallback to
Ollama: never used (`fallback_used_count: 0`).

Token usage (provider-reported, summed across all 60 current records):
133,385 prompt tokens, 51,037 completion tokens, 250,607 total tokens.

Latency (summed across all current records): ~755.5s of Gemini generation
latency; ~783.9s of end-to-end answer-generation latency (includes retrieval,
prompt construction, and validation for `GROUNDED_RAG`).

Full machine-readable detail: `data/structured/manifests/legal_answer_eval_outputs.json`
(per-slot records) and `data/structured/manifests/legal_answer_eval_generation_summary.json`
(aggregate counts, recomputed from current record state on every run).

### Review packet status

`docs/LEGAL_ANSWER_EVAL_REVIEW.md` has been regenerated with Answer A / Answer B
content from the current outputs using the frozen, concealed pair map. Items
whose underlying condition still has not generated show "Answer unavailable
(FAILED_PROVIDER)" rather than fabricated content (19 such placeholders
remain). Given the 41/60 success rate, `backend/scripts/evaluate_grounded_legal_answers.py`
reports `GENERATION_COMPLETED_WITH_FAILURES`, not `OUTPUTS_READY_FOR_BLINDED_HUMAN_REVIEW`.
Human review of this run should not be treated as covering the full frozen set;
resuming generation (same run ID, only missing/failed slots) once provider
capacity allows would raise coverage without invalidating already-successful
outputs.

No quality comparison, preference, or correctness conclusion is drawn here.
Human scoring has not started; `legal_answer_eval_reviews.json` remains empty.

## Final Decision Framework

Later final outcomes are limited to:

- GROUNDED RAG CLEARLY PREFERRED
- GROUNDED RAG MODESTLY PREFERRED
- NO CLEAR ADVANTAGE
- LLM-ONLY PREFERRED
- EVALUATION INCONCLUSIVE
