"""Primary-then-fallback chain for the product answer model.

``LEGALAI_LLM_PROVIDER`` is the primary (``groq`` or ``gemini``);
``LEGALAI_LLM_FALLBACK_PROVIDER`` is the fallback (the other one, or empty to
disable). The chain is an ordinary answer adapter (``generate_structured_answer``),
so the frozen generation pipeline is unchanged.

The fallback is tried only when the primary fails as a *provider*:
- model unavailable (missing key or model name),
- authentication rejected (401/403),
- model not found (404, e.g. a wrong model name),
- rate limit (429),
- timeout,
- upstream 5xx or network error.

It is never tried because of content: an answer that fails schema or citation
validation, an empty or non-JSON body, a request rejected as too large (the
query pipeline already retries that once with reduced context), or any other
4xx. Each adapter keeps its own bounded retries; the chain adds at most one
call to the fallback.

The answering backend is recorded in ``ModelGenerationMetadata``:
``provider`` is the backend that produced the answer, and
``primary_provider``, ``fallback_provider``, ``fallback_used`` and
``fallback_reason`` (the primary's sanitized error code) describe the chain.
When both fail, the fallback's sanitized error is raised, and the query API
maps it to its usual safe error response.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from backend.app.services.legal_answer_generation import (
    LegalAnswerModelResponse,
    ModelProviderError,
    ModelUnavailableError,
)

logger = logging.getLogger("legalai.llm_chain")

PROVIDER_FAILURE_SUFFIXES = ("_AUTH_ERROR", "_RATE_LIMIT", "_TIMEOUT", "_PROVIDER_ERROR")
PROVIDER_FAILURE_HTTP_STATUSES = {401, 403, 404, 408, 429}
UNAVAILABLE_CODE = "MODEL_UNAVAILABLE"


def failure_code(exc: Exception) -> str:
    return UNAVAILABLE_CODE if isinstance(exc, ModelUnavailableError) else getattr(exc, "code", type(exc).__name__)


def is_provider_failure(exc: Exception) -> bool:
    """True when the primary failed as a provider (fall back); False for content or request errors."""
    if isinstance(exc, ModelUnavailableError):
        return True
    if not isinstance(exc, ModelProviderError):
        return False
    if exc.code.endswith("_REQUEST_TOO_LARGE"):
        return False
    if exc.code.endswith(PROVIDER_FAILURE_SUFFIXES):
        return True
    status = getattr(exc, "http_status", None)
    return status in PROVIDER_FAILURE_HTTP_STATUSES or (status is not None and 500 <= status <= 599)


class FallbackAnswerAdapter:
    """Answer adapter that tries ``primary``, then ``fallback`` on a provider failure."""

    def __init__(self, primary: Any, fallback: Any, *, primary_name: str, fallback_name: str) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_name = primary_name
        self.fallback_name = fallback_name

    @property
    def configured_model_id(self) -> str:
        return getattr(self.primary, "configured_model_id", "")

    def generate_structured_answer(self, prompt: str, *, schema: Any, mode: Any) -> LegalAnswerModelResponse:
        started = perf_counter()
        try:
            response = self.primary.generate_structured_answer(prompt, schema=schema, mode=mode)
        except (ModelUnavailableError, ModelProviderError) as exc:
            if not is_provider_failure(exc):
                raise
            reason = failure_code(exc)
            logger.warning("answer provider fallback primary=%s reason=%s fallback=%s", self.primary_name, reason, self.fallback_name)
            try:
                response = self.fallback.generate_structured_answer(prompt, schema=schema, mode=mode)
            except (ModelUnavailableError, ModelProviderError) as fallback_exc:
                logger.error(
                    "answer providers failed primary=%s reason=%s fallback=%s reason=%s",
                    self.primary_name, reason, self.fallback_name, failure_code(fallback_exc),
                )
                raise
            return self._record(response, started, fallback_used=True, reason=reason)
        return self._record(response, started, fallback_used=False, reason=None)

    def _record(self, response: LegalAnswerModelResponse, started: float, *, fallback_used: bool, reason: str | None) -> LegalAnswerModelResponse:
        metadata = response.model_metadata.model_copy(
            update={
                "fallback_used": fallback_used,
                "primary_provider": self.primary_name,
                "fallback_provider": self.fallback_name,
                "fallback_reason": reason,
            }
        )
        timings = {**response.timings, "provider_chain_ms": round((perf_counter() - started) * 1000, 3)}
        return response.model_copy(update={"model_metadata": metadata, "timings": timings})


def build_answer_adapter(settings: Any, factories: dict[str, Any]) -> Any | None:
    """Primary adapter, wrapped in a FallbackAnswerAdapter when a different fallback is configured.

    ``factories`` maps provider names to adapter constructors. Returns None
    when the primary provider is not supported.
    """
    primary_name = settings.legalai_llm_provider.strip().lower()
    if primary_name not in factories:
        return None
    primary = factories[primary_name](settings)
    fallback_name = (settings.legalai_llm_fallback_provider or "").strip().lower()
    if not fallback_name or fallback_name in {"none", primary_name} or fallback_name not in factories:
        return primary
    return FallbackAnswerAdapter(primary, factories[fallback_name](settings), primary_name=primary_name, fallback_name=fallback_name)
