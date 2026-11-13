# Evaluation 2026-10: three-configuration re-run (prompt v3, Groq)

Steps 24-24c, plan Task 4.A.1 (RAG-003, R32). The run data is in `data/evaluation/runs/2026-10_v3_groq/`; the
full, UNREVIEWED outputs are outside the repository.

**Status: complete for automatic metrics; the review sample is reviewed by an AI chat assistant (not Claude Code),
blind to configuration and not human-verified (section 4).**
- **Retrieval:** complete.
- **Generation:** all 90 cells (30 queries x 3 configurations) have a record.
  - Public half: run on 2026-10-30 (step 24).
  - Professional half: re-run on 2026-10-31 (step 24b) on gpt-oss-120b only, under the no-fallback policy; the
    last cell, B ans-q029, on 2026-11-01 (step 24c).
  - 84 records are schema-valid answers. The other 6 remain as recorded, not retried:
    - schema failures: A ans-q019, B ans-q016;
    - Groq "json_validate_failed" 400s: A ans-q017, A ans-q020, C ans-q014;
    - BUSY: C ans-q010 (public).
- **Review:** the 15 x 3 sample was reviewed in two rounds by an AI chat assistant (not Claude Code), blind to
  configuration and not human-verified: round 1 on 600-character excerpts, round 2 on the full cited passages for
  the rows round 1 did not judge supported. Both were imported on 2026-11-13 (section 4).

**Headline (grounding, round 2):** All structured citations point to real retrieved evidence (structural 100%); on AI
review with the full cited passages, about 77% are at least partly supported and about 67% fully (B 0.650 and C 0.690
strict; B 0.775 and C 0.762 lenient; round 2, AI reviewer, not human-verified). Round 1, on excerpts cut at 600
characters, gave about 65% and about 21%; the cut caused most of that gap (section 4).

## 1. What exists and how it works

**Retrieval benchmark** (`legalai-retrieval-eval-v1`, frozen; `data/structured/manifests/retrieval_eval_*`):
- **Queries:** 30, corpus-supported, across 5 types: statute_explicit 10, plain_language 8, procedural_relief 6,
  transition_regime 3, hard_ambiguous 3. By regime, 25 are IPC/CrPC, 2 BNS/BNSS and 3 mixed.
- **Pooling** (`legalai-retrieval-pool-v1`): BM25, dense BGE-M3, hybrid RRF and hybrid + BGE reranker each retrieve
  20. Ranks 1-15 enter the pool, every system's top 5 is always kept, and each query's pool holds at most 25
  candidates, ordered by best rank. That gives 695 pooled chunks. The pool traces store each chunk's rank per
  system, ranks up to 15 only.
- **Human labels:** 695, from one reviewer, blinded to ranks and scores.
  - Chunk relevance: 2 = highly relevant (251), 1 = partially relevant (222), 0 = not relevant (219),
    uncertain (3, excluded).
  - Document relevance, recorded separately: yes, no or uncertain.
- **Metrics** (`analyze_retrieval_eval.py`):
  - Broad relevance is grade 1 or 2; strict relevance is grade 2.
  - P@5, MRR@5, graded nDCG@5 (gains 2/1/0), document hit@5.
  - **Pooled** R@5 and R@20: relevant means judged relevant within the pool, not across the whole corpus.
  - Rankings are the pooled per-system ranks, so "R@20" covers ranks up to 15 that made it into the pool.

**Generation evaluation** (`legalai-grounded-answer-eval-v1`, frozen; `legal_answer_eval*.json`):
- 30 queries, 15 public and 15 professional, 10 at each difficulty. They include 4 `negative_out_of_scope` queries
  and 7 with ambiguous or insufficient facts.
- The historical run (September 2026) used Gemini `gemini-3.6-flash` with prompt v1 under two conditions:
  `LLM_ONLY` and `GROUNDED_RAG` (hybrid + rerank top 5).
