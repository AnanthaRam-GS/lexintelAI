import json
from pathlib import Path
import unittest

from backend.scripts import analyze_regime_retrieval_experiment as experiment


class RegimeRetrievalExperimentTests(unittest.TestCase):
    def test_variant_uses_judgment_regime_metadata(self) -> None:
        queries = [{"query_id": "q1", "query_text": "offence under BNS after 1 July 2024"}]
        traces = [
            {"query_id": "q1", "chunk_id": "old", "rerank_rank": 1, "rerank_score": 1.0},
            {"query_id": "q1", "chunk_id": "new", "rerank_rank": 2, "rerank_score": 0.9},
        ]
        regimes = {("q1", "old"): "ipc_crpc", ("q1", "new"): "bns_bnss"}

        rows = experiment.variant_traces(queries, traces, "R2", regimes)
        rank_by_chunk = {row["chunk_id"]: row["rerank_rank"] for row in rows}

        self.assertEqual(rank_by_chunk["new"], 1)
        self.assertEqual(rank_by_chunk["old"], 2)

    def test_variant_sort_is_stable_for_equal_adjusted_scores(self) -> None:
        queries = [{"query_id": "q1", "query_text": "criminal appeal"}]
        traces = [
            {"query_id": "q1", "chunk_id": "b", "rerank_rank": 1, "rerank_score": 1.0},
            {"query_id": "q1", "chunk_id": "a", "rerank_rank": 2, "rerank_score": 1.0},
        ]
        rows = experiment.variant_traces(queries, traces, "R1", {})
        rank_by_chunk = {row["chunk_id"]: row["rerank_rank"] for row in rows}

        self.assertEqual(rank_by_chunk["b"], 1)
        self.assertEqual(rank_by_chunk["a"], 2)

    def test_script_does_not_reference_frozen_benchmark_artifacts(self) -> None:
        source = Path(experiment.__file__).read_text(encoding="utf-8")
        forbidden = [
            "retrieval_eval_results",
            "retrieval_eval_per_query_metrics",
            "retrieval_eval_judgments",
            "retrieval_eval_pool_traces",
        ]
        self.assertFalse(any(name in source for name in forbidden))

    def test_experiment_artifacts_have_dev_scope_when_present(self) -> None:
        if not experiment.EXPERIMENT_PATH.exists():
            self.skipTest("experiment artifact not generated yet")
        payload = json.loads(experiment.EXPERIMENT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(payload["development_version"], "legalai-retrieval-dev-v1")
        self.assertEqual(set(payload["variants"]), {"R0", "R1", "R2", "R3"})
        self.assertEqual(len(payload["resolver_qa"]), 20)
        self.assertIn(payload["selection_decision"].split(":")[0].split(" — ")[0], {"REGIME VARIANT ACCEPTED", "INCONCLUSIVE"})


if __name__ == "__main__":
    unittest.main()
