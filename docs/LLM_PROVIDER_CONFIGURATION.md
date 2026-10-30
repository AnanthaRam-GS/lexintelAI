# LLM Provider Configuration

LegalAI has two independent, non-interacting uses of a generative LLM. They
must never be confused with each other:

| | Product runtime | Frozen Phase-0 evaluation |
|---|---|---|
| What it is | The live `/query/*` API endpoints used by the frontend | `backend/scripts/run_grounded_answer_eval_generation.py`, the `legalai-answer-eval-generation-v1` benchmark |
| Provider | **Groq** (`openai/gpt-oss-120b`), configurable | **Gemini only** — hardcoded to `GeminiAnswerAdapter`, does not read `LEGALAI_LLM_PROVIDER` |
| Purpose | Answer real user queries | Produce a fixed, comparable eval dataset (currently 59/60 outputs generated) |
| May the provider change? | Yes, via `LEGALAI_LLM_PROVIDER` | No — changing it would invalidate already-generated, human-reviewed outputs |

Changing the product runtime's provider **does not change**:
- retrieval (BM25 lexical index + BGE-M3 dense retrieval, fused via RRF)
- the legal corpus or its embeddings
- the BGE reranker (`BAAI/bge-reranker-v2-m3`)
- where citations come from (always retrieval metadata, never invented)
- InLegalBERT's role (it has none in answer generation today — see below)

Only the final generative call — the one that turns retrieved evidence into a
structured, cited answer — is provider-swappable.

## Product runtime providers

Set via `LEGALAI_LLM_PROVIDER`:

