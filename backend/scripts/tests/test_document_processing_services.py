"""Tests for reusable document parser and chunker service adapters."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf

from backend.scripts.tests import db_test_bootstrap  # Must stay the first backend import.
from backend.app.models.ingest import IngestionStatus
from backend.app.services.chunker import DocumentChunkingError, chunk_document
from backend.app.services.document_parser import DocumentParsingError, parse_document
from backend.app.services.ingestion import process_ingestion_job


def write_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    try:
        for text in pages:
            page = document.new_page()
            if text:
                page.insert_text((72, 72), text)
        document.save(path)
    finally:
        document.close()


class DocumentParserServiceTest(unittest.TestCase):
    def test_valid_text_pdf_preserves_pages_and_paragraphs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            write_pdf(path, ["JUDGMENT\n\n1. First page section 302 IPC.", "2. Second page evidence."])

            parsed = parse_document(path)

        self.assertEqual(parsed["page_count"], 2)
        self.assertIn("First page", parsed["text"])
        self.assertEqual(parsed["pages"][0]["page_number"], 1)
        self.assertTrue(parsed["paragraphs"])
        self.assertEqual(parsed["extraction"]["method"], "pymupdf_native_text")
        self.assertFalse(parsed["extraction"]["ocr_used"])

    def test_missing_file_rejected(self) -> None:
        with self.assertRaisesRegex(DocumentParsingError, "does not exist"):
            parse_document("/tmp/legalai-missing-document.pdf")

    def test_invalid_pdf_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.pdf"
            path.write_bytes(b"not a real pdf")
            with self.assertRaisesRegex(DocumentParsingError, "extraction failed"):
                parse_document(path)

    def test_empty_text_pdf_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.pdf"
            write_pdf(path, [""])
            with self.assertRaisesRegex(DocumentParsingError, "no extractable native text"):
                parse_document(path)


class ChunkerServiceTest(unittest.TestCase):
    def parsed_document(self) -> dict:
        paragraphs = [
            {
                "document_id": "local:test",
                "paragraph_index": index,
                "text": f"{index}. " + ("legal evidence section 302 ipc " * 80),
                "page_start": 1 if index < 3 else 2,
                "page_end": 1 if index < 3 else 2,
                "heading_path": ["JUDGMENT"],
                "block_type": "paragraph",
                "source_offsets": None,
            }
            for index in range(6)
        ]
        return {
            "document_id": "local:test",
            "source_file_name": "sample.pdf",
            "sha256": "abc123",
            "paragraphs": paragraphs,
            "metadata": {"provider": "local_upload", "source_document_id": "abc123", "text_source_type": "pdf_native"},
        }

    def test_chunking_is_deterministic_with_stable_ids(self) -> None:
        document = self.parsed_document()
        first = chunk_document(document)
        second = chunk_document(document)
        self.assertEqual([chunk["chunk_id"] for chunk in first], [chunk["chunk_id"] for chunk in second])
        self.assertTrue(all(chunk["text"] == chunk["chunk_text"] for chunk in first))

    def test_chunking_respects_size_and_overlap_strategy(self) -> None:
        chunks = chunk_document(self.parsed_document())
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(chunk["estimated_token_count"] for chunk in chunks), 900)
        self.assertLessEqual(chunks[0]["paragraph_end"], chunks[1]["paragraph_end"])
        self.assertLessEqual(chunks[1]["paragraph_start"], chunks[0]["paragraph_end"] + 1)

    def test_provenance_and_heading_are_preserved(self) -> None:
        chunks = chunk_document(self.parsed_document())
        self.assertEqual(chunks[0]["page_start"], 1)
        self.assertIsNotNone(chunks[-1]["page_end"])
        self.assertEqual(chunks[0]["section_heading"], "JUDGMENT")
        self.assertIn("paragraph_start", chunks[0])

    def test_empty_input_rejected(self) -> None:
        with self.assertRaisesRegex(DocumentChunkingError, "no paragraphs"):
            chunk_document({"document_id": "local:empty", "paragraphs": []})


class IngestionBoundaryAdapterTest(unittest.TestCase):
    def test_ingestion_reaches_embedding_and_indexing_with_service_adapters(self) -> None:
        job = FakeJob("job-1")
        fake_db = FakeSession(job)
        embedder = FakeEmbeddingProvider()
        vector_store = FakeVectorStore()
        parsed = ChunkerServiceTest().parsed_document()

        with patch("backend.app.services.ingestion.SessionLocal", return_value=fake_db), patch(
            "backend.app.services.document_parser.parse_document", return_value=parsed
        ):
            process_ingestion_job(
                job_id=job.id,
                file_path="sample.pdf",
                doc_type="judgment",
                embedding_provider=embedder,
                vector_store=vector_store,
            )

        self.assertEqual(job.status, IngestionStatus.COMPLETED.value)
        self.assertEqual(job.progress, 100)
        self.assertEqual(fake_db.commits >= 5, True)
        self.assertTrue(embedder.calls)
        self.assertTrue(vector_store.upserts)


class FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id
        self.status = IngestionStatus.QUEUED.value
        self.progress = 0
        self.document_id = None
        self.error_message = None
        self.started_at = None
        self.completed_at = None


class FakeQuery:
    def __init__(self, job: FakeJob) -> None:
        self.job = job

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.job


class FakeSession:
    def __init__(self, job: FakeJob) -> None:
        self.job = job
        self.commits = 0
        self.added = []

    def query(self, model):
        # Only job lookups find something; document (duplicate) lookups find nothing.
        return FakeQuery(self.job if getattr(model, "__name__", "") == "IngestionJob" else None)

    def add(self, item):
        self.added.append(item)

    def commit(self):
        self.commits += 1

    def refresh(self, item):
        if getattr(item, "id", None) is None:
            item.id = 1

    def rollback(self):
        pass

    def close(self):
        pass


class FakeEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[1.0, 0.0] for _ in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserts = []

    def upsert_chunks(self, **kwargs):
        self.upserts.append(kwargs)
        return {"inserted": len(kwargs["ids"]), "updated": 0, "skipped_unchanged": 0}


db_test_bootstrap.isolate_test_cases(globals())


if __name__ == "__main__":
    unittest.main()
