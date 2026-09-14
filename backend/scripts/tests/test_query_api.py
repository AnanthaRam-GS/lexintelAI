"""Tests for public and professional LegalAI query API wiring."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.app.api import query as query_api
from backend.app.core.dependencies import get_current_user
from backend.app.db.session import get_db
from backend.app.services.legal_answer_generation import (
    AnswerMode,
    GroundedCitation,
    GroundingStatus,
    LegalAnswerResult,
    LegalAnswerWarning,
    ModelGenerationMetadata,
    ProfessionalLegalBrief,
    PublicLegalAnswer,
    RetrievedAuthority,
)
from backend.main import app


class QueryApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        app.dependency_overrides[query_api.get_retrieval_service] = lambda: object()
        app.dependency_overrides[query_api.get_answer_adapter] = lambda: object()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_public_query_requires_no_auth_and_does_not_save_history(self) -> None:
        result = public_result()
        with patch.object(query_api, "run_frozen_query_pipeline", return_value=result) as pipeline, patch.object(
            query_api, "save_query_history"
        ) as save_history:
            response = self.client.post("/query/public", json={"text": "Can the police arrest me without notice?"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            body,
            {
                "explanation": "You may have procedural protections.",
                "sections": [
                    {
                        "title": "BNSS section 35",
                        "explanation": "Applicability depends on the specific facts and documents.",
                        "link": "https://www.indiacode.nic.in/",
                    }
                ],
                "sources": [{"title": "Example v State", "link": "https://example.test/judgment"}],
                "nextStepGuidance": "Preserve papers Speak to a lawyer",
            },
        )
        self.assertNotIn("model_metadata", body)
        self.assertNotIn("evidence_retrieved", body)
        pipeline.assert_called_once()
        self.assertEqual(pipeline.call_args.kwargs["mode"], AnswerMode.PUBLIC)
        save_history.assert_not_called()

    def test_public_query_validates_request_body(self) -> None:
        response = self.client.post("/query/public", json={"text": ""})
        self.assertEqual(response.status_code, 422)

    def test_public_query_maps_pipeline_failure_without_internal_detail(self) -> None:
        with patch.object(
            query_api,
            "run_frozen_query_pipeline",
            side_effect=query_api.QueryExecutionError(
                "MODEL_UNAVAILABLE",
                "The legal answer model is temporarily unavailable.",
                503,
            ),
        ):
            response = self.client.post("/query/public", json={"text": "Help"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "MODEL_UNAVAILABLE")
        self.assertNotIn("api-key", str(response.json()).lower())

    def test_professional_query_requires_authentication(self) -> None:
        response = self.client.post("/query/professional", json={"text": "Research bail under BNSS"})
        self.assertEqual(response.status_code, 401)

    def test_professional_query_rejects_wrong_role(self) -> None:
        app.dependency_overrides[get_db] = lambda: Mock()
        app.dependency_overrides[get_current_user] = lambda: user(role="public")
        response = self.client.post("/query/professional", json={"text": "Research bail under BNSS"})
        self.assertEqual(response.status_code, 403)

    def test_professional_query_accepts_lawyer_and_saves_successful_history(self) -> None:
        fake_db = Mock()
        app.dependency_overrides[get_db] = lambda: fake_db
        app.dependency_overrides[get_current_user] = lambda: user(role="lawyer")
        result = professional_result()
        with patch.object(query_api, "run_frozen_query_pipeline", return_value=result) as pipeline, patch.object(
            query_api, "save_query_history"
        ) as save_history:
            response = self.client.post(
                "/query/professional",
                json={"text": "Prepare bail research", "session_id": "session-1"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["case_brief"]["summary"], "Bail research brief")
        self.assertEqual(body["precedents"][0]["case_name"], "Example v State")
        self.assertNotIn("retrieved full chunk body", str(body))
        pipeline.assert_called_once()
        self.assertEqual(pipeline.call_args.kwargs["mode"], AnswerMode.PROFESSIONAL)
        save_history.assert_called_once()
        self.assertEqual(save_history.call_args.kwargs["query_text"], "Prepare bail research")
        self.assertEqual(save_history.call_args.kwargs["user_id"], 42)
        self.assertEqual(save_history.call_args.kwargs["generation_backend"], "mock")

    def test_professional_query_does_not_save_failed_generation(self) -> None:
        app.dependency_overrides[get_db] = lambda: Mock()
        app.dependency_overrides[get_current_user] = lambda: user(role="admin")
        with patch.object(
            query_api,
            "run_frozen_query_pipeline",
            side_effect=query_api.QueryExecutionError("MODEL_OUTPUT_VALIDATION_FAILED", "Bad structured answer.", 502),
        ), patch.object(query_api, "save_query_history") as save_history:
            response = self.client.post("/query/professional", json={"text": "Research"})

        self.assertEqual(response.status_code, 502)
        save_history.assert_not_called()

    def test_query_routes_are_registered(self) -> None:
        routes = {route.path for route in app.routes}
        self.assertIn("/query/public", routes)
        self.assertIn("/query/professional", routes)


def user(*, role: str):
    return type("UserStub", (), {"id": 42, "role": role})()


def metadata(mode: AnswerMode) -> ModelGenerationMetadata:
    return ModelGenerationMetadata(provider="mock", configured_model_id="mock-model", response_mode=mode)


def citation() -> GroundedCitation:
    return GroundedCitation(
        evidence_id="E1",
        claim_id="C1",
        supported_text="supported",
        source_metadata={"case_name": "Example v State", "source_url": "https://example.test/judgment"},
    )


def public_result() -> LegalAnswerResult:
    answer = PublicLegalAnswer(
        summary="You may have procedural protections.",
        possible_legal_provisions=["BNSS section 35"],
        possible_next_steps=["Preserve papers", "Speak to a lawyer"],
        citations=[citation()],
    )
    return LegalAnswerResult(
        query="query",
        mode=AnswerMode.PUBLIC,
        answer=answer,
        summary=answer.summary,
        citations=[citation()],
        grounding_status=GroundingStatus.STRUCTURALLY_GROUNDED,
        evidence_used=["E1"],
        evidence_retrieved=["E1"],
        model_metadata=metadata(AnswerMode.PUBLIC),
        query_understanding_version="test-understanding",
        retrieval_version="test-retrieval",
    )


def professional_result() -> LegalAnswerResult:
    answer = ProfessionalLegalBrief(
        issue_summary="Bail research brief",
        explicit_legal_provisions=["BNSS section 480"],
        legal_regime="BNSS",
        retrieved_authorities=[
            RetrievedAuthority(
                evidence_id="E1",
                document_id="doc-1",
                case_name="Example v State",
                court={"name": "Example Court"},
                judgment_date="2024-01-02",
                source_url="https://example.test/judgment",
                paragraph_start=3,
                paragraph_end=5,
            )
        ],
        legal_issues=["Bail"],
        applicable_principles=["Grounded principle"],
        analysis=["Grounded analysis"],
    )
    return LegalAnswerResult(
        query="query",
        mode=AnswerMode.PROFESSIONAL,
        answer=answer,
        summary=answer.issue_summary,
        citations=[citation()],
        grounding_status=GroundingStatus.STRUCTURALLY_GROUNDED,
        warnings=[LegalAnswerWarning(code="BENIGN", message="test")],
        evidence_used=["E1"],
        evidence_retrieved=["E1"],
        model_metadata=metadata(AnswerMode.PROFESSIONAL),
        query_understanding_version="test-understanding",
        retrieval_version="test-retrieval",
    )


if __name__ == "__main__":
    unittest.main()
