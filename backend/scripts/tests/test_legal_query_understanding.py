import hashlib
import json
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from backend.app.services.legal_query_understanding import (
    QUERY_UNDERSTANDING_VERSION,
    LegalQueryUnderstanding,
    understand_legal_query,
)
from backend.app.services.legal_section_hybrid_ranking import deterministic_ranked_candidates


REPO_ROOT = Path(__file__).resolve().parents[3]


class MockCrossEncoderSectionRanker:
    def __init__(self) -> None:
        self.calls = 0

    def rank(self, query, analysis, deterministic_candidates, top_k=5):
        self.calls += 1
        ranked = list(reversed(deterministic_ranked_candidates(deterministic_candidates, top_k)))
        return [
            replace(
                item,
                rank=index,
                final_score=float(100 - index),
                semantic_score=float(100 - index),
                ranking_source="hybrid",
            )
            for index, item in enumerate(ranked, start=1)
        ]


class LegalQueryUnderstandingTests(unittest.TestCase):
    def test_schema_original_query_and_normalized_query_are_separate(self) -> None:
        query = "  Sec. 302 IPC   murder bail before Sessions Court  "
        result = understand_legal_query(query, section_ranking_mode="deterministic")
        self.assertIsInstance(result, LegalQueryUnderstanding)
        self.assertEqual(result.schema_version, QUERY_UNDERSTANDING_VERSION)
        self.assertEqual(result.query, query)
        self.assertEqual(result.analysis.original_query, query)
        self.assertEqual(result.normalized_query, "Section 302 IPC murder bail before Sessions Court")
        self.assertEqual(result.section_ranking_status, "deterministic")
        self.assertEqual(result.fallbacks_used, [])

    def test_reuses_query_analysis_and_deterministic_ner(self) -> None:
        result = understand_legal_query("Section 302 IPC murder bail before Sessions Court")
        self.assertEqual([section.section for section in result.explicit_sections], ["302"])
        self.assertEqual([statute.canonical for statute in result.explicit_statutes], ["IPC"])
        self.assertIn("homicide", result.offence_families)
        self.assertIn("deterministic_ner", {item.source for item in result.provenance})
        self.assertEqual(result.versions.ner_schema, "legalai-ner-schema-v1")
        self.assertEqual(result.legal_regime.regime, "ipc_crpc")

    def test_explicit_section_authority_and_supplementary_predictions(self) -> None:
        result = understand_legal_query("Section 302 IPC murder bail before Sessions Court")
        self.assertEqual(result.explicit_sections[0].statute, "IPC")
        self.assertEqual(result.explicit_sections[0].section, "302")
        first = result.predicted_sections[0]
        self.assertEqual((first.statute, first.section), ("IPC", "302"))
        self.assertTrue(first.protected_explicit)
        self.assertIn("predicted_sections_supplementary", result.retrieval_enrichment.priority_policy)
        prediction = result.analysis.predicted_sections[0]
        self.assertEqual(prediction.relationship_to_explicit, "supports_explicit")

    def test_new_code_and_mixed_regime_are_preserved(self) -> None:
        new_code = understand_legal_query("After July 2024, which BNS section covers murder?")
        self.assertEqual(new_code.legal_regime.regime, "mixed_or_transition")
        self.assertTrue(any(item.statute == "BNS" and item.section == "103" for item in new_code.predicted_sections))
        self.assertIn("TRANSITIONAL_LAW_CONTEXT", {warning.code for warning in new_code.warnings})

        mixed = understand_legal_query("Section 103 BNS and Section 302 IPC transition issue")
        self.assertEqual(mixed.legal_regime.regime, "mixed_or_transition")
        self.assertEqual({section.statute for section in mixed.explicit_sections}, {"BNS", "IPC"})
        self.assertTrue(any(conflict.code == "EXPLICIT_OLD_NEW_STATUTE_MIX" for conflict in mixed.conflicts))

    def test_deterministic_mode_does_not_load_learned_ranker(self) -> None:
        ranker = MockCrossEncoderSectionRanker()
        result = understand_legal_query("Section 302 IPC murder bail before Sessions Court", section_ranker=ranker)
        self.assertEqual(ranker.calls, 0)
        self.assertEqual(result.section_ranking_status, "deterministic")
        self.assertEqual(result.predicted_sections[0].ranking_source, "deterministic")

    def test_mocked_cross_encoder_mode_reorders_bounded_candidates(self) -> None:
        ranker = MockCrossEncoderSectionRanker()
        baseline = understand_legal_query("Section 302 IPC murder bail before Sessions Court")
        reranked = understand_legal_query(
            "Section 302 IPC murder bail before Sessions Court",
            section_ranking_mode="cross_encoder_protected_hybrid",
            section_ranker=ranker,
        )
        self.assertEqual(ranker.calls, 1)
        self.assertEqual(reranked.section_ranking_status, "cross_encoder_protected_hybrid")
        self.assertLessEqual(len(reranked.predicted_sections), 5)
        self.assertEqual(
            {(item.statute, item.section) for item in reranked.predicted_sections},
            {(item.statute, item.section) for item in baseline.predicted_sections},
        )
        self.assertEqual(reranked.predicted_sections[0].section, "302")
        self.assertTrue(reranked.predicted_sections[0].protected_explicit)

    def test_cross_encoder_unavailable_falls_back_with_warning(self) -> None:
        result = understand_legal_query(
            "Section 302 IPC murder bail before Sessions Court",
            section_ranking_mode="cross_encoder_protected_hybrid",
        )
        self.assertEqual(result.section_ranking_status, "fallback_deterministic")
        self.assertEqual(result.fallbacks_used, ["SECTION_RANKER_FALLBACK_DETERMINISTIC"])
        self.assertIn("SECTION_RANKER_FALLBACK_DETERMINISTIC", {warning.code for warning in result.warnings})
        self.assertEqual(result.predicted_sections[0].ranking_source, "deterministic")

    def test_negative_and_empty_queries_do_not_force_sections(self) -> None:
        civil = understand_legal_query("Property partition dispute between brothers with no criminal allegation")
        self.assertEqual(civil.predicted_sections, [])
        self.assertIn("NO_SECTION_CANDIDATES", {warning.code for warning in civil.warnings})

        empty = understand_legal_query("   ")
        self.assertEqual(empty.query, "   ")
        self.assertEqual(empty.normalized_query, "")
        self.assertEqual(empty.predicted_sections, [])

    def test_provenance_timings_retrieval_enrichment_and_serialization(self) -> None:
        result = understand_legal_query("FIR quashing for cheating under Section 420 IPC")
        payload = json.loads(result.model_dump_json())
        self.assertEqual(payload["schema_version"], QUERY_UNDERSTANDING_VERSION)
        self.assertIn("retrieval_enrichment", payload)
        self.assertEqual(payload["retrieval_enrichment"]["original_query"], result.query)
        self.assertTrue({"user_explicit", "deterministic_query_analysis", "deterministic_ner", "regime_resolver"} <= {item.source for item in result.provenance})
        self.assertGreaterEqual(result.timings.total_ms, 0.0)
        self.assertIn("cheating", result.retrieval_enrichment.offence_families)

    def test_cli_outputs_json_without_retrieval_or_model_dependency(self) -> None:
        completed = subprocess.run(
            [
                str(REPO_ROOT / ".venv/bin/python"),
                "backend/scripts/analyze_legal_query_understanding.py",
                "Section 302 IPC murder bail before Sessions Court",
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["section_ranking_status"], "deterministic")
        self.assertEqual(payload["query"], "Section 302 IPC murder bail before Sessions Court")

    def test_frozen_assets_and_selected_configs_are_unchanged(self) -> None:
        expected = {
            "backend/app/services/legal_section_prediction.py": "6dec51c45531b7f4098655266223dca93d4a8d40f5cdb44f6556c35702f27a3c",
            "data/structured/manifests/legal_section_catalog.json": "2d2c8fbf4a241d2adc6f67ce827f990976d3309cb59b7add15f6bc26d439dbef",
            "data/structured/manifests/legal_section_eval.json": "b4ac7034d534eb13dc19d512fd0b376730b860754fe4a58e71dab41f9322ae8e",
            "data/structured/manifests/legal_ner_selected_configuration.json": "45b1e3f8282e58cf99c621e4f7d8d909c3f88549b2c850310ea333cfeafaf2d9",
            "data/structured/manifests/legal_section_selected_configuration.json": "9b1b3902a30a70890edb88043c07971b10ef6796340cff92cad5ffcabdfb969e",
            "data/structured/manifests/retrieval_selected_configuration.json": "31f6ce663e76e3934ec47935174636964227d56a7eb41256ee520c0152feb7fc",
        }
        for path, digest in expected.items():
            self.assertEqual(hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
