"""OCR fallback through the API and admin ingestion (RAG-005), against the isolated test DB.

No live LLM: the brief and public answers come from mocked adapters. Ingestion
writes only to the test database and to temporary Chroma/BM25 stores (copies,
never dev). Tests that run Tesseract are skipped, with the reason, when it is
not installed; the acceptance run must have it.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from fastapi.testclient import TestClient

from backend.app.api import query as query_api
from backend.app.core.config import Settings
from backend.app.db.models import Document
from backend.app.models.ingest import IngestionStatus
from backend.app.services import ingestion, ocr as ocr_service
from backend.app.services.chunker import chunk_document
from backend.app.services.document_parser import parse_document
from backend.app.services.legal_answer_generation import LegalAnswerModelResponse, ModelGenerationMetadata
from backend.app.services.private_pdf_rag import build_private_chunks
from backend.main import app
from backend.scripts.tests.brief_fixtures import expected as expected_brief
from backend.scripts.tests.ocr_fixtures import OCR_FIXTURE_DIR
# Modules, not classes: a test class imported by name would be collected and run again here.
from backend.scripts.tests import test_ingest as ingest_tests
from backend.scripts.tests import test_query_api as query_tests
from backend.scripts.tests.test_query_api import MOCK_POSTURE, _REFERENCE, _flat, mock_claims, pdf_upload

TESSERACT = ocr_service.tesseract_status(Settings())
REQUIRES_TESSERACT = unittest.skipUnless(
    TESSERACT.get("available"), f"Tesseract OCR is not available: {TESSERACT.get('reason')}. Install it (docs/OCR.md) to run these tests."
)
EVIDENCE_LABELS = {"witnesses": "Witnesses", "documents": "Documents", "medical_forensic": "Medical/forensic", "electronic": "Electronic", "recoveries": "Recoveries/seizures"}


def fixture_bytes(name: str) -> bytes:
    return (OCR_FIXTURE_DIR / name).read_bytes()


def scanned_private_chunk_texts(name: str) -> dict[str, str]:
    """P# chunk texts of a scanned fixture, through the same OCR parser, chunker and wrapper as an upload."""
    document = parse_document(OCR_FIXTURE_DIR / name, ocr_profile="query")
    document["source_file_name"] = name
    return {chunk.private_chunk_id: _flat(chunk.text) for chunk in build_private_chunks(chunk_document(document))}


class PublicStubAdapter:
    calls = 0

    def generate_structured_answer(self, prompt, *, schema, mode):
        PublicStubAdapter.calls += 1
        answer = {"summary": "MOCK PUBLIC SUMMARY", "what_this_may_mean": [], "possible_legal_provisions": [], "possible_next_steps": [],
                  "important_cautions": [], "citations": []}
        return LegalAnswerModelResponse(
            raw_response="{}",
            parsed_response={"answer": answer, "summary": "MOCK PUBLIC SUMMARY", "claims": mock_claims()},
            model_metadata=ModelGenerationMetadata(provider="mock", configured_model_id="mock-model", response_mode=mode),
        )


