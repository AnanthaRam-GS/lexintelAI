"""Generic answer adapter for OpenAI-compatible chat-completions providers (step 21).

One adapter, configured by a provider *profile*: base URL, the settings field that holds the API key, model ID,
output limit, timeout, how the answer schema is sent, an optional reasoning-control parameter, and an optional
per-request token ceiling for the request-size guard. Profiles: ``nvidia`` (NVIDIA API catalog), ``ollama``
(local), and ``deepseek`` / ``openrouter`` (defined, disabled until a key is configured).

It returns the same ``LegalAnswerModelResponse`` contract as the Groq and Gemini adapters, so the frozen
generation pipeline, the provider chain (``llm_provider_chain.py``) and the validator are unchanged:

- errors are ``ModelProviderError`` codes prefixed with the profile name (``NVIDIA_TIMEOUT``, ``OLLAMA_RATE_LIMIT``,
  ``NVIDIA_AUTH_ERROR``, ``NVIDIA_PROVIDER_ERROR``, ``NVIDIA_REQUEST_TOO_LARGE``...), so the chain falls back on
  exactly the same provider failures as before;
- a length stop is ``<PROFILE>_OUTPUT_TRUNCATED``, never a partial answer;
- reasoning returned separately (``reasoning_content`` / ``reasoning`` fields, or a leading ``<think>`` block in the
  content) is excluded from the answer; its token count is recorded (the provider's count when reported, otherwise
  an estimate from the excluded text);
- a Markdown code fence around the JSON is removed; the JSON itself is parsed and validated by the frozen pipeline.

Nothing here logs keys, prompts, answers or document text: only status codes, finish reasons and token counts.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from pydantic import BaseModel

from backend.app.services.groq_answer_adapter import (
    groq_payload_schema,
    safe_http_error_body,
    safe_string,
)
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    LegalAnswerModelResponse,
    ModelGenerationMetadata,
    ModelProviderError,
    ModelUnavailableError,
    elapsed_ms,
)
from backend.app.services.llm_pacing import llm_pacer, retry_after_seconds
from backend.app.services.provider_diagnostics import log_provider_http_error, sanitize_provider_message
from backend.app.services.token_budget import estimate_tokens

logger = logging.getLogger("legalai.openai_compatible")

PROFILE_NAMES = ("nvidia", "ollama", "deepseek", "openrouter", "groq_backup")
# How the answer schema reaches the model:
#   json_schema  response_format {"type": "json_schema", ...} (non-strict, as for Groq)
#   json_object  response_format {"type": "json_object"} plus the schema in a system message
#   prompt       no response_format, the schema in a system message only: for a server without constrained decoding
#                (the Homebrew Ollama build's MLX runner answers 501 "structured output is unavailable"). The reply is
#                still parsed and validated strictly by the frozen pipeline; nothing is repaired here.
STRUCTURED_OUTPUT_MODES = ("json_schema", "json_object", "prompt")
SCHEMA_INSTRUCTION = "Respond with one JSON object that conforms to this JSON schema, and nothing else:\n"
THINK_BLOCK = re.compile(r"^\s*<think>(.*?)</think>\s*", re.DOTALL)
CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n?```\s*$", re.DOTALL)


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    base_url: str
    api_key: str
    api_key_env: str
    model: str
    max_output_tokens: int
    timeout_seconds: float
    structured_output: str = "json_schema"
    # Extra request fields that control reasoning, e.g. {"reasoning_effort": "low"}; empty sends none.
    reasoning_options: tuple[tuple[str, Any], ...] = ()
    # Per-request token ceiling (prompt + schema + output) for the request-size guard; None disables it.
    max_request_tokens: int | None = None
    token_estimate_factor: float = 1.51
    # Server-sent events (`stream: true`): the timeout then applies to each read, not to the whole generation.
    stream: bool = False
    # Total time a streamed answer may take (the per-read timeout alone does not bound it).
    stream_deadline_seconds: float = 300.0
    # Per-mode routing (step 22): the model for public answers; empty uses ``model``.
    public_model: str = ""
    # Model-ID prefixes that accept reasoning_options; empty sends them to every model.
    reasoning_models: tuple[str, ...] = ()
    # The account whose rate limits apply (step 23 pacing); empty means the profile name. groq_backup shares Groq's.
    rate_limit_account: str = ""

    def model_for(self, mode: AnswerMode) -> str:
        return self.public_model if mode == AnswerMode.PUBLIC and self.public_model else self.model

    def reasoning_for(self, model: str) -> tuple[tuple[str, Any], ...]:
        return self.reasoning_options if not self.reasoning_models or model.startswith(self.reasoning_models) else ()
    requires_key: bool = True
    enabled: bool = True
    disabled_reason: str = ""

    @property
    def error_prefix(self) -> str:
        return self.name.upper()


def _optional_int(value: Any) -> int | None:
    return int(value) if value not in (None, "", 0) else None


def _reasoning(effort: str) -> tuple[tuple[str, Any], ...]:
    effort = (effort or "").strip()
    return (("reasoning_effort", effort),) if effort else ()


def provider_profile(settings: Any, name: str) -> ProviderProfile:
    """The profile ``name`` built from settings (env vars documented in .env.example and the README)."""
    name = name.strip().lower()
    default_output = settings.legalai_llm_max_output_tokens
    if name == "nvidia":
        return ProviderProfile(
            name="nvidia",
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
            api_key_env="NVIDIA_API_KEY",
            model=settings.nvidia_model,
            max_output_tokens=settings.nvidia_max_output_tokens or default_output,
            timeout_seconds=settings.nvidia_timeout_seconds,
            structured_output=settings.nvidia_structured_output,
            reasoning_options=_reasoning(settings.nvidia_reasoning_effort),
            max_request_tokens=_optional_int(settings.nvidia_max_request_tokens),
            stream=settings.nvidia_stream,
            stream_deadline_seconds=settings.nvidia_stream_deadline_seconds,
        )
    if name == "ollama":
        return ProviderProfile(
            name="ollama",
            base_url=settings.ollama_base_url.rstrip("/") + "/v1",
            api_key="",
            api_key_env="",
            model=settings.ollama_model,
            max_output_tokens=settings.ollama_max_output_tokens or default_output,
            timeout_seconds=settings.ollama_timeout_seconds,
            structured_output=settings.ollama_structured_output,
            reasoning_options=_reasoning(settings.ollama_reasoning_effort),
            # The model's context window (num_ctx): the OpenAI-compatible API cannot raise it per request.
            max_request_tokens=_optional_int(settings.ollama_context_tokens),
            requires_key=False,
        )
    if name == "groq_backup":
        # Step 22: a second Groq model as the fallback. Groq's limits are per model (step 22 headers), so it still
        # answers when GROQ_MODEL is rate-limited or failing. Same key, base URL, ceiling and reasoning effort.
        # GROQ_BACKUP_PUBLIC_MODEL mirrors GROQ_PUBLIC_MODEL routing: each mode falls back to the other model.
        model = settings.groq_backup_model
        return ProviderProfile(
            rate_limit_account="groq",
            public_model=settings.groq_backup_public_model,
            name="groq_backup",
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            api_key_env="GROQ_API_KEY",
            model=model,
            max_output_tokens=default_output,
            timeout_seconds=settings.legalai_llm_timeout_seconds,
            # Groq documents reasoning_effort for its gpt-oss models only (groq_answer_adapter.py).
            reasoning_options=_reasoning(settings.legalai_groq_reasoning_effort),
            reasoning_models=("openai/gpt-oss-",),
            max_request_tokens=_optional_int(settings.legalai_groq_max_request_tokens),
            token_estimate_factor=settings.legalai_groq_token_estimate_factor,
            enabled=bool(model),
            disabled_reason="GROQ_BACKUP_MODEL is not configured",
        )
    if name in {"deepseek", "openrouter"}:
        key = getattr(settings, f"{name}_api_key", "")
        return ProviderProfile(
            name=name,
            base_url=getattr(settings, f"{name}_base_url"),
            api_key=key,
            api_key_env=f"{name.upper()}_API_KEY",
            model=getattr(settings, f"{name}_model"),
            max_output_tokens=default_output,
            timeout_seconds=settings.legalai_llm_timeout_seconds,
            enabled=bool(key),
            disabled_reason=f"{name.upper()}_API_KEY is not configured (profile defined for future use)",
        )
    raise ValueError(f"unknown OpenAI-compatible provider profile: {name}")


class OpenAICompatibleAnswerAdapter:
    """Answer adapter for one OpenAI-compatible provider profile."""

    max_attempts = 3
    backoff_seconds = (1.0, 2.0)

    def __init__(self, settings: Any, profile: str | ProviderProfile, *, temperature: float | None = None, sleep=time.sleep, urlopen=None) -> None:
        self.settings = settings
        self.profile = profile if isinstance(profile, ProviderProfile) else provider_profile(settings, profile)
        self.temperature = settings.legalai_llm_temperature if temperature is None else temperature
        self.sleep = sleep
        self._urlopen = urlopen or urllib.request.urlopen

    @property
    def configured_model_id(self) -> str:
        return self.profile.model

    def rate_limit_key(self, mode: AnswerMode) -> tuple[str, str]:
        """The pacing bucket (step 23): (rate-limit account, model for this mode)."""
        return (self.profile.rate_limit_account or self.profile.name, self.profile.model_for(mode))

    @property
    def max_output_tokens(self) -> int:
        return self.profile.max_output_tokens

    def generate_structured_answer(self, prompt: str, *, schema: type[BaseModel], mode: AnswerMode) -> LegalAnswerModelResponse:
        profile = self.profile
        if not profile.enabled:
            raise ModelUnavailableError(f"Provider profile {profile.name} is disabled: {profile.disabled_reason}.")
        model = profile.model_for(mode)
        if not model or (profile.requires_key and not profile.api_key):
            raise ModelUnavailableError(f"{profile.api_key_env or profile.name} and the {profile.name} model must be configured before live generation.")
        started = perf_counter()
        payload = self.build_payload(prompt, schema, mode)
        retry_reasons: list[str] = []
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
                exc.final_provider_status = status_label(exc)
                if not is_retryable(exc, profile) or attempt >= self.max_attempts:
                    raise
                retry_reasons.append(status_label(exc))
                self.sleep(self.backoff_seconds[min(attempt - 1, len(self.backoff_seconds) - 1)])
        if body is None:
            raise ModelProviderError(f"{profile.error_prefix}_INVALID_RESPONSE", f"{profile.name} returned no API response.")
        usage = body.get("usage") or {}
        choice = (body.get("choices") or [{}])[0]
        finish_reason = choice.get("finish_reason")
        answer_text, reasoning_text = split_reasoning(choice.get("message") or {})
        reported_reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        reasoning_tokens = reported_reasoning if reported_reasoning is not None else (estimate_tokens(reasoning_text) if reasoning_text else None)
        logger.info(
            "openai_compatible_completion provider=%s finish_reason=%s prompt_tokens=%s completion_tokens=%s reasoning_tokens=%s "
            "reasoning_separated=%s max_output_tokens=%s",
            profile.name, finish_reason, usage.get("prompt_tokens"), usage.get("completion_tokens"), reasoning_tokens,
            bool(reasoning_text), profile.max_output_tokens,
        )
        if finish_reason == "length":
            # A cut-off answer is never presented as complete (and is not a provider failure, so no fallback).
            raise ModelProviderError(f"{profile.error_prefix}_OUTPUT_TRUNCATED", f"{profile.name} stopped at the output token limit.")
        if not answer_text:
            raise ModelProviderError(f"{profile.error_prefix}_EMPTY_RESPONSE", f"{profile.name} returned no answer content.")
        metadata = ModelGenerationMetadata(
            provider=profile.name,
            configured_model_id=model,
            actual_model_id=body.get("model") or model,
            temperature=self.temperature,
            response_mode=mode,
            attempt_count=attempt_count,
            retry_count=len(retry_reasons),
            retry_reasons=retry_reasons,
            final_provider_status="SUCCESS",
            finish_reason=finish_reason,
            reasoning_tokens=reasoning_tokens,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
        )
        return LegalAnswerModelResponse(
            raw_response=answer_text,
            parsed_response=None,
            model_metadata=metadata,
            timings={"generation_latency_ms": elapsed_ms(perf_counter, started)},
        )

    def build_payload(self, prompt: str, schema: type[BaseModel], mode: AnswerMode | None = None) -> dict[str, Any]:
        profile = self.profile
        model = profile.model_for(mode) if mode is not None else profile.model
        envelope = groq_payload_schema(schema)
        messages = [{"role": "user", "content": prompt}]
        response_format: dict[str, Any] | None
        if profile.structured_output in {"json_object", "prompt"}:
            # The schema the json_schema mode would carry, as a system message; the prompt itself is unchanged.
            messages.insert(0, {"role": "system", "content": SCHEMA_INSTRUCTION + json.dumps(envelope)})
            response_format = {"type": "json_object"} if profile.structured_output == "json_object" else None
        elif profile.structured_output == "json_schema":
            # Non-strict for the same reason as Groq: source_metadata is an open-ended object.
            response_format = {"type": "json_schema", "json_schema": {"name": "legal_answer", "strict": False, "schema": envelope}}
        else:
            raise ModelUnavailableError(f"Unsupported structured output mode for {profile.name}: {profile.structured_output}.")
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": profile.max_output_tokens,
            **dict(profile.reasoning_for(model)),
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if profile.stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self.profile
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "legalai-backend/1.0"}
        if profile.api_key:
            headers["Authorization"] = f"Bearer {profile.api_key}"
        request = urllib.request.Request(
            profile.base_url.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
        )
        prefix = profile.error_prefix
        key = (profile.rate_limit_account or profile.name, str(payload.get("model") or ""))
        try:
            with self._urlopen(request, timeout=profile.timeout_seconds) as response:
                llm_pacer.observe(key, dict(getattr(response, "headers", None) or {}))
                if payload.get("stream"):
                    return assemble_stream(response, deadline_seconds=profile.stream_deadline_seconds)
                return json.loads(response.read().decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise ModelProviderError(f"{prefix}_TIMEOUT", f"{profile.name} request timed out.") from exc
        except urllib.error.HTTPError as exc:
            headers = dict(getattr(exc, "headers", None) or {})
            llm_pacer.observe(key, headers)
            provider_code, provider_message = sanitized_error(exc, profile.name)
            error = ModelProviderError(
                http_error_code(exc.code, prefix),
                f"{profile.name} request failed with HTTP {exc.code}: {provider_message}",
                http_status=exc.code,
                provider_code=provider_code,
                provider_message=provider_message,
            )
            error.retry_after_seconds = retry_after_seconds(headers) if exc.code == 429 else None
            raise error from exc
        except urllib.error.URLError as exc:
            reason = exc.reason.__class__.__name__ if hasattr(exc, "reason") else "URLError"
            if isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout)):
                raise ModelProviderError(f"{prefix}_TIMEOUT", f"{profile.name} request timed out.") from exc
            raise ModelProviderError(f"{prefix}_PROVIDER_ERROR", f"{profile.name} request failed before a response: {reason}.") from exc
        except json.JSONDecodeError as exc:
            raise ModelProviderError(f"{prefix}_INVALID_RESPONSE", f"{profile.name} returned a non-JSON API response.") from exc


def assemble_stream(response: Any, *, deadline_seconds: float | None = None, clock=time.monotonic) -> dict[str, Any]:
    """Collect an OpenAI-style SSE stream into the non-streaming response shape.

    Each ``data:`` line is a chunk; ``delta.content`` and ``delta.reasoning_content`` / ``delta.reasoning`` are
    concatenated, the last ``finish_reason`` and the ``usage`` chunk (``stream_options.include_usage``) are kept.
    A malformed chunk raises ``json.JSONDecodeError`` (mapped to ``*_INVALID_RESPONSE`` by the caller).

    ``deadline_seconds`` bounds the whole stream: the socket timeout only bounds each read, and a server that sends
    keep-alive lines without tokens would otherwise hold the request open (step 22: NVIDIA held one for 30 minutes).
    """
    content: list[str] = []
    reasoning: list[str] = []
    finish_reason = None
    usage = None
    model = None
    started = clock()
    for raw_line in response:
        if deadline_seconds is not None and clock() - started > deadline_seconds:
            raise TimeoutError("stream deadline exceeded")
        line = raw_line.decode("utf-8").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        model = chunk.get("model") or model
        if chunk.get("usage"):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            content.append(str(delta.get("content") or ""))
            reasoning.append(str(delta.get("reasoning_content") or delta.get("reasoning") or ""))
            finish_reason = choice.get("finish_reason") or finish_reason
    message = {"content": "".join(content), "reasoning_content": "".join(reasoning)}
    return {"model": model, "choices": [{"message": message, "finish_reason": finish_reason}], "usage": usage or {}}


def split_reasoning(message: dict[str, Any]) -> tuple[str, str]:
    """(answer text, reasoning text): separate reasoning never reaches the answer parser."""
    reasoning_parts = [str(message.get(key) or "") for key in ("reasoning_content", "reasoning")]
    text = str(message.get("content") or "")
    think = THINK_BLOCK.match(text)
    if think:
        reasoning_parts.append(think.group(1))
        text = text[think.end():]
    fence = CODE_FENCE.match(text)
    if fence:
        text = fence.group(1)
    return text.strip(), "\n".join(part for part in reasoning_parts if part.strip())


def http_error_code(status: int, prefix: str) -> str:
    if status == 429:
        return f"{prefix}_RATE_LIMIT"
    if status == 413:
        return f"{prefix}_REQUEST_TOO_LARGE"
    if status in {401, 403}:
        return f"{prefix}_AUTH_ERROR"
    if 500 <= status <= 599:
        return f"{prefix}_PROVIDER_ERROR"
    return f"{prefix}_HTTP_ERROR"


def sanitized_error(exc: urllib.error.HTTPError, provider: str) -> tuple[str | None, str]:
    """Provider error type/code and a truncated message; the request (prompt, key) is never included."""
    body = safe_http_error_body(exc)
    provider_code, provider_message = None, f"{provider} request failed with HTTP {exc.code}."
    if body:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            provider_message = sanitize_provider_message(body) or provider_message
        else:
            error = payload.get("error", payload) if isinstance(payload, dict) else {}
            if isinstance(error, dict):
                provider_code = safe_string(error.get("type") or error.get("code"))
                provider_message = sanitize_provider_message(error.get("message") or error.get("detail")) or provider_message
            elif isinstance(error, str):
                provider_message = sanitize_provider_message(error) or provider_message
            if isinstance(payload, dict):
                log_provider_http_error(provider, exc.code, payload)
    return provider_code, provider_message


def status_label(exc: ModelProviderError) -> str:
    return f"HTTP_{exc.http_status}" if exc.http_status is not None else exc.code


def is_retryable(exc: ModelProviderError, profile: ProviderProfile) -> bool:
    # A 429 is left to the provider chain (step 23): fallback or a wait for retry-after, never a quick retry.
    if exc.http_status in {502, 503, 504}:
        return True
    if exc.http_status is not None:
        return False
    return exc.code in {f"{profile.error_prefix}_TIMEOUT", f"{profile.error_prefix}_PROVIDER_ERROR"}
