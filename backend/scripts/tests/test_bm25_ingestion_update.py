"""Tests for incremental BM25 maintenance during trusted ingestion."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app.api import query as query_api
from backend.app.services import ingestion
from backend.app.services.retrieval.bm25 import (
    DEFAULT_B,
    DEFAULT_INDEX_NAME,
    DEFAULT_K1,
    LEXICAL_INDEX_VERSION,
    TOKENIZER_VERSION,
    Bm25Config,
    Bm25LexicalIndex,
)


class Bm25IngestionUpdateTests(unittest.TestCase):
    def test_upsert_is_idempotent_and_preserves_frozen_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Bm25LexicalIndex(Path(tmp), DEFAULT_INDEX_NAME, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
            first = index.upsert_chunks([trusted_chunk("doc:7:chunk:0000", "uniquelexicaltoken bail context")])
            second = index.upsert_chunks([trusted_chunk("doc:7:chunk:0000", "uniquelexicaltoken bail context")])

            self.assertEqual(first["inserted"], 1)
            self.assertEqual(second["skipped_unchanged"], 1)
            self.assertEqual(index.count(), 1)
            self.assertEqual(index.metadata["index_version"], LEXICAL_INDEX_VERSION)
            self.assertEqual(index.metadata["tokenizer_version"], TOKENIZER_VERSION)
            self.assertEqual(index.metadata["k1"], DEFAULT_K1)
            self.assertEqual(index.metadata["b"], DEFAULT_B)

    def test_new_chunk_is_retrievable_after_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Bm25LexicalIndex(Path(tmp), DEFAULT_INDEX_NAME, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
            index.upsert_chunks([trusted_chunk("doc:1:chunk:0000", "baseline murder evidence")])
            self.assertEqual(index.query("newtokenonly", top_k=5), [])

            index.upsert_chunks([trusted_chunk("doc:2:chunk:0000", "newtokenonly appears in trusted upload")])
            results = index.query("newtokenonly", top_k=5)

            self.assertEqual(results[0].chunk_id, "doc:2:chunk:0000")
            self.assertEqual(results[0].retrieval_mode, "lexical")

    def test_atomic_persist_preserves_previous_index_on_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            persist_dir = Path(tmp)
            index = Bm25LexicalIndex(persist_dir, DEFAULT_INDEX_NAME, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
            index.upsert_chunks([trusted_chunk("doc:1:chunk:0000", "baseline token")])
            original_payload = index.path.read_text(encoding="utf-8")

            with patch("backend.app.services.retrieval.bm25.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    index.upsert_chunks([trusted_chunk("doc:2:chunk:0000", "new token")])

            self.assertEqual(index.path.read_text(encoding="utf-8"), original_payload)
            reloaded = Bm25LexicalIndex(persist_dir, DEFAULT_INDEX_NAME, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
            self.assertEqual(reloaded.count(), 1)
            self.assertEqual(reloaded.query("baseline", top_k=1)[0].chunk_id, "doc:1:chunk:0000")

    def test_duplicate_update_batch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            index = Bm25LexicalIndex(Path(tmp), DEFAULT_INDEX_NAME, Bm25Config(k1=DEFAULT_K1, b=DEFAULT_B))
            chunk = trusted_chunk("doc:1:chunk:0000", "same")
            with self.assertRaises(ValueError):
                index.upsert_chunks([chunk, chunk])

    def test_ingestion_bm25_chunk_adapter_uses_persisted_document_ids(self) -> None:
        doc = type("Doc", (), {"id": 42, "source_url": "https://example.test", "case_name": "State v Sample", "court_level": "high_court", "year": 2024, "checksum": "abc"})()
        chunks = [{"text": "trusted text", "chunk_index": 0, "page_start": 1, "page_end": 2, "paragraph_start": 3, "paragraph_end": 4}]
        result = ingestion.trusted_bm25_chunks(doc, chunks, ["doc:42:chunk:0000"])

        self.assertEqual(result[0]["chunk_id"], "doc:42:chunk:0000")
        self.assertEqual(result[0]["document_id"], "42")
        self.assertEqual(result[0]["chunk_text"], "trusted text")
        self.assertEqual(result[0]["provider"], "admin_upload")

    def test_retrieval_cache_can_be_invalidated_after_ingestion_update(self) -> None:
        query_api._cached_retrieval_service.cache_clear()
        marker = object()
        with patch.object(query_api, "make_service", return_value=marker) as make_service:
            self.assertIs(query_api.get_retrieval_service(), marker)
            self.assertIs(query_api.get_retrieval_service(), marker)
            query_api.clear_retrieval_service_cache()
            self.assertIs(query_api.get_retrieval_service(), marker)
        self.assertEqual(make_service.call_count, 2)

    def test_professional_pdf_flow_does_not_call_bm25_mutation(self) -> None:
        with patch.object(ingestion, "update_trusted_bm25_index") as update_bm25:
            context = query_api.build_private_pdf_context(
                {"source_file_name": "upload.pdf"},
                [{"chunk_id": "private-1", "text": "private facts", "page_start": 1, "page_end": 1}],
                query="private facts",
            )
        self.assertIn("private facts", context)
        update_bm25.assert_not_called()


def trusted_chunk(chunk_id: str, text: str) -> dict:
    document_id = chunk_id.split(":chunk:", 1)[0]
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "chunk_text": text,
        "provider": "admin_upload",
        "source_document_id": document_id,
        "source_url": "https://example.test/doc",
        "case_title": "State v Sample",
        "court": {},
        "decision_date": None,
        "decision_year": 2024,
        "effective_offence_family": "homicide",
        "effective_legal_regime": "ipc_crpc",
        "chunk_index": 0,
        "paragraph_start": 1,
        "paragraph_end": 1,
        "page_start": 1,
        "page_end": 1,
        "text_source_type": "pdf_native",
        "raw_sha256": "abc",
        "normalizer_version": "test-normalizer",
        "chunker_version": "test-chunker",
    }


if __name__ == "__main__":
    unittest.main()
