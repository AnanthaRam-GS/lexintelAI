import hashlib
import json
import unittest
from pathlib import Path

from backend.app.schemas.query_analysis import PredictedLegalSection
from backend.app.services.legal_section_hybrid_ranking import (
    LegalSectionRankingConfig,
    MockLegalSectionSemanticRanker,
    build_query_representation,
    build_section_semantic_text,
    compare_against_d0,
    rank_legal_section_candidates,
)
from backend.app.services.legal_section_prediction import DEFAULT_TOP_K, load_section_catalog
from backend.app.services.query_analysis import analyze_legal_query


REPO_ROOT = Path(__file__).resolve().parents[3]
PREDICTOR_SHA256 = "6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c"
CATALOG_SHA256 = "2d2c8fbf4a241d2adc6f67ce827f990976d3309cb59b7add15f6bc26d439dbef"
GOLD_SHA256 = "b4ac7034d534eb13dc19d512fd0b376730b860754fe4a58e71dab41f9322ae8e"
GOLD_SUMMARY_SHA256 = "53d8ad35629ee57fc5cb20b9decf682fd8ecd08ab39707e861ef0b8cdc93feee"
BASELINE_EVAL_SHA256 = "f4346089eb05bd205646fa56218317a049d9d15fbe16e5c8aa20ef34ce0ce2b3"


def candidate(statute: str, section: str, score: float, rank: int, relationship: str = "supplementary") -> PredictedLegalSection:
    return PredictedLegalSection(
        statute=statute,
        section=section,
        normalized_section=section.casefold(),
        score=score,
        rank=rank,
        source="deterministic_baseline",
        confidence="high",
        evidence=["test"],
        prediction_version="legalai-section-prediction-baseline-v1",
        relationship_to_explicit=relationship,
    )


