import json
import socket
import unittest
import urllib.error
from io import BytesIO
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    ClaimType,
    GeminiAnswerAdapter,
    GroundedCitation,
    GroundedLegalClaim,
    GroundingStatus,
    LegalAnswerModelResponse,
    ModelGenerationMetadata,
    ProfessionalLegalBrief,
    PublicLegalAnswer,
    gemini_schema,
    generate_legal_answer,
    is_retryable_gemini_error,
    model_payload_schema,
    sanitized_http_diagnostic,
)
from backend.scripts.diagnose_gemini_http import classify_root_cause
from backend.scripts.run_gemini_grounded_smoke import SMOKE_CASES, base_record, build_parser
from backend.scripts.tests.test_legal_answer_foundation import MockAdapter, evidence, retrieval
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


def gemini_payload(text=None):
    text = text or json.dumps(
        {
            "summary": "Fixture answer.",
            "what_this_may_mean": ["The cited fixture is relevant."],
            "possible_legal_provisions": ["Section 302 IPC was mentioned by the user."],
            "possible_next_steps": ["Verify current procedure locally."],
            "important_cautions": ["Applicability depends on facts."],
            "citations": [
                {
                    "evidence_id": "E1",
                    "claim_id": "c1",
                    "supported_text": "support",
                    "source_metadata": evidence("E1").citation_metadata.model_dump(mode="json"),
                    "support_level": "structural",
                }
            ],
        }
    )
    return {
        "modelVersion": "configured-model-returned",
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 7, "totalTokenCount": 18},
    }


