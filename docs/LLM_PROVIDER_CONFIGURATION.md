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
- anything else (including `ollama`) → a controlled `503 MODEL_PROVIDER_UNAVAILABLE` response. There is **no silent fallback** between providers.

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
