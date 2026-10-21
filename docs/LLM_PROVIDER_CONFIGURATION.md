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
- anything else (including `ollama`) → a controlled `503 MODEL_PROVIDER_UNAVAILABLE` response.

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

### Required environment variables

```
LEGALAI_LLM_PROVIDER=groq          # or "gemini"

GEMINI_API_KEY=                    # required if provider=gemini, or for the frozen benchmark
GEMINI_MODEL=

GROQ_API_KEY=                      # required if provider=groq
GROQ_MODEL=openai/gpt-oss-120b     # never hardcoded in code — always read from this variable
GROQ_BASE_URL=https://api.groq.com/openai/v1   # optional, defaults to the value above

LEGALAI_LLM_FALLBACK_PROVIDER=gemini   # used only on a provider failure of the primary
LEGALAI_QUERY_DEBUG=false              # true returns per-stage timings and the backend in `debug`

LEGALAI_LLM_TEMPERATURE=0.1        # shared by both providers
LEGALAI_LLM_TIMEOUT_SECONDS=60.0   # shared by both providers
```

Both `GEMINI_API_KEY`/`GEMINI_MODEL` and `GROQ_API_KEY`/`GROQ_MODEL` may be
configured at the same time — Gemini's values remain in use by the frozen
benchmark regardless of which provider serves live product traffic. Never
commit real values for any of these; `.env.example` documents placeholders
only.

## Error mapping (both providers)

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

`OllamaAnswerAdapter` remains an explicit, deliberate stub — its
`generate_structured_answer` unconditionally raises. `get_answer_adapter()`
never routes to it; any provider value other than `gemini`/`groq` (Ollama
included) returns a controlled `503 MODEL_PROVIDER_UNAVAILABLE` before an
Ollama adapter would ever be constructed. This did not change with the Groq
integration.
