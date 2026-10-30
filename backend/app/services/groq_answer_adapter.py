"""Groq generative-provider adapter for the live LegalAI product runtime.

This module is intentionally kept separate from
`backend/app/services/legal_answer_generation.py`, which is pinned by the
frozen grounded-answer benchmark's component-hash manifest
(`data/structured/manifests/legal_answer_eval.json`). Adding a new provider
here only *imports* shared contracts and exceptions from that frozen module
(imports do not change its file hash) so the benchmark's Gemini-only
component hashes remain valid.

The adapter implements the same `LegalAnswerModelAdapter` protocol as
`GeminiAnswerAdapter` and returns the exact same `LegalAnswerModelResponse`
contract, so the rest of the (frozen) grounded-answer pipeline in
`legal_answer_generation.generate_legal_answer` requires no changes.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from backend.app.core.config import Settings
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    GroundedLegalClaim,
    LegalAnswerModelResponse,
    ModelGenerationMetadata,
    ModelProviderError,
    ModelUnavailableError,
    elapsed_ms,
)
from backend.app.services.provider_diagnostics import log_provider_http_error

logger = logging.getLogger("legalai.groq")


class GroqAnswerAdapter:
    """Product-runtime answer adapter backed by Groq's OpenAI-compatible API."""

    max_attempts = 3
    backoff_seconds = (0.25, 0.5)

    def __init__(
        self,
        settings: Settings,
        *,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        sleep=time.sleep,
    ) -> None:
        self.settings = settings
        self.temperature = settings.legalai_llm_temperature if temperature is None else temperature
        self.timeout_seconds = settings.legalai_llm_timeout_seconds if timeout_seconds is None else timeout_seconds
        self.sleep = sleep

    @property
    def configured_model_id(self) -> str:
        return self.settings.groq_model

    def model_for(self, mode: AnswerMode) -> str:
        """Per-mode routing (step 22): GROQ_PUBLIC_MODEL serves public answers when set (it has its own rate limits);
        GROQ_MODEL serves professional answers, and public ones too when no public model is set."""
        public_model = (getattr(self.settings, "groq_public_model", "") or "").strip()
        return public_model if mode == AnswerMode.PUBLIC and public_model else self.settings.groq_model

    def generate_structured_answer(self, prompt: str, *, schema: type[BaseModel], mode: AnswerMode) -> LegalAnswerModelResponse:
        model = self.model_for(mode)
        if not self.settings.groq_api_key or not model:
            raise ModelUnavailableError("Groq API key and GROQ_MODEL must be configured before live generation.")
        started = perf_counter()
        retry_reasons: list[str] = []
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_completion_tokens": self.settings.legalai_llm_max_output_tokens,
            **groq_reasoning_options(self.settings, model),
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "legal_answer",
                    # Non-strict: GroundedCitation.source_metadata is an intentionally
                    # open-ended dict[str, Any] (it mirrors whatever fields the
                    # retrieval evidence packet supplies). OpenAI/Groq's strict mode
                    # requires additionalProperties:false on every object subschema,
                    # which cannot be satisfied for a genuinely free-form dict without
                    # closing it to always-empty. Non-strict still guides the model
                    # with the full schema (matching Gemini's own leniency here) and
                    # the response is still validated server-side by parse_model_payload.
                    "strict": False,
                    "schema": groq_payload_schema(schema),
                },
            },
        }
        body = None
        attempt_count = 0
        for attempt in range(1, self.max_attempts + 1):
            attempt_count = attempt
            try:
                body = self._post(payload)
                break
            except ModelProviderError as exc:
                exc.attempt_count = attempt
                exc.retry_count = len(retry_reasons)
                exc.retry_reasons = list(retry_reasons)
                exc.final_provider_status = provider_status(exc)
                if not is_retryable_groq_error(exc) or attempt >= self.max_attempts:
                    raise
                retry_reasons.append(provider_status(exc))
                self.sleep(self.backoff_seconds[min(attempt - 1, len(self.backoff_seconds) - 1)])
        if body is None:
            raise ModelProviderError("GROQ_INVALID_RESPONSE", "Groq returned no API response.")
        usage = body.get("usage", {})
        # Completion diagnostics only (no content): whether the output hit a length limit,
        # and how much of the completion budget went to reasoning tokens.
        choice = (body.get("choices") or [{}])[0]
        finish_reason = choice.get("finish_reason")
        logger.info(
            "groq_completion finish_reason=%s completion_tokens=%s reasoning_tokens=%s max_completion_tokens=%s",
            finish_reason,
            usage.get("completion_tokens"),
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            self.settings.legalai_llm_max_output_tokens,
        )
        if finish_reason == "length":
            # A cut-off answer is never presented as complete (and is not a provider failure, so no fallback).
            raise ModelProviderError("GROQ_OUTPUT_TRUNCATED", "Groq stopped at the output token limit.")
        text = extract_groq_text(body)
        metadata = ModelGenerationMetadata(
            provider="groq",
            configured_model_id=model,
            actual_model_id=body.get("model") or model,
            temperature=self.temperature,
            response_mode=mode,
            fallback_used=False,
            attempt_count=attempt_count,
            retry_count=len(retry_reasons),
            retry_reasons=retry_reasons,
            final_provider_status="SUCCESS",
            finish_reason=finish_reason,
            reasoning_tokens=(usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        return LegalAnswerModelResponse(
            raw_response=text,
            parsed_response=None,
            model_metadata=metadata,
            timings={"generation_latency_ms": elapsed_ms(perf_counter, started)},
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.settings.groq_api_key}",
                # Groq's API is fronted by Cloudflare, which blocks requests that
                # omit a User-Agent as automated/bot traffic (HTTP 403, Cloudflare
                # error 1010) before they ever reach Groq's own auth layer.
                "User-Agent": "legalai-backend/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise ModelProviderError("GROQ_TIMEOUT", "Groq request timed out.") from exc
        except socket.timeout as exc:
            raise ModelProviderError("GROQ_TIMEOUT", "Groq request timed out.") from exc
        except urllib.error.HTTPError as exc:
            diagnostic = sanitized_http_diagnostic(exc)
            raise ModelProviderError(
                http_error_code(exc),
                diagnostic.message,
                http_status=diagnostic.http_status,
                provider_code=diagnostic.provider_code,
                provider_message=diagnostic.provider_message,
            ) from exc
        except urllib.error.URLError as exc:
            raise ModelProviderError("GROQ_PROVIDER_ERROR", sanitized_url_error(exc)) from exc
        except json.JSONDecodeError as exc:
            raise ModelProviderError("GROQ_INVALID_RESPONSE", "Groq returned a non-JSON API response.") from exc

    def _endpoint(self) -> str:
        base = self.settings.groq_base_url.rstrip("/")
        return f"{base}/chat/completions"


# Groq documents reasoning_effort (low | medium | high) for the GPT-OSS models
# (https://console.groq.com/docs/reasoning); it is sent only to those models.
GROQ_REASONING_EFFORT_MODELS = ("openai/gpt-oss-",)
GROQ_REASONING_EFFORTS = {"low", "medium", "high"}


def groq_reasoning_options(settings: Any, model: str | None = None) -> dict[str, str]:
    effort = (getattr(settings, "legalai_groq_reasoning_effort", "") or "").strip().lower()
    if effort in GROQ_REASONING_EFFORTS and str(model or settings.groq_model).startswith(GROQ_REASONING_EFFORT_MODELS):
        return {"reasoning_effort": effort}
    return {}


def extract_groq_text(body: dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if not choices:
        raise ModelProviderError("GROQ_EMPTY_RESPONSE", "Groq returned no choices.")
    message = choices[0].get("message") or {}
    text = str(message.get("content") or "").strip()
    if not text:
        raise ModelProviderError("GROQ_EMPTY_RESPONSE", "Groq returned no text content.")
    return text


def http_error_code(exc: urllib.error.HTTPError) -> str:
    if exc.code == 429:
        return "GROQ_RATE_LIMIT"
    if exc.code == 413:
        # Groq also reports "tokens per minute" tier limits this way when a
        # single request's prompt is larger than the account's TPM allowance
        # (distinct from the request-count 429 rate limit above) - this is not
        # transient and retrying the same prompt will not help.
        return "GROQ_REQUEST_TOO_LARGE"
    if exc.code in {401, 403}:
        return "GROQ_AUTH_ERROR"
    if 500 <= exc.code <= 599:
        return "GROQ_PROVIDER_ERROR"
    return "GROQ_HTTP_ERROR"


@dataclass(frozen=True)
class SanitizedHttpDiagnostic:
    http_status: int
    provider_code: str | None
    provider_message: str
    message: str


def sanitized_http_diagnostic(exc: urllib.error.HTTPError) -> SanitizedHttpDiagnostic:
    provider_code = None
    provider_message = f"Groq request failed with HTTP {exc.code}."
    body = safe_http_error_body(exc)
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            provider_message = body[:300]
        else:
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            provider_code = safe_string(error.get("type") or error.get("code"))
            provider_message = safe_string(error.get("message")) or provider_message
            log_provider_http_error("groq", exc.code, payload)
    return SanitizedHttpDiagnostic(
        http_status=exc.code,
        provider_code=provider_code,
        provider_message=provider_message,
        message=f"Groq request failed with HTTP {exc.code}: {provider_message}",
    )


def safe_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    try:
        return raw.decode("utf-8", errors="replace")
    except AttributeError:
        return str(raw)


def safe_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:500]


def sanitized_url_error(exc: urllib.error.URLError) -> str:
    reason = exc.reason.__class__.__name__ if hasattr(exc, "reason") else "URLError"
    return f"Groq request failed before receiving a response: {reason}."


def provider_status(exc: ModelProviderError) -> str:
    if exc.http_status is not None:
        return f"HTTP_{exc.http_status}"
    return exc.code


def is_retryable_groq_error(exc: ModelProviderError) -> bool:
    if exc.http_status in {429, 503}:
        return True
    if exc.http_status in {400, 401, 403, 404}:
        return False
    if exc.code == "GROQ_TIMEOUT":
        return True
    if exc.code == "GROQ_PROVIDER_ERROR" and exc.http_status is None:
        return True
    return False


def groq_payload_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Build the top-level answer envelope schema, in OpenAI strict-mode form.

    Mirrors the envelope shape built by
    `legal_answer_generation.model_payload_schema` (answer/summary/claims),
    but sanitizes for OpenAI/Groq structured-output strict mode instead of
    Gemini's schema dialect: every object gets `additionalProperties: false`
    and every property is listed in `required` (nullable fields stay
    optional in *value*, not in the required list shape, via their existing
    `anyOf [..., {"type": "null"}]` union from Pydantic).
    """
    return groq_schema(
        {
            "type": "object",
            "properties": {
                "answer": schema.model_json_schema(mode="serialization"),
                "summary": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": GroundedLegalClaim.model_json_schema(mode="serialization"),
                },
            },
            "required": ["answer", "summary", "claims"],
        }
    )


def groq_schema(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = collect_schema_definitions(schema)
    return sanitize_groq_schema(schema, definitions)


def collect_schema_definitions(value: Any) -> dict[str, Any]:
    definitions: dict[str, Any] = {}
    if isinstance(value, list):
        for item in value:
            definitions.update(collect_schema_definitions(item))
    if not isinstance(value, dict):
        return definitions
    nested = value.get("$defs")
    if isinstance(nested, dict):
        definitions.update(nested)
    for item in value.values():
        definitions.update(collect_schema_definitions(item))
    return definitions


def sanitize_groq_schema(value: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [sanitize_groq_schema(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        name = value["$ref"].rsplit("/", 1)[-1]
        return sanitize_groq_schema(definitions.get(name, {}), definitions)
    sanitized: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"$defs", "title", "default", "examples"}:
            continue
        if key == "anyOf":
            sanitized["anyOf"] = sanitize_groq_schema(item, definitions)
            continue
        sanitized[key] = sanitize_groq_schema(item, definitions)
    if sanitized.get("type") == "object" and "properties" in sanitized:
        sanitized["additionalProperties"] = False
        sanitized["required"] = list(sanitized["properties"].keys())
    return sanitized
