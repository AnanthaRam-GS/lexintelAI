# Evaluation 2026-10: three-configuration re-run (prompt v3, Groq)

Step 24, plan Task 4.A.1 (RAG-003, R32). The run data is in `data/evaluation/runs/2026-10_v3_groq/`; the full,
UNREVIEWED outputs are outside the repository.

**Status: partly complete.**
- **Retrieval:** complete.
- **Generation:** complete for the 15 public queries; the 15 professional queries were cut short by Groq's daily
  token limit (details below).
- **Human review:** sheet produced, not yet filled.

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

**Paired comparison** (the 13 public queries all three answered; the fairest comparison):

| | A, LLM-only | B, dense RAG | C, full LegalAI |
|---|---:|---:|---:|
| Schema-valid | 13/13 | 13/13 | 13/13 |
| Citations: valid / total | 0 / 0 | 36 / 36 | 39 / 39 |
| Structural grounding rate | n/a (no citations) | 1.00 | 1.00 |
| Answers with ≥1 valid grounded claim | 0.0% | 84.6% | **92.3%** |
| Unsupported references / all references | 0 / 0 (undefined) | 0 / 36 | 1 / 41 (2.4%) |
| Out-of-scope: no-coverage answer | 0 / 2 | 1 / 2 | 1 / 2 |
| In-scope answered "not covered" | 0 | 2 | 0 |
| Median latency (s, including queue wait) | 1.7 | 29.9 | 25.7 |

**All 30 queries:**

| | A | B | C |
|---|---:|---:|---:|
| SUCCESS / SCHEMA_FAILED / BUSY / PROVIDER_ERROR | 16 / 7 / 7 / 0 | 16 / 4 / 9 / 1 | 14 / 6 / 9 / 1 |
| Truncated | 0 | 0 | 0 |
| Public: schema-valid | 15/15 | 15/15 | 13/15 |
| Professional: schema-valid | 1/15 | 1/15 | 1/15 |
| Valid / total citations | 0 / 0 | 42 / 42 | 39 / 39 |
| Answers with ≥1 valid grounded claim (of answered) | 0% | 81.3% | 85.7% |
| Completion tokens | 11,132 | 17,706 | 19,735 |

**Reading:**
- **Grounding.** C grounds more answers than A, which grounds none by construction: 92.3% against 0% of answers
  have a valid cited claim. C also grounds more than B (92.3% against 84.6%). Every structured citation in B and C
  passed validation.
- **Unsupported citations are not "lower" in C than in A.** A's rate is undefined: told not to invent authority,
  it named no case at all, which makes its answers unverifiable rather than better supported. C named one case
  that is not in its evidence (*Shajan Skaria v. State of Kerala*, ans-q009), so its rate is 1 of 41. The result
  is reported as measured; nothing was tuned.
- **Dense-only retrieval.** B answered two in-scope questions as "not covered", which C did not: dense-only
  retrieval finds weaker evidence for some queries. The paired retrieval numbers above agree.
- **Out-of-scope queries.** Only B and C ever say "not covered"; A answers out-of-scope questions from general
  knowledge.

### Why the professional half is incomplete

Groq's free tier allows 200,000 tokens per model per day. The step 22-23 live runs earlier the same day, plus this
run, exhausted both models' daily limits during the professional half. Every 429 says "tokens per day (TPD):
Limit 200000, Used 195-199K", with retry times of 6-33 minutes. The step 23 pacing models the per-minute limit;
the daily limit has no header, so:
- **25 records were refused as `MODEL_BUSY`**, correctly: the retry time was beyond the 90 s queue wait.
- **With gpt-oss-120b exhausted, professional answers fell back to gpt-oss-20b, which failed the professional schema
  in 10 of its 11 professional answers in B and C** (`MODEL_OUTPUT_VALIDATION_FAILED`; plus 2 Groq
  "json_validate_failed" 400s). This is evidence for the
  step 24 professional fallback policy (wait for 120b), and against relying on 20b for professional briefs.

**To complete:** after the daily limit resets, delete the failed professional records and re-run (about 42 calls;
the script skips records that exist), then regenerate the review sheet. Results for the professional half should not
be quoted until then.

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
- **Current state:** 17 of the 45 sampled answers are the failed professional records. Regenerate the sheet after
  the re-run, before review starts.

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

- **Sample size:** 30 generation queries, with 13 answered by all three configurations. Differences of a few
  answers are within noise.
- **Structural is not human grounding:** a valid citation points at real retrieved evidence, but that is not proof
  the evidence supports the claim or that the law is correct. The human review measures that.
- **Pooled recall** for retrieval (above).
- **Provider change:** the historical generation run used Gemini with prompt v1, this one Groq gpt-oss with prompt
  v3. The two are not directly comparable.
- **Model mix:** under the pacing queue a configuration's answer can come from either model (successful answers:
  A 11 on 20b and 5 on 120b, B 10 and 6, C 10 and 4), so configuration and model are partly confounded. This is the
  product's real behaviour. The paired subset is all public: A was answered by 20b/120b in 10/3 queries, B in 7/6,
  C in 10/3.

## 7. Next steps

1. Re-run the professional half after Groq's daily limit resets (about 42 calls), then regenerate the review sheet.
2. Human review of the 15 x 3 sample, then run `import_human_review.py`.
3. Collect the about 70 new benchmark queries and labels with the kit, then recompute retrieval metrics on v2.
4. For UAT and evaluations: Groq's daily limit (200K tokens per model) caps a day at about 30 answers per model.
   Plan heavy runs on separate days, or use a paid tier.
