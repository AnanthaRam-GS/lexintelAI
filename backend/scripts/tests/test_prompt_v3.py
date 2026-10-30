"""Step 22: prompt v3 (concision), prompt selection and the failure-record provider label (no network, no database)."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.api.query import prompt_builder  # noqa: E402
from backend.app.core.config import Settings  # noqa: E402
from backend.app.services.legal_answer_generation import (  # noqa: E402
    AnswerMode,
    ModelProviderError,
    build_grounded_evidence_packet,
    failed_provider_name,
    generate_legal_answer,
)
from backend.app.services.legal_answer_prompt import build_legal_answer_prompt  # noqa: E402
from backend.app.services.legal_answer_prompt_v2 import NO_COVERAGE_STATEMENT, V2_RULES, build_legal_answer_prompt_v2  # noqa: E402
from backend.app.services.legal_answer_prompt_v3 import (  # noqa: E402
    PROFESSIONAL_TARGET_OUTPUT_TOKENS,
    PROMPT_V3,
    PUBLIC_TARGET_OUTPUT_TOKENS,
    build_legal_answer_prompt_v3,
    concision_rules,
)
from backend.app.services.legal_query_understanding import understand_legal_query  # noqa: E402
from backend.scripts.tests.test_legal_answer_foundation import retrieval  # noqa: E402

MANIFEST = REPO_ROOT / "data/structured/manifests/legal_answer_eval.json"


def packet():
    return build_grounded_evidence_packet(understand_legal_query("bail"), retrieval())


def settings(**values) -> Settings:
    return Settings(_env_file=None, app_env="test", **values)


class PromptV3Tests(unittest.TestCase):
    def test_v3_keeps_every_v2_rule_and_section(self) -> None:
        for mode in (AnswerMode.PUBLIC, AnswerMode.PROFESSIONAL):
            with self.subTest(mode=mode):
                v3 = build_legal_answer_prompt_v3(packet(), mode=mode).prompt
                self.assertIn(V2_RULES, v3)
                self.assertIn(NO_COVERAGE_STATEMENT, v3)
                for block in ("<SYSTEM_RULES>", "<MODE_REQUIREMENTS>", "<GROUNDING_RULES>", "<LENGTH_RULES>", "<QUERY_CONTEXT>",
                              "<EVIDENCE_SET>", "<CITATION_POLICY>"):
                    self.assertIn(block, v3)
                # The private-PDF context is inserted before the evidence set, as for v2.
                self.assertIn("\n\n<EVIDENCE_SET>", v3)

    def test_v3_is_v2_plus_the_length_rules_only(self) -> None:
        for mode in (AnswerMode.PUBLIC, AnswerMode.PROFESSIONAL):
            with self.subTest(mode=mode):
                v2 = build_legal_answer_prompt_v2(packet(), mode=mode)
                v3 = build_legal_answer_prompt_v3(packet(), mode=mode)
                block = f"<LENGTH_RULES>\n\n{concision_rules(mode)}\n\n</LENGTH_RULES>\n\n"
                self.assertEqual(v3.prompt.replace(block, ""), v2.prompt)
                self.assertEqual(v3.answer_schema, v2.answer_schema)  # same output schema: no contract change

    def test_length_targets_per_mode(self) -> None:
        self.assertEqual((PUBLIC_TARGET_OUTPUT_TOKENS, PROFESSIONAL_TARGET_OUTPUT_TOKENS), (900, 1200))
        public = concision_rules(AnswerMode.PUBLIC)
        professional = concision_rules(AnswerMode.PROFESSIONAL)
        self.assertIn("under about 900 tokens (about 680 words)", public)
        self.assertIn("under about 1200 tokens (about 900 words)", professional)
        for rules in (public, professional):
            self.assertIn("State each point once", rules)
            self.assertIn("short bullet-style strings", rules)
            self.assertIn("leave the answer object's own citations list empty", rules)
            self.assertIn("give only case_name and source_url", rules)
            self.assertIn("never put a P# ID in a citation", rules)
            self.assertIn("the PRIVATE_DOCUMENT_MAP block", rules)
            self.assertNotIn("<PRIVATE_DOCUMENT_", rules)  # never the tag itself: it would read as a document map
            self.assertIn("do not restate them", rules)

    def test_v1_and_v2_stay_pinned(self) -> None:
        hashes = json.loads(MANIFEST.read_text())["component_hashes"]
        for path in ("backend/app/services/legal_answer_prompt.py", "backend/app/services/legal_answer_prompt_v2.py"):
            with self.subTest(path=path):
                self.assertEqual(hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest(), hashes[path])
        self.assertNotIn("<LENGTH_RULES>", build_legal_answer_prompt(packet(), mode=AnswerMode.PUBLIC).prompt)


class PromptSelectionTests(unittest.TestCase):
    def test_default_is_v3_and_v2_stays_selectable(self) -> None:
        self.assertEqual(prompt_builder(settings())[0], PROMPT_V3)
        self.assertEqual(prompt_builder(settings(legalai_prompt_version="V2"))[0], "legal_answer_prompt_v2")

    def test_v1_and_unknown_versions_are_refused(self) -> None:
        for version in ("v1", "v4", ""):
            with self.subTest(version=version), self.assertRaises(ValueError):
                prompt_builder(settings(legalai_prompt_version=version))


class RecordingAdapter:
    """Mocked model: records the prompt it receives and answers with one claim citing E1."""

    configured_model_id = "fixture"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_structured_answer(self, prompt, *, schema, mode):
        from backend.app.services.legal_answer_generation import LegalAnswerModelResponse, ModelGenerationMetadata

        self.prompts.append(prompt)
        body = {"answer": {"issue_summary": "s", "legal_regime": "ipc_crpc"}, "summary": "s",
                "claims": [{"claim_id": "c1", "text": "t", "claim_type": "CASE_LAW",
                            "citations": [{"evidence_id": "E1", "claim_id": "c1", "supported_text": "x"}]}]}
        return LegalAnswerModelResponse(raw_response=json.dumps(body), parsed_response=body,
                                        model_metadata=ModelGenerationMetadata(provider="fixture", configured_model_id="fixture", response_mode=mode))


def four_items():
    from backend.scripts.tests.test_legal_answer_foundation import evidence

    return retrieval([evidence(f"E{i}", f"Fixture text {i} about bail.") for i in range(1, 5)])


class PrivateEvidenceBudgetTests(unittest.TestCase):
    """Step 22: the lowest-ranked trusted evidence is trimmed before private (P#) evidence is cut."""

    def attempt(self, builder, adapter):
        from backend.app.api import query as query_api
        from backend.app.services.product_context_budget import resolve_product_context_budget

        return query_api._attempt_generation(
            query="bail", query_tokens=1, understanding=understand_legal_query("bail"), retrieval=four_items(),
            mode=AnswerMode.PROFESSIONAL, adapter=adapter, product_budget=resolve_product_context_budget(settings()),
            tier=query_api.ContextTier.NORMAL, private_context_builder=builder, prompt=query_api.PROMPT_BUILDERS["v3"],
        )

    def test_trusted_items_are_trimmed_until_the_private_context_fits_whole(self) -> None:
        from backend.app.api.query import PrivateContextDoesNotFit

        calls = []

        def builder(prompt_text, *, allow_partial=True):
            items = prompt_text.count('<EVIDENCE id="')
            calls.append((items, allow_partial))
            if items > 2 and not allow_partial:
                raise PrivateContextDoesNotFit(800, 300)
            return "<PRIVATE_DOCUMENT_MAP>whole map</PRIVATE_DOCUMENT_MAP>"

        adapter = RecordingAdapter()
        result, _tier, bounded = self.attempt(builder, adapter)
        self.assertEqual([item.citation_id for item in bounded.evidence], ["E1", "E2"])  # E4 then E3 dropped, by rank
        self.assertEqual(calls, [(4, False), (3, False), (2, False)])
        self.assertIn("whole map", adapter.prompts[-1])
        self.assertEqual(result.model_metadata.evidence_items_trimmed, 2)
        self.assertEqual(result.model_metadata.prompt_version, PROMPT_V3)

    def test_with_one_trusted_item_left_the_builder_may_shrink_the_private_context(self) -> None:
        from backend.app.api.query import PrivateContextDoesNotFit

        def builder(prompt_text, *, allow_partial=True):
            if not allow_partial:
                raise PrivateContextDoesNotFit(5000, 100)
            return "<PRIVATE_DOCUMENT_EVIDENCE>partial</PRIVATE_DOCUMENT_EVIDENCE>"

        adapter = RecordingAdapter()
        _result, _tier, bounded = self.attempt(builder, adapter)
        self.assertEqual([item.citation_id for item in bounded.evidence], ["E1"])
        self.assertIn("partial", adapter.prompts[-1])

    def test_the_map_builder_signals_then_refuses_only_when_it_cannot_shrink(self) -> None:
        from backend.app.api.query import PrivateContextDoesNotFit, QueryExecutionError, build_local_map_context_builder
        from backend.app.services.local_document_map import build_local_document_map
        from backend.app.services.token_budget import TokenBudget
        from backend.scripts.tests.brief_fixtures import fixture_private_chunks

        filename, chunks = fixture_private_chunks("fir")
        document_map = build_local_document_map(chunks, filename=filename, dense_provider=None, token_budget_tokens=5000)
        tight = TokenBudget(context_tokens=1000, reserved_output_tokens=0, safety_margin_tokens=0, private_pdf_ceiling_tokens=1500,
                            trusted_evidence_ceiling_tokens=4000)
        builder = build_local_map_context_builder(document_map, budget=tight)
        with self.assertRaises(PrivateContextDoesNotFit):
            builder("x " * 900, allow_partial=False)
        with self.assertRaises(QueryExecutionError) as refused:
            builder("x " * 900)
        self.assertEqual(refused.exception.code, "PDF_CONTEXT_TOO_LARGE")
        roomy = TokenBudget(context_tokens=10000, reserved_output_tokens=0, safety_margin_tokens=0, private_pdf_ceiling_tokens=1500,
                            trusted_evidence_ceiling_tokens=4000)
        self.assertIn("<PRIVATE_DOCUMENT_MAP", build_local_map_context_builder(document_map, budget=roomy)("x", allow_partial=False))


class GroqRoutingTests(unittest.TestCase):
    """Step 22: GROQ_PUBLIC_MODEL routes public answers to a separate model; professional answers keep GROQ_MODEL."""

    def generate(self, mode, **values):
        from unittest.mock import patch

        from backend.app.services.groq_answer_adapter import GroqAnswerAdapter
        from backend.app.services.legal_answer_generation import ProfessionalLegalBrief, PublicLegalAnswer
        from backend.scripts.tests.test_groq_answer_adapter import FakeHttpResponse, groq_payload

        body = groq_payload()
        body["choices"][0]["finish_reason"] = "stop"
        body.pop("model", None)
        base = dict(groq_api_key="k", groq_model="openai/gpt-oss-120b", legalai_groq_reasoning_effort="low")
        adapter = GroqAnswerAdapter(settings(**{**base, **values}))
        schema = PublicLegalAnswer if mode == AnswerMode.PUBLIC else ProfessionalLegalBrief
        with patch("urllib.request.urlopen", return_value=FakeHttpResponse(body)) as urlopen:
            response = adapter.generate_structured_answer("p", schema=schema, mode=mode)
        return json.loads(urlopen.call_args.args[0].data), response.model_metadata

    def test_public_answers_go_to_the_public_model(self) -> None:
        sent, metadata = self.generate(AnswerMode.PUBLIC, groq_public_model="openai/gpt-oss-20b")
        self.assertEqual((sent["model"], sent["reasoning_effort"]), ("openai/gpt-oss-20b", "low"))
        self.assertEqual(metadata.configured_model_id, "openai/gpt-oss-20b")

    def test_professional_answers_keep_the_main_model(self) -> None:
        sent, metadata = self.generate(AnswerMode.PROFESSIONAL, groq_public_model="openai/gpt-oss-20b")
        self.assertEqual(sent["model"], "openai/gpt-oss-120b")
        self.assertEqual(metadata.configured_model_id, "openai/gpt-oss-120b")

    def test_no_public_model_means_one_model(self) -> None:
        for mode in (AnswerMode.PUBLIC, AnswerMode.PROFESSIONAL):
            with self.subTest(mode=mode):
                self.assertEqual(self.generate(mode)[0]["model"], "openai/gpt-oss-120b")

    def test_reasoning_effort_follows_the_routed_model(self) -> None:
        sent, _ = self.generate(AnswerMode.PUBLIC, groq_public_model="qwen/qwen3.8-27b")
        self.assertEqual(sent["model"], "qwen/qwen3.8-27b")
        self.assertNotIn("reasoning_effort", sent)


ENV_EXAMPLE = REPO_ROOT / ".env.example"


def env_example() -> dict[str, str]:
    values = {}
    for line in ENV_EXAMPLE.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


class GroqBudgetArithmeticTests(unittest.TestCase):
    """Step 22: the documented Groq budget fits the 8,000-token per-request limit."""

    def test_guard_arithmetic(self) -> None:
        from backend.app.api.query import RequestSizeGuard
        from backend.app.services.groq_answer_adapter import groq_payload_schema
        from backend.app.services.legal_answer_generation import PublicLegalAnswer
        from backend.app.services.token_budget import estimate_tokens

        guard = RequestSizeGuard(ceiling_tokens=8000, max_output_tokens=2048, estimate_factor=1.51)
        schema_tokens = estimate_tokens(json.dumps(groq_payload_schema(PublicLegalAnswer)))
        prompt = "word " * 2000
        expected = round((estimate_tokens(prompt) + schema_tokens) * 1.51) + 2048
        self.assertEqual(guard.estimated_request_tokens(prompt, AnswerMode.PUBLIC), expected)
        self.assertEqual(guard.fits(prompt, AnswerMode.PUBLIC), expected <= 8000)
        # The largest estimate the guard admits leaves the whole output limit inside the ceiling.
        largest = (8000 - 2048) / 1.51
        self.assertLessEqual(round(largest * 1.51) + 2048, 8000)

    def test_env_example_budget_is_consistent(self) -> None:
        env = env_example()
        ceiling = int(env["LEGALAI_GROQ_MAX_REQUEST_TOKENS"])
        max_output = int(env["LEGALAI_LLM_MAX_OUTPUT_TOKENS"])
        self.assertEqual(ceiling, 8000)
        # The output reserve is the real output limit, and the v3 targets leave headroom under it.
        self.assertEqual(int(env["LEGALAI_LLM_RESERVED_OUTPUT_TOKENS"]), max_output)
        self.assertGreater(max_output, PROFESSIONAL_TARGET_OUTPUT_TOKENS)
        # The product budget never promises more than one request can carry.
        self.assertLessEqual(int(env["LEGALAI_PRODUCT_MAX_INPUT_TOKENS"]), ceiling)
        available = int(env["LEGALAI_PRODUCT_MAX_INPUT_TOKENS"]) - max_output - int(env["LEGALAI_LLM_CONTEXT_SAFETY_MARGIN_TOKENS"])
        self.assertGreaterEqual(available, int(env["PRIVATE_PDF_INPUT_BUDGET_TOKENS"]))
        self.assertEqual(env["LEGALAI_PROMPT_VERSION"], "v3")


class FailingAdapter:
    configured_model_id = "m"

    def __init__(self, code: str) -> None:
        self.code = code

    def generate_structured_answer(self, prompt, *, schema, mode):
        raise ModelProviderError(self.code, "failed")


class FailureProviderLabelTests(unittest.TestCase):
    """Step 22: the failure record names the provider that failed (it was always "gemini")."""

    def test_the_failed_provider_is_recorded(self) -> None:
        understanding = understand_legal_query("bail")
        for code, provider in (("GROQ_OUTPUT_TRUNCATED", "groq"), ("NVIDIA_TIMEOUT", "nvidia"), ("OLLAMA_PROVIDER_ERROR", "ollama"),
                               ("GEMINI_RATE_LIMIT", "gemini"), ("OPENROUTER_AUTH_ERROR", "openrouter")):
            with self.subTest(code=code):
                result = generate_legal_answer(understanding, retrieval(), mode=AnswerMode.PUBLIC, adapter=FailingAdapter(code), prompt="p")
                self.assertEqual(result.model_metadata.provider, provider)
                self.assertEqual(result.warnings[0].code, code)
                self.assertTrue(result.summary.startswith(f"{provider.capitalize()} generation failed"))

    def test_an_unprefixed_code_is_unknown(self) -> None:
        self.assertEqual(failed_provider_name(ModelProviderError("TIMEOUT", "x")), "unknown")
        self.assertEqual(failed_provider_name(ModelProviderError("_X", "x")), "unknown")


if __name__ == "__main__":
    unittest.main()
