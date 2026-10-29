# Live Run Summary (steps 11 to 11d, and the step 21 provider bake-off)

Supervised live runs of the four query endpoints against the reconciled dev database and stores, with real
retrieval models and a live answer provider. This file holds identifiers, codes, scores, timings, counts and
pass/fail only. Full request/response JSON (UNREVIEWED, for legal review) is kept outside the repository: `~/legalai_reviews/live_runs/20261019T140605Z/` (step 11), `~/legalai_reviews/live_runs/20261020T053615Z/` (step 11b), `~/legalai_reviews/live_runs/20261020T154442Z/` (step 11c), `~/legalai_reviews/live_runs/20261020T162033Z/` (step 11d).

## Provider configuration

- Primary: Groq `openai/gpt-oss-120b`; fallback: Gemini `gemini-3.8-flash (gemini-3.6-flash in step 11)`.
- `LEGALAI_LLM_PROVIDER=groq` (primary), `LEGALAI_LLM_FALLBACK_PROVIDER=gemini` configured; live runs used `none` because Gemini is unavailable.
- `LEGALAI_GROQ_REASONING_EFFORT=low` (Groq `reasoning_effort`, low/medium/high for gpt-oss: https://console.groq.com/docs/reasoning).
- `LEGALAI_LLM_MAX_OUTPUT_TOKENS=2048`, `LEGALAI_GROQ_MAX_REQUEST_TOKENS=8000` (Developer-tier 8K TPM: https://console.groq.com/docs/rate-limits), `LEGALAI_GROQ_TOKEN_ESTIMATE_FACTOR=1.7`.
- `LEGALAI_GEMINI_THINKING=low` (`thinkingConfig.thinkingLevel`: https://ai.google.dev/gemini-api/docs/generate-content/thinking), `LEGALAI_GEMINI_TIMEOUT_SECONDS=90`.
- `LEGALAI_LLM_MAX_RETRIES=1` for live runs; runs at least 75 s apart.
- Provider calls (per HTTP request, retries included): step 11 25 of 25; step 11b 6 of 20; step 11c 15 of 25; step 11d 6 of 25 (2 Gemini, 4 Groq).
- Gemini: Step 11d retest (2 calls, single attempt, thinking low, 90 s timeout): R1 timed out at 90 s; P1 returned HTTP 503 with the captured provider message `UNAVAILABLE`: "This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later." Step 11c: 0 of 6 generation attempts succeeded (timeouts, 503). Provider order stays **Groq primary, Gemini fallback** (temporary deviation; see `docs/LLM_PROVIDER_CONFIGURATION.md`).
- Live fallback check: **DEFERRED**: Gemini has not answered a generation call in steps 11b, 11c or 11d, so the live check (primary forced to fail, fallback answers) cannot pass. Mocked coverage: `test_llm_provider_chain.py` and `test_query_api.py::test_provider_failure_falls_back_and_records_the_backend`.
- Both providers failing: Step 11 run E1 (both keys blanked, 0 provider calls) returned a sanitized HTTP 503 with no stack trace; the corrected `MODEL_UNAVAILABLE` mapping is covered by `test_both_providers_unavailable_returns_a_sanitized_error`.

## Step 11d calibration

- C1: R1 (professional), effort low, max output 2,048: `finish_reason=length`, reasoning 55 tokens, completion 2,048; size guard trimmed 2 evidence items (3 kept). Returned `502 MODEL_OUTPUT_TRUNCATED`.
- C2: R1, effort low, max output 2,560: `finish_reason=length`, reasoning 48 tokens, completion 2,560; size guard trimmed 3 items (2 kept). Returned `502 MODEL_OUTPUT_TRUNCATED`.
- Low effort cut reasoning from 1,219–1,272 tokens (step 11c, default effort) to about 50, so reasoning is no longer the problem: the professional answer JSON itself is longer than 2,560 tokens. A larger output limit leaves less room for evidence under the 8,000-token per-request ceiling (C2 already had to drop to 2 items), so the professional runs cannot fit on this tier.

## Per-run results

Effort column: Groq reasoning effort and max output tokens ("default" = not sent, before step 11d). Tokens: reasoning / completion.

| Run | Step | Endpoint | HTTP | Backend | Prompt | Effort, max out | Finish | Latency (s) | Tokens | Trimmed | Valid citations | Relative relevance | Raw reranker score | Field counts / sources | Checks |
|---|---|---|---:|---|---|---|---|---:|---|---:|---|---|---|---|---|
| P1-public-ipc | 11 | public_text | 200 | groq | v1 | default | — | 15.0 | — | — | 0/3 (METADATA_MISMATCH, UNSUPPORTED_CASE_REFERENCE) | — | — | sections 2, sources 2 (validated citations: 0) | sources validated-only FAIL; no-coverage answer no; jargon none; stack trace none |
| R1-prof-dowry | 11 | professional_text | 200 | groq | v1 | default | — | 14.6 | — | — | 0/0 | 0.000–1.000 | 4.414–5.597 | parties 0, chronology 0, procedural 0, evidence 0, facts 3, precedents 3 | cited_in_answer ok (0 cited); excerpt ≤400 ok; chunk IDs in PG ok; E# refs resolve ok; P# refs resolve ok |
| G1-gemini-check | 11b | professional_text | 503 | — | — | default | — | 67.7 | — | — | — | — | — | — | error `MODEL_PROVIDER_TIMEOUT` |
| P2-public-bns | 11b | public_text | 200 | groq | v1 | default | — | 11.2 | — | — | 0/0 | — | — | sections 1, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |
| P3-public-unanswerable | 11b | public_text | 200 | groq | v1 | default | — | 11.1 | — | — | 0/0 | — | — | sections 2, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |
| P4-public-pdf-fir | 11b | query_public_pdf | 200 | groq | v1 | default | — | 15.1 | — | — | 2/2 | — | — | sections 4, sources 2 (validated citations: 2) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |
| R2-prof-anticipatory-bail | 11b | professional_text | 200 | groq | v1 | default | — | 14.9 | — | — | 1/1 | — | 4.229–4.229 | parties 0, chronology 0, procedural 1, evidence 0, facts 1, precedents 1 | cited_in_answer ok (1 cited); excerpt ≤400 ok; chunk IDs in PG ok; E# refs resolve ok; P# refs resolve ok |
| GE-B2-brief-fir | 11c | query_professional_pdf | 503 | — | — | default | — | 75.5 | — | — | — | — | — | — | error `MODEL_PROVIDER_UNAVAILABLE` |
| GE-P1-public-ipc | 11c | public_text | 503 | — | — | default | — | 34.6 | — | — | — | — | — | — | error `MODEL_PROVIDER_UNAVAILABLE` |
| GE-R1-prof-dowry | 11c | professional_text | 503 | — | — | default | — | 127.9 | — | — | — | — | — | — | error `MODEL_PROVIDER_TIMEOUT` |
| P1-public-ipc | 11c | public_text | 503 | — | — | default | — | 12.9 | — | — | — | — | — | — | error `MODEL_PROVIDER_ERROR` |
| P2-public-bns | 11c | public_text | 200 | groq | v2 | default | stop | 9.9 | — | — | 0/0 | — | — | sections 0, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer yes; jargon none; stack trace none |
| P3-public-unanswerable | 11c | public_text | 200 | groq | v2 | default | stop | 9.9 | — | — | 0/0 | — | — | sections 0, sources 0 (validated citations: 0) | sources validated-only ok; no-coverage answer yes; jargon none; stack trace none |
| P4-public-pdf-fir | 11c | query_public_pdf | 503 | — | — | default | — | 13.1 | — | — | — | — | — | — | error `MODEL_PROVIDER_ERROR` |
| R1-prof-dowry | 11c | professional_text | 502 | — | — | default | — | 12.7 | — | — | — | — | — | — | error `MODEL_OUTPUT_TRUNCATED` |
| R2-prof-anticipatory-bail | 11c | professional_text | 502 | — | — | default | — | 12.6 | — | — | — | — | — | — | error `MODEL_OUTPUT_TRUNCATED` |
| C1-R1-prof-dowry | 11d | professional_text | 502 | groq | — | low, 2,048 | length | 12.9 | 55 / 2,048 | 2 | — | — | — | — | error `MODEL_OUTPUT_TRUNCATED` |
| C2-R1-prof-dowry | 11d | professional_text | 502 | groq | — | low, 2,560 | length | 13.7 | 48 / 2,560 | 3 | — | — | — | — | error `MODEL_OUTPUT_TRUNCATED` |
| GR-P1-public-ipc | 11d | public_text | 503 | gemini | — | gemini thinking low | — | 10.5 | — | — | — | — | — | — | error `MODEL_PROVIDER_UNAVAILABLE` (provider=gemini status=503 type=UNAVAILABLE code=503) |
| GR-R1-prof-dowry | 11d | professional_text | 503 | gemini | — | gemini thinking low | — | 97.6 | — | — | — | — | — | — | error `MODEL_PROVIDER_TIMEOUT` |
| P1-public-ipc | 11d | public_text | 200 | groq | v2 | low, 2,048 | stop | 11.4 | 65 / 1,600 | 3 | 2/2 | — | — | sections 4, sources 2 (validated citations: 2) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |
| P4-public-pdf-fir | 11d | query_public_pdf | 200 | groq | v2 | low, 2,048 | stop | 12.9 | 124 / 1,789 | 3 | 3/3 | — | — | sections 3, sources 2 (validated citations: 3) | sources validated-only ok; no-coverage answer no; jargon none; stack trace none |

## Citation validation: prompt v2 against v1

Prompt v2: **5 of 5** citations valid across the answered runs with claims (step 11d P1 2/2, P4 3/3; no validation issues), plus 2 correct no-coverage answers (step 11c P2, P3). Prompt v1 baseline (steps 11 and 11b): 3 of 7.

## Groq HTTP 400 (step 11c)

Step 11c P1 and P4 returned Groq HTTP 400 before error capture existed. In step 11d both reran under the same 2,048 output limit with effort low and the size guard on, and both answered (`finish_reason=stop`), so no 400 recurred and **no provider message was captured**. The cause is therefore not confirmed. The most likely explanation is that at default effort, reasoning (about 1,200 tokens) plus the public answer (1,600–1,800 tokens) exceeded 2,048, and Groq's JSON-schema mode rejected the cut-off output. `provider_http_error` logging (status, type, code, sanitized message) is now in place for any recurrence.

## Not run

| Item | Status |
|---|---|
| R1 (professional, dowry) | blocked: provider capacity (calibration C1/C2 truncated at 2,048 and 2,560 output tokens) |
| R2 (professional, anticipatory bail) | blocked: provider capacity (same professional schema as R1; truncated at 2,048 in step 11c) |
| R3 (professional) | blocked: provider capacity (not run; same professional schema) |
| B1–B5 (PDF briefs) | blocked: provider capacity (professional schema plus private document map; less room than R1) |
| Q1 (PDF question, professional) | blocked: provider capacity (professional schema) |
| Live fallback check | deferred: Gemini unavailable (503 high demand, 90 s timeouts) |

## Latency by stage (ms)

| Run | Step | parse | document_map | query_understanding | dense_retrieval | bm25_retrieval | fusion | rerank | context_assembly | generation | answer_parse_and_citation_validation | total |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1-public-ipc | 11 | — | — | 4.2 | 224.2 | 6.7 | 0.2 | 7186.4 | 0.6 | 7609.5 | 0.4 | 15033.5 |
| R1-prof-dowry | 11 | — | — | 2.2 | 122.7 | 2.2 | 0.2 | 7259.4 | 0.3 | 7222.7 | 0.5 | 14614.8 |
| P2-public-bns | 11b | — | — | 3.9 | 105.3 | 4.6 | 0.2 | 7388.6 | 0.5 | 3667.5 | 0.1 | 11171.4 |
| P3-public-unanswerable | 11b | — | — | 2.9 | 130.6 | 3.6 | 0.2 | 7328.7 | 0.3 | 3630.9 | 0.2 | 11099.4 |
| P4-public-pdf-fir | 11b | 11.1 | — | 2.3 | 122.1 | 2.7 | 0.2 | 7325.7 | 281.1 | 7339.5 | 0.4 | 15086.6 |
| R2-prof-anticipatory-bail | 11b | — | — | 1.6 | 121.0 | 1.4 | 0.2 | 7250.9 | 2.1 | 7456.3 | 1.5 | 14838.2 |
| P2-public-bns | 11c | — | — | 2.7 | 127.4 | 4.6 | 0.2 | 7307.5 | 1.7 | 2458.8 | 0.6 | 9904.8 |
| P3-public-unanswerable | 11c | — | — | 2.3 | 132.4 | 3.5 | 0.2 | 7320.2 | 0.3 | 2439.4 | 0.2 | 9900.4 |
| P1-public-ipc | 11d | — | — | 3.8 | 92.5 | 6.6 | 0.2 | 7311.9 | 5.5 | 3939.5 | 0.6 | 11362.0 |
| P4-public-pdf-fir | 11d | 10.5 | — | 2.7 | 115.7 | 2.7 | 0.2 | 7323.0 | 954.3 | 4437.4 | 0.5 | 12848.1 |

Professional text queries (answered runs, steps 11 and 11b): median total **14.7 s** over 2 runs against the 15 s target (within target). Dominant stage: `generation_ms` (median 7.3 s); generation median 7.3 s, rerank median 7.3 s.

Step 11d public runs: P1-public-ipc total 11.4 s (rerank 7.3 s, generation 3.9 s); P4-public-pdf-fir total 12.8 s (rerank 7.3 s, generation 4.4 s).

## Other checks

- Verifier: `verify_store_consistency.py` CONSISTENT on dev after step 11d; BM25 file and Chroma HNSW segment files unchanged (sha256 and mtime); dev table counts identical to after step 11c.
- `chroma_store/chroma.sqlite3`: only Chroma's internal `acquire_write` table changes (one row per process; 81 → 95 since the pre-run backup); all 20 other tables are identical to the backup.
- History: step 11d P1 and P4 (public) added 0 rows; truncated runs C1 and C2 added 0 rows (no cut-off answer stored or shown). Earlier: R1 and R2 (step 11/11b) each added 1 row with `generation_backend=groq`.
- Public sources: every source in step 11d P1 and P4 is a validated citation (2 sources each; P4's 3 valid citations come from 2 judgments).
- Size guard: P1 actual request 3,241 prompt + 2,048 max output = 5,289 tokens; P4 3,287 + 2,048 = 5,335, against an 8,000 ceiling. Estimate factor 1.7 is conservative for these prompts (both trimmed 3 of 5 items); it was calibrated from step 11c ratios of 1.38–1.65.
- Pre-run backup: `~/legalai_backups/20261019T140501Z` (verified by restore).
- Brief-map compaction (rendered map tokens, before → after): judgment 695 → 530, fir 630 → 551, chargesheet 960 → 805, petition 884 → 752, unknown 397 → 379.
- Step 11c no-coverage: P2 (BNS snatching) and P3 (off-corpus trademark) returned the prompt v2 no-coverage statement with no provisions or sources; P2's three chunks all had negative reranker scores (−2.95 to −4.23).

## Step 21 provider bake-off (2026-10-29)

Groq, Gemini, NVIDIA (`deepseek-ai/deepseek-v4.1-flash`) and local Ollama (`legalai-gemma4-12b`, gemma4:12b with
a 16k context) ran P1, P3, R1, B2 (FIR brief) and B3 (charge-sheet brief) through the product pipeline, prompt v2,
retries 1, fallback off. Outputs (UNREVIEWED): `~/legalai_reviews/live_runs/20261029T_step21_bakeoff/`. Provider
calls: 33 of 40 (Groq 6, Gemini 10, NVIDIA 7, Ollama 10). The full table and configurations are in
`docs/LLM_PROVIDER_CONFIGURATION.md` ("Provider bake-off (step 21)").

- Groq: P1 200 (3/3 citations), P3 correct no-coverage; R1 and B2 `502 MODEL_OUTPUT_TRUNCATED` at 2,048; B3
  `413 PDF_CONTEXT_TOO_LARGE` (0 calls). Headers still `x-ratelimit-limit-tokens: 8000`.
- Gemini: 8 generation calls, 0 answers (503 high demand, 90 s timeouts).
- NVIDIA: the model listing answers, generation never does (P1 4 timeouts, two 64-token probes timed out at 60 s).
- Ollama: schema-valid on P1, P3, B2 and B3, P3 correct no-coverage, but 0/3 valid citations on every answer
  (`METADATA_MISMATCH`); R1 truncated at 4,096; 1–4.5 minutes per answer. `json_schema` first returned HTTP 501
  (the Homebrew build's MLX runner has no constrained decoding); the reported runs use `prompt` mode.
- Decision: no provider passes R1, B2 and B3; the chain stays Groq primary, Gemini fallback.
- Live fallback check (2 calls): **FAILED**. The chain switched in both directions, with the fallback recorded in
  the logs, but neither fallback answered: Gemini timed out; Groq returned HTTP 200 truncated at 2,048 on P1
  (502 `MODEL_OUTPUT_TRUNCATED`).

## Open items

- Step 21: no configured provider answers professional questions or briefs. Options needing an owner decision: a
  higher Groq tier, a paid key for an OpenAI-compatible provider (the `deepseek`/`openrouter` profiles are ready), a
  retry of NVIDIA when its endpoint responds, or a shorter professional output schema.

- Professional answers (R1–R3, B1–B5, Q1) are blocked on the Groq Developer tier: the professional JSON exceeds 2,560 output tokens even at low reasoning effort, and prompt plus output must fit in 8,000 tokens. Options: a higher Groq tier, a working Gemini fallback, or a shorter professional output schema (a product decision; not changed here).
- Gemini `gemini-3.8-flash` has not completed a generation in steps 11b–11d (503 high demand, timeouts). The live fallback check stays deferred.
- The Groq HTTP 400 from step 11c was not reproduced, so its provider message is still uncaptured (see above).
- The size-guard estimate factor (1.7) over-trims public prompts by about one to two evidence items; recalibrate once more runs are available.
