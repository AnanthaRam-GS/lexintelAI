"""Tests for the human-labelled retrieval evaluation workflow."""

from __future__ import annotations

from collections import Counter
import json
import math
import tempfile
import unittest
from pathlib import Path

from backend.app.services.retrieval.evaluation import (
    PoolingConfig,
    apply_review,
    build_query_manifest,
    generate_pool,
    mrr,
    ndcg_at_k,
    pooled_recall_at_k,
    precision_at_k,
    validate_judgment,
)
from backend.app.services.vector_store import RetrievalResult
from backend.scripts.build_vector_index import load_chunks
from backend.scripts.tests.local_corpus import requires_local_corpus


class FakeRetriever:
    def retrieve(self, query: str, mode: str, top_k: int, candidate_k: int, rerank: bool = False) -> list[RetrievalResult]:
        prefix = "rerank" if rerank else mode
        shared = self.result(f"{query}:shared:chunk:0000", 1, 1.0, prefix)
        rows = [shared]
        for rank in range(2, top_k + 1):
            rows.append(self.result(f"{query}:{prefix}:chunk:{rank:04d}", rank, 1.0 / rank, prefix))
        return rows

    def result(self, chunk_id: str, rank: int, score: float, label: str) -> RetrievalResult:
        return RetrievalResult(
            chunk_id=chunk_id,
            document_id=chunk_id.split(":chunk:")[0],
            text=f"{label} candidate text for section 302 IPC with enough context.",
            score=score,
            rank=rank,
            case_title=f"Case {chunk_id}",
            court={"court_name": "Test Court", "court_level": "high_court"},
            decision_date="2025-01-01",
            source_url="https://example.test/judgment",
            page_start=1,
            page_end=1,
            paragraph_start=1,
            paragraph_end=2,
            effective_offence_family="homicide",
            effective_legal_regime="ipc_crpc",
            text_source_type="pdf_native",
            retrieval_mode=label,
            rerank_score=score if label == "rerank" else None,
        )


class RetrievalEvaluationTest(unittest.TestCase):
    @requires_local_corpus
    def test_query_manifest_is_balanced_and_corpus_supported(self) -> None:
        chunks = load_chunks()
        queries = build_query_manifest(chunks)
        self.assertEqual(len(queries), 30)
        self.assertEqual([query["query_id"] for query in queries], [f"eval-q{index:03d}" for index in range(1, 31)])
        self.assertEqual(
            Counter(query["query_type"] for query in queries),
            {
                "statute_explicit": 10,
                "plain_language": 8,
                "procedural_relief": 6,
                "transition_regime": 3,
                "hard_ambiguous": 3,
            },
        )
        self.assertIn("prior_sanity_query", {query["origin"] for query in queries})
        self.assertTrue(all(query["corpus_supporting_document_ids"] for query in queries))

    def test_pooling_deduplicates_caps_and_blinds_judgments(self) -> None:
        query = {"query_id": "eval-q001", "query_text": "murder conviction section 302 IPC"}
        judgments, traces = generate_pool([query], FakeRetriever(), PoolingConfig(candidate_depth=8, primary_depth=6, always_retain_top=2, max_pool_size=10))
        self.assertEqual(len(judgments), 10)
        self.assertEqual(len(traces), 10)
        self.assertEqual(len({row["chunk_id"] for row in judgments}), 10)
        self.assertTrue(all(row["human_status"] == "pending" for row in judgments))
        self.assertTrue(all(row["reviewer"] == "" for row in judgments))
        trace_keys = {"dense_rank", "dense_score", "lexical_rank", "lexical_score", "hybrid_rank", "hybrid_score", "rerank_rank", "rerank_score"}
        self.assertTrue(all(trace_keys.isdisjoint(row) for row in judgments))
        self.assertTrue(any(trace_keys & set(row) for row in traces))
        self.assertTrue(all(row["query_id"] == "eval-q001" for row in judgments))

    def test_review_application_updates_only_judgment_manifest(self) -> None:
        query = {"query_id": "eval-q001", "query_text": "murder conviction section 302 IPC"}
        judgments, traces = generate_pool([query], FakeRetriever(), PoolingConfig(candidate_depth=3, primary_depth=3, max_pool_size=5))
        with tempfile.TemporaryDirectory() as tmp:
            judgments_path = Path(tmp) / "judgments.json"
            traces_path = Path(tmp) / "traces.json"
            judgments_path.write_text(json.dumps(judgments, indent=2), encoding="utf-8")
            trace_before = json.dumps(traces, indent=2)
            traces_path.write_text(trace_before, encoding="utf-8")
            updated = apply_review(judgments_path, "eval-q001", judgments[0]["chunk_id"], 2, "yes", "reviewer-a", "2026-09-07T00:00:00+00:00", "direct answer")
            self.assertEqual(updated["human_status"], "reviewed")
            self.assertEqual(updated["human_relevance"], 2)
            self.assertEqual(traces_path.read_text(encoding="utf-8"), trace_before)

    def test_relevance_validation_and_metric_scaffold(self) -> None:
        labels = {"a": 2, "b": 1, "c": 0, "d": "uncertain"}
        results = ["c", "b", "a", "d"]
        self.assertEqual(precision_at_k(results, labels, 2), 0.5)
        self.assertEqual(pooled_recall_at_k(results, labels, 3), 1.0)
        self.assertEqual(mrr(results, labels), 0.5)
        self.assertTrue(math.isclose(ndcg_at_k(results, labels, 3), 0.58688267143572))
        self.assertEqual(precision_at_k(results, {}, 5), "not_available")
        valid = {"human_relevance": "uncertain", "document_relevant": "uncertain", "notes": ""}
        validate_judgment(valid)
        invalid = dict(valid, human_relevance=3)
        with self.assertRaises(ValueError):
            validate_judgment(invalid)


if __name__ == "__main__":
    unittest.main()
