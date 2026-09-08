import unittest
from pathlib import Path
import json

from backend.app.services.query_analysis import ANALYSIS_VERSION, analyze_legal_query


class QueryAnalysisFoundationTests(unittest.TestCase):
    def test_original_query_preserved_and_normalized(self) -> None:
        query = "  Can I get bail under Sec. 438   CrPC? "
        analysis = analyze_legal_query(query)
        self.assertEqual(analysis.original_query, query)
        self.assertEqual(analysis.normalized_query, "Can I get bail under Section 438 CrPC?")

    def test_statute_detection(self) -> None:
        query = "IPC CrPC BNS BNSS NDPS Act POCSO Act SC/ST Act Indian Evidence Act"
        analysis = analyze_legal_query(query)
        self.assertEqual(
            [statute.canonical for statute in analysis.explicit_statutes],
            ["IPC", "CrPC", "BNS", "BNSS", "NDPS Act", "POCSO Act", "SC/ST Act", "Evidence Act"],
        )

    def test_section_extraction_and_statute_association(self) -> None:
        analysis = analyze_legal_query("Sections 406 and 420 IPC with Section 438 CrPC")
        sections = [(section.section, section.statute, section.source) for section in analysis.explicit_sections]
        self.assertIn(("406", "IPC", "explicit"), sections)
        self.assertIn(("420", "IPC", "explicit"), sections)
        self.assertIn(("438", "CrPC", "explicit"), sections)

    def test_subsection_extraction(self) -> None:
        analysis = analyze_legal_query("Sections 108, 352, 351(3) BNS")
        sections = [(section.section, section.statute) for section in analysis.explicit_sections]
        self.assertIn(("351(3)", "BNS"), sections)

    def test_ambiguous_section_safety(self) -> None:
        analysis = analyze_legal_query("Section 302 and anticipatory bail")
        self.assertEqual(analysis.explicit_sections[0].statute, None)
        self.assertIn("section_without_explicit_statute", analysis.warnings)
        self.assertEqual(analysis.predicted_sections, [])

    def test_date_and_transition_phrase_extraction(self) -> None:
        analysis = analyze_legal_query("offence before 1 July 2024 and after commencement of new criminal laws")
        self.assertTrue(any(item.relation == "before" and item.normalized_date == "2024-07-01" for item in analysis.dates))
        self.assertTrue(any(item.relation == "after" and item.normalized_date == "2024-07-01" for item in analysis.dates))

    def test_court_extraction(self) -> None:
        analysis = analyze_legal_query("Delhi High Court petition after trial court order")
        courts = [(court.court_level, court.value) for court in analysis.court_mentions]
        self.assertIn(("high_court", "Delhi High Court"), courts)
        self.assertIn(("district_court", "trial court"), courts)

    def test_procedural_posture(self) -> None:
        analysis = analyze_legal_query("anticipatory bail and FIR quashing in criminal appeal")
        self.assertEqual([item.normalized for item in analysis.procedural_posture], ["anticipatory_bail", "fir_quashing", "criminal_appeal"])

    def test_offence_family_hints_and_multi_family_warning(self) -> None:
        analysis = analyze_legal_query("A minor was lured away from her parents and sexually assaulted.")
        families = [item.normalized for item in analysis.offence_family_hints]
        self.assertIn("kidnapping", families)
        self.assertIn("sexual_offences", families)
        self.assertIn("multiple_offence_families", analysis.warnings)

    def test_fixture_a_bail_crpc_ipc(self) -> None:
        analysis = analyze_legal_query("Can I get anticipatory bail under Section 438 CrPC for a 2023 IPC case?")
        self.assertEqual({s.canonical for s in analysis.explicit_statutes}, {"CrPC", "IPC"})
        self.assertIn(("438", "CrPC"), [(s.section, s.statute) for s in analysis.explicit_sections])
        self.assertIn("anticipatory_bail", [item.normalized for item in analysis.procedural_posture])
        self.assertEqual(analysis.legal_regime, "ipc_crpc")

    def test_fixture_b_transition(self) -> None:
        analysis = analyze_legal_query("Which BNSS provision applies to an IPC offence committed before 1 July 2024?")
        self.assertEqual({s.canonical for s in analysis.explicit_statutes}, {"BNSS", "IPC"})
        self.assertEqual(analysis.legal_regime, "mixed_or_transition")
        self.assertIn("conflicting_old_new_statutes", analysis.warnings)

    def test_fixture_c_dowry_no_invented_section(self) -> None:
        analysis = analyze_legal_query("My husband and in-laws are harassing me for dowry.")
        self.assertIn("dowry", [item.normalized for item in analysis.offence_family_hints])
        self.assertEqual(analysis.explicit_sections, [])
        self.assertEqual(analysis.legal_regime, "unknown")

    def test_fixture_d_entrustment_no_invented_section(self) -> None:
        analysis = analyze_legal_query("Money was entrusted to a business partner and he dishonestly kept it.")
        self.assertIn("criminal_breach_of_trust", [item.normalized for item in analysis.offence_family_hints])
        self.assertEqual(analysis.predicted_sections, [])

    def test_regime_resolver_reuse_and_model_fields_empty(self) -> None:
        analysis = analyze_legal_query("BNS offence under BNSS in 2025")
        self.assertEqual(analysis.legal_regime, "bns_bnss")
        self.assertEqual(analysis.entities, [])
        self.assertEqual(analysis.predicted_sections, [])

    def test_stable_deterministic_output_and_version(self) -> None:
        first = analyze_legal_query("murder case in Supreme Court").model_dump()
        second = analyze_legal_query("murder case in Supreme Court").model_dump()
        self.assertEqual(first, second)
        self.assertEqual(first["analysis_version"], ANALYSIS_VERSION)

    def test_frozen_retrieval_selection_remains_disabled(self) -> None:
        root = Path(__file__).resolve().parents[3]
        selected = json.loads((root / "data/structured/manifests/retrieval_selected_configuration.json").read_text(encoding="utf-8"))
        decision = json.loads((root / "data/structured/manifests/retrieval_tuning_decision.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["experimental_features"], {
            "regime_ranking_enabled": False,
            "query_expansion_enabled": False,
            "metadata_reranking_enabled": False,
        })
        self.assertEqual(decision["final_decision"], "RETAIN_UNTUNED_HYBRID_RERANK")
        self.assertFalse(decision["further_phase0_retrieval_tuning"])
        self.assertFalse(decision["frozen_benchmark_rerun_required"])


if __name__ == "__main__":
    unittest.main()
