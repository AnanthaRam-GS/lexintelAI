"""Unit and integration tests for LegalAI Task 1.R.2 (Corpus Ingestion & Job Management)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import numpy as np
from fastapi.testclient import TestClient

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from backend.app.core.security import COOKIE_NAME
from backend.app.db.models import Chunk, Document, DocumentSection, IngestionJob
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
from backend.app.api import ingest as ingest_api
from backend.app.api import query as query_api
from backend.app.services import ingestion
from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.retrieval.bm25 import DEFAULT_INDEX_NAME, Bm25LexicalIndex
from backend.app.services.vector_store import EXPECTED_EMBEDDING_DIMENSION, INDEX_VERSION, ChromaVectorStore, JsonVectorStore
from backend.main import app
from backend.scripts import build_lexical_index, enrich_index_metadata, verify_store_consistency
from backend.scripts.seed_users import seed_development_users
from backend.scripts.tests.db_test_bootstrap import TEST_SEED_PASSWORDS, TEST_LAWYER_PASSWORD, TEST_ADMIN_PASSWORD


class FailingVectorStore:
    """Test double that exercises the vector-indexing failure branch."""

    def upsert_chunks(self, **kwargs) -> dict:
        raise RuntimeError("Vector store indexing is unavailable")

    def delete_document(self, document_id: str) -> int:
        return 0


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

    def test_parser_dependency_failure_fails_gracefully(self) -> None:
        """When parsing is unavailable, the job must transition to FAILED."""
        job = create_ingestion_job(self.db)
        self.assertEqual(job.status, "QUEUED")

        def missing_parser(file_path: str) -> dict:
            raise RuntimeError(
                "Ingestion blocked: shared document_parser service is unavailable."
            )

        process_ingestion_job(
            job_id=job.id,
            file_path="dummy.pdf",
            doc_type="judgment",
            parser_func=missing_parser,
        )

        self.db.expire_all()
        refreshed = get_ingestion_job(self.db, job.id)
        self.assertEqual(refreshed.status, IngestionStatus.FAILED.value)
        # SEC-007: sanitized message plus internal code; raw exception text stays in logs.
        self.assertEqual(refreshed.error_code, "PARSE_FAILED")
        self.assertEqual(refreshed.error_message, "The PDF could not be read.")
        self.assertNotIn("document_parser", refreshed.error_message)
        self.assertFalse(refreshed.needs_reconciliation)
        self.assertIsNotNone(refreshed.completed_at)

    def test_vector_indexing_missing_fails_job(self) -> None:
        """When vector store is unavailable, the job must fail and cannot be marked COMPLETED."""
        job = create_ingestion_job(self.db)

        def mock_parser(file_path: str) -> dict:
            return {"text": "Valid legal text section 302 IPC"}

        def mock_chunker(extracted: dict) -> list[dict]:
            return [{"text": "Valid legal text section 302 IPC", "chunk_index": 0}]

        embedder = DeterministicMockEmbeddingProvider()

        process_ingestion_job(
            job_id=job.id,
            file_path="test.pdf",
            doc_type="judgment",
            parser_func=mock_parser,
            chunker_func=mock_chunker,
            embedding_provider=embedder,
            vector_store=FailingVectorStore(),
        )

        self.db.expire_all()
        refreshed = get_ingestion_job(self.db, job.id)
        self.assertEqual(refreshed.status, IngestionStatus.FAILED.value)
        self.assertEqual(refreshed.error_code, "VECTOR_INDEX_FAILED")
        self.assertEqual(refreshed.error_message, "The vector index could not be updated.")
        self.assertNotIn("Vector store indexing is unavailable", refreshed.error_message)
        self.assertFalse(refreshed.needs_reconciliation)
        self.assertIsNone(refreshed.document_id)
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
            # Admin uploads use corpus-format IDs keyed by the file checksum.
            self.assertEqual(doc.source_document_key, "admin:abc123sha256")
            self.assertEqual([chunk["chunk_id"] for chunk in bm25_updates[0]], ["admin:abc123sha256:chunk:0000", "admin:abc123sha256:chunk:0001"])
            self.assertEqual([chunk.chroma_id for chunk in sorted(chunks, key=lambda c: c.chunk_index)], ["admin:abc123sha256:chunk:0000", "admin:abc123sha256:chunk:0001"])
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

            self.assertEqual(vector_store.count(), 0)  # compensated: no vectors left behind

        self.db.expire_all()
        refreshed = get_ingestion_job(self.db, job.id)
        self.assertEqual(refreshed.status, IngestionStatus.FAILED.value)
        self.assertEqual(refreshed.error_code, "LEXICAL_INDEX_FAILED")
        self.assertEqual(refreshed.error_message, "The keyword index could not be updated.")
        self.assertNotIn("BM25 lexical indexing unavailable", refreshed.error_message)
        self.assertFalse(refreshed.needs_reconciliation)
        self.assertIsNone(refreshed.document_id)
        self.assertEqual(self.db.query(Document).count(), 0)
        self.assertNotEqual(refreshed.status, IngestionStatus.COMPLETED.value)


class TestIngestionEndpoints(unittest.TestCase):
    """Integration tests for /ingest/upload, /ingest/status, and /ingest/corpus/stats."""

    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users(TEST_SEED_PASSWORDS)

    def get_admin_client(self) -> TestClient:
        client = TestClient(app)
        res = client.post(
            "/auth/login",
            json={"email": "admin@legalai.local", "password": TEST_ADMIN_PASSWORD},
        )
        assert res.status_code == 200
        return client

    def get_lawyer_client(self) -> TestClient:
        client = TestClient(app)
        res = client.post(
            "/auth/login",
            json={"email": "lawyer@legalai.local", "password": TEST_LAWYER_PASSWORD},
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
        # Service health uses the frontend contract: healthy | degraded | down.
        self.assertEqual(data["postgres_status"], "healthy")
        self.assertIn(data["chroma_status"], {"healthy", "degraded", "down"})
        self.assertIn(data["bm25_status"], {"healthy", "degraded", "down"})
        self.assertEqual(data["postgres_chunk_count"], 0)


TEST_COLLECTION = "test_trusted_collection"
SECRET_ERROR = "boom-internal-detail"


class TestIngestionReliability(unittest.TestCase):
    """BE-001/002/005, DATA-003, SEC-007 against real temporary Chroma and BM25 stores.

    Every test starts with one fully indexed baseline document, so the
    consistency verifier (verify_store_consistency.py) can run against
    non-empty stores.
    """

    @classmethod
    def setUpClass(cls) -> None:
        seed_development_users(TEST_SEED_PASSWORDS)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.chroma_dir = root / "chroma"
        self.bm25_dir = root / "bm25"
        self.upload_dir = root / "uploads"
        self.upload_dir.mkdir()
        self.env = patch.dict(os.environ, {"CHROMA_PERSIST_DIR": str(self.chroma_dir), "CHROMA_COLLECTION_NAME": TEST_COLLECTION})
        self.env.start()
        self.bm25_patch = patch.object(build_lexical_index, "DEFAULT_PERSIST_DIR", self.bm25_dir)
        self.bm25_patch.start()
        self.db = SessionLocal()
        self.baseline = self.ingest("baseline judgment", "baseline")
        self.assertEqual(self.baseline.status, IngestionStatus.COMPLETED.value, self.baseline.error_message)

    def tearDown(self) -> None:
        self.db.close()
        self.bm25_patch.stop()
        self.env.stop()
        query_api.clear_retrieval_service_cache()
        self.tmp.cleanup()

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def embedder() -> DeterministicMockEmbeddingProvider:
        return DeterministicMockEmbeddingProvider(EmbeddingConfig(model_name="deterministic-mock", dimension=EXPECTED_EMBEDDING_DIMENSION))

    @staticmethod
    def parsed(text: str, seed: str) -> dict:
        return {"text": text, "sha256": hashlib.sha256(seed.encode()).hexdigest(), "metadata": {"text_source_type": "pdf_native"}}

    @staticmethod
    def chunker(extracted: dict) -> list[dict]:
        base = extracted["text"]
        return [
            {"text": f"{base} part one", "chunk_index": 0, "page_start": 1, "page_end": 1, "paragraph_start": 1, "paragraph_end": 2,
             "heading_path": ["FACTS"], "chunker_version": "test-chunker", "normalizer_version": "test-normalizer", "estimated_token_count": 4},
            {"text": f"{base} part two", "chunk_index": 1, "page_start": None, "page_end": None, "paragraph_start": 3, "paragraph_end": 4,
             "heading_path": [], "chunker_version": "test-chunker", "normalizer_version": "test-normalizer", "estimated_token_count": 4},
        ]

    def ingest(self, text: str, seed: str, **overrides) -> IngestionJob:
        job = create_ingestion_job(self.db)
        kwargs = {
            "job_id": job.id,
            "file_path": f"{seed}.pdf",
            "doc_type": "judgment",
            "court_level": "high_court",
            "year": 2024,
            "source_url": f"https://example.test/{seed}",
            "case_name": f"Case {seed}",
            "parser_func": lambda _path: self.parsed(text, seed),
            "chunker_func": self.chunker,
            "embedding_provider": self.embedder(),
            "retrieval_cache_invalidator": lambda: None,
        }
        kwargs.update(overrides)
        process_ingestion_job(**kwargs)
        self.db.expire_all()
        return get_ingestion_job(self.db, job.id)

    def verifier_exit(self) -> int:
        return verify_store_consistency.main([
            "--database-url-env", "TEST_DATABASE_URL",
            "--chroma-dir", str(self.chroma_dir),
            "--bm25-file", str(self.bm25_dir / f"{DEFAULT_INDEX_NAME}.json"),
            "--collection", TEST_COLLECTION,
        ])

    def store_counts(self) -> tuple[int, int, int]:
        vectors = ingestion.trusted_vector_store(ingestion.Settings()).count()
        records = Bm25LexicalIndex(self.bm25_dir, DEFAULT_INDEX_NAME).count()
        return self.db.query(Chunk).count(), vectors, records

    def collections(self, chroma_dir: Path | None = None) -> list[str]:
        database = (chroma_dir or self.chroma_dir) / "chroma.sqlite3"
        if not database.exists():
            return []
        connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
        try:
            return sorted(row[0] for row in connection.execute("SELECT name FROM collections"))
        finally:
            connection.close()

    def assert_failed_cleanly(self, job: IngestionJob, code: str) -> None:
        self.assertEqual(job.status, IngestionStatus.FAILED.value)
        self.assertEqual(job.error_code, code)
        self.assertEqual(job.error_message, ingestion.SAFE_MESSAGES[code])
        self.assertNotIn(SECRET_ERROR, job.error_message)
        self.assertFalse(job.needs_reconciliation)
        self.assertIsNone(job.document_id)
        self.assertEqual(self.db.query(Document).count(), 1)  # only the baseline
        self.assertEqual(self.db.query(DocumentSection).count(), 0)  # the baseline cites no section
        self.assertEqual(self.store_counts(), (2, 2, 2))
        self.assertEqual(self.verifier_exit(), 0)

    # -- BE-001 / metadata parity ------------------------------------------

    def test_successful_ingestion_is_consistent_with_corpus_metadata_schema(self) -> None:
        self.assertEqual(self.store_counts(), (2, 2, 2))
        self.assertEqual(self.verifier_exit(), 0)
        document = self.db.query(Document).one()
        key = ingestion.admin_document_key(hashlib.sha256(b"baseline").hexdigest())
        self.assertEqual(document.source_document_key, key)
        self.assertEqual(sorted(c.chroma_id for c in document.chunks), [f"{key}:chunk:0000", f"{key}:chunk:0001"])

        store = ingestion.trusted_vector_store(ingestion.Settings())
        chroma_metadata = store.get_chunk(f"{key}:chunk:0000")["metadata"]
        bm25_metadata = Bm25LexicalIndex(self.bm25_dir, DEFAULT_INDEX_NAME).get_chunk(f"{key}:chunk:0000")["metadata"]
        required = {
            "chunk_id", "document_id", "provider", "source_document_id", "source_url", "case_title", "court",
            "decision_date", "decision_year", "chunk_index", "paragraph_start", "paragraph_end", "page_start",
            "page_end", "has_page_provenance", "text_source_type", "raw_sha256", "normalizer_version", "chunker_version",
        }
        for metadata in (chroma_metadata, bm25_metadata):
            self.assertLessEqual(required, set(metadata))
            self.assertEqual(metadata["document_id"], key)
            self.assertEqual(metadata["court"], '{"court_level": "high_court"}')
            self.assertEqual(metadata["decision_year"], 2024)
            self.assertEqual(metadata["decision_date"], "")  # not supplied by the upload: never inferred
            self.assertEqual((metadata["page_start"], metadata["paragraph_start"], metadata["paragraph_end"]), (1, 1, 2))
            self.assertNotIn("effective_offence_family", metadata)  # not derivable: never fabricated
            self.assertEqual(metadata["effective_legal_regime"], "unknown")  # no statute cited
            self.assertEqual((metadata["doc_type"], metadata["cited_section_count"], metadata["chunk_section_count"]), ("judgment", 0, 0))
            self.assertNotIn("cited_sections", metadata)  # empty list: absent key, count 0
            self.assertEqual(metadata["index_metadata_version"], "index_metadata_v1")
        self.assertIn("index_fingerprint", chroma_metadata)
        second = store.get_chunk(f"{key}:chunk:0001")["metadata"]
        self.assertEqual((second["page_start"], second["has_page_provenance"]), (-1, False))

    def test_ingestion_writes_sections_outcomes_and_index_metadata_together(self) -> None:
        text = (
            "The appellant was charged under Section 302 IPC read with Section 34 IPC and Section 313 Cr.P.C. "
            "In the result, the appeal is dismissed. The conviction of the appellant is upheld."
        )
        job = self.ingest(text, "analysed")
        self.assertEqual(job.status, IngestionStatus.COMPLETED.value, job.error_message)
        document = self.db.get(Document, job.document_id)
        self.assertEqual(
            {(row.statute, row.section) for row in document.document_sections},
            {("IPC", "302"), ("IPC", "34"), ("CrPC", "313")},
        )
        self.assertEqual((document.appeal_result, document.conviction_status, document.case_disposition), ("dismissed", "convicted", "appeal dismissed"))
        self.assertEqual(document.outcome_method, "operative_rules_v2")
        self.assertIn("appeal_result", document.outcome_evidence)

        key = document.source_document_key
        store = ingestion.trusted_vector_store(ingestion.Settings())
        index = Bm25LexicalIndex(self.bm25_dir, DEFAULT_INDEX_NAME)
        for chunk_id in (f"{key}:chunk:0000", f"{key}:chunk:0001"):
            for metadata in (store.get_chunk(chunk_id)["metadata"], index.get_chunk(chunk_id)["metadata"]):
                self.assertEqual(metadata["doc_type"], "judgment")
                self.assertEqual(metadata["cited_sections"], ["CrPC 313", "IPC 34", "IPC 302"])
                self.assertEqual(metadata["offence_sections"], ["IPC 302"])
                self.assertEqual(metadata["chunk_sections"], ["CrPC 313", "IPC 34", "IPC 302"])
                self.assertEqual((metadata["cited_section_count"], metadata["offence_section_count"], metadata["chunk_section_count"]), (3, 1, 3))
                self.assertEqual(metadata["effective_legal_regime"], "ipc_crpc")
                self.assertNotIn("effective_offence_family", metadata)
        self.assertEqual(self.verifier_exit(), 0)

    def test_injected_failures_in_the_analytics_writes_leave_no_trace(self) -> None:
        text = "The appellant was charged under Section 302 IPC. The appeal is dismissed."
        real_produce = ingestion.produce_document

        def produce_then_fail(session, document, chunks, stats, regimes=None):
            real_produce(session, document, chunks, stats, regimes)  # sections and outcomes really written, then failure
            session.flush()
            raise RuntimeError(SECRET_ERROR)

        def raise_secret(*_args, **_kwargs):
            raise RuntimeError(SECRET_ERROR)

        for index, (target, replacement) in enumerate((("add_index_metadata", raise_secret), ("produce_document", produce_then_fail))):
            with self.subTest(failure=target), patch.object(ingestion, target, replacement):
                job = self.ingest(f"{text} {index}", f"analytics-failure-{index}")
                self.assert_failed_cleanly(job, "ANALYTICS_FAILED")

    def enrich(self, *extra: str) -> int:
        return enrich_index_metadata.main([
            "--database-url-env", "TEST_DATABASE_URL",
            "--chroma-dir", str(self.chroma_dir),
            "--bm25-file", str(self.bm25_dir / f"{DEFAULT_INDEX_NAME}.json"),
            "--collection", TEST_COLLECTION,
            *extra,
        ])

    def strip_index_metadata(self) -> None:
        """Remove the index_metadata_v1 fields and the derived regime, as in an index built before step 9."""
        from backend.app.services.index_metadata import FIELDS

        removed = {key: None for key in (*FIELDS, "effective_legal_regime")}
        store = ingestion.trusted_vector_store(ingestion.Settings())
        ids = store._collection.get(include=[])["ids"]
        store._collection.update(ids=ids, metadatas=[dict(removed) for _ in ids])
        index = Bm25LexicalIndex(self.bm25_dir, DEFAULT_INDEX_NAME)
        for record in index.records.values():
            for key in removed:
                record["metadata"].pop(key, None)
        index.persist()

    def index_snapshot(self) -> dict:
        store = ingestion.trusted_vector_store(ingestion.Settings())
        got = store._collection.get(include=["embeddings", "documents", "metadatas"])
        vectors = {i: hashlib.sha256(np.asarray(e, dtype=np.float32).tobytes()).hexdigest() for i, e in zip(got["ids"], got["embeddings"])}
        payload = json.loads((self.bm25_dir / f"{DEFAULT_INDEX_NAME}.json").read_text())
        return {
            "vectors": vectors,
            "documents": dict(zip(got["ids"], got["documents"])),
            "metadatas": dict(zip(got["ids"], got["metadatas"])),
            "bm25_statistics": enrich_index_metadata.bm25_statistics_digest(payload),
        }

    def test_enrichment_adds_only_metadata_and_is_idempotent(self) -> None:
        job = self.ingest("Charged under Section 302 IPC and Section 103 BNS. The appeal is dismissed.", "to-enrich")
        self.assertEqual(job.status, IngestionStatus.COMPLETED.value, job.error_message)
        enriched = self.index_snapshot()
        self.strip_index_metadata()
        self.assertEqual(self.verifier_exit(), 1)  # fields missing
        stripped = self.index_snapshot()

        self.assertEqual(self.enrich("--dry-run"), 0)
        self.assertEqual(self.index_snapshot(), stripped)  # dry run writes nothing
        self.assertEqual(self.enrich(), 0)
        after = self.index_snapshot()
        self.assertEqual(after, enriched)  # same metadata as ingestion wrote, nothing else changed
        self.assertEqual((after["vectors"], after["documents"], after["bm25_statistics"]), (stripped["vectors"], stripped["documents"], stripped["bm25_statistics"]))
        key = self.db.get(Document, job.document_id).source_document_key
        self.assertEqual(after["metadatas"][f"{key}:chunk:0000"]["effective_legal_regime"], "mixed_or_transition")
        self.assertEqual(self.verifier_exit(), 0)
        self.assertEqual(self.enrich(), 0)
        self.assertEqual(self.index_snapshot(), after)  # second run: 0 changes

    def test_enrichment_never_changes_an_existing_legal_regime(self) -> None:
        store = ingestion.trusted_vector_store(ingestion.Settings())
        ids = store._collection.get(include=[])["ids"]
        store._collection.update(ids=ids, metadatas=[{"effective_legal_regime": "ipc_crpc"} for _ in ids])  # e.g. a reviewed value
        self.assertEqual(self.enrich(), 0)
        self.assertEqual({m["effective_legal_regime"] for m in store._collection.get(include=["metadatas"])["metadatas"]}, {"ipc_crpc"})

    def test_verifier_detects_corrupted_index_metadata(self) -> None:
        job = self.ingest("Charged under Section 302 IPC. The appeal is dismissed.", "to-corrupt")
        key = self.db.get(Document, job.document_id).source_document_key
        store = ingestion.trusted_vector_store(ingestion.Settings())
        store._collection.update(ids=[f"{key}:chunk:0000"], metadatas=[{"offence_sections": ["IPC 307"]}])
        self.assertEqual(self.verifier_exit(), 1)
        store._collection.update(ids=[f"{key}:chunk:0000"], metadatas=[{"offence_sections": ["IPC 302"]}])
        self.assertEqual(self.verifier_exit(), 0)
        index = Bm25LexicalIndex(self.bm25_dir, DEFAULT_INDEX_NAME)
        index.records[f"{key}:chunk:0001"]["metadata"]["doc_type"] = "statute"
        index.persist()
        self.assertEqual(self.verifier_exit(), 1)

    def test_injected_failures_leave_no_trace_and_sanitized_errors(self) -> None:
        real_store = ingestion.trusted_vector_store(ingestion.Settings())

        class PartialThenFailStore:
            def upsert_chunks(self, **kwargs):
                real_store.upsert_chunks(**kwargs)  # vectors really written, then failure
                raise RuntimeError(SECRET_ERROR)

            def delete_document(self, document_id):
                return real_store.delete_document(document_id)

        def raise_secret(*_args, **_kwargs):
            raise RuntimeError(SECRET_ERROR)

        def bm25_write_then_fail(chunks):
            ingestion.update_trusted_bm25_index(chunks)  # BM25 really written, then failure
            raise RuntimeError(SECRET_ERROR)

        class FailingEmbedder:
            config = EmbeddingConfig()

            def embed_documents(self, texts):
                raise RuntimeError(SECRET_ERROR)

        cases = {
            "PARSE_FAILED": {"parser_func": raise_secret},
            "CHUNKING_FAILED": {"chunker_func": lambda _doc: []},
            "EMBEDDING_FAILED": {"embedding_provider": FailingEmbedder()},
            "VECTOR_INDEX_FAILED": {"vector_store": PartialThenFailStore()},
            "LEXICAL_INDEX_FAILED": {"bm25_update_func": bm25_write_then_fail},
            # case_name longer than documents.case_name (500): fails at the final PostgreSQL commit.
            "DATABASE_WRITE_FAILED": {"case_name": "x" * 600},
        }
        for index, (code, overrides) in enumerate(cases.items()):
            with self.subTest(stage=code):
                job = self.ingest(f"failure document {index}", f"failure-{index}", **overrides)
                self.assert_failed_cleanly(job, code)

    def test_failure_during_cleanup_is_flagged_for_reconciliation(self) -> None:
        real_store = ingestion.trusted_vector_store(ingestion.Settings())

        class UndeletableStore:
            def upsert_chunks(self, **kwargs):
                return real_store.upsert_chunks(**kwargs)

            def delete_document(self, document_id):
                raise RuntimeError(SECRET_ERROR)

        def failing_bm25(_chunks):
            raise RuntimeError(SECRET_ERROR)

        job = self.ingest("cleanup failure document", "cleanup-failure", vector_store=UndeletableStore(), bm25_update_func=failing_bm25)
        self.assertEqual(job.status, IngestionStatus.FAILED.value)
        self.assertEqual(job.error_code, "LEXICAL_INDEX_FAILED")
        self.assertTrue(job.needs_reconciliation)
        self.assertEqual(job.error_message, ingestion.SAFE_MESSAGES["LEXICAL_INDEX_FAILED"] + ingestion.RECONCILIATION_SUFFIX)
        self.assertNotIn(SECRET_ERROR, job.error_message)
        self.assertEqual(self.db.query(Document).count(), 1)
        self.assertEqual(self.verifier_exit(), 1)  # the leftover vectors are what reconciliation must fix
        stats = get_corpus_stats(self.db)
        self.assertEqual(stats.reconciliation_job_count, 1)
        self.assertEqual(
            (stats.reconciliation_jobs[0].job_id, stats.reconciliation_jobs[0].error_code, stats.reconciliation_jobs[0].error_message),
            (job.id, "LEXICAL_INDEX_FAILED", job.error_message),
        )

    # -- DATA-003 -----------------------------------------------------------

    def test_duplicate_checksum_is_rejected_before_any_write(self) -> None:
        job = self.ingest("baseline judgment", "baseline")  # same checksum as the baseline
        self.assert_failed_cleanly(job, "DUPLICATE_DOCUMENT")

    def test_duplicate_race_at_commit_does_not_remove_the_winner(self) -> None:
        # Both pre-write checks miss the duplicate; the unique constraint catches it at commit.
        with patch.object(ingestion, "find_document_by_checksum", return_value=None):
            job = self.ingest("baseline judgment", "baseline")
        self.assertEqual(job.status, IngestionStatus.FAILED.value)
        self.assertEqual(job.error_code, "DUPLICATE_DOCUMENT")
        self.assertFalse(job.needs_reconciliation)
        self.assertEqual(self.store_counts(), (2, 2, 2))  # the baseline's index entries are kept
        self.assertEqual(self.verifier_exit(), 0)

    def test_upload_of_known_document_returns_409_without_writes(self) -> None:
        payload = b"%PDF-1.4 already ingested payload"
        checksum = hashlib.sha256(payload).hexdigest()
        self.db.query(Document).filter(Document.id == self.baseline.document_id).update({"checksum": checksum})
        self.db.commit()
        client = TestClient(app)
        self.assertEqual(client.post("/auth/login", json={"email": "admin@legalai.local", "password": TEST_ADMIN_PASSWORD}).status_code, 200)
        jobs_before = self.db.query(IngestionJob).count()

        response = client.post(
            "/ingest/upload",
            files={"file": ("again.pdf", io.BytesIO(payload), "application/pdf")},
            data={"doc_type": "judgment"},
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "DOCUMENT_ALREADY_INGESTED")
        self.assertEqual(response.json()["detail"]["document_id"], self.baseline.document_id)
        self.assertEqual(self.db.query(IngestionJob).count(), jobs_before)
        self.assertEqual(list(ingest_api.UPLOAD_DIR.glob("*again.pdf")) if ingest_api.UPLOAD_DIR.exists() else [], [])
        self.assertEqual(self.store_counts(), (2, 2, 2))

    # -- BE-005 -------------------------------------------------------------

    def age_job(self, job: IngestionJob, status: str, minutes: int) -> None:
        old = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        self.db.query(IngestionJob).filter(IngestionJob.id == job.id).update(
            {"status": status, "created_at": old, "started_at": old if status != "QUEUED" else None}
        )
        self.db.commit()

    def test_stale_jobs_are_reaped_and_their_partial_index_entries_removed(self) -> None:
        queued = create_ingestion_job(self.db)
        self.age_job(queued, "QUEUED", 120)
        recent = create_ingestion_job(self.db)

        indexing = create_ingestion_job(self.db)
        payload = b"%PDF-1.4 interrupted upload"
        (self.upload_dir / f"{indexing.id}_interrupted.pdf").write_bytes(payload)
        key = ingestion.admin_document_key(hashlib.sha256(payload).hexdigest())
        chunks = [
            ingestion.corpus_format_chunk(raw, i, key, hashlib.sha256(payload).hexdigest(), "Interrupted", None, None, None, "pdf_native")
            for i, raw in enumerate(self.chunker({"text": "interrupted judgment"}))
        ]
        store = ingestion.trusted_vector_store(ingestion.Settings())
        store.upsert_chunks(
            ids=[c["chunk_id"] for c in chunks],
            vectors=self.embedder().embed_documents([c["chunk_text"] for c in chunks]),
            documents=[c["chunk_text"] for c in chunks],
            metadatas=ingestion.chroma_metadatas(chunks, self.embedder()),
        )
        ingestion.update_trusted_bm25_index(chunks)
        self.age_job(indexing, "INDEXING", 120)
        self.assertEqual(self.verifier_exit(), 1)  # interrupted write left index entries behind

        orphaned = create_ingestion_job(self.db)  # INDEXING without a stored upload
        self.age_job(orphaned, "INDEXING", 120)

        reaped = ingestion.reap_stale_jobs(self.db, upload_dir=self.upload_dir)

        self.assertEqual(sorted(reaped), sorted([queued.id, indexing.id, orphaned.id]))
        self.db.expire_all()
        for job_id, needs_reconciliation in ((queued.id, False), (indexing.id, False), (orphaned.id, True)):
            job = get_ingestion_job(self.db, job_id)
            self.assertEqual((job.status, job.error_code, job.needs_reconciliation), ("FAILED", "STALE_JOB", needs_reconciliation))
        self.assertEqual(get_ingestion_job(self.db, recent.id).status, "QUEUED")
        self.assertEqual(self.verifier_exit(), 0)  # partial entries removed
        self.assertEqual(ingestion.reap_stale_jobs(self.db, upload_dir=self.upload_dir), [])

    def test_status_read_reaps_stale_job(self) -> None:
        job = create_ingestion_job(self.db)
        self.age_job(job, "EXTRACTING", 120)
        client = TestClient(app)
        client.post("/auth/login", json={"email": "admin@legalai.local", "password": TEST_ADMIN_PASSWORD})
        response = client.get(f"/ingest/status/{job.id}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["status"], body["error_code"], body["needs_reconciliation"]), ("FAILED", "STALE_JOB", False))
        self.assertEqual(body["error"], ingestion.SAFE_MESSAGES["STALE_JOB"])

    # -- BE-002 / read paths -----------------------------------------------

    def test_status_reports_real_store_health(self) -> None:
        stats = get_corpus_stats(self.db)
        self.assertEqual((stats.chroma_status, stats.bm25_status, stats.postgres_status), ("healthy", "healthy", "healthy"))
        self.assertEqual((stats.chroma_record_count, stats.bm25_record_count, stats.postgres_chunk_count), (2, 2, 2))
        self.assertEqual(stats.chroma_collection, TEST_COLLECTION)

        self.db.add(Chunk(document_id=self.baseline.document_id, chunk_index=9, text="pg only", chroma_id="pg-only"))
        self.db.commit()
        degraded = get_corpus_stats(self.db)
        self.assertEqual((degraded.chroma_status, degraded.bm25_status), ("degraded", "degraded"))

    def test_status_reports_missing_or_wrong_dimension_collection_without_creating_it(self) -> None:
        before = self.collections()
        with patch.dict(os.environ, {"CHROMA_COLLECTION_NAME": "missing_collection"}):
            missing = get_corpus_stats(self.db)
        self.assertEqual(missing.chroma_status, "down")
        self.assertIn("does not exist", missing.chroma_detail)
        self.assertEqual(self.collections(), before)

        absent_dir = Path(self.tmp.name) / "no_store_here"
        with patch.dict(os.environ, {"CHROMA_PERSIST_DIR": str(absent_dir)}):
            no_store = get_corpus_stats(self.db)
        self.assertEqual(no_store.chroma_status, "down")
        self.assertFalse(absent_dir.exists())

        ChromaVectorStore(self.chroma_dir, "wrong_dimension_collection", {"index_version": INDEX_VERSION}).upsert_chunks(
            ids=["x"], vectors=[[0.1] * 8], documents=["x"], metadatas=[{"document_id": "x"}]
        )
        with patch.dict(os.environ, {"CHROMA_COLLECTION_NAME": "wrong_dimension_collection"}):
            wrong = get_corpus_stats(self.db)
        self.assertEqual(wrong.chroma_status, "down")
        self.assertIn("dimension 8", wrong.chroma_detail)

    def test_query_path_fails_without_creating_a_missing_collection(self) -> None:
        before = self.collections()
        ChromaVectorStore(self.chroma_dir, "wrong_dimension_collection", {"index_version": INDEX_VERSION}).upsert_chunks(
            ids=["x"], vectors=[[0.1] * 8], documents=["x"], metadatas=[{"document_id": "x"}]
        )
        absent_dir = Path(self.tmp.name) / "no_store_here"
        for env in (
            {"CHROMA_COLLECTION_NAME": "missing_collection"},
            {"CHROMA_COLLECTION_NAME": "wrong_dimension_collection"},
            {"CHROMA_PERSIST_DIR": str(absent_dir)},
        ):
            with self.subTest(env=env), patch.dict(os.environ, env):
                query_api.clear_retrieval_service_cache()
                with self.assertRaises(HTTPException) as raised:
                    query_api.get_retrieval_service()
                self.assertEqual(raised.exception.status_code, 503)
                self.assertEqual(raised.exception.detail["code"], "RETRIEVAL_INDEX_UNAVAILABLE")
        self.assertEqual(self.collections(), sorted(before + ["wrong_dimension_collection"]))
        self.assertNotIn("missing_collection", self.collections())
        self.assertFalse(absent_dir.exists())


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