- Grounding there is **structural**: `validate_legal_answer_citations` checks every citation's evidence ID, claim
  link and copied metadata against the retrieved evidence, and `validate_claim_grounding` labels each answer
  STRUCTURALLY, PARTIALLY or UNGROUNDED. Its results: GROUNDED_RAG 29 of 30 parsed, 23 structurally grounded.
- 0 human reviews exist.

## 2. Retrieval re-run (no LLM)

`backend/scripts/rerun_retrieval_eval.py` re-retrieved the 30 frozen queries on the current stores, pooled them
with the frozen rules, and scored them against the frozen human labels with the frozen metric code. A self-check
first reproduces the published frozen numbers from the frozen traces.

| System | P@5 (broad) | Pooled R@5 | Pooled R@20 | MRR@5 | nDCG@5 | P@5 (strict) | Pooled rankings identical to frozen |
|---|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.833 | 0.277 | 0.673 | 0.917 | 0.728 | 0.533 | 30/30 |
| Dense | 0.860 | 0.284 | 0.686 | 0.942 | 0.786 | 0.593 | 30/30 |
| Hybrid (RRF) | 0.873 | 0.286 | 0.705 | 0.961 | **0.785** (frozen 0.787) | **0.587** (frozen 0.593) | 29/30 |
| Hybrid + rerank | 0.873 | 0.290 | 0.723 | 0.961 | 0.819 | 0.633 | 30/30 |

- Every number equals the frozen one except hybrid nDCG@5 and strict P@5, in one query (`eval-q005`). The CPU fp32
  run (the frozen configuration) and the product run (MPS, fp16 reranker) give identical results. No re-run ranking
  contains an unjudged chunk.
- **The q005 difference.** Chunk `indian_kanoon:47759402:chunk:0001` was found by BM25 alone in the frozen run
  (rank 3; RRF 1/63). It is now also returned by dense retrieval at rank 20, the last of the 20 candidates (RRF
  1/63 + 1/80), which moves it from hybrid rank 11 to 5. Dense ranks 1-15, the only ones stored, are identical.
  The change is at the boundary of the dense top 20, consistent with approximate nearest-neighbour search (HNSW)
  on the rebuilt Chroma index. It does not reach hybrid + rerank, whose rankings are identical.
- **Caveat:** recall is pooled recall, so it understates recall against the whole corpus.

## 3. Generation: three configurations

`backend/scripts/run_three_config_eval.py`, on the 30 frozen queries:

| Configuration | Evidence | Prompt |
|---|---|---|
| A, LLM-only | none | `legal_answer_prompt_v3_llm_only` (v3 structure and length rules, empty citations, no invented authority) |
| B, dense-only RAG | BGE-M3 dense top 5 (no BM25, RRF or reranker) | v3 |
| C, full LegalAI | hybrid BM25 + dense RRF + BGE reranker, top 5 | v3 |

**Shared setup:**
- B and C run the product's own generation step (`_attempt_generation`: evidence budget, size guard, prompt v3,
  citation validation).
- All three use the current routing and the step 23 pacing queue.
- The three configurations are run interleaved for each query.

**Metrics:**
- schema validity and truncation;
- **structural grounding:** valid citations / total, and answers with at least one claim citing valid evidence;
- **unsupported-citation rate:** structured citations to IDs or cases not in the evidence (`UNKNOWN_EVIDENCE_ID`,
  `UNSUPPORTED_CASE_REFERENCE`), plus case names or reporter citations written in the answer text that match no
  evidence case name (a heuristic; the human review checks it). In A every reference counts as unsupported;
- no-coverage answers;
- latency, tokens and the answering model.

### Results

**Paired comparison** (the 24 queries all three configurations answered with a schema-valid answer: 13 public and
11 professional; the fairest comparison):

