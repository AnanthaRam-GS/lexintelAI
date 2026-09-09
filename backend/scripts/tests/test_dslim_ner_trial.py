import json
import tempfile
import unittest
from pathlib import Path

from backend.scripts import run_dslim_ner_trial as trial


REPO_ROOT = Path(__file__).resolve().parents[3]


class DslimNERTrialTests(unittest.TestCase):
    def test_candidate_model_id_and_primary_threshold(self) -> None:
        self.assertEqual(trial.MODEL_ID, "dslim/bert-base-NER")
        self.assertEqual(trial.PRIMARY_THRESHOLD, 0.70)

    def test_raw_label_mapping_is_conservative(self) -> None:
        self.assertEqual(trial.canonical_label_for("B-PER"), "PERSON")
        self.assertEqual(trial.canonical_label_for("B-ORG"), "ORGANIZATION")
        self.assertEqual(trial.canonical_label_for("I-LOC"), "LOCATION")
        self.assertIsNone(trial.canonical_label_for("PROVISION"))
        self.assertIsNone(trial.canonical_label_for("WITNESS"))
        self.assertIsNone(trial.canonical_label_for("MISC"))

    def test_model_offsets_are_preserved(self) -> None:
        text = "Ramesh Kumar filed in Bengaluru."
        raw = [{"text": "Ramesh Kumar", "start_char": 0, "end_char": 12, "raw_label": "PER", "confidence": 0.91}]
        entities, unmapped = trial.raw_to_canonical_entities("ner-fixture", text, raw)
        self.assertEqual(unmapped, [])
        self.assertEqual((entities[0].text, entities[0].start_char, entities[0].end_char, entities[0].entity_type), ("Ramesh Kumar", 0, 12, "PERSON"))

    def test_unmapped_labels_are_reported(self) -> None:
        text = "criminal intimidation"
        raw = [{"text": text, "start_char": 0, "end_char": len(text), "raw_label": "MISC", "confidence": 0.99}]
        entities, unmapped = trial.raw_to_canonical_entities("ner-fixture", text, raw)
        self.assertEqual(entities, [])
        self.assertEqual(unmapped[0]["normalized_raw_label"], "MISC")

    def test_result_schema_and_exact_metric_comparison_with_fixture(self) -> None:
        raw_payload = fixture_raw_payload()
        result = trial.evaluate_from_raw(raw_payload, {"model_id": trial.MODEL_ID, "id2label": {"0": "O", "1": "B-PER", "2": "B-ORG", "3": "B-LOC", "4": "B-MISC"}}, trial.PRIMARY_THRESHOLD)["trial"]
        self.assertEqual(result["candidate"], trial.MODEL_ID)
        self.assertEqual(result["gold_contract"]["gold_entities"], 89)
        self.assertIn("D0_deterministic", result["systems"])
        self.assertIn("L2_learned", result["systems"])
        self.assertIn("H2_hybrid", result["systems"])
        self.assertEqual(result["primary_threshold"], 0.70)

    def test_protected_type_preservation_and_retrieval_freeze(self) -> None:
        raw_payload = fixture_raw_payload()
        result = trial.evaluate_from_raw(raw_payload, {"model_id": trial.MODEL_ID}, trial.PRIMARY_THRESHOLD)["trial"]
        self.assertEqual(result["protected_type_regression_check"]["regression_count"], 0)
        selected = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        decision = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_tuning_decision.json").read_text(encoding="utf-8"))
        t1 = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_trial.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["candidate_depth"], 20)
        self.assertFalse(decision["frozen_benchmark_rerun_required"])
        self.assertEqual(t1["candidate"], "evolawyer/inlegalbert-sc-ner-silver")

    def test_learned_person_organization_location_merge_and_zero_entity_handling(self) -> None:
        result = trial.evaluate_from_raw(fixture_raw_payload(), {"model_id": trial.MODEL_ID}, trial.PRIMARY_THRESHOLD)["trial"]
        target = result["target_gap_analysis"]["H2_hybrid"]
        self.assertGreaterEqual(target["PERSON"]["true_positive"], 1)
        self.assertGreaterEqual(target["ORGANIZATION"]["true_positive"], 1)
        self.assertGreaterEqual(target["LOCATION"]["true_positive"], 1)
        self.assertEqual(result["zero_entity_guardrails"][0]["l2_false_positive_count"], 0)
        self.assertEqual(result["zero_entity_guardrails"][1]["h2_false_positive_count"], 0)

    def test_raw_prediction_schema_can_be_written_as_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "raw.json"
            path.write_text(json.dumps(fixture_raw_payload(), indent=2), encoding="utf-8")
            parsed = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["candidate"], trial.MODEL_ID)
        self.assertEqual(len(parsed["examples"]), 36)

    def test_gold_and_baseline_immutability_contracts(self) -> None:
        gold = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_gold_template.json").read_text(encoding="utf-8"))
        baseline = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_deterministic_baseline.json").read_text(encoding="utf-8"))
        self.assertEqual(len(gold["examples"]), 36)
        self.assertEqual(sum(len(item["gold_entities"]) for item in gold["examples"]), 89)
        self.assertEqual(baseline["prediction_count"], 76)
        self.assertEqual(baseline["global_exact"]["f1"], 0.787879)


def fixture_raw_payload() -> dict:
    gold = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_gold_template.json").read_text(encoding="utf-8"))
    examples = []
    for example in gold["examples"]:
        raw = []
        if example["example_id"] == "ner-q005":
            raw.append(raw_for(example["text"], "Ramesh Kumar", "PER", 0.95))
        if example["example_id"] == "ner-q010":
            raw.append(raw_for(example["text"], "Bengaluru", "LOC", 0.94))
        if example["example_id"] == "ner-q016":
            raw.append(raw_for(example["text"], "Alpha Traders", "ORG", 0.93))
        examples.append({"example_id": example["example_id"], "text": example["text"], "inference_ms": 1.0, "raw_predictions": [item for item in raw if item]})
    return {"schema_version": trial.NER_SCHEMA_VERSION, "candidate": trial.MODEL_ID, "model_load_time_ms": 10.0, "examples": examples}


def raw_for(text: str, needle: str, raw_label: str, confidence: float) -> dict | None:
    start = text.find(needle)
    if start < 0:
        return None
    return {
        "example_id": "fixture",
        "text": needle,
        "start_char": start,
        "end_char": start + len(needle),
        "raw_label": raw_label,
        "confidence": confidence,
    }


if __name__ == "__main__":
    unittest.main()
