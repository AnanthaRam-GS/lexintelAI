"""Unit and integration tests for LegalAI Task 1.R.2 (Corpus Ingestion & Job Management)."""

from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.core.security import COOKIE_NAME
from backend.app.db.models import Chunk, Document, IngestionJob
from backend.app.db.session import SessionLocal
from backend.app.models.ingest import IngestionStatus
from backend.app.services.embeddings.mock import DeterministicMockEmbeddingProvider
from backend.app.services.ingestion import (
    create_ingestion_job,
    get_corpus_stats,
    get_ingestion_job,
    get_job_chunk_count,
    process_ingestion_job,
)
from backend.app.services.vector_store import INDEX_VERSION, JsonVectorStore
from backend.main import app
from backend.scripts.seed_users import seed_development_users


class TestIngestionUnitAndState(unittest.TestCase):
    """Unit tests for ingestion helpers, state machine, and persistence."""

    def setUp(self) -> None:
        self.db = SessionLocal()

    def tearDown(self) -> None:
        self.db.close()

    def test_job_creation_and_retrieval(self) -> None:
        job = create_ingestion_job(self.db)
        self.assertIsNotNone(job.id)
        self.assertEqual(job.status, IngestionStatus.QUEUED.value)
        self.assertEqual(job.progress, 0)

        fetched = get_ingestion_job(self.db, job.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, job.id)

    def test_missing_dependency_fails_gracefully(self) -> None:
        """When Ananthu's document_parser is missing, the job must transition to FAILED."""
        job = create_ingestion_job(self.db)
        self.assertEqual(job.status, "QUEUED")

        # Process with no parser provided (will fail on missing document_parser import)
        process_ingestion_job(
            job_id=job.id,
            file_path="dummy.pdf",
            doc_type="judgment",
        )

        self.db.expire_all()
        refreshed = get_ingestion_job(self.db, job.id)
        self.assertEqual(refreshed.status, IngestionStatus.FAILED.value)
        self.assertIn("document_parser", refreshed.error_message)
        self.assertIsNotNone(refreshed.completed_at)

    def test_vector_indexing_missing_fails_job(self) -> None:
        """When vector store is unavailable, the job must fail and cannot be marked COMPLETED."""
        job = create_ingestion_job(self.db)

        def mock_parser(file_path: str) -> dict:
            return {"text": "Valid legal text section 302 IPC"}

        def mock_chunker(extracted: dict) -> list[dict]:
            return [{"text": "Valid legal text section 302 IPC", "chunk_index": 0}]

        embedder = DeterministicMockEmbeddingProvider()

        # Chroma is not installed in .venv, so vector_store=None will fail at the indexing step
        process_ingestion_job(
            job_id=job.id,
            file_path="test.pdf",
            doc_type="judgment",
            parser_func=mock_parser,
            chunker_func=mock_chunker,
            embedding_provider=embedder,
            vector_store=None,
        )

        self.db.expire_all()
        refreshed = get_ingestion_job(self.db, job.id)
        self.assertEqual(refreshed.status, IngestionStatus.FAILED.value)
        self.assertIn("Vector store indexing is unavailable", refreshed.error_message)
        self.assertNotEqual(refreshed.status, IngestionStatus.COMPLETED.value)

    def test_successful_flow_persists_document_and_chunks(self) -> None:
        """Test complete QUEUED -> EXTRACTING -> CHUNKING -> EMBEDDING -> INDEXING -> COMPLETED flow."""
        job = create_ingestion_job(self.db)

        # Mock parser returning raw text structure
        def mock_parser(file_path: str) -> dict:
            return {"text": "Criminal judgment text section 302 IPC", "page_count": 2}

        # Mock chunker returning legal chunks
        def mock_chunker(extracted: dict) -> list[dict]:
            return [
                {
                    "text": "First chunk discussing facts and section 302",
                    "chunk_index": 0,
                    "token_count": 8,
                    "page_start": 1,
                    "page_end": 1,
                    "paragraph_start": 1,
                    "paragraph_end": 2,
                    "section_heading": "Facts",
                },
                {
                    "text": "Second chunk discussing evidence and conviction",
                    "chunk_index": 1,
                    "token_count": 7,
                    "page_start": 2,
                    "page_end": 2,
                    "paragraph_start": 3,
                    "paragraph_end": 4,
                    "section_heading": "Analysis",
                },
            ]

        # Use deterministic mock embedding and JSON vector store from shared vector_store.py
        embedder = DeterministicMockEmbeddingProvider()
        with tempfile.TemporaryDirectory() as tmpdir:
            vector_store = JsonVectorStore(
                persist_dir=Path(tmpdir),
                collection_name="test_collection",
                collection_metadata={"index_version": INDEX_VERSION},
            )
            bm25_updates = []

            process_ingestion_job(
                job_id=job.id,
                file_path="test_judgment.pdf",
                doc_type="judgment",
                court_level="high_court",
                year=2024,
                source_url="https://indiankanoon.org/doc/9999/",
                checksum="abc123sha256",
                case_name="State vs Sample",
                parser_func=mock_parser,
                chunker_func=mock_chunker,
                embedding_provider=embedder,
                vector_store=vector_store,
                bm25_update_func=lambda chunks: bm25_updates.append(chunks) or {"indexed_chunks": len(chunks)},
                retrieval_cache_invalidator=lambda: None,
            )

            self.db.expire_all()
            refreshed = get_ingestion_job(self.db, job.id)
            self.assertEqual(refreshed.status, IngestionStatus.COMPLETED.value)
            self.assertEqual(refreshed.progress, 100)
            self.assertIsNotNone(refreshed.document_id)
            self.assertIsNone(refreshed.error_message)

            # Verify Document record in PostgreSQL
            doc = self.db.query(Document).filter(Document.id == refreshed.document_id).first()
            self.assertIsNotNone(doc)
            self.assertEqual(doc.case_name, "State vs Sample")
            self.assertEqual(doc.doc_type, "judgment")
            self.assertEqual(doc.court_level, "high_court")
            self.assertEqual(doc.year, 2024)

            # Verify Chunk records in PostgreSQL
            chunk_count = get_job_chunk_count(self.db, doc.id)
            self.assertEqual(chunk_count, 2)
            chunks = self.db.query(Chunk).filter(Chunk.document_id == doc.id).all()
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0].section_heading, "Facts")
            self.assertEqual(chunks[1].section_heading, "Analysis")

            # Verify Vector Store records
            self.assertEqual(vector_store.count(), 2)
            self.assertEqual(len(bm25_updates), 1)
            self.assertEqual([chunk["chunk_id"] for chunk in bm25_updates[0]], [f"doc:{doc.id}:chunk:0000", f"doc:{doc.id}:chunk:0001"])
            self.assertEqual(bm25_updates[0][0]["chunk_text"], "First chunk discussing facts and section 302")

    def test_bm25_failure_prevents_completed_job(self) -> None:
        job = create_ingestion_job(self.db)

        def mock_parser(file_path: str) -> dict:
            return {"text": "Criminal judgment text section 302 IPC", "page_count": 1}

        def mock_chunker(extracted: dict) -> list[dict]:
            return [{"text": "Trusted chunk section 302", "chunk_index": 0}]

        def failing_bm25_update(chunks: list[dict]) -> dict:
            raise RuntimeError("BM25 lexical indexing unavailable")

        with tempfile.TemporaryDirectory() as tmpdir:
            vector_store = JsonVectorStore(
                persist_dir=Path(tmpdir),
                collection_name="test_collection",
                collection_metadata={"index_version": INDEX_VERSION},
            )
            process_ingestion_job(
                job_id=job.id,
                file_path="test_judgment.pdf",
                doc_type="judgment",
                parser_func=mock_parser,
                chunker_func=mock_chunker,
                embedding_provider=DeterministicMockEmbeddingProvider(),
                vector_store=vector_store,
                bm25_update_func=failing_bm25_update,
                retrieval_cache_invalidator=lambda: None,
            )

        self.db.expire_all()
        refreshed = get_ingestion_job(self.db, job.id)
        self.assertEqual(refreshed.status, IngestionStatus.FAILED.value)
        self.assertIn("BM25 lexical indexing unavailable", refreshed.error_message)
        self.assertNotEqual(refreshed.status, IngestionStatus.COMPLETED.value)


