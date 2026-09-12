"""Mocked tests for the Phase 0.9C-B grounded answer generation harness.

No test in this module makes a live Gemini/network call; the Gemini adapter
and retrieval service are always substituted with in-memory fakes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    ClaimType,
    GroundedCitation,
    GroundedLegalClaim,
    GroundingStatus,
    LegalAnswerModelResponse,
    ModelGenerationMetadata,
    ModelProviderError,
    ModelUnavailableError,
)
from backend.app.services.legal_rag_retrieval import (
    CitationMetadata,
    LegalEvidenceChunk,
    LegalRetrievalResult,
    RetrievalStageCounts,
    RetrievalTimings,
)
from backend.scripts import run_grounded_answer_eval_generation as harness


ROOT = Path(__file__).resolve().parents[3]
MODULE = "backend.scripts.run_grounded_answer_eval_generation"


def make_evidence(evidence_id: str, text: str = "Fixture judgment text.") -> LegalEvidenceChunk:
    citation = CitationMetadata(
        citation_id=evidence_id,
        chunk_id=f"doc:{evidence_id}",
        document_id="doc-1",
        judgment_id="doc-1",
        case_name="Fixture v State",
        court={"court_name": "Supreme Court of India"},
        date="2025-01-01",
        source_url="https://example.test/fixture",
        paragraph_start=1,
        paragraph_end=2,
    )
    return LegalEvidenceChunk(
        rank=1,
        citation_id=evidence_id,
        chunk_id=citation.chunk_id,
        document_id=citation.document_id,
        judgment_id=citation.judgment_id,
        text=text,
        paragraph_start=1,
        paragraph_end=2,
        citation_metadata=citation,
    )


def make_retrieval(query: str, evidence_ids: list[str]) -> LegalRetrievalResult:
    items = [make_evidence(eid, f"Text for {eid} matching {query}") for eid in evidence_ids]
    return LegalRetrievalResult(
        query=query,
        query_understanding_version="legalai-query-understanding-v1",
        understanding_summary={},
        evidence=items,
        stage_counts=RetrievalStageCounts(
            bm25_returned=len(items),
            dense_returned=len(items),
            rrf_unique_candidates=len(items),
            reranker_candidates=len(items),
            final_evidence_count=len(items),
        ),
        timings=RetrievalTimings(),
    )


def cited_claim(evidence_id: str = "E1") -> GroundedLegalClaim:
    citation = GroundedCitation(
        evidence_id=evidence_id,
        claim_id="c1",
        supported_text="Supported proposition.",
        source_metadata={},
    )
    return GroundedLegalClaim(
        claim_id="c1",
        text="A grounded proposition.",
        claim_type=ClaimType.CASE_LAW,
        citations=[citation],
        grounding_status=GroundingStatus.STRUCTURALLY_GROUNDED,
    )


class FakeAdapter:
    """Stands in for GeminiAnswerAdapter; retry policy is exercised inside the real adapter, not here."""

    def __init__(self, outcome="success", citations_claim=None, model="fixture-model"):
        self.outcome = outcome
        self.claim = citations_claim or cited_claim()
        self.configured_model_id = model
        self.calls = 0

    def generate_structured_answer(self, prompt, *, schema, mode):
        self.calls += 1
        if self.outcome == "unavailable":
            raise ModelUnavailableError("fixture unavailable")
        if self.outcome == "provider_error":
            error = ModelProviderError("GEMINI_RATE_LIMIT", "rate limited", http_status=429)
            error.attempt_count = 3
            error.retry_count = 2
            error.retry_reasons = ["HTTP_429", "HTTP_429"]
            error.final_provider_status = "HTTP_429"
            raise error
        metadata = ModelGenerationMetadata(
            provider="gemini",
            configured_model_id=self.configured_model_id,
            actual_model_id=self.configured_model_id,
            response_mode=mode,
            fallback_used=False,
            attempt_count=1,
            retry_count=0,
        )
        if self.outcome == "bad_schema":
            return LegalAnswerModelResponse(raw_response="not-json", parsed_response=None, model_metadata=metadata)
        answer_fields = {
            "summary": "Fixture summary.",
            "citations": [item.model_dump(mode="json") for item in self.claim.citations],
        }
        if schema.__name__ == "PublicLegalAnswer":
            answer_fields.update(
                what_this_may_mean=["depends on facts"],
                possible_legal_provisions=[],
                possible_next_steps=[],
                important_cautions=[],
            )
        else:
            answer_fields.update(
                issue_summary="Fixture issue.",
                material_facts_from_query=[],
                explicit_legal_provisions=[],
                potential_additional_provisions=[],
                procedural_posture=[],
                legal_regime="ipc_crpc",
                retrieved_authorities=[],
                legal_issues=[],
                applicable_principles=[],
                analysis=[],
                counterpoints=[],
                uncertainties=[],
                recommended_research_questions=[],
            )
        payload = {"answer": answer_fields, "claims": [self.claim.model_dump(mode="json")], "summary": "Fixture summary."}
        return LegalAnswerModelResponse(
            raw_response=json.dumps(payload),
            parsed_response=payload,
            model_metadata=metadata,
        )


class GenerationHarnessTests(unittest.TestCase):
    def test_dry_run_makes_zero_model_calls(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "backend/scripts/run_grounded_answer_eval_generation.py"), "--dry-run"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "DRY_RUN_ONLY")
        self.assertFalse(payload["live_generation_executed"])
        self.assertEqual(payload["llm_calls"], 0)
        self.assertEqual(payload["planned_outputs"], 60)
        self.assertEqual(payload["example_count"], 30)

    def test_llm_only_has_no_retrieval_and_no_corpus_metadata(self) -> None:
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")
        with patch(f"{MODULE}.understand_legal_query") as mocked_understand, patch(
            f"{MODULE}.retrieve_legal_evidence"
        ) as mocked_retrieve, patch(f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter()):
            record = harness.generate_llm_only_record("ans-q001", "A murder query", AnswerMode.PUBLIC, settings)
            mocked_understand.assert_not_called()
            mocked_retrieve.assert_not_called()
        self.assertEqual(record["retrieval_count"], 0)
        self.assertEqual(record["evidence_ids"], [])
        self.assertEqual(record["generation_status"], "SUCCESS")

    def test_llm_only_prompt_contains_no_evidence_block(self) -> None:
        prompt = harness.build_llm_only_prompt("Some query", AnswerMode.PUBLIC)
        self.assertNotIn('<EVIDENCE id="', prompt)
        self.assertIn("NO_RETRIEVED_EVIDENCE_AVAILABLE_IN_THIS_CONDITION", prompt)
        self.assertIn("Some query", prompt)

    def test_grounded_rag_receives_retrieval_evidence(self) -> None:
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")
        retrieval = make_retrieval("query one", ["E1", "E2"])
        with patch(f"{MODULE}.retrieve_legal_evidence", return_value=retrieval), patch(
            f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter()
        ):
            record = harness.generate_grounded_rag_record("ans-q001", "query one", AnswerMode.PUBLIC, settings, service=object())
        self.assertEqual(record["retrieval_count"], 2)
        self.assertEqual(record["evidence_ids"], ["E1", "E2"])
        self.assertEqual(record["generation_status"], "SUCCESS")

    def test_evidence_isolation_between_examples(self) -> None:
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")

        def fake_retrieve(understanding, *, retrieval_service):
            return make_retrieval(understanding.query, ["E1"] if understanding.query == "query one" else ["E5", "E6"])

        with patch(f"{MODULE}.retrieve_legal_evidence", side_effect=fake_retrieve), patch(
            f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter(citations_claim=cited_claim("E1"))
        ):
            record_one = harness.generate_grounded_rag_record("ans-q001", "query one", AnswerMode.PUBLIC, settings, service=object())
            record_two = harness.generate_grounded_rag_record("ans-q002", "query two", AnswerMode.PUBLIC, settings, service=object())
        self.assertEqual(record_one["evidence_ids"], ["E1"])
        self.assertEqual(record_two["evidence_ids"], ["E5", "E6"])
        self.assertNotEqual(set(record_one["evidence_ids"]), set(record_two["evidence_ids"]))

    def test_condition_isolation_llm_only_signature_excludes_retrieval(self) -> None:
        import inspect

        params = list(inspect.signature(harness.generate_llm_only_record).parameters)
        self.assertNotIn("retrieval", params)
        self.assertNotIn("service", params)

    def test_same_provider_and_model_across_conditions(self) -> None:
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")
        retrieval = make_retrieval("q", ["E1"])
        with patch(f"{MODULE}.retrieve_legal_evidence", return_value=retrieval), patch(
            f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter(model=settings.gemini_model)
        ):
            grounded = harness.generate_grounded_rag_record("ans-q001", "q", AnswerMode.PUBLIC, settings, service=object())
        with patch(f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter(model=settings.gemini_model)):
            llm_only = harness.generate_llm_only_record("ans-q001", "q", AnswerMode.PUBLIC, settings)
        self.assertEqual(grounded["provider"], llm_only["provider"])
        self.assertEqual(grounded["configured_model"], llm_only["configured_model"])
        self.assertEqual(grounded["provider"], "gemini")

    def test_bounded_retries_are_delegated_to_adapter_not_reimplemented(self) -> None:
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")
        fake = FakeAdapter(outcome="provider_error")
        with patch(f"{MODULE}.GeminiAnswerAdapter", return_value=fake):
            record = harness.generate_llm_only_record("ans-q001", "q", AnswerMode.PUBLIC, settings)
        self.assertEqual(fake.calls, 1, "harness must call the adapter exactly once and rely on its internal retry loop")
        self.assertEqual(record["generation_status"], "FAILED_PROVIDER")
        self.assertEqual(record["provider_attempt_count"], 3)
        self.assertEqual(record["retry_count"], 2)
        self.assertEqual(record["retry_reasons"], ["HTTP_429", "HTTP_429"])

    def test_model_unavailable_is_recorded_not_crashed(self) -> None:
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")
        with patch(f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter(outcome="unavailable")):
            record = harness.generate_llm_only_record("ans-q001", "q", AnswerMode.PUBLIC, settings)
        self.assertEqual(record["generation_status"], "MODEL_UNAVAILABLE")
        self.assertIsNone(record["answer_structured"])

    def test_schema_failure_is_recorded_explicitly(self) -> None:
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")
        with patch(f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter(outcome="bad_schema")):
            record = harness.generate_llm_only_record("ans-q001", "q", AnswerMode.PUBLIC, settings)
        self.assertEqual(record["generation_status"], "FAILED_SCHEMA")

    def test_no_ollama_fallback(self) -> None:
        source = (ROOT / "backend/scripts/run_grounded_answer_eval_generation.py").read_text(encoding="utf-8")
        self.assertNotIn("Ollama", source)
        settings = Settings(gemini_api_key="fixture-key", gemini_model="fixture-model")
        with patch(f"{MODULE}.GeminiAnswerAdapter", return_value=FakeAdapter()):
            record = harness.generate_llm_only_record("ans-q001", "q", AnswerMode.PUBLIC, settings)
        self.assertFalse(record["fallback_used"])

    def test_run_id_is_stable_and_frozen(self) -> None:
        self.assertEqual(harness.RUN_ID, "legalai-answer-eval-generation-v1")
        manifest = json.loads((ROOT / "data/structured/manifests/legal_answer_eval.json").read_text(encoding="utf-8"))
        settings = Settings(gemini_model="fixture-model")
        metadata_one = harness.build_run_metadata(manifest, settings, "2026-01-01T00:00:00+00:00", None)
        metadata_two = harness.build_run_metadata(manifest, settings, "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00")
        self.assertEqual(metadata_one["run_id"], metadata_two["run_id"])

    def test_resume_skips_already_successful_slots(self) -> None:
        existing_outputs = [
            {"example_id": "ans-q001", "condition": "LLM_ONLY", "generation_status": "SUCCESS"},
            {"example_id": "ans-q001", "condition": "GROUNDED_RAG", "generation_status": "FAILED_PROVIDER"},
        ]
        completed = harness.completed_keys_from_outputs(existing_outputs)
        self.assertEqual(completed, {("ans-q001", "LLM_ONLY")})
        self.assertNotIn(("ans-q001", "GROUNDED_RAG"), completed)

    def test_pair_map_untouched_by_review_packet_population(self) -> None:
        pair_map_path = ROOT / "data/structured/manifests/legal_answer_eval_pair_map.json"
        before = hashlib.sha256(pair_map_path.read_bytes()).hexdigest()
        manifest = json.loads((ROOT / "data/structured/manifests/legal_answer_eval.json").read_text(encoding="utf-8"))
        outputs_manifest = {"outputs": []}
        with patch.object(harness, "REVIEW_PACKET_PATH", ROOT / "backend/scripts/tests/_tmp_review_packet.md"):
            harness.populate_review_packet(manifest, outputs_manifest)
            harness.REVIEW_PACKET_PATH.unlink(missing_ok=True)
        after = hashlib.sha256(pair_map_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_review_packet_conceals_condition_labels(self) -> None:
        manifest = json.loads((ROOT / "data/structured/manifests/legal_answer_eval.json").read_text(encoding="utf-8"))
        outputs_manifest = {
            "outputs": [
                {
                    "example_id": "ans-q001",
                    "condition": "LLM_ONLY",
                    "generation_status": "SUCCESS",
                    "summary": "Fixture summary.",
                    "answer_structured": {"summary": "x", "citations": []},
                },
                {
                    "example_id": "ans-q001",
                    "condition": "GROUNDED_RAG",
                    "generation_status": "SUCCESS",
                    "summary": "Fixture summary.",
                    "answer_structured": {"summary": "x", "citations": []},
                },
            ]
        }
        tmp_path = ROOT / "backend/scripts/tests/_tmp_review_packet_blinding.md"
        with patch.object(harness, "REVIEW_PACKET_PATH", tmp_path):
            harness.populate_review_packet(manifest, outputs_manifest)
            content = tmp_path.read_text(encoding="utf-8")
            tmp_path.unlink(missing_ok=True)
        self.assertNotIn("LLM_ONLY", content)
        self.assertNotIn("GROUNDED_RAG", content)
        self.assertIn("Answer A", content)
        self.assertIn("Answer B", content)

    def test_human_reviews_untouched_by_generation_module(self) -> None:
        source = (ROOT / "backend/scripts/run_grounded_answer_eval_generation.py").read_text(encoding="utf-8")
        self.assertNotIn("legal_answer_eval_reviews.json", source)

    def test_output_json_round_trips(self) -> None:
        tmp_path = ROOT / "backend/scripts/tests/_tmp_outputs.json"
        with patch.object(harness, "OUTPUTS_PATH", tmp_path):
            harness.write_outputs(
                [{"example_id": "ans-q001", "condition": "LLM_ONLY", "generation_status": "SUCCESS"}],
                {"run_id": harness.RUN_ID},
                "in_progress",
            )
            loaded = json.loads(tmp_path.read_text(encoding="utf-8"))
            tmp_path.unlink(missing_ok=True)
        self.assertEqual(loaded["generation_status"], "in_progress")
        self.assertEqual(len(loaded["outputs"]), 1)

    def test_generation_status_helper_maps_result_states(self) -> None:
        from types import SimpleNamespace

        success = SimpleNamespace(answer=object(), warnings=[])
        self.assertEqual(harness.generation_status_from_result(success), "SUCCESS")

        insufficient = SimpleNamespace(answer=None, warnings=[SimpleNamespace(code="INSUFFICIENT_RETRIEVED_AUTHORITY")])
        self.assertEqual(harness.generation_status_from_result(insufficient), "INSUFFICIENT_RETRIEVED_AUTHORITY")

        schema_failed = SimpleNamespace(answer=None, warnings=[SimpleNamespace(code="MODEL_OUTPUT_VALIDATION_FAILED")])
        self.assertEqual(harness.generation_status_from_result(schema_failed), "FAILED_SCHEMA")

    def test_never_imports_live_network_client_at_call_site(self) -> None:
        # Guards against accidental direct urllib usage bypassing GeminiAnswerAdapter in this module.
        source = (ROOT / "backend/scripts/run_grounded_answer_eval_generation.py").read_text(encoding="utf-8")
        self.assertNotIn("urllib", source)


if __name__ == "__main__":
    unittest.main()
