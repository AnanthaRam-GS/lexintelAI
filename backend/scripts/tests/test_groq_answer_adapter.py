"""Unit tests for the Groq product-runtime answer adapter.

No live Groq calls are made anywhere in this file — every HTTP interaction is
mocked via `unittest.mock.patch("urllib.request.urlopen", ...)`.
"""

from __future__ import annotations

import json
import socket
import unittest
import urllib.error
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.services.groq_answer_adapter import GroqAnswerAdapter, groq_payload_schema
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    ModelProviderError,
    ModelUnavailableError,
    PublicLegalAnswer,
    generate_legal_answer,
)
from backend.scripts.tests.test_legal_answer_foundation import evidence, retrieval
from backend.app.services.legal_query_understanding import understand_legal_query


class FakeHttpResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _fixture_citation() -> dict:
    return {
        "evidence_id": "E1",
        "claim_id": "c1",
        "supported_text": "support",
        "source_metadata": evidence("E1").citation_metadata.model_dump(mode="json"),
        "support_level": "structural",
    }


def groq_payload(text=None):
    text = text or json.dumps(
        {
            "answer": {
                "summary": "Fixture answer.",
                "what_this_may_mean": ["The cited fixture is relevant."],
                "possible_legal_provisions": ["Section 302 IPC was mentioned by the user."],
                "possible_next_steps": ["Verify current procedure locally."],
                "important_cautions": ["Applicability depends on facts."],
                "citations": [_fixture_citation()],
            },
            "summary": "Fixture answer.",
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "A case-specific bail proposition requires retrieved authority.",
                    "claim_type": "CASE_LAW",
                    "citations": [_fixture_citation()],
                    "grounding_status": "STRUCTURALLY_GROUNDED",
                }
            ],
        }
    )
    return {
        "model": "configured-model-returned",
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }


def http_error(status: int, reason: str = "HTTP error", body: str | None = None) -> urllib.error.HTTPError:
    from io import BytesIO

    fp = BytesIO(json.dumps({"error": {"message": body or reason, "type": "fixture_error"}}).encode()) if body or reason else None
    return urllib.error.HTTPError("url", status, reason, hdrs=None, fp=fp)


