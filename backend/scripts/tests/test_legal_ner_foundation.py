import json
import unittest
from pathlib import Path

from backend.app.schemas.legal_ner import CanonicalEntity, NER_SCHEMA_VERSION
from backend.app.services.legal_ner import (
    CANONICAL_ENTITY_TYPES,
    DisabledLegalNERModel,
    LABEL_MAPPING,
    TokenPrediction,
    canonical_entity_type,
    exact_entity_metrics,
    extract_deterministic_entities,
    merge_entities,
    reconstruct_bio_entities,
)
from backend.app.services.query_analysis import analyze_legal_query
from backend.scripts.validate_legal_ner_eval import validate_manifest


class LegalNERFoundationTests(unittest.TestCase):
    def test_canonical_taxonomy_is_small_and_versioned(self) -> None:
        self.assertEqual(NER_SCHEMA_VERSION, "legalai-ner-schema-v1")
        self.assertLessEqual(len(CANONICAL_ENTITY_TYPES), 14)
        self.assertIn("STATUTE", CANONICAL_ENTITY_TYPES)
        self.assertIn("FIR_NUMBER", CANONICAL_ENTITY_TYPES)

    def test_label_mapping_is_canonical_and_centralized(self) -> None:
        self.assertEqual(LABEL_MAPPING["B-PER"], "PERSON")
        self.assertEqual(LABEL_MAPPING["ORGANISATION"], "ORGANIZATION")
        self.assertEqual(LABEL_MAPPING["LAW"], "STATUTE")
        self.assertEqual(canonical_entity_type("I-ORG"), "ORGANIZATION")
        self.assertIsNone(canonical_entity_type("O"))

    def test_deterministic_statute_section_and_court_entities(self) -> None:
        text = "Section 302 IPC was considered by the Supreme Court."
        result = extract_deterministic_entities(text)
        spans = {(entity.entity_type, entity.text) for entity in result.entities}
        self.assertIn(("SECTION", "Section 302"), spans)
        self.assertIn(("STATUTE", "IPC"), spans)
        self.assertIn(("COURT", "Supreme Court"), spans)
        for entity in result.entities:
            self.assertEqual(text[entity.start_char : entity.end_char], entity.text)
            self.assertEqual(entity.source, "deterministic")
            self.assertTrue(entity.provenance)

    def test_deterministic_date_procedure_and_offence_entities(self) -> None:
        text = "Can anticipatory bail apply before 1 July 2024 in a murder case?"
        result = extract_deterministic_entities(text)
        spans = {(entity.entity_type, entity.text) for entity in result.entities}
        self.assertIn(("LEGAL_PROCEDURE", "anticipatory bail"), spans)
        self.assertIn(("DATE", "before 1 July 2024"), spans)
        self.assertIn(("OFFENCE", "murder"), spans)

    def test_conservative_fir_and_police_station_patterns(self) -> None:
        text = "FIR No. 137 of 2023 was registered at Gannavaram Urban Police Station."
        result = extract_deterministic_entities(text)
        spans = {(entity.entity_type, entity.text) for entity in result.entities}
        self.assertIn(("FIR_NUMBER", "FIR No. 137 of 2023"), spans)
        self.assertIn(("POLICE_STATION", "Gannavaram Urban Police Station"), spans)

    def test_case_citation_pattern(self) -> None:
        text = "The petitioner relied on AIR 1973 SC 2622."
        result = extract_deterministic_entities(text)
        self.assertIn(("CASE_CITATION", "AIR 1973 SC 2622"), {(e.entity_type, e.text) for e in result.entities})

    def test_exact_duplicate_merge_preserves_provenance(self) -> None:
        text = "IPC"
        left = entity(text, 0, 3, "STATUTE", "deterministic", 1.0)
        right = entity(text, 0, 3, "STATUTE", "model", 0.7)
        merged = merge_entities([left, right])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source, "merged")
        self.assertEqual(len(merged[0].provenance), 2)

    def test_overlap_prefers_protected_deterministic_section(self) -> None:
        text = "Section 302 IPC"
        deterministic = entity(text, 0, 11, "SECTION", "deterministic", 1.0)
        model = entity(text, 8, 15, "STATUTE", "model", 0.99)
        merged = merge_entities([model, deterministic])
        self.assertEqual([(item.entity_type, item.text) for item in merged], [("SECTION", "Section 302")])

    def test_stable_ordering(self) -> None:
        text = "IPC Section 302 Supreme Court"
        entities = [entity(text, 16, 29, "COURT"), entity(text, 0, 3, "STATUTE"), entity(text, 4, 15, "SECTION")]
        self.assertEqual([item.text for item in merge_entities(entities)], ["IPC", "Section 302", "Supreme Court"])

    def test_disabled_model_adapter_returns_empty(self) -> None:
        self.assertEqual(DisabledLegalNERModel().extract("Section 302 IPC"), [])

    def test_bio_reconstruction_merges_token_offsets(self) -> None:
        text = "Ramesh Kumar filed in Delhi High Court."
        tokens = [
            TokenPrediction("Ramesh", 0, 6, "B-PER", 0.9),
            TokenPrediction("Kumar", 7, 12, "I-PER", 0.8),
            TokenPrediction("[SEP]", None, None, "O", is_special=True),
            TokenPrediction("Delhi", 22, 27, "B-COURT", 0.9),
            TokenPrediction("High", 28, 32, "I-COURT", 0.9),
            TokenPrediction("Court", 33, 38, "I-COURT", 0.9),
        ]
        entities = reconstruct_bio_entities(tokens, text, model_name="synthetic")
        self.assertEqual([(item.entity_type, item.text) for item in entities], [("PERSON", "Ramesh Kumar"), ("COURT", "Delhi High Court")])

    def test_bioes_singleton(self) -> None:
        text = "IPC applies."
        entities = reconstruct_bio_entities([TokenPrediction("IPC", 0, 3, "S-LAW", 0.95)], text)
        self.assertEqual([(item.entity_type, item.text) for item in entities], [("STATUTE", "IPC")])

    def test_exact_metrics_and_per_type_metrics(self) -> None:
        text = "Section 302 IPC"
        predicted = [entity(text, 0, 11, "SECTION"), entity(text, 12, 15, "STATUTE")]
        gold = [entity(text, 0, 11, "SECTION"), entity(text, 12, 15, "COURT")]
        metrics = exact_entity_metrics(predicted, gold)
        self.assertEqual(metrics["overall"]["precision"], 0.5)
        self.assertEqual(metrics["overall"]["recall"], 0.5)
        self.assertEqual(metrics["per_type"]["SECTION"]["f1"], 1.0)
        self.assertEqual(metrics["per_type"]["STATUTE"]["false_positive"], 1)
        self.assertEqual(metrics["per_type"]["COURT"]["false_negative"], 1)

    def test_empty_predictions_and_empty_gold_metrics(self) -> None:
        metrics = exact_entity_metrics([], [])
        self.assertEqual(metrics["overall"]["precision"], 0.0)
        self.assertEqual(metrics["overall"]["recall"], 0.0)
        self.assertEqual(metrics["overall"]["f1"], 0.0)

    def test_query_analysis_compatibility_keeps_predicted_sections_empty(self) -> None:
        analysis = analyze_legal_query("Section 302 IPC in Supreme Court")
        result = extract_deterministic_entities(analysis.original_query)
        self.assertEqual(analysis.predicted_sections, [])
        self.assertTrue(result.entities)

    def test_eval_manifest_pending_and_valid(self) -> None:
        root = Path(__file__).resolve().parents[3]
        payload = json.loads((root / "data/structured/manifests/legal_ner_eval.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["examples"]), 36)
        self.assertEqual({item["review_status"] for item in payload["examples"]}, {"pending"})
        self.assertTrue(all(item["gold_entities"] == [] for item in payload["examples"]))
        self.assertEqual(validate_manifest(), [])

    def test_retrieval_freeze_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[3]
        selected = json.loads((root / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["candidate_depth"], 20)
        self.assertEqual(selected["final_top_k"], 5)
        self.assertFalse(selected["experimental_features"]["regime_ranking_enabled"])
        self.assertFalse(selected["experimental_features"]["query_expansion_enabled"])
        self.assertFalse(selected["experimental_features"]["metadata_reranking_enabled"])


def entity(text: str, start: int, end: int, entity_type: str, source: str = "deterministic", confidence: float = 1.0) -> CanonicalEntity:
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
        provenance=[],
    )


if __name__ == "__main__":
    unittest.main()
