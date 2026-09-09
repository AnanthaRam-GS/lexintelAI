import hashlib
import json
import unittest
from pathlib import Path

from backend.scripts.evaluate_legal_section_baseline import (
    EXPECTED_CATALOG_SHA256,
    EXPECTED_PREDICTOR_SHA256,
    aggregate,
    per_query_metrics,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_SHA256 = "b4ac7034d534eb13dc19d512fd0b376730b860754fe4a58e71dab41f9322ae8e"
GOLD_SUMMARY_SHA256 = "53d8ad35629ee57fc5cb20b9decf682fd8ecd08ab39707e861ef0b8cdc93feee"


class LegalSectionBaselineEvaluationTests(unittest.TestCase):
    def test_metric_correctness_for_multilabel_query(self) -> None:
        predictions = [
            {"statute": "IPC", "normalized_section": "302"},
            {"statute": "IPC", "normalized_section": "304"},
            {"statute": "CrPC", "normalized_section": "439"},
        ]
        gold = [
            {"statute": "IPC", "section": "302", "normalized_section": "302", "relevance": "primary"},
            {"statute": "CrPC", "section": "439", "normalized_section": "439", "relevance": "relevant"},
            {"statute": "SC/ST Act", "section": "18", "normalized_section": "18", "relevance": "uncertain"},
        ]
        metrics = per_query_metrics(predictions, gold)
        self.assertEqual(metrics["precision_at_1"], 1.0)
        self.assertEqual(metrics["precision_at_3"], 2 / 3)
        self.assertEqual(metrics["recall_at_3"], 1.0)
        self.assertEqual(metrics["reciprocal_rank"], 1.0)
        self.assertGreater(metrics["ndcg_at_5"], 0.9)

    def test_uncertain_and_zero_positive_handling(self) -> None:
        uncertain_only = per_query_metrics(
            [{"statute": "SC/ST Act", "normalized_section": "18"}],
            [{"statute": "SC/ST Act", "section": "18", "normalized_section": "18", "relevance": "uncertain"}],
        )
        self.assertEqual(uncertain_only["precision_at_1"], 0.0)
        self.assertIsNone(uncertain_only["recall_at_1"])
        self.assertIsNone(uncertain_only["ndcg_at_5"])

    def test_aggregate_metrics_skip_zero_positive_recall_denominators(self) -> None:
        rows = [
            {"metrics": {"precision_at_1": 1.0, "precision_at_3": 1 / 3, "precision_at_5": 0.2, "recall_at_1": 1.0, "recall_at_3": 1.0, "recall_at_5": 1.0, "reciprocal_rank": 1.0, "ndcg_at_5": 1.0, "hit_at_1": 1.0, "hit_at_3": 1.0, "hit_at_5": 1.0}},
            {"metrics": {"precision_at_1": 0.0, "precision_at_3": 0.0, "precision_at_5": 0.0, "recall_at_1": None, "recall_at_3": None, "recall_at_5": None, "reciprocal_rank": 0.0, "ndcg_at_5": None, "hit_at_1": 0.0, "hit_at_3": 0.0, "hit_at_5": 0.0}},
        ]
        metrics = aggregate(rows)
        self.assertEqual(metrics["recall_at_5"], 1.0)
        self.assertEqual(metrics["precision_at_1"], 0.5)

    def test_baseline_result_schema_and_counts(self) -> None:
        baseline = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_baseline_eval.json").read_text(encoding="utf-8")
        )
        self.assertEqual(baseline["schema_version"], "legalai-section-baseline-eval-v1")
        self.assertEqual(baseline["dataset"]["examples"], 36)
        self.assertEqual(baseline["dataset"]["positive_gold"], 60)
        self.assertEqual(baseline["dataset"]["uncertain_gold"], 1)
        self.assertEqual(baseline["dataset"]["zero_positive_examples"], ["sec-q026", "sec-q027", "sec-q035"])
        self.assertLessEqual(baseline["dataset"]["max_top_k"], 5)
        self.assertEqual(baseline["decision"], "DETERMINISTIC BASELINE USEFUL BUT LEARNED MULTI-LABEL MODEL JUSTIFIED")

    def test_per_example_schema_and_guardrails(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_baseline_per_example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["schema_version"], "legalai-section-baseline-per-example-v1")
        self.assertEqual(len(payload["items"]), 36)
        by_id = {item["example_id"]: item for item in payload["items"]}
        self.assertEqual(by_id["sec-q026"]["predictions"], [])
        self.assertEqual(by_id["sec-q027"]["predictions"], [])
        self.assertEqual(by_id["sec-q035"]["predictions"], [])
        self.assertIn(["IPC", "302"], by_id["sec-q001"]["diagnostics"]["explicit_section_status"]["present"])
        self.assertTrue(by_id["sec-q024"]["subsets"]["mixed_transition"])
        self.assertTrue(all(row["diagnostics"]["top_k"] <= 5 for row in payload["items"]))

    def test_per_statute_and_error_taxonomy(self) -> None:
        baseline = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_baseline_eval.json").read_text(encoding="utf-8")
        )
        expected_statutes = {"IPC", "CrPC", "BNS", "BNSS", "NDPS Act", "POCSO Act", "SC/ST Act"}
        self.assertEqual(set(baseline["per_statute_results"]), expected_statutes)
        self.assertEqual(baseline["per_statute_results"]["NDPS Act"]["recall_at_5"], 1.0)
        self.assertIn("MISSING_GOLD_SECTION", baseline["error_taxonomy"])
        self.assertIn("OVERPREDICTION", baseline["error_taxonomy"])

    def test_raw_predictions_schema(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "data/structured/manifests/legal_section_baseline_predictions.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(payload["schema_version"], "legalai-section-baseline-predictions-v1")
        self.assertEqual(len(payload["items"]), 36)
        for row in payload["items"]:
            self.assertIn("explicit_sections", row)
            self.assertIn("predicted_sections", row)
            self.assertTrue(all("score" in item and "rank" in item for item in row["predicted_sections"]))

    def test_frozen_input_hashes_and_freezes(self) -> None:
        self.assertEqual(
            hashlib.sha256((REPO_ROOT / "backend/app/services/legal_section_prediction.py").read_bytes()).hexdigest(),
            EXPECTED_PREDICTOR_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((REPO_ROOT / "data/structured/manifests/legal_section_catalog.json").read_bytes()).hexdigest(),
            EXPECTED_CATALOG_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((REPO_ROOT / "data/structured/manifests/legal_section_eval.json").read_bytes()).hexdigest(),
            EVAL_SHA256,
        )
        self.assertEqual(
            hashlib.sha256((REPO_ROOT / "data/structured/manifests/legal_section_gold_summary.json").read_bytes()).hexdigest(),
            GOLD_SUMMARY_SHA256,
        )


if __name__ == "__main__":
    unittest.main()