class LegalSectionLearnedRankingFoundationTests(unittest.TestCase):
    def test_stable_section_semantic_text_uses_catalog_fields_only(self) -> None:
        entry = next(item for item in load_section_catalog() if item["statute"] == "IPC" and item["section"] == "302")
        text = build_section_semantic_text(entry)
        self.assertEqual(
            text,
            "IPC Section 302: Murder. Punishment for murder. Family: homicide. Regime: ipc_crpc.",
        )

    def test_query_representations_preserve_original_query_authority(self) -> None:
        analysis = analyze_legal_query("Section 438 CrPC anticipatory bail")
        self.assertEqual(build_query_representation(analysis, "Q0"), analysis.original_query)
        self.assertIn(analysis.original_query, build_query_representation(analysis, "Q1"))
        self.assertIn("Legal regime:", build_query_representation(analysis, "Q2"))

    def test_default_config_is_deterministic_and_training_safe(self) -> None:
        config = LegalSectionRankingConfig()
        config.validate()
        self.assertEqual(config.mode, "deterministic")
        self.assertFalse(config.gold_training_allowed)
        self.assertIsNone(config.semantic_weight)
        self.assertIsNone(config.deterministic_weight)

    def test_invalid_config_rejects_training_and_top_k_expansion(self) -> None:
        with self.assertRaises(ValueError):
            LegalSectionRankingConfig(gold_training_allowed=True).validate()
        with self.assertRaises(ValueError):
            LegalSectionRankingConfig(final_top_k=DEFAULT_TOP_K + 1).validate()
        with self.assertRaises(ValueError):
            LegalSectionRankingConfig(mode="hybrid").validate()

    def test_mock_semantic_scorer_and_result_schema(self) -> None:
        analysis = analyze_legal_query("Section 302 IPC murder")
        candidates = [
            candidate("IPC", "302", 0.9, 1, "supports_explicit"),
            candidate("IPC", "304", 0.8, 2),
        ]
        ranker = MockLegalSectionSemanticRanker({("IPC", "302"): 0.1, ("IPC", "304"): 0.9})
        ranked = rank_legal_section_candidates(
            analysis.original_query,
            analysis,
            candidates,
            semantic_ranker=ranker,
            config=LegalSectionRankingConfig(mode="semantic"),
        )
        self.assertEqual(ranked[0].statute, "IPC")
        self.assertEqual(ranked[0].section, "302")
        self.assertTrue(ranked[0].protected_explicit)
        self.assertEqual(ranked[0].ranking_source, "semantic")
        self.assertIsNotNone(ranked[0].semantic_score)

    def test_deterministic_mode_preserves_existing_order(self) -> None:
        ranked = rank_legal_section_candidates(
            "query",
            analyze_legal_query("query"),
            [candidate("IPC", "304", 0.8, 2), candidate("IPC", "302", 0.9, 1)],
        )
        self.assertEqual([(item.statute, item.section) for item in ranked], [("IPC", "302"), ("IPC", "304")])

    def test_zero_positive_guardrail_can_return_empty(self) -> None:
        self.assertEqual(
            rank_legal_section_candidates("certified copy application", analyze_legal_query("certified copy application"), []),
            [],
        )

    def test_hybrid_mode_uses_predeclared_weights_and_top_k_bound(self) -> None:
        analysis = analyze_legal_query("robbery hurt")
        candidates = [
            candidate("IPC", "394", 0.7, 1),
            candidate("IPC", "392", 0.9, 2),
            candidate("IPC", "323", 0.6, 3),
        ]
        ranker = MockLegalSectionSemanticRanker({("IPC", "323"): 0.99, ("IPC", "394"): 0.1, ("IPC", "392"): 0.2})
        ranked = rank_legal_section_candidates(
            analysis.original_query,
            analysis,
            candidates,
            semantic_ranker=ranker,
            config=LegalSectionRankingConfig(mode="hybrid", semantic_weight=0.5, deterministic_weight=0.5, final_top_k=2),
        )
        self.assertLessEqual(len(ranked), 2)
        self.assertTrue(all(item.rank <= DEFAULT_TOP_K for item in ranked))

    def test_d0_comparator_schema(self) -> None:
        d0 = json.loads((REPO_ROOT / "data/structured/manifests/legal_section_baseline_eval.json").read_text(encoding="utf-8"))
        candidate_eval = json.loads(json.dumps(d0))
        candidate_eval["overall_metrics"]["precision_at_1"] = 0.6
        deltas = compare_against_d0(candidate_eval, d0)
        self.assertEqual(deltas["precision_at_1"], 0.1)
        self.assertIn("ndcg_at_5", deltas)

    def test_feasibility_and_trial_config_are_disabled_templates(self) -> None:
        feasibility = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_learned_ranking_feasibility.json").read_text(
                encoding="utf-8"
            )
        )
        config = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_learned_trial_config.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(feasibility["status"], "foundation_ready_no_learned_trial_run")
        self.assertTrue(feasibility["no_download_performed"])
        self.assertTrue(feasibility["no_learned_effectiveness_run_performed"])
        self.assertEqual(config["mode"], "disabled")
        self.assertIsNone(config["candidate_model"])
        self.assertIsNone(config["semantic_weight"])
        self.assertIsNone(config["deterministic_weight"])
        self.assertFalse(config["gold_training_allowed"])

    def test_frozen_inputs_and_baseline_artifacts_unchanged(self) -> None:
        paths = {
            "backend/app/services/legal_section_prediction.py": PREDICTOR_SHA256,
            "data/structured/manifests/legal_section_catalog.json": CATALOG_SHA256,
            "data/structured/manifests/legal_section_eval.json": GOLD_SHA256,
            "data/structured/manifests/legal_section_gold_summary.json": GOLD_SUMMARY_SHA256,
            "data/structured/manifests/legal_section_baseline_eval.json": BASELINE_EVAL_SHA256,
        }
        for path, expected in paths.items():
            self.assertEqual(hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest(), expected)

    def test_retrieval_and_ner_freezes_remain_unchanged(self) -> None:
        retrieval = json.loads(
            (REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json").read_text(
                encoding="utf-8"
            )
        )
        ner = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_ner_selected_configuration.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(retrieval["candidate_depth"], 20)
        self.assertFalse(retrieval["experimental_features"]["regime_ranking_enabled"])
        self.assertEqual(ner["mode"], "deterministic")
        self.assertIsNone(ner["learned_model"])
        self.assertFalse(ner["hybrid_enabled"])


if __name__ == "__main__":
    unittest.main()