| | A, LLM-only | B, dense RAG | C, full LegalAI |
|---|---:|---:|---:|
| Citations: valid / total | 0 / 0 | 71 / 71 | 73 / 73 |
| Structural grounding rate | n/a (no citations) | 1.00 | 1.00 |
| Answers with ≥1 valid grounded claim | 0.0% | 87.5% (21/24) | **95.8%** (23/24) |
| Flagged unsupported references / all references | 3 / 3 | 1 / 72 | 3 / 77 |
| …of which are real case names not in the evidence (checked by hand) | 3 | 1 | 2 |
| Out-of-scope (4): no-coverage answer | 0 / 4 | 2 / 4 | 1 / 4 |
| In-scope answered "not covered" | 0 | 2 | 0 |
| Median latency (s, including queue wait) | 4.4 | 33.6 | 29.4 |

**By mode** (all 15 queries of each mode; rates of schema-valid answers):

| | A public | B public | C public | A professional | B professional | C professional |
|---|---:|---:|---:|---:|---:|---:|
| Schema-valid | 15/15 | 15/15 | 13/15 | 12/15 | 14/15 | **15/15** |
| Not schema-valid | — | — | 1 BUSY, 1 Groq 400 | 1 schema, 2 Groq 400 | 1 schema | — |
| Valid / total citations | 0 / 0 | 38 / 38 | 39 / 39 | 0 / 0 | 46 / 48 | 46 / 46 |
| Answers with ≥1 valid grounded claim | 0% | 80.0% | 92.3% | 0% | 92.9% | 93.3% |
| Flagged unsupported / all references | 0 / 0 | 0 / 38 | 1 / 41 | 4 / 4 | 2 / 50 | 3 / 49 |
| Out-of-scope (2): no-coverage answer | 0 / 2 | 1 / 2 | 1 / 2 | 0 / 2 | 1 / 2 | 0 / 2 |
| In-scope answered "not covered" | 0 | 3 | 0 | 0 | 0 | 1 |
| Median latency (s) | 2.0 | 33.3 | 25.7 | 16.5 | 35.2 | 43.7 |

**All 30 queries:**

| | A | B | C |
|---|---:|---:|---:|
| SUCCESS / SCHEMA_FAILED / BUSY / PROVIDER_ERROR | 27 / 1 / 0 / 2 | 29 / 1 / 0 / 0 | 28 / 0 / 1 / 1 |
| Truncated | 0 | 0 | 0 |
| Valid / total citations | 0 / 0 | 84 / 86 | 85 / 85 |
| Answers with ≥1 valid grounded claim (of schema-valid) | 0% | 86.2% | 92.9% |
| Completion tokens | 22,745 | 35,551 | 33,970 |
| Answering model (schema-valid answers) | 120b 16, 20b 11 | 120b 20, 20b 9 | 120b 18, 20b 10 |

All professional answers came from gpt-oss-120b; public answers came from either model under the pacing queue.

**Reading:**
- **Grounding.** In the paired set, C grounds 95.8% of answers with at least one valid cited claim, against 87.5%
  for B and 0% for A (which has no evidence, by construction). Every structured citation in C passed validation
  (85/85); B had 2 rejected citations of 86, both in professional answers.
- **Unsupported references are not "lower" in C than in A.**
  - A's references are all unsupported by construction (it has no evidence). In public answers it named no case
    at all, which makes those answers unverifiable rather than better supported. In professional answers it named
    4 cases from memory (*State v. K. K. Singh*, *Sukhram Singh v. State*, *State v. Ramesh*, *Arun Kumar v.
    State*), none of which can be checked against evidence.
  - C named 2 real cases that are not in its retrieved evidence: *Shajan Skaria v. State of Kerala* (ans-q009,
    public) and *Union of India v. Nirala Yadav* (ans-q021, professional). B also named *Nirala Yadav* in ans-q021.
  - The automatic text heuristic counts any "X v. Y" as a case name, so it also flagged three statute comparisons:
    "IPC v. BNSS" (B and C, ans-q019) and "BNS v. Section" (C, ans-q026). The table gives both counts. The scorer
    was **not** changed after seeing these results; the human review's authority rows check every flagged name.
  - All the unsupported case names are in the answer **text**. None is a structured citation: the validator
    rejects structured citations to cases outside the evidence, but it does not read the answer text.
