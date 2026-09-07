"""Tests for BM25 lexical and hybrid retrieval foundation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.retrieval.bm25 import Bm25Config, Bm25LexicalIndex, LEXICAL_INDEX_VERSION, tokenize_legal_text
from backend.app.services.retrieval.service import HybridConfig, RetrievalService, reciprocal_rank_fusion
from backend.app.services.vector_store import RetrievalResult
from backend.scripts import build_vector_index as builder


class FakeDenseProvider:
    config = EmbeddingConfig(model_name="fake", dimension=2)

    @property
    def embedding_dimension(self) -> int:
        return 2

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


class FakeVectorStore:
    def __init__(self, results: list[RetrievalResult]) -> None:
        self.results = results

    def query_dense(self, vector: list[float], top_k: int = 5, filters: dict[str, object] | None = None) -> list[RetrievalResult]:
        rows = self.results
        if filters and filters.get("effective_offence_family"):
            rows = [row for row in rows if row.effective_offence_family == filters["effective_offence_family"]]
        return rows[:top_k]


class RetrievalFoundationTest(unittest.TestCase):
    def chunk(self, chunk_id: str, text: str, family: str = "homicide") -> dict[str, object]:
        row = builder.load_chunks(limit=1)[0]
        row = dict(row)
        row.update(
            {
                "chunk_id": chunk_id,
                "document_id": chunk_id.rsplit(":chunk:", 1)[0],
                "chunk_text": text,
                "effective_offence_family": family,
                "effective_legal_regime": "ipc_crpc",
                "case_title": f"Case {chunk_id}",
            }
        )
        return row

    def result(self, chunk_id: str, rank: int, score: float, family: str = "homicide") -> RetrievalResult:
        return RetrievalResult(
            chunk_id=chunk_id,
            document_id=chunk_id.split(":chunk:")[0],
            text="section text",
            score=score,
            rank=rank,
            case_title=f"Case {chunk_id}",
            court={"court_name": "Court", "court_level": "high_court"},
            decision_date="2025-01-01",
            source_url="https://example.test",
            page_start=1,
            page_end=2,
            paragraph_start=1,
            paragraph_end=2,
            effective_offence_family=family,
            effective_legal_regime="ipc_crpc",
            text_source_type="pdf_native",
        )

    def test_tokenizer_preserves_statutes_and_equivalences(self) -> None:
        tokens = tokenize_legal_text("Sections 304-B, 498A, 302 IPC, 376 Cr.P.C. BNSS NDPS")
        self.assertIn("304-b", tokens)
        self.assertIn("304b", tokens)
        self.assertIn("498a", tokens)
        self.assertIn("498-a", tokens)
        self.assertIn("302", tokens)
        self.assertIn("ipc", tokens)
        self.assertIn("crpc", tokens)
        self.assertIn("bnss", tokens)
        self.assertIn("ndps", tokens)

    def test_bm25_index_count_ranking_and_provenance(self) -> None:
        chunks = [
            self.chunk("doc:1:chunk:0000", "murder conviction section 302 IPC"),
            self.chunk("doc:2:chunk:0000", "dowry death section 304-B IPC", "dowry_and_domestic_cruelty"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            index = Bm25LexicalIndex(Path(tmp), config=Bm25Config())
            build = index.build(chunks, rebuild=True)
            self.assertEqual(build["indexed_chunks"], 2)
            self.assertEqual(index.count(), 2)
            results = index.query("section 304B IPC", top_k=1)
            self.assertEqual(results[0].chunk_id, "doc:2:chunk:0000")
            self.assertEqual(results[0].effective_offence_family, "dowry_and_domestic_cruelty")
            self.assertEqual(index.query("", top_k=5), [])
            self.assertEqual(index.query("termnotpresent", top_k=5), [])
            self.assertEqual(index.query("section 304B IPC", top_k=2), index.query("section 304B IPC", top_k=2))

    def test_bm25_index_version_and_chunk_universe_mismatch(self) -> None:
        chunks = [self.chunk("doc:1:chunk:0000", "section 302 ipc")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legalai_trusted_judgments_bm25_v1.json"
            path.write_text(json.dumps({"metadata": {"index_version": "old"}, "records": []}), encoding="utf-8")
            with self.assertRaises(ValueError):
                Bm25LexicalIndex(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            index = Bm25LexicalIndex(Path(tmp))
            index.build(chunks, rebuild=True)
            changed = [self.chunk("doc:1:chunk:0000", "different section 302 ipc")]
            with self.assertRaises(ValueError):
                index.build(changed, rebuild=False)

    def test_rrf_formula_deduplicates_and_preserves_diagnostics(self) -> None:
        dense = [self.result("doc:1:chunk:0000", 1, 0.9), self.result("doc:2:chunk:0000", 2, 0.8)]
        lexical = [self.result("doc:1:chunk:0000", 1, 7.0), self.result("doc:3:chunk:0000", 2, 6.0)]
        fused = reciprocal_rank_fusion(dense, lexical, rrf_k=60)
        self.assertEqual(fused[0].chunk_id, "doc:1:chunk:0000")
        self.assertAlmostEqual(fused[0].hybrid_score or 0, (1 / 61) + (1 / 61))
        self.assertEqual(fused[0].dense_rank, 1)
        self.assertEqual(fused[0].lexical_rank, 1)
        self.assertEqual(len({row.chunk_id for row in fused}), 3)

    def test_retrieval_service_modes_candidates_topk_filters_and_provenance(self) -> None:
        dense = [self.result("doc:1:chunk:0000", 1, 0.9), self.result("doc:2:chunk:0000", 2, 0.8, "theft_and_robbery")]
        lexical_chunks = [
            self.chunk("doc:1:chunk:0000", "murder conviction section 302 IPC"),
            self.chunk("doc:3:chunk:0000", "murder common intention section 34 IPC"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            lexical = Bm25LexicalIndex(Path(tmp))
            lexical.build(lexical_chunks, rebuild=True)
            service = RetrievalService(FakeDenseProvider(), FakeVectorStore(dense), lexical, HybridConfig(rrf_k=60, candidate_k=2))
            dense_response = service.retrieve("murder section 302", "dense", top_k=1)
            self.assertEqual(dense_response.results[0].retrieval_mode, "dense")
            lexical_response = service.retrieve("murder section 302", "lexical", top_k=1)
            self.assertEqual(lexical_response.results[0].retrieval_mode, "lexical")
            hybrid_response = service.retrieve("murder section 302", "hybrid", top_k=2, candidate_k=2)
            self.assertLessEqual(len(hybrid_response.results), 2)
            self.assertEqual(hybrid_response.trace.candidate_k, 2)
            self.assertTrue(all(result.case_title for result in hybrid_response.results))
            filtered = service.retrieve("murder section 302", "hybrid", top_k=5, filters={"effective_offence_family": "homicide"})
            self.assertTrue(all(result.effective_offence_family == "homicide" for result in filtered.results))
            self.assertEqual(lexical.metadata["index_version"], LEXICAL_INDEX_VERSION)


if __name__ == "__main__":
    unittest.main()
