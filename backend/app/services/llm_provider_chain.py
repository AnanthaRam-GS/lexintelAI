"""Primary-then-fallback chain for the product answer model, with rate-limit pacing (step 23).

``LEGALAI_LLM_PROVIDER`` is the primary; ``LEGALAI_LLM_FALLBACK_PROVIDER`` the fallback (empty or ``none`` disables
it). The chain is an ordinary answer adapter (``generate_structured_answer``), so the frozen generation pipeline is
unchanged.

The fallback is tried only when the primary fails as a *provider*:
- model unavailable (missing key or model name),
- authentication rejected (401/403),
- model not found (404, e.g. a wrong model name),
- rate limit (429),
- timeout,
- upstream 5xx or network error.

It is never tried because of content: an answer that fails schema or citation validation, an empty or non-JSON
body, a request rejected as too large (the query pipeline already retries that once with reduced context), or any
other 4xx.

Pacing (step 23, ``services/llm_pacing.py``), for providers with known rate limits (Groq):

1. The request waits in the FIFO queue until its primary or its fallback model has capacity for the estimated
   tokens (prompt estimate x ``LEGALAI_GROQ_TOKEN_ESTIMATE_FACTOR`` + the output limit). The primary is preferred;
   when only the fallback has capacity, the fallback answers (``fallback_reason=PRIMARY_AT_CAPACITY``). Waiting
   longer than ``LEGALAI_LLM_QUEUE_MAX_WAIT_SECONDS`` raises ``GenerationQueueTimeout`` (``MODEL_BUSY`` with
   ``Retry-After``).
2. The generation slot (``rate_limit.generation_slots``) is taken only after that grant, so a queued request holds
   no slot, and the model inference lock is never held here.
3. On a 429 the model's bucket is blocked for the provider's ``retry-after`` (or its token reset). If the other
   model has capacity now, it answers at once; otherwise the request waits for the retry time (when that is within
   its queue deadline) and retries once. Never sooner than the provider says.
4. ``timings`` records ``queue_wait_ms``, ``rate_limit_wait_ms`` and ``rate_limit_retries``; ``retry_reasons`` gains
   ``RATE_LIMIT_RETRY_AFTER`` after such a retry.

The answering backend is recorded in ``ModelGenerationMetadata``: ``provider`` is the backend that produced the
answer, and ``primary_provider``, ``fallback_provider``, ``fallback_used`` and ``fallback_reason`` describe the
chain. When both fail, the last sanitized error is raised and the query API maps it to its usual safe response.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterator

from backend.app.services.legal_answer_generation import (
    AnswerMode,
    LegalAnswerModelResponse,
    ModelProviderError,
    ModelUnavailableError,
)
from backend.app.services.llm_pacing import Key, LLMPacer, ModelLimits, PacingTimeout, llm_pacer

logger = logging.getLogger("legalai.llm_chain")

PROVIDER_FAILURE_SUFFIXES = ("_AUTH_ERROR", "_RATE_LIMIT", "_TIMEOUT", "_PROVIDER_ERROR")
PROVIDER_FAILURE_HTTP_STATUSES = {401, 403, 404, 408, 429}
UNAVAILABLE_CODE = "MODEL_UNAVAILABLE"
PRIMARY_AT_CAPACITY = "PRIMARY_AT_CAPACITY"
RATE_LIMIT_RETRY = "RATE_LIMIT_RETRY_AFTER"
# A 429 without retry-after or reset headers: wait for the provider's whole per-minute window.
DEFAULT_RATE_LIMIT_WAIT_SECONDS = 60.0
SLOT_BUSY_RETRY_AFTER_SECONDS = 15


class GenerationQueueTimeout(Exception):
    """No model capacity (or generation slot) within the request's queue wait; answered MODEL_BUSY."""

    def __init__(self, retry_after_seconds: float, waited_seconds: float) -> None:
        super().__init__(f"no answer capacity within the queue wait ({waited_seconds:.1f}s waited)")
        self.retry_after_seconds = max(1, int(round(retry_after_seconds)))
        self.waited_seconds = waited_seconds


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