- **Professional answers on 120b only.** With the step 24b policy (no fallback to 20b), the professional schema-valid
  rate rose from 1/15 per configuration (step 24, when 20b answered professional queries as the fallback) to 12-15
  of 15. B and C together produced 29 schema-valid professional answers from 30 attempts that reached the model
  (one schema failure, B ans-q016). The 120b failures are in A (one schema failure, two Groq "json_validate_failed"
  400s: the model's JSON was rejected by the provider).
- **Dense-only retrieval.** B answered three in-scope public questions as "not covered" (two in the paired set),
  which C did not. C answered one in-scope professional question (ans-q017) as "not covered", which B did not.
- **Out-of-scope queries.** Only B and C ever say "not covered" (B 2 of 4, C 1 of 4); A answers all out-of-scope
  questions from general knowledge.
- **Latency.** Medians include the pacing-queue wait (professional: up to 45 s for 120b; C's median professional
  queue wait in the paired set was 36 s). Model time alone is far shorter.

### How the professional half was completed (steps 24b-24c)

**Step 24, 2026-10-30.** The first run exhausted Groq's daily limit, 200,000 tokens per model, in its professional
half. The step 22-23 live runs earlier that day had used part of it.
- Every 429 said "tokens per day (TPD): Limit 200000, Used 195-199K", with retry times of 6-33 minutes.
- 25 records were refused as `MODEL_BUSY`: the retry time was beyond the queue wait.
- With gpt-oss-120b exhausted, professional answers fell back to gpt-oss-20b. 20b **failed the professional schema
  in 10 of its 11 professional answers** in B and C (`MODEL_OUTPUT_VALIDATION_FAILED`, plus 2 Groq
  "json_validate_failed" 400s).

**Step 24b, decided from these results.**
- Professional answers never fall back to 20b. They wait up to 45 s for 120b, then get `MODEL_BUSY`.
- Daily budgets are tracked per model. When no model can serve, the answer is `DAILY_CAPACITY_REACHED`.
- Step 24c changed the tracker to Groq's rolling 24-hour window.
- The 43 failed and superseded professional records were moved aside (kept outside the repository, not deleted).

**Re-run, 2026-10-31 16:51-17:13 UTC.**
- The tracker started with all 200,000 tokens available on both models.
- 43 cells: 36 answers, 2 schema failures, 2 Groq 400s, and 5 BUSY.
- The BUSY cells hit the per-minute limit: one 120b model, about 6,000-7,000 tokens per answer, and 8,000 tokens
  per minute.

**Retry of the 5 BUSY cells, spaced 75 s apart.**
- 4 were answered.
- The fifth, B ans-q029, was refused by the daily tracker **before sending** (`DAILY_CAPACITY_REACHED`; 120b had
  used 194,393 of its 200,000 tokens in the window).
- The retried answers' latencies (76-80 s) include the 75 s spacing.

Steps 24b-24c used **42 provider calls** (40 OK, 2 HTTP 400) of the 45 approved, and no daily-limit 429.

**B ans-q029, 2026-11-01 17:17 UTC (step 24c).**
- Before the call, `llm_daily` showed 176,105 of 200,000 tokens free for 120b (the gate was ≥ 8,000).
- **1 provider call** (HTTP 200) of the 2 allowed. The answer is schema-valid, with 2 of 2 citations valid and no
  unsupported references.
- The BUSY record it replaces is kept outside the repository.

**Capacity lesson.** A day of Groq's free tier allows about 30 answers per model. One three-configuration pass
over 15 professional queries, about 45 answers on 120b, does not fit in one day.

## 4. Human review

`backend/scripts/build_review_sheet.py` wrote `~/legalai_reviews/eval_runs/2026-10_v3_groq/human_review/review_sheet.csv`
(outside the repository) for a stratified sample of 15 queries x 3 configurations: both modes, all difficulties,
and 2 out-of-scope queries.
- **Blinding:** configurations appear as X/Y/Z, shuffled per query; the key is in `review_key.json`, kept from
  reviewers.
- **Answer rows:** reviewers fill `legal_correctness` (correct, partly_correct, incorrect or cannot_judge).
- **Authority rows** (every cited authority, and every case named in the text): reviewers fill `citation_support`
  (supported, partly, not_supported or incorrect_law).
- **Import:** `backend/scripts/import_human_review.py --sheet … --key … --output data/evaluation/runs/2026-10_v3_groq/human_review/result.json`
  validates the sheet and computes the **human-verified grounding rate** per configuration (strict: supported;
  lenient: supported or partly), the incorrect-law share, and legal correctness.
- **Sheet:** regenerated after the professional re-run (same seed, so the same 15 queries: 8 public, 7
  professional). 43 of the 45 sampled answers are real answers. The other 2 are a Groq 400 in C public (ans-q014)
  and in A professional (ans-q020), shown to reviewers as failed. The sheet has 129 rows: 45 answers, 82 cited
  authorities (B 40, C 42; A cites none) and 2 cases named in C's answer text.
- **Evidence excerpts were cut at 600 characters** (`run_three_config_eval.py` stores `text[:600]` for each retrieved
  item, and the sheet shows that). Every one of the 82 excerpts is exactly 600 characters, often ending mid-sentence,
  while a chunk can be up to about 900 tokens. The reviewer saw only the start of each cited passage.

### Round 2 (2026-11-13): full cited passages — the headline result, UNREVIEWED by a person

**Reviewer provenance:** the reviewer is an AI chat assistant (not Claude Code), working from full passages, blind to
configuration and not human-verified. The `reviewer` column of every round 2 row reads "AI (Claude chat; not Claude
Code); round 2 with full passages; blind to configuration; not human-verified". The completed sheet is
`~/legalai_reviews/eval_runs/2026-10_v3_groq/human_review/review_sheet_round2_reviewed.csv` (outside the
repository). It re-judged the 66 authority rows that round 1 did not judge `supported` (65 structured citations and
the "BNS v. Section" text reference), seeing each cited chunk in full and round 1's judgment and notes. The import
(`import_human_review.py --round 2`) is in `data/evaluation/runs/2026-10_v3_groq/human_review/result_round2.json`
(aggregates only); round 1's `result.json` is unchanged.

