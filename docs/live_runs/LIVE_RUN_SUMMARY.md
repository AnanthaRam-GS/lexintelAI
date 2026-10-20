# Live Run Summary (steps 11, 11b and 11c)

Supervised live runs of the four query endpoints against the reconciled dev database and stores, with real
retrieval models and a live answer provider. This file holds identifiers, codes, scores, timings, counts and
pass/fail only. Full request/response JSON (UNREVIEWED, for legal review) is kept outside the repository:
`~/legalai_reviews/live_runs/20261019T140605Z/` (step 11), `~/legalai_reviews/live_runs/20261020T053615Z/` (step 11b) and `~/legalai_reviews/live_runs/20261020T154442Z/` (step 11c).

## Provider configuration

- Primary: Groq `openai/gpt-oss-120b`; fallback: Gemini `gemini-3.8-flash (gemini-3.6-flash in step 11)` (temporary deviation from the plan;
  see `docs/LLM_PROVIDER_CONFIGURATION.md`).
- Steps 11b and 11c normal runs: fallback disabled (`LEGALAI_LLM_FALLBACK_PROVIDER=none`, Gemini was failing),
  `LEGALAI_LLM_MAX_RETRIES=1`, runs at least 75 s apart. Step 11c: prompt v2 and `LEGALAI_LLM_MAX_OUTPUT_TOKENS=2048`.
- Provider calls (per HTTP request, retries included): step 11 25 of 25; step 11b 6 of 20; step 11c 15 of 25.
- Gemini evaluation (step 11c): FAILED — `gemini-3.8-flash` resolves (models.get, 1 call: "Gemini 3.8 Flash", thinking model, 65,536 output tokens), but R1, P1 and B2 with Gemini as the only provider all failed (two 60 s timeouts and HTTP 503s, 6 calls with retries). Groq stays primary; the deviation note stays in `LLM_PROVIDER_CONFIGURATION.md`.
- Gemini check (step 11b, 1 call): FAILED — the single call timed out after 60 s (sanitized `MODEL_PROVIDER_TIMEOUT`, HTTP 503); in step 11 every Gemini call returned HTTP 503 or 429.
- Live fallback check: **DEFERRED** — Gemini answered none of its 4 generation attempts in step 11c (nor in 11b), so the live check (primary forced to fail, the other provider answers) could not pass and was not run; the step 11c stop rule had also ended the session. Mocked coverage: `test_llm_provider_chain.py` and `test_query_api.py::test_provider_failure_falls_back_and_records_the_backend`.
- Both providers failing: step 11 run E1 (both keys blanked for that process, 0 provider calls) returned a sanitized HTTP 503 with no stack trace. It returned `QUERY_PIPELINE_UNAVAILABLE` because of the frozen-file bug fixed in step 11b; the corrected `MODEL_UNAVAILABLE` mapping is covered by `test_both_providers_unavailable_returns_a_sanitized_error`.

## Per-run results

| Run | Step | Endpoint | HTTP | Backend | Prompt | Finish | Latency (s) | Valid citations | Relative relevance | Raw reranker score | Field counts / sources | Checks |
|---|---|---|---:|---|---|---|---:|---|---|---|---|---|
| P1-public-ipc | 11 | public_text | 200 | groq | v1 | — | 15.0 | 0/3 (METADATA_MISMATCH, UNSUPPORTED_CASE_REFERENCE) | — | — | sections 2, sources 2 (validated citations: 0) | sources validated-only FAIL; no-coverage answer no; jargon none; stack trace none |
| R1-prof-dowry | 11 | professional_text | 200 | groq | v1 | — | 14.6 | 0/0 | 0.000–1.000 | 4.414–5.597 | parties 0, chronology 0, procedural 0, evidence 0, facts 3, precedents 3 | cited_in_answer ok (0 cited); excerpt ≤400 ok; chunk IDs in PG ok; E# refs resolve ok; P# refs resolve ok |
| G1-gemini-check | 11b | professional_text | 503 | — | — | — | 67.7 | — | — | — | — | error `MODEL_PROVIDER_TIMEOUT` |
| P2-public-bns | 11b | public_text | 200 | groq | v1 | — | 11.2 | 0/0 | — | — | sections 1, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |
| P3-public-unanswerable | 11b | public_text | 200 | groq | v1 | — | 11.1 | 0/0 | — | — | sections 2, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |
| P4-public-pdf-fir | 11b | query_public_pdf | 200 | groq | v1 | — | 15.1 | 2/2 | — | — | sections 4, sources 2 (validated citations: 2) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |
| R2-prof-anticipatory-bail | 11b | professional_text | 200 | groq | v1 | — | 14.9 | 1/1 | — | 4.229–4.229 | parties 0, chronology 0, procedural 1, evidence 0, facts 1, precedents 1 | cited_in_answer ok (1 cited); excerpt ≤400 ok; chunk IDs in PG ok; E# refs resolve ok; P# refs resolve ok |
| GE-B2-brief-fir | 11c | query_professional_pdf | 503 | — | — | — | 75.5 | — | — | — | — | error `MODEL_PROVIDER_UNAVAILABLE` |
| GE-P1-public-ipc | 11c | public_text | 503 | — | — | — | 34.6 | — | — | — | — | error `MODEL_PROVIDER_UNAVAILABLE` |
| GE-R1-prof-dowry | 11c | professional_text | 503 | — | — | — | 127.9 | — | — | — | — | error `MODEL_PROVIDER_TIMEOUT` |
| P1-public-ipc | 11c | public_text | 503 | — | — | — | 12.9 | — | — | — | — | error `MODEL_PROVIDER_ERROR` |
| P2-public-bns | 11c | public_text | 200 | groq | v2 | stop | 9.9 | 0/0 | — | — | sections 0, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer yes; jargon none; stack trace none |
| P3-public-unanswerable | 11c | public_text | 200 | groq | v2 | stop | 9.9 | 0/0 | — | — | sections 0, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer yes; jargon none; stack trace none |
| P4-public-pdf-fir | 11c | query_public_pdf | 503 | — | — | — | 13.1 | — | — | — | — | error `MODEL_PROVIDER_ERROR` |
| R1-prof-dowry | 11c | professional_text | 502 | — | — | — | 12.7 | — | — | — | — | error `MODEL_OUTPUT_TRUNCATED` |
| R2-prof-anticipatory-bail | 11c | professional_text | 502 | — | — | — | 12.6 | — | — | — | — | error `MODEL_OUTPUT_TRUNCATED` |

