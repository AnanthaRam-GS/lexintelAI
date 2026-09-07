"""Tests for frozen human retrieval relevance labels."""

from __future__ import annotations

from collections import Counter
import json
import unittest
from pathlib import Path

from backend.scripts.build_vector_index import load_chunks


ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "data/structured/manifests"
JUDGMENTS_PATH = MANIFEST_DIR / "retrieval_eval_judgments.json"
QUERIES_PATH = MANIFEST_DIR / "retrieval_eval_queries.json"
TRACES_PATH = MANIFEST_DIR / "retrieval_eval_pool_traces.json"
SUMMARY_PATH = MANIFEST_DIR / "retrieval_eval_human_label_summary.json"


class RetrievalEvalHumanLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.queries = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
        cls.judgments = json.loads(JUDGMENTS_PATH.read_text(encoding="utf-8"))
        cls.traces = json.loads(TRACES_PATH.read_text(encoding="utf-8"))
        cls.summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

    def test_all_labels_are_complete_and_valid(self) -> None:
        self.assertEqual(len(self.queries), 30)
        self.assertEqual(len(self.judgments), 695)
        statuses = Counter(row["human_status"] for row in self.judgments)
        self.assertEqual(statuses["reviewed"], 695)
        self.assertEqual(statuses["pending"], 0)
        self.assertTrue(all(row["human_relevance"] in {0, 1, 2, "uncertain"} for row in self.judgments))
        self.assertTrue(all(row["document_relevant"] in {"yes", "no", "uncertain"} for row in self.judgments))
        self.assertTrue(all(row["reviewer"] == "Ananthu" for row in self.judgments))
        self.assertTrue(all(row["reviewed_at"] for row in self.judgments))

    def test_chunk_query_and_judgment_keys_are_valid(self) -> None:
        query_ids = {query["query_id"] for query in self.queries}
        chunk_ids = {chunk["chunk_id"] for chunk in load_chunks()}
        judgment_keys = [(row["query_id"], row["chunk_id"]) for row in self.judgments]
        self.assertEqual(len(judgment_keys), len(set(judgment_keys)))
        self.assertTrue(all(row["query_id"] in query_ids for row in self.judgments))
        self.assertTrue(all(row["chunk_id"] in chunk_ids for row in self.judgments))
        self.assertEqual([query["query_id"] for query in self.queries], [f"eval-q{index:03d}" for index in range(1, 31)])

    def test_summary_matches_manifest_counts(self) -> None:
        relevance = Counter(row["human_relevance"] for row in self.judgments)
        document = Counter(row["document_relevant"] for row in self.judgments)
        self.assertEqual(self.summary["reviewed"], 695)
        self.assertEqual(self.summary["pending"], 0)
        self.assertEqual(self.summary["relevance_counts"], {"2": relevance[2], "1": relevance[1], "0": relevance[0], "uncertain": relevance["uncertain"]})
        self.assertEqual(self.summary["document_relevance_counts"], {"yes": document["yes"], "no": document["no"], "uncertain": document["uncertain"]})
        self.assertEqual(self.summary["reviewer_counts"], {"Ananthu": 695})

    def test_machine_traces_remain_separate_from_human_labels(self) -> None:
        trace_keys = {"dense_rank", "dense_score", "lexical_rank", "lexical_score", "hybrid_rank", "hybrid_score", "rerank_rank", "rerank_score"}
        self.assertEqual(len(self.traces), 695)
        self.assertTrue(all(trace_keys.isdisjoint(row) for row in self.judgments))
        self.assertTrue(any(any(row.get(key) is not None for key in trace_keys) for row in self.traces))

    def test_required_edge_cases_are_preserved(self) -> None:
        q024 = [row for row in self.judgments if row["query_id"] == "eval-q024"]
        q028 = [row for row in self.judgments if row["query_id"] == "eval-q028"]
        self.assertEqual(sum(1 for row in q024 if row["human_relevance"] == 2), 0)
        self.assertEqual(sum(1 for row in q028 if row["human_relevance"] == 2), 0)
        q030_candidate_17 = next(row for row in self.judgments if row["query_id"] == "eval-q030" and row["blinded_order"] == 17)
        self.assertEqual(q030_candidate_17["human_relevance"], 2)
        self.assertEqual(q030_candidate_17["document_relevant"], "no")


if __name__ == "__main__":
    unittest.main()