**Round 1 vs round 2, structured citations** (round 2 = round 1 with the 65 re-judged citations replaced):

| | A, LLM-only | B, dense RAG, round 1 | B, round 2 | C, full LegalAI, round 1 | C, round 2 |
|---|---:|---:|---:|---:|---:|
| Structured citations | 0 | 40 | 40 | 42 | 42 |
| Structural grounding (valid / total) | n/a | 1.00 | 1.00 | 1.00 | 1.00 |
| Strict (supported) | n/a | 0.225 (9) | **0.650** (26) | 0.190 (8) | **0.690** (29) |
| Lenient (supported or partly) | n/a | 0.700 (28) | **0.775** (31) | 0.595 (25) | **0.762** (32) |
| not_supported / incorrect_law | — | 8 / 4 | 5 / 4 | 13 / 4 | 7 / 3 |
| Change, strict / lenient | — | | +0.425 / +0.075 | | +0.500 / +0.167 |

With C's two text-named cases (the importer's headline figure; round 2 leaves "BNS v. Section" `not_applicable`), C is
0.209 / 0.605 in round 1 and **0.698 / 0.767** in round 2 over 43 judged authorities (change +0.488 / +0.163).
Incorrect-law share: B 0.100 in both rounds; C 0.093 -> 0.070.

**Movement** (round 1 -> round 2, the re-judged rows):

| Round 1 -> round 2 | B (31 rows) | C (35 rows) |
|---|---:|---:|
| partly -> supported | 13 | 15 |
| not_supported -> supported | 4 | 5 |
| incorrect_law -> supported | 0 | 1 |
| not_supported -> partly | 0 | 1 |
| partly -> partly | 5 | 2 |
| not_supported -> not_supported | 4 | 7 |
| incorrect_law -> incorrect_law | 4 | 3 |
| partly -> not_supported | 1 | 0 |
| not_applicable -> not_applicable | 0 | 1 |
| **Up / unchanged / down** | **17 / 13 / 1** | **22 / 13 / 0** |

