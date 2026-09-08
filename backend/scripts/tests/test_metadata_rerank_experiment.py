import unittest

from backend.scripts import analyze_metadata_rerank_experiment as experiment


class MetadataRerankExperimentTests(unittest.TestCase):
    def test_dev_only_safeguard_rejects_eval_queries(self) -> None:
        with self.assertRaises(ValueError):
            experiment.validate_dev_scope([{"query_id": "eval-q001", "development_version": "legalai-retrieval-eval-v1"}], [])

    def test_metadata_prior_is_bounded_and_penalizes_mismatch(self) -> None:
        weights = {"court_match": 0.5, "posture_match": 0.5}
        self.assertEqual(experiment.metadata_prior({"court_match": "match", "posture_match": "match"}, weights), 0.2)
        self.assertLess(experiment.metadata_prior({"court_match": "mismatch"}, {"court_match": 0.1}), 0)

    def test_near_tie_adjustment_changes_only_close_candidates(self) -> None:
        queries = [{"query_id": "dev-q001", "query_text": "Supreme Court criminal appeal discussing murder conviction", "development_version": "legalai-retrieval-dev-v1"}]
        traces = [
            {"query_id": "dev-q001", "chunk_id": "a", "rerank_rank": 1, "rerank_score": 1.0},
            {"query_id": "dev-q001", "chunk_id": "b", "rerank_rank": 2, "rerank_score": 0.95},
            {"query_id": "dev-q001", "chunk_id": "c", "rerank_rank": 3, "rerank_score": 0.1},
        ]
        judgments = [
            {"query_id": "dev-q001", "chunk_id": "a", "court": {"court_name": "Delhi High Court", "court_level": "high_court"}, "case_title": "Civil Petition", "decision_date": "", "effective_offence_family": "other", "effective_legal_regime": "unknown", "bounded_chunk_preview": ""},
            {"query_id": "dev-q001", "chunk_id": "b", "court": {"court_name": "Supreme Court of India", "court_level": "supreme_court"}, "case_title": "Criminal Appeal", "decision_date": "", "effective_offence_family": "homicide", "effective_legal_regime": "unknown", "bounded_chunk_preview": ""},
            {"query_id": "dev-q001", "chunk_id": "c", "court": {"court_name": "Supreme Court of India", "court_level": "supreme_court"}, "case_title": "Criminal Appeal", "decision_date": "", "effective_offence_family": "homicide", "effective_legal_regime": "unknown", "bounded_chunk_preview": ""},
        ]
        adjusted, diagnostics = experiment.adjusted_traces(queries, traces, judgments, "M2")
        ranks = {row["chunk_id"]: row["rerank_rank"] for row in adjusted}
        self.assertEqual(ranks["b"], 1)
        self.assertEqual(ranks["c"], 3)
        self.assertTrue(diagnostics["ordering_changes"]["dev-q001"]["top5_order_changed"])

    def test_stable_ties_are_deterministic(self) -> None:
        queries = [{"query_id": "dev-q001", "query_text": "criminal appeal", "development_version": "legalai-retrieval-dev-v1"}]
        traces = [
            {"query_id": "dev-q001", "chunk_id": "b", "rerank_rank": 1, "rerank_score": 1.0},
            {"query_id": "dev-q001", "chunk_id": "a", "rerank_rank": 2, "rerank_score": 1.0},
        ]
        judgments = [
            {"query_id": "dev-q001", "chunk_id": "b", "court": {}, "case_title": "", "decision_date": "", "effective_offence_family": "", "effective_legal_regime": "", "bounded_chunk_preview": ""},
            {"query_id": "dev-q001", "chunk_id": "a", "court": {}, "case_title": "", "decision_date": "", "effective_offence_family": "", "effective_legal_regime": "", "bounded_chunk_preview": ""},
        ]
        first, _ = experiment.adjusted_traces(queries, traces, judgments, "M1")
        second, _ = experiment.adjusted_traces(queries, traces, judgments, "M1")
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
