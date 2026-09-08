import unittest

from backend.scripts import analyze_query_expansion_experiment as experiment


class QueryExpansionExperimentTests(unittest.TestCase):
    def test_dev_only_safeguard_rejects_eval_queries(self) -> None:
        queries = [{"query_id": "eval-q001", "development_version": "legalai-retrieval-eval-v1"}]
        with self.assertRaises(ValueError):
            experiment.validate_dev_scope(queries, [])

    def test_candidate_generation_counts_overlap(self) -> None:
        rankings = {"q1": {"bm25": ["a", "b", "x"], "dense": ["b", "c", "y"]}}
        qrels = {"q1": {"a": 1, "b": 2, "c": 0, "x": 0, "y": 1}}
        result = experiment.candidate_generation(rankings, qrels)["aggregate"]
        self.assertEqual(result["bm25"], 2)
        self.assertEqual(result["dense"], 2)
        self.assertEqual(result["intersection"], 1)
        self.assertEqual(result["union"], 3)

    def test_new_lost_relevant_candidates(self) -> None:
        baseline = {"q1": {"bm25": ["a", "b"], "dense": ["a"], "hybrid": ["a"]}}
        variant = {"q1": {"bm25": ["b", "c"], "dense": ["a", "c"], "hybrid": ["c"]}}
        qrels = {"q1": {"a": 1, "b": 0, "c": 2}}
        result = experiment.new_lost(variant, baseline, qrels)
        self.assertEqual(result["bm25"]["aggregate"], {"new_broad": 1, "lost_broad": 1, "new_grade2": 1, "lost_grade2": 0})
        self.assertEqual(result["hybrid"]["aggregate"], {"new_broad": 1, "lost_broad": 1, "new_grade2": 1, "lost_grade2": 0})


if __name__ == "__main__":
    unittest.main()
