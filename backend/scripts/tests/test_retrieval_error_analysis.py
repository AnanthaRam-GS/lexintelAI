"""Tests for retrieval benchmark error-analysis helpers."""

from __future__ import annotations

import unittest

from backend.scripts.analyze_retrieval_errors import (
    build_qrels,
    chunk_quality,
    overlap_analysis,
    quality_flags,
    rerank_analysis,
    validate_freeze,
)


class RetrievalErrorAnalysisTest(unittest.TestCase):
    def test_overlap_counts_union_intersection_and_neither(self) -> None:
        queries = [{"query_id": "eval-q001"}]
        qrels = {"eval-q001": {"a": 2, "b": 1, "c": 0, "d": 1}}
        traces = [
            {"query_id": "eval-q001", "chunk_id": "a", "lexical_rank": 1, "dense_rank": 2, "hybrid_rank": 1, "rerank_rank": 1},
            {"query_id": "eval-q001", "chunk_id": "b", "lexical_rank": 2, "dense_rank": None, "hybrid_rank": 2, "rerank_rank": 2},
            {"query_id": "eval-q001", "chunk_id": "c", "lexical_rank": None, "dense_rank": 1, "hybrid_rank": 3, "rerank_rank": 3},
            {"query_id": "eval-q001", "chunk_id": "d", "lexical_rank": None, "dense_rank": None, "hybrid_rank": None, "rerank_rank": None},
        ]
        analysis = overlap_analysis(queries, traces, qrels)
        broad = analysis["per_query"]["eval-q001"]["broad"]
        self.assertEqual(broad["bm25_only"], 1)
        self.assertEqual(broad["intersection"], 1)
        self.assertEqual(broad["neither"], 1)
        self.assertEqual(broad["union"], 2)

    def test_rerank_promotion_and_demotion_detection(self) -> None:
        metrics = [
            {
                "query_id": "eval-q001",
                "systems": {
                    "hybrid": {"broad_precision_at_5": 0.2, "graded_ndcg_at_5": 0.2, "strict_precision_at_5": 0.0},
                    "hybrid_rerank": {"broad_precision_at_5": 0.4, "graded_ndcg_at_5": 0.4, "strict_precision_at_5": 0.2},
                },
            }
        ]
        qrels = {"eval-q001": {str(i): 0 for i in range(1, 8)}}
        qrels["eval-q001"].update({"6": 2, "2": 1})
        traces = [
            {"query_id": "eval-q001", "chunk_id": "1", "hybrid_rank": 1, "rerank_rank": 6},
            {"query_id": "eval-q001", "chunk_id": "2", "hybrid_rank": 2, "rerank_rank": 7},
            {"query_id": "eval-q001", "chunk_id": "3", "hybrid_rank": 3, "rerank_rank": 3},
            {"query_id": "eval-q001", "chunk_id": "4", "hybrid_rank": 4, "rerank_rank": 4},
            {"query_id": "eval-q001", "chunk_id": "5", "hybrid_rank": 5, "rerank_rank": 5},
            {"query_id": "eval-q001", "chunk_id": "6", "hybrid_rank": 6, "rerank_rank": 1},
        ]
        analysis = rerank_analysis(metrics, traces, qrels)
        row = analysis["per_query"]["eval-q001"]
        self.assertEqual(row["status"], "reranker_helpful")
        self.assertEqual(row["grade2_promoted_into_top5"], ["6"])
        self.assertEqual(row["relevant_dropped_from_top5"], ["2"])

    def test_chunk_quality_flags_right_and_wrong_document_cases(self) -> None:
        self.assertEqual(quality_flags({"document_relevant": "yes", "human_relevance": 0}), ["right_document_wrong_chunk"])
        self.assertEqual(quality_flags({"document_relevant": "no", "human_relevance": 1}), ["wrong_document_useful_chunk"])
        queries = [{"query_id": "eval-q001"}]
        judgments = [
            {"query_id": "eval-q001", "chunk_id": "a", "document_relevant": "yes", "human_relevance": 0},
            {"query_id": "eval-q001", "chunk_id": "b", "document_relevant": "no", "human_relevance": 2},
        ]
        traces = [
            {"query_id": "eval-q001", "chunk_id": "a", "lexical_rank": 1, "dense_rank": 1, "hybrid_rank": 1, "rerank_rank": 1},
            {"query_id": "eval-q001", "chunk_id": "b", "lexical_rank": 2, "dense_rank": 2, "hybrid_rank": 2, "rerank_rank": 2},
        ]
        summary = chunk_quality(queries, judgments, traces)
        self.assertEqual(summary["overall"]["right_document_wrong_chunk"], 1)
        self.assertEqual(summary["overall"]["wrong_document_useful_chunk"], 1)

    def test_qrels_and_freeze_validation(self) -> None:
        judgments = [{"query_id": "eval-q001", "chunk_id": "a", "human_relevance": 2, "document_relevant": "yes"}]
        qrels, docrels = build_qrels(judgments)
        self.assertEqual(qrels["eval-q001"]["a"], 2)
        self.assertEqual(docrels["eval-q001"]["a"], "yes")
        results = {"overall": {system: {"broad_precision_at_5": value, "graded_ndcg_at_5": ndcg} for system, value, ndcg in [
            ("bm25", 0.833333, 0.727987),
            ("dense", 0.86, 0.785689),
            ("hybrid", 0.873333, 0.787465),
            ("hybrid_rerank", 0.873333, 0.819445),
        ]}}
        with self.assertRaises(ValueError):
            validate_freeze([{"query_id": "eval-q001"}], judgments, {"reviewed": 1, "pending": 0}, results)


if __name__ == "__main__":
    unittest.main()
