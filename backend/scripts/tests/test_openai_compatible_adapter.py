"""Step 21: the generic OpenAI-compatible answer adapter (mocked HTTP; no network, no keys)."""

from __future__ import annotations

import io
import json
import socket
import sys
import unittest
import urllib.error
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.api.query import ANSWER_ADAPTER_FACTORIES, request_size_guard  # noqa: E402
from backend.app.core.config import Settings  # noqa: E402
from backend.app.services.legal_answer_generation import (  # noqa: E402
    AnswerMode,
    ModelProviderError,
    ModelUnavailableError,
    PublicLegalAnswer,
)
from backend.app.services.llm_provider_chain import FallbackAnswerAdapter, build_answer_adapter, is_provider_failure  # noqa: E402
from backend.app.services.openai_compatible_adapter import (  # noqa: E402
    OpenAICompatibleAnswerAdapter,
    provider_profile,
    split_reasoning,
)

FAKE_KEY = "nvapi-FAKEKEYFORTESTS0123456789"
ANSWER = {"answer": {"explanation": "x"}, "summary": "s", "claims": []}


def settings(**values: Any) -> Settings:
    base = dict(
        _env_file=None, app_env="test", nvidia_api_key=FAKE_KEY, nvidia_model="vendor/model-x", ollama_model="local-model",
        legalai_llm_max_output_tokens=2048,
    )
    return Settings(**{**base, **values})


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def completion(content: str = json.dumps(ANSWER), *, finish: str = "stop", message_extra: dict | None = None, usage: dict | None = None) -> dict:
    return {
        "model": "vendor/model-x",
        "choices": [{"finish_reason": finish, "message": {"role": "assistant", "content": content, **(message_extra or {})}}],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


class Recorder:
    """A fake urlopen: returns or raises the queued outcomes and records each request."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[Any] = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(json.dumps(outcome).encode("utf-8"))

    def payload(self, index: int = 0) -> dict:
        return json.loads(self.requests[index][0].data.decode("utf-8"))


def http_error(status: int, body: dict | str = "") -> urllib.error.HTTPError:
    raw = (json.dumps(body) if isinstance(body, dict) else body).encode("utf-8")
    return urllib.error.HTTPError("https://example.invalid/v1/chat/completions", status, "error", {}, io.BytesIO(raw))


def adapter(urlopen: Recorder, profile: str = "nvidia", **values: Any) -> OpenAICompatibleAnswerAdapter:
    return OpenAICompatibleAnswerAdapter(settings(**values), profile, sleep=lambda _: None, urlopen=urlopen)


def generate(target: OpenAICompatibleAnswerAdapter):
    return target.generate_structured_answer("prompt text", schema=PublicLegalAnswer, mode=AnswerMode.PUBLIC)


class ProfileConfigTests(unittest.TestCase):
    def test_nvidia_profile_from_settings(self) -> None:
        profile = provider_profile(settings(nvidia_max_output_tokens=8192, nvidia_reasoning_effort="low", nvidia_max_request_tokens=60000), "nvidia")
        self.assertEqual(profile.base_url, "https://integrate.api.nvidia.com/v1")
        self.assertEqual((profile.model, profile.max_output_tokens, profile.max_request_tokens), ("vendor/model-x", 8192, 60000))
        self.assertEqual(profile.reasoning_options, (("reasoning_effort", "low"),))
        self.assertEqual(profile.api_key_env, "NVIDIA_API_KEY")
        self.assertTrue(profile.requires_key and profile.enabled)

    def test_output_limit_defaults_to_the_shared_setting(self) -> None:
        self.assertEqual(provider_profile(settings(), "nvidia").max_output_tokens, 2048)

    def test_ollama_profile_is_local_and_keyless(self) -> None:
        profile = provider_profile(settings(ollama_base_url="http://localhost:11434/", ollama_context_tokens=16384), "ollama")
        self.assertEqual(profile.base_url, "http://localhost:11434/v1")
        self.assertFalse(profile.requires_key)
        self.assertEqual(profile.max_request_tokens, 16384)

    def test_deepseek_and_openrouter_are_disabled_without_a_key(self) -> None:
        for name in ("deepseek", "openrouter"):
            with self.subTest(profile=name):
                self.assertFalse(provider_profile(settings(), name).enabled)
                with self.assertRaisesRegex(ModelUnavailableError, "disabled"):
                    generate(adapter(Recorder(), name))
        self.assertTrue(provider_profile(settings(deepseek_api_key="sk-test", deepseek_model="m"), "deepseek").enabled)

    def test_missing_key_or_model_is_unavailable_without_a_call(self) -> None:
        recorder = Recorder()
        with self.assertRaises(ModelUnavailableError):
            generate(adapter(recorder, nvidia_api_key=""))
        with self.assertRaises(ModelUnavailableError):
            generate(adapter(recorder, nvidia_model=""))
        self.assertEqual(recorder.requests, [])

    def test_unknown_profile_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            provider_profile(settings(), "acme")

    def test_factories_cover_every_profile(self) -> None:
        for name in ("nvidia", "ollama", "deepseek", "openrouter"):
            self.assertIsInstance(ANSWER_ADAPTER_FACTORIES[name](settings()), OpenAICompatibleAnswerAdapter)


class RequestTests(unittest.TestCase):
    def test_json_schema_payload_and_headers(self) -> None:
        recorder = Recorder(completion())
        generate(adapter(recorder, nvidia_timeout_seconds=42, nvidia_reasoning_effort="low"))
        request, timeout = recorder.requests[0]
        self.assertEqual(request.full_url, "https://integrate.api.nvidia.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {FAKE_KEY}")
        self.assertEqual(timeout, 42)
        payload = recorder.payload()
        self.assertEqual(payload["model"], "vendor/model-x")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "prompt text"}])
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(sorted(payload["response_format"]["json_schema"]["schema"]["properties"]), ["answer", "claims", "summary"])

    def test_json_object_mode_sends_the_schema_as_a_system_message_and_keeps_the_prompt(self) -> None:
        recorder = Recorder(completion())
        generate(adapter(recorder, nvidia_structured_output="json_object"))
        payload = recorder.payload()
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn('"claims"', payload["messages"][0]["content"])
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "prompt text"})

    def test_prompt_mode_sends_no_response_format(self) -> None:
        recorder = Recorder(completion())
        result = generate(adapter(recorder, "ollama", ollama_structured_output="prompt"))
        payload = recorder.payload()
        self.assertNotIn("response_format", payload)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn('"claims"', payload["messages"][0]["content"])
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "prompt text"})
        self.assertEqual(result.model_metadata.provider, "ollama")

    def test_unknown_structured_output_mode_is_unavailable(self) -> None:
        recorder = Recorder(completion())
        with self.assertRaises(ModelUnavailableError):
            generate(adapter(recorder, nvidia_structured_output="grammar"))
        self.assertEqual(recorder.requests, [])

    def test_ollama_sends_no_authorization(self) -> None:
        recorder = Recorder(completion())
        generate(adapter(recorder, "ollama"))
        self.assertIsNone(recorder.requests[0][0].get_header("Authorization"))
        self.assertEqual(recorder.requests[0][0].full_url, "http://localhost:11434/v1/chat/completions")

    def test_success_records_the_backend_and_tokens(self) -> None:
        response = generate(adapter(Recorder(completion())))
        metadata = response.model_metadata
        self.assertEqual((metadata.provider, metadata.actual_model_id, metadata.finish_reason), ("nvidia", "vendor/model-x", "stop"))
        self.assertEqual((metadata.prompt_tokens, metadata.completion_tokens), (100, 50))
        self.assertEqual(json.loads(response.raw_response), ANSWER)


class ReasoningSeparationTests(unittest.TestCase):
    def test_reasoning_content_field_is_excluded_and_counted_from_usage(self) -> None:
        body = completion(message_extra={"reasoning_content": "secret chain of thought"},
                          usage={"prompt_tokens": 10, "completion_tokens": 90, "completion_tokens_details": {"reasoning_tokens": 40}})
        response = generate(adapter(Recorder(body)))
        self.assertEqual(json.loads(response.raw_response), ANSWER)
        self.assertNotIn("chain of thought", response.raw_response)
        self.assertEqual(response.model_metadata.reasoning_tokens, 40)

    def test_think_block_and_code_fence_are_removed_and_reasoning_estimated(self) -> None:
        content = "<think>weighing the evidence carefully</think>\n```json\n" + json.dumps(ANSWER) + "\n```"
        response = generate(adapter(Recorder(completion(content))))
        self.assertEqual(json.loads(response.raw_response), ANSWER)
        self.assertGreater(response.model_metadata.reasoning_tokens, 0)

    def test_ollama_reasoning_field(self) -> None:
        answer, reasoning = split_reasoning({"content": json.dumps(ANSWER), "reasoning": "thinking"})
        self.assertEqual((json.loads(answer), reasoning), (ANSWER, "thinking"))

    def test_no_reasoning_means_none(self) -> None:
        self.assertIsNone(generate(adapter(Recorder(completion()))).model_metadata.reasoning_tokens)

    def test_reasoning_only_is_an_empty_response(self) -> None:
        with self.assertRaisesRegex(ModelProviderError, "returned no answer content") as raised:
            generate(adapter(Recorder(completion("", message_extra={"reasoning_content": "only thoughts"}))))
        self.assertEqual(raised.exception.code, "NVIDIA_EMPTY_RESPONSE")


class TruncationTests(unittest.TestCase):
    def test_length_stop_is_a_truncation_failure_not_a_provider_failure(self) -> None:
        recorder = Recorder(completion('{"answer": {"expl', finish="length"))
        with self.assertRaises(ModelProviderError) as raised:
            generate(adapter(recorder))
        self.assertEqual(raised.exception.code, "NVIDIA_OUTPUT_TRUNCATED")
        self.assertFalse(is_provider_failure(raised.exception))  # no fallback on a cut-off answer
        self.assertEqual(len(recorder.requests), 1)  # and no retry


class ErrorMappingTests(unittest.TestCase):
    def failure(self, *outcomes: Any, retries: int = 1, profile: str = "nvidia") -> tuple[ModelProviderError, Recorder]:
        recorder = Recorder(*outcomes)
        target = adapter(recorder, profile)
        target.max_attempts = retries + 1
        with self.assertRaises(ModelProviderError) as raised:
            generate(target)
        return raised.exception, recorder

    def test_codes_and_fallback_semantics(self) -> None:
        cases = [
            (http_error(429, {"error": {"message": "slow down"}}), "NVIDIA_RATE_LIMIT", True, 2),
            (http_error(401, {"error": {"message": "bad key"}}), "NVIDIA_AUTH_ERROR", True, 1),
            (http_error(403, "forbidden"), "NVIDIA_AUTH_ERROR", True, 1),
            (http_error(404, {"detail": "model not found"}), "NVIDIA_HTTP_ERROR", True, 1),
            (http_error(413, {"error": {"message": "too large"}}), "NVIDIA_REQUEST_TOO_LARGE", False, 1),
            (http_error(400, {"error": {"message": "bad schema"}}), "NVIDIA_HTTP_ERROR", False, 1),
            (http_error(503, {"error": {"message": "busy"}}), "NVIDIA_PROVIDER_ERROR", True, 2),
            (socket.timeout("read timed out"), "NVIDIA_TIMEOUT", True, 2),
            (urllib.error.URLError(ConnectionRefusedError()), "NVIDIA_PROVIDER_ERROR", True, 2),
        ]
        for outcome, code, falls_back, calls in cases:
            with self.subTest(code=code, outcome=type(outcome).__name__):
                error, recorder = self.failure(outcome, outcome)
                self.assertEqual(error.code, code)
                self.assertEqual(is_provider_failure(error), falls_back)
                self.assertEqual(len(recorder.requests), calls)  # retried once (LEGALAI_LLM_MAX_RETRIES=1) only when transient

    def test_ollama_errors_are_prefixed(self) -> None:
        error, _ = self.failure(urllib.error.URLError(ConnectionRefusedError()), urllib.error.URLError(ConnectionRefusedError()), profile="ollama")
        self.assertEqual(error.code, "OLLAMA_PROVIDER_ERROR")

    def test_key_never_appears_in_errors_or_logs(self) -> None:
        with self.assertLogs("legalai", level="INFO") as logs:
            error, _ = self.failure(http_error(401, {"error": {"message": f"invalid key {FAKE_KEY}"}}))
            generate(adapter(Recorder(completion())))
        text = " ".join([str(error), error.provider_message or "", *logs.output])
        self.assertNotIn(FAKE_KEY, text)
        self.assertNotIn("prompt text", text)
        self.assertIn("[redacted]", text)

    def test_retry_then_success(self) -> None:
        recorder = Recorder(http_error(503, "busy"), completion())
        target = adapter(recorder)
        target.max_attempts = 2
        response = generate(target)
        self.assertEqual((response.model_metadata.attempt_count, response.model_metadata.retry_reasons), (2, ["HTTP_503"]))


class ChainAndSizeGuardTests(unittest.TestCase):
    def test_profile_primary_with_groq_fallback(self) -> None:
        chain = build_answer_adapter(settings(legalai_llm_provider="nvidia", legalai_llm_fallback_provider="groq", legalai_llm_max_retries=1),
                                     ANSWER_ADAPTER_FACTORIES)
        self.assertIsInstance(chain, FallbackAnswerAdapter)
        self.assertIsInstance(chain.primary, OpenAICompatibleAnswerAdapter)
        self.assertEqual(chain.primary.max_attempts, 2)
        self.assertEqual((chain.primary_name, chain.fallback_name), ("nvidia", "groq"))

    def test_size_guard_uses_the_primary_profile_ceiling(self) -> None:
        guard = request_size_guard(settings(legalai_llm_provider="ollama", ollama_context_tokens=16384, ollama_max_output_tokens=4096))
        self.assertEqual((guard.ceiling_tokens, guard.max_output_tokens), (16384, 4096))
        self.assertTrue(guard.fits("short prompt", AnswerMode.PUBLIC))
        self.assertFalse(guard.fits("word " * 20000, AnswerMode.PUBLIC))

    def test_no_ceiling_means_no_guard(self) -> None:
        self.assertIsNone(request_size_guard(settings(legalai_llm_provider="nvidia")))

    def test_groq_guard_is_unchanged(self) -> None:
        guard = request_size_guard(settings(legalai_llm_provider="groq", legalai_groq_max_request_tokens=8000))
        self.assertEqual((guard.ceiling_tokens, guard.max_output_tokens, guard.estimate_factor), (8000, 2048, 1.51))
        self.assertIsNone(request_size_guard(settings(legalai_llm_provider="groq")))


if __name__ == "__main__":
    unittest.main()
