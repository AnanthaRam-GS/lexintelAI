import hashlib
import json
import unittest
from pathlib import Path

from backend.scripts.validate_legal_section_gold import EXPECTED_COUNTS, EXPECTED_PREDICTOR_SHA256, validate_gold


REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_SHA256 = "2d2c8fbf4a241d2adc6f67ce827f990976d3309cb59b7add15f6bc26d439dbef"


class LegalSectionGoldLabelsTests(unittest.TestCase):
    def test_gold_validator_accepts_materialized_manifest(self) -> None:
        result = validate_gold()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["examples"], EXPECTED_COUNTS["examples"])
        self.assertEqual(result["reviewed"], EXPECTED_COUNTS["reviewed"])
        self.assertEqual(result["pending"], EXPECTED_COUNTS["pending"])
        self.assertEqual(result["primary"], EXPECTED_COUNTS["primary"])
        self.assertEqual(result["relevant"], EXPECTED_COUNTS["relevant"])
        self.assertEqual(result["uncertain"], EXPECTED_COUNTS["uncertain"])
        self.assertEqual(result["positive"], EXPECTED_COUNTS["positive"])
        self.assertEqual(result["total_annotated"], EXPECTED_COUNTS["total"])
        self.assertEqual(result["zero_positive_ids"], EXPECTED_COUNTS["zero_positive_ids"])

    def test_summary_counts_match_gold_manifest(self) -> None:
        summary = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_gold_summary.json").read_text(encoding="utf-8")
        )
        self.assertEqual(summary["example_count"], 36)
        self.assertEqual(summary["reviewed"], 36)
        self.assertEqual(summary["pending"], 0)
        self.assertEqual(summary["primary_count"], 36)
        self.assertEqual(summary["relevant_count"], 24)
        self.assertEqual(summary["uncertain_count"], 1)
        self.assertEqual(summary["positive_count"], 60)
        self.assertEqual(summary["total_judgment_count"], 61)
        self.assertEqual(summary["zero_positive_example_ids"], ["sec-q026", "sec-q027", "sec-q035"])
        self.assertEqual(summary["reviewer_counts"], {"Ananthu": 36})

    def test_catalog_and_predictor_are_immutable(self) -> None:
        catalog = (REPO_ROOT / "data/structured/manifests/legal_section_catalog.json").read_bytes()
        predictor = (REPO_ROOT / "backend/app/services/legal_section_prediction.py").read_bytes()
        self.assertEqual(hashlib.sha256(catalog).hexdigest(), CATALOG_SHA256)
        self.assertEqual(hashlib.sha256(predictor).hexdigest(), EXPECTED_PREDICTOR_SHA256)

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