class GeminiGroundedSmokeTests(unittest.TestCase):
    def understanding(self):
        return understand_legal_query("Section 302 IPC murder bail before Sessions Court")

    def settings(self):
        return Settings(gemini_api_key="test-key", gemini_model="configured-model", legalai_llm_temperature=0.1)

    def test_smoke_cases_are_fixed_and_fallback_is_disabled_by_contract(self):
        self.assertEqual([case["id"] for case in SMOKE_CASES], ["SMOKE-01", "SMOKE-02", "SMOKE-03", "SMOKE-04"])
        args = build_parser().parse_args(["--live"])
        self.assertTrue(args.live)

    def test_gemini_adapter_uses_configured_model_and_maps_token_metadata(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["timeout"] = timeout
            return FakeHttpResponse(gemini_payload())

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            response = GeminiAnswerAdapter(self.settings()).generate_structured_answer(
                "prompt",
                schema=object_with_schema(),
                mode=AnswerMode.PUBLIC,
            )
        self.assertIn("/models/configured-model:generateContent", captured["url"])
        self.assertNotIn("test-key", json.dumps(response.model_dump(mode="json")))
        self.assertEqual(response.model_metadata.configured_model_id, "configured-model")
        self.assertEqual(response.model_metadata.actual_model_id, "configured-model-returned")
        self.assertEqual(response.model_metadata.prompt_tokens, 11)
        self.assertEqual(response.model_metadata.completion_tokens, 7)
        self.assertEqual(response.model_metadata.total_tokens, 18)
        self.assertFalse(response.model_metadata.fallback_used)

    def test_provider_timeout_rate_limit_and_error_are_sanitized(self):
        adapter = GeminiAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", side_effect=socket.timeout()):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIn("GEMINI_TIMEOUT", {warning.code for warning in result.warnings})
        self.assertFalse(result.model_metadata.fallback_used)

        rate = urllib.error.HTTPError("url", 429, "Too Many Requests", hdrs=None, fp=None)
        with patch("urllib.request.urlopen", side_effect=rate):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIn("GEMINI_RATE_LIMIT", {warning.code for warning in result.warnings})
        self.assertNotIn("test-key", result.model_dump_json())

    def test_sanitized_http_diagnostic_extracts_safe_provider_message(self):
        body = json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "Invalid response schema field."}}).encode()
        error = urllib.error.HTTPError("url", 400, "Bad Request", hdrs=None, fp=BytesIO(body))
        diagnostic = sanitized_http_diagnostic(error)
        self.assertEqual(diagnostic.http_status, 400)
        self.assertEqual(diagnostic.provider_code, "INVALID_ARGUMENT")
        self.assertIn("Invalid response schema", diagnostic.provider_message)

    def test_auth_model_rate_limit_and_schema_root_cause_classification(self):
        self.assertEqual(classify_root_cause(provider_error("GEMINI_AUTH_ERROR", 403)), "AUTHENTICATION_CONFIGURATION")
        self.assertEqual(classify_root_cause(provider_error("GEMINI_RATE_LIMIT", 429)), "QUOTA_OR_RATE_LIMIT")
        self.assertEqual(classify_root_cause(provider_error("GEMINI_HTTP_ERROR", 404, "model not found")), "MODEL_UNAVAILABLE_OR_RETIRED")
        self.assertEqual(classify_root_cause(provider_error("GEMINI_HTTP_ERROR", 400, "bad schema")), "REQUEST_SCHEMA_INVALID")

    def test_invalid_json_from_provider_is_structured_parse_failure(self):
        adapter = GeminiAnswerAdapter(self.settings())
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(gemini_payload(text="not json"))):
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertIn("MODEL_OUTPUT_VALIDATION_FAILED", {warning.code for warning in result.warnings})
        self.assertFalse(result.model_metadata.repair_attempted)

    def test_valid_citation_and_metadata_mismatch_are_reported_in_record(self):
        good = generate_legal_answer(self.understanding(), retrieval(), adapter=MockAdapter(), prompt="prompt")
        good_record = base_record({"id": "T", "query": "q", "mode": AnswerMode.PUBLIC}, self.settings(), retrieval(), good, "SUCCESS", [])
        self.assertEqual(good_record["valid_citation_count"], 1)
        self.assertEqual(good_record["invalid_citation_count"], 0)

        bad_claim = GroundedLegalClaim(
            claim_id="c1",
            text="Bad fixture.",
            claim_type=ClaimType.CASE_LAW,
            citations=[
                GroundedCitation(
                    evidence_id="E1",
                    claim_id="c1",
                    supported_text="support",
                    source_metadata={"case_name": "Invented Case", "source_url": "https://fake.test/case"},
                )
            ],
            grounding_status=GroundingStatus.STRUCTURALLY_GROUNDED,
        )
        bad = generate_legal_answer(self.understanding(), retrieval(), adapter=MockAdapter(claim=bad_claim), prompt="prompt")
        bad_record = base_record({"id": "T", "query": "q", "mode": AnswerMode.PUBLIC}, self.settings(), retrieval(), bad, "SUCCESS", [])
        self.assertGreater(bad_record["invalid_citation_count"], 0)
        self.assertIn("METADATA_MISMATCH", bad_record["invalid_citation_reasons"])

    def test_generation_response_serializes_without_sdk_objects(self):
        response = LegalAnswerModelResponse(
            raw_response="{}",
            parsed_response={},
            model_metadata=ModelGenerationMetadata(provider="gemini", configured_model_id="configured-model", response_mode=AnswerMode.PUBLIC),
        )
        json.loads(response.model_dump_json())

    def test_gemini_schema_inlines_refs_and_strips_unsupported_fields(self):
        schema = {
            "$defs": {"Thing": {"title": "Thing", "type": "object", "properties": {"name": {"type": "string"}}}},
            "type": "object",
            "properties": {"thing": {"$ref": "#/$defs/Thing"}, "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        }
        converted = gemini_schema(schema)
        encoded = json.dumps(converted)
        self.assertNotIn("$defs", encoded)
        self.assertNotIn("$ref", encoded)
        self.assertNotIn("title", encoded)
        self.assertTrue(converted["properties"]["maybe"]["nullable"])

    def test_professional_schema_preserves_nested_required_citation_fields(self):
        canonical_required = set(GroundedCitation.model_json_schema(mode="serialization")["required"])
        self.assertEqual(canonical_required, {"evidence_id", "claim_id", "supported_text"})

        schema = model_payload_schema(ProfessionalLegalBrief)
        citation_item = schema["properties"]["answer"]["properties"]["citations"]["items"]
        self.assertEqual(set(citation_item["required"]), canonical_required)
        self.assertIn("source_metadata", citation_item["properties"])
        self.assertEqual(citation_item["properties"]["claim_id"]["type"], "string")
        self.assertEqual(citation_item["properties"]["supported_text"]["type"], "string")
        self.assertEqual(citation_item["properties"]["evidence_id"]["type"], "string")

    def test_claim_and_public_schema_nested_citation_arrays_retain_item_schema(self):
        schema = model_payload_schema(PublicLegalAnswer)
        public_citation = schema["properties"]["answer"]["properties"]["citations"]["items"]
        claim_citation = schema["properties"]["claims"]["items"]["properties"]["citations"]["items"]
        for citation_item in [public_citation, claim_citation]:
            self.assertEqual(set(citation_item["required"]), {"evidence_id", "claim_id", "supported_text"})
            self.assertIn("support_level", citation_item["properties"])
        encoded = json.dumps(schema)
        self.assertNotIn("$defs", encoded)
        self.assertNotIn("$ref", encoded)
        self.assertNotIn("title", encoded)
        self.assertNotIn("default", encoded)

    def test_retryability_classifier_is_deterministic(self):
        self.assertTrue(is_retryable_gemini_error(provider_error("GEMINI_RATE_LIMIT", 429)))
        self.assertTrue(is_retryable_gemini_error(provider_error("GEMINI_PROVIDER_ERROR", 503)))
        self.assertTrue(is_retryable_gemini_error(provider_error("GEMINI_TIMEOUT", None)))
        self.assertTrue(is_retryable_gemini_error(provider_error("GEMINI_PROVIDER_ERROR", None)))
        self.assertFalse(is_retryable_gemini_error(provider_error("GEMINI_HTTP_ERROR", 400)))
        self.assertFalse(is_retryable_gemini_error(provider_error("GEMINI_AUTH_ERROR", 401)))
        self.assertFalse(is_retryable_gemini_error(provider_error("GEMINI_AUTH_ERROR", 403)))
        self.assertFalse(is_retryable_gemini_error(provider_error("GEMINI_HTTP_ERROR", 404)))
        self.assertFalse(is_retryable_gemini_error(provider_error("MODEL_OUTPUT_VALIDATION_FAILED", None)))

    def test_transient_503_retries_then_success(self):
        first = http_error(503, "UNAVAILABLE", "temporary")
        with patch("urllib.request.urlopen", side_effect=[first, FakeHttpResponse(gemini_payload())]) as mocked:
            response = GeminiAnswerAdapter(self.settings(), sleep=lambda _: None).generate_structured_answer(
                "prompt",
                schema=object_with_schema(),
                mode=AnswerMode.PUBLIC,
            )
        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(response.model_metadata.attempt_count, 2)
        self.assertEqual(response.model_metadata.retry_count, 1)
        self.assertEqual(response.model_metadata.retry_reasons, ["HTTP_503"])
        self.assertEqual(response.model_metadata.final_provider_status, "SUCCESS")

    def test_two_transient_503_retries_then_success(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=[
                http_error(503, "UNAVAILABLE", "temporary"),
                http_error(503, "UNAVAILABLE", "temporary"),
                FakeHttpResponse(gemini_payload()),
            ],
        ) as mocked:
            response = GeminiAnswerAdapter(self.settings(), sleep=lambda _: None).generate_structured_answer(
                "prompt",
                schema=object_with_schema(),
                mode=AnswerMode.PUBLIC,
            )
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(response.model_metadata.attempt_count, 3)
        self.assertEqual(response.model_metadata.retry_count, 2)
        self.assertEqual(response.model_metadata.retry_reasons, ["HTTP_503", "HTTP_503"])

    def test_transient_503_is_bounded_after_three_attempts(self):
        adapter = GeminiAnswerAdapter(self.settings(), sleep=lambda _: None)
        with patch(
            "urllib.request.urlopen",
            side_effect=[
                http_error(503, "UNAVAILABLE", "temporary"),
                http_error(503, "UNAVAILABLE", "temporary"),
                http_error(503, "UNAVAILABLE", "temporary"),
            ],
        ) as mocked:
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertEqual(mocked.call_count, 3)
        self.assertEqual(result.model_metadata.attempt_count, 3)
        self.assertEqual(result.model_metadata.retry_count, 2)
        self.assertEqual(result.model_metadata.retry_reasons, ["HTTP_503", "HTTP_503"])
        self.assertEqual(result.model_metadata.final_provider_status, "HTTP_503")

    def test_timeout_and_429_retry_then_success(self):
        for error, expected_reason in [(socket.timeout(), "GEMINI_TIMEOUT"), (http_error(429, "RESOURCE_EXHAUSTED", "quota"), "HTTP_429")]:
            with self.subTest(expected_reason=expected_reason):
                with patch("urllib.request.urlopen", side_effect=[error, FakeHttpResponse(gemini_payload())]) as mocked:
                    response = GeminiAnswerAdapter(self.settings(), sleep=lambda _: None).generate_structured_answer(
                        "prompt",
                        schema=object_with_schema(),
                        mode=AnswerMode.PUBLIC,
                    )
                self.assertEqual(mocked.call_count, 2)
                self.assertEqual(response.model_metadata.retry_reasons, [expected_reason])

    def test_non_retryable_http_errors_do_not_retry(self):
        for status in [400, 401, 404]:
            with self.subTest(status=status):
                adapter = GeminiAnswerAdapter(self.settings(), sleep=lambda _: None)
                with patch("urllib.request.urlopen", side_effect=http_error(status, "ERROR", "not retryable")) as mocked:
                    result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
                self.assertEqual(mocked.call_count, 1)
                self.assertEqual(result.model_metadata.attempt_count, 1)
                self.assertEqual(result.model_metadata.retry_count, 0)
                self.assertEqual(result.model_metadata.final_provider_status, f"HTTP_{status}")

    def test_successful_generation_invalid_schema_does_not_transient_retry(self):
        adapter = GeminiAnswerAdapter(self.settings(), sleep=lambda _: None)
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(gemini_payload(text="not json"))) as mocked:
            result = generate_legal_answer(self.understanding(), retrieval(), adapter=adapter, prompt="prompt")
        self.assertEqual(mocked.call_count, 1)
        self.assertIn("MODEL_OUTPUT_VALIDATION_FAILED", {warning.code for warning in result.warnings})
        self.assertEqual(result.model_metadata.attempt_count, 1)
        self.assertEqual(result.model_metadata.retry_count, 0)
        self.assertFalse(result.model_metadata.repair_attempted)


def object_with_schema():
    class MinimalSchema:
        @staticmethod
        def model_json_schema(mode="serialization"):
            return {"type": "object"}

    return MinimalSchema


def provider_error(code, status, message=""):
    from backend.app.services.legal_answer_generation import ModelProviderError

    return ModelProviderError(code, message, http_status=status, provider_code=None, provider_message=message)


def http_error(status, provider_code, message):
    body = json.dumps({"error": {"code": status, "status": provider_code, "message": message}}).encode()
    return urllib.error.HTTPError("url", status, "HTTP error", hdrs=None, fp=BytesIO(body))


if __name__ == "__main__":
    unittest.main()