class GroqAnswerAdapterTests(unittest.TestCase):
    def understanding(self):
        return understand_legal_query("Section 302 IPC murder bail before Sessions Court")

    def settings(self, **overrides) -> Settings:
        defaults = dict(groq_api_key="test-groq-key", groq_model="openai/gpt-oss-120b", legalai_llm_provider="groq")
        defaults.update(overrides)
        # Not the developer's .env (e.g. its GROQ_PUBLIC_MODEL routing): these tests fix every setting they rely on.
        return Settings(_env_file=None, **defaults)

    def test_adapter_initializes_with_configured_key_and_model(self) -> None:
        adapter = GroqAnswerAdapter(self.settings())
        self.assertEqual(adapter.configured_model_id, "openai/gpt-oss-120b")
        self.assertEqual(adapter.settings.groq_api_key, "test-groq-key")

    def test_missing_api_key_fails_safely_as_model_unavailable(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(groq_api_key=""))
        with self.assertRaises(ModelUnavailableError):
            adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)

    def test_missing_model_fails_safely_as_model_unavailable(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(groq_model=""))
        with self.assertRaises(ModelUnavailableError):
            adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)

    def test_model_id_comes_from_configuration_not_hardcoded(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(groq_payload())

        adapter = GroqAnswerAdapter(self.settings(groq_model="a-completely-different-model-id"))
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)

        self.assertEqual(captured["body"]["model"], "a-completely-different-model-id")
        self.assertEqual(response.model_metadata.configured_model_id, "a-completely-different-model-id")
        self.assertNotIn("openai/gpt-oss-120b", json.dumps(captured["body"]))

    def test_successful_structured_answer_reaches_generate_legal_answer(self) -> None:
        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(groq_payload())):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIsNotNone(result.answer)
        self.assertEqual(result.model_metadata.provider, "groq")
        self.assertEqual(result.model_metadata.actual_model_id, "configured-model-returned")
        self.assertEqual(result.model_metadata.prompt_tokens, 11)
        self.assertEqual(result.model_metadata.completion_tokens, 7)
        self.assertEqual(result.model_metadata.total_tokens, 18)
        self.assertFalse(result.model_metadata.fallback_used)

    def test_malformed_json_response_is_recorded_as_schema_failure_not_invented(self) -> None:
        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(groq_payload(text="not json"))):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIsNone(result.answer)
        self.assertIn("MODEL_OUTPUT_VALIDATION_FAILED", {warning.code for warning in result.warnings})

    def test_401_maps_to_auth_error(self) -> None:
        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", side_effect=http_error(401, "Unauthorized")):
            with self.assertRaises(ModelProviderError) as ctx:
                adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)
        self.assertEqual(ctx.exception.code, "GROQ_AUTH_ERROR")

    def test_403_maps_to_auth_error(self) -> None:
        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", side_effect=http_error(403, "Forbidden")):
            with self.assertRaises(ModelProviderError) as ctx:
                adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)
        self.assertEqual(ctx.exception.code, "GROQ_AUTH_ERROR")

    def test_429_maps_to_rate_limit_without_a_quick_retry(self) -> None:
        # Step 23: no 0.25 s retry into the same per-minute window; the provider chain waits for retry-after.
        sleeps: list[float] = []
        adapter = GroqAnswerAdapter(self.settings(), sleep=sleeps.append)
        error = http_error(429, "Too Many Requests")
        error.headers = {"retry-after": "7", "x-ratelimit-remaining-tokens": "120"}
        with patch("urllib.request.urlopen", side_effect=error) as urlopen:
            with self.assertRaises(ModelProviderError) as ctx:
                adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)
        self.assertEqual(ctx.exception.code, "GROQ_RATE_LIMIT")
        self.assertEqual((ctx.exception.attempt_count, urlopen.call_count, sleeps), (1, 1, []))
        self.assertEqual(ctx.exception.retry_after_seconds, 7.0)

    def test_429_recorded_through_full_pipeline_as_rate_limit_warning(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(), sleep=lambda _seconds: None)
        with patch("urllib.request.urlopen", side_effect=http_error(429, "Too Many Requests")):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIn("GROQ_RATE_LIMIT", {warning.code for warning in result.warnings})

    def test_timeout_maps_to_timeout_code(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(), sleep=lambda _seconds: None)
        with patch("urllib.request.urlopen", side_effect=socket.timeout()):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIn("GROQ_TIMEOUT", {warning.code for warning in result.warnings})

    def test_upstream_500_maps_to_provider_error(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(), sleep=lambda _seconds: None)
        with patch("urllib.request.urlopen", side_effect=http_error(500, "Internal Server Error")):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIn("GROQ_PROVIDER_ERROR", {warning.code for warning in result.warnings})

    def test_413_maps_to_request_too_large_and_is_not_retried(self) -> None:
        """Regression test: a real Groq account on the free/on-demand tier
        returns HTTP 413 (not 429) when a single request's prompt exceeds its
        tokens-per-minute allowance - observed in production with a large
        professional PDF query (~11.5k tokens against an 8k TPM cap). This is
        not transient, so it must not be retried and must not be flattened
        into the generic MODEL_PROVIDER_ERROR bucket."""
        adapter = GroqAnswerAdapter(self.settings(), sleep=lambda _seconds: None)
        body = "Request too large for model `openai/gpt-oss-120b` on tokens per minute (TPM): Limit 8000, Requested 11467"
        with patch("urllib.request.urlopen", side_effect=http_error(413, "Payload Too Large", body=body)) as mocked:
            with self.assertRaises(ModelProviderError) as ctx:
                adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)
        self.assertEqual(ctx.exception.code, "GROQ_REQUEST_TOO_LARGE")
        self.assertEqual(mocked.call_count, 1, "a too-large request must not be retried")

    def test_413_recorded_through_full_pipeline_as_request_too_large_warning(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(), sleep=lambda _seconds: None)
        with patch("urllib.request.urlopen", side_effect=http_error(413, "Payload Too Large")):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIn("GROQ_REQUEST_TOO_LARGE", {warning.code for warning in result.warnings})

    def test_transient_503_retries_then_succeeds(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(), sleep=lambda _seconds: None)
        with patch(
            "urllib.request.urlopen",
            side_effect=[http_error(503, "Service Unavailable"), FakeHttpResponse(groq_payload())],
        ) as mocked:
            response = adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(response.model_metadata.retry_count, 1)

    def test_non_retryable_400_does_not_retry(self) -> None:
        adapter = GroqAnswerAdapter(self.settings(), sleep=lambda _seconds: None)
        with patch("urllib.request.urlopen", side_effect=http_error(400, "Bad Request")) as mocked:
            with self.assertRaises(ModelProviderError):
                adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)
        self.assertEqual(mocked.call_count, 1)

    def test_provider_response_and_key_never_leak_into_result(self) -> None:
        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", side_effect=http_error(429, "Too Many Requests")):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        serialized = result.model_dump_json()
        self.assertNotIn("test-groq-key", serialized)
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn("Bearer", serialized)

    def test_api_key_never_appears_in_request_url_or_is_logged_in_the_clear(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            return FakeHttpResponse(groq_payload())

        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)

        self.assertNotIn("test-groq-key", captured["url"])
        self.assertEqual(captured["headers"].get("Authorization"), "Bearer test-groq-key")

    def test_request_sends_a_user_agent_to_avoid_cloudflare_bot_blocking(self) -> None:
        """Regression test: Groq's API is fronted by Cloudflare, which returns a
        403 (Cloudflare error 1010) for requests with no User-Agent, before the
        request ever reaches Groq's own auth layer. This must never regress."""
        captured = {}

        def fake_urlopen(request, timeout):
            captured["headers"] = dict(request.header_items())
            return FakeHttpResponse(groq_payload())

        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)

        self.assertTrue(captured["headers"].get("User-agent"), "request must carry a non-empty User-Agent header")

    def test_response_format_is_non_strict_to_tolerate_open_ended_source_metadata(self) -> None:
        """Regression test: strict:true rejects GroundedCitation.source_metadata
        (an open dict[str, Any]) with a 400 'additionalProperties:false must be
        set on every object' error from Groq, since it has no fixed properties."""
        captured = {}

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHttpResponse(groq_payload())

        adapter = GroqAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)

        self.assertFalse(captured["body"]["response_format"]["json_schema"]["strict"])

    def test_endpoint_uses_configured_base_url(self) -> None:
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return FakeHttpResponse(groq_payload())

        adapter = GroqAnswerAdapter(self.settings(groq_base_url="https://groq.internal.test/openai/v1/"))
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            adapter.generate_structured_answer("prompt", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)

        self.assertEqual(captured["url"], "https://groq.internal.test/openai/v1/chat/completions")

    def test_groq_schema_is_strict_openai_form(self) -> None:
        schema = groq_payload_schema(PublicLegalAnswer)
        self.assertEqual(schema["type"], "object")
        self.assertFalse(schema.get("additionalProperties", True) and "$defs" in schema)
        self._assert_strict(schema)

    def _assert_strict(self, node) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                self.assertEqual(node.get("additionalProperties"), False)
                self.assertEqual(set(node.get("required", [])), set(node["properties"].keys()))
            for value in node.values():
                self._assert_strict(value)
        elif isinstance(node, list):
            for item in node:
                self._assert_strict(item)


if __name__ == "__main__":
    unittest.main()