def is_rate_limit(exc: Exception) -> bool:
    return isinstance(exc, ModelProviderError) and (exc.http_status == 429 or exc.code.endswith("_RATE_LIMIT"))


def model_limits(settings: Any, account: str) -> ModelLimits | None:
    """Known per-model limits for an account (Groq); None means the provider is not paced."""
    if account == "groq":
        return ModelLimits(int(settings.legalai_groq_tokens_per_minute), int(settings.legalai_groq_requests_per_minute))
    return None


def request_tokens(adapter: Any, prompt: str, schema: Any, settings: Any) -> int:
    """Tokens a request asks for: the request-size guard's prompt estimate plus the output limit."""
    from backend.app.services.groq_answer_adapter import groq_payload_schema
    from backend.app.services.token_budget import estimate_tokens

    estimate = estimate_tokens(prompt) + estimate_tokens(json.dumps(groq_payload_schema(schema)))
    factor = float(getattr(settings, "legalai_groq_token_estimate_factor", 1.0))
    return round(estimate * factor) + int(getattr(adapter, "max_output_tokens", 0) or 0)


def paced_key(adapter: Any, mode: Any, settings: Any) -> tuple[Key | None, ModelLimits | None]:
    if adapter is None or not hasattr(adapter, "rate_limit_key"):
        return None, None
    key = adapter.rate_limit_key(mode)
    limits = model_limits(settings, key[0])
    return (key, limits) if limits is not None and key[1] else (None, None)


def configure_pacing(settings: Any, adapters: list[Any], pacer: LLMPacer = llm_pacer) -> None:
    """Register the buckets of every model these adapters can use (both modes), e.g. at startup for /health."""
    for adapter in adapters:
        for mode in (AnswerMode.PUBLIC, AnswerMode.PROFESSIONAL):
            key, limits = paced_key(adapter, mode, settings)
            if key is not None:
                pacer.configure(key, limits)


@dataclass
class _Entry:
    name: str
    adapter: Any
    key: Key | None
    tokens: int


