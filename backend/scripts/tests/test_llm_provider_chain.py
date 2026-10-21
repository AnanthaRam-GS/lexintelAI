"""Primary-then-fallback answer provider chain (no network, no database)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import Settings
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    LegalAnswerModelResponse,
    ModelGenerationMetadata,
    ModelProviderError,
    ModelUnavailableError,
    ProfessionalLegalBrief,
)
from backend.app.services.llm_provider_chain import FallbackAnswerAdapter, build_answer_adapter, is_provider_failure


class StubAdapter:
    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.calls = 0
        self.configured_model_id = f"{name}-model"

    def generate_structured_answer(self, prompt, *, schema, mode):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LegalAnswerModelResponse(
            raw_response="{}",
            parsed_response={"answer": {"issue_summary": "ok", "legal_regime": "ipc_crpc"}, "summary": "ok", "claims": []},
            model_metadata=ModelGenerationMetadata(provider=self.name, configured_model_id=f"{self.name}-model", response_mode=mode),
        )


def provider_error(code: str, status: int | None = None) -> ModelProviderError:
    return ModelProviderError(code, "sanitized message", http_status=status)


PROVIDER_FAILURES = {
    "missing key": ModelUnavailableError("Groq API key must be configured."),
    "auth": provider_error("GROQ_AUTH_ERROR", 401),
    "model not found": provider_error("GROQ_HTTP_ERROR", 404),
    "rate limit": provider_error("GROQ_RATE_LIMIT", 429),
    "timeout": provider_error("GROQ_TIMEOUT"),
    "upstream 5xx": provider_error("GROQ_PROVIDER_ERROR", 503),
    "network": provider_error("GROQ_PROVIDER_ERROR"),
}
CONTENT_FAILURES = {
    "request too large": provider_error("GROQ_REQUEST_TOO_LARGE", 413),
    "bad request": provider_error("GROQ_HTTP_ERROR", 400),
    "empty body": provider_error("GROQ_EMPTY_RESPONSE"),
    "non-JSON body": provider_error("GROQ_INVALID_RESPONSE"),
}


def chain(primary_error: Exception | None = None, fallback_error: Exception | None = None):
    primary, fallback = StubAdapter("groq", primary_error), StubAdapter("gemini", fallback_error)
    return FallbackAnswerAdapter(primary, fallback, primary_name="groq", fallback_name="gemini"), primary, fallback


def call(adapter):
    return adapter.generate_structured_answer("prompt", schema=ProfessionalLegalBrief, mode=AnswerMode.PROFESSIONAL)


class ProviderChainTests(unittest.TestCase):
    def test_primary_success_records_the_chain_without_fallback(self) -> None:
        adapter, primary, fallback = chain()
        metadata = call(adapter).model_metadata
        self.assertEqual((primary.calls, fallback.calls), (1, 0))
        self.assertEqual(
            (metadata.provider, metadata.fallback_used, metadata.primary_provider, metadata.fallback_provider, metadata.fallback_reason),
            ("groq", False, "groq", "gemini", None),
        )

    def test_provider_failures_fall_back_and_record_the_reason(self) -> None:
        for label, error in PROVIDER_FAILURES.items():
            with self.subTest(failure=label):
                self.assertTrue(is_provider_failure(error))
                adapter, primary, fallback = chain(primary_error=error)
                response = call(adapter)
                metadata = response.model_metadata
                self.assertEqual((primary.calls, fallback.calls), (1, 1))
                self.assertEqual((metadata.provider, metadata.fallback_used, metadata.primary_provider), ("gemini", True, "groq"))
                self.assertEqual(metadata.fallback_reason, "MODEL_UNAVAILABLE" if label == "missing key" else error.code)
                self.assertIn("provider_chain_ms", response.timings)

    def test_content_and_request_failures_never_fall_back(self) -> None:
        for label, error in CONTENT_FAILURES.items():
            with self.subTest(failure=label):
                self.assertFalse(is_provider_failure(error))
                adapter, primary, fallback = chain(primary_error=error)
                with self.assertRaises(ModelProviderError) as raised:
                    call(adapter)
                self.assertIs(raised.exception, error)
                self.assertEqual(fallback.calls, 0)

    def test_unexpected_exceptions_are_not_swallowed_or_retried(self) -> None:
        adapter, _primary, fallback = chain(primary_error=RuntimeError("bug"))
        with self.assertRaises(RuntimeError):
            call(adapter)
        self.assertEqual(fallback.calls, 0)

    def test_both_failing_raises_the_fallbacks_sanitized_error_once(self) -> None:
        fallback_error = provider_error("GEMINI_PROVIDER_ERROR", 503)
        adapter, primary, fallback = chain(primary_error=provider_error("GROQ_TIMEOUT"), fallback_error=fallback_error)
        with self.assertRaises(ModelProviderError) as raised:
            call(adapter)
        self.assertIs(raised.exception, fallback_error)
        self.assertEqual((primary.calls, fallback.calls), (1, 1))  # no loop

    def test_build_answer_adapter(self) -> None:
        factories = {"groq": lambda s: StubAdapter("groq"), "gemini": lambda s: StubAdapter("gemini")}
        chained = build_answer_adapter(Settings(legalai_llm_provider="groq", legalai_llm_fallback_provider="gemini"), factories)
        self.assertIsInstance(chained, FallbackAnswerAdapter)
        self.assertEqual((chained.primary.name, chained.fallback.name), ("groq", "gemini"))
        for disabled in ("", "none", "groq", "ollama"):
            plain = build_answer_adapter(Settings(legalai_llm_provider="groq", legalai_llm_fallback_provider=disabled), factories)
            self.assertNotIsInstance(plain, FallbackAnswerAdapter)
        self.assertIsNone(build_answer_adapter(Settings(legalai_llm_provider="ollama"), factories))

    def test_retry_override_applies_per_instance_without_changing_defaults(self) -> None:
        from backend.app.services.groq_answer_adapter import GroqAnswerAdapter
        from backend.app.services.legal_answer_generation import GeminiAnswerAdapter

        factories = {"groq": GroqAnswerAdapter, "gemini": GeminiAnswerAdapter}
        default = build_answer_adapter(Settings(legalai_llm_provider="groq", legalai_llm_fallback_provider="gemini"), factories)
        self.assertEqual((default.primary.max_attempts, default.fallback.max_attempts), (GroqAnswerAdapter.max_attempts, GeminiAnswerAdapter.max_attempts))
        limited = build_answer_adapter(
            Settings(legalai_llm_provider="groq", legalai_llm_fallback_provider="gemini", legalai_llm_max_retries=1), factories
        )
        self.assertEqual((limited.primary.max_attempts, limited.fallback.max_attempts), (2, 2))
        self.assertEqual((GroqAnswerAdapter.max_attempts, GeminiAnswerAdapter.max_attempts), (3, 3))  # class defaults unchanged


if __name__ == "__main__":
    unittest.main()
