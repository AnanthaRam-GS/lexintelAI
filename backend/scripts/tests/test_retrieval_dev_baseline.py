"""Tests for untuned retrieval development-set baseline outputs."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "data/structured/manifests"


class RetrievalDevBaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = json.loads((MANIFEST_DIR / "retrieval_dev_results.json").read_text(encoding="utf-8"))
        cls.per_query = json.loads((MANIFEST_DIR / "retrieval_dev_per_query_metrics.json").read_text(encoding="utf-8"))
        cls.coverage = json.loads((MANIFEST_DIR / "retrieval_dev_judged_coverage.json").read_text(encoding="utf-8"))
        cls.overlap = json.loads((MANIFEST_DIR / "retrieval_dev_candidate_overlap.json").read_text(encoding="utf-8"))
        cls.bootstrap = json.loads((MANIFEST_DIR / "retrieval_dev_bootstrap.json").read_text(encoding="utf-8"))

    def test_dev_baseline_counts_and_systems(self) -> None:
        self.assertEqual(len(self.per_query), 20)
        self.assertEqual(set(self.results["overall"]), {"bm25", "dense", "hybrid", "hybrid_rerank"})
        self.assertEqual(self.results["overall"]["hybrid"]["strict_eligible_query_count"], 18)

    def test_judged_coverage_top5_complete_and_top20_censored(self) -> None:
        self.assertTrue(all(row["judged_coverage_at_5"] == 1.0 for row in self.coverage.values()))
        self.assertTrue(all(row["judged_coverage_at_20"] < 1.0 for row in self.coverage.values()))

    def test_zero_strict_qrel_queries_are_marked(self) -> None:
        statuses = {row["query_id"]: row["strict_status"] for row in self.per_query}
        self.assertEqual(statuses["dev-q006"], "not_applicable_no_strict_relevant_qrel")
        self.assertEqual(statuses["dev-q007"], "not_applicable_no_strict_relevant_qrel")

    def test_focus_breakdown_and_overlap_are_present(self) -> None:
        self.assertIn("legal_regime", self.results["tuning_focus_breakdown"])
        self.assertIn("metadata_reranking", self.results["tuning_focus_breakdown"])
        self.assertGreater(self.overlap["aggregate"]["broad"]["bm25_only"], 0)
        self.assertGreater(self.overlap["aggregate"]["broad"]["dense_only"], 0)

    def test_rerank_delta_and_bootstrap_are_deterministic_outputs(self) -> None:
        delta = self.results["rerank_delta"]["broad_precision_at_5"]
        self.assertEqual(len(delta["improved"]), 6)
        self.assertEqual(len(delta["worsened"]), 2)
        self.assertEqual(delta["mean_delta"], 0.06)
        self.assertEqual(self.bootstrap["samples"], 10000)
        self.assertEqual(self.bootstrap["seed"], 20260907)


if __name__ == "__main__":
    unittest.main()
