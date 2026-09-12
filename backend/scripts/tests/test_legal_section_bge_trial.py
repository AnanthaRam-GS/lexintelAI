import hashlib
import json
import unittest
from pathlib import Path

from backend.scripts.evaluate_legal_section_bge_trial import (
    EXPECTED_CATALOG_SHA256,
    EXPECTED_D0_SHA256,
    EXPECTED_GOLD_SHA256,
    EXPECTED_PREDICTOR_SHA256,
    MODEL_ID,
    RRF_K,
    decide,
    rank_hybrid_rrf_candidates,
    rank_semantic_candidates,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class LegalSectionBgeTrialTests(unittest.TestCase):
    def test_trial_model_and_metadata(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["model"]["model_id"], MODEL_ID)
        self.assertEqual(payload["model"]["embedding_dimension"], 1024)
        self.assertEqual(payload["model"]["device"], "cpu")
        self.assertEqual(payload["trial_design"]["query_representation"], "Q0_original_query_only")
        self.assertEqual(payload["trial_design"]["fusion_strategy"], "reciprocal_rank_fusion")
        self.assertEqual(payload["trial_design"]["rrf_k"], RRF_K)
        self.assertEqual(payload["trial_design"]["candidate_expansion_count"], 0)
        self.assertLessEqual(payload["dataset"]["max_top_k"], 5)

    def test_semantic_ordering_is_bounded_to_d0_candidates(self) -> None:
        candidates = [
            {"statute": "IPC", "section": "302", "normalized_section": "302", "score": 0.9, "rank": 1},
            {"statute": "IPC", "section": "304", "normalized_section": "304", "score": 0.8, "rank": 2},
        ]
        ranked = rank_semantic_candidates(candidates, {("IPC", "302"): 0.1, ("IPC", "304"): 0.9})
        self.assertEqual([(item["statute"], item["section"]) for item in ranked], [("IPC", "304"), ("IPC", "302")])
        self.assertEqual({(item["statute"], item["section"]) for item in ranked}, {("IPC", "302"), ("IPC", "304")})

    def test_hybrid_rrf_is_deterministic_and_protects_explicit_sections(self) -> None:
        candidates = [
            {"statute": "IPC", "section": "302", "normalized_section": "302", "score": 0.9, "rank": 1},
            {"statute": "IPC", "section": "304", "normalized_section": "304", "score": 0.8, "rank": 2},
        ]
        ranked = rank_hybrid_rrf_candidates(
            candidates,
            {("IPC", "302"): 0.1, ("IPC", "304"): 0.9},
            {("IPC", "302")},
        )
        self.assertEqual(ranked[0]["section"], "302")
        self.assertTrue(ranked[0]["explicit_protected"])
        self.assertTrue(all(item["ranking_source"] == "bge_m3_rrf_hybrid" for item in ranked))

    def test_zero_positive_guardrail_preserved(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["zero_positive_guardrails"]["false_positive_rate"], 0.0)
        for row in payload["zero_positive_guardrails"]["examples"]:
            self.assertEqual(row["d0_count"], 0)
            self.assertEqual(row["s1_count"], 0)
            self.assertEqual(row["h1_count"], 0)

    def test_metrics_and_decision_schema(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_eval.json").read_text(encoding="utf-8")
        )
        self.assertGreater(payload["metrics"]["s1"]["precision_at_1"], payload["metrics"]["d0"]["precision_at_1"])
        self.assertEqual(payload["metrics"]["h1"]["precision_at_1"], payload["metrics"]["d0"]["precision_at_1"])
        self.assertEqual(payload["metrics"]["h1"]["recall_at_5"], payload["metrics"]["d0"]["recall_at_5"])
        self.assertEqual(payload["decision"], "INCONCLUSIVE — TRY CROSS-ENCODER RERANKER")
        self.assertEqual(
            decide(payload["metrics"]["d0"], payload["metrics"]["h1"], [{"example_id": "sec-q026", "h1_predictions": []}]),
            "INCONCLUSIVE — TRY CROSS-ENCODER RERANKER",
        )

    def test_rank_movement_and_score_diagnostics(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_bge_trial_eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["primary_rank_movement"]["h1"]["missing"], 2)
        self.assertEqual(payload["primary_rank_movement"]["s1"]["moved_up"], 14)
        self.assertGreater(
            payload["score_diagnostics"]["gold_positive_candidates"]["mean"],
            payload["score_diagnostics"]["non_gold_candidates"]["mean"],
        )

    def test_frozen_artifact_hashes(self) -> None:
        expected = {
            "backend/app/services/legal_section_prediction.py": EXPECTED_PREDICTOR_SHA256,
            "data/structured/manifests/legal_section_catalog.json": EXPECTED_CATALOG_SHA256,
            "data/structured/manifests/legal_section_eval.json": EXPECTED_GOLD_SHA256,
            "data/structured/manifests/legal_section_baseline_eval.json": EXPECTED_D0_SHA256,
        }
        for path, digest in expected.items():
            self.assertEqual(hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