class FallbackAnswerAdapter:
    """Answer adapter that tries ``primary``, then ``fallback`` on a provider failure, paced when ``pacer`` is set."""

    def __init__(self, primary: Any, fallback: Any | None, *, primary_name: str, fallback_name: str | None,
                 settings: Any = None, pacer: LLMPacer | None = None, slots: Any = None, clock=time.monotonic) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_name = primary_name
        self.fallback_name = fallback_name
        self.settings = settings
        self.pacer = pacer
        self.slots = slots
        self.clock = clock

    @property
    def configured_model_id(self) -> str:
        return getattr(self.primary, "configured_model_id", "")

    @property
    def manages_generation_slot(self) -> bool:
        """When paced, the chain takes the generation slot itself, after the queue (query.py then does not)."""
        return self.pacer is not None and self.slots is not None

    def generate_structured_answer(self, prompt: str, *, schema: Any, mode: Any) -> LegalAnswerModelResponse:
        if self.pacer is None:
            return self._unpaced(prompt, schema=schema, mode=mode)
        return self._paced(prompt, schema=schema, mode=mode)

    # -- without pacing (unknown provider limits): the step 11 chain, unchanged ------------------------------------

    def _unpaced(self, prompt: str, *, schema: Any, mode: Any) -> LegalAnswerModelResponse:
        started = perf_counter()
        try:
            response = self.primary.generate_structured_answer(prompt, schema=schema, mode=mode)
        except (ModelUnavailableError, ModelProviderError) as exc:
            if self.fallback is None or not is_provider_failure(exc):
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

    # -- with pacing ------------------------------------------------------------------------------------------------

    def _paced(self, prompt: str, *, schema: Any, mode: Any) -> LegalAnswerModelResponse:
        started = perf_counter()
        began = self.clock()
        deadline = began + float(getattr(self.settings, "legalai_llm_queue_max_wait_seconds", 90.0))
        entries = []
        for name, adapter in ((self.primary_name, self.primary), (self.fallback_name, self.fallback)):
            if adapter is None:
                continue
            key, limits = paced_key(adapter, mode, self.settings)
            if key is not None:
                self.pacer.register(key, limits)
            entries.append(_Entry(name, adapter, key, request_tokens(adapter, prompt, schema, self.settings)))
        stats = {"queue_wait_ms": 0.0, "rate_limit_wait_ms": 0.0, "rate_limit_retries": 0.0}

        entry, waited = self._acquire(entries, deadline, began)
        stats["queue_wait_ms"] += waited * 1000
        reason = PRIMARY_AT_CAPACITY if entry is not entries[0] else None
        if reason:
            logger.warning("answer provider fallback primary=%s reason=%s fallback=%s", self.primary_name, reason, entry.name)
        failed: list[_Entry] = []
        retried = False
        while True:
            try:
                with self._slot(deadline, began):
                    response = entry.adapter.generate_structured_answer(prompt, schema=schema, mode=mode)
            except (ModelUnavailableError, ModelProviderError) as exc:
                if not is_provider_failure(exc):
                    raise
                code = failure_code(exc)
                if entry is entries[0]:
                    reason = code
                if is_rate_limit(exc):
                    wait = getattr(exc, "retry_after_seconds", None)
                    wait = DEFAULT_RATE_LIMIT_WAIT_SECONDS if wait is None else float(wait)
                    if entry.key is not None:
                        self.pacer.block(entry.key, wait)
                    other = next((e for e in entries if e is not entry and e not in failed and self._take_now(e)), None)
                    logger.warning("rate_limit provider=%s model=%s retry_after_s=%.1f immediate_fallback=%s",
                                   entry.name, entry.key[1] if entry.key else "", wait, other.name if other else "none")
                    if other is not None:
                        entry = other
                        continue
                    if retried or self.clock() + wait > deadline:
                        raise GenerationQueueTimeout(wait, self.clock() - began) from exc
                    retried = True
                    stats["rate_limit_retries"] += 1
                    waiting_since = self.clock()
                    entry, _ = self._acquire([e for e in entries if e not in failed], deadline, began)
                    stats["rate_limit_wait_ms"] += (self.clock() - waiting_since) * 1000
                    continue
                failed.append(entry)
                remaining = [e for e in entries if e not in failed]
                if not remaining:
                    if len(entries) > 1:
                        logger.error("answer providers failed primary=%s reason=%s fallback=%s reason=%s",
                                     self.primary_name, reason, self.fallback_name, code)
                    raise
                logger.warning("answer provider fallback primary=%s reason=%s fallback=%s", self.primary_name, code, remaining[0].name)
                entry, waited = self._acquire(remaining, deadline, began)
                stats["queue_wait_ms"] += waited * 1000
                continue
            fallback_used = entry is not entries[0]
            response = self._record(response, started, fallback_used=fallback_used, reason=reason if fallback_used else None,
                                    stats=stats, retried=retried)
            logger.info(
                "llm_pacing provider=%s model=%s queue_wait_ms=%.0f rate_limit_wait_ms=%.0f rate_limit_retries=%d fallback_used=%s reason=%s",
                entry.name, entry.key[1] if entry.key else "", stats["queue_wait_ms"], stats["rate_limit_wait_ms"],
                int(stats["rate_limit_retries"]), fallback_used, reason if fallback_used else None,
            )
            return response

    def _acquire(self, entries: list[_Entry], deadline: float, began: float) -> tuple[_Entry, float]:
        paced = [entry for entry in entries if entry.key is not None]
        if not paced:
            return entries[0], 0.0
        # In entry order (primary first); an unpaced entry is a key the pacer has no bucket for, so always free.
        candidates = [(entry.key, entry.tokens) if entry.key is not None else (("unpaced", entry.name), 0) for entry in entries]
        try:
            key, waited = self.pacer.acquire(candidates, timeout_seconds=max(0.0, deadline - self.clock()))
        except PacingTimeout as exc:
            raise GenerationQueueTimeout(exc.retry_after_seconds, self.clock() - began) from exc
        for entry in entries:
            if entry.key == key or (entry.key is None and key == ("unpaced", entry.name)):
                return entry, waited
        return entries[0], waited

    def _take_now(self, entry: _Entry) -> bool:
        return True if entry.key is None else self.pacer.take_now(entry.key, entry.tokens)

    @contextmanager
    def _slot(self, deadline: float, began: float) -> Iterator[None]:
        if self.slots is None:
            yield
            return
        size = int(getattr(self.settings, "llm_max_concurrent_generations", 4))
        wait = min(float(getattr(self.settings, "llm_generation_wait_seconds", 10.0)), max(0.0, deadline - self.clock()))
        with self.slots.slot(size, wait) as acquired:
            if not acquired:
                raise GenerationQueueTimeout(SLOT_BUSY_RETRY_AFTER_SECONDS, self.clock() - began)
            yield

    def _record(self, response: LegalAnswerModelResponse, started: float, *, fallback_used: bool, reason: str | None,
                stats: dict[str, float] | None = None, retried: bool = False) -> LegalAnswerModelResponse:
        update: dict[str, Any] = {}
        if self.fallback is not None:
            update.update({
                "fallback_used": fallback_used,
                "primary_provider": self.primary_name,
                "fallback_provider": self.fallback_name,
                "fallback_reason": reason,
            })
        if retried:
            update["retry_reasons"] = [*response.model_metadata.retry_reasons, RATE_LIMIT_RETRY]
        metadata = response.model_metadata.model_copy(update=update)
        timings = {**response.timings, "provider_chain_ms": round((perf_counter() - started) * 1000, 3)}
        if stats is not None:
            timings.update({name: round(value, 3) for name, value in stats.items()})
        return response.model_copy(update={"model_metadata": metadata, "timings": timings})


