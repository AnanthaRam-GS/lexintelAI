"""Tests for reranking foundation."""

from __future__ import annotations

import unittest

from backend.app.services.embeddings.base import EmbeddingConfig
from backend.app.services.reranking.base import Reranker, RerankerConfig
from backend.app.services.reranking.mock import DeterministicMockReranker
from backend.app.services.retrieval.service import HybridConfig, RetrievalService
from backend.app.services.vector_store import RetrievalResult


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


class RuleReranker(Reranker):
    def __init__(self, scores: dict[str, float], fail: bool = False) -> None:
        self.config = RerankerConfig(model_name="rule-reranker", top_k=5)
        self.scores = scores
        self.fail = fail

    def score_pairs(self, query: str, candidates: list[RetrievalResult]) -> list[float]:
        if self.fail:
            raise RuntimeError("reranker failed")
        return [self.scores.get(candidate.chunk_id, 0.0) for candidate in candidates]


class RerankingFoundationTest(unittest.TestCase):
    def result(self, chunk_id: str, rank: int, score: float, family: str = "homicide") -> RetrievalResult:
        return RetrievalResult(
            chunk_id=chunk_id,
            document_id=chunk_id.split(":chunk:")[0],
            text=("long text " * 200) + chunk_id,
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
            retrieval_mode="hybrid",
            dense_rank=rank,
            dense_score=score,
            hybrid_score=score,
        )

    def test_mock_reranker_is_deterministic(self) -> None:
        candidates = [self.result("doc:1:chunk:0000", 1, 0.3), self.result("doc:2:chunk:0000", 2, 0.2)]
        reranker = DeterministicMockReranker()
        first = reranker.rerank("section 302", candidates, top_k=2)
        second = reranker.rerank("section 302", candidates, top_k=2)
        self.assertEqual(first, second)

    def test_reranker_ordering_topk_and_pre_ranks_preserved(self) -> None:
        candidates = [self.result("doc:1:chunk:0000", 1, 0.3), self.result("doc:2:chunk:0000", 2, 0.2), self.result("doc:3:chunk:0000", 3, 0.1)]
        reranker = RuleReranker({"doc:3:chunk:0000": 9.0, "doc:1:chunk:0000": 4.0, "doc:2:chunk:0000": 4.0})
        results = reranker.rerank("section 302", candidates, top_k=2)
        self.assertEqual([result.chunk_id for result in results], ["doc:3:chunk:0000", "doc:1:chunk:0000"])
        self.assertEqual(results[0].pre_rerank_rank, 3)
        self.assertEqual(results[0].pre_rerank_score, 0.1)
        self.assertEqual(results[0].rerank_rank, 1)
        self.assertEqual(results[0].dense_rank, 3)
        self.assertEqual(results[0].hybrid_score, 0.1)

    def test_provenance_unchanged_and_no_duplicate_ids(self) -> None:
        candidate = self.result("doc:1:chunk:0000", 1, 0.3)
        reranked = RuleReranker({"doc:1:chunk:0000": 1.0}).rerank("query", [candidate], top_k=1)[0]
        for field in [
            "chunk_id",
            "document_id",
            "text",
            "source_url",
            "court",
            "decision_date",
            "page_start",
            "page_end",
            "paragraph_start",
            "paragraph_end",
            "effective_offence_family",
            "effective_legal_regime",
            "text_source_type",
        ]:
            self.assertEqual(getattr(candidate, field), getattr(reranked, field))
        self.assertEqual(len({reranked.chunk_id}), 1)

    def test_empty_one_candidate_ties_and_failure(self) -> None:
        reranker = RuleReranker({})
        self.assertEqual(reranker.rerank("query", [], top_k=5), [])
        one = reranker.rerank("query", [self.result("doc:1:chunk:0000", 1, 0.3)], top_k=5)
        self.assertEqual(len(one), 1)
        tied = reranker.rerank("query", [self.result("doc:2:chunk:0000", 2, 0.2), self.result("doc:1:chunk:0000", 1, 0.3)], top_k=2)
        self.assertEqual([result.chunk_id for result in tied], ["doc:2:chunk:0000", "doc:1:chunk:0000"])
        with self.assertRaises(RuntimeError):
            RuleReranker({}, fail=True).rerank("query", [self.result("doc:1:chunk:0000", 1, 0.3)], top_k=1)

    def test_service_reranks_candidate_k_and_filters(self) -> None:
        candidates = [
            self.result("doc:1:chunk:0000", 1, 0.3, "homicide"),
            self.result("doc:2:chunk:0000", 2, 0.2, "theft_and_robbery"),
            self.result("doc:3:chunk:0000", 3, 0.1, "homicide"),
        ]
        service = RetrievalService(
            dense_provider=FakeDenseProvider(),
            vector_store=FakeVectorStore(candidates),
            reranker=RuleReranker({"doc:3:chunk:0000": 9.0, "doc:1:chunk:0000": 1.0}),
            hybrid_config=HybridConfig(candidate_k=3),
        )
        response = service.retrieve("section 302", "dense", top_k=1, candidate_k=3, rerank=True, filters={"effective_offence_family": "homicide"})
        self.assertEqual(response.results[0].chunk_id, "doc:3:chunk:0000")
        self.assertEqual(response.results[0].pre_rerank_rank, 2)
        self.assertTrue(response.trace.rerank)
        self.assertEqual(response.trace.candidate_k, 3)

    def test_config_documents_max_length_truncation_policy(self) -> None:
        config = RerankerConfig(max_length=256)
        self.assertEqual(config.max_length, 256)
        self.assertIn("max_length", config.truncation_policy)


if __name__ == "__main__":
    unittest.main()