@REQUIRES_TESSERACT
class ScannedBriefTests(query_tests.ProfessionalBriefPipelineTests):
    """The scanned FIR through the professional brief upload, with the mocked brief adapter."""

    # Reuse the brief pipeline's mocked retrieval and adapter, not its own fixture tests.
    for _name in [name for name in dir(query_tests.ProfessionalBriefPipelineTests) if name.startswith("test_")]:
        locals()[_name] = None

    def upload(self, filename: str, *, mode: str = "brief", path: str = "/query/professional/pdf"):
        with patch.object(query_api, "save_query_history"):
            return self.client.post(
                path,
                data={"query": "Prepare a case brief for this document.", "analysis_mode": mode},
                files=pdf_upload(filename=filename, body=fixture_bytes(filename)),
            )

    def test_scanned_fir_brief_matches_the_fir_expected_output(self) -> None:
        response = self.upload("fir_scanned.pdf")
        self.assertEqual(response.status_code, 200, response.text)
        brief = response.json()["case_brief"]
        expectation = expected_brief("fir")
        chunk_texts = scanned_private_chunk_texts("fir_scanned.pdf")

        detected = re.search(r'<PRIVATE_DOCUMENT_MAP document_type="([^"]+)"', self.adapter.prompts[-1]).group(1)
        self.assertEqual(detected, expectation["document_type"])
        parties = brief["parties_and_roles"]
        for party in expectation["parties"]:
            self.assertTrue(any(item.lower().startswith(f"{party['role']}:") and party["name"].lower() in item.lower() for item in parties), parties)
        self.assertEqual(len(parties), len(expectation["parties"]), parties)
        self.assert_references_resolve(parties, chunk_texts, name="fir_scanned", field="parties_and_roles")

        dates = [item.split(" - ", 1)[0] for item in brief["chronology"]]
        self.assertEqual(dates, sorted(dates))
        self.assertTrue(set(expectation["dated_events"]) <= set(dates), dates)
        self.assert_references_resolve(brief["chronology"], chunk_texts, name="fir_scanned", field="chronology")

        stages = {label.strip().lower() for item in brief["procedural_considerations"] if _REFERENCE.search(item) for label in item.split(": ", 1)[0].split(";")}
        self.assertTrue({stage.lower() for stage in expectation["procedural_stages"]} <= stages, stages)
        self.assertIn(MOCK_POSTURE[0], brief["procedural_considerations"])

        categories = {label.strip() for item in brief["evidence_identified"] for label in item.split(": ", 1)[0].split(",")}
        self.assertTrue({EVIDENCE_LABELS[c] for c in expectation["evidence_categories"]} <= categories, categories)
        self.assertFalse({EVIDENCE_LABELS[c] for c in expectation["absent_evidence_categories"]} & categories, categories)
        self.assert_references_resolve(brief["evidence_identified"], chunk_texts, name="fir_scanned", field="evidence_identified")
        # A clean scan (mean confidence ~95) carries no OCR warning.
        self.assertNotIn(query_api.OCR_LOW_CONFIDENCE_LIMITATION, brief["limitations"])

    def test_degraded_scan_adds_the_ocr_limitation_to_the_brief(self) -> None:
        response = self.upload("fir_degraded_scan.pdf")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(query_api.OCR_LOW_CONFIDENCE_LIMITATION, response.json()["case_brief"]["limitations"])

    def test_degraded_scan_adds_the_ocr_limitation_to_the_public_answer(self) -> None:
        app.dependency_overrides[query_api.get_answer_adapter] = lambda: PublicStubAdapter()
        response = self.client.post(
            "/query/public/pdf",
            data={"query": "What does this complaint say happened?"},
            files=pdf_upload(filename="fir_degraded_scan.pdf", body=fixture_bytes("fir_degraded_scan.pdf")),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["limitations"], [query_api.OCR_LOW_CONFIDENCE_LIMITATION])
        clean = self.client.post(
            "/query/public/pdf",
            data={"query": "What does this complaint say happened?"},
            files=pdf_upload(filename="fir_scanned.pdf", body=fixture_bytes("fir_scanned.pdf")),
        )
        self.assertEqual(clean.json()["limitations"], [])

    def test_over_cap_scan_returns_ocr_limit_exceeded_without_a_provider_call(self) -> None:
        calls_before = self.adapter.calls
        for path in ("/query/professional/pdf", "/query/public/pdf"):
            with self.subTest(path=path):
                response = self.upload("over_cap_scanned.pdf", path=path)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["code"], "OCR_LIMIT_EXCEEDED")
                self.assertIn("up to 10 scanned pages", response.json()["error"])
        self.assertEqual(self.adapter.calls, calls_before)

    def test_missing_tesseract_returns_ocr_unavailable(self) -> None:
        ocr_service.clear_tesseract_status_cache()
        self.addCleanup(ocr_service.clear_tesseract_status_cache)
        with patch.dict(os.environ, {"TESSERACT_CMD": "/nonexistent/legalai/tesseract"}):
            response = self.upload("fir_scanned.pdf")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "OCR_UNAVAILABLE")
        self.assertNotIn("nonexistent", response.text)
        self.assertIn("scanned document", response.json()["error"])


@REQUIRES_TESSERACT
class OcrIngestionRehearsalTests(ingest_tests.TestIngestionReliability):
    """Admin ingestion of a scanned judgment page into the test DB and temporary store copies."""

    for _name in [name for name in dir(ingest_tests.TestIngestionReliability) if name.startswith("test_")]:
        locals()[_name] = None

    def ingest_fixture(self, name: str):
        path = self.upload_dir / name
        shutil.copyfile(OCR_FIXTURE_DIR / name, path)
        return self.ingest("unused", name, file_path=str(path), parser_func=None, chunker_func=None, case_name=f"OCR rehearsal {name}")

    def test_scanned_judgment_page_is_ingested_with_its_extraction_method(self) -> None:
        job = self.ingest_fixture("judgment_page_scanned.pdf")
        self.assertEqual(job.status, IngestionStatus.COMPLETED.value, job.error_message)
        document = self.db.query(Document).filter(Document.id == job.document_id).one()
        self.assertEqual(document.extraction_method, "ocr")
        self.assertEqual(document.ocr_pages, [1])
        self.assertGreaterEqual(document.ocr_mean_confidence, 80)
        self.assertTrue(document.chunks)
        self.assertTrue(all(chunk.page_start == 1 for chunk in document.chunks if chunk.page_start is not None))
        baseline = self.db.query(Document).filter(Document.id == self.baseline.document_id).one()
        self.assertIsNone(baseline.extraction_method)  # injected parser output carries no provenance
        self.assertEqual(self.verifier_exit(), 0)

    def test_mixed_pdf_records_mixed_and_its_ocr_pages(self) -> None:
        job = self.ingest_fixture("mixed_text_and_scanned.pdf")
        self.assertEqual(job.status, IngestionStatus.COMPLETED.value, job.error_message)
        document = self.db.query(Document).filter(Document.id == job.document_id).one()
        self.assertEqual((document.extraction_method, document.ocr_pages), ("mixed", [2, 4]))
        self.assertEqual(self.verifier_exit(), 0)

    def test_ocr_limit_and_missing_tesseract_fail_cleanly(self) -> None:
        with patch.dict(os.environ, {"OCR_MAX_PAGES_INGESTION": "5"}):
            job = self.ingest_fixture("over_cap_scanned.pdf")
        self.assert_failed_cleanly(job, "OCR_LIMIT_EXCEEDED")
        ocr_service.clear_tesseract_status_cache()
        self.addCleanup(ocr_service.clear_tesseract_status_cache)
        with patch.dict(os.environ, {"TESSERACT_CMD": "/nonexistent/legalai/tesseract"}):
            job = self.ingest_fixture("fir_scanned.pdf")
        self.assert_failed_cleanly(job, "OCR_UNAVAILABLE")
        self.assertEqual(ingestion.SAFE_MESSAGES["OCR_UNAVAILABLE"], job.error_message)


if __name__ == "__main__":
    unittest.main()
