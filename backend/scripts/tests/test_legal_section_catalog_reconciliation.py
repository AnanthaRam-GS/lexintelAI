import hashlib
import json
import unittest
from pathlib import Path

from backend.scripts.validate_section_catalog_coverage import (
    APPROVED_HUMAN_REVIEW_ADDITIONS,
    BASELINE_CATALOG_KEYS,
    CORRECTED_REVIEW_TOTALS,
    EXPECTED_CATALOG_COUNT,
    coverage_summary,
    duplicate_normalized_keys,
    load_catalog,
    normalize_key,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PREDICTOR_SHA256 = "6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c"


class LegalSectionCatalogReconciliationTests(unittest.TestCase):
    def test_catalog_count_and_authorized_additions(self) -> None:
        entries = load_catalog()
        keys = {normalize_key((entry["statute"], entry["section"])) for entry in entries}
        baseline = {normalize_key(key) for key in BASELINE_CATALOG_KEYS}
        approved = {normalize_key(key) for key in APPROVED_HUMAN_REVIEW_ADDITIONS}

        self.assertEqual(len(entries), EXPECTED_CATALOG_COUNT)
        self.assertEqual(len(APPROVED_HUMAN_REVIEW_ADDITIONS), 18)
        self.assertEqual(keys - baseline, approved)
        self.assertEqual(approved - keys, set())

    def test_subsection_notation_is_preserved(self) -> None:
        literal_sections = {(entry["statute"], entry["section"]) for entry in load_catalog()}
        for key in [
            ("NDPS Act", "36A(4)"),
            ("CrPC", "154(3)"),
            ("BNSS", "173(4)"),
            ("BNSS", "187(3)"),
            ("SC/ST Act", "3(1)(r)"),
            ("SC/ST Act", "3(1)(s)"),
        ]:
            self.assertIn(key, literal_sections)

    def test_no_duplicate_or_unauthorized_normalized_keys(self) -> None:
        summary = coverage_summary()
        self.assertTrue(summary["valid"])
        self.assertEqual(summary["missing"], [])
        self.assertEqual(summary["duplicates"], {})
        self.assertEqual(summary["normalization_conflicts"], 0)
        self.assertEqual(summary["unauthorized_additions"], [])
        self.assertEqual(summary["additions_relative_to_baseline"], 18)

    def test_duplicate_helper_detects_normalized_conflicts(self) -> None:
        duplicates = duplicate_normalized_keys([("CrPC", "154(3)"), (" crpc ", "154 (3)")])
        self.assertEqual(duplicates, {("crpc", "154(3)"): 2})

    def test_eval_manifest_remains_pending_and_unmaterialized(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(payload["examples"]), 36)
        self.assertEqual({item["review_status"] for item in payload["examples"]}, {"pending"})
        self.assertEqual(sum(1 for item in payload["examples"] if item["review_status"] == "reviewed"), 0)
        self.assertTrue(all(item["gold_sections"] == [] for item in payload["examples"]))

    def test_predictor_source_is_unchanged(self) -> None:
        source = (REPO_ROOT / "backend/app/services/legal_section_prediction.py").read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), PREDICTOR_SHA256)

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

    def test_corrected_review_totals_are_recorded(self) -> None:
        self.assertEqual(CORRECTED_REVIEW_TOTALS["examples"], 36)
        self.assertEqual(CORRECTED_REVIEW_TOTALS["primary"], 36)
        self.assertEqual(CORRECTED_REVIEW_TOTALS["relevant"], 24)
        self.assertEqual(CORRECTED_REVIEW_TOTALS["uncertain"], 1)
        self.assertEqual(CORRECTED_REVIEW_TOTALS["positive_primary_relevant"], 60)
        self.assertEqual(CORRECTED_REVIEW_TOTALS["total_annotated_including_uncertain"], 61)
        self.assertEqual(CORRECTED_REVIEW_TOTALS["zero_positive_examples"], ["sec-q026", "sec-q027", "sec-q035"])


if __name__ == "__main__":
    unittest.main()
