import json
import tempfile
import unittest
from pathlib import Path

from backend.app.schemas.legal_ner import CanonicalEntity, EntityProvenance
from backend.app.services.hybrid_legal_ner import (
    DEFAULT_NER_MODE,
    PROTECTED_DETERMINISTIC_TYPES,
    HybridMergeConfig,
    merge_hybrid_entities,
)
from backend.scripts.evaluate_hybrid_legal_ner import PREDICTION_TEMPLATE_PATH, evaluate_prediction_manifest, validate_prediction_manifest


REPO_ROOT = Path(__file__).resolve().parents[3]


class HybridLegalNERDesignTests(unittest.TestCase):
    def test_protected_deterministic_type_priority(self) -> None:
        deterministic = [entity("Section 302 IPC", 0, 11, "SECTION", "deterministic")]
        learned = [entity("Section 302 IPC", 8, 15, "STATUTE", "model", confidence=0.99)]
        result = merge_hybrid_entities(deterministic, learned, HybridMergeConfig(mode="hybrid"))
        self.assertEqual([(item.text, item.entity_type) for item in result.entities], [("Section 302", "SECTION")])
        self.assertEqual(result.diagnostics.learned_suppressed_due_to_protected_overlap, 1)

    def test_learned_person_organization_location_insertion(self) -> None:
        text = "Ramesh Kumar met Alpha Traders in Chennai."
        learned = [
            entity(text, 0, 12, "PERSON", "model"),
            entity(text, 17, 30, "ORGANIZATION", "model"),
            entity(text, 34, 41, "LOCATION", "model"),
        ]
        result = merge_hybrid_entities([], learned, HybridMergeConfig(mode="hybrid"))
        self.assertEqual([(item.entity_type, item.text) for item in result.entities], [("PERSON", "Ramesh Kumar"), ("ORGANIZATION", "Alpha Traders"), ("LOCATION", "Chennai")])
        self.assertEqual(result.diagnostics.learned_inserted_count, 3)

    def test_duplicate_removal_preserves_provenance(self) -> None:
        text = "Ramesh"
        left = entity(text, 0, 6, "PERSON", "model")
        right = entity(text, 0, 6, "PERSON", "model")
        result = merge_hybrid_entities([], [left, right], HybridMergeConfig(mode="hybrid"))
        self.assertEqual(len(result.entities), 1)
        self.assertEqual(result.diagnostics.exact_duplicates_removed, 1)
        self.assertEqual(len(result.entities[0].provenance), 2)

    def test_same_span_conflict_uses_type_priority(self) -> None:
        text = "accused"
        deterministic = [entity(text, 0, 7, "LEGAL_ROLE", "deterministic")]
        learned = [entity(text, 0, 7, "PERSON", "model")]
        result = merge_hybrid_entities(deterministic, learned, HybridMergeConfig(mode="hybrid"))
        self.assertEqual([(item.entity_type, item.text) for item in result.entities], [("LEGAL_ROLE", "accused")])
        self.assertEqual(result.diagnostics.same_span_conflicts, 1)

    def test_overlapping_shared_boundary_improvement(self) -> None:
        text = "Supreme Court of India"
        deterministic = [entity(text, 0, 13, "COURT", "deterministic")]
        learned = [entity(text, 0, 22, "COURT", "model")]
        result = merge_hybrid_entities(deterministic, learned, HybridMergeConfig(mode="hybrid"))
        self.assertEqual([(item.entity_type, item.text, item.source) for item in result.entities], [("COURT", "Supreme Court of India", "merged")])

    def test_confidence_threshold(self) -> None:
        text = "Ramesh"
        learned = [entity(text, 0, 6, "PERSON", "model", confidence=0.2)]
        result = merge_hybrid_entities([], learned, HybridMergeConfig(mode="hybrid", min_confidence=0.7))
        self.assertEqual(result.entities, [])
        self.assertEqual(result.diagnostics.learned_below_threshold, 1)

    def test_stable_ordering(self) -> None:
        text = "IPC Ramesh"
        result = merge_hybrid_entities(
            [entity(text, 0, 3, "STATUTE", "deterministic")],
            [entity(text, 4, 10, "PERSON", "model")],
            HybridMergeConfig(mode="hybrid"),
        )
        self.assertEqual([item.text for item in result.entities], ["IPC", "Ramesh"])

    def test_prediction_manifest_template_validates(self) -> None:
        self.assertEqual(validate_prediction_manifest(PREDICTION_TEMPLATE_PATH), [])

    def test_prediction_manifest_rejects_bad_source_and_offsets(self) -> None:
        payload = json.loads(PREDICTION_TEMPLATE_PATH.read_text(encoding="utf-8"))
        payload["examples"][0]["predicted_entities"] = [{"text": "Section 303", "entity_type": "SECTION", "start_char": 0, "end_char": 11, "confidence": 0.9, "source": "deterministic"}]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            errors = "\n".join(validate_prediction_manifest(path))
        self.assertIn("source must be model", errors)
        self.assertIn("text does not match exact source span", errors)

    def test_hybrid_metric_calculation_no_model_default_path(self) -> None:
        result = evaluate_prediction_manifest(PREDICTION_TEMPLATE_PATH)
        self.assertEqual(result["systems"]["learned"]["exact"]["true_positive"], 0)
        self.assertEqual(result["systems"]["hybrid"]["exact"], result["systems"]["deterministic"]["exact"])
        self.assertEqual(result["hybrid_value"]["learned_suppressed_due_to_protected_overlap"], 0)

    def test_default_mode_is_deterministic(self) -> None:
        self.assertEqual(DEFAULT_NER_MODE, "deterministic")
        self.assertIn("LEGAL_PROCEDURE", PROTECTED_DETERMINISTIC_TYPES)
        config_text = (REPO_ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
        env_text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn('legal_ner_mode: str = "deterministic"', config_text)
        self.assertIn("LEGAL_NER_MODE=deterministic", env_text)

    def test_query_analysis_compatibility_and_retrieval_freeze(self) -> None:
        selected = json.loads((REPO_ROOT / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["candidate_depth"], 20)
        self.assertEqual(selected["final_top_k"], 5)
        self.assertFalse(selected["experimental_features"]["regime_ranking_enabled"])


def entity(text: str, start: int, end: int, entity_type: str, source: str, confidence: float = 0.95) -> CanonicalEntity:
    span = text[start:end]
    return CanonicalEntity(
        text=span,
        normalized_text=span.casefold(),
        entity_type=entity_type,
        start_char=start,
        end_char=end,
        confidence=confidence,
        source=source,
        extractor=f"{source}.fixture",
        model_name="fixture-model" if source == "model" else None,
        provenance=[EntityProvenance(source=source, extractor=f"{source}.fixture", model_name="fixture-model" if source == "model" else None, confidence=confidence)],
    )


if __name__ == "__main__":
    unittest.main()