**The 600-character cut caused most of the round 1 gap.** Round 2 changed only what the reviewer saw (the full chunk
instead of its first 600 characters). With that, strict support rose from 17 to 55 of the 82 structured citations
(B+C), closing 58% of round 1's gap to full support (B 55%, C 62%). The lenient rate moved less (53 -> 63 of 82),
because round 1 had already counted most of these citations as `partly`. What remains after round 2 is the residual
gap: about a third of citations are not fully supported (B 14, C 13), including 12 judged `not_supported` and 7
`incorrect_law`.

**Remaining incorrect-law citations (7: B 4, C 3).** They cluster in IPC→BNS transition reasoning: 3 of the 7, and
2 of C's 3, misstate how the IPC and the BNS apply across 1 July 2024. The other 4 are each a different error.
- **Transition (3):**
  - C ans-q007 ("murder remains under IPC 302 after the transition"; an offence after 1 July 2024 is BNS 103);
  - C ans-q026 ("302 IPC is the proper charge if homicide is proven"; the offence date, not proof, decides 302 vs
    103);
  - B ans-q026 ("BNS 103 and IPC 302 may both apply"; they cannot both apply to the same act).
- **Other (4):**
  - B ans-q001: "bail is a constitutional right", which in the passage is only a party's submission (the passage is
    about suspension of sentence);
  - C ans-q003: the case is said to have found robbery, while the court held the s.392 conviction unsustainable;
  - B ans-q015: misdescribes the content of SC/ST Act s.3(2)(v)/(va);
  - B ans-q023: says NDPS s.35 presumes possession; it presumes a culpable mental state.

**Reading round 2.**
- **C and B are still not distinguishable.** C is slightly higher on strict support (0.690 vs 0.650), B on lenient
  (0.775 vs 0.762). One judgment moves a rate by about 2.5 points.
- **Round 2 can mostly only move up.** It re-judged only rows round 1 did not call `supported`, and the reviewer saw
  round 1's judgments, so it may anchor on them. One row moved down (B, partly -> not_supported).
- **Same reviewer type as round 1,** AI, not human-verified, of the same model family as the assistant that built
  the pipeline; its errors may be correlated with the system's.

### Round 1 (2026-11-13): 600-character excerpts — kept for history, UNREVIEWED by a person

**Reviewer provenance:** the reviewer is an AI chat assistant (not Claude Code), blind to configuration and not
human-verified. The `reviewer` column of every row reads "AI (Claude chat; not Claude Code); blind to configuration;
not human-verified". The completed sheet is
`~/legalai_reviews/eval_runs/2026-10_v3_groq/human_review/review_sheet_reviewed.csv` (outside the repository); its
non-review columns are identical to the issued sheet. The aggregates (no answer text) are in
`data/evaluation/runs/2026-10_v3_groq/human_review/result.json`. The script's "human-verified" field names are kept,
but these are **AI-reviewed** rates.

**Scale.** The reviewer used the sheet's values plus three it has no counterpart for: `abstained` (5 answers: a
no-coverage answer instead of a legal answer; the notes call three reasonable, one unwarranted (B ans-q003), and
one a possible corpus gap on a question POCSO covers (B ans-q014)),
`no_answer` (2: the two failed cells above) and `not_applicable` (1 authority row: "BNS v. Section", a scorer
artefact, not a case). By the project owner's decision these are kept **one-to-one as their own categories**: the
importer accepts them, counts them, and leaves them out of the denominators like `cannot_judge`. No judgment was
edited or merged.

