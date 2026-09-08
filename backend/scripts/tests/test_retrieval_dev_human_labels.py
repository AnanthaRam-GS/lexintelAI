"""Tests for frozen human labels on the retrieval development set."""

from __future__ import annotations

from collections import Counter
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "data/structured/manifests"


class RetrievalDevHumanLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.queries = json.loads((MANIFEST_DIR / "retrieval_dev_queries.json").read_text(encoding="utf-8"))
        cls.judgments = json.loads((MANIFEST_DIR / "retrieval_dev_judgments.json").read_text(encoding="utf-8"))
        cls.traces = json.loads((MANIFEST_DIR / "retrieval_dev_pool_traces.json").read_text(encoding="utf-8"))
        cls.summary = json.loads((MANIFEST_DIR / "retrieval_dev_human_label_summary.json").read_text(encoding="utf-8"))

    def test_dev_labels_are_complete_and_match_corrected_totals(self) -> None:
        statuses = Counter(row["human_status"] for row in self.judgments)
        relevance = Counter(row["human_relevance"] for row in self.judgments)
        self.assertEqual(len(self.queries), 20)
        self.assertEqual(len(self.judgments), 474)
        self.assertEqual(statuses["reviewed"], 474)
        self.assertEqual(statuses["pending"], 0)
        self.assertEqual({2: relevance[2], 1: relevance[1], 0: relevance[0], "uncertain": relevance["uncertain"]}, {2: 103, 1: 174, 0: 197, "uncertain": 0})
        self.assertEqual(self.summary["human_relevance_counts"], {"grade_2": 103, "grade_1": 174, "grade_0": 197, "uncertain": 0})

    def test_labels_have_valid_schema_and_reviewer_fields(self) -> None:
        self.assertTrue(all(row["human_relevance"] in {0, 1, 2, "uncertain"} for row in self.judgments))
        self.assertTrue(all(row["document_relevant"] in {"yes", "no", "uncertain"} for row in self.judgments))
        self.assertTrue(all(row["reviewer"] == "Ananthu" for row in self.judgments))
        self.assertTrue(all(row["reviewed_at"] for row in self.judgments))

    def test_candidate_keys_queries_and_traces_remain_consistent(self) -> None:
        query_ids = {query["query_id"] for query in self.queries}
        keys = [(row["query_id"], row["chunk_id"]) for row in self.judgments]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(row["query_id"] in query_ids for row in self.judgments))
        self.assertEqual(len(self.traces), 474)
        self.assertEqual({(row["query_id"], row["chunk_id"]) for row in self.traces}, set(keys))

    def test_required_edge_cases_are_preserved(self) -> None:
        q006 = [row for row in self.judgments if row["query_id"] == "dev-q006"]
        q007 = [row for row in self.judgments if row["query_id"] == "dev-q007"]
        q012 = [row for row in self.judgments if row["query_id"] == "dev-q012"]
        q016 = [row for row in self.judgments if row["query_id"] == "dev-q016"]
        self.assertEqual(sum(row["human_relevance"] == 2 for row in q006), 0)
        self.assertEqual(sum(row["human_relevance"] == 2 for row in q007), 0)
        self.assertGreater(sum(row["human_relevance"] == 2 for row in q012), 0)
        self.assertGreater(sum(row["document_relevant"] == "yes" for row in q016), 0)


if __name__ == "__main__":
    unittest.main()
