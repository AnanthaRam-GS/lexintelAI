"""Prompt v2, case-name normalization and output-limit handling (no network, no database)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.config import Settings
from backend.app.services.case_names import normalized_for_generation, strip_date_suffix
from backend.app.services.groq_answer_adapter import GroqAnswerAdapter
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    GeminiAnswerAdapter,
    LegalAnswerModelResponse,
    ModelGenerationMetadata,
    ModelProviderError,
    ProfessionalLegalBrief,
    build_grounded_evidence_packet,
    generate_legal_answer,
)
from backend.app.services.legal_answer_prompt import build_legal_answer_prompt
from backend.app.services.legal_answer_prompt_v2 import (
    NO_COVERAGE_STATEMENT,
    PROMPT_VERSION,
    V2_RULES,
    build_legal_answer_prompt_v2,
    is_no_coverage_answer,
)
from backend.app.services.legal_query_understanding import understand_legal_query
from backend.app.services.llm_provider_chain import is_provider_failure
from backend.scripts.tests.test_groq_answer_adapter import FakeHttpResponse, groq_payload
from backend.scripts.tests.test_legal_answer_foundation import evidence, retrieval

TITLE = "Sri Tanay Das vs The State Of Tripura on 2 May, 2022"


def titled_retrieval():
    item = evidence("E1")
    item = item.model_copy(update={"case_name": TITLE, "citation_metadata": item.citation_metadata.model_copy(update={"case_name": TITLE})})
    return retrieval([item])


class CaseNameTests(unittest.TestCase):
    def test_strips_only_a_trailing_decision_date(self) -> None:
        self.assertEqual(strip_date_suffix(TITLE), "Sri Tanay Das vs The State Of Tripura")
        self.assertEqual(strip_date_suffix("A vs B on 12 September, 2023"), "A vs B")
        self.assertEqual(strip_date_suffix("A vs B on 3 Sept 2021"), "A vs B")
        self.assertEqual(strip_date_suffix("A vs B on 30 july, 2021"), "A vs B")
        for unchanged in ("A vs B", "Order on bail of 2 May 2022 vs State", "A vs B on appeal", "", None):
            self.assertEqual(strip_date_suffix(unchanged), unchanged)

    def test_generation_copy_is_normalized_and_the_original_is_untouched(self) -> None:
        original = titled_retrieval()
        normalized = normalized_for_generation(original)
        self.assertEqual(normalized.evidence[0].case_name, "Sri Tanay Das vs The State Of Tripura")
        self.assertEqual(normalized.evidence[0].citation_metadata.case_name, "Sri Tanay Das vs The State Of Tripura")
        self.assertEqual(original.evidence[0].case_name, TITLE)
        self.assertEqual(original.evidence[0].citation_metadata.case_name, TITLE)

    def test_a_citation_copying_the_shown_name_validates(self) -> None:
        shown_name = "Sri Tanay Das vs The State Of Tripura"
        understanding = understand_legal_query("bail")
        normalized = normalized_for_generation(titled_retrieval())
        prompt = build_legal_answer_prompt_v2(build_grounded_evidence_packet(understanding, normalized), mode=AnswerMode.PROFESSIONAL).prompt
        self.assertIn(shown_name, prompt)
        self.assertNotIn(TITLE, prompt)
        adapter = CopyingAdapter(shown_name)
        result = generate_legal_answer(understanding, normalized, mode=AnswerMode.PROFESSIONAL, adapter=adapter, prompt=prompt)
        self.assertTrue(result.citation_validation.valid, result.citation_validation.issues)
        # The same citation checked against the full title fails, as in step 11 run P1.
        unnormalized = generate_legal_answer(understanding, titled_retrieval(), mode=AnswerMode.PROFESSIONAL, adapter=adapter, prompt=prompt)
        self.assertFalse(unnormalized.citation_validation.valid)


class CopyingAdapter:
    """Mocked model that cites E1 with the case name shown in the prompt."""

    configured_model_id = "fixture"

    def __init__(self, case_name: str) -> None:
        self.case_name = case_name

    def generate_structured_answer(self, prompt, *, schema, mode):
        citation = {"evidence_id": "E1", "claim_id": "c1", "supported_text": "support", "source_metadata": {"case_name": self.case_name}}
        body = {"answer": {"issue_summary": "s", "legal_regime": "ipc_crpc"}, "summary": "s",
                "claims": [{"claim_id": "c1", "text": "t", "claim_type": "CASE_LAW", "citations": [citation]}]}
        return LegalAnswerModelResponse(
            raw_response=json.dumps(body), parsed_response=body,
            model_metadata=ModelGenerationMetadata(provider="fixture", configured_model_id="fixture", response_mode=mode),
        )


class PromptV2Tests(unittest.TestCase):
    def test_v2_adds_the_grounding_rules_and_keeps_v1_unchanged(self) -> None:
        packet = build_grounded_evidence_packet(understand_legal_query("bail"), retrieval())
        v1 = build_legal_answer_prompt(packet, mode=AnswerMode.PUBLIC).prompt
        v2 = build_legal_answer_prompt_v2(packet, mode=AnswerMode.PUBLIC).prompt
        self.assertEqual(PROMPT_VERSION, "legal_answer_prompt_v2")
        self.assertNotIn("<GROUNDING_RULES>", v1)
        self.assertIn(V2_RULES, v2)
        self.assertIn("an answer with an empty claims array is invalid", v2)
        self.assertIn("copy case_name, court, date and source_url exactly", v2)
        self.assertIn(NO_COVERAGE_STATEMENT, v2)
        self.assertIn("no substantive legal answer", v2)
        # v2 keeps every v1 section (rules, mode requirements, query context, evidence, citation policy).
        for block in ("<SYSTEM_RULES>", "<MODE_REQUIREMENTS>", "<QUERY_CONTEXT>", "<EVIDENCE_SET>", "<CITATION_POLICY>"):
            self.assertIn(block, v2)

    def test_no_coverage_detection(self) -> None:
        self.assertTrue(is_no_coverage_answer(f"{NO_COVERAGE_STATEMENT} A trademark attorney can help."))
        self.assertFalse(is_no_coverage_answer("Cheating is punishable under Section 420 IPC."))
        self.assertFalse(is_no_coverage_answer(None))


class OutputLimitTests(unittest.TestCase):
    def settings(self) -> Settings:
        return Settings(groq_api_key="k", groq_model="m", gemini_api_key="k", gemini_model="g", legalai_llm_max_output_tokens=1234)

    def test_groq_sends_the_limit_and_rejects_a_length_stop(self) -> None:
        body = groq_payload()
        body["choices"][0]["finish_reason"] = "length"
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(body)) as urlopen, self.assertLogs("legalai.groq", "INFO") as logs:
            with self.assertRaises(ModelProviderError) as raised:
                GroqAnswerAdapter(self.settings()).generate_structured_answer("p", schema=ProfessionalLegalBrief, mode=AnswerMode.PROFESSIONAL)
        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(sent["max_completion_tokens"], 1234)
        self.assertEqual(raised.exception.code, "GROQ_OUTPUT_TRUNCATED")
        self.assertFalse(is_provider_failure(raised.exception))  # truncation never triggers the fallback
        self.assertIn("finish_reason=length", logs.output[0])

    def test_groq_records_a_normal_stop(self) -> None:
        body = groq_payload()
        body["choices"][0]["finish_reason"] = "stop"
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(body)):
            response = GroqAnswerAdapter(self.settings()).generate_structured_answer("p", schema=ProfessionalLegalBrief, mode=AnswerMode.PROFESSIONAL)
        self.assertEqual(response.model_metadata.finish_reason, "stop")

    def test_gemini_sends_the_limit_and_rejects_a_max_tokens_stop(self) -> None:
        def body(reason):
            return {"candidates": [{"finishReason": reason, "content": {"parts": [{"text": json.dumps({"answer": {}, "summary": "", "claims": []})}]}}]}

        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(body("MAX_TOKENS"))) as urlopen:
            with self.assertRaises(ModelProviderError) as raised:
                GeminiAnswerAdapter(self.settings()).generate_structured_answer("p", schema=ProfessionalLegalBrief, mode=AnswerMode.PROFESSIONAL)
        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(sent["generationConfig"]["maxOutputTokens"], 1234)
        self.assertEqual(raised.exception.code, "GEMINI_OUTPUT_TRUNCATED")
        self.assertFalse(is_provider_failure(raised.exception))
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(body("STOP"))):
            response = GeminiAnswerAdapter(self.settings()).generate_structured_answer("p", schema=ProfessionalLegalBrief, mode=AnswerMode.PROFESSIONAL)
        self.assertEqual(response.model_metadata.finish_reason, "STOP")

    def test_default_output_limit_is_2048(self) -> None:
        self.assertEqual(Settings.model_fields["legalai_llm_max_output_tokens"].default, 2048)


if __name__ == "__main__":
    unittest.main()
