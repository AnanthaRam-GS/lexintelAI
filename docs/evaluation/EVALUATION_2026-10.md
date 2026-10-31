# Evaluation 2026-10: three-configuration re-run (prompt v3, Groq)

Steps 24-24c, plan Task 4.A.1 (RAG-003, R32). The run data is in `data/evaluation/runs/2026-10_v3_groq/`; the
full, UNREVIEWED outputs are outside the repository.

**Status: complete for automatic metrics; human review not yet done.**
- **Retrieval:** complete.
- **Generation:** all 90 cells (30 queries x 3 configurations) have a record.
  - Public half: run on 2026-10-30 (step 24).
  - Professional half: re-run on 2026-10-31 (step 24b) on gpt-oss-120b only, under the no-fallback policy.
  - 83 records are schema-valid answers. The other 7: 2 schema failures, 3 Groq "json_validate_failed" 400s and
    2 BUSY.
- **Human review:** sheet produced for the full sample, not yet filled.

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

**Paired comparison** (the 23 queries all three configurations answered with a schema-valid answer: 13 public and
10 professional; the fairest comparison):

| | A, LLM-only | B, dense RAG | C, full LegalAI |
|---|---:|---:|---:|
| Citations: valid / total | 0 / 0 | 69 / 69 | 71 / 71 |
| Structural grounding rate | n/a (no citations) | 1.00 | 1.00 |
| Answers with ≥1 valid grounded claim | 0.0% | 87.0% (20/23) | **95.7%** (22/23) |
| Flagged unsupported references / all references | 3 / 3 | 1 / 70 | 3 / 75 |
| …of which are real case names not in the evidence (checked by hand) | 3 | 1 | 2 |
| Out-of-scope (4): no-coverage answer | 0 / 4 | 2 / 4 | 1 / 4 |
| In-scope answered "not covered" | 0 | 2 | 0 |
| Median latency (s, including queue wait) | 3.8 | 33.6 | 29.4 |

**By mode** (all 15 queries of each mode; rates of schema-valid answers):

| | A public | B public | C public | A professional | B professional | C professional |
|---|---:|---:|---:|---:|---:|---:|
| Schema-valid | 15/15 | 15/15 | 13/15 | 12/15 | 13/15 | **15/15** |
| Not schema-valid | — | — | 1 BUSY, 1 Groq 400 | 1 schema, 2 Groq 400 | 1 schema, 1 BUSY | — |
| Valid / total citations | 0 / 0 | 38 / 38 | 39 / 39 | 0 / 0 | 44 / 46 | 46 / 46 |
| Answers with ≥1 valid grounded claim | 0% | 80.0% | 92.3% | 0% | 92.3% | 93.3% |
| Flagged unsupported / all references | 0 / 0 | 0 / 38 | 1 / 41 | 4 / 4 | 2 / 48 | 3 / 49 |
| Out-of-scope (2): no-coverage answer | 0 / 2 | 1 / 2 | 1 / 2 | 0 / 2 | 1 / 2 | 0 / 2 |
| In-scope answered "not covered" | 0 | 3 | 0 | 0 | 0 | 1 |
| Median latency (s) | 2.0 | 33.3 | 25.7 | 16.5 | 38.3 | 43.7 |

**All 30 queries:**

| | A | B | C |
|---|---:|---:|---:|
| SUCCESS / SCHEMA_FAILED / BUSY / PROVIDER_ERROR | 27 / 1 / 0 / 2 | 28 / 1 / 1 / 0 | 28 / 0 / 1 / 1 |
| Truncated | 0 | 0 | 0 |
| Valid / total citations | 0 / 0 | 82 / 84 | 85 / 85 |
| Answers with ≥1 valid grounded claim (of schema-valid) | 0% | 85.7% | 92.9% |
| Completion tokens | 22,745 | 33,972 | 33,970 |
| Answering model (schema-valid answers) | 120b 16, 20b 11 | 120b 19, 20b 9 | 120b 18, 20b 10 |

All professional answers came from gpt-oss-120b; public answers came from either model under the pacing queue.

**Reading:**
- **Grounding.** In the paired set, C grounds 95.7% of answers with at least one valid cited claim, against 87.0%
  for B and 0% for A (which has no evidence, by construction). Every structured citation in C passed validation
  (85/85); B had 2 rejected citations of 84, both in professional answers.
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
  of 15. B and C together produced 28 schema-valid professional answers from 29 attempts that reached the model
  (one schema failure, B ans-q016). The 120b failures are in A (one schema failure, two Groq "json_validate_failed"
  400s: the model's JSON was rejected by the provider).
- **Dense-only retrieval.** B answered three in-scope public questions as "not covered" (two in the paired set),
  which C did not. C answered one in-scope professional question (ans-q017) as "not covered", which B did not.
- **Out-of-scope queries.** Only B and C ever say "not covered" (B 2 of 4, C 1 of 4); A answers all out-of-scope
  questions from general knowledge.
- **Latency.** Medians include the pacing-queue wait (professional: up to 45 s for 120b; C's median professional
  queue wait in the paired set was 37 s). Model time alone is far shorter.

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
  used 194,393 of its 200,000 tokens in the window). It keeps its BUSY record from the re-run.
- The retried answers' latencies (76-80 s) include the 75 s spacing.

Step 24b-24c used **42 provider calls** (40 OK, 2 HTTP 400) of the 45 approved, and no daily-limit 429.

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
- **Current state:** regenerated after the professional re-run (same seed, so the same 15 queries: 8 public, 7
  professional). 43 of the 45 sampled answers are real answers. The other 2 are a Groq 400 in C public (ans-q014)
  and in A professional (ans-q020), shown to reviewers as failed. The sheet has 129 rows. It is ready for review
  and not yet filled.

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

- **Sample size:** 30 generation queries, with 23 answered by all three configurations. Differences of a few
  answers are within noise (one answer in the paired set is 4.3 points).
- **Two days:** the public half ran on 2026-10-30 and the professional half on 2026-10-31 (the 4 retried cells
  later that day). Each configuration's queries of one mode ran in the same session, interleaved, so the
  comparison between configurations is not affected; the comparison between modes partly is.
- **Unsupported-reference heuristic:** see the reading above. Flagged counts are upper bounds; the hand-checked
  counts are given beside them.
- **Structural is not human grounding:** a valid citation points at real retrieved evidence, but that is not proof
  the evidence supports the claim or that the law is correct. The human review measures that.
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

1. Human review of the 15 x 3 sample, then run `import_human_review.py`.
2. Collect the about 70 new benchmark queries and labels with the kit, then recompute retrieval metrics on v2.
3. Optional, on another day: retry B ans-q029 (1 call) for a complete professional row.
