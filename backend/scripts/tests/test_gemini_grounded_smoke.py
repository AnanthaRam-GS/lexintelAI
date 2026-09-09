import json
import socket
import unittest
import urllib.error
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
    generate_legal_answer,
)
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


def object_with_schema():
    class MinimalSchema:
        @staticmethod
        def model_json_schema(mode="serialization"):
            return {"type": "object"}

    return MinimalSchema


if __name__ == "__main__":
    unittest.main()