**Erratum (2026-11-13, verdict unchanged), row `ans-q020-X-01`** (answer, `partly_correct`): the round 1 note's
"exception backwards" reasoning was wrong. The full passage (paras 24-25) adopts the view that cured filings continue
under the CrPC (round 2, ans-q020-X-05: incorrect_law -> supported). The `partly_correct` verdict stands because
remand is not addressed. The note is appended to that row's `notes` in `review_sheet_reviewed.csv` (the sheet before
the erratum is kept as `review_sheet_reviewed.before_erratum_20261113.csv`); no other cell changed, and re-importing
round 1 gives an identical `result.json`.

**Reviewed grounding next to structural grounding** (the same sampled answers; structural = the validator's valid /
total structured citations):

| | A, LLM-only | B, dense RAG | C, full LegalAI |
|---|---:|---:|---:|
| Structured citations reviewed | 0 | 40 | 42 |
| Structural grounding (valid / total) | n/a (no citations) | 1.00 (40/40) | 1.00 (42/42) |
| Reviewed grounding, strict (supported) | n/a | **0.225** (9/40) | **0.190** (8/42) |
| Reviewed grounding, lenient (supported or partly) | n/a | 0.700 (28/40) | 0.595 (25/42) |
| not_supported / incorrect_law | — | 8 / 4 | 13 / 4 |
| Incorrect-law share | — | 0.100 | 0.095 |
| Cases named in the answer text | — | — | 2: 1 supported, 1 not_applicable |

With C's text reference included (the importer's headline figure), C is 0.209 strict and 0.605 lenient over 43
judged authorities.

**Legal correctness** (answers; `abstained`, `no_answer` and `cannot_judge` are not judged for correctness):

| | A | B | C |
|---|---:|---:|---:|
| correct / partly_correct / incorrect | 6 / 5 / 3 | 6 / 3 / 2 | 6 / 7 / 0 |
| abstained / no_answer | 0 / 1 | 4 / 0 | 1 / 1 |
| Share correct (of answers judged) | 0.43 (6/14) | 0.55 (6/11) | 0.46 (6/13) |

**The gap between structural and reviewed grounding (round 1; see round 2 above).** Every structured citation in B and C is structurally valid
(1.00), but the reviewer judged only about one in five fully supported by the excerpt shown (B 0.225, C 0.190), and
six to seven in ten at least partly supported. Structural validity proves that a citation points at real retrieved
evidence with matching metadata; it does not show that the passage supports the claim. That second question is
where most citations fall short. Reading the gap:
- **The excerpt cut lowers the reviewed rate.** In 11 of the 83 judged authority rows the notes say the supporting
  content was not in the excerpt shown (2 of them say the excerpt was cut off). With full passages some `partly` and
  `not_supported` judgments could move up, so the strict rate is a lower bound for these citations. (Round 2
  confirmed this: strict support rose from 0.21 to 0.67 with full passages.)
- **Not all of it is the cut.** Many notes describe an excerpt on a different point (for example a bail claim
  citing a passage about section 313 statements), and 8 citations (B 4, C 4) were judged to state the wrong law.
- **C is not better than B on this sample.** C's reviewed rates are slightly lower (strict 0.190 vs 0.225, lenient
  0.595 vs 0.700), against C's higher share of answers with a grounded claim in section 3. With 40-42 citations a
  difference of one or two judgments moves the rate by 2.5-5 points, so the two are not distinguishable here.
- **One reviewer, AI, not human-verified,** and of the same model family as the assistant that built the pipeline;
  its errors may be correlated with the system's. These rates are evidence about the gap, not a final grounding
  figure.

### How round 2 was built (step 28)

- **Sheet:** `review_sheet_round2.csv`, built by `backend/scripts/build_review_round2.py`: the 66 round 1 authority
  rows not judged `supported` (65 structured citations: round 1 partly 36, not_supported 21, incorrect_law 8; and the
  "BNS v. Section" text reference, which cites no chunk). The 18 rows judged `supported` in round 1 were not re-asked.
- **Full passages:** each citation's chunk is read from PostgreSQL (read-only, `chunks.chroma_id`). All 92 chunk IDs
  saved for the run were found, and all 65 citation rows matched exactly one chunk whose text starts with the round 1
  excerpt (33 distinct chunks, 1,764 to 4,024 characters).