def build_answer_adapter(settings: Any, factories: dict[str, Any]) -> Any | None:
    """Primary adapter, wrapped in a FallbackAnswerAdapter when a different fallback is configured or pacing applies.

    ``factories`` maps provider names to adapter constructors. Returns None when the primary provider is not
    supported.
    """
    from backend.app.core.rate_limit import generation_slots

    primary_name = settings.legalai_llm_provider.strip().lower()
    if primary_name not in factories:
        return None
    primary = _with_retry_override(factories[primary_name](settings), settings)
    fallback_name = (settings.legalai_llm_fallback_provider or "").strip().lower()
    fallback = None
    if fallback_name and fallback_name not in {"none", primary_name} and fallback_name in factories:
        fallback = _with_retry_override(factories[fallback_name](settings), settings)
    else:
        fallback_name = None
    paced = bool(getattr(settings, "legalai_llm_pacing_enabled", False)) and any(
        paced_key(adapter, AnswerMode.PUBLIC, settings)[0] is not None for adapter in (primary, fallback)
    )
    if fallback is None and not paced:
        return primary
    return FallbackAnswerAdapter(
        primary, fallback, primary_name=primary_name, fallback_name=fallback_name, settings=settings,
        pacer=llm_pacer if paced else None, slots=generation_slots if paced else None,
    )


def _with_retry_override(adapter: Any, settings: Any) -> Any:
    """Apply LEGALAI_LLM_MAX_RETRIES (retries after the first attempt) to one adapter instance.

    Unset keeps the adapter's own default; the class defaults are not changed.
    """
    retries = getattr(settings, "legalai_llm_max_retries", None)
    if retries is not None and hasattr(adapter, "max_attempts"):
        adapter.max_attempts = max(0, int(retries)) + 1
    return adapter
