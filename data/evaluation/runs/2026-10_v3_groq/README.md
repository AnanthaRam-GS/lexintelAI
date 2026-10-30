# Evaluation run 2026-10_v3_groq (step 24)

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

## Provenance

- **Retrieval:** no LLM. The `cpu_fp32` variant is the frozen configuration: BGE-M3, BM25 k1 1.5 / b 0.75, RRF K 60,
  BGE reranker, on CPU. The `product` variant uses MPS with the reranker in fp16. Both use the current corpus.
- **Generation:** provider Groq.
  - Professional answers on `openai/gpt-oss-120b`, public answers on `openai/gpt-oss-20b`, with the `groq_backup`
    fallback (each mode falls back to the other model).
  - Prompt v3 for B and C; `legal_answer_prompt_v3_llm_only` for A.
  - The step 23 pacing queue (90 s) and the step 24 professional policy (wait up to 45 s for 120b).
- **Calls:** 73 provider calls (63 OK, 8 HTTP 429 from Groq's daily token limit, 2 HTTP 400 "json_validate_failed"),
  within the step's budget of 110.
- **Full outputs** (answers, citations, evidence text), marked UNREVIEWED, are outside the repository:
  `~/legalai_reviews/eval_runs/2026-10_v3_groq/` (`raw/{A_llm_only,B_dense_rag,C_full_legalai}/`, `human_review/`,
  the call ledger).

## Status

- The retrieval re-run is complete.
- The generation run is **complete for the 15 public queries** and **incomplete for the 15 professional queries**.
  Groq's daily token limit (200K tokens per model per day) was exhausted mid-run, so 25 records were refused as
  `MODEL_BUSY`. Professional answers also fell back to gpt-oss-20b, which failed the professional schema 10 times.
- To complete it, delete the failed professional records and re-run after the daily limit resets (about 42 calls):
  `run_three_config_eval.py --raw-dir ~/legalai_reviews/eval_runs/2026-10_v3_groq/raw` (it skips existing records).
