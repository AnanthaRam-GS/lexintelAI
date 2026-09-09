import hashlib
import json
import unittest
from pathlib import Path

from backend.scripts.evaluate_legal_section_bge_reranker_trial import (
    CATALOG_PATH,
    D0_PATH,
    EVAL_PATH,
    EXPECTED_CATALOG_SHA256,
    EXPECTED_D0_SHA256,
    EXPECTED_GOLD_SHA256,
    EXPECTED_NER_FREEZE_SHA256,
    EXPECTED_PREDICTOR_SHA256,
    EXPECTED_RETRIEVAL_FREEZE_SHA256,
    EXPECTED_T1_EVAL_SHA256,
    MAX_LENGTH,
    MODEL_ID,
    NER_FREEZE_PATH,
    PREDICTOR_PATH,
    RETRIEVAL_FREEZE_PATH,
    T1_EVAL_PATH,
    decision,
    model_snapshot_path,
    rank_cross_encoder_candidates,
    rank_protected_hybrid_candidates,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


class LegalSectionBgeRerankerTrialTests(unittest.TestCase):
    def load_payload(self) -> dict:
        return json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_bge_reranker_trial_eval.json").read_text(encoding="utf-8")
        )

    def test_trial_model_metadata_and_local_snapshot(self) -> None:
        payload = self.load_payload()
        self.assertEqual(payload["model"]["model_id"], MODEL_ID)
        self.assertEqual(payload["model"]["revision"], "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e")
        self.assertEqual(payload["model"]["architecture"], "XLMRobertaForSequenceClassification")
        self.assertEqual(payload["model"]["tokenizer"], "XLMRobertaTokenizer")
        self.assertEqual(payload["model"]["max_sequence_length"], MAX_LENGTH)
        self.assertTrue(payload["model"]["local_only_loading"])
        self.assertEqual(model_snapshot_path().name, payload["model"]["revision"])

    def test_trial_design_preserves_query_representation_and_bounded_universe(self) -> None:
        payload = self.load_payload()
        self.assertEqual(payload["trial_design"]["query_representation"], "Q0_original_query_only")
        self.assertEqual(payload["trial_design"]["section_representation"], "0.7C catalog-fields-only semantic text")
        self.assertEqual(payload["trial_design"]["pair_construction"], "(original_query_text, section_semantic_text)")
        self.assertEqual(payload["trial_design"]["candidate_generation"], "frozen deterministic predictor output only")
        self.assertEqual(payload["trial_design"]["candidate_expansion_count"], 0)
        self.assertEqual(payload["trial_design"]["fusion_search_count"], 0)
        self.assertLessEqual(payload["dataset"]["max_top_k"], 5)

    def test_x1_raw_score_ordering_and_deterministic_ties(self) -> None:
        candidates = [
            {"statute": "IPC", "section": "302", "normalized_section": "302", "score": 0.9, "rank": 1},
            {"statute": "IPC", "section": "304", "normalized_section": "304", "score": 0.8, "rank": 2},
            {"statute": "BNS", "section": "103", "normalized_section": "103", "score": 0.7, "rank": 3},
        ]
        scores = {("IPC", "302"): 1.0, ("IPC", "304"): 3.0, ("BNS", "103"): 3.0}
        ranked = rank_cross_encoder_candidates(candidates, scores)
        self.assertEqual([(item["statute"], item["section"]) for item in ranked], [("IPC", "304"), ("BNS", "103"), ("IPC", "302")])
        self.assertEqual({(item["statute"], item["section"]) for item in ranked}, {("IPC", "302"), ("IPC", "304"), ("BNS", "103")})

    def test_hx1_protects_explicit_sections_without_expansion(self) -> None:
        x1 = [
            {"statute": "IPC", "section": "304", "normalized_section": "304", "rank": 1, "deterministic_rank": 2, "cross_encoder_score": 4.0},
            {"statute": "IPC", "section": "302", "normalized_section": "302", "rank": 2, "deterministic_rank": 1, "cross_encoder_score": 1.0},
        ]
        hx1 = rank_protected_hybrid_candidates([], x1, {("IPC", "302")})
        self.assertEqual(hx1[0]["section"], "302")
        self.assertTrue(hx1[0]["explicit_protected"])
        self.assertEqual({(item["statute"], item["section"]) for item in hx1}, {("IPC", "302"), ("IPC", "304")})

    def test_metrics_guardrails_and_decisions(self) -> None:
        payload = self.load_payload()
        self.assertGreater(payload["metrics"]["hx1"]["precision_at_1"], payload["metrics"]["d0"]["precision_at_1"])
        self.assertGreater(payload["metrics"]["hx1"]["mrr"], payload["metrics"]["d0"]["mrr"])
        self.assertGreater(payload["metrics"]["hx1"]["ndcg_at_5"], payload["metrics"]["d0"]["ndcg_at_5"])
        self.assertGreater(payload["metrics"]["hx1"]["precision_at_1"], payload["metrics"]["t1_s1"]["precision_at_1"])
        self.assertEqual(payload["guardrail_metrics"]["hx1"]["primary_recall_at_5"], payload["guardrail_metrics"]["d0"]["primary_recall_at_5"])
        self.assertEqual(payload["guardrail_metrics"]["hx1"]["explicit_recall_at_5"], 1.0)
        self.assertEqual(payload["guardrail_metrics"]["hx1"]["zero_positive_false_positive_rate"], 0.0)
        self.assertEqual(payload["candidate_decision"], "BGE CROSS-ENCODER ACCEPTED FOR HYBRID SECTION RANKING")
        self.assertEqual(payload["leading_signal_decision"], "CROSS-ENCODER IS LEADING SECTION RANKING SIGNAL")
        self.assertEqual(
            decision(payload["metrics"]["d0"], payload["metrics"]["t1_s1"], payload["metrics"]["hx1"], payload["guardrail_metrics"]),
            "BGE CROSS-ENCODER ACCEPTED FOR HYBRID SECTION RANKING",
        )

    def test_zero_positive_and_explicit_audits(self) -> None:
        payload = self.load_payload()
        self.assertEqual(payload["zero_positive_guardrails"]["false_positive_rate"], 0.0)
        for row in payload["zero_positive_guardrails"]["examples"]:
            self.assertEqual(row["d0_count"], 0)
            self.assertEqual(row["t1_s1_count"], 0)
            self.assertEqual(row["x1_count"], 0)
            self.assertEqual(row["hx1_count"], 0)
        self.assertTrue(all(row["hx1_rank"] is not None for row in payload["explicit_section_audit"]))

    def test_rank_movement_score_analysis_and_schema(self) -> None:
        payload = self.load_payload()
        self.assertEqual(payload["primary_rank_movement"]["hx1_vs_d0"]["moved_up"], 14)
        self.assertEqual(payload["primary_rank_movement"]["hx1_vs_t1_s1"]["moved_up"], 4)
        self.assertGreater(
            payload["score_diagnostics"]["gold_positive_candidate_pairs"]["mean"],
            payload["score_diagnostics"]["non_gold_candidate_pairs"]["mean"],
        )
        self.assertEqual(payload["score_diagnostics"]["pairwise_discrimination"]["fraction"], 0.864583)
        self.assertEqual(payload["dataset"]["examples"], 36)
        self.assertEqual(payload["dataset"]["positive_gold"], 60)
        self.assertEqual(payload["dataset"]["uncertain"], 1)
        self.assertEqual(payload["dataset"]["zero_positive"], 3)

    def test_frozen_assets_are_unchanged(self) -> None:
        expected = {
            PREDICTOR_PATH: EXPECTED_PREDICTOR_SHA256,
            CATALOG_PATH: EXPECTED_CATALOG_SHA256,
            EVAL_PATH: EXPECTED_GOLD_SHA256,
            D0_PATH: EXPECTED_D0_SHA256,
            T1_EVAL_PATH: EXPECTED_T1_EVAL_SHA256,
            RETRIEVAL_FREEZE_PATH: EXPECTED_RETRIEVAL_FREEZE_SHA256,
            NER_FREEZE_PATH: EXPECTED_NER_FREEZE_SHA256,
        }
        for path, digest in expected.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
