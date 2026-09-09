import json
import unittest
from pathlib import Path

from backend.app.services.legal_ner import DisabledLegalNERModel
from backend.scripts import evaluate_deterministic_legal_ner as evaluator


REPO_ROOT = Path(__file__).resolve().parents[3]


class LegalNERDeterministicBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.results = evaluator.evaluate()
        cls.baseline = cls.results["baseline"]
        cls.per_examples = cls.results["per_examples"]
        cls.errors = cls.results["errors"]

    def test_evaluates_36_examples_and_89_gold_entities(self) -> None:
        self.assertEqual(self.baseline["example_count"], 36)
        self.assertEqual(self.baseline["gold_entity_count"], 89)
        self.assertEqual(self.baseline["prediction_count"], 76)

    def test_learned_adapter_disabled(self) -> None:
        self.assertFalse(self.baseline["learned_ner_enabled"])
        self.assertEqual(DisabledLegalNERModel().extract("Section 302 IPC"), [])

    def test_exact_span_type_global_counts(self) -> None:
        exact = self.baseline["global_exact"]
        self.assertEqual(exact["true_positive"], 65)
        self.assertEqual(exact["false_positive"], 11)
        self.assertEqual(exact["false_negative"], 24)

    def test_micro_precision_recall_f1(self) -> None:
        exact = self.baseline["global_exact"]
        self.assertEqual(exact["precision"], 0.855263)
        self.assertEqual(exact["recall"], 0.730337)
        self.assertEqual(exact["f1"], 0.787879)

    def test_per_type_metrics_include_all_types(self) -> None:
        self.assertEqual(set(self.baseline["per_type"]), set(evaluator.CANONICAL_ENTITY_TYPES))
        self.assertEqual(self.baseline["per_type"]["STATUTE"]["f1"], 1.0)
        self.assertEqual(self.baseline["per_type"]["SECTION"]["f1"], 1.0)
        self.assertEqual(self.baseline["per_type"]["PERSON"]["false_negative"], 3)
        self.assertEqual(self.baseline["per_type"]["ORGANIZATION"]["false_negative"], 4)

    def test_span_only_metrics_are_separate(self) -> None:
        self.assertEqual(self.baseline["span_only"], {"tp": 65, "fp": 11, "fn": 24, "precision": 0.855263, "recall": 0.730337, "f1": 0.787879})

    def test_zero_entity_examples_have_no_false_positives(self) -> None:
        zero = {item["example_id"]: item for item in self.baseline["zero_entity_examples"]}
        self.assertEqual(set(zero), {"ner-q026", "ner-q036"})
        self.assertEqual(zero["ner-q026"]["false_positive_count"], 0)
        self.assertEqual(zero["ner-q036"]["false_positive_count"], 0)

    def test_no_duplicate_prediction_matching(self) -> None:
        for example in self.per_examples:
            keys = [(item["start_char"], item["end_char"], item["entity_type"]) for item in example["predicted_entities"]]
            self.assertEqual(len(keys), len(set(keys)))

    def test_error_taxonomy(self) -> None:
        self.assertEqual(self.errors["total_errors"], 35)
        self.assertEqual(self.errors["error_type_counts"], {"BOUNDARY_MISMATCH": 16, "MISSING_ENTITY_TYPE": 16, "SPURIOUS_ENTITY": 3})
        self.assertEqual(self.errors["wrong_type_examples"], [])

    def test_stable_deterministic_output(self) -> None:
        self.assertEqual(self.results["baseline"], evaluator.evaluate()["baseline"])

    def test_gold_immutability(self) -> None:
        gold = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_gold_template.json").read_text(encoding="utf-8"))
        source = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_eval.json").read_text(encoding="utf-8"))
        self.assertEqual([(item["example_id"], item["text"]) for item in gold["examples"]], [(item["example_id"], item["text"]) for item in source["examples"]])
        self.assertEqual(sum(len(item["gold_entities"]) for item in gold["examples"]), 89)

    def test_query_analysis_compatibility(self) -> None:
        q001 = next(example for example in self.per_examples if example["example_id"] == "ner-q001")
        self.assertEqual(len(q001["false_positives"]), 0)
        self.assertEqual(len(q001["false_negatives"]), 0)

    def test_retrieval_freeze(self) -> None:
        selected = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        decision = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_tuning_decision.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["candidate_depth"], 20)
        self.assertEqual(selected["final_top_k"], 5)
        self.assertFalse(selected["experimental_features"]["regime_ranking_enabled"])
        self.assertFalse(decision["frozen_benchmark_rerun_required"])


if __name__ == "__main__":
    unittest.main()