class TestIngestionEndpoints(unittest.TestCase):
    """Integration tests for /ingest/upload, /ingest/status, and /ingest/corpus/stats."""

    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users()

    def get_admin_client(self) -> TestClient:
        client = TestClient(app)
        res = client.post(
            "/auth/login",
            json={"email": "admin@legalai.local", "password": "AdminPassword123!"},
        )
        assert res.status_code == 200
        return client

    def get_lawyer_client(self) -> TestClient:
        client = TestClient(app)
        res = client.post(
            "/auth/login",
            json={"email": "lawyer@legalai.local", "password": "LawyerPassword123!"},
        )
        assert res.status_code == 200
        return client

    def test_upload_requires_auth_and_admin_role(self) -> None:
        dummy_pdf = io.BytesIO(b"%PDF-1.4 dummy content")

        # 1. Unauthenticated client -> 401
        anon_client = TestClient(app)
        res_unauth = anon_client.post(
            "/ingest/upload",
            files={"file": ("test.pdf", dummy_pdf, "application/pdf")},
            data={"doc_type": "judgment"},
        )
        self.assertEqual(res_unauth.status_code, 401)

        # 2. Authenticated as lawyer -> 403
        dummy_pdf.seek(0)
        lawyer_client = self.get_lawyer_client()
        res_lawyer = lawyer_client.post(
            "/ingest/upload",
            files={"file": ("test.pdf", dummy_pdf, "application/pdf")},
            data={"doc_type": "judgment"},
        )
        self.assertEqual(res_lawyer.status_code, 403)

    def test_upload_non_pdf_extension_rejected(self) -> None:
        admin_client = self.get_admin_client()
        txt_file = io.BytesIO(b"%PDF-1.4 but with txt extension")
        res = admin_client.post(
            "/ingest/upload",
            files={"file": ("document.txt", txt_file, "application/pdf")},
            data={"doc_type": "judgment"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("must have a .pdf extension", res.json()["detail"])

    def test_upload_fake_pdf_missing_magic_header_rejected(self) -> None:
        admin_client = self.get_admin_client()
        fake_pdf = io.BytesIO(b"This is just a text file renamed to .pdf")
        res = admin_client.post(
            "/ingest/upload",
            files={"file": ("fake_document.pdf", fake_pdf, "application/pdf")},
            data={"doc_type": "judgment"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Missing '%PDF-' header", res.json()["detail"])

    def test_upload_incompatible_content_type_rejected(self) -> None:
        admin_client = self.get_admin_client()
        pdf_file = io.BytesIO(b"%PDF-1.4 valid header but wrong content type")
        res = admin_client.post(
            "/ingest/upload",
            files={"file": ("document.pdf", pdf_file, "text/plain")},
            data={"doc_type": "judgment"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Invalid content type", res.json()["detail"])

    def test_upload_empty_file_rejected(self) -> None:
        admin_client = self.get_admin_client()
        empty_file = io.BytesIO(b"")
        res = admin_client.post(
            "/ingest/upload",
            files={"file": ("empty.pdf", empty_file, "application/pdf")},
            data={"doc_type": "judgment"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("empty", res.json()["detail"])

    def test_upload_success_creates_single_queued_job(self) -> None:
        admin_client = self.get_admin_client()
        pdf_bytes = io.BytesIO(b"%PDF-1.4 sample PDF binary payload")
        res = admin_client.post(
            "/ingest/upload",
            files={"file": ("sample_judgment.pdf", pdf_bytes, "application/pdf")},
            data={
                "doc_type": "judgment",
                "court_level": "supreme_court",
                "year": "2024",
                "source_url": "https://example.com/judgments/sample.pdf",
                "case_name": "ABC vs XYZ",
            },
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("job_id", data)
        self.assertEqual(data["status"], IngestionStatus.QUEUED.value)

        # Verify job was created in DB
        db = SessionLocal()
        try:
            job = db.query(IngestionJob).filter(IngestionJob.id == data["job_id"]).first()
            self.assertIsNotNone(job)
            self.assertIn(
                job.status,
                [
                    IngestionStatus.QUEUED.value,
                    IngestionStatus.EXTRACTING.value,
                    IngestionStatus.FAILED.value,
                ],
            )
        finally:
            db.close()

    def test_status_unknown_job_returns_404(self) -> None:
        admin_client = self.get_admin_client()
        res = admin_client.get("/ingest/status/nonexistent-uuid-99999")
        self.assertEqual(res.status_code, 404)
        self.assertIn("not found", res.json()["detail"])

    def test_status_for_existing_job(self) -> None:
        admin_client = self.get_admin_client()
        db = SessionLocal()
        try:
            job = create_ingestion_job(db)
            job_id = job.id
        finally:
            db.close()

        res = admin_client.get(f"/ingest/status/{job_id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["job_id"], job_id)
        self.assertEqual(data["status"], IngestionStatus.QUEUED.value)
        self.assertEqual(data["progress"], 0)
        self.assertIsNone(data["error"])

    def test_corpus_stats_endpoint(self) -> None:
        admin_client = self.get_admin_client()
        res = admin_client.get("/ingest/corpus/stats")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("total_documents", data)
        self.assertIsInstance(data["total_documents"], int)
        self.assertIn("by_type", data)
        self.assertIsInstance(data["by_type"], list)
        self.assertEqual(data["postgres_status"], "connected")
        self.assertIn("chroma_status", data)


if __name__ == "__main__":
    unittest.main()
