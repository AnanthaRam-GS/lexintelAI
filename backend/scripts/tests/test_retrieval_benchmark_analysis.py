"""Tests for formal retrieval benchmark metric calculations."""

from __future__ import annotations

import unittest

from backend.scripts.analyze_retrieval_eval import (
    bootstrap_deltas,
    document_hit_at_5,
    mrr_at_k,
    ndcg_at_k,
    pooled_recall_at_k,
    precision_at_k,
)


class RetrievalBenchmarkAnalysisTest(unittest.TestCase):
    def test_broad_and_strict_precision_at_5(self) -> None:
        labels = {"a": 2, "b": 1, "c": 0, "d": "uncertain", "e": 2}
        ranking = ["a", "b", "c", "d", "e"]
        self.assertEqual(precision_at_k(ranking, labels, 5, "broad"), 0.6)
        self.assertEqual(precision_at_k(ranking, labels, 5, "strict"), 0.4)

    def test_pooled_recall_and_zero_strict_denominator(self) -> None:
        labels = {"a": 1, "b": 0, "c": "uncertain"}
        self.assertEqual(pooled_recall_at_k(["a", "b"], labels, 5, "broad"), 1.0)
        self.assertIsNone(pooled_recall_at_k(["a", "b"], labels, 5, "strict"))

    def test_unjudged_top20_is_not_counted_as_zero(self) -> None:
        labels = {"a": 2, "b": 1}
        ranking = ["x", "a", "b"]
        with self.assertRaises(KeyError):
            precision_at_k(ranking + ["c", "d"], labels, 5, "broad")
        self.assertEqual(pooled_recall_at_k(ranking, labels, 20, "broad"), 1.0)

    def test_mrr_ndcg_and_document_hit(self) -> None:
        labels = {"a": 0, "b": 2, "c": 1, "d": 0, "e": 0}
        ranking = ["a", "b", "c", "d", "e"]
        self.assertEqual(mrr_at_k(ranking, labels, 5, "broad"), 0.5)
        self.assertAlmostEqual(ndcg_at_k(ranking, labels, 5, "graded"), 0.66967181649423)
        self.assertTrue(document_hit_at_5(ranking, {"a": "no", "b": "yes", "c": "no", "d": "no", "e": "no"}))
        self.assertIsNone(document_hit_at_5(ranking, {"a": "no", "b": "uncertain", "c": "no", "d": "no", "e": "no"}))

    def test_deterministic_bootstrap(self) -> None:
        row = {
            "systems": {
                "hybrid": {"broad_precision_at_5": 0.8, "graded_ndcg_at_5": 0.7, "broad_mrr_at_5": 1.0},
                "dense": {"broad_precision_at_5": 0.6, "graded_ndcg_at_5": 0.5, "broad_mrr_at_5": 0.5},
                "hybrid_rerank": {"broad_precision_at_5": 1.0, "graded_ndcg_at_5": 0.9, "broad_mrr_at_5": 1.0},
            }
        }
        first = bootstrap_deltas([row, row], samples=100, seed=7)
        second = bootstrap_deltas([row, row], samples=100, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first["comparisons"]["hybrid_minus_dense"]["broad_precision_at_5"]["mean_delta"], 0.2)


if __name__ == "__main__":
    unittest.main()
