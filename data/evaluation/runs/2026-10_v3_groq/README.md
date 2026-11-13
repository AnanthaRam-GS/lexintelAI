# Evaluation run 2026-10_v3_groq (steps 24-24c)

A new, versioned run. It reads the frozen benchmarks and never writes them; `frozen_inputs.sha256` lists their hashes,
which were unchanged before and after the run. Full method and results: `docs/evaluation/EVALUATION_2026-10.md`.

| File | Content |
|---|---|
| `corpus_state.json` | Store-consistency check at the time of the run: 70 documents and 1,356 chunks in PostgreSQL, Chroma and BM25; BM25 fingerprint `af2b9ee3…`; CONSISTENT |
| `frozen_inputs.sha256` | SHA-256 of the 20 frozen benchmark files and docs (all unchanged) |
| `retrieval/metrics_{cpu_fp32,product}.json` | The 30 frozen retrieval queries re-run in 4 systems: per query and overall, beside the frozen numbers |
| `retrieval/trace_comparison_{cpu_fp32,product}.json` | Per query and system, whether the pooled ranking equals the frozen one, with the differing chunks |
| `generation/summary.json` | Three-configuration generation results: overall, per mode and the paired subset, with provenance (provider, models, prompt versions and hashes, pacing) |
| `generation/per_query_scores.json` | Per query and configuration: status, scores, model, latency, tokens and evidence chunk IDs (no answer text) |
| `human_review/result.json` | Review of the 15 x 3 sample, imported 2026-11-13 with `import_human_review.py`: per configuration, citation-support and legal-correctness counts and rates (aggregates only, no answer text). The reviewer is an AI chat assistant (not Claude Code), blind to configuration and not human-verified; evidence excerpts were cut at 600 characters |

## Provenance

- **Retrieval:** no LLM. The `cpu_fp32` variant is the frozen configuration: BGE-M3, BM25 k1 1.5 / b 0.75, RRF K 60,
  BGE reranker, on CPU. The `product` variant uses MPS with the reranker in fp16. Both use the current corpus.
- **Generation:** provider Groq. Prompt v3 for B and C; `legal_answer_prompt_v3_llm_only` for A.
  - **Public half** (2026-10-30, step 24): `openai/gpt-oss-20b`, falling back at once to `openai/gpt-oss-120b`;
    the step 23 pacing queue (90 s).
  - **Professional half** (2026-10-31, step 24b): `openai/gpt-oss-120b` only, with no fallback. It waits up to
    45 s for 120b, then `MODEL_BUSY`. The rolling 24-hour daily tracker (step 24c) is on. B ans-q029 was
    re-run on 2026-11-01 (step 24c), the same way.
- **Calls:**
  - Step 24: 73 provider calls (63 OK, 8 HTTP 429 from Groq's daily token limit, 2 HTTP 400 "json_validate_failed"),
    within that step's budget of 110.
  - Steps 24b-24c: 42 calls (40 OK, 2 HTTP 400), within the approved 45.
  - Step 24c, B ans-q029: 1 call (OK), within the approved 2.
- **Full outputs** (answers, citations, evidence text), marked UNREVIEWED, are outside the repository at
  `~/legalai_reviews/eval_runs/2026-10_v3_groq/`:
  - `raw/{A_llm_only,B_dense_rag,C_full_legalai}/`;
  - `human_review/`;
  - the call ledgers;
  - the superseded records, kept and not deleted: `raw_superseded_step24/` (the failed professional records from
    step 24) and `raw_superseded_step24b_busy/` and `raw_superseded_step24c_busy/` (the BUSY records that were
    retried).

## Status

- The retrieval re-run is complete.
- The generation run is **complete**: all 90 cells have a record, and 84 are schema-valid answers.
  - The 6 that are not: 2 schema failures (A ans-q019, B ans-q016), 3 Groq 400s (C ans-q014 from step 24's public
    half; A ans-q017 and ans-q020) and 1 BUSY (C ans-q010, public).
- The review sheet for the sample (15 queries x 3 configurations) was reviewed by an AI chat assistant (not Claude
  Code), blind to configuration and not human-verified, and imported on 2026-11-13 (`human_review/result.json`;
  `docs/evaluation/EVALUATION_2026-10.md`, section 4). A check by a person is still to be done.
