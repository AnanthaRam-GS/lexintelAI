# Legal Gemini Grounded Smoke Trial

## Purpose

Phase 0 Step 0.9B-T1 adds the first controlled Gemini integration path for
citation-grounded LegalAI answers. The task verifies wiring, structured parsing,
citation validation, grounding validation, sanitized error behavior, and smoke-run
artifact generation.

## Why Smoke Trial Before Formal Evaluation

This stage is not an answer-quality benchmark. Four fixed cases are enough to confirm
that the pipeline can run or fail cleanly, but they are not enough to score legal
accuracy, tune prompts, compare providers, or choose a model.

## Provider Configuration

Primary provider: Gemini.

Runtime code reads the configured model from `GEMINI_MODEL` through `Settings`; it does
not hardcode a Gemini model identifier. The API key is read from `GEMINI_API_KEY` and is
never printed or written to artifacts.

The smoke runner disables automatic Ollama fallback so provider behavior remains
attributable to Gemini.

## Fixed Cases

| ID | Mode | Query |
| --- | --- | --- |
| SMOKE-01 | public | Section 302 IPC murder bail before Sessions Court |
| SMOKE-02 | public | After July 2024, which BNS section covers murder? |
| SMOKE-03 | professional | Can anticipatory bail under Section 438 CrPC be sought in a cheating FIR? |
| SMOKE-04 | professional | Section 103 BNS and Section 302 IPC transition issue |

## Call Budget

Maximum normal generation calls: 4.

Maximum optional schema-repair calls: 4.

Absolute live-call maximum: 8.

The current implementation does not perform repair calls. Invalid model output is
recorded as a structured validation failure.

## Frozen Retrieval

Each case uses the existing frozen retrieval stack:

BM25 + BGE-M3 dense retrieval + RRF K=60 + BGE reranker + final top 5.

The smoke runner does not tune retrieval, expand queries, add metadata boosts, or modify
query understanding.

## Grounding Contract

The answer layer consumes `LegalQueryUnderstanding` and `LegalRetrievalResult`, builds a
`GroundedEvidencePacket`, constructs a prompt, and validates generated citations and
claim grounding before returning `LegalAnswerResult`.

Grounding statuses remain:

- `STRUCTURALLY_GROUNDED`
- `PARTIALLY_GROUNDED`
- `UNGROUNDED`
- `INSUFFICIENT_RETRIEVED_AUTHORITY`

These statuses are structural only.

## Citation Validation

Valid citations must reference evidence IDs present in the current retrieval result.
Unknown IDs, orphan citations, duplicate malformed citation objects, invented case
metadata, unsupported court/date fields, and unsupported URLs are rejected.

## Structured Output

Gemini is requested to produce JSON-compatible structured output with:

- `answer`
- `summary`
- `claims`

The nested `answer` must match either `PublicLegalAnswer` or
`ProfessionalLegalBrief`, depending on the fixed case mode.

## Repair Policy

The foundation permits at most one future schema-format repair attempt per case. This
trial does not perform repair calls. Repair must never invent citations, add evidence,
or change legal content to pass grounding.

## Error Handling

The Gemini adapter sanitizes timeout, rate-limit, authorization, provider, empty
response, invalid response, and schema-parse failures. API keys, headers, and SDK
internals are not included in `LegalAnswerResult` or smoke artifacts.

## Live Results

The local configuration provided a Gemini model value, but no Gemini API key was
available. The `--live` smoke runner therefore recorded all four cases as:

`SKIPPED_GEMINI_CREDENTIALS_UNAVAILABLE`

No live Gemini call was made. No Ollama fallback was used.

## HTTP Diagnostic Follow-Up

The later live completion attempt had credentials available and resolved
`GEMINI_MODEL` to `gemini-1.5-flash` from local configuration. The four fixed smoke
cases reached Gemini but failed before answer generation with HTTP 400.

A minimal provider-health diagnostic then isolated two provider/configuration issues
without sending retrieval evidence:

- the adapter initially sent Pydantic `$defs`/`$ref` schema fields that Gemini rejected;
- after schema sanitization, Gemini returned HTTP 404 because the configured model was
  not available for `v1beta generateContent` on the configured account/API path.

Provider model discovery confirmed the configured model was not in the
`generateContent`-capable model list. Do not rerun the four-case grounded smoke trial
until `GEMINI_MODEL` is set to an available model and the minimal health check succeeds.

## Limitations

This trial does not establish that Gemini is legally accurate, better than another
provider, or suitable for production. It does not compare LLM-only and RAG answers and
does not tune prompts from the four smoke cases.

## Next Evaluation Stage

After credentials are available and the live path is exercised, the next step is to
design a frozen grounded-answer evaluation set and a separate LLM-only versus RAG
comparison protocol.