- **Blinding kept:** rows keep their `review_id`, `example_id` and X/Y/Z label; the builder never reads
  `review_key.json` and finds each chunk among the evidence of all three configurations of the query.
- **Import:** `import_human_review.py --round 2 --sheet …round2_reviewed.csv --round1-sheet …reviewed.csv --key …
  --output data/evaluation/runs/2026-10_v3_groq/human_review/result_round2.json`; it refuses to write over the round
  1 `result.json`.

## 5. Labelling kit (about 70 new retrieval queries)

`data/evaluation/labelling_kit/`:
- `queries_template.csv`;
- `LABELLING_GUIDE.md`: the scale, pooling, blinding, worked examples, and coverage targets across offence
  families, IPC vs BNS, and procedure;
- `generate_pools.py`: the frozen pool-v1 method, no LLM;
- `validate_labels.py`: checks a sheet, then merges the frozen 30 plus the new queries into a new
  `legalai-retrieval-eval-v2`; the frozen files are only read and their hashes are checked;
- `TEAM_GUIDE.md`: the steps and time estimates, about 25-30 person-hours.

Tested with fakes, and live on 2 example queries (22 and 24 pooled candidates), which were then removed.

## 6. Caveats

- **Sample size:** 30 generation queries, with 24 answered by all three configurations. Differences of a few
  answers are within noise (one answer in the paired set is 4.2 points).
- **Three days:** the public half ran on 2026-10-30, the professional half on 2026-10-31 (the 4 retried cells
  later that day), and B ans-q029 on 2026-11-01. Each configuration's queries of one mode ran in the same session, interleaved, so the
  comparison between configurations is not affected; the comparison between modes partly is.
- **Unsupported-reference heuristic:** see the reading above. Flagged counts are upper bounds; the hand-checked
  counts are given beside them.
- **Structural is not reviewed grounding:** a valid citation points at real retrieved evidence, but that is not proof
  the evidence supports the claim or that the law is correct. On the review sample, structural grounding is 1.00 for
  B and C while the AI-reviewed strict rate with full passages (round 2) is 0.650 and 0.690 (section 4).
- **The review is AI, not human-verified,** in both rounds; round 1 saw excerpts cut at 600 characters, round 2 the
  full passages for the rows round 1 did not judge supported (section 4).
- **Pooled recall** for retrieval (above).
- **Provider change:** the historical generation run used Gemini with prompt v1, this one Groq gpt-oss with prompt
  v3. The two are not directly comparable.
- **Model mix (public only):** under the pacing queue a public answer can come from either model (schema-valid
  public answers on 20b / 120b: A 11 / 4, B 9 / 6, C 10 / 3), so for public queries configuration and model are
  partly confounded. This is the product's real behaviour. Professional answers are all from 120b.

## 7. Future improvements

- **Unsupported case names in answer text** (decision, step 24b: recorded, not changed now). The validator checks
  structured citations only, so a case named in the answer text but absent from the evidence passes. In this run
  that happened in 2 of C's 28 schema-valid answers: *Union of India v. Nirala Yadav* (professional) and *Shajan
  Skaria v. State of Kerala* (public). A future check could detect case names in the answer text (with a stricter pattern
  than this evaluation's heuristic, which also matches "IPC v. BNSS"). It could then reject them, or mark them as
  "not from the retrieved sources", when they match no evidence case name. That would change the validator and
  the pinned prompt contract, so it needs its own step and a re-run.
- **Daily capacity:** see `docs/LLM_PROVIDER_CONFIGURATION.md`, "Capacity planning". Evaluations, UAT and the
  demo run on separate days (decision, step 24b). Before each, check `/health` → `llm_daily`: it shows the
  remaining budget in the rolling 24 hours.

## 8. Next steps

1. A person checks the AI review of the 15 x 3 sample (both rounds), starting with the 7 incorrect-law citations and
   the 12 judged `not_supported` in round 2.
2. Collect the about 70 new benchmark queries and labels with the kit, then recompute retrieval metrics on v2.
