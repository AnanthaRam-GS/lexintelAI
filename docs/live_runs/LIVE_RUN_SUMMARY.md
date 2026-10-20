# Live Run Summary (steps 11 and 11b)

Supervised live runs of the four query endpoints against the reconciled dev database and stores, with real
retrieval models and a live answer provider. This file holds identifiers, codes, scores, timings, counts and
pass/fail only. Full request/response JSON (UNREVIEWED, for legal review) is kept outside the repository:
`~/legalai_reviews/live_runs/20261019T140605Z/` (step 11) and `~/legalai_reviews/live_runs/20261020T053615Z/` (step 11b).

## Provider configuration

- Primary: Groq `openai/gpt-oss-120b`; fallback: Gemini `gemini-3.8-flash (gemini-3.6-flash in step 11)` (temporary deviation from the plan;
  see `docs/LLM_PROVIDER_CONFIGURATION.md`).
- Step 11b normal runs: fallback disabled (`LEGALAI_LLM_FALLBACK_PROVIDER=none`), `LEGALAI_LLM_MAX_RETRIES=1`,
  runs at least 75 s apart.
- Provider calls: step 11 used 25 of 25; step 11b used 6 of 20 (counted per HTTP request, retries included).
- Gemini check (step 11b, 1 call): FAILED — the single call timed out after 60 s (sanitized `MODEL_PROVIDER_TIMEOUT`, HTTP 503); in step 11 every Gemini call returned HTTP 503 or 429.
- Live fallback check: **DEFERRED** — Gemini did not answer the check call, so the live check (Groq forced to fail, Gemini answers) was not run. The chain is covered by mocked tests: `test_llm_provider_chain.py` (fallback on each provider-failure class, never on content, both-fail raises the fallback's sanitized error) and `test_query_api.py::test_provider_failure_falls_back_and_records_the_backend`.
- Both providers failing: step 11 run E1 (both keys blanked for that process, 0 provider calls) returned a sanitized HTTP 503 with no stack trace. It returned `QUERY_PIPELINE_UNAVAILABLE` because of the frozen-file bug fixed in step 11b; the corrected `MODEL_UNAVAILABLE` mapping is covered by `test_both_providers_unavailable_returns_a_sanitized_error`.

## Per-run results

| Run | Step | Endpoint | HTTP | Backend | Latency (s) | Valid citations | Relative relevance | Raw reranker score | Field counts / sources | Checks |
|---|---|---|---:|---|---:|---|---|---|---|---|
| P1-public-ipc | 11 | public_text | 200 | groq | 15.0 | 0/3 (METADATA_MISMATCH, UNSUPPORTED_CASE_REFERENCE) | — | — | sections 2, sources 2 (validated citations: 0) | sources validated-only FAIL; jargon none; stack trace none |
| R1-prof-dowry | 11 | professional_text | 200 | groq | 14.6 | 0/0 | 0.000–1.000 | 4.414–5.597 | parties 0, chronology 0, procedural 0, evidence 0, facts 3, precedents 3 | cited_in_answer ok (0 cited); excerpt ≤400 ok; chunk IDs in PG ok; E# refs resolve ok; P# refs resolve ok |
| G1-gemini-check | 11b | professional_text | 503 | — | 67.7 | — | — | — | — | error `MODEL_PROVIDER_TIMEOUT` |
| P2-public-bns | 11b | public_text | 200 | groq | 11.2 | 0/0 | — | — | sections 1, sources 0 (validated citations: 0) | sources validated-only ok; jargon none; stack trace none |
| P3-public-unanswerable | 11b | public_text | 200 | groq | 11.1 | 0/0 | — | — | sections 2, sources 0 (validated citations: 0) | sources validated-only ok; jargon none; stack trace none |
| P4-public-pdf-fir | 11b | query_public_pdf | 200 | groq | 15.1 | 2/2 | — | — | sections 4, sources 2 (validated citations: 2) | sources validated-only ok; jargon none; stack trace none |
| R2-prof-anticipatory-bail | 11b | professional_text | 200 | groq | 14.9 | 1/1 | — | 4.229–4.229 | parties 0, chronology 0, procedural 1, evidence 0, facts 1, precedents 1 | cited_in_answer ok (1 cited); excerpt ≤400 ok; chunk IDs in PG ok; E# refs resolve ok; P# refs resolve ok |

## Latency by stage (ms)

| Run | parse | document_map | query_understanding | dense_retrieval | bm25_retrieval | fusion | rerank | context_assembly | generation | answer_parse_and_citation_validation | total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1-public-ipc | — | — | 4.2 | 224.2 | 6.7 | 0.2 | 7186.4 | 0.6 | 7609.5 | 0.4 | 15033.5 |
| R1-prof-dowry | — | — | 2.2 | 122.7 | 2.2 | 0.2 | 7259.4 | 0.3 | 7222.7 | 0.5 | 14614.8 |
| P2-public-bns | — | — | 3.9 | 105.3 | 4.6 | 0.2 | 7388.6 | 0.5 | 3667.5 | 0.1 | 11171.4 |
| P3-public-unanswerable | — | — | 2.9 | 130.6 | 3.6 | 0.2 | 7328.7 | 0.3 | 3630.9 | 0.2 | 11099.4 |
| P4-public-pdf-fir | 11.1 | — | 2.3 | 122.1 | 2.7 | 0.2 | 7325.7 | 281.1 | 7339.5 | 0.4 | 15086.6 |
| R2-prof-anticipatory-bail | — | — | 1.6 | 121.0 | 1.4 | 0.2 | 7250.9 | 2.1 | 7456.3 | 1.5 | 14838.2 |

Professional text queries: median total **14.7 s** over 2 runs against the 15 s target (within target). Dominant stage: `generation_ms` (median 7.3 s); generation median 7.3 s, rerank median 7.3 s.

## Other checks

- History: professional runs R1 and R2 each added 1 `query_history` row for the seed lawyer with `generation_backend=groq`; public runs P1–P4 added 0.
- Verifier: `verify_store_consistency.py` CONSISTENT on dev after both sessions; BM25 file and the Chroma HNSW segment files unchanged (sha256 and mtime).
- `chroma_store/chroma.sqlite3` changes hash whenever a process opens the store: only Chroma's internal `acquire_write` table gains a row per process (+7 rows over both sessions); every data table (embeddings, metadata, list metadata, queue, collections, segments) is identical to the pre-run backup.
- Public sources (step 11b): every source in P2–P4 is a validated citation; P2 and P3 had no validated citation, so they returned no sources (step 11 run P1, before the fix, showed 2 sources built from 0 validated citations).
- Brief-map compaction (rendered map tokens, before → after): judgment 695 → 530, fir 630 → 551, chargesheet 960 → 805, petition 884 → 752, unknown 397 → 379; real-path private budgets 1500 / 886 / 863 / 794 / 1500, so all five now fit the dev budget. The live brief runs (B1–B5) and Q1 were not reached.
- Pre-run backup: `~/legalai_backups/20261019T140501Z` (verified by restore).

## Open findings

- Groq per-request limit: R2's first request got HTTP 413 (request too large for the account's tokens-per-minute tier), even with runs 75 s apart; the pipeline's one reduced-context retry answered it with 1 precedent. The step 11b stop rule ended the session there, so R3, B1–B5 and Q1 were not run.
- Output cap: Groq returns at most 3,072 completion tokens (no `max_tokens` is sent). R2 ended with `finish_reason=length` at 3,072 tokens, 1,383 of them reasoning; its fields still end on complete sentences and its JSON validated. Step 11 runs P1 and R1 also reported exactly 3,072.
- Citation root cause (P1): the retrieved case names carry the Indian Kanoon date suffix (" ... on <decision date>"); the model wrote the name without it, and the frozen validator requires an exact match (METADATA_MISMATCH + UNSUPPORTED_CASE_REFERENCE). Evidence IDs were correct.
- Citation root cause (R1): the model returned an empty `claims` array and cited E# inline in prose, so no structured citation exists. Not truncation: R1's JSON validated and its fields end on complete sentences.
- P3 (unanswerable): the model answered from general knowledge instead of stating that the retrieved authority does not cover the question; no source validated, so the UI shows its 'could not verify a source' note.
