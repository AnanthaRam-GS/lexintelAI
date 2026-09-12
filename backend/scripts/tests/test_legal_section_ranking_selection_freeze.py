import hashlib
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIR = REPO_ROOT / "data/structured/manifests"
SELECTED_PATH = MANIFEST_DIR / "legal_section_selected_configuration.json"
DECISION_PATH = MANIFEST_DIR / "legal_section_ranking_decision.json"


class LegalSectionRankingSelectionFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.selected = json.loads(SELECTED_PATH.read_text(encoding="utf-8"))
        cls.decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))

    def test_selected_configuration_core_fields(self) -> None:
        self.assertEqual(self.selected["selection_decision"], "SELECT_BGE_CROSS_ENCODER_PROTECTED_HYBRID")
        self.assertEqual(self.selected["ranking"]["selected_model"], "BAAI/bge-reranker-v2-m3")
        self.assertEqual(self.selected["ranking"]["selected_model_revision"], "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")
        self.assertEqual(self.selected["ranking"]["ranking_mode"], "cross_encoder_protected_hybrid")
        self.assertEqual(self.selected["candidate_generation"]["mode"], "deterministic")
        self.assertFalse(self.selected["candidate_generation"]["candidate_expansion"])
        self.assertEqual(self.selected["ranking"]["final_top_k"], 5)
        self.assertFalse(self.selected["ranking"]["training_used"])
        self.assertFalse(self.selected["ranking"]["fine_tuning_used"])

    def test_guardrails_and_fallback_policy(self) -> None:
        guardrails = self.selected["safety_guardrails"]
        self.assertTrue(guardrails["explicit_section_protection"])
        self.assertTrue(guardrails["regime_protection"])
        self.assertTrue(guardrails["zero_positive_guardrail"])
        self.assertTrue(guardrails["bounded_catalog"])
        self.assertFalse(guardrails["candidate_expansion_enabled"])
        self.assertTrue(guardrails["top_k_lte_5"])
        self.assertEqual(self.selected["fallback"]["if_cross_encoder_unavailable"], "deterministic_D0_ranking")
        self.assertFalse(self.selected["fallback"]["automatic_third_party_model_substitution"])
        self.assertEqual(self.selected["runtime_default_policy"]["LEGAL_SECTION_RANKING_MODE"], "deterministic")

    def test_decision_policy_fields(self) -> None:
        self.assertEqual(self.decision["final_decision"], "SELECT_BGE_CROSS_ENCODER_PROTECTED_HYBRID")
        self.assertFalse(self.decision["further_model_search"])
        self.assertFalse(self.decision["fine_tuning_now"])
        self.assertFalse(self.decision["candidate_expansion_now"])
        self.assertEqual(self.decision["future_training_research"], "allowed")

    def test_frozen_metric_evidence(self) -> None:
        evidence = self.selected["comparative_evidence"]
        self.assertEqual(evidence["D0"]["precision_at_1"], 0.5)
        self.assertEqual(evidence["D0"]["mrr"], 0.662037)
        self.assertEqual(evidence["D0"]["ndcg_at_5"], 0.722516)
        self.assertEqual(evidence["T1_S1"]["precision_at_1"], 0.777778)
        self.assertEqual(evidence["T1_S1"]["mrr"], 0.814815)
        self.assertEqual(evidence["T1_S1"]["ndcg_at_5"], 0.821095)
        self.assertEqual(evidence["T1_H1"]["precision_at_1"], 0.5)
        self.assertEqual(evidence["T1_H1"]["mrr"], 0.662037)
        self.assertEqual(evidence["T1_H1"]["ndcg_at_5"], 0.726846)
        self.assertEqual(evidence["T2_HX1"]["precision_at_1"], 0.805556)
        self.assertEqual(evidence["T2_HX1"]["mrr"], 0.833333)
        self.assertEqual(evidence["T2_HX1"]["ndcg_at_5"], 0.831325)
        self.assertEqual(evidence["T2_HX1"]["explicit_recall_at_5"], 1.0)
        self.assertEqual(evidence["T2_HX1"]["zero_positive_false_positive_rate"], 0.0)

    def test_decision_manifest_records_t1_and_t2_outcomes(self) -> None:
        self.assertEqual(self.decision["key_metrics"]["T1_S1"]["decision"], "INCONCLUSIVE — TRY CROSS-ENCODER RERANKER")
        self.assertEqual(
            self.decision["key_metrics"]["T2_HX1"]["candidate_decision"],
            "BGE CROSS-ENCODER ACCEPTED FOR HYBRID SECTION RANKING",
        )
        self.assertEqual(self.decision["key_metrics"]["T2_HX1"]["leading_signal"], "CROSS-ENCODER IS LEADING SECTION RANKING SIGNAL")
        self.assertIn("cannot recover gold sections absent", self.decision["candidate_generation_limitation"])

    def test_frozen_artifact_hashes(self) -> None:
        expected = {
            "backend/app/services/legal_section_prediction.py": self.decision["frozen_artifact_hashes"]["predictor"],
            "data/structured/manifests/legal_section_catalog.json": self.decision["frozen_artifact_hashes"]["catalog"],
            "data/structured/manifests/legal_section_eval.json": self.decision["frozen_artifact_hashes"]["gold"],
            "data/structured/manifests/legal_section_baseline_eval.json": self.decision["frozen_artifact_hashes"]["d0_eval"],
            "data/structured/manifests/legal_section_bge_trial_eval.json": self.decision["frozen_artifact_hashes"]["t1_eval"],
            "data/structured/manifests/legal_section_bge_reranker_trial_eval.json": self.decision["frozen_artifact_hashes"]["t2_eval"],
            "data/structured/manifests/retrieval_selected_configuration.json": self.decision["frozen_artifact_hashes"]["retrieval_freeze"],
            "data/structured/manifests/legal_ner_selected_configuration.json": self.decision["frozen_artifact_hashes"]["ner_freeze"],
        }
        for path, digest in expected.items():
            self.assertEqual(hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
