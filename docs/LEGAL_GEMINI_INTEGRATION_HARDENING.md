# Legal Gemini Integration Hardening

## Purpose

Phase 0 Step 0.9B-T1R-F1 hardens only generic Gemini provider integration behavior
exposed by the frozen four-case live smoke trial.

This work does not tune legal prompts, weaken citation validation, change retrieval,
change query understanding, change NER, change section ranking, compare models, or run
formal answer evaluation.

## Structured Output Diagnosis

The blocked smoke trial showed one returned Gemini payload that failed
`ProfessionalLegalBrief` validation because nested citation objects omitted required
`claim_id` and `supported_text` fields.

Local schema inspection found that the provider-facing schema for
`ProfessionalLegalBrief.answer.citations.items` had been reduced to an empty object.
The root cause was generic schema conversion: the sanitizer collected only top-level
`$defs`, while Pydantic emits additional nested `$defs` inside embedded answer and
claim schemas. Removing nested `$defs` before resolving their `$ref` references erased
the nested `GroundedCitation` item contract.

The canonical LegalAI schemas were not weakened. `GroundedCitation` still requires:

- `evidence_id`
- `claim_id`
- `supported_text`

## Schema Fix

The Gemini schema conversion now recursively collects `$defs` throughout the full
provider payload schema before sanitization. `$ref` entries are then expanded from that
collected definition map, and unsupported Gemini schema keywords are stripped only after
the referenced schema content has been preserved.

The sanitizer still removes unsupported descriptive or Pydantic-specific constructs,
including `$defs`, `$ref`, `title`, `default`, `examples`, and
`additionalProperties`, but preserves semantic constraints such as `type`,
`properties`, `items`, `required`, and `enum`.

## Provider Retry Policy

Gemini generation now uses bounded transient retries:

- maximum attempts: 3 total, including the initial attempt
- retryable: HTTP 429, HTTP 503, timeout, temporary connection failure before response
- non-retryable: HTTP 400, 401, 403, 404, invalid provider JSON, empty provider content
- backoff: deterministic bounded delay of 0.25 seconds, then 0.5 seconds

Retry metadata is recorded on model metadata:

- `attempt_count`
- `retry_count`
- `retry_reasons`
- `final_provider_status`

## Retry vs Repair

Provider retry handles transient transport or provider availability failures before a
successful model response is available.

Format repair remains separate and is only relevant after a successful model response
fails structured parsing. This phase does not expand the existing one-repair policy and
does not use repair to invent citations, add evidence, alter legal reasoning, or fix
grounding failures.

Schema validation failure from returned model content is not treated as a transient
provider failure and is not retried blindly.

## Live Calls

No grounded smoke case was rerun during F1. No retrieved legal evidence was sent to
Gemini.

No minimal live structured-output provider health check was needed because the root
cause and fix were proven locally with deterministic schema diagnostics and mocked
provider tests.

## Next Step

The generic Gemini integration path is now hardened. The same frozen four-case grounded
smoke trial can be rerun once in a separate task to verify the live behavior under the
new provider schema and retry policy.
