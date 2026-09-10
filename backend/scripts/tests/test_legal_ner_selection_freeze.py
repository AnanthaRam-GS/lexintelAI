import json
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.schemas.legal_ner import NER_SCHEMA_VERSION
from backend.app.services.hybrid_legal_ner import DEFAULT_NER_MODE
from backend.app.services.legal_ner import DisabledLegalNERModel, extract_deterministic_entities


REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTED_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_selected_configuration.json"
DECISION_PATH = REPO_ROOT / "data/structured/manifests/legal_ner_model_decision.json"


class LegalNERSelectionFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.selected = json.loads(SELECTED_PATH.read_text(encoding="utf-8"))
        cls.decision = json.loads(DECISION_PATH.read_text(encoding="utf-8"))

    def test_selected_mode_schema_and_flags(self) -> None:
        self.assertEqual(self.selected["schema_version"], NER_SCHEMA_VERSION)
        self.assertEqual(self.selected["mode"], "deterministic")
        self.assertEqual(self.selected["selected_extractor"], "deterministic_legal_ner")
        self.assertIsNone(self.selected["learned_model"])
        self.assertFalse(self.selected["hybrid_enabled"])
        self.assertFalse(self.selected["learned_ner_enabled"])

    def test_runtime_defaults_remain_deterministic(self) -> None:
        settings = Settings()
        self.assertFalse(settings.legal_ner_enabled)
        self.assertEqual(settings.legal_ner_model, "")
        self.assertEqual(settings.legal_ner_mode, "deterministic")
        self.assertEqual(DEFAULT_NER_MODE, "deterministic")

    def test_d0_metrics_frozen(self) -> None:
        baseline = self.selected["baseline"]
        self.assertEqual(baseline["predictions"], 76)
        self.assertEqual(baseline["true_positive"], 65)
        self.assertEqual(baseline["false_positive"], 11)
        self.assertEqual(baseline["false_negative"], 24)
        self.assertEqual(baseline["precision"], 0.855263)
        self.assertEqual(baseline["recall"], 0.730337)
        self.assertEqual(baseline["f1"], 0.787879)

    def test_candidate_decisions_frozen(self) -> None:
        self.assertEqual(self.selected["experimental_candidates"]["T1"]["decision"], "LEARNED CANDIDATE REJECTED")
        self.assertEqual(self.selected["experimental_candidates"]["T2"]["decision"], "GENERAL NER CANDIDATE REJECTED")
        self.assertEqual(self.selected["candidate_comparison_decision"], "NEITHER CANDIDATE JUSTIFIED")

    def test_final_decision_and_model_shopping_policy(self) -> None:
        self.assertEqual(self.decision["final_decision"], "RETAIN_DETERMINISTIC_NER_PHASE0")
        self.assertFalse(self.decision["further_pretrained_candidate_search"])
        self.assertFalse(self.decision["fine_tuning_now"])
        self.assertEqual(self.decision["future_learned_ner_research"], "allowed")

    def test_default_path_loads_no_learned_model_or_hybrid_merge(self) -> None:
        with patch("backend.app.services.hybrid_legal_ner.merge_hybrid_entities") as merge_mock:
            result = extract_deterministic_entities("Section 302 IPC bail before the Sessions Court")
        merge_mock.assert_not_called()
        self.assertEqual(result.extractor, "deterministic_legal_ner")
        self.assertIsNone(result.model_name)
        self.assertEqual(DisabledLegalNERModel().extract("Ramesh Kumar"), [])

    def test_gold_and_artifact_immutability_contracts(self) -> None:
        gold = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_gold_template.json").read_text(encoding="utf-8"))
        source = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_eval.json").read_text(encoding="utf-8"))
        d0 = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_deterministic_baseline.json").read_text(encoding="utf-8"))
        t1 = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_inlegalbert_trial.json").read_text(encoding="utf-8"))
        t2 = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_dslim_trial.json").read_text(encoding="utf-8"))
        self.assertEqual([(item["example_id"], item["text"]) for item in gold["examples"]], [(item["example_id"], item["text"]) for item in source["examples"]])
        self.assertEqual(sum(len(item["gold_entities"]) for item in gold["examples"]), 89)
        self.assertEqual(d0["global_exact"]["f1"], 0.787879)
        self.assertEqual(t1["decision"], "LEARNED CANDIDATE REJECTED")
        self.assertEqual(t2["decision"], "GENERAL NER CANDIDATE REJECTED")

    def test_retrieval_freeze(self) -> None:
        selected = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        decision = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_tuning_decision.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["candidate_depth"], 20)
        self.assertEqual(selected["final_top_k"], 5)
        self.assertFalse(selected["experimental_features"]["regime_ranking_enabled"])
        self.assertFalse(decision["frozen_benchmark_rerun_required"])


if __name__ == "__main__":
    unittest.main()
