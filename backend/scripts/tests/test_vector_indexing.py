"""Tests for dense embedding and vector-index infrastructure."""

from __future__ import annotations

import json
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

from backend.app.services.embeddings.base import EmbeddingConfig, validate_vectors
from backend.app.services.embeddings.mock import DeterministicMockEmbeddingProvider
from backend.app.services.vector_store import INDEX_VERSION, ChromaVectorStore, JsonVectorStore, metadata_for_chroma
from backend.scripts import build_vector_index as builder


class VectorIndexingTest(unittest.TestCase):
    def chunk(self, chunk_id: str = "doc:1:chunk:0000", text: str = "murder conviction section 302 IPC") -> dict[str, object]:
        return {
            "chunk_id": chunk_id,
            "document_id": "doc:1",
            "provider": "indian_kanoon",
            "source_document_id": "1",
            "source_url": "https://indiankanoon.org/doc/1/",
            "case_title": "A vs B",
            "court": {"court_name": "Court", "court_level": "high_court"},
            "decision_date": "2024-01-01",
            "decision_year": 2024,
            "effective_offence_family": "homicide",
            "effective_legal_regime": "ipc_crpc",
            "chunk_index": 0,
            "paragraph_start": 0,
            "paragraph_end": 1,
            "page_start": 1,
            "page_end": 2,
            "heading_path": ["JUDGMENT"],
            "text_source_type": "pdf_native",
            "raw_sha256": "sha",
            "chunk_text": text,
            "estimated_token_count": 10,
            "normalizer_version": "normalizer",
            "chunker_version": "chunker",
        }

    def test_mock_embeddings_are_deterministic_and_normalized(self) -> None:
        provider = DeterministicMockEmbeddingProvider(EmbeddingConfig(model_name="mock", dimension=16, normalize_embeddings=True))
        first = provider.embed_query("same text")
        second = provider.embed_query("same text")
        other = provider.embed_query("different text")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 16)
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in first)), 1.0, places=6)

    def test_vector_validation_rejects_bad_vectors(self) -> None:
        self.assertEqual(validate_vectors([[0.1, 0.2]], 2), 2)
        with self.assertRaises(ValueError):
            validate_vectors([[0.0, 0.0]], 2)
        with self.assertRaises(ValueError):
            validate_vectors([[0.1], [0.1, 0.2]], None)

    def test_metadata_preserves_provenance_and_optional_pages(self) -> None:
        chunk = self.chunk()
        metadata = metadata_for_chroma(chunk, "fp")
        self.assertEqual(metadata["source_url"], chunk["source_url"])
        self.assertEqual(metadata["page_start"], 1)
        self.assertTrue(metadata["has_page_provenance"])
        non_pdf = dict(chunk, page_start=None, page_end=None, text_source_type="local_text")
        metadata = metadata_for_chroma(non_pdf, "fp")
        self.assertEqual(metadata["page_start"], -1)
        self.assertFalse(metadata["has_page_provenance"])

    def test_json_vector_store_upsert_query_delete_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonVectorStore(Path(tmp), "collection", {"index_version": INDEX_VERSION})
            provider = DeterministicMockEmbeddingProvider(EmbeddingConfig(model_name="mock", dimension=8, normalize_embeddings=True))
            chunk = self.chunk()
            vector = provider.embed_query(chunk["chunk_text"])
            metadata = metadata_for_chroma(chunk, "fp")
            counts = store.upsert_chunks([chunk["chunk_id"]], [vector], [chunk["chunk_text"]], [metadata])
            self.assertEqual(counts["inserted"], 1)
            counts = store.upsert_chunks([chunk["chunk_id"]], [vector], [chunk["chunk_text"]], [metadata])
            self.assertEqual(counts["skipped_unchanged"], 1)
            results = store.query_dense(provider.embed_query("murder section 302"), top_k=1)
            self.assertEqual(results[0].chunk_id, chunk["chunk_id"])
            self.assertEqual(results[0].source_url, chunk["source_url"])
            self.assertEqual(store.delete_document("doc:1"), 1)
            self.assertEqual(store.count(), 0)

    def test_index_version_mismatch_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collection.json"
            path.write_text(json.dumps({"metadata": {"index_version": "old"}, "records": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                JsonVectorStore(Path(tmp), "collection", {"index_version": INDEX_VERSION})

    def test_chroma_adapter_fails_safely_when_dependency_missing(self) -> None:
        if importlib.util.find_spec("chromadb") is not None:
            self.skipTest("chromadb is installed in this environment")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                ChromaVectorStore(Path(tmp), "collection", {"index_version": INDEX_VERSION})

    def test_chroma_vector_store_upsert_query_delete_and_idempotency(self) -> None:
        if importlib.util.find_spec("chromadb") is None:
            self.skipTest("chromadb is not installed in this environment")
        with tempfile.TemporaryDirectory() as tmp:
            store = ChromaVectorStore(Path(tmp), "collection", {"index_version": INDEX_VERSION, "hnsw:space": "cosine"})
            provider = DeterministicMockEmbeddingProvider(EmbeddingConfig(model_name="mock", dimension=8, normalize_embeddings=True))
            chunk = self.chunk()
            vector = provider.embed_query(chunk["chunk_text"])
            metadata = metadata_for_chroma(chunk, "fp")
            counts = store.upsert_chunks([chunk["chunk_id"]], [vector], [chunk["chunk_text"]], [metadata])
            self.assertEqual(counts["inserted"], 1)
            self.assertEqual(store.existing_fingerprints([chunk["chunk_id"]]), {chunk["chunk_id"]: "fp"})
            self.assertIsNotNone(store.get_chunk(chunk["chunk_id"]))
            results = store.query_dense(provider.embed_query("murder section 302"), top_k=1)
            self.assertEqual(results[0].chunk_id, chunk["chunk_id"])
            self.assertTrue(math.isfinite(results[0].score))
            self.assertEqual(store.delete_document("doc:1"), 1)
            self.assertEqual(store.count(), 0)

    def test_fingerprint_changes_with_text_or_model(self) -> None:
        config = EmbeddingConfig(model_name="mock", dimension=8)
        chunk = self.chunk()
        first = builder.index_fingerprint(chunk, config)
        changed_text = dict(chunk, chunk_text="different")
        changed_model = EmbeddingConfig(model_name="other", dimension=8)
        self.assertNotEqual(first, builder.index_fingerprint(changed_text, config))
        self.assertNotEqual(first, builder.index_fingerprint(chunk, changed_model))

    def test_build_index_is_idempotent_and_prevents_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chunks = [self.chunk("doc:1:chunk:0000"), self.chunk("doc:1:chunk:0001", "dowry death section 304B")]
            provider = DeterministicMockEmbeddingProvider(EmbeddingConfig(model_name="mock", dimension=8))
            first = builder.build_index(chunks, provider, Path(tmp), "collection", rebuild=True, batch_size=1)
            second = builder.build_index(chunks, provider, Path(tmp), "collection", rebuild=False, batch_size=1)
            self.assertEqual(first["inserted"], 2)
            self.assertEqual(second["skipped_unchanged"], 2)
            self.assertEqual(second["embedded"], 0)
            self.assertEqual(second["final_collection_count"], 2)

    def test_failure_isolation(self) -> None:
        class FailingProvider(DeterministicMockEmbeddingProvider):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            result = builder.build_index([self.chunk()], FailingProvider(EmbeddingConfig(model_name="mock", dimension=8)), Path(tmp), "collection", rebuild=True)
            self.assertEqual(result["failed"], 1)
            self.assertEqual(result["final_collection_count"], 0)

    def test_dry_run_uses_real_chunk_outputs_without_embedding(self) -> None:
        chunks = builder.load_chunks(limit=3)
        summary = builder.dry_run_summary(chunks, "collection", Path("chroma_store"), EmbeddingConfig())
        self.assertEqual(summary["expected_chunks"], 3)
        self.assertFalse(summary["would_mutate_vector_store"])


if __name__ == "__main__":
    unittest.main()
