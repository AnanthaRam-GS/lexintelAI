"""Tests for the separate retrieval tuning/development set."""

from __future__ import annotations

from collections import Counter
import json
import unittest
from pathlib import Path

from backend.scripts.build_retrieval_dev_set import DEV_POOL_VERSION, DEV_VERSION
from backend.scripts.build_vector_index import load_chunks

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = ROOT / "data/structured/manifests"


class RetrievalDevSetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.queries = json.loads((MANIFEST_DIR / "retrieval_dev_queries.json").read_text(encoding="utf-8"))
        cls.judgments = json.loads((MANIFEST_DIR / "retrieval_dev_judgments.json").read_text(encoding="utf-8"))
        cls.traces = json.loads((MANIFEST_DIR / "retrieval_dev_pool_traces.json").read_text(encoding="utf-8"))
        cls.summary = json.loads((MANIFEST_DIR / "retrieval_dev_summary.json").read_text(encoding="utf-8"))
        cls.benchmark_queries = json.loads((MANIFEST_DIR / "retrieval_eval_queries.json").read_text(encoding="utf-8"))

    def test_query_count_ids_distribution_and_versions(self) -> None:
        self.assertEqual(len(self.queries), 20)
        self.assertEqual([query["query_id"] for query in self.queries], [f"dev-q{index:03d}" for index in range(1, 21)])
        self.assertEqual(Counter(query["query_type"] for query in self.queries), {"legal_regime_transition": 6, "composite_ambiguous": 5, "plain_language_expansion": 4, "metadata_sensitive": 3, "hard_negative": 2})
        self.assertTrue(all(query["development_version"] == DEV_VERSION for query in self.queries))
        self.assertTrue(all(query["prior_benchmark_similarity"] != "near_duplicate" for query in self.queries))

    def test_support_and_no_exact_benchmark_duplicates(self) -> None:
        chunk_ids = {chunk["chunk_id"] for chunk in load_chunks()}
        benchmark_texts = {query["query_text"].strip().lower() for query in self.benchmark_queries}
        self.assertTrue(all(query["query_text"].strip().lower() not in benchmark_texts for query in self.queries))
        self.assertTrue(all(query["supporting_document_ids"] for query in self.queries))
        self.assertTrue(all(query["supporting_chunk_ids"] for query in self.queries))
        self.assertTrue(all(chunk_id in chunk_ids for query in self.queries for chunk_id in query["supporting_chunk_ids"]))

    def test_candidates_are_pending_unique_and_in_trusted_corpus(self) -> None:
        chunk_ids = {chunk["chunk_id"] for chunk in load_chunks()}
        keys = [(row["query_id"], row["chunk_id"]) for row in self.judgments]
        self.assertEqual(len(self.judgments), 474)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(row["human_status"] == "pending" for row in self.judgments))
        self.assertTrue(all(row["human_relevance"] == "uncertain" and row["document_relevant"] == "uncertain" for row in self.judgments))
        self.assertTrue(all(row["chunk_id"] in chunk_ids for row in self.judgments))

    def test_blinding_and_trace_separation(self) -> None:
        rank_keys = {"dense_rank", "dense_score", "lexical_rank", "lexical_score", "hybrid_rank", "hybrid_score", "rerank_rank", "rerank_score"}
        self.assertTrue(all(rank_keys.isdisjoint(row) for row in self.judgments))
        self.assertEqual(len(self.traces), len(self.judgments))
        self.assertTrue(all(row["pooling_version"] == DEV_POOL_VERSION for row in self.traces))
        self.assertTrue(any(any(row.get(key) is not None for key in rank_keys) for row in self.traces))

    def test_every_system_top5_retained_and_workload_bounded(self) -> None:
        for query in self.queries:
            query_rows = [row for row in self.traces if row["query_id"] == query["query_id"]]
            for rank_field in ["dense_rank", "lexical_rank", "hybrid_rank", "rerank_rank"]:
                ranks = {row[rank_field] for row in query_rows if row.get(rank_field) is not None and row[rank_field] <= 5}
                self.assertEqual(ranks, {1, 2, 3, 4, 5})
        self.assertLessEqual(self.summary["workload"]["total_pooled_chunks"], 600)
        self.assertEqual(self.summary["human_labels_assigned"], 0)


if __name__ == "__main__":
    unittest.main()