- `gemini` → `GeminiAnswerAdapter` (`backend/app/services/legal_answer_generation.py`)
- `groq` → `GroqAnswerAdapter` (`backend/app/services/groq_answer_adapter.py`)
- `nvidia`, `ollama`, `deepseek`, `openrouter`, `groq_backup` → `OpenAICompatibleAnswerAdapter` with that provider
  profile (`backend/app/services/openai_compatible_adapter.py`, steps 21-22; see "OpenAI-compatible provider
  profiles" below). `deepseek` and `openrouter` are defined but disabled until their key is set.
- anything else → a controlled `503 MODEL_PROVIDER_UNAVAILABLE` response.

Since step 22 the chain is **Groq primary, `groq_backup` fallback**, with prompt v3 and per-mode routing:
professional answers on `openai/gpt-oss-120b`, public answers on `openai/gpt-oss-20b`, and each mode falls back to
the other model, which has its own rate limits. See "Step 22: prompt v3 and the Groq setup".

### Primary and fallback (step 11)

**Groq is the primary and Gemini the fallback**
(`LEGALAI_LLM_PROVIDER=groq`, `LEGALAI_LLM_FALLBACK_PROVIDER=gemini`).

> **Temporary deviation from the plan.** The plan names Gemini as the primary
> provider. Groq is primary for now because Gemini was not reliably
> available: in the step 11 live runs (2026-10-19), every Gemini call returned
> HTTP 503 or 429. Revert to Gemini primary when it is available again. This
> is an owner decision (step 11b).
>
> **Step 11c re-check (2026-10-20): the deviation stays.** `GEMINI_MODEL` is
> now `gemini-3.8-flash`. It resolves (models.get: "Gemini 3.8 Flash", a
> thinking model, 65,536 output tokens), but the 3-call evaluation (R1, P1
> and brief B2, with Gemini as the only provider) failed all three: two
> 60-second timeouts and HTTP 503s, 6 provider calls including one retry
> each. Gemini primary needs all three to return schema-valid JSON, untruncated,
> within about 15 s.
`backend/app/services/llm_provider_chain.py` wraps the two adapters in a
`FallbackAnswerAdapter`. It is an ordinary answer adapter, so the frozen
generation pipeline is unchanged.

The fallback is tried **only when the primary fails as a provider**:
- missing key or model name;
- authentication rejected (401/403);
- model not found (404);
- rate limit (429);
- timeout;
- upstream 5xx or network error.

It is **never tried because of content**:
- an answer that fails schema or citation validation;
- an empty or non-JSON body;
- a request rejected as too large (the query pipeline already retries that once with reduced context);
- any other 4xx.

Each adapter keeps its own bounded retries, and the chain adds at most one
fallback call, never a loop.

The answering backend is recorded in `ModelGenerationMetadata`:
- `provider` is the backend that produced the answer;
- `primary_provider`, `fallback_provider` and `fallback_used` describe the chain;
- `fallback_reason` is the primary's sanitized error code.

That provider is saved as `query_history.generation_backend` and logged on
every query (`query_timings ... provider=... fallback_used=...`). When
`LEGALAI_QUERY_DEBUG=true`, it is also returned in the response `debug`
field. When both providers fail, the fallback's sanitized error is mapped
to the usual safe API error (table below).

`LEGALAI_LLM_FALLBACK_PROVIDER` empty, `none` or equal to the primary disables
the fallback.

`LEGALAI_LLM_MAX_RETRIES` (optional) overrides each adapter's automatic
retries after the first attempt, per process. Unset keeps the adapter
default (3 attempts). Supervised live runs set it to 1 to bound the provider
call count. The Groq adapter logs `finish_reason`, `completion_tokens` and
`reasoning_tokens` for every completion, never content.

### Output limit and truncation (step 11c)

`LEGALAI_LLM_MAX_OUTPUT_TOKENS` (default 2048) is sent to both providers:
Groq `max_completion_tokens` and Gemini `generationConfig.maxOutputTokens`.
For reasoning or thinking models it covers reasoning tokens too.

A response that stops at the limit is never presented as complete:
- Groq `finish_reason=length` raises `GROQ_OUTPUT_TRUNCATED`;
- Gemini `finishReason=MAX_TOKENS` raises `GEMINI_OUTPUT_TRUNCATED`;
- the API returns `502 MODEL_OUTPUT_TRUNCATED`;
- it is a content failure, so the fallback is not tried.

The finish reason and the prompt version are recorded in
`ModelGenerationMetadata`, the `query_timings` log line, the `debug` field and
the history `generation` record.

### Fitting provider limits (step 11d)

**Groq reasoning effort.**
- `LEGALAI_GROQ_REASONING_EFFORT` (`low`, `medium` or `high`; default `low`)
  is sent as `reasoning_effort`, only to `openai/gpt-oss-*` models.
- Groq documents `reasoning_effort` with these three values for
  `openai/gpt-oss-120b` (https://console.groq.com/docs/reasoning, checked
  2026-10-20).
- Reasoning tokens (`usage.completion_tokens_details.reasoning_tokens`) count
  toward `max_completion_tokens`. They are recorded in `reasoning_tokens` and
  logged.

**Groq request-size guard.** `LEGALAI_GROQ_MAX_REQUEST_TOKENS` is set to the
account's per-request limit. Groq's base Developer-plan limit for
`openai/gpt-oss-120b` is 8K tokens per minute
(https://console.groq.com/docs/rate-limits); unset disables the guard. With
Groq as the primary, the pipeline:
1. estimates the request before sending, as `estimate_tokens(prompt +
   schema) × LEGALAI_GROQ_TOKEN_ESTIMATE_FACTOR + LEGALAI_LLM_MAX_OUTPUT_TOKENS`;
2. drops the lowest-ranked trusted evidence items, whole, until it fits, and
   records the count in `evidence_items_trimmed`;
3. never drops private (P#) document evidence, and keeps at least one trusted
   item. If that still does not fit, it returns `413 PDF_CONTEXT_TOO_LARGE`
   for an uploaded document, otherwise `413 MODEL_PROVIDER_REQUEST_TOO_LARGE`.

The factor defaults to 1.51 (step 12 calibration,
`backend/scripts/calibrate_request_size_guard.py`). The calibration rebuilt the
exact prompt of all 10 recorded Groq runs, and each one's evidence matched the
captured chunk IDs. Groq's reported `prompt_tokens` were 1.18-1.43 times
`estimate_tokens(prompt + schema)`, and 1.51 is the worst ratio plus 5%. No
recorded run is underestimated; the closest margin is 329 tokens. The earlier
1.7 (step 11d) came from approximate rebuilds and over-trimmed: P1 and P4 kept
2 of 5 evidence items, and now keep 3. No local tokenizer for gpt-oss
(`o200k_harmony`) is available offline, so a fixed factor is used instead of
exact counting. Details are in `docs/performance/PERFORMANCE_BASELINE.md`.

Step 22 recalibration (27 recorded Groq runs, prompts v1-v3; the step 22 runs record the guard's estimate of the
exact prompt sent): ratios 1.07-1.49, worst 1.4928 (B3, prompt v3, charge-sheet brief). 1.51 never underestimated a
run, but B3's margin was 66 tokens. The default is now **1.57** (worst plus 5%). At 1.57 every case still fits
(zero-call dry run), and the briefs B1-B4 keep one trusted authority beside the document map.

**Gemini thinking and timeout.**
- `LEGALAI_GEMINI_THINKING` (`low`, `medium` or `high`; default `low`) is
  sent as `generationConfig.thinkingConfig.thinkingLevel`.
- Gemini 3.8 Flash supports `low`, `medium` and `high`, and its default is
  `medium` (https://ai.google.dev/gemini-api/docs/generate-content/thinking).
- Thinking tokens count toward `maxOutputTokens`; they are recorded from
  `usageMetadata.thoughtsTokenCount`.
- `LEGALAI_GEMINI_TIMEOUT_SECONDS` (default 90) replaces the shared timeout
  for Gemini.

**Provider error capture.** Non-2xx provider responses log one
`provider_http_error` line with the provider, HTTP status, error type, code
and message (`services/provider_diagnostics.py`):
- only `error.type`, `error.code`/`status` and `error.message` are read;
- the message has key-shaped strings redacted and is truncated to 240
  characters;
- fields such as Groq's `failed_generation`, prompt text, keys and document
  text are never logged.

**Live result (step 11d; details in `docs/live_runs/LIVE_RUN_SUMMARY.md`).**
- Effort `low` cut reasoning from about 1,200-1,300 tokens to 48-124.
- Public answers now fit: P1 and P4 finished (`stop`) at 1,600 and 1,789
  output tokens, with every citation valid.
- Professional answers still truncate. R1's professional JSON exceeded 2,048
  and 2,560 output tokens even at effort `low`, and raising the output limit
  further leaves too little of the 8,000-token request for evidence. R1-R3,
  B1-B5 and Q1 are recorded as blocked by provider capacity. They need a higher
  Groq tier, a working fallback, or a shorter professional output.
- Gemini retest: one 90 s timeout and one 503 ("high demand"). The order stays
  Groq primary, Gemini fallback.

### Prompt v2 (step 11c)

The product uses `legal_answer_prompt_v2.py`. Prompt v1
(`legal_answer_prompt.py`) is unchanged and remains the frozen baseline of the
Phase-0 evaluation.

v2 adds three rules:
- every substantive statement is a structured claim citing evidence IDs;
- case names are copied exactly;
- when no evidence is relevant, the answer starts with "The available sources
  do not cover this question." and gives no general-knowledge legal answer.

The API enforces this:
- an answer without claims is rejected (`502 MODEL_OUTPUT_MISSING_CITATIONS`),
  unless it is such a no-coverage answer;
- a public no-coverage answer carries no provisions, sources or legal steps.

The model and the citation validator see case names without the Indian Kanoon
date suffix (`services/case_names.py`); stored metadata and the UI keep the
full title. The validator itself is unchanged.

### Frozen-file change: `legal_answer_generation.py` re-pinned (2026-10-20)

`model_unavailable_result()` referenced the undefined names `http_status`,
`provider_code` and `provider_message`. It raised `NameError` whenever the
answer model was unavailable (missing key or model), so the API returned
`QUERY_PIPELINE_UNAVAILABLE` instead of `MODEL_UNAVAILABLE`. It now records
`None` for them, because no provider was called.

The prompt, schemas, parsing and citation validation are unchanged.

| | SHA-256 |
|---|---|
| old | `4c8de1d0eed16f11a1aa60d37a65a90e7931429971a52c4df6f31ff469f3d131` |
| new | `7760d55c056ee414649d9df11631ebe4ea94ae7fab3393686b20724f2a67cb8e` |

The change is recorded in
`data/structured/manifests/legal_answer_eval.json` (`component_hashes` and
`component_hash_changes`).

**Step 11c**, recorded the same way:
- `legal_answer_generation.py` re-pinned again, `7760d55c…` → `c547baf0…`,
  for the Gemini output limit, truncation detection and the new
  `finish_reason`/`prompt_version` metadata fields;
- `legal_answer_prompt_v2.py` pinned at `9cdc948c…`;
- the v1 prompt pin (`5a300bf8…`) is unchanged.

**Step 11d**: `legal_answer_generation.py` re-pinned `c547baf0…` →
`44a90e1d…`, for the Gemini thinking level and timeout, thought-token and
error logging, and the `reasoning_tokens` and `evidence_items_trimmed`
metadata fields. The already-generated eval outputs
(`legal_answer_eval_outputs.json`) keep the hashes recorded at their run.

`GroqAnswerAdapter` lives in its own module, separate from
`legal_answer_generation.py`, specifically so that adding it does not change
that file's contents or SHA-256 hash — `legal_answer_generation.py` is one of
five source files pinned by
`data/structured/manifests/legal_answer_eval.json`'s `component_hashes`,
which the frozen benchmark's `verify_component_hashes_or_die` checks before
every live-generation run. The adapter only *imports* shared types and
exceptions from that file (imports do not affect a file's hash) and returns
the exact same `LegalAnswerModelResponse` contract, so the rest of the
(frozen) grounded-answer pipeline requires no changes to support it.

### OpenAI-compatible provider profiles (step 21)

`OpenAICompatibleAnswerAdapter` serves any provider with an OpenAI-style `POST <base>/chat/completions`. A
*profile* sets the base URL, the API-key variable, the model ID, the output limit, the timeout, how the answer
schema is sent, an optional reasoning-control field and an optional per-request token ceiling:

| Profile | Base URL | Key | Model | Structured output | Reasoning | Size guard |
|---|---|---|---|---|---|---|
| `nvidia` | `NVIDIA_BASE_URL` (`https://integrate.api.nvidia.com/v1`) | `NVIDIA_API_KEY` | `NVIDIA_MODEL` | `NVIDIA_STRUCTURED_OUTPUT` (default `json_schema`) | `NVIDIA_REASONING_EFFORT` (empty: none) | `NVIDIA_MAX_REQUEST_TOKENS` (empty: off) |
| `ollama` | `OLLAMA_BASE_URL` + `/v1` | none | `OLLAMA_MODEL` | `OLLAMA_STRUCTURED_OUTPUT` (default `prompt`) | `OLLAMA_REASONING_EFFORT` | `OLLAMA_CONTEXT_TOKENS` (the model's `num_ctx`) |
| `deepseek` | `DEEPSEEK_BASE_URL` | `DEEPSEEK_API_KEY` | `DEEPSEEK_MODEL` | `json_schema` | none | off |
| `openrouter` | `OPENROUTER_BASE_URL` | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` | `json_schema` | none | off |

Model IDs have no default in code; `.env.example` carries the verified ones. Structured-output modes:
`json_schema` sends `response_format` with the answer schema (non-strict, as for Groq); `json_object` sends
`{"type": "json_object"}` and the schema as a system message; `prompt` sends the schema as a system message and no
`response_format`, for servers without constrained decoding. In every mode the reply is parsed strictly and
validated by the unchanged frozen pipeline, and the prompt (v2) itself is unchanged.

It keeps the chain's contract:
- errors are `<PROFILE>_*` codes (`NVIDIA_TIMEOUT`, `OLLAMA_PROVIDER_ERROR`, `NVIDIA_RATE_LIMIT`,
  `NVIDIA_AUTH_ERROR`, `*_REQUEST_TOO_LARGE`…), so the fallback rules above apply unchanged;
- `finish_reason: "length"` is `<PROFILE>_OUTPUT_TRUNCATED` (502 `MODEL_OUTPUT_TRUNCATED`, no fallback);
- reasoning returned in `reasoning_content` / `reasoning` or a leading `<think>` block is removed from the answer, and
  its token count is recorded in `reasoning_tokens` (the provider's count, or an estimate of the removed text);
- the backend, prompt version, finish reason and token counts are recorded as for Groq;
- the request-size guard applies the profile's ceiling (`max_request_tokens`) with the Groq estimate factor;
- retries (429/502/503/504, timeouts, network errors) follow `LEGALAI_LLM_MAX_RETRIES`;
- only status codes, finish reasons and token counts are logged: never keys, prompts, answers or document text.

Mocked tests: `backend/scripts/tests/test_openai_compatible_adapter.py`.

### Provider bake-off (step 21, 2026-10-29)

Each provider ran the same five cases through the real product pipeline (dev backend, prompt v2,
`LEGALAI_LLM_MAX_RETRIES=1`, fallback off): P1 (public, cheating), P3 (public, trademark: must be no-coverage),
R1 (professional, 304B dowry death), B2 (FIR brief), B3 (charge-sheet brief). Budget: at most 40 provider calls,
10 per provider; **33 used** (Groq 6, Gemini 10, NVIDIA 7, Ollama 10, including retests, probes and the fallback
check). Full outputs (UNREVIEWED) are outside the repository, under
`~/legalai_reviews/live_runs/20261029T_step21_bakeoff/`.

**Configurations**
- **Groq** `openai/gpt-oss-120b`: output 2,048, reasoning low, ceiling 8,000, dev context budget (7,200 input).
  Retest: `/models` lists it (131,072 context, 65,536 max completion); the chat headers still say
  `x-ratelimit-limit-tokens: 8000` and `x-ratelimit-limit-requests: 1000`, so the per-request (per-minute) token
  limit is still 8,000.
- **Gemini** `gemini-3.8-flash` (models.get: 1,048,576 input, 65,536 output, thinking): output 8,192, thinking low,
  90 s timeout.
- **NVIDIA** `deepseek-ai/deepseek-v4.1-flash`, verified in NVIDIA's own `GET /v1/models` listing (85 models;
  `nvidia/deepseek-v4.1-flash` is not listed) and on its build.nvidia.com page (`base_url
  https://integrate.api.nvidia.com/v1`). Output 16,384, timeout 120 s then 300 s, large context budget
  (40,000 input).
- **Ollama** 0.40.11 (Homebrew) on an Apple M5 with 24 GB RAM: `gemma4:12b` (12.4B, nvfp4, MLX runner, 7.7 GB),
  wrapped as `legalai-gemma4-12b` with `num_ctx 16384`. That leaves about 16 GB for macOS, BGE-M3 and the reranker;
  `qwen3.8` (18 GB) would not. Output 4,096, thinking off (`reasoning_effort: none`), 300 s timeout, budget sized to
  16k (16,384 input, 4,096 reserved output). `json_schema` got HTTP 501 "structured output is unavailable" on all
  five cases: the Homebrew build ships no xgrammar library for the MLX runner. The cases were re-run in `prompt`
  mode.

**Results** (latency is total / provider call, in seconds, excluding the harness's rate-limit spacing; tokens are
prompt / output / reasoning)

| Provider | Case | HTTP | Calls | Schema | Finish | Citations valid | No-coverage | Latency | Tokens | Trimmed | Brief map |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Groq | P1 | 200 | 1 | yes | stop | 3/3 | | 11.1 / 5.6 | 4,133 / 2,000 / 24 | 2 | |
| Groq | P3 | 200 | 1 | yes | stop | 0/0 | **yes** | 6.9 / 2.0 | 4,873 / 177 / 33 | 2 | |
| Groq | R1 | 502 truncated | 1 | no | length | – | | – / 6.2 | – / 2,048 / 38 | 2 | |
| Groq | B2 | 502 truncated | 1 | no | length | – | | – / 5.4 | – / 2,048 / 67 | 3 | |
| Groq | B3 | 413 `PDF_CONTEXT_TOO_LARGE` | 0 | – | – | – | | – | – | – | |
| Gemini | P1 | 503 timeout | 2 (503, timeout) | no | – | – | | – / 112.6 | – | – | |
| Gemini | P3 | 503 unavailable | 2 (timeout, 503) | no | – | – | no answer | – / 109.7 | – | – | |
| Gemini | R1 | 503 timeout | 2 (503, timeout) | no | – | – | | – / 95.8 | – | – | |
| Gemini | B2 | 503 unavailable | 2 (timeout, 503) | no | – | – | | – / 94.9 | – | – | |
| Gemini | B3 | 413 `PDF_CONTEXT_TOO_LARGE` (dev budget) | 0 | – | – | – | | – | – | – | |
| NVIDIA | P1 | 503 timeout | 4 (all timeouts: 120 s ×2, 300 s ×2) | no | – | – | | – / 844.9 | – | – | |
| NVIDIA | P3, R1, B2, B3 | not run: the endpoint did not answer a 64-token "Reply with OK" probe within 60 s, twice (16:42 and 18:33 UTC); the model listing itself answered in 0.7 s | | | | | | | | | |
| Ollama | P1 | 200 | 1 (+1 501) | yes | stop | 0/3 `METADATA_MISMATCH` | | 104.7 / 99.0 | 6,226 / 1,995 / 0 | 0 | |
| Ollama | P3 | 200 | 1 (+1 501) | yes | stop | 0/0 | **yes** | 60.2 / 58.0 | 7,984 / 298 / 0 | 0 | |
| Ollama | R1 | 502 truncated | 1 (+1 501) | no | length | – | | – / 260.3 | – / 4,096 / 0 | 0 | |
| Ollama | B2 | 200 | 1 (+1 501) | yes | stop | 0/3 `METADATA_MISMATCH` | | 273.9 / 264.3 | 9,591 / 3,501 / 0 | 0 | 2/2 parties, 2/2 events, 2/2 stages, 3/3 evidence: match |
| Ollama | B3 | 200 | 1 (+1 501) | yes | stop | 0/3 `METADATA_MISMATCH` | | 254.1 / 241.8 | 10,538 / 3,230 / 0 | 0 | 3/3, 6/6, 5/5, 4/4: match |

The brief's map-derived fields (parties, chronology, procedural stages, evidence categories) come from the local
document map, not the model, so they match the expected files whenever a brief is produced.

**Decision: the chain is unchanged (Groq primary, Gemini fallback).** The primary had to pass R1, B2 and B3
untruncated with valid citations; no provider did:
- Groq passes the public cases (P1 3/3 citations, P3 correct no-coverage, about 6 s calls) but truncates
  professional answers at 2,048 output tokens, and its 8,000-token per-request limit cannot hold the charge-sheet
  brief (B3) at all. More output is not possible inside 8,000 tokens without cutting the evidence further.
- Gemini failed every call (503 "high demand" and 90 s timeouts), as in step 11c.
- NVIDIA lists the model but never answered, not even a 64-token probe.
- Ollama is schema-valid on 4 of 5 but cites no evidence validly (every citation's source metadata mismatches the
  evidence), truncates R1 at 4,096, and takes 1–4.5 minutes per answer. It is not configured as a fallback.

The live fallback check (2 calls) showed the chain switches correctly but no fallback produced an answer: with Groq
forced to fail, Gemini timed out (90 s); with Gemini forced to fail, Groq answered HTTP 200 but stopped at the 2,048
output limit on P1 (2,048 tokens, 34 reasoning), so the product returned 502 `MODEL_OUTPUT_TRUNCATED`. P1 used
2,000 tokens in the bake-off: Groq's limit is marginal even for public answers.

### Step 22: prompt v3 and the Groq setup (2026-10-30)

Budget: at most 50 provider calls; **45 used** (Groq 39, NVIDIA 4, Gemini 2). Full outputs (UNREVIEWED):
`~/legalai_reviews/live_runs/20261030T_step22/`. The per-run table is in `docs/live_runs/LIVE_RUN_SUMMARY.md`.

**NVIDIA retry: failed.**
- The adapter now streams when `NVIDIA_STREAM=true` (SSE, `stream_options.include_usage`).
- DeepSeek V4.1 Flash got two 64-token streamed calls, 18 minutes apart. Both timed out with no first byte
  (120 s, 150 s).
- `GET /v1/models` (85 models) answered in 0.2 s. Three alternatives appear in both that listing and NVIDIA's
  chat-completions reference: `openai/gpt-oss-20b`, `nvidia/nemotron-3-super-120b-a12b` and `z-ai/glm-5.3-flash`.
- The first, `openai/gpt-oss-20b`, kept the stream open without a token for 1,797 s. That was the second consecutive
  timeout, so the stop rule ended NVIDIA; the other two were not called.
- The stream reader now has a total deadline (`NVIDIA_STREAM_DEADLINE_SECONDS`, default 300). Before, a server that
  sends keep-alives without tokens could hold a request indefinitely, because the socket timeout only bounds each
  read.

**Groq per-model limits** (one 16-token call each):

| Model | Headers | Docs |
|---|---|---|
| `openai/gpt-oss-120b` | 8,000 tokens per minute, 1,000 requests per day | 30 RPM, 200K TPD |
| `openai/gpt-oss-20b` | 8,000 tokens per minute, 1,000 requests per day | 30 RPM, 200K TPD |
| `qwen/qwen3.8-27b` | 8,000 tokens per minute, 1,000 requests per day | 30 RPM, 200K TPD |

The limits are separate per model: each model reported 999 daily requests remaining minutes after the others' calls.

**Prompt v3** (`legal_answer_prompt_v3.py`, pinned in the eval manifest; v1 and v2 unchanged):
- It is v2 plus `<LENGTH_RULES>`, with the same output schemas.
- **Length targets:** about 900 output tokens for public answers and 1,200 for professional ones.
- **Shape:** each point once; summaries of at most two sentences; at most 3 entries per list of text; at most 4
  claims; uncertainties stay objects.
- **Citations:** citations live in the claims only (the answer object's own `citations` list is never read);
  `source_metadata` carries only `case_name` and `source_url`; no P# citations.
- **Briefs:** the private document map is not restated.
- **Iteration:**
  - The first version, with length targets only, was ignored: R1, R3 and all five briefs stopped at 2,048 tokens.
  - The second version fixed the length, but the "short entries" wording turned `uncertainties` into strings
    (`MODEL_OUTPUT_VALIDATION_FAILED`).
  - The third ran the live runs. The measured answer shape, characters per field with no text, showed the
    duplicated citation list.
  - After the runs, one wording change: the rule names "the PRIVATE_DOCUMENT_MAP block" without its opening `<`,
    because the literal tag in every prompt read as a document map that was not there (a question-mode test, and
    the fake E2E provider's detector). The pinned hash is of this version.

**Budget.** `.env.example` and the zero-call dry run use:
- output 2,048 (the reserve equals the limit) and ceiling 8,000;
- product input 8,000, margin 300, trusted evidence 4,000, private PDF 1,500;
- factor 1.57 (above).

The private-context builders now signal when the private context does not fit (`PrivateContextDoesNotFit`). The
lowest-ranked trusted item is then dropped first. While more than one trusted item is left, the document map or
the question-focused P# excerpts are never cut; with one item left, the map gets 413 as before and the excerpts
shrink. This removed B3's `413 PDF_CONTEXT_TOO_LARGE`.

**Routing.**
- `gpt-oss-20b` (separate limits) qualified for public answers:
  - P1 had 3/3 valid citations with the final v3 (0/3 with the first v3, `METADATA_MISMATCH`);
  - P3 was a correct no-coverage answer.
- `qwen/qwen3.8-27b` failed P1 (0/4, first v3) and was not retried.
- Public answers go to 20b (`GROQ_PUBLIC_MODEL`), professional answers stay on 120b, and the routed model is
  recorded in `backend.model` and in the query-history `generation`.

**Fallback.**
- Gemini again answered 503 "high demand" with the new key, so the fallback is `groq_backup`: a second Groq model
  with its own limits, mirrored per mode (`GROQ_BACKUP_MODEL`=20b for professional, `GROQ_BACKUP_PUBLIC_MODEL`=120b
  for public).
- The live check (Groq forced to fail) **passed**: `groq_backup`/20b answered P1 with HTTP 200, finish `stop`, 3/3
  valid citations, `fallback_used: true`.

**Results** (gpt-oss-120b, final v3; the per-run table is in the live-run summary):
- 13 of 13 succeeded untruncated: P1-P4, R1-R3, B1-B5 and Q1.
- Citations valid: 41 of 41.
- P2 and P3 were correct no-coverage answers.
- Every brief's map fields matched the expected files.
- Output tokens: public 119-1,258, professional 882-1,879. All are under the 2,048 cap, but the v3 targets were
  exceeded in 10 runs: P1 and P4 above ~900, and R1, R3, B1-B5 and Q1 above ~1,200. The model follows the shape
  rules, not the numbers.

**Sustained check: 1 of 5 public queries succeeded** in 22 s. The second got HTTP 429 from 20b (3,920 tokens left
in the minute, against a request of about 7,000) and again on the adapter's retry. After 2 consecutive limit errors
the run's stop rule refused all further Groq calls, including the 120b fallback. Each model's 8,000 tokens per
minute holds about one answer, so a burst of 5 in 2 minutes cannot succeed on this tier.

### Required environment variables

```
LEGALAI_LLM_PROVIDER=groq          # or gemini | nvidia | ollama | deepseek | openrouter | groq_backup
LEGALAI_PROMPT_VERSION=v3          # or v2 (v1 is the frozen evaluation baseline)

GEMINI_API_KEY=                    # required if provider=gemini, or for the frozen benchmark
GEMINI_MODEL=

GROQ_API_KEY=                      # required if provider=groq
GROQ_MODEL=openai/gpt-oss-120b     # never hardcoded in code — always read from this variable
GROQ_PUBLIC_MODEL=openai/gpt-oss-20b          # public answers (empty: GROQ_MODEL)
GROQ_BACKUP_MODEL=openai/gpt-oss-20b          # groq_backup fallback for professional answers
GROQ_BACKUP_PUBLIC_MODEL=openai/gpt-oss-120b  # groq_backup fallback for public answers (empty: GROQ_BACKUP_MODEL)
GROQ_BASE_URL=https://api.groq.com/openai/v1   # optional, defaults to the value above

LEGALAI_LLM_FALLBACK_PROVIDER=groq_backup   # used only on a provider failure of the primary
LEGALAI_QUERY_DEBUG=false              # true returns per-stage timings and the backend in `debug`

LEGALAI_LLM_TEMPERATURE=0.1        # shared by all providers
LEGALAI_LLM_TIMEOUT_SECONDS=60.0   # Groq, and the deepseek/openrouter profiles

NVIDIA_API_KEY=                    # required if provider=nvidia
NVIDIA_MODEL=deepseek-ai/deepseek-v4.1-flash
NVIDIA_MAX_OUTPUT_TOKENS=16384     # plus NVIDIA_BASE_URL, _TIMEOUT_SECONDS, _STRUCTURED_OUTPUT,
                                   # _REASONING_EFFORT, _MAX_REQUEST_TOKENS, _STREAM, _STREAM_DEADLINE_SECONDS
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=legalai-gemma4-12b    # plus OLLAMA_CONTEXT_TOKENS, _MAX_OUTPUT_TOKENS, _TIMEOUT_SECONDS,
                                   # _STRUCTURED_OUTPUT, _REASONING_EFFORT
DEEPSEEK_API_KEY= / DEEPSEEK_MODEL= / OPENROUTER_API_KEY= / OPENROUTER_MODEL=   # disabled while empty
```

Each provider's context budget (`LEGALAI_PRODUCT_MAX_INPUT_TOKENS`, `LEGALAI_LLM_RESERVED_OUTPUT_TOKENS`,
`PRIVATE_PDF_INPUT_BUDGET_TOKENS`…) must match its capacity. In step 21 the Groq-sized budget refused the
charge-sheet brief (413 `PDF_CONTEXT_TOO_LARGE`) before any provider call; since step 22 the lowest-ranked trusted
evidence is trimmed first, so the brief fits (see "Step 22").

Both `GEMINI_API_KEY`/`GEMINI_MODEL` and `GROQ_API_KEY`/`GROQ_MODEL` may be
configured at the same time — Gemini's values remain in use by the frozen
benchmark regardless of which provider serves live product traffic. Never
commit real values for any of these; `.env.example` documents placeholders
only.

## Error mapping (all providers)

Provider failures are normalized to the same set of API error codes
regardless of which provider produced them, so the frontend does not need to
know or care which one is active:

| Condition | Internal code (e.g.) | API code | HTTP status |
|---|---|---|---|
| Missing/empty key or model | — (`ModelUnavailableError`) | `MODEL_UNAVAILABLE` | 503 |
| 401 / 403 | `GEMINI_AUTH_ERROR` / `GROQ_AUTH_ERROR` | `MODEL_PROVIDER_AUTH_ERROR` | 503 |
| 429 | `GEMINI_RATE_LIMIT` / `GROQ_RATE_LIMIT` | `MODEL_PROVIDER_QUOTA_EXCEEDED` | 429 |
| Timeout | `GEMINI_TIMEOUT` / `GROQ_TIMEOUT` | `MODEL_PROVIDER_TIMEOUT` | 503 |
| Upstream 5xx / network error | `GEMINI_PROVIDER_ERROR` / `GROQ_PROVIDER_ERROR` | `MODEL_PROVIDER_UNAVAILABLE` | 503 |
| Bad/empty body, invalid JSON | `GEMINI_*` / `GROQ_*` (other) | `MODEL_PROVIDER_ERROR` | 503 |
| Structured output fails validation | `MODEL_OUTPUT_VALIDATION_FAILED` | `MODEL_OUTPUT_VALIDATION_FAILED` | 502 |

The OpenAI-compatible profiles use the same mapping with their own prefix (`NVIDIA_*`, `OLLAMA_*`, `DEEPSEEK_*`,
`OPENROUTER_*`, `GROQ_BACKUP_*`). Until step 22 the failure metadata of an unanswered request recorded
`provider: "gemini"` whatever the provider. `legal_answer_generation.py` now records the provider that failed, read
from the error code prefix (`failed_provider_name`; re-pinned with the reason in the eval manifest), and
`test_prompt_v3.py` covers it.

None of these responses ever include an API key, an `Authorization` header,
the raw upstream response body, or a stack trace. The end user only ever
sees "LegalAI"-branded copy (e.g. "Answer service unavailable", "Usage limit
reached") — the provider name is never surfaced outside this document and
the backend's own internal exception messages.

Retries are bounded (at most 3 attempts, short backoff) and only apply to
429/503/timeout — 400/401/403/404 fail immediately without retrying.

## InLegalBERT

No fine-tuned InLegalBERT checkpoint exists in this repository
(`models/` contains only a `.gitkeep`). It has never been, and is not now,
part of answer generation for either provider — it is optional NLP tooling
(`LEGAL_NER_ENABLED=false` by default) unrelated to the product's generative
LLM choice.

## Ollama

Since step 21, `LEGALAI_LLM_PROVIDER=ollama` (or the fallback) is served by the `ollama` profile of
`OpenAICompatibleAnswerAdapter` through Ollama's OpenAI-compatible API (`<OLLAMA_BASE_URL>/v1`, no key). The old
`OllamaAnswerAdapter` stub in the frozen `legal_answer_generation.py` is unchanged and no longer routed to.

The OpenAI-compatible API cannot set the context window per request, and Ollama's default is small, so create a
model with a fixed `num_ctx` and give the same value to the size guard:

```
ollama pull gemma4:12b
printf 'FROM gemma4:12b\nPARAMETER num_ctx 16384\n' > Modelfile
ollama create legalai-gemma4-12b -f Modelfile
ollama ps          # CONTEXT shows 16384 once loaded
```

```
OLLAMA_MODEL=legalai-gemma4-12b
OLLAMA_CONTEXT_TOKENS=16384
OLLAMA_MAX_OUTPUT_TOKENS=4096
OLLAMA_TIMEOUT_SECONDS=300
OLLAMA_STRUCTURED_OUTPUT=prompt    # json_schema needs a build with constrained decoding for the model's runner
OLLAMA_REASONING_EFFORT=none       # gemma4 thinks by default; none turns it off
```

Size the context budget to the 16k window (the step 21 run used `LEGALAI_PRODUCT_MAX_INPUT_TOKENS=16384`,
`LEGALAI_LLM_RESERVED_OUTPUT_TOKENS=4096`, `LEGALAI_LLM_CONTEXT_SAFETY_MARGIN_TOKENS=1000`,
`TRUSTED_EVIDENCE_INPUT_BUDGET_TOKENS=4000`, `PRIVATE_PDF_INPUT_BUDGET_TOKENS=4500`). On a 24 GB Mac a 12B model
leaves room for BGE-M3 and the reranker; larger models do not. Its answers are schema-valid but cite no evidence
validly, so it is for local experiments only (see the bake-off).