## Latency by stage (ms)

| Run | parse | document_map | query_understanding | dense_retrieval | bm25_retrieval | fusion | rerank | context_assembly | generation | answer_parse_and_citation_validation | total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1-public-ipc | — | — | 4.2 | 224.2 | 6.7 | 0.2 | 7186.4 | 0.6 | 7609.5 | 0.4 | 15033.5 |
| R1-prof-dowry | — | — | 2.2 | 122.7 | 2.2 | 0.2 | 7259.4 | 0.3 | 7222.7 | 0.5 | 14614.8 |
| P2-public-bns | — | — | 3.9 | 105.3 | 4.6 | 0.2 | 7388.6 | 0.5 | 3667.5 | 0.1 | 11171.4 |
| P3-public-unanswerable | — | — | 2.9 | 130.6 | 3.6 | 0.2 | 7328.7 | 0.3 | 3630.9 | 0.2 | 11099.4 |
| P4-public-pdf-fir | 11.1 | — | 2.3 | 122.1 | 2.7 | 0.2 | 7325.7 | 281.1 | 7339.5 | 0.4 | 15086.6 |
| R2-prof-anticipatory-bail | — | — | 1.6 | 121.0 | 1.4 | 0.2 | 7250.9 | 2.1 | 7456.3 | 1.5 | 14838.2 |
| P2-public-bns | — | — | 2.7 | 127.4 | 4.6 | 0.2 | 7307.5 | 1.7 | 2458.8 | 0.6 | 9904.8 |
| P3-public-unanswerable | — | — | 2.3 | 132.4 | 3.5 | 0.2 | 7320.2 | 0.3 | 2439.4 | 0.2 | 9900.4 |

Professional text queries: median total **14.7 s** over 2 runs against the 15 s target (within target). Dominant stage: `generation_ms` (median 7.3 s); generation median 7.3 s, rerank median 7.3 s.

## Other checks

- History: professional runs R1 and R2 each added 1 `query_history` row for the seed lawyer with `generation_backend=groq`; public runs P1–P4 added 0.
- Verifier: `verify_store_consistency.py` CONSISTENT on dev after both sessions; BM25 file and the Chroma HNSW segment files unchanged (sha256 and mtime).
- `chroma_store/chroma.sqlite3` changes hash whenever a process opens the store: only Chroma's internal `acquire_write` table gains a row per process (+7 rows over both sessions); every data table (embeddings, metadata, list metadata, queue, collections, segments) is identical to the pre-run backup.
- Public sources (step 11b): every source in P2–P4 is a validated citation; P2 and P3 had no validated citation, so they returned no sources (step 11 run P1, before the fix, showed 2 sources built from 0 validated citations).
- Pre-run backup: `~/legalai_backups/20261019T140501Z` (verified by restore).
- Brief-map compaction (rendered map tokens, before → after): judgment 695 → 530, fir 630 → 551, chargesheet 960 → 805, petition 884 → 752, unknown 397 → 379; real-path private budgets 1500 / 886 / 863 / 794 / 1500, so all five fit the dev budget. The live briefs (B1–B5) and Q1 were not reached in any session.
- Step 11c no-coverage: P3 (off-corpus trademark question) and P2 (BNS snatching) both returned the prompt v2 no-coverage statement with no provisions or sources. For P2 all three retrieved chunks had negative reranker scores (−2.95 to −4.23) and none mentions snatching, robbery or theft, so the corpus does not cover it.
- Step 11c truncation handling: R1 and R2 stopped at the 2,048-token output limit (`finish_reason=length`; reasoning used 1,219 and 1,272 tokens) and were returned as `502 MODEL_OUTPUT_TRUNCATED` with no history row — no cut-off answer was shown.

## Open findings

- Step 11c stopped under the stop rule after Groq returned HTTP 413 twice (P2 and R2, each then answered or ended by the one retry). R3, B1–B5, Q1 and the fallback check were not run. 15 of 25 calls used.
- Output limit too small for professional answers: with `max_completion_tokens=2048`, gpt-oss-120b spends 1,200–1,300 tokens on reasoning, so R1 and R2 truncated. Public answers fit (812 and 668 tokens). Raising the limit runs into the Groq tier's per-request token limit (prompt + max output), which already caused the 413s.
- P1 and P4 (step 11c) returned Groq HTTP 400, mapped to `503 MODEL_PROVIDER_ERROR`; the provider message was not captured (the run harness records internals only for successful runs). The likely cause is Groq's JSON-schema mode rejecting output cut at the token limit (`json_validate_failed`); not confirmed.
- Citation validation: steps 11 and 11b (prompt v1): 3 of 7 citations valid across 6 answered runs (P1 0/3, R1 no claims, P4 2/2, R2 1/1). Step 11c (prompt v2) has no answered run with claims to compare: P2 and P3 were correct no-coverage answers, and every other run failed before an answer.
- Gemini (`gemini-3.8-flash`): 0 successful generations in 11b and 11c (timeouts, 503, 429).
