import json
import unittest
from pathlib import Path

from backend.app.schemas.query_analysis import PredictedLegalSection
from backend.app.services.legal_section_prediction import (
    DEFAULT_TOP_K,
    PREDICTION_VERSION,
    evaluate_section_predictions,
    load_section_catalog,
    predict_legal_sections,
)
from backend.app.services.query_analysis import analyze_legal_query


REPO_ROOT = Path(__file__).resolve().parents[3]


class LegalSectionPredictionFoundationTests(unittest.TestCase):
    def test_schema_and_catalog_loading(self) -> None:
        prediction = PredictedLegalSection(
            statute="IPC",
            section="302",
            normalized_section="302",
            score=0.9,
            rank=1,
            source="deterministic_baseline",
            confidence="high",
            evidence=["homicide"],
            prediction_version=PREDICTION_VERSION,
        )
        self.assertEqual(prediction.statute, "IPC")
        catalog = load_section_catalog()
        self.assertGreaterEqual(len(catalog), 40)
        self.assertIn("IPC", {entry["statute"] for entry in catalog})
        self.assertIn("BNS", {entry["statute"] for entry in catalog})
        self.assertIn("BNSS", {entry["statute"] for entry in catalog})

    def test_regime_filtering_old_code(self) -> None:
        predictions = predict_legal_sections("murder case under IPC in 2023")
        statutes = {item.statute for item in predictions}
        self.assertIn("IPC", statutes)
        self.assertNotIn("BNS", statutes)

    def test_regime_filtering_new_code(self) -> None:
        predictions = predict_legal_sections("murder case under BNS in 2025")
        statutes = {item.statute for item in predictions}
        self.assertIn("BNS", statutes)
        self.assertNotIn("IPC", statutes)

    def test_transition_allows_old_and_new_candidates(self) -> None:
        predictions = predict_legal_sections("Section 302 IPC and Section 103 BNS transition issue for murder")
        statutes = {item.statute for item in predictions}
        self.assertIn("IPC", statutes)
        self.assertIn("BNS", statutes)

    def test_explicit_section_guardrail(self) -> None:
        analysis = analyze_legal_query("Section 438 CrPC anticipatory bail in cheating FIR")
        explicit = {(item.statute, item.section) for item in analysis.explicit_sections}
        self.assertIn(("CrPC", "438"), explicit)
        supports = [item for item in analysis.predicted_sections if item.statute == "CrPC" and item.section == "438"]
        self.assertTrue(supports)
        self.assertEqual(supports[0].relationship_to_explicit, "supports_explicit")
        self.assertTrue(all(item.source == "deterministic_baseline" for item in analysis.predicted_sections))

    def test_multi_label_top_k_and_stable_ranking(self) -> None:
        first = predict_legal_sections("robbery with hurt and criminal conspiracy under IPC")
        second = predict_legal_sections("robbery with hurt and criminal conspiracy under IPC")
        self.assertLessEqual(len(first), DEFAULT_TOP_K)
        self.assertGreaterEqual(len(first), 3)
        self.assertEqual([item.model_dump() for item in first], [item.model_dump() for item in second])

    def test_query_analysis_integration_and_provenance(self) -> None:
        analysis = analyze_legal_query("false promise cheating and criminal breach of trust")
        self.assertTrue(analysis.predicted_sections)
        self.assertTrue(all(item.prediction_version == PREDICTION_VERSION for item in analysis.predicted_sections))
        self.assertTrue(all(item.evidence for item in analysis.predicted_sections))

    def test_pending_eval_manifest(self) -> None:
        payload = json.loads((REPO_ROOT / "data/structured/manifests/legal_section_eval.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "legalai-section-eval-v1")
        self.assertEqual(len(payload["examples"]), 36)
        self.assertEqual({item["review_status"] for item in payload["examples"]}, {"pending"})
        self.assertTrue(all(item["gold_sections"] == [] for item in payload["examples"]))
        queries = " ".join(item["query"].casefold() for item in payload["examples"])
        for marker in ["ipc", "crpc", "bns", "bnss", "transition", "quashing", "default bail"]:
            self.assertIn(marker, queries)

    def test_future_metrics_for_multilabel_gold(self) -> None:
        predicted = predict_legal_sections("cheating and criminal breach of trust under IPC")
        gold = [
            {"statute": "IPC", "section": "420", "relevance": "primary"},
            {"statute": "IPC", "section": "406", "relevance": "relevant"},
        ]
        metrics = evaluate_section_predictions(predicted, gold)
        self.assertIn("precision_at_1", metrics)
        self.assertIn("ndcg_at_5", metrics)
        self.assertGreater(metrics["recall_at_5"], 0)

    def test_negative_query_returns_no_section_candidates(self) -> None:
        self.assertEqual(predict_legal_sections("certified copy application format"), [])

    def test_no_query_id_rules(self) -> None:
        source = (REPO_ROOT / "backend/app/services/legal_section_prediction.py").read_text(encoding="utf-8")
        self.assertNotIn("sec-q", source)

    def test_retrieval_and_ner_freezes(self) -> None:
        retrieval = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        ner = json.loads((REPO_ROOT / "data/structured/manifests/legal_ner_selected_configuration.json").read_text(encoding="utf-8"))
        self.assertEqual(retrieval["candidate_depth"], 20)
        self.assertFalse(retrieval["experimental_features"]["regime_ranking_enabled"])
        self.assertEqual(ner["mode"], "deterministic")
        self.assertIsNone(ner["learned_model"])
        self.assertFalse(ner["hybrid_enabled"])


if __name__ == "__main__":
    unittest.main()
